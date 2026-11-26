# Execute the installer with network, SCM and app registration boundaries mocked.
# Filesystem writes and compilation use an isolated real temporary directory.
$ErrorActionPreference = 'Stop'
$installerPath = Join-Path $PSScriptRoot '..\assets\windows_agent\install.ps1'
$source = [IO.File]::ReadAllText((Resolve-Path $installerPath))
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Installer did not parse.' }

$requestStub = @'
function Invoke-LanLensInstallerRequest {
    param([string]$Uri, [string]$Body)
    $state = $global:LanLensInstallerTest
    if ($Uri.EndsWith('/api/agents/enroll')) {
        $state.EnrollCalls++
        if ($state.EnrollCalls -gt 1) { throw 'Consumed enrollment token was used again (HTTP 409).' }
        return '{"agent_id":"fixture-agent","agent_secret":"fixture-secret"}'
    }
    if ($Uri.EndsWith('/LanLensAgent.cs')) {
        $state.Downloads++
        return ('public static class Entry { public static void Main() { System.Console.WriteLine(' + $state.Downloads + '); } }')
    }
    if ($Uri.EndsWith('/uninstall.ps1')) { return '# fixture uninstaller' }
    throw 'Unexpected download endpoint.'
}
'@
$registrationStub = @'
function Register-LanLensUninstaller {
    $global:LanLensInstallerTest.Registrations++
    if ($global:LanLensInstallerTest.FailRegistrationOnce) {
        $global:LanLensInstallerTest.FailRegistrationOnce = $false
        throw 'Fixture registration failure.'
    }
}
'@
$replacements = @{ 'Invoke-LanLensInstallerRequest' = $requestStub; 'Register-LanLensUninstaller' = $registrationStub }
$functions = @($ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $replacements.ContainsKey($node.Name) }, $true))
if ($functions.Count -ne $replacements.Count) { throw 'Installer boundary functions were not found.' }
foreach ($function in ($functions | Sort-Object { $_.Extent.StartOffset } -Descending)) {
    $source = $source.Remove($function.Extent.StartOffset, $function.Extent.EndOffset - $function.Extent.StartOffset).Insert($function.Extent.StartOffset, $replacements[$function.Name])
}
$installer = [ScriptBlock]::Create($source)

