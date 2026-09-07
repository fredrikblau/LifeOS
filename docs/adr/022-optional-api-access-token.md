# ADR-022: The API May Require a Shared Token

**Status:** Complete
**Last Updated:** 2026-09-07
**Decision:** Accepted

## Context

LifeOS has never authenticated anything. That was a coherent choice while the
deployment story was "a laptop, or a host on your tailnet": the network *was*
the perimeter, and the CORS comment in `api/main.py` says so outright — "this
app has no authentication of its own." Every internal caller leans on that.
The watchdogs, the sync scripts, `mcp_server.py`, and the Telegram worker all
address the API over localhost with no credential.

The assumption stops holding the moment the same process runs on a VPS with a
public IP, which is the deployment shape this fork targets (Telegram-first,
always-on, no laptop required). A 2026-09 audit of exactly such a deployment
found the API bound to `0.0.0.0:8000` on a host with no firewall, and the
access log showed unrelated hosts on the open internet had already fetched
`/api/memories` and walked the `/crm`, `/crm/family` and `/crm/relationship`
pages. Nothing was misconfigured relative to the documentation; the
documentation simply assumed a private network.

Two properties had to hold at once:

1. **An existing private deployment must not change behaviour.** Anyone
   running on a tailnet today has clients — browser, whisper-relay, MCP —
   that send no credential and must keep working untouched.
2. **The fix cannot depend on the operator having a reverse proxy.** The
   deployment that was exposed had no nginx, no Caddy, no TLS. A solution
   that only exists as "put it behind something else" would not have
   protected it.

## Decision

**`LIFEOS_API_TOKEN` gates the whole API, and is inert unless set.**

`api/middleware/access_token.py` adds one ASGI middleware:

- Unset or blank (the default) — every request passes untouched. A tailnet
  deployment is byte-for-byte unchanged, satisfying property 1 by
  construction rather than by careful exemption lists.
- Set — a non-loopback caller must present the token, as an `Authorization:
  Bearer` credential, an `X-LifeOS-Token` header, a `lifeos_token` cookie, or
  a one-time `?token=` query parameter that is then stored as the cookie so
  the browser UI needs it in a URL exactly once. Comparison is
  `secrets.compare_digest`, so a wrong guess leaks no prefix through timing.
- **Loopback callers are always exempt.** This is what keeps the internal
  callers working with no change at all, and it costs nothing: anything
  already running as the LifeOS user can read the SQLite and Chroma files
  directly, so requiring a token from localhost would be ceremony, not
  security.
- `/health` stays open even when the token is set, so an out-of-band watchdog
  can still distinguish "down" from "locked".

Alongside it, `warn_if_api_is_publicly_reachable()` logs a loud startup
warning when the API binds an address wider than localhost with no token set.
It changes no behaviour; it makes the exposure visible at startup instead of
in an access log months later.

**Scope:** one shared secret, one user. This is a perimeter for a
single-operator system, not a login system — there are no accounts, sessions,
roles, or rotation. It is also explicitly *not* a substitute for keeping the
port off the public internet; the guidance is to do both.

## Rationale

- **Default-off is the only way to add auth to a system whose every internal
  caller predates it.** An opt-in gate needs no audit of which of the 200-odd
  endpoints each internal script touches; an opt-out one would have needed
  exactly that audit, and would have broken someone the first time it was
  wrong.
- **Loopback exemption is the honest boundary.** The threat is the internet,
  not the machine. Drawing the line where the actual privilege boundary
  already sits keeps the rule short enough to reason about.
- **The query-parameter-then-cookie path is what makes it usable from a
  browser.** The web UI issues its own `fetch()` calls to root-relative paths
  with no opportunity to attach a header. Without the cookie step, enabling
  the token would have meant "the API is protected and the UI no longer
  works," which is the kind of tradeoff that gets a security feature turned
  back off.

## Alternatives Considered

### Require a reverse proxy with HTTP basic auth

**Rejected because:** it does not protect the deployment that motivated the
change. The exposed host had no proxy, and adding "install and configure
nginx" to the setup path makes the secure configuration the harder one — the
reliable way to end up with neither.

### Bind to `127.0.0.1` by default

**Rejected as the primary fix because:** it silently breaks every remote
surface (the web UI over a VPN or tailnet) with no error a user can act on,
and it is trivially undone by the first person who wants the UI back. It is
still the right *option* — `LIFEOS_HOST` already exposes it, and the new
startup warning points at it — but as one of three remedies the warning
names, not as a change of default.

### Real per-user authentication (accounts, sessions, OAuth)

**Rejected because:** LifeOS is single-operator by design; every other part
of the system — the vault, the memory store, the personas — assumes exactly
one person. Accounts would be a large surface added to protect a population
of one.

## Consequences

### Positive

- A public-IP deployment has a first-party way to stop the internet reading a
  complete personal record, with no extra infrastructure.
- The startup warning turns a silent, invisible exposure into something the
  operator is told about the first time the server starts.

### Negative

- **A shared token has no revocation story beyond changing it**, which logs
  out every client at once. Acceptable for one operator; not a model that
  extends.
- **The token is exempt on loopback, so anything that can reach localhost is
  still fully trusted** — including, for example, another user account on the
  same host. The threat model stops at the machine boundary.
- **Enabling it does not retroactively secure a port that has already been
  scraped.** An operator in that position has to treat the data as disclosed;
  the middleware only stops the next request.

## Related Documents

### Operational

- [Configuration](../guides/configuration.md) — `LIFEOS_API_TOKEN`, `LIFEOS_HOST`

### Code References

- `api/middleware/access_token.py` — `AccessTokenMiddleware`
- `api/main.py` — middleware registration, `warn_if_api_is_publicly_reachable()`
- `tests/test_access_token_middleware.py`
