<#
.SYNOPSIS
  CMMC Ready: read-only Windows evidence collector.

.DESCRIPTION
  Reads security settings from this computer and writes them to a JSON file
  that CMMC Ready turns into objective-level findings.

  The script only reads. It never changes a setting, writes to the registry,
  or applies a policy. The one file it creates is the temporary export from
  'secedit /export' in $env:TEMP, which it deletes straight afterwards.
  No credentials are used or stored. Each check records the exact command it
  ran; a check that cannot be read (for example without administrator rights)
  is recorded as "unavailable" with the reason, and the script carries on.

  Works on Windows PowerShell 5.1 and PowerShell 7. Run it elevated for the
  full set of checks.

.PARAMETER OutFile
  Where to write the JSON. Defaults to windows-evidence.json in the current folder.

.PARAMETER RedactNames
  Replace the names of local Administrators group members with member-1,
  member-2, and so on.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\collect-windows.ps1 -OutFile out.json
#>
[CmdletBinding()]
param(
    [string]$OutFile = 'windows-evidence.json',
    [switch]$RedactNames
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne 'Win32NT') {
    throw 'collect-windows.ps1 runs on Windows only.'
}

$script:Checks = [ordered]@{}
$script:CheckCommand = ''
$script:SystemAccess = $null
$script:SystemAccessError = $null
$script:SmbConfig = $null
$script:SmbConfigError = $null

$IsAdmin = $false
try {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    $IsAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
} catch { }

# --- helpers ---------------------------------------------------------------

function Invoke-Check {
    param([string]$Id, [string]$Command, [scriptblock]$Script)
    $script:CheckCommand = $Command
    $entry = [ordered]@{ status = 'unavailable'; value = $null; reason = $null; command = $Command }
    try {
        $value = & $Script
        if ($null -eq $value) { throw 'the command returned no data' }
        $entry.status = 'ok'
        $entry.value = $value
    } catch {
        $entry.reason = (($_.Exception.Message -replace '\s+', ' ')).Trim()
    }
    $entry.command = $script:CheckCommand
    $script:Checks[$Id] = $entry
}

function Invoke-Native {
    param([string]$File, [string[]]$Arguments)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $File @Arguments 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    $lines = @($out | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { "$_" }
    } | Where-Object { $_ -and $_.Trim() })
    [pscustomobject]@{ Output = $lines; ExitCode = $code }
}

function ConvertTo-Int {
    param($Value)
    $number = 0
    if ($null -ne $Value -and [int]::TryParse(("$Value").Trim(), [ref]$number)) { return $number }
    return $null
}

function Get-RegValue {
    # Returns $null when the key or value does not exist; throws when access is denied.
    param([ValidateSet('HKLM', 'HKCU')][string]$Hive, [string]$SubKey, [string]$Name)
    $hiveId = if ($Hive -eq 'HKLM') { [Microsoft.Win32.RegistryHive]::LocalMachine } else { [Microsoft.Win32.RegistryHive]::CurrentUser }
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hiveId, [Microsoft.Win32.RegistryView]::Registry64)
    try {
        $key = $base.OpenSubKey($SubKey)
        if ($null -eq $key) { return $null }
        try { return $key.GetValue($Name, $null) } finally { $key.Dispose() }
    } finally {
        $base.Dispose()
    }
}

