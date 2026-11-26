# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Terraform state as `terraform show -json` prints it (never the source files: state holds
what actually exists).

Databases, queues, buckets, caches and DNS records become resources; resources of a SaaS
provider the catalog knows say that product is in use. Every attribute marked sensitive, and
every value that looks like a secret, is dropped and counted before anything is kept; users,
memberships and other resources about people are skipped whole.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

from mirrordimensions.importers import Fact, ImportResult
from mirrordimensions.importers._common import fact, product, subject_for
from mirrordimensions.importers.scrub import person_like, secret_like

CATEGORIES: dict[str, tuple[str, ...]] = {
    "database": (
        "aws_db_instance",
        "aws_rds_cluster",
        "aws_dynamodb_table",
        "google_sql_database_instance",
        "google_spanner_instance",
        "azurerm_postgresql_flexible_server",
        "azurerm_mysql_flexible_server",
        "azurerm_mssql_server",
        "azurerm_cosmosdb_account",
    ),
    "queue": (
        "aws_sqs_queue",
        "aws_sns_topic",
        "aws_kinesis_stream",
        "aws_msk_cluster",
        "google_pubsub_topic",
        "azurerm_servicebus_queue",
        "azurerm_servicebus_topic",
        "azurerm_eventhub",
    ),
    "bucket": (
        "aws_s3_bucket",
        "google_storage_bucket",
        "azurerm_storage_container",
        "azurerm_storage_account",
    ),
    "cache": (
        "aws_elasticache_cluster",
        "aws_elasticache_replication_group",
        "google_redis_instance",
        "azurerm_redis_cache",
    ),
    "dns": (
        "aws_route53_record",
        "google_dns_record_set",
        "cloudflare_record",
        "cloudflare_dns_record",
        "azurerm_dns_a_record",
        "azurerm_dns_cname_record",
    ),
}
CATEGORY = {t: c for c, types in CATEGORIES.items() for t in types}
NAME_KEYS = (
    "name",
    "identifier",
    "cluster_identifier",
    "bucket",
    "topic",
    "queue_name",
    "replication_group_id",
    "cluster_id",
)
ENGINE_KEYS = ("engine", "database_version", "engine_version")
PEOPLE_TYPES = re.compile(
    r"(user|membership|member|collaborator|login_profile|invitation|people|person)", re.I
)
CLOUD_PROVIDERS = (
    "aws",
    "google",
    "google-beta",
    "azurerm",
    "azuread",
    "cloudflare",
    "random",
    "null",
    "tls",
    "time",
    "local",
    "kubernetes",
    "helm",
)


