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

If you find a vulnerability in LanLens, please report it responsibly and include as much detail as possible:

- affected version
- deployment type (for example Docker, reverse proxy, standalone)
- reproduction steps
- possible impact
- logs, screenshots, request samples, or proof of concept if relevant

### Preferred reporting path

Use **GitHub Security Advisories / private vulnerability reporting** for this repository if available.

If private reporting is not available, contact the maintainer directly through a private channel instead of posting details publicly.

## What to expect

After a valid report is received:

- the issue will be reviewed as quickly as possible
- impact and severity will be assessed
- a fix or mitigation plan will be prepared when confirmed
- public disclosure should wait until affected users have a reasonable chance to update

## Scope

Please report issues such as:

- authentication or authorization bypass
- privilege escalation
- remote code execution
- command injection
- SQL injection
- SSRF
- insecure default configuration with real security impact
- secrets exposure
- vulnerabilities in scan, credential, notification, or admin-related functionality

## Out of Scope

The following usually do **not** count as reportable vulnerabilities unless they lead to real security impact:

- best-practice suggestions without exploit path
- missing hardening recommendations only
- self-XSS without privilege impact
- denial of service requiring unrealistic resources
- vulnerabilities in unsupported or heavily modified deployments

## Handling Sensitive Data

Please avoid including real passwords, tokens, private keys, or production secrets in reports.

If redaction is possible, prefer redacted examples.

## Update Guidance

If a security fix is released:

- update to the latest supported version as soon as practical
- review release notes carefully
- back up your instance before updating, especially when database-related changes are involved