function Get-Prop {
    param($Object, [string]$Name)
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Get-SystemAccess {
    # 'secedit /export' to a temp file, read the [System Access] section, delete the file.
    if ($null -ne $script:SystemAccess) { return $script:SystemAccess }
    if ($null -ne $script:SystemAccessError) { throw $script:SystemAccessError }
    $tmp = Join-Path $env:TEMP ('cmmcready-' + [guid]::NewGuid().ToString('N') + '.inf')
    try {
        $run = Invoke-Native 'secedit.exe' @('/export', '/cfg', $tmp, '/areas', 'SECURITYPOLICY')
        if ($run.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $tmp)) {
            $script:SystemAccessError = 'secedit /export failed (exit ' + $run.ExitCode + '): ' + ($run.Output -join ' ')
            throw $script:SystemAccessError
        }
        $map = @{}
        $inSection = $false
        foreach ($line in (Get-Content -LiteralPath $tmp -Encoding Unicode)) {
            if ($line -match '^\[(.+)\]\s*$') { $inSection = ($Matches[1] -eq 'System Access'); continue }
            if ($inSection -and $line -match '^\s*(\w+)\s*=\s*(.*?)\s*$') { $map[$Matches[1]] = $Matches[2] }
        }
        if ($map.Count -eq 0) {
            $script:SystemAccessError = 'secedit export contained no [System Access] section'
            throw $script:SystemAccessError
        }
        $script:SystemAccess = $map
    } finally {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
    }
    return $script:SystemAccess
}

function Get-SmbConfig {
    if ($null -ne $script:SmbConfig) { return $script:SmbConfig }
    if ($null -ne $script:SmbConfigError) { throw $script:SmbConfigError }
    try {
        $script:SmbConfig = Get-SmbServerConfiguration -ErrorAction Stop
    } catch {
        $script:SmbConfigError = $_.Exception.Message
        throw
    }
    return $script:SmbConfig
}

$secedit = 'secedit /export /cfg "<temp file in $env:TEMP>" /areas SECURITYPOLICY'

# --- checks ----------------------------------------------------------------

Invoke-Check 'password_policy' $secedit {
    $sa = Get-SystemAccess
    [ordered]@{
        MinimumPasswordAge    = ConvertTo-Int $sa['MinimumPasswordAge']
        MaximumPasswordAge    = ConvertTo-Int $sa['MaximumPasswordAge']
        MinimumPasswordLength = ConvertTo-Int $sa['MinimumPasswordLength']
        PasswordComplexity    = ConvertTo-Int $sa['PasswordComplexity']
        PasswordHistorySize   = ConvertTo-Int $sa['PasswordHistorySize']
        ClearTextPassword     = ConvertTo-Int $sa['ClearTextPassword']
    }
}

Invoke-Check 'lockout_policy' $secedit {
    $sa = Get-SystemAccess
    [ordered]@{
        LockoutBadCount   = ConvertTo-Int $sa['LockoutBadCount']
        ResetLockoutCount = ConvertTo-Int $sa['ResetLockoutCount']
        LockoutDuration   = ConvertTo-Int $sa['LockoutDuration']
    }
}

Invoke-Check 'audit_policy' 'auditpol /get /category:* /r' {
    # The CSV header and the setting text are in the display language, so the
    # rows are read by position and subcategories are identified by GUID.
    $run = Invoke-Native 'auditpol.exe' @('/get', '/category:*', '/r')
    if ($run.ExitCode -ne 0) { throw ('auditpol failed (exit ' + $run.ExitCode + '): ' + ($run.Output -join ' ')) }
    $rows = @($run.Output | Where-Object { $_.Trim() } | ConvertFrom-Csv -Header 'c1', 'c2', 'c3', 'c4', 'c5', 'c6')
    $subs = [ordered]@{}
    foreach ($row in $rows) {
        if ($row.c4 -match '^\{[0-9A-Fa-f\-]{36}\}$') {
            $subs[$row.c4.ToUpper()] = [ordered]@{ name = $row.c3; setting = $row.c5 }
        }
    }
    if ($subs.Count -eq 0) { throw 'auditpol output had no audit subcategory rows' }
    [ordered]@{ subcategories = $subs }
}

