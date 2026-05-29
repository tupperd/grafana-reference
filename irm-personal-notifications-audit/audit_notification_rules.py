#!/usr/bin/env python3
"""
Audit Grafana OnCall personal notification rules across all users on a stack.

Catches notification-config drift: on-call engineers who never configured
their personal notification rules, or who changed them to something that no
longer follows best practice. Point-in-time, stateless, read-only.

Policy (per user, all must pass to be compliant):
  1. has_rules            - the DEFAULT notification chain is non-empty.
  2. two_methods          - the DEFAULT chain uses >= --min-methods distinct
                            notification methods (distinct `type`, ignoring
                            `wait`). Redundancy: never rely on a single channel.
  3. important_configured - the IMPORTANT chain (important=true) is non-empty.

Auth model (see README.md):
  - personal_notification_rules is a user-settings endpoint that REJECTS
    Grafana service-account tokens (403 "Invalid token"). It needs a dedicated
    OnCall API key. Set ONCALL_API_KEY in .env.
  - The OnCall API base URL is auto-discovered from the IRM plugin settings
    using your active gcx context's token, or you can pin it via ONCALL_API_URL.

Exit codes: 0 = all compliant, 1 = one or more violations, 2 = hard error.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

DEFAULT_MIN_METHODS = 2
WAIT_TYPE = "wait"
PAGE_RETRY_MAX = 4
HTTP_TIMEOUT = 30


class ApiError(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


def curl_get_json(url, headers, timeout=HTTP_TIMEOUT):
    """GET via curl (uses the system trust store; avoids Python's macOS TLS gap).

    Secret headers are passed on curl's stdin (-K -) so they never appear in
    the process list. Returns (status_code, parsed_json_or_None).
    """
    # curl config-file syntax: one `name = value` directive per line.
    config = [
        "silent",
        "show-error",
        f"max-time = {timeout}",
        'write-out = "\\n%{http_code}"',
    ]
    for key, val in headers.items():
        config.append(f'header = "{key}: {val}"')
    config.append(f'url = "{url}"')
    proc = subprocess.run(
        ["curl", "-K", "-"],
        input="\n".join(config),
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise ApiError(f"curl failed for {url}: {proc.stderr.strip()}", None)
    out = proc.stdout
    nl = out.rfind("\n")
    body = out[:nl] if nl >= 0 else out
    try:
        code = int(out[nl + 1:].strip())
    except ValueError:
        code = None
    try:
        data = json.loads(body) if body.strip() else None
    except (json.JSONDecodeError, ValueError):
        data = None
    return code, data, body


# --------------------------------------------------------------------------- #
# Config resolution
# --------------------------------------------------------------------------- #
def load_env(path):
    """Minimal .env loader: KEY=VALUE lines, '#' comments, optional quotes."""
    env = {}
    if not path or not os.path.exists(path):
        return env
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def gcx_current_context():
    out = subprocess.run(
        ["gcx", "config", "current-context"],
        capture_output=True, text=True,
    )
    return out.stdout.strip() or None


def gcx_config_file():
    """Resolve the user-scope gcx config file path via `gcx config path`."""
    out = subprocess.run(
        ["gcx", "config", "path"], capture_output=True, text=True,
    )
    try:
        entries = json.loads(out.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    user = [e for e in entries if e.get("type") == "user"]
    chosen = (user or entries)
    return chosen[0]["path"] if chosen else None


def read_gcx_context(context):
    """Return (server_url, token) for a gcx context by parsing its config file.

    The token is needed only to auto-discover the OnCall API URL.
    """
    path = gcx_config_file()
    if not path or not os.path.exists(path):
        return None, None
    text = open(path).read()
    # Slice out the named context block (2-space indented under `contexts:`).
    block_re = re.compile(
        r"^  " + re.escape(context) + r":\n(.*?)(?=^  \S|\Z)",
        re.S | re.M,
    )
    m = block_re.search(text)
    block = m.group(1) if m else text
    server = re.search(r"server:\s*(\S+)", block)
    token = re.search(r"token:\s*(\S+)", block)
    server_v = server.group(1).strip().strip('"').strip("'") if server else None
    token_v = token.group(1).strip().strip('"').strip("'") if token else None
    return server_v, token_v


def discover_oncall_api_url(server, token):
    """GET {server}/api/plugins/grafana-irm-app/settings -> jsonData.onCallApiUrl."""
    if not server or not token:
        return None
    url = server.rstrip("/") + "/api/plugins/grafana-irm-app/settings"
    try:
        code, data, _ = curl_get_json(url, {"Authorization": "Bearer " + token})
    except ApiError:
        return None
    if code != 200 or not isinstance(data, dict):
        return None
    return (data.get("jsonData") or {}).get("onCallApiUrl")


# --------------------------------------------------------------------------- #
# OnCall API client (uses the dedicated OnCall API key)
# --------------------------------------------------------------------------- #
class OnCallClient:
    def __init__(self, base_url, api_key):
        self.base = base_url.rstrip("/")
        self.api_key = api_key

    def _get(self, path, params=None):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"Authorization": self.api_key}
        backoff = 1.0
        for attempt in range(PAGE_RETRY_MAX):
            code, data, body = curl_get_json(url, headers)
            if code == 429 and attempt < PAGE_RETRY_MAX - 1:
                time.sleep(backoff)
                backoff *= 2
                continue
            if code != 200:
                raise ApiError(f"HTTP {code} on {url}\n  {body[:200]}", code)
            if data is None:
                raise ApiError(f"Non-JSON response on {url}\n  {body[:200]}", code)
            return data
        raise ApiError(f"Exhausted retries on {url}", None)

    def paginate(self, path, params=None):
        """Yield every result across all pages (follows `next`)."""
        params = dict(params or {})
        while True:
            page = self._get(path, params)
            for item in page.get("results", []):
                yield item
            nxt = page.get("next")
            if not nxt:
                break
            # `next` is an absolute URL; re-extract its query for the next call.
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(nxt).query))

    def list_users(self):
        return list(self.paginate("/api/v1/users/"))

    def notification_rules(self, user_id, important):
        return list(self.paginate(
            "/api/v1/personal_notification_rules/",
            {"user_id": user_id, "important": str(important).lower()},
        ))


# --------------------------------------------------------------------------- #
# Policy evaluation
# --------------------------------------------------------------------------- #
def is_service_account(user):
    """Grafana service accounts (not on-call humans).

    Grafana prefixes every service-account login with `sa-`, and they carry no
    real email address. Either signal is sufficient.
    """
    username = (user.get("username") or "").lower()
    email = user.get("email") or ""
    return username.startswith("sa-") or "@" not in email


def distinct_methods(rules):
    return sorted({r.get("type") for r in rules if r.get("type") != WAIT_TYPE})


def evaluate_user(default_rules, important_rules, min_methods):
    methods = distinct_methods(default_rules)
    checks = {
        "has_rules": len(default_rules) >= 1,
        "two_methods": len(methods) >= min_methods,
        "important_configured": len(important_rules) >= 1,
    }
    return {
        "compliant": all(checks.values()),
        "checks": checks,
        "failed": [k for k, ok in checks.items() if not ok],
        "default_methods": methods,
        "default_count": len(default_rules),
        "important_count": len(important_rules),
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def colorize(text, code, enabled):
    return f"\033[{code}m{text}\033[0m" if enabled else text


def render_report(results, min_methods, base_url, show_all, color, skipped_sa=0):
    total = len(results)
    compliant = [r for r in results if r["eval"]["compliant"]]
    violations = [r for r in results if not r["eval"]["compliant"]]
    pct = (len(compliant) / total * 100) if total else 0.0

    print()
    print(colorize("OnCall Personal Notification Rules Audit", "1", color))
    print(f"  Stack OnCall API : {base_url}")
    print(f"  Generated        : {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"  Policy           : has_rules, >= {min_methods} methods, important chain set")
    if skipped_sa:
        print(f"  Skipped          : {skipped_sa} service account(s)")
    banner = f"  Result           : {len(compliant)}/{total} users compliant ({pct:.0f}%)"
    print(colorize(banner, "32" if not violations else "33", color))
    print()

    rows = violations + (compliant if show_all else [])
    if not rows:
        print(colorize("  All users compliant. Nothing to flag.", "32", color))
        print()
        return

    headers = ["USER", "EMAIL", "FAILED CHECKS", "DEFAULT (methods)", "IMPORTANT"]
    table = []
    for r in rows:
        ev = r["eval"]
        failed = "OK" if ev["compliant"] else ",".join(ev["failed"])
        methods = ", ".join(ev["default_methods"]) or "(none)"
        default_cell = f"{ev['default_count']} steps [{methods}]"
        important_cell = f"{ev['important_count']} steps"
        table.append([
            r["username"] or "(unknown)",
            r["email"] or "",
            failed,
            default_cell,
            important_cell,
        ])

    widths = [len(h) for h in headers]
    for row in table:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt(cells, bold=False):
        line = "  " + "  ".join(c.ljust(widths[i]) for i, c in enumerate(cells))
        return colorize(line, "1", color) if bold else line

    print(fmt(headers, bold=True))
    print("  " + "  ".join("-" * w for w in widths))
    for r, row in zip(rows, table):
        ok = r["eval"]["compliant"]
        line = fmt(row)
        print(colorize(line, "32", color) if ok else colorize(line, "31", color))
    print()
    if not show_all and compliant:
        print(f"  ({len(compliant)} compliant users hidden; pass --verbose to show)")
        print()


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def die(msg, code=2):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def main():
    ap = argparse.ArgumentParser(description="Audit OnCall personal notification rules.")
    ap.add_argument("--context", help="gcx context to use (default: active context)")
    ap.add_argument("--min-methods", type=int, default=DEFAULT_MIN_METHODS,
                    help=f"distinct methods required in default chain (default {DEFAULT_MIN_METHODS})")
    ap.add_argument("--env", default=os.path.join(os.path.dirname(__file__), ".env"),
                    help="path to .env file (default: ./.env next to script)")
    ap.add_argument("--verbose", action="store_true", help="also show compliant users")
    ap.add_argument("--include-service-accounts", action="store_true",
                    help="audit Grafana service accounts too (skipped by default)")
    ap.add_argument("--json", metavar="PATH", help="write full results as JSON to PATH")
    ap.add_argument("--no-color", action="store_true", help="disable ANSI color")
    args = ap.parse_args()

    color = sys.stdout.isatty() and not args.no_color
    env = load_env(args.env)

    # OnCall API key is mandatory for the notification-rules endpoint.
    api_key = env.get("ONCALL_API_KEY") or os.environ.get("ONCALL_API_KEY")
    if not api_key:
        die(
            "ONCALL_API_KEY is not set.\n"
            "  personal_notification_rules requires a dedicated OnCall API key;\n"
            "  a Grafana service-account token returns 403 'Invalid token'.\n"
            "  Create one: IRM > Settings > API Keys (or API Tokens) in your stack,\n"
            "  then copy .env.example to .env and set ONCALL_API_KEY (and optionally\n"
            "  ONCALL_API_URL)."
        )

    # OnCall API base URL: explicit override, else auto-discover via gcx token.
    base_url = env.get("ONCALL_API_URL") or os.environ.get("ONCALL_API_URL")
    if not base_url:
        context = args.context or gcx_current_context()
        if not context:
            die("No ONCALL_API_URL set and no active gcx context to discover it from.")
        server, token = read_gcx_context(context)
        base_url = discover_oncall_api_url(server, token)
        if not base_url:
            die(
                f"Could not auto-discover the OnCall API URL from gcx context "
                f"'{context}'.\n  Set ONCALL_API_URL in .env (find it under "
                f"IRM > Settings > API)."
            )

    client = OnCallClient(base_url, api_key)

    # Pull users (works with the OnCall API key) and map id -> identity.
    try:
        users = client.list_users()
    except ApiError as exc:
        if exc.code == 403:
            die("403 listing users. Check the OnCall API key is valid and has "
                "admin scope.\n  " + str(exc))
        die(str(exc))

    skipped_sa = 0
    if not args.include_service_accounts:
        kept = [u for u in users if not is_service_account(u)]
        skipped_sa = len(users) - len(kept)
        users = kept

    results = []
    for u in users:
        uid = u.get("id")
        try:
            default_rules = client.notification_rules(uid, important=False)
            important_rules = client.notification_rules(uid, important=True)
        except ApiError as exc:
            if exc.code == 403:
                die("403 reading personal_notification_rules. The OnCall API key "
                    "lacks user-settings access\n  (or you used a service-account "
                    "token). " + str(exc))
            die(str(exc))
        ev = evaluate_user(default_rules, important_rules, args.min_methods)
        results.append({
            "user_id": uid,
            "username": u.get("username"),
            "email": u.get("email"),
            "eval": ev,
        })

    results.sort(key=lambda r: (r["eval"]["compliant"], (r["username"] or "").lower()))

    render_report(results, args.min_methods, base_url, args.verbose, color, skipped_sa)

    if args.json:
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "oncall_api_url": base_url,
            "policy": {"min_methods": args.min_methods},
            "summary": {
                "total": len(results),
                "compliant": sum(1 for r in results if r["eval"]["compliant"]),
                "skipped_service_accounts": skipped_sa,
            },
            "users": results,
        }
        with open(args.json, "w") as fh:
            json.dump(payload, fh, indent=2)
        print(f"  Wrote JSON results to {args.json}\n")

    violations = [r for r in results if not r["eval"]["compliant"]]
    sys.exit(1 if violations else 0)


if __name__ == "__main__":
    main()
