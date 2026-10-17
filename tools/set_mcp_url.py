#!/usr/bin/env python3
"""Write the Wayfare MCP server URL into the Codex plugin.
Run after `npx wrangler deploy` in mcp-server/:
    python3 tools/set_mcp_url.py https://wayfare-mcp.<your-subdomain>.workers.dev/mcp
Writes plugins/wayfare/mcp.json (portable format) and plugins/wayfare/.mcp.json (Codex)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "wayfare"
PLACEHOLDER = "https://wayfare-mcp.YOUR-SUBDOMAIN.workers.dev/mcp"
NAME = "wayfare"


def write(url: str) -> None:
    (PLUGIN / "mcp.json").write_text(json.dumps({
        "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
        "mcpServers": {NAME: {"type": "streamable-http", "url": url}},
    }, indent=2) + "\n", encoding="utf-8")
    (PLUGIN / ".mcp.json").write_text(json.dumps({"mcpServers": {NAME: {"url": url}}}, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else PLACEHOLDER
    if url != PLACEHOLDER and not re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d+)?/mcp", url):
        print("The URL must be https://<host>/mcp")
        return 1
    write(url)
    print(f"MCP server URL set to {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
