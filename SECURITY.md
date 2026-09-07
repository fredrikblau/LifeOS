# Security Policy

LifeOS holds a complete personal record — emails, messages, contacts,
finances, health data, private notes — and runs with real authority over
files, APIs and, through the agent worker, code execution. Treat a
vulnerability here as you would one in a password manager.

## Reporting

Report privately through
[GitHub's security advisories](https://github.com/fredrikblau/LifeOS/security/advisories/new).
Please don't open a public issue for anything exploitable.

Include what an attacker could reach, the smallest reproduction you have, and
the version or commit. **Redact your own data** — a proof of concept should
never carry real memories, contacts or tokens.

## What counts

Anything that lets someone who should not have it read or change personal
data, or make LifeOS act on their behalf. In particular:

- **Unauthenticated access.** The API has no login of its own. `LIFEOS_API_TOKEN`
  is the perimeter when one is set ([ADR-022](docs/adr/022-optional-api-access-token.md));
  a way around it is a vulnerability.
- **Prompt injection through ingested content.** Emails, web pages, forwarded
  messages and documents are *data*, never instructions. Content that induces
  the assistant to act — send mail, run a tool, exfiltrate context — is a
  vulnerability, not a curiosity.
- **Data leaving the machine unexpectedly.** Anything that sends personal data
  anywhere the operator did not configure.
- **Secrets in logs, errors or committed files.**
- **Actions taken without the confirmation the system promises** — email
  sending, calendar writes and agent spend all require explicit approval.

## Deploying it safely

The single most common real-world exposure is the simplest one: **the API
reachable from the internet.** It serves the entire personal record and, by
default, requires nothing to read it. If the host has a public IP:

- set `LIFEOS_API_TOKEN`, **and**
- keep the port off the internet — bind `LIFEOS_HOST=127.0.0.1`, firewall it,
  or put it behind a VPN.

The server logs a warning at startup when it binds a wide address with no
token set. Do not ignore it.

## Scope

This project is maintained by one person as a personal system. There is no
paid bounty and no response-time guarantee. Fixes for issues that also affect
[nbramia/LifeOS](https://github.com/nbramia/LifeOS) will be reported upstream.
