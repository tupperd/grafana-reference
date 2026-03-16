# Grafana Assistant MCP Server

An MCP (Model Context Protocol) server that wraps the `grafana-assistant` CLI, giving Claude accurate, documentation-grounded answers about the Grafana ecosystem.

## What it does

Exposes a single `grafana_assistant` tool that Claude calls automatically when answering questions about:

- Grafana dashboards and panels
- PromQL / MetricsQL / LogQL queries
- Loki, Tempo, Mimir, Cortex
- Grafana alerting rules
- Grafana Agent / Alloy
- Grafana plugins and data sources
- Grafana Cloud configuration

## Prerequisites

1. **Install the Grafana Assistant CLI:**

   ```bash
   brew install grafana/tap/grafana-assistant
   ```

2. **Set up the Python virtual environment:**

   ```bash
   cd assistant-cli-mcp
   python3 -m venv .venv
   .venv/bin/pip install -e .
   ```

## Registering with Claude Code

Use `claude mcp add` with one of three scopes depending on your needs.

### Local scope (this project only, private to you)

Default scope — useful while testing or if the server is only relevant to this repo.

```bash
claude mcp add grafana-assistant \
  /Users/davidtupper/playground/grafana-reference/assistant-cli-mcp/.venv/bin/python \
  /Users/davidtupper/playground/grafana-reference/assistant-cli-mcp/server.py
```

Config is stored in `~/.claude.json` under the project's entry. Not shared with teammates.

### Project scope (shared with your team)

Saves config to `.mcp.json` in the project root. Commit that file to share the server with everyone on the repo.

```bash
claude mcp add --scope project grafana-assistant \
  /path/to/assistant-cli-mcp/.venv/bin/python \
  /path/to/assistant-cli-mcp/server.py
```

> **Note:** Each team member still needs the `grafana-assistant` CLI and the `.venv` set up locally. Claude Code will prompt each user to approve the project-scoped server before first use.

### User scope (all projects, private to you)

Makes the server available in every Claude Code session on your machine — no need to re-register per project.

```bash
claude mcp add --scope user grafana-assistant \
  /Users/davidtupper/playground/grafana-reference/assistant-cli-mcp/.venv/bin/python \
  /Users/davidtupper/playground/grafana-reference/assistant-cli-mcp/server.py
```

Config is stored in `~/.claude.json` at the top level.

## Verifying the setup

```bash
# Check status and scope
claude mcp get grafana-assistant

# List all registered servers
claude mcp list
```

## Removing or changing scope

```bash
# Remove from local scope
claude mcp remove grafana-assistant -s local

# Remove from user scope
claude mcp remove grafana-assistant -s user

# Remove from project scope
claude mcp remove grafana-assistant -s project
```

## Scope comparison

| Scope | Stored in | Who can use it | Version controlled |
|-------|-----------|----------------|--------------------|
| `local` | `~/.claude.json` (per-project) | You, this project only | No |
| `project` | `.mcp.json` (repo root) | Anyone with the repo | Yes |
| `user` | `~/.claude.json` (global) | You, all projects | No |

Precedence when the same name exists at multiple scopes: **local > project > user**.
