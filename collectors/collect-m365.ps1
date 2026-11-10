<#
.SYNOPSIS
  CMMC Ready: read-only Microsoft 365 / Entra ID evidence collector.

.DESCRIPTION
  Reads identity security settings from your Microsoft 365 tenant through the
  Microsoft Graph PowerShell SDK and writes them to a JSON file that CMMC Ready
  turns into objective-level findings.

  The script only reads. Every Graph call is a GET and the sign-in asks for
  four read-only permission scopes: Policy.Read.All, Directory.Read.All,
  AuditLog.Read.All and RoleManagement.Read.Directory. It never creates,
  changes or deletes anything in the tenant, never writes files other than the
  output JSON, and never handles a password, secret or token itself: you sign
  in interactively through Connect-MgGraph and the SDK keeps the session.
  Each check records the exact request it made; a check that cannot be read
  (missing consent or licence, for example Conditional Access needs Entra ID P1)
  is recorded as "unavailable" with the reason, and the script carries on.

  Requires the Microsoft.Graph.Authentication module
  (Install-Module Microsoft.Graph.Authentication -Scope CurrentUser) and an
  account that can consent to, or has been granted, the four scopes (for
  example Global Reader or Security Reader).

  Works on Windows PowerShell 5.1 and PowerShell 7.

.PARAMETER OutFile
  Where to write the JSON. Defaults to m365-evidence.json in the current folder.

.PARAMETER RedactNames
  Leave out the display names of directory role members and replace their
  object IDs with principal-1, principal-2, and so on. Role counts are kept.

.PARAMETER AuditWindowDays
  How far back to look for audit log entries. Defaults to 7.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\collect-m365.ps1 -OutFile m365.json -RedactNames