function Get-Service {
    [CmdletBinding()] param([string]$Name)
    if ($global:LanLensInstallerTest.HasService) { [pscustomobject]@{ Name = 'LanLensAgent' } }
}
function Stop-Service {
    [CmdletBinding()] param([string]$Name, [switch]$Force)
    $global:LanLensInstallerTest.Running = $false
}
function Start-Service {
    [CmdletBinding()] param([string]$Name)
    $state = $global:LanLensInstallerTest
    if (-not $state.HasService) { throw 'Fixture service is missing.' }
    if ($state.FailStartOnce) { $state.FailStartOnce = $false; throw 'Fixture start failure.' }
    $state.Running = $true
}
function sc.exe {
    param([string]$Operation, [Parameter(ValueFromRemainingArguments = $true)][string[]]$Remaining)
    $global:LASTEXITCODE = 0
    if ($Operation -eq 'create') { $global:LanLensInstallerTest.HasService = $true }
    elseif ($Operation -notin @('description', 'failure')) { throw 'Unexpected service command.' }
}
function icacls { $global:LASTEXITCODE = 0 }
function Get-CimInstance {
    param([string]$ClassName)
    if ($ClassName -eq 'Win32_NetworkAdapterConfiguration') {
        return [pscustomobject]@{ IPEnabled = $true; MACAddress = '00:11:22:33:44:55'; IPAddress = @('192.0.2.10') }
    }
    if ($ClassName -eq 'Win32_OperatingSystem') {
        return [pscustomobject]@{ Caption = 'Fixture OS'; Version = '1'; BuildNumber = '1' }
    }
    throw 'Unexpected collector.'
}
function Assert-True([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Assert-Fails([scriptblock]$Action, [string]$Expected) {
    $failure = $null
    try { & $Action } catch { $failure = $_ }
    Assert-True ($null -ne $failure) ('Expected failure: ' + $Expected)
    Assert-True ($failure.Exception.Message.Contains($Expected)) ('Unexpected failure: ' + $failure.Exception.Message)
}

$originalProgramData = $env:ProgramData
$testDirectory = Join-Path ([IO.Path]::GetTempPath()) ('LanLens-installer-test-' + [Guid]::NewGuid().ToString('N'))
$global:LanLensInstallerTest = @{
    EnrollCalls = 0; Downloads = 0; Registrations = 0; HasService = $false
    Running = $false; FailStartOnce = $false; FailRegistrationOnce = $false
}
try {
    $env:ProgramData = $testDirectory
    $arguments = @{ ServerUrl = 'https://lanlens.example.test'; EnrollmentToken = 'single-use-fixture-token'; IntervalMinutes = 17; TrustUntrustedCertificate = $true }
    & $installer @arguments
    $configFile = Join-Path $testDirectory 'LanLensAgent\agent.json'
    $exeFile = Join-Path $testDirectory 'LanLensAgent\LanLensAgent.exe'
    Assert-True ($global:LanLensInstallerTest.EnrollCalls -eq 1) 'First installation did not enroll exactly once.'
    Assert-True $global:LanLensInstallerTest.Running 'First installation did not start.'

    # Existing configuration may contain a progressed sequence and a legacy pin.
    $config = Get-Content -Raw $configFile | ConvertFrom-Json
    $config.sequence = 41
    $config.trust_untrusted_certificate = $false
    $config | Add-Member -NotePropertyName certificate_sha256 -NotePropertyValue ('a' * 64)
    $config | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 $configFile
    $savedConfig = [IO.File]::ReadAllText($configFile)
    $arguments.IntervalMinutes = 99

    & $installer @arguments
    Assert-True ($global:LanLensInstallerTest.EnrollCalls -eq 1) 'Ordinary rerun reenrolled the existing agent.'
    Assert-True ([IO.File]::ReadAllText($configFile) -ceq $savedConfig) 'Ordinary rerun changed saved configuration.'
    Assert-True ($global:LanLensInstallerTest.Registrations -eq 2) 'Ordinary rerun did not refresh Windows app registration.'

    $global:LanLensInstallerTest.HasService = $false
    Remove-Item $exeFile
    & $installer @arguments
    Assert-True ($global:LanLensInstallerTest.EnrollCalls -eq 1) 'Repair reenrolled the existing agent.'
    Assert-True ($global:LanLensInstallerTest.HasService -and $global:LanLensInstallerTest.Running -and (Test-Path $exeFile)) 'Missing service/executable was not repaired.'
    Assert-True ([IO.File]::ReadAllText($configFile) -ceq $savedConfig) 'Repair changed saved configuration.'

    $previousExe = [Convert]::ToBase64String([IO.File]::ReadAllBytes($exeFile))
    $global:LanLensInstallerTest.FailStartOnce = $true
    Assert-Fails { & $installer @arguments } 'Fixture start failure.'
    Assert-True ([Convert]::ToBase64String([IO.File]::ReadAllBytes($exeFile)) -ceq $previousExe) 'Failed start did not restore previous executable.'
    Assert-True $global:LanLensInstallerTest.Running 'Previous agent was not restarted after rollback.'
    Assert-True ([IO.File]::ReadAllText($configFile) -ceq $savedConfig) 'Rollback changed saved configuration.'

    $global:LanLensInstallerTest.FailRegistrationOnce = $true
    Assert-Fails { & $installer @arguments } 'Fixture registration failure.'
    Assert-True ([Convert]::ToBase64String([IO.File]::ReadAllBytes($exeFile)) -ceq $previousExe) 'Registration failure did not restore previous executable.'
    Assert-True $global:LanLensInstallerTest.Running 'Registration failure left the old service stopped.'

    $downloadCount = $global:LanLensInstallerTest.Downloads
    $arguments.ServerUrl = 'https://other.example.test'
    Assert-Fails { & $installer @arguments } 'Installation URL must match'
    $arguments.ServerUrl = 'https://lanlens.example.test'
    '{"server_url":"https://lanlens.example.test","agent_id":"fixture-agent"}' | Set-Content -Encoding UTF8 $configFile
    Assert-Fails { & $installer @arguments } 'no usable enrollment'
    Remove-Item $configFile
    Assert-Fails { & $installer @arguments } 'configuration is missing'
    Assert-True ($global:LanLensInstallerTest.EnrollCalls -eq 1 -and $global:LanLensInstallerTest.Downloads -eq $downloadCount) 'Invalid local identity triggered an enrollment or download.'
    Write-Host 'PASS: first install, normal rerun, repair, rollback, registration failure and invalid local identity.'
} finally {
    $env:ProgramData = $originalProgramData
    Remove-Item -LiteralPath $testDirectory -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Variable LanLensInstallerTest -Scope Global -ErrorAction SilentlyContinue
}
