# DNS names and AXFR zone transfer

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

## AXFR integration

AXFR synchronization is optional, separately enabled and read-only. It uses the
standard DNS zone-transfer protocol and therefore works with Microsoft DNS,
BIND and other authoritative servers that permit AXFR.

Enter the authoritative DNS server, port and one or more explicit zones.
LanLens reads A, AAAA, PTR and CNAME records. It never creates, changes or
deletes DNS records. Zone enumeration is deliberately not attempted because
AXFR requires an explicit zone name.

The DNS server must allow TCP zone transfers from the LanLens host. For
Microsoft DNS this can be configured in the zone's transfer settings. Prefer
restricting transfers to the LanLens source address. If the server requires
TSIG, enter the key name, Base64 secret and matching HMAC algorithm. The secret
is Fernet-encrypted using the LanLens `SECRET_KEY` and is never returned by the
configuration API.

Connection tests transfer records but do not store them. Manual or scheduled
synchronization associates records with existing devices by IP address,
canonical name or already-known name. Normal network scans continue if AXFR is
unavailable; the last sanitized integration error remains visible in Settings.

## Security and privacy

- Restrict AXFR to the LanLens source address and only the required zones.
- Prefer TSIG in addition to an address-based transfer ACL.
- Zone data may expose internal host and service names; restrict LanLens access.
- TSIG secrets remain encrypted and are never returned by the DNS config API.
- Disable AXFR synchronization to stop scheduled zone activity. Disable the parent
  DNS-names feature to stop all additional DNS-name collection.