#>
[CmdletBinding()]
param(
    [string]$OutFile = 'm365-evidence.json',
    [switch]$RedactNames,
    [ValidateRange(1, 30)][int]$AuditWindowDays = 7
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$Scopes = @('Policy.Read.All', 'Directory.Read.All', 'AuditLog.Read.All', 'RoleManagement.Read.Directory')

$script:Checks = [ordered]@{}
$script:CheckCommand = ''
$script:CaPolicies = $null
$script:CaError = $null

# --- helpers ---------------------------------------------------------------

# Exception message plus the service's own error body (ErrorDetails) when the SDK supplies one.
function Get-ErrorText {
    param($ErrorRecord)
    $text = [string]$ErrorRecord.Exception.Message
    if ($null -ne $ErrorRecord.ErrorDetails -and $ErrorRecord.ErrorDetails.Message) {
        $text += ' ' + [string]$ErrorRecord.ErrorDetails.Message
    }
    (($text -replace '\s+', ' ')).Trim()
}

function Invoke-Check {
    param([string]$Id, [string]$Command, [scriptblock]$Script)
    $script:CheckCommand = $Command
    $entry = [ordered]@{ status = 'unavailable'; value = $null; reason = $null; command = $Command }
    try {
        $value = & $Script
        if ($null -eq $value) { throw 'the request returned no data' }
        $entry.status = 'ok'
        $entry.value = $value
    } catch {
        $entry.reason = Get-ErrorText $_
    }
    $entry.command = $script:CheckCommand
    $script:Checks[$Id] = $entry
}

# GET one Graph resource, returned as the JSON the service sent (camelCase hashtable).
function Get-GraphObject {
    param([string]$Uri)
    Invoke-MgGraphRequest -Method GET -Uri $Uri -OutputType HashTable
}

# GET a collection and follow @odata.nextLink until it is complete.
function Get-GraphList {
    param([string]$Uri)
    $items = New-Object System.Collections.ArrayList
    $next = $Uri
    while ($next) {
        $page = Invoke-MgGraphRequest -Method GET -Uri $next -OutputType HashTable
        if ($page.ContainsKey('value')) { foreach ($item in @($page['value'])) { [void]$items.Add($item) } }
        $next = $null
        if ($page.ContainsKey('@odata.nextLink')) { $next = [string]$page['@odata.nextLink'] }
    }
    , @($items)
}

function Get-CaPolicies {
    if ($null -ne $script:CaError) { throw $script:CaError }
    if ($null -eq $script:CaPolicies) {
        try {
            $script:CaPolicies = Get-GraphList 'https://graph.microsoft.com/v1.0/identity/conditionalAccess/policies'
        } catch {
            $script:CaError = Get-ErrorText $_
            throw $script:CaError
        }
    }
    , @($script:CaPolicies)
}

# --- sign in (read-only scopes, interactive, nothing stored by this script) ----

if (-not (Get-Module -ListAvailable -Name Microsoft.Graph.Authentication)) {
    throw 'The Microsoft.Graph.Authentication module is not installed. Run: Install-Module Microsoft.Graph.Authentication -Scope CurrentUser'
}
Import-Module Microsoft.Graph.Authentication -ErrorAction Stop
Connect-MgGraph -Scopes $Scopes -NoWelcome
$context = Get-MgContext
if ($null -eq $context) { throw 'Connect-MgGraph did not return a session.' }

# --- checks ----------------------------------------------------------------

Invoke-Check 'security_defaults' 'GET /v1.0/policies/identitySecurityDefaultsEnforcementPolicy' {
    Get-GraphObject 'https://graph.microsoft.com/v1.0/policies/identitySecurityDefaultsEnforcementPolicy'
}

Invoke-Check 'conditional_access' 'GET /v1.0/identity/conditionalAccess/policies' {
    $policies = Get-CaPolicies
    [ordered]@{ policies = $policies }
}

Invoke-Check 'auth_methods' 'GET /v1.0/policies/authenticationMethodsPolicy' {
    $policy = Get-GraphObject 'https://graph.microsoft.com/v1.0/policies/authenticationMethodsPolicy'
    $configs = @()
    if ($policy.ContainsKey('authenticationMethodConfigurations')) {
        foreach ($c in @($policy['authenticationMethodConfigurations'])) {
            $configs += [ordered]@{ id = $c['id']; state = $c['state'] }
        }
    }
    [ordered]@{
        id                                 = $policy['id']
        displayName                        = $policy['displayName']
        policyVersion                      = $policy['policyVersion']
        authenticationMethodConfigurations = $configs
    }
}

Invoke-Check 'role_assignments' 'GET /v1.0/roleManagement/directory/roleDefinitions; GET /v1.0/roleManagement/directory/roleAssignments?$expand=principal' {
    $definitions = @()
    foreach ($d in (Get-GraphList 'https://graph.microsoft.com/v1.0/roleManagement/directory/roleDefinitions?$select=id,templateId,displayName')) {
        $definitions += [ordered]@{ id = $d['id']; templateId = $d['templateId']; displayName = $d['displayName'] }
    }
    $assignments = @()
    $aliases = @{}
    foreach ($a in (Get-GraphList 'https://graph.microsoft.com/v1.0/roleManagement/directory/roleAssignments?$expand=principal')) {
        $principalId = [string]$a['principalId']
        $principalType = $null
        $principalName = $null
        if ($a.ContainsKey('principal') -and $null -ne $a['principal']) {
            $principalType = $a['principal']['@odata.type']
            $principalName = $a['principal']['displayName']
        }
        if ($RedactNames) {
            if (-not $aliases.ContainsKey($principalId)) { $aliases[$principalId] = 'principal-' + ($aliases.Count + 1) }
            $principalId = $aliases[$principalId]
            $principalName = $null
        }
        $entry = [ordered]@{
            id               = $a['id']
            roleDefinitionId = $a['roleDefinitionId']
            principalId      = $principalId
            directoryScopeId = $a['directoryScopeId']
            appScopeId       = $a['appScopeId']
            principal        = [ordered]@{ '@odata.type' = $principalType }
        }
        if (-not $RedactNames) { $entry.principal.displayName = $principalName }
        $assignments += $entry
    }
    [ordered]@{ role_definitions = $definitions; assignments = $assignments }
}

Invoke-Check 'session_controls' 'GET /v1.0/identity/conditionalAccess/policies (conditions.users, conditions.applications, sessionControls)' {
    $subset = @()
    foreach ($p in (Get-CaPolicies)) {
        $conditions = $p['conditions']
        $subset += [ordered]@{
            id              = $p['id']
            displayName     = $p['displayName']
            state           = $p['state']
            conditions      = [ordered]@{ users = $conditions['users']; applications = $conditions['applications'] }
            sessionControls = $p['sessionControls']
        }
    }
    [ordered]@{ policies = $subset }
}

Invoke-Check 'audit_log' 'GET /v1.0/auditLogs/directoryAudits?$top=1&$filter=activityDateTime ge <now minus window>' {
    $since = [datetime]::UtcNow.AddDays(-$AuditWindowDays).ToString('yyyy-MM-ddTHH:mm:ssZ')
    $uri = 'https://graph.microsoft.com/v1.0/auditLogs/directoryAudits?$top=1&$filter=' + [uri]::EscapeDataString("activityDateTime ge $since")
    $page = Get-GraphObject $uri
    $found = @($page['value'])
    $latest = $null
    if ($found.Count -gt 0) { $latest = [string]$found[0]['activityDateTime'] }
    [ordered]@{ window_days = $AuditWindowDays; entries_found = ($found.Count -gt 0); latest_activity = $latest }
}

# --- output ----------------------------------------------------------------

$document = [ordered]@{
    collector    = 'm365'
    version      = 1
    collected_at = [datetime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    tenant       = [ordered]@{ id = [string]$context.TenantId; names_redacted = [bool]$RedactNames }
    checks       = $script:Checks
}

try { Disconnect-MgGraph | Out-Null } catch { }

$json = $document | ConvertTo-Json -Depth 20
$target = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutFile)
[System.IO.File]::WriteAllText($target, $json + "`n", (New-Object System.Text.UTF8Encoding($false)))

$ok = @($script:Checks.Values | Where-Object { $_.status -eq 'ok' }).Count
$unavailable = $script:Checks.Count - $ok
Write-Host "CMMC Ready Microsoft 365 collector: $ok checks ok, $unavailable unavailable."
Write-Host "Wrote $target"
