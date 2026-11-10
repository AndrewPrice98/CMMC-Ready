# Collector coverage

Generated from `backend/cmmcready/evidence/rules.yml` by `python -m cmmcready catalog --coverage-md --write`. CI fails if this file is out of date.

Each row is one rule applied to one NIST SP 800-171A assessment objective. The last column says what the rule is allowed to record:

- **Met or Not met**: the setting decides the objective for that host or tenant.
- **Met only**: a compliant value meets the objective; anything else leaves it Not assessed, because the control may be implemented another way.
- **Not met only**: a clear gap fails the objective, but a compliant value is only supporting evidence (Not assessed), because one setting does not show the whole objective is met.
- **Supporting evidence**: always recorded as Not assessed, with the observed value shown to the assessor.
- **Information for the assessor**: the observed values are listed for the assessor to review (for example group members).

A check the collector could not read (no administrator rights, a missing module, a missing licence, output in an unexpected language) is always Not assessed, never Met or Not met. When several rules inform one objective, any Not met wins, and Met needs every rule to be Met. The assessor's own answer always overrides collector evidence; a disagreement is flagged as a conflict.

## Windows (`collectors/collect-windows.ps1`)

| Objective | Determine if | Check | Rule | Collector may record |
|---|---|---|---|---|
| 3.1.1[d] | system access is limited to authorized users. | `guest_account` | `disabled` | Not met only |
| 3.1.5[a] | privileged accounts are identified. | `local_admins` | `list` | Information for the assessor |
| 3.1.8[a] | the means of limiting unsuccessful logon attempts is defined. | `lockout_policy` | `threshold` | Met or Not met |
| 3.1.8[b] | the defined means of limiting unsuccessful logon attempts is implemented. | `lockout_policy` | `threshold` | Met or Not met |
| 3.1.9[b] | privacy and security notices are displayed. | `logon_banner` | `notice` | Met or Not met |
| 3.1.10[a] | the period of inactivity after which the system initiates a session lock is defined. | `screen_lock` | `inactivity_lock` | Met or Not met |
| 3.1.10[b] | access to the system and viewing of data is prevented by initiating a session lock after the defined period of inactivity. | `screen_lock` | `inactivity_lock` | Met or Not met |
| 3.1.10[c] | previously visible information is concealed via a pattern-hiding display after the defined period of inactivity. | `screen_lock` | `inactivity_lock` | Met or Not met |
| 3.1.12[c] | remote access sessions are controlled. | `rdp` | `controlled` | Met or Not met |
| 3.1.13[b] | cryptographic mechanisms to protect the confidentiality of remote access sessions are implemented. | `rdp` | `encrypted` | Met or Not met |
| 3.3.1[c] | audit records are created (generated). | `audit_policy` | `core_events` | Met or Not met |
| 3.3.1[f] | audit records are retained as defined. | `event_log_retention` | `retention` | Met or Not met |
| 3.4.7[l] | the use of nonessential protocols is restricted, disabled, or prevented as defined. | `smb1` | `disabled` | Not met only |
| 3.5.7[a] | password complexity requirements are defined. | `password_policy` | `min_length` | Met or Not met |
| 3.5.7[c] | minimum password complexity requirements as defined are enforced when new passwords are created. | `password_policy` | `complexity` | Met or Not met |
| 3.5.8[a] | the number of generations during which a password cannot be reused is specified. | `password_policy` | `history` | Met or Not met |
| 3.5.8[b] | reuse of passwords is prohibited during the specified number of generations. | `password_policy` | `history` | Met or Not met |
| 3.5.10[a] | passwords are cryptographically protected in storage. | `password_policy` | `reversible` | Met or Not met |
| 3.8.7[a] | the use of removable media on system components is controlled. | `autoplay` | `all_drives` | Met only |
| 3.8.7[a] | the use of removable media on system components is controlled. | `usb_storage` | `blocked` | Met only |
| 3.13.1[f] | communications are controlled at key internal boundaries. | `firewall_profiles` | `enabled` | Not met only |
| 3.13.6[a] | network communications traffic is denied by default. | `firewall_profiles` | `default_deny` | Met or Not met |
| 3.13.11[a] | FIPS-validated cryptography is employed to protect the confidentiality of CUI. | `fips_mode` | `enabled` | Supporting evidence |
| 3.13.15[a] | the authenticity of communications sessions is protected. | `smb_signing` | `required` | Not met only |
| 3.13.16[a] | the confidentiality of CUI at rest is protected. | `bitlocker` | `fixed_volumes` | Met or Not met |
| 3.14.1[f] | system flaws are corrected within the specified time frame. | `patch_level` | `recent` | Not met only |
| 3.14.2[b] | protection from malicious code at designated locations is provided. | `defender` | `protection_on` | Met or Not met |
| 3.14.4[a] | malicious code protection mechanisms are updated when new releases are available. | `defender` | `signatures` | Met or Not met |
| 3.14.5[c] | real-time malicious code scans of files from external sources as files are downloaded, opened, or executed are performed. | `defender` | `realtime_scan` | Met or Not met |

## Microsoft 365 / Entra ID (`collectors/collect-m365.ps1`)

| Objective | Determine if | Check | Rule | Collector may record |
|---|---|---|---|---|
| 3.1.5[a] | privileged accounts are identified. | `privileged_roles` | `privileged_identified` | Supporting evidence |
| 3.1.5[b] | access to privileged accounts is authorized in accordance with the principle of least privilege. | `privileged_roles` | `global_admin_limit` | Not met only |
| 3.1.5[d] | access to security functions is authorized in accordance with the principle of least privilege. | `privileged_roles` | `global_admin_limit` | Not met only |
| 3.1.6[b] | users are required to use non-privileged accounts or roles when accessing nonsecurity functions. | `privileged_roles` | `non_privileged_use` | Supporting evidence |
| 3.1.11[a] | conditions requiring a user session to terminate are defined. | `session_timeout` | `condition_defined` | Supporting evidence |
| 3.1.11[b] | a user session is automatically terminated after any of the defined conditions occur. | `session_timeout` | `frequency_enforced` | Not met only |
| 3.1.12[c] | remote access sessions are controlled. | `legacy_auth` | `remote_control` | Supporting evidence |
| 3.3.1[c] | audit records are created (generated). | `audit_log` | `recent_entries` | Met only |
| 3.5.2[a] | the identity of each user is authenticated or verified as a prerequisite to system access. | `auth_methods` | `enabled_methods` | Information for the assessor |
| 3.5.3[b] | multifactor authentication is implemented for local access to privileged accounts. | `mfa` | `privileged_local` | Supporting evidence |
| 3.5.3[c] | multifactor authentication is implemented for network access to privileged accounts. | `mfa` | `privileged_network` | Met or Not met |
| 3.5.3[d] | multifactor authentication is implemented for network access to non-privileged accounts. | `legacy_auth` | `bypass_closed` | Met or Not met |
| 3.5.3[d] | multifactor authentication is implemented for network access to non-privileged accounts. | `mfa` | `general_users` | Met or Not met |
