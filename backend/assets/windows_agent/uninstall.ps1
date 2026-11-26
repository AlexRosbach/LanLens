# LanLens Windows agent uninstall, invoked from Windows Installed apps.
$ErrorActionPreference = 'Stop'
if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $process = Start-Process -FilePath $ps -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $PSCommandPath) -Verb RunAs -Wait -PassThru
    exit $process.ExitCode
}
$installDir = Join-Path $env:ProgramData 'LanLensAgent'
$configFile = Join-Path $installDir 'agent.json'
$registry = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\LanLensAgent'
if (Get-Service LanLensAgent -ErrorAction SilentlyContinue) {
    Stop-Service LanLensAgent -Force
    & sc.exe delete LanLensAgent | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not remove the LanLens Agent service.' }
}
# Revoke the local identity on the server; retain the device and inventory.
# Network failure never prevents local removal; report the manual action.
$revoked = $false
if (Test-Path $configFile) {
    try {
        $cfg = Get-Content -Raw $configFile | ConvertFrom-Json
        $uri = [Uri]($cfg.server_url.TrimEnd('/') + '/api/agents/unenroll')
        if ($uri.Scheme -ne 'https' -or $uri.UserInfo) { throw 'HTTPS required.' }
        $request = [Net.HttpWebRequest][Net.WebRequest]::Create($uri)
        $request.Method = 'POST'
        $request.AllowAutoRedirect = $false
        $request.ContentLength = 0
        $request.Timeout = 10000
        if ($cfg.certificate_sha256 -or $cfg.trust_untrusted_certificate -eq $true) {
            Add-Type -TypeDefinition @'
using System;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
public static class LanLensUninstallTls {
    public static RemoteCertificateValidationCallback Callback(string pin, bool allowUntrusted) {
        return delegate(object sender, X509Certificate cert, X509Chain chain, SslPolicyErrors errors) {
            if (cert == null) return false;
            if (String.IsNullOrEmpty(pin)) return allowUntrusted;
            if ((errors & ~SslPolicyErrors.RemoteCertificateChainErrors) != SslPolicyErrors.None) return false;
            using (var leaf = new X509Certificate2(cert))
            using (var sha = SHA256.Create()) {
                return DateTime.UtcNow >= leaf.NotBefore.ToUniversalTime() && DateTime.UtcNow <= leaf.NotAfter.ToUniversalTime()
                    && String.Equals(BitConverter.ToString(sha.ComputeHash(leaf.RawData)).Replace("-", ""), pin, StringComparison.OrdinalIgnoreCase);
            }
        };
    }
}
'@
            $request.ServerCertificateValidationCallback = [LanLensUninstallTls]::Callback([string]$cfg.certificate_sha256, ($cfg.trust_untrusted_certificate -eq $true))
        }
        $request.Headers['Authorization'] = "Bearer $($cfg.agent_id).$($cfg.agent_secret)"
        $response = $request.GetResponse()
        try { $revoked = ([int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 300) } finally { $response.Dispose() }
    } catch { Write-Warning 'Could not revoke the agent on LanLens. Revoke its installation token manually.' }
}
if (-not $revoked) {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show('The local agent will be removed. Revoke its installation token in LanLens before enrolling again.', 'LanLens Agent') | Out-Null
    } catch { Write-Warning 'Revoke the old installation token in LanLens.' }
}
# Do not delete unrelated files. Only the known agent files and owned log archives.
foreach ($name in @('LanLensAgent.exe','LanLensAgent.cs','LanLensAgent.new.exe','LanLensAgent.exe.bak','agent.json','agent.json.tmp','agent.log','uninstall.ps1')) {
    Remove-Item -LiteralPath (Join-Path $installDir $name) -Force -ErrorAction SilentlyContinue
}
Get-ChildItem -LiteralPath $installDir -Filter 'agent-*.log' -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^agent-\d{4}-\d{2}-\d{2}\.log$' } | Remove-Item -Force
if (Test-Path $installDir) {
    if (-not (Get-ChildItem -LiteralPath $installDir -Force)) { Remove-Item -LiteralPath $installDir -Force }
}
if ((Test-Path $configFile) -or (Test-Path (Join-Path $installDir 'LanLensAgent.exe'))) { throw 'Agent files could not be removed. Retry uninstall as administrator.' }
Remove-Item -Path $registry -Force -ErrorAction SilentlyContinue
