# Windows agent: private or self-signed HTTPS certificates

TLS verification is enabled by default. On the Deep Scan → Windows Agent installation page, enable **Explicitly trust an untrusted certificate** if necessary. No certificate fingerprint is required.

The generated installation command allows untrusted certificate chains for downloading the installer, compiling and enrolling the agent, and subsequent inventory reports. The setting is persisted as a boolean in the protected agent.json configuration. HTTPS and a presented server certificate are required; redirects are disabled. With the explicit exception, chain, hostname and validity-date verification are bypassed. Bootstrap and installer use request-local certificate callbacks instead of PowerShell web cmdlets. The Windows trust store is not changed. Existing explicit fingerprint configurations retain their pin checks.

**Security warning:** an untrusted certificate chain cannot authenticate the server. An attacker could impersonate the server, deliver modified executable code, or intercept enrollment and reporting credentials. Prefer a normally trusted private or public CA certificate. Only enable the exception where the network and endpoint are trusted.

Linux agent behavior is unchanged.