Invoke-Check 'event_log_retention' 'Get-WinEvent -ListLog Security; Get-WinEvent -LogName Security -Oldest -MaxEvents 1' {
    $log = Get-WinEvent -ListLog Security -ErrorAction Stop
    $oldest = Get-WinEvent -LogName Security -Oldest -MaxEvents 1 -ErrorAction Stop
    [ordered]@{
        log_name              = 'Security'
        enabled               = [bool]$log.IsEnabled
        log_mode              = [string]$log.LogMode
        max_size_kb           = [int64]($log.MaximumSizeInBytes / 1KB)
        record_count          = $log.RecordCount
        oldest_record_number  = [int64]$oldest.RecordId
        oldest_event_age_days = [int][math]::Floor(((Get-Date) - $oldest.TimeCreated).TotalDays)
    }
}

Invoke-Check 'bitlocker' 'Get-BitLockerVolume; Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3"' {
    $fixed = @(Get-CimInstance -ClassName Win32_LogicalDisk -Filter 'DriveType=3' -ErrorAction Stop | ForEach-Object { $_.DeviceID })
    $volumes = @()
    foreach ($v in @(Get-BitLockerVolume -ErrorAction Stop)) {
        if ($fixed -notcontains [string]$v.MountPoint) { continue }
        $status = "$($v.ProtectionStatus)"
        $entry = [ordered]@{ mount_point = [string]$v.MountPoint; volume_type = [string]$v.VolumeType }
        # Only On/Off are recorded; anything else stays unknown rather than guessed.
        if ($status -eq 'On' -or $status -eq '1') { $entry.protection_status = 'On' }
        elseif ($status -eq 'Off' -or $status -eq '0') { $entry.protection_status = 'Off' }
        $entry.encryption_percentage = $v.EncryptionPercentage
        $volumes += $entry
    }
    if ($volumes.Count -eq 0) { throw 'no fixed volumes were reported by BitLocker' }
    [ordered]@{ volumes = $volumes }
}

Invoke-Check 'firewall_profiles' 'Get-NetFirewallProfile -PolicyStore ActiveStore' {
    $profiles = @()
    foreach ($p in @(Get-NetFirewallProfile -PolicyStore ActiveStore -ErrorAction Stop)) {
        $enabled = "$($p.Enabled)"
        $action = "$($p.DefaultInboundAction)"
        $entry = [ordered]@{ name = [string]$p.Name }
        if ($enabled -eq 'True' -or $enabled -eq '1') { $entry.enabled = $true }
        elseif ($enabled -eq 'False' -or $enabled -eq '0') { $entry.enabled = $false }
        if ($action -eq 'Block' -or $action -eq '4') { $entry.default_inbound_action = 'Block' }
        elseif ($action -eq 'Allow' -or $action -eq '2') { $entry.default_inbound_action = 'Allow' }
        else { $entry.default_inbound_action = 'NotConfigured' }
        $profiles += $entry
    }
    if ($profiles.Count -eq 0) { throw 'no firewall profiles were returned' }
    [ordered]@{ profiles = $profiles }
}

Invoke-Check 'screen_lock' 'registry: HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System InactivityTimeoutSecs; HKCU\Software\Policies\Microsoft\Windows\Control Panel\Desktop ScreenSaveActive, ScreenSaveTimeOut, ScreenSaverIsSecure' {
    $desktop = 'Software\Policies\Microsoft\Windows\Control Panel\Desktop'
    [ordered]@{
        inactivity_timeout_secs  = ConvertTo-Int (Get-RegValue 'HKLM' 'SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' 'InactivityTimeoutSecs')
        screensaver_active       = ConvertTo-Int (Get-RegValue 'HKCU' $desktop 'ScreenSaveActive')
        screensaver_timeout_secs = ConvertTo-Int (Get-RegValue 'HKCU' $desktop 'ScreenSaveTimeOut')
        screensaver_secure       = ConvertTo-Int (Get-RegValue 'HKCU' $desktop 'ScreenSaverIsSecure')
    }
}

Invoke-Check 'smb_signing' 'Get-SmbServerConfiguration' {
    $c = Get-SmbConfig
    [ordered]@{
        require_security_signature = [bool]$c.RequireSecuritySignature
        enable_security_signature  = [bool]$c.EnableSecuritySignature
    }
}

