# IRM Personal Notification Rules Audit

Stateless, read-only audit of Grafana OnCall **personal notification rules**
across every user on a stack. It catches notification-config drift: on-call
engineers who never set up notifications, or who changed them to something that
no longer follows best practice (and would silently miss a page).

Python 3, standard library only. No `pip install`.

## Policy

A user is **compliant** only if all three checks pass:

| Check | Meaning |
|---|---|
| `has_rules` | The **default** notification chain is non-empty. |
| `two_methods` | The default chain uses **>= N distinct notification methods** (distinct `type`, ignoring `wait`). Redundancy: don't rely on a single channel. `N` defaults to 2 (`--min-methods`). |
| `important_configured` | The **important** chain (`important=true`) is non-empty. |

The "important" chain is OnCall's separate, more aggressive path for
high-urgency alerts; an empty one means important alerts fall back to the
default behaviour.

## Auth (read this first)

The `personal_notification_rules` endpoint is a **user-settings** endpoint. It
**rejects Grafana service-account tokens** (returns `403 "Invalid token"`),
even though those same tokens work for `users`, `alert_groups`, and
`schedules`. You therefore need a **dedicated OnCall API key**.

1. In your stack, go to **IRM > Settings > API Keys** (a.k.a. API Tokens) and
   create a key with admin scope.
2. `cp .env.example .env` and set `ONCALL_API_KEY`.
3. (Optional) set `ONCALL_API_URL`. If you leave it blank, the script
   auto-discovers it from your active `gcx` context by reading the IRM plugin
   settings (`onCallApiUrl`), so the only thing you must provide is the key.

The OnCall API key is sent as a raw `Authorization: <key>` header (no `Bearer`).
The `gcx` service-account token, when used, is only read to discover the API
URL, never for the rules calls.

## Usage

```bash
cd irm-notification-policy-drift-audit
python3 audit_notification_rules.py            # audit active gcx context
python3 audit_notification_rules.py --context my-stack
python3 audit_notification_rules.py --verbose  # show compliant users too
python3 audit_notification_rules.py --min-methods 3
python3 audit_notification_rules.py --json out.json
```

Flags:

- `--context <name>` - gcx context to audit (default: active context).
- `--min-methods <n>` - distinct methods required in the default chain (default 2).
- `--env <path>` - path to the `.env` file (default: `./.env` next to the script).
- `--verbose` - include compliant users in the table.
- `--include-service-accounts` - audit Grafana service accounts too (skipped by default).
- `--json <path>` - also write the full machine-readable results.
- `--no-color` - disable ANSI color.

## Output

A summary banner (`M/N users compliant`) followed by a table of the
**non-compliant** users only (compliant users are collapsed to a count unless
`--verbose`). Each violation row shows the failed checks, the default chain's
distinct methods, and the important chain step count.

## Exit codes (cron-friendly)

| Code | Meaning |
|---|---|
| `0` | All users compliant. |
| `1` | One or more users non-compliant. |
| `2` | Hard error (missing key, auth failure, network, bad URL). |

Run it on a schedule and alert on a non-zero exit. Example cron line:

```cron
0 8 * * 1  cd /path/to/irm-notification-policy-drift-audit && /usr/bin/python3 audit_notification_rules.py --no-color >> audit.log 2>&1 || echo "OnCall notif audit found drift" | mail -s "OnCall audit" you@example.com
```

## Scope notes

- **Skips Grafana service accounts by default** (login prefixed `sa-`, or no
  real email, e.g. `sa-1-gcx`) since they are bots, not on-call humans. The
  banner reports how many were skipped. Pass `--include-service-accounts` to
  audit them too.
- Point-in-time only. It does not store snapshots or diff against a previous
  run (change-over-time drift is out of scope for this version).
- Read-only. It never modifies notification rules.
