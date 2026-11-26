# LanLens Windows agent uninstall, invoked from Windows Installed apps.
$ErrorActionPreference = 'Stop'
if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $process = Start-Process -FilePath $ps -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $PSCommandPath) -Verb RunAs -Wait -PassThru
    exit $process.ExitCode
}
$installDir = Join-Path $env:ProgramData 'LanLensAgent'
$configFile = Join-Path $installDir 'agent.json'
$registry = 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\LanLensAgent'
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
        $request.ReadWriteTimeout = 10000
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
# Keep the uninstall script and app registration until all other owned files
# have gone, so a locked executable does not leave a broken retry command.
$ownedFiles = @('LanLensAgent.exe','LanLensAgent.cs','LanLensAgent.new.exe','LanLensAgent.exe.bak','uninstall.new.ps1','agent.json','agent.json.tmp','agent.log')
foreach ($name in $ownedFiles) {
    $path = Join-Path $installDir $name
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force -ErrorAction Stop }
}
Get-ChildItem -LiteralPath $installDir -Filter 'agent-*.log' -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^agent-\d{4}-\d{2}-\d{2}\.log$' } | Remove-Item -Force -ErrorAction Stop
# The explicit view also removes app entries written by older 32-bit installers.
$views = if ([Environment]::Is64BitOperatingSystem) { @([Microsoft.Win32.RegistryView]::Registry64, [Microsoft.Win32.RegistryView]::Registry32) } else { @([Microsoft.Win32.RegistryView]::Registry32) }
foreach ($view in $views) {
    $hive = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, $view)
    try { $hive.DeleteSubKeyTree($registry, $false) } finally { $hive.Dispose() }
}
# Only remove this script after successful cleanup. Any unrelated files remain.
Remove-Item -LiteralPath (Join-Path $installDir 'uninstall.ps1') -Force -ErrorAction SilentlyContinue
if ((Test-Path $installDir) -and -not (Get-ChildItem -LiteralPath $installDir -Force)) { Remove-Item -LiteralPath $installDir -Force }