Invoke-Check 'smb1' 'Get-SmbServerConfiguration' {
    try {
        $c = Get-SmbConfig
        [ordered]@{ server_enabled = [bool]$c.EnableSMB1Protocol }
    } catch {
        # Readable without administrator rights: the explicit server setting.
        $script:CheckCommand = 'registry: HKLM\SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters SMB1'
        $smb1 = ConvertTo-Int (Get-RegValue 'HKLM' 'SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters' 'SMB1')
        if ($null -eq $smb1) { throw ('Get-SmbServerConfiguration failed and the SMB1 registry value is not set: ' + $_.Exception.Message) }
        [ordered]@{ server_enabled = ($smb1 -ne 0) }
    }
}

Invoke-Check 'local_admins' 'Get-LocalGroupMember -SID S-1-5-32-544' {
    $members = @()
    $n = 0
    foreach ($m in @(Get-LocalGroupMember -SID 'S-1-5-32-544' -ErrorAction Stop)) {
        $n++
        $name = if ($RedactNames) { "member-$n" } else { [string]$m.Name }
        $members += [ordered]@{ name = $name; object_class = [string]$m.ObjectClass; principal_source = [string]$m.PrincipalSource }
    }
    [ordered]@{ count = $members.Count; members = $members }
}

Invoke-Check 'rdp' 'registry: HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services (policy) then HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server (fDenyTSConnections, WinStations\RDP-Tcp); Get-CimInstance Win32_TSGeneralSetting (NLA)' {
    $policy = 'SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services'
    $ts = 'SYSTEM\CurrentControlSet\Control\Terminal Server'
    $tcp = $ts + '\WinStations\RDP-Tcp'
    $deny = ConvertTo-Int (Get-RegValue 'HKLM' $policy 'fDenyTSConnections')
    if ($null -eq $deny) { $deny = ConvertTo-Int (Get-RegValue 'HKLM' $ts 'fDenyTSConnections') }
    if ($null -eq $deny) { throw 'fDenyTSConnections is not set' }
    $result = [ordered]@{ deny_connections = ($deny -ne 0) }

    $nla = ConvertTo-Int (Get-RegValue 'HKLM' $policy 'UserAuthentication')
    if ($null -eq $nla) {
        try {
            $setting = Get-CimInstance -Namespace 'root/cimv2/TerminalServices' -ClassName Win32_TSGeneralSetting -Filter "TerminalName='RDP-Tcp'" -ErrorAction Stop
            $nla = ConvertTo-Int (Get-Prop $setting 'UserAuthenticationRequired')
        } catch { }
    }
    if ($null -eq $nla) { $nla = ConvertTo-Int (Get-RegValue 'HKLM' $tcp 'UserAuthentication') }
    # When NLA cannot be read the key is left out, so the engine treats it as unknown.
    if ($null -ne $nla) { $result.nla_required = ($nla -ne 0) }

    $layer = ConvertTo-Int (Get-RegValue 'HKLM' $policy 'SecurityLayer')
    if ($null -eq $layer) { $layer = ConvertTo-Int (Get-RegValue 'HKLM' $tcp 'SecurityLayer') }
    $result.security_layer = $layer
    $enc = ConvertTo-Int (Get-RegValue 'HKLM' $policy 'MinEncryptionLevel')
    if ($null -eq $enc) { $enc = ConvertTo-Int (Get-RegValue 'HKLM' $tcp 'MinEncryptionLevel') }
    $result.min_encryption_level = $enc
    $result
}

Invoke-Check 'defender' 'Get-MpComputerStatus' {
    $s = Get-MpComputerStatus -ErrorAction Stop
    $result = [ordered]@{
        antivirus_enabled            = [bool](Get-Prop $s 'AntivirusEnabled')
        realtime_protection_enabled  = [bool](Get-Prop $s 'RealTimeProtectionEnabled')
        on_access_protection_enabled = [bool](Get-Prop $s 'OnAccessProtectionEnabled')
    }
    $age = ConvertTo-Int (Get-Prop $s 'AntivirusSignatureAge')
    if ($null -ne $age) { $result.antivirus_signature_age_days = $age }
    $mode = Get-Prop $s 'AMRunningMode'
    if ($null -ne $mode) { $result.running_mode = [string]$mode }
    $result
}

