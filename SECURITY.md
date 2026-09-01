# Security policy

## Supported versions

PipeLens is currently pre-1.0. Security fixes are developed on `main` and included in the next release.
The latest published release is the only release line considered for backports.

| Version | Supported |
| --- | --- |
| `main` | Yes |
| Latest release | Yes |
| Older releases | No |

## Report a vulnerability privately

Do not open a public issue for a suspected vulnerability, exposed credential, private workflow log, or
personal data. Use
[GitHub private vulnerability reporting](https://github.com/sangmu1126/PipeLens/security/advisories/new)
instead.

Include only the information needed to reproduce and assess the issue:

- affected release, commit, component, and configuration;
- impact and the access level required to exploit it;
- minimal reproduction steps or a proof of concept;
- redacted logs, requests, or screenshots; and
- any known workaround.

Never include live GitHub App private keys, OAuth secrets, webhook secrets, session secrets, encryption
keys, access tokens, repository credentials, or unredacted user data. Revoke or rotate an exposed secret
before reporting it.

Do not commit realistic secret-shaped test values, even when they are inactive. Use explicit placeholders
such as `<redacted-token>` and inject test credentials at runtime. Every pull request is scanned with
Trivy's built-in secret rules in addition to GitHub secret scanning and push protection. A scan exception
requires a narrow, reviewed rule with a documented false-positive reason; never suppress a finding merely
because a validity check labels a credential inactive or unknown.

The maintainer will coordinate validation, remediation, release, and disclosure in the private advisory.
Please do not disclose the issue publicly until a coordinated disclosure time is agreed.

## Public security hardening reports

A defensive improvement without an exploitable vulnerability may use the normal bug report form. Remove
secrets and identifying workflow data first, and explain why public discussion is safe.
