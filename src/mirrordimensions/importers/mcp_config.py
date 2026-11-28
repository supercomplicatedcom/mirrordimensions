# SPDX-License-Identifier: Apache-2.0
"""The agent's MCP client configuration: `mcpServers` (Claude Code's `.mcp.json`, and the
portable format other clients share) or `servers` (VS Code's `mcp.json`).

A remote server (`url`) becomes an MCP server system with its production hostname. A server
on the agent's own machine (`command`) is part of the agent; the product it serves and the
production URLs in its arguments or variables say which systems the agent works in.
Header values and secret-looking variables are never read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from mirrordimensions.importers import Fact, ImportResult
from mirrordimensions.importers._common import fact, host_of, product, subject_for
from mirrordimensions.importers.scrub import secret_like


class McpConfig:
    name = "mcp-config"
    label = "Agent tool configuration"

    def detect(self, path: Path, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        servers = _servers(cast(dict[str, Any], data))
        return bool(servers) and all(
            isinstance(v, dict) and ("url" in v or "command" in v) for v in servers.values()
        )

    def read(self, path: Path, data: Any) -> ImportResult:
        doc = cast(dict[str, Any], data)
        key = "mcpServers" if "mcpServers" in doc else "servers"
        out = ImportResult(importer=self.name, file=path.name)
        remote = local = 0
        for name, raw in sorted(_servers(doc).items()):
            server = cast(dict[str, Any], raw)
            where = f"{key}.{name}"
            # Header values carry credentials; the names alone say nothing a fact needs.
            out.skipped_secrets += len(cast(dict[str, Any], server.get("headers") or {}))
            if "url" in server:
                remote += 1
                out.facts += self._remote(name, str(server["url"]), where, path.name, out)
            else:
                local += 1
                out.facts += self._local(name, server, where, path.name, out)
        out.summary = (
            f"{remote + local} tool server(s): {remote} remote, {local} on the agent's machine"
        )
        return out

    def _remote(self, name: str, url: str, where: str, file: str, out: ImportResult) -> list[Fact]:
        subject = f"mcp:{name}"
        found = host_of(url)
        facts = [
            fact(self.name, file, where, "system", subject, {"kind": "mcp-server", "name": name})
        ]
        if found is None:
            out.skipped["url not resolvable"] = out.skipped.get("url not resolvable", 0) + 1
            return facts
        host, endpoint = found
        facts.append(
            fact(
                self.name,
                file,
                f"{where}.url",
                "hostname",
                subject,
                {"hostname": host, "endpoint": endpoint},
            )
        )
        return facts

    def _local(
        self, name: str, server: dict[str, Any], where: str, file: str, out: ImportResult
    ) -> list[Fact]:
        args = [str(a) for a in cast(list[Any], server.get("args") or [])]
        env = {str(k): str(v) for k, v in cast(dict[str, Any], server.get("env") or {}).items()}
        entry = next(
            (e for e in (product(n) for n in (name, *args, str(server.get("command", "")))) if e),
            None,
        )
        if entry is None:
            out.skipped["local servers for no known product"] = (
                out.skipped.get("local servers for no known product", 0) + 1
            )
            return []
        subject = subject_for(entry, name)
        facts = [
            fact(
                self.name,
                file,
                where,
                "system",
                subject,
                {
                    "product": entry.slug,
                    "name": entry.name,
                    "via": "a tool server on the agent's machine",
                },
                confidence="derived",
            )
        ]
        values = [(f"{where}.args[{i}]", "", a) for i, a in enumerate(args)]
        values += [(f"{where}.env.{k}", k, v) for k, v in sorted(env.items())]
        for location, var, value in values:
            if secret_like(value, var):
                out.skipped_secrets += 1
                continue
            text = value.split("=", 1)[-1] if value.startswith("--") else value
            found = host_of(text)
            if found:
                facts.append(
                    fact(self.name, file, location, "hostname", subject, {"hostname": found[0]})
                )
        return facts


def _servers(doc: dict[str, Any]) -> dict[str, Any]:
    servers = doc.get("mcpServers", doc.get("servers"))
    return cast(dict[str, Any], servers) if isinstance(servers, dict) else {}