Invoke-Check 'autoplay' 'registry: HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer NoDriveTypeAutoRun' {
    [ordered]@{ no_drive_type_auto_run = ConvertTo-Int (Get-RegValue 'HKLM' 'SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer' 'NoDriveTypeAutoRun') }
}

Invoke-Check 'usb_storage' 'registry: HKLM\SYSTEM\CurrentControlSet\Services\USBSTOR Start' {
    [ordered]@{ usbstor_start = ConvertTo-Int (Get-RegValue 'HKLM' 'SYSTEM\CurrentControlSet\Services\USBSTOR' 'Start') }
}

Invoke-Check 'patch_level' 'Get-HotFix' {
    $dated = @(Get-HotFix -ErrorAction Stop | Where-Object { $_.InstalledOn } | Sort-Object InstalledOn -Descending)
    if ($dated.Count -eq 0) { throw 'Get-HotFix returned no entries with an InstalledOn date' }
    [ordered]@{ latest_installed_on = ([datetime]$dated[0].InstalledOn).ToString('yyyy-MM-dd'); hotfix_count = $dated.Count }
}

Invoke-Check 'fips_mode' 'registry: HKLM\SYSTEM\CurrentControlSet\Control\Lsa\FipsAlgorithmPolicy Enabled' {
    $v = ConvertTo-Int (Get-RegValue 'HKLM' 'SYSTEM\CurrentControlSet\Control\Lsa\FipsAlgorithmPolicy' 'Enabled')
    [ordered]@{ enabled = ($v -eq 1) }
}

Invoke-Check 'logon_banner' 'registry: HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System legalnoticecaption, legalnoticetext' {
    $key = 'SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
    $caption = Get-RegValue 'HKLM' $key 'legalnoticecaption'
    $text = Get-RegValue 'HKLM' $key 'legalnoticetext'
    [ordered]@{
        caption = if ($null -eq $caption) { $null } else { [string]$caption }
        text    = if ($null -eq $text) { $null } else { [string]$text }
    }
}

Invoke-Check 'guest_account' 'Get-CimInstance Win32_UserAccount -Filter "LocalAccount=True AND SID LIKE ''%-501''"' {
    $guest = @(Get-CimInstance -ClassName Win32_UserAccount -Filter "LocalAccount=True AND SID LIKE '%-501'" -ErrorAction Stop)
    if ($guest.Count -eq 0) { throw 'the built-in Guest account (RID 501) was not found' }
    [ordered]@{ enabled = (-not [bool]$guest[0].Disabled) }
}

# --- output ----------------------------------------------------------------

$hostInfo = [ordered]@{ name = $env:COMPUTERNAME; os = $null; build = $null; domain_joined = $null; elevated = $IsAdmin }
try {
    $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
    $hostInfo.os = [string]$os.Caption
    $hostInfo.build = [string]$os.BuildNumber
    $hostInfo.domain_joined = [bool](Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop).PartOfDomain
} catch { }

$document = [ordered]@{
    collector    = 'windows'
    version      = 1
    collected_at = [datetime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    host         = $hostInfo
    checks       = $script:Checks
}

$json = $document | ConvertTo-Json -Depth 10
$target = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutFile)
[System.IO.File]::WriteAllText($target, $json + "`n", (New-Object System.Text.UTF8Encoding($false)))

$ok = @($script:Checks.Values | Where-Object { $_.status -eq 'ok' }).Count
$unavailable = $script:Checks.Count - $ok
Write-Host "CMMC Ready Windows collector: $ok checks ok, $unavailable unavailable (elevated: $IsAdmin)."
Write-Host "Wrote $target"
