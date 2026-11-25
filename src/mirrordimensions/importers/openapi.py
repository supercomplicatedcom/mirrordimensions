# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""An OpenAPI 3 description (YAML or JSON) of an API the agent calls.

The API's title names the product (through the catalog) or, failing that, an internal
service; its first absolute server URL is the production hostname; each operation is an
endpoint. Contact details and descriptions are not read: only titles, servers, methods,
paths, operation ids and summaries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from mirrordimensions.importers import ImportResult
from mirrordimensions.importers._common import fact, host_of, product, subject_for

METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


class OpenApi:
    name = "openapi"
    label = "API specification"

    def detect(self, path: Path, data: Any) -> bool:
        return isinstance(data, dict) and str(
            cast(dict[str, Any], data).get("openapi", "")
        ).startswith("3.")

    def read(self, path: Path, data: Any) -> ImportResult:
        doc = cast(dict[str, Any], data)
        title = str(cast(dict[str, Any], doc.get("info") or {}).get("title") or path.stem)
        entry = product(title)
        subject = subject_for(entry, title)
        out = ImportResult(importer=self.name, file=path.name)
        system: dict[str, Any] = {"name": entry.name if entry else title}
        if entry is not None:
            system["product"] = entry.slug
        else:
            system["kind"] = "internal-service"
        out.facts.append(fact(self.name, path.name, "info.title", "system", subject, system))
        for i, server in enumerate(cast(list[dict[str, Any]], doc.get("servers") or [])):
            url = str(server.get("url", ""))
            for var, spec in cast(dict[str, Any], server.get("variables") or {}).items():
                url = url.replace(
                    "{" + var + "}", str(cast(dict[str, Any], spec).get("default", ""))
                )
            found = host_of(url)
            if found:
                out.facts.append(
                    fact(
                        self.name,
                        path.name,
                        f"servers[{i}].url",
                        "hostname",
                        subject,
                        {"hostname": found[0], "base_path": found[1]},
                    )
                )
                break
        count = 0
        for route, item in sorted(cast(dict[str, Any], doc.get("paths") or {}).items()):
            path_item = cast(dict[str, Any], item or {})
            for method in METHODS:
                if method not in path_item:
                    continue
                op = cast(dict[str, Any], path_item.get(method) or {})
                value = {"method": method.upper(), "path": route}
                if op.get("operationId"):
                    value["operation"] = str(op["operationId"])
                if op.get("summary"):
                    value["summary"] = str(op["summary"])
                out.facts.append(
                    fact(
                        self.name, path.name, f"paths.{route}.{method}", "endpoint", subject, value
                    )
                )
                count += 1
        out.summary = f"{count} endpoint(s) of {system['name']}"
        return out
