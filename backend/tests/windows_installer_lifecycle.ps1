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
    param([string]$Uri, [string]$Body, [string]$Authorization, [string]$OutFile)
    $state = $global:LanLensInstallerTest
    if ($Uri.EndsWith('/api/agents/identity')) {
        $state.IdentityChecks++
        if ($state.IdentityStatus -ne 200) { throw (New-LifecycleHttpError $state.IdentityStatus) }
        if ($Authorization -cne ('Bearer ' + $state.ActiveId + '.' + $state.ActiveSecret)) { throw (New-LifecycleHttpError 401) }
        return (@{ status = 'active'; agent_id = $state.ActiveId; primary_mac = $state.IdentityMac; platform = $state.IdentityPlatform; last_sequence = 0 } | ConvertTo-Json -Compress)
    }
    if ($Uri.EndsWith('/api/agents/enroll')) {
        $state.EnrollCalls++
        if ($state.ForceEnrollStatus) { throw (New-LifecycleHttpError $state.ForceEnrollStatus) }
        $payload = $Body | ConvertFrom-Json
        if (-not $state.ValidTokens.ContainsKey($payload.token) -or $state.ConsumedTokens.ContainsKey($payload.token)) { throw (New-LifecycleHttpError 401) }
        $state.ConsumedTokens[$payload.token] = $true
        $state.EnrollAccepted++
        $state.ActiveId = 'fixture-agent-' + $state.EnrollAccepted
        $state.ActiveSecret = 'fixture-secret-' + $state.EnrollAccepted
        $state.IdentityStatus = 200
        $state.LastEnrollMac = $payload.primary_mac
        return (@{ agent_id = $state.ActiveId; agent_secret = $state.ActiveSecret } | ConvertTo-Json -Compress)
    }
    if ($Uri.EndsWith('/LanLensAgent.ico') -and $OutFile) { Copy-Item -LiteralPath $state.IconPath -Destination $OutFile; return }
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
$processStub = @'
function Get-LanLensAgentProcess {
    $process = New-Object PSObject
    $process | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {
        param($Milliseconds)
        $global:LanLensInstallerTest.WaitCalls++
        if ($global:LanLensInstallerTest.FailWaitOnce) { $global:LanLensInstallerTest.FailWaitOnce = $false; return $false }
        return $true
    }
    $process | Add-Member -MemberType ScriptMethod -Name Dispose -Value { }
    return $process
}
'@
$replacements = @{ 'Invoke-LanLensInstallerRequest' = $requestStub; 'Register-LanLensUninstaller' = $registrationStub; 'Get-LanLensAgentProcess' = $processStub }
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
    if ($global:LanLensInstallerTest.MutateSettingsOnStop) {
        $global:LanLensInstallerTest.MutateSettingsOnStop = $false
        $path = Join-Path $env:ProgramData 'LanLensAgent\agent.json'
        $latest = Get-Content -Raw $path | ConvertFrom-Json
        $latest.interval_minutes = 23
        $latest.custom_setting = 'latest-value'
        $latest | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 $path
    }
    if ($global:LanLensInstallerTest.MutateMacOnStop -or $global:LanLensInstallerTest.MutateIdentityOnStop) {
        $path = Join-Path $env:ProgramData 'LanLensAgent\agent.json'
        $latest = Get-Content -Raw $path | ConvertFrom-Json
        if ($global:LanLensInstallerTest.MutateMacOnStop) { $latest.primary_mac = '00:11:22:33:44:66' }
        if ($global:LanLensInstallerTest.MutateIdentityOnStop) { $latest.agent_id = 'another-agent' }
        $global:LanLensInstallerTest.MutateMacOnStop = $false
        $global:LanLensInstallerTest.MutateIdentityOnStop = $false
        $latest | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 $path
    }
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
function icacls {
    param([string]$Path, [Parameter(ValueFromRemainingArguments = $true)][string[]]$Options)
    $global:LanLensInstallerTest.AclCalls += [pscustomobject]@{ Path = $Path; Options = $Options }
    $global:LASTEXITCODE = 0
}
function Get-CimInstance {
    param([string]$ClassName)
    if ($ClassName -eq 'Win32_NetworkAdapterConfiguration') {
        foreach ($mac in $global:LanLensInstallerTest.AdapterMacs) { [pscustomobject]@{ IPEnabled = $true; MACAddress = $mac; IPAddress = @('192.0.2.10') } }
        return
    }
    if ($ClassName -eq 'Win32_OperatingSystem') {
        return [pscustomobject]@{ Caption = 'Fixture OS'; Version = '1'; BuildNumber = '1' }
    }
    throw 'Unexpected collector.'
}
function Assert-True([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function New-LifecycleHttpError([int]$Status) {
    $failure = New-Object System.InvalidOperationException -ArgumentList ('Fixture HTTP ' + $Status)
    $failure.Data['HttpStatusCode'] = $Status
    return $failure
}
function Assert-Fails([scriptblock]$Action, [string]$Expected) {
    $failure = $null
    try { & $Action } catch { $failure = $_ }
    Assert-True ($null -ne $failure) ('Expected failure: ' + $Expected)
    Assert-True ($failure.Exception.Message.Contains($Expected)) ('Unexpected failure: ' + $failure.Exception.Message)
}

$originalProgramData = $env:ProgramData
$testDirectory = Join-Path ([IO.Path]::GetTempPath()) ('LanLens-installer-test-' + [Guid]::NewGuid().ToString('N'))
$global:LanLensInstallerTest = @{
    EnrollCalls = 0; EnrollAccepted = 0; Downloads = 0; Registrations = 0; HasService = $false
    Running = $false; FailStartOnce = $false; FailRegistrationOnce = $false
    IdentityStatus = 200; IdentityChecks = 0; IdentityMac = '00:11:22:33:44:55'; IdentityPlatform = 'windows'
    ActiveId = ''; ActiveSecret = ''; LastEnrollMac = ''; MutateSettingsOnStop = $false
    MutateMacOnStop = $false; MutateIdentityOnStop = $false; FailWaitOnce = $false; WaitCalls = 0; ForceEnrollStatus = 0
    AdapterMacs = @('00:11:22:33:44:55')
    ValidTokens = @{ 'single-use-fixture-token' = $true; 'fresh-recovery-fixture-token' = $true; 'rollback-recovery-fixture-token' = $true }
    ConsumedTokens = @{}
    AclCalls = @()
    IconPath = (Resolve-Path (Join-Path $PSScriptRoot '..\assets\windows_agent\LanLensAgent.ico')).Path
}
try {
    $env:ProgramData = $testDirectory
    $arguments = @{ ServerUrl = 'https://lanlens.example.test'; EnrollmentToken = 'single-use-fixture-token'; IntervalMinutes = 17; TrustUntrustedCertificate = $true }
    & $installer @arguments
    $configFile = Join-Path $testDirectory 'LanLensAgent\agent.json'
    $exeFile = Join-Path $testDirectory 'LanLensAgent\LanLensAgent.exe'
    Assert-True ($global:LanLensInstallerTest.EnrollCalls -eq 1) 'First installation did not enroll exactly once.'
    Assert-True $global:LanLensInstallerTest.Running 'First installation did not start.'
    $installDirectory = Split-Path $configFile
    $installedIcon = Join-Path $installDirectory 'LanLensAgent.ico'
    Assert-True (Test-Path $installedIcon) 'The app icon was not installed.'
    Assert-True ($global:LanLensInstallerTest.AclCalls.Count -eq 2) 'Expected directory traversal and icon read ACLs.'
    foreach ($acl in $global:LanLensInstallerTest.AclCalls) {
        $users = @($acl.Options | Where-Object { $_ -like '*S-1-5-32-545*' })
        Assert-True ($users.Count -eq 1) 'Expected one explicit Users permission per icon-related ACL.'
        if ($acl.Path -eq $installDirectory) { Assert-True ($users[0] -ceq '*S-1-5-32-545:(X)') 'Directory permission must allow traverse only, without inheritance.' }
        elseif ($acl.Path -eq $installedIcon) { Assert-True ($users[0] -ceq '*S-1-5-32-545:R') 'The icon must grant read access only.' }
        else { throw 'Users permissions were applied to a private agent file.' }
    }

    # Existing configuration may contain a progressed sequence and a legacy pin.
    $config = Get-Content -Raw $configFile | ConvertFrom-Json
    $config.sequence = 41
    $config.trust_untrusted_certificate = $false
    $config | Add-Member -NotePropertyName certificate_sha256 -NotePropertyValue ('a' * 64)
    $config | Add-Member -NotePropertyName custom_setting -NotePropertyValue 'keep-this'
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

    # A missing old-server route or a temporary status failure is not revocation.
    foreach ($status in @(404, 503)) {
        $global:LanLensInstallerTest.IdentityStatus = $status
        & $installer @arguments
        Assert-True ($global:LanLensInstallerTest.EnrollCalls -eq 1) 'Unavailable identity endpoint caused reenrollment.'
        Assert-True ([IO.File]::ReadAllText($configFile) -ceq $savedConfig) 'Unavailable identity endpoint changed credentials.'
    }
    $global:LanLensInstallerTest.IdentityStatus = 200
    $global:LanLensInstallerTest.IdentityPlatform = 'linux'
    Assert-Fails { & $installer @arguments } 'another platform'
    $global:LanLensInstallerTest.IdentityPlatform = 'windows'
    $global:LanLensInstallerTest.IdentityMac = '00:11:22:33:44:99'
    Assert-Fails { & $installer @arguments } 'MAC does not match'
    $global:LanLensInstallerTest.IdentityMac = '00:11:22:33:44:55'

    $downloadCount = $global:LanLensInstallerTest.Downloads
    $arguments.ServerUrl = 'https://other.example.test'
    Assert-Fails { & $installer @arguments } 'Installation URL must match'
    $arguments.ServerUrl = 'https://lanlens.example.test'
    '{"server_url":"https://lanlens.example.test","agent_id":"fixture-agent"}' | Set-Content -Encoding UTF8 $configFile
    Assert-Fails { & $installer @arguments } 'no usable enrollment'
    Remove-Item $configFile
    Assert-Fails { & $installer @arguments } 'configuration is missing'
    Assert-True ($global:LanLensInstallerTest.EnrollCalls -eq 1 -and $global:LanLensInstallerTest.Downloads -eq $downloadCount) 'Invalid local identity triggered an enrollment or download.'
    [IO.File]::WriteAllText($configFile, $savedConfig)

    # Revocation can only be repaired with a new, unconsumed enrollment token.
    $global:LanLensInstallerTest.IdentityStatus = 401
    $arguments.Remove('EnrollmentToken')
    Assert-Fails { & $installer @arguments } 'Create a NEW installation command'
    Assert-True ($global:LanLensInstallerTest.EnrollCalls -eq 1) 'Revoked identity without a token attempted enrollment.'
    $arguments.EnrollmentToken = 'single-use-fixture-token'
    Assert-Fails { & $installer @arguments } 'Fixture HTTP 401'
    Assert-True ($global:LanLensInstallerTest.EnrollAccepted -eq 1) 'Consumed token restored a revoked identity.'
    Assert-True ([IO.File]::ReadAllText($configFile) -ceq $savedConfig) 'Rejected recovery erased the existing configuration.'

    $arguments.EnrollmentToken = 'fresh-recovery-fixture-token'
    $callsBeforeBlocked = $global:LanLensInstallerTest.EnrollCalls
    $global:LanLensInstallerTest.FailWaitOnce = $true
    Assert-Fails { & $installer @arguments } 'Timed out waiting for the previous agent process'
    Assert-True ($global:LanLensInstallerTest.EnrollCalls -eq $callsBeforeBlocked -and [IO.File]::ReadAllText($configFile) -ceq $savedConfig) 'Process wait failure changed the registration or config.'

    $global:LanLensInstallerTest.ForceEnrollStatus = 409
    Assert-Fails { & $installer @arguments } 'Fixture HTTP 409'
    $global:LanLensInstallerTest.ForceEnrollStatus = 0
    Assert-True ([IO.File]::ReadAllText($configFile) -ceq $savedConfig -and $global:LanLensInstallerTest.Running) 'Enrollment conflict did not preserve config and restart the previous service.'
    Assert-True (-not $global:LanLensInstallerTest.ConsumedTokens.ContainsKey($arguments.EnrollmentToken) -and $global:LanLensInstallerTest.EnrollAccepted -eq 1) 'Enrollment conflict consumed the fresh token or restored the identity.'

    foreach ($changedField in @('MutateMacOnStop', 'MutateIdentityOnStop')) {
        $callsBeforeBlocked = $global:LanLensInstallerTest.EnrollCalls
        $global:LanLensInstallerTest[$changedField] = $true
        Assert-Fails { & $installer @arguments } 'Agent configuration changed during installation'
        Assert-True ($global:LanLensInstallerTest.EnrollCalls -eq $callsBeforeBlocked) 'Concurrent identity or MAC change triggered enrollment.'
        [IO.File]::WriteAllText($configFile, $savedConfig)
    }

    $withoutMac = Get-Content -Raw $configFile | ConvertFrom-Json
    $withoutMac.PSObject.Properties.Remove('primary_mac')
    $withoutMac | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 $configFile
    $callsBeforeAmbiguous = $global:LanLensInstallerTest.EnrollCalls
    Assert-Fails { & $installer @arguments } 'Restore the enrolled primary_mac'
    Assert-True ($global:LanLensInstallerTest.EnrollCalls -eq $callsBeforeAmbiguous) 'Legacy recovery guessed the enrolled adapter.'
    [IO.File]::WriteAllText($configFile, $savedConfig)
    $global:LanLensInstallerTest.AdapterMacs = @('00:11:22:33:44:55')

    $global:LanLensInstallerTest.MutateSettingsOnStop = $true
    & $installer @arguments
    $recovered = Get-Content -Raw $configFile | ConvertFrom-Json
    Assert-True ($global:LanLensInstallerTest.EnrollAccepted -eq 2) 'Fresh token did not recover the registration.'
    Assert-True ($recovered.agent_id -ceq $global:LanLensInstallerTest.ActiveId -and $recovered.agent_secret -ceq $global:LanLensInstallerTest.ActiveSecret -and $recovered.sequence -eq 0) 'Recovery did not save the new identity with a new sequence.'
    Assert-True ($recovered.primary_mac -eq '00:11:22:33:44:55' -and $recovered.interval_minutes -eq 23 -and $recovered.custom_setting -eq 'latest-value') 'Recovery did not preserve latest settings and enrolled MAC.'
    Assert-True ($recovered.trust_untrusted_certificate -eq $false -and $recovered.certificate_sha256 -ceq ('a' * 64)) 'Recovery replaced saved TLS configuration.'
    Assert-True (-not (Test-Path ($configFile + '.installing'))) 'Atomic config replacement left a pending credentials file.'

    # An executable rollback must retain the newly issued, valid credentials.
    $previousExe = [Convert]::ToBase64String([IO.File]::ReadAllBytes($exeFile))
    $global:LanLensInstallerTest.IdentityStatus = 401
    $arguments.EnrollmentToken = 'rollback-recovery-fixture-token'
    $global:LanLensInstallerTest.FailStartOnce = $true
    Assert-Fails { & $installer @arguments } 'Fixture start failure.'
    $recovered = Get-Content -Raw $configFile | ConvertFrom-Json
    Assert-True ($global:LanLensInstallerTest.EnrollAccepted -eq 3 -and $recovered.agent_id -ceq $global:LanLensInstallerTest.ActiveId) 'Rollback restored the revoked identity.'
    Assert-True ([Convert]::ToBase64String([IO.File]::ReadAllBytes($exeFile)) -ceq $previousExe -and $global:LanLensInstallerTest.Running) 'Recovery rollback did not restart the previous executable.'
    Write-Host 'PASS: install/update/repair, config preservation, transient identity errors, strict token recovery and rollback.'
} finally {
    $env:ProgramData = $originalProgramData
    Remove-Item -LiteralPath $testDirectory -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Variable LanLensInstallerTest -Scope Global -ErrorAction SilentlyContinue
}