class Terraform:
    name = "terraform"
    label = "Terraform state"

    def detect(self, path: Path, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        doc = cast(dict[str, Any], data)
        values = doc.get("values")
        return "terraform_version" in doc and (
            values is None or (isinstance(values, dict) and "root_module" in values)
        )

    def read(self, path: Path, data: Any) -> ImportResult:
        doc = cast(dict[str, Any], data)
        out = ImportResult(importer=self.name, file=path.name)
        values = cast(dict[str, Any], doc.get("values") or {})
        for name, output in cast(dict[str, Any], values.get("outputs") or {}).items():
            # Outputs are not read; sensitive ones are counted with the secrets skipped.
            if cast(dict[str, Any], output).get("sensitive"):
                out.skipped_secrets += 1
            del name
        kept = 0
        for resource in _resources(cast(dict[str, Any], values.get("root_module") or {})):
            if resource.get("mode", "managed") != "managed":
                continue
            facts = self._resource(resource, path.name, out)
            kept += bool(facts)
            out.facts += facts
        out.summary = (
            f"{kept} resource(s) kept of {kept + sum(out.skipped.values()) + out.skipped_people}"
        )
        return out

    def _resource(self, r: dict[str, Any], file: str, out: ImportResult) -> list[Fact]:
        kind = str(r.get("type", ""))
        address = str(r.get("address", kind))
        attrs = cast(dict[str, Any], r.get("values") or {})
        mask: Any = r.get("sensitive_values") or {}
        if PEOPLE_TYPES.search(kind):
            out.skipped_people += 1
            return []
        out.skipped_secrets += _count_dropped(attrs, mask)
        safe = {
            k: v
            for k, v in attrs.items()
            if isinstance(v, str)
            and not _masked(mask, k)
            and not secret_like(v, k)
            and not person_like(v, k)
        }
        category = CATEGORY.get(kind)
        if category == "dns":
            host = safe.get("fqdn") or safe.get("name") or ""
            host = host.rstrip(".").lower()
            if "." not in host:
                out.skipped["dns records without a full name"] = (
                    out.skipped.get("dns records without a full name", 0) + 1
                )
                return []
            return [
                fact(
                    self.name,
                    file,
                    address,
                    "resource",
                    f"dns:{host}",
                    {"category": "dns", "hostname": host, "type": kind},
                )
            ]
        if category is not None:
            label = next((safe[k] for k in NAME_KEYS if safe.get(k)), str(r.get("name", kind)))
            value: dict[str, Any] = {"category": category, "name": label, "type": kind}
            engine = next((safe[k] for k in ENGINE_KEYS if safe.get(k)), None)
            if engine:
                value["engine"] = engine
            return [fact(self.name, file, address, "resource", f"{category}:{label}", value)]
        provider = str(r.get("provider_name", "")).rsplit("/", 1)[-1]
        if provider and provider not in CLOUD_PROVIDERS:
            entry = product(provider)
            if entry is not None:
                return [
                    fact(
                        self.name,
                        file,
                        address,
                        "system",
                        subject_for(entry, provider),
                        {
                            "product": entry.slug,
                            "name": entry.name,
                            "via": f"Terraform provider {provider}",
                        },
                        confidence="derived",
                    )
                ]
        out.skipped["other resources"] = out.skipped.get("other resources", 0) + 1
        return []


def _resources(module: dict[str, Any]) -> list[dict[str, Any]]:
    found = list(cast(list[dict[str, Any]], module.get("resources") or []))
    for child in cast(list[dict[str, Any]], module.get("child_modules") or []):
        found += _resources(child)
    return found


def _masked(mask: Any, key: str) -> bool:
    """Whether `sensitive_values` marks this attribute, or anything inside it, sensitive."""
    if not isinstance(mask, dict):
        return False
    return _any_true(cast(dict[str, Any], mask).get(key))


def _any_true(mask: Any) -> bool:
    if mask is True:
        return True
    if isinstance(mask, dict):
        return any(_any_true(v) for v in cast(dict[str, Any], mask).values())
    if isinstance(mask, list):
        return any(_any_true(v) for v in cast(list[Any], mask))
    return False


def _count_dropped(attrs: dict[str, Any], mask: Any, name: str = "") -> int:
    """Attributes dropped as secret: sensitive per the mask, or secret-looking by name or value."""
    count = 0
    for key, value in attrs.items():
        sub = cast(dict[str, Any], mask).get(key) if isinstance(mask, dict) else None
        if sub is True:
            count += 1
        elif isinstance(value, dict):
            count += _count_dropped(cast(dict[str, Any], value), sub, key)
        elif isinstance(value, list):
            for i, item in enumerate(cast(list[Any], value)):
                inner = (
                    cast(list[Any], sub)[i]
                    if isinstance(sub, list) and i < len(cast(list[Any], sub))
                    else None
                )
                if inner is True:
                    count += 1
                elif isinstance(item, dict):
                    count += _count_dropped(cast(dict[str, Any], item), inner, key)
                elif isinstance(item, str) and secret_like(item, key):
                    count += 1
        elif isinstance(value, str) and value and secret_like(value, key or name):
            count += 1
    return count
