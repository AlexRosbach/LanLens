# Security Policy

## Supported Versions

LanLens is currently maintained on the latest release line.

| Version | Supported |
| ------- | --------- |
| latest release | ✅ |
| older releases | ❌ |
| development / PR branches | best effort only |

## Reporting a Vulnerability

Please **do not open public GitHub issues** for security vulnerabilities.

If you find a vulnerability in LanLens, please report it responsibly and
include the affected version, deployment type, reproduction steps and possible
impact. Include logs, screenshots, request samples or proof of concept only
after removing credentials and production network data.

Use **GitHub Security Advisories / private vulnerability reporting** for this
repository if available. If private reporting is unavailable, contact the
maintainer through a private channel instead of posting details publicly.

## What to expect

- Reports are reviewed and assessed for impact and severity.
- Confirmed issues receive a fix or mitigation plan.
- Public disclosure should wait until affected users have a reasonable chance
  to update.

## Scope

Please report authentication or authorization bypass, privilege escalation,
remote code execution, command/SQL injection, SSRF, secrets exposure, insecure
defaults with real impact, and vulnerabilities in scan, credential,
notification or administrative functionality.

Best-practice suggestions without an exploit path, self-XSS without privilege
impact, unrealistic resource exhaustion and unsupported or heavily modified
deployments are usually out of scope.

## Handling Sensitive Data

Do not include real passwords, tokens, private keys, production inventories,
packet captures or database files in reports. Prefer minimal redacted examples.

LanLens is self-hosted. Inventory, credentials, discovery observations and
analysis results remain in the configured database/data volume unless an
operator explicitly configures an outbound integration. API responses mask
stored credentials, but operators must protect the data volume and backups.

Passive discovery stores bounded protocol metadata, not raw packet payloads.
Sophos Security Heartbeat detection records only endpoint/source identity,
destination, transport and observation time; its encrypted TLS payload is not
stored or interpreted.

## Dependency audit note

The frontend is a client-only React single-page application built with Vite. It
does not use React Router framework mode, server rendering, React Server
Components, actions or server actions. As of the 1.6.0 release-candidate audit,
`npm audit` reports GHSA-qwww-vcr4-c8h2 in React Router's RSC action handling.
That code path is not shipped or reachable in LanLens. Downgrading to the
suggested older release reintroduces multiple client-side redirect/XSS
advisories, so LanLens stays on the current release while tracking an upstream
fix.

The backend uses PyJWT with an explicit HS256 algorithm allowlist. The previous
`python-jose` dependency was removed because it pulled an unused ECDSA/RSA
dependency chain with an unpatched `ecdsa` advisory.

SSH credential tests and deep scans reject unknown or changed host keys. The
default persistent trust store is `/data/ssh_known_hosts`; operators must verify
fingerprints before adding entries.

Cross-origin browser access is disabled by default. Deployments with a separate
trusted frontend may set `LANLENS_CORS_ORIGINS` to a comma-separated list of
exact origins; wildcard credentialed CORS is not enabled.

## Update Guidance

Update to the latest supported version as soon as practical, review release
notes, and back up the instance before updating, especially for database
migrations.
