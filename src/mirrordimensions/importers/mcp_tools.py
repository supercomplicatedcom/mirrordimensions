# SPDX-License-Identifier: Apache-2.0
"""An MCP server's exported tool list: the result of `tools/list`, with the server's
`serverInfo`, protocol versions and instructions as its `initialize` reported them.

It belongs to the configured server with the same name: the file `<server>.tools.json`, or
`serverInfo.name`. Nothing is fetched from a real server; the export is the evidence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from mirrordimensions.importers import ImportResult
from mirrordimensions.importers._common import fact


class McpTools:
    name = "mcp-tools"
    label = "Exported tool list"

    def detect(self, path: Path, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        tools = cast(dict[str, Any], data).get("tools")
        return isinstance(tools, list) and all(
            isinstance(t, dict) and "name" in t and "inputSchema" in t
            for t in cast(list[Any], tools)
        )

    def read(self, path: Path, data: Any) -> ImportResult:
        doc = cast(dict[str, Any], data)
        info = cast(dict[str, Any], doc.get("serverInfo") or {})
        stem = path.name.removesuffix(".json")
        name = (
            stem.removesuffix(".tools")
            if stem.endswith(".tools")
            else str(info.get("name") or stem)
        )
        subject = f"mcp:{name}"
        out = ImportResult(importer=self.name, file=path.name)
        server: dict[str, Any] = {"kind": "mcp-server", "name": name}
        if info.get("name") and info.get("version"):
            server["server_info"] = {"name": str(info["name"]), "version": str(info["version"])}
        if doc.get("protocolVersions"):
            server["protocol_versions"] = [str(v) for v in cast(list[Any], doc["protocolVersions"])]
        if doc.get("instructions"):
            server["instructions"] = str(doc["instructions"])
        out.facts.append(fact(self.name, path.name, "serverInfo", "system", subject, server))
        tools = cast(list[dict[str, Any]], doc.get("tools") or [])
        for i, tool in enumerate(tools):
            kept = {
                k: tool[k]
                for k in (
                    "name",
                    "title",
                    "description",
                    "inputSchema",
                    "outputSchema",
                    "annotations",
                )
                if k in tool
            }
            out.facts.append(fact(self.name, path.name, f"tools[{i}]", "tool", subject, kept))
        out.summary = f"{len(tools)} tool(s) of {name}"
        return out
