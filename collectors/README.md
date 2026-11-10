# Collectors

Two PowerShell scripts gather evidence for CMMC Ready. Both are **read-only**: they never change a setting, never write to the registry or the tenant, and never ask for, store or send a password, secret or token. Each writes one JSON file that you upload on the dashboard's **Evidence** page (or check with `python -m cmmcready collect-parse`). Nothing is sent anywhere by the scripts themselves.

Every check records the exact command it ran. A check that cannot be read (no administrator rights, a missing module, a missing licence) is recorded as `"status": "unavailable"` with the reason, the script carries on, and the objectives it informs stay **Not assessed**. They never become Met or Not met because something could not be read.

Which objectives each check informs, and what it is allowed to decide, is listed in [docs/COLLECTOR_COVERAGE.md](../docs/COLLECTOR_COVERAGE.md).

## Windows: `collect-windows.ps1`

Runs on Windows PowerShell 5.1 and PowerShell 7. Run it elevated for the full set of checks. Without elevation, the checks that need administrator rights are recorded as unavailable (on a standard Windows 11 workstation: password and lockout policy, audit policy, Security log retention and BitLocker).

```powershell
powershell -ExecutionPolicy Bypass -File .\collect-windows.ps1 -OutFile windows-evidence.json
# -RedactNames replaces local Administrators group member names with member-1, member-2, ...
```

| Check | Exactly what runs |
|---|---|
| `password_policy`, `lockout_policy` | `secedit /export /cfg "<temp file in $env:TEMP>" /areas SECURITYPOLICY`, then the `[System Access]` section is read and the temp file deleted |
| `audit_policy` | `auditpol /get /category:* /r` (rows read by position, subcategories by GUID) |
| `event_log_retention` | `Get-WinEvent -ListLog Security`; `Get-WinEvent -LogName Security -Oldest -MaxEvents 1` |
| `bitlocker` | `Get-BitLockerVolume`; `Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3"` |
| `firewall_profiles` | `Get-NetFirewallProfile -PolicyStore ActiveStore` |
| `screen_lock` | Registry read: `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System` `InactivityTimeoutSecs`; screen saver values from `HKCU\Software\Policies\Microsoft\Windows\Control Panel\Desktop`, else `HKCU\Control Panel\Desktop` |
| `smb_signing` | `Get-SmbServerConfiguration` |
| `smb1` | `Get-SmbServerConfiguration`; without rights, registry read `HKLM\SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters` `SMB1` |
| `local_admins` | `Get-LocalGroupMember -SID S-1-5-32-544` |
| `rdp` | Registry reads under `HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services` and `HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server` (`fDenyTSConnections`, `WinStations\RDP-Tcp`); `Get-CimInstance Win32_TSGeneralSetting` for NLA |
| `defender` | `Get-MpComputerStatus` |
| `autoplay` | Registry read: `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer` `NoDriveTypeAutoRun` |
| `usb_storage` | Registry read: `HKLM\SYSTEM\CurrentControlSet\Services\USBSTOR` `Start` |
| `patch_level` | `Get-HotFix` |
| `fips_mode` | Registry read: `HKLM\SYSTEM\CurrentControlSet\Control\Lsa\FipsAlgorithmPolicy` `Enabled` |
| `logon_banner` | Registry read: `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System` `legalnoticecaption`, `legalnoticetext` |
| `guest_account` | `Get-CimInstance Win32_UserAccount -Filter "LocalAccount=True AND SID LIKE '%-501'"` |
| host details | `Get-CimInstance Win32_OperatingSystem`, `Win32_ComputerSystem` (OS, build, domain joined), plus whether the session is elevated |

Registry values are read through .NET `RegistryKey.OpenSubKey`, which opens keys read-only.

**Side effects.** `secedit /export` writes its export to a randomly named file in `$env:TEMP`, which the script deletes straight afterwards. Windows itself also appends a line to `%windir%\security\logs\scesrv.log` whenever `secedit` runs; that is an operating-system side effect the script cannot avoid. Nothing else is written apart from the output JSON.

**Language.** `auditpol` prints its settings in the display language. The parser understands the English values only ("Success and Failure", "Success", "Failure", "No Auditing"); on a system in another language the audit settings stay unknown and objective 3.3.1[c] stays Not assessed.

**What the output contains.** The computer name, OS caption and build, domain membership, the values above and, unless `-RedactNames` is used, the names of local Administrators group members. Review the file before sharing it.

## Microsoft 365 / Entra ID: `collect-m365.ps1`

Needs the Microsoft Graph PowerShell SDK authentication module and an account that can consent to, or has been granted, four read-only scopes (for example Global Reader or Security Reader). You sign in interactively through `Connect-MgGraph`; the SDK keeps the session and the script never sees a token.

```powershell
Install-Module Microsoft.Graph.Authentication -Scope CurrentUser
powershell -ExecutionPolicy Bypass -File .\collect-m365.ps1 -OutFile m365-evidence.json -RedactNames
# -AuditWindowDays 7 (default; 1-30) sets how far back to look for directory audit entries
```

Scopes requested: `Policy.Read.All`, `Directory.Read.All`, `AuditLog.Read.All`, `RoleManagement.Read.Directory`. Every request is a `GET` through `Invoke-MgGraphRequest`:

| Check | Exactly what runs |
|---|---|
| `security_defaults` | `GET /v1.0/policies/identitySecurityDefaultsEnforcementPolicy` |
| `conditional_access` | `GET /v1.0/identity/conditionalAccess/policies` (all pages) |
| `auth_methods` | `GET /v1.0/policies/authenticationMethodsPolicy` (method ids and states only) |
| `role_assignments` | `GET /v1.0/roleManagement/directory/roleDefinitions?$select=id,templateId,displayName`; `GET /v1.0/roleManagement/directory/roleAssignments?$expand=principal` |
| `session_controls` | The Conditional Access policies above, reduced to users, applications and session controls |
| `audit_log` | `GET /v1.0/auditLogs/directoryAudits?$top=1&$filter=activityDateTime ge <now minus window>` |

The script ends with `Disconnect-MgGraph`. Conditional Access needs Entra ID P1; without it that check is recorded as unavailable. CMMC Ready derives four checks from these responses (`mfa`, `legacy_auth`, `session_timeout`, `privileged_roles`); only enabled policies count, never report-only or disabled ones.

**What the output contains.** The tenant ID, the policies above (including their names) and, unless `-RedactNames` is used, the display names and object IDs of directory role members. With `-RedactNames`, member names are left out and IDs become `principal-1`, `principal-2` and so on; role counts are kept.

## Checking a file before upload

```bash
cd backend
python -m cmmcready collect-parse windows ../windows-evidence.json
python -m cmmcready collect-parse m365 ../m365-evidence.json
```

This validates the file and prints how many checks were readable, why any were not, and how many objectives the rules mark met, not met and not assessed. CI runs the Windows collector on GitHub's `windows-latest` runner under both PowerShell versions and fails unless at least 8 checks were readable.
