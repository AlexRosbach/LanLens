# Windows agent: private or self-signed HTTPS certificates

TLS verification is enabled by default. On the Deep Scan → Windows Agent installation page, enable **Explicitly trust an untrusted certificate** if necessary. No certificate fingerprint is required.

The generated installation command allows untrusted certificate chains for downloading the installer, compiling and enrolling the agent, and subsequent inventory reports. The setting is persisted as a boolean in the protected agent.json configuration. HTTPS and a presented server certificate are required; redirects are disabled. With the explicit exception, chain, hostname and validity-date verification are bypassed. Bootstrap and installer use request-local certificate callbacks instead of PowerShell web cmdlets. The Windows trust store is not changed. Existing explicit fingerprint configurations retain their pin checks.

**Security warning:** an untrusted certificate chain cannot authenticate the server. An attacker could impersonate the server, deliver modified executable code, or intercept enrollment and reporting credentials. Prefer a normally trusted private or public CA certificate. Only enable the exception where the network and endpoint are trusted.

Linux agent behavior is unchanged.

## Local diagnostics and updating existing Windows agents

Deep Scan → Windows Agent provides a copyable update command. Run elevated using the original server URL and certificate option. The existing agent registration, report sequence and configuration are retained. The service writes `C:\ProgramData\LanLensAgent\agent.log` (UTC); daily archives are named `agent-YYYY-MM-DD.log`. Older archives are removed after 30 calendar days when logging. Logs include collector status, report endpoint, counts, sequence, HTTP status and accepted device/run IDs, but never enrollment tokens, bearer credentials or inventory payloads. New enrollments persist the selected MAC to prevent switching adapters on reboot. Existing configurations without a saved MAC continue using the previous selection behavior; a 409 identity mismatch requires checking the enrolled device MAC. In Device → Deep Scan, agent status reports the last accepted sequence and run, and findings are grouped by source even without SSH/WinRM configuration. First and changed reports appear in Change Timeline; identical reports update the last-report status without adding timeline noise.
