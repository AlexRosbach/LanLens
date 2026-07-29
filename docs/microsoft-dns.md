# DNS names and Microsoft DNS

LanLens 1.5.9 can retain every DNS or discovery name associated with a device
while showing one stable preferred name in lists, headings, notifications and
i-doit object titles.

## Device names

Enable **DNS names and aliases** under **Settings → Network Discovery**. The
device page then shows observed names, record type, source, canonical CNAME
target, status and timestamps.

The preferred-name modes are:

- **Automatic**: custom device label, hostname, IP address, then MAC address.
- **Discovered**: an explicitly selected observed DNS name.
- **Manual**: an operator-entered name that is not overwritten by scans.

Aliases remain searchable and available for device correlation. They are not
appended to the visible primary name.

## Microsoft DNS integration

Microsoft DNS synchronization is optional, separately enabled and read-only.
It uses an existing `windows_winrm` credential from the encrypted LanLens
credential vault and PowerShell's `Get-DnsServerZone` and
`Get-DnsServerResourceRecord` commands.

The account requires only enough rights to establish the configured WinRM
session, list zones when automatic discovery is used, and read A, AAAA, PTR and
CNAME records. LanLens never creates, changes or deletes DNS records.

Enter one zone per line to restrict synchronization. Leave the zone list empty
to read forward zones returned by the Microsoft DNS server. Connection tests
read records but do not store them. Manual or scheduled synchronization
associates records with existing devices by IP address, canonical name or
already-known name.

Use HTTPS WinRM with a trusted certificate where available. Normal network
scans continue if Microsoft DNS is unavailable; the last sanitized integration
error remains visible in Settings.

## Security and privacy

- Use a dedicated least-privilege read-only account.
- Do not grant DNS administration rights to the LanLens account.
- Zone data may expose internal host and service names; restrict LanLens access.
- Credentials remain encrypted and are never returned by the DNS config API.
- Disable Microsoft DNS to stop scheduled zone activity. Disable the parent
  DNS-names feature to stop all additional DNS-name collection.
