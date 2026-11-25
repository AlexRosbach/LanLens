# Windows agent: private or self-signed HTTPS certificates

TLS verification is enabled by default. On the Deep Scan → Windows Agent installation page, enable **Explicitly trust an untrusted certificate** and supply the SHA-256 fingerprint of the actual HTTPS server leaf certificate from a trusted source (64 hex digits; separators allowed in the UI). For example, on a trusted machine with the exported public server certificate in DER format, run `certutil -hashfile server.cer SHA256`. Do not use the Windows SHA-1 thumbprint. Do not obtain the fingerprint through an unverified connection.

The generated installation command checks the certificate pin before downloading the installer, then applies the same check for the agent source download and enrollment. The pin is persisted in the protected agent.json configuration and used for subsequent reports. Hostname and certificate validity dates are still verified; redirects are disabled. No certificate is added to the Windows trust store. When the certificate rotates, update certificate_sha256 in the protected configuration with the verified replacement fingerprint. Existing installations without a pin retain normal certificate validation. Prefer a normally trusted CA certificate when possible.

Linux agent behavior is unchanged.
