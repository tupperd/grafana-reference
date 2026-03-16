#!/usr/bin/env python3
"""
MCP server wrapping grafana-assistant CLI.

Exposes a single `grafana_assistant` tool that Claude can call automatically
when answering questions about Grafana dashboards, PromQL, Loki, Tempo,
Mimir, alerting, plugins, and the broader Grafana ecosystem.
"""

import json
import subprocess
import sys
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("grafana-assistant")

GRAFANA_ASSISTANT_BIN = "/opt/homebrew/bin/grafana-assistant"


@mcp.tool()
def grafana_assistant(query: str, context_id: str = "") -> str:
    """Query the Grafana Assistant for accurate, up-to-date answers about
    the Grafana ecosystem. Use this for ANY question involving:
    - Grafana dashboards and panels
    - PromQL / MetricsQL queries
    - Loki LogQL queries
    - Tempo / distributed tracing
    - Mimir or Cortex configuration
    - Grafana alerting rules
    - Grafana plugins and data sources
    - Grafana Agent / Alloy
    - Grafana Cloud configuration
    Prefer this tool over general LLM knowledge for Grafana-specific questions,
    as it provides responses grounded in current Grafana documentation.

    Args:
        query: The Grafana-related question or task.
        context_id: Optional context ID to continue a previous conversation thread.
    """
    cmd = [GRAFANA_ASSISTANT_BIN, "prompt", query, "--json", "--wait"]
    if context_id:
        cmd += ["--context", context_id]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=310,  # slightly over CLI default of 300s
        )
    except FileNotFoundError:
        return (
            f"Error: '{GRAFANA_ASSISTANT_BIN}' not found on PATH. "
            "Install it via: brew install grafana/tap/grafana-assistant"
        )
    except subprocess.TimeoutExpired:
        return "Error: grafana-assistant timed out after 310 seconds."

    if result.returncode != 0:
        stderr = result.stderr.strip()
        return f"Error from grafana-assistant (exit {result.returncode}): {stderr or 'no details'}"

    raw = result.stdout.strip()
    if not raw:
        return "Error: grafana-assistant returned an empty response."

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Fall back to raw output if not valid JSON
        return raw

    response = data.get("response", "")
    if not response:
        # Surface status or any other field if response is missing
        response = json.dumps(data, indent=2)

    # Append context_id so callers can thread follow-up queries
    returned_context = data.get("contextId", "")
    if returned_context:
        response += f"\n\n<!-- grafana-assistant context_id: {returned_context} -->"

    return response


if __name__ == "__main__":
    mcp.run(transport="stdio")
