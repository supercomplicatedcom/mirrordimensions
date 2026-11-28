# SPDX-License-Identifier: Apache-2.0
"""Twin adapters' configuration, without starting them."""

from __future__ import annotations

import json

from mirrordimensions.config.manifest import Manifest
from mirrordimensions.network import sandbox
from mirrordimensions.twins.base import get_twin
from mirrordimensions.twins.relay import _quote  # pyright: ignore[reportPrivateUsage]
from mirrordimensions.world.denylist import TELL_WORDS

MANIFEST = Manifest.model_validate(
    {
        "version": 1,
        "name": "northfield-ops",
        "company": {
            "name": "Northfield Logistics",
            "domain": "northfield-logistics.com",
            "seed": 48213,
        },
        "apps": [
            {"id": "code", "product": "gitea", "hostname": "git.northfield-logistics.com"},
            {"id": "chat", "product": "mattermost", "hostname": "chat.northfield-logistics.com"},
        ],
    }
)
SECRETS = {
    f"{app}:{k}": f"value-{k}"
    for app in ("code", "chat")
    for k in ("db_password", "admin_password", "user_password", "secret_key", "internal_token")
}


def _specs() -> dict[str, dict[str, object]]:
    plan = sandbox.plan_from(MANIFEST)
    return {
        s.name: {
            "env": s.env,
            "image": s.image,
            "platform": s.platform,
            "dns": s.dns,
            "networks": s.networks,
            "volumes": s.volumes,
        }
        for s in sandbox.specs(plan, [], [], SECRETS)
    }


def test_twins_replace_stubs_with_product_and_database() -> None:
    specs = _specs()
    assert {"app-01", "db-01", "app-02", "db-02", "ns2", "ops-01"} <= set(specs)
    assert "gitea/gitea" in str(specs["app-01"]["image"])
    assert "mattermost-team-edition" in str(specs["app-02"]["image"])


def test_mattermost_runs_amd64_under_emulation() -> None:
    assert _specs()["app-02"]["platform"] == "linux/amd64"


def test_twins_resolve_through_the_system_resolver_only() -> None:
    specs = _specs()
    for name in ("app-01", "db-01", "app-02", "db-02", "ops-01"):
        assert specs[name]["dns"] == ["10.41.0.53"], name
        assert list(specs[name]["networks"]) == [sandbox.APPS], name  # type: ignore[arg-type]


def test_gitea_is_configured_like_a_corporate_install() -> None:
    env: dict[str, str] = _specs()["app-01"]["env"]  # type: ignore[assignment]
    assert env["GITEA____APP_NAME"] == "Northfield Logistics Git"
    assert env["GITEA__security__INSTALL_LOCK"] == "true"
    assert env["GITEA__server__DISABLE_SSH"] == "true"
    assert env["GITEA__server__OFFLINE_MODE"] == "true"
    assert env["GITEA__service__DISABLE_REGISTRATION"] == "true"
    assert env["GITEA__webhook__ALLOWED_HOST_LIST"] == "external"
    assert env["GITEA__server__ROOT_URL"] == "https://git.northfield-logistics.com/"


def test_mattermost_fetches_nothing_from_outside_and_shows_no_tours() -> None:
    env: dict[str, str] = _specs()["app-02"]["env"]  # type: ignore[assignment]
    for key in (
        "ENABLELINKPREVIEWS",
        "ENABLEONBOARDINGFLOW",
        "ENABLETUTORIAL",
        "ENABLESECURITYFIXALERT",
    ):
        assert env[f"MM_SERVICESETTINGS_{key}"] == "false", key
    assert env["MM_PLUGINSETTINGS_ENABLEMARKETPLACE"] == "false"
    assert env["MM_IMAGEPROXYSETTINGS_ENABLE"] == "false"
    assert env["MM_TEAMSETTINGS_SITENAME"] == "Northfield Logistics Chat"


def test_routes_point_at_each_products_port() -> None:
    routes = json.loads(sandbox.routes_json(sandbox.plan_from(MANIFEST), []))["routes"]
    assert routes["git.northfield-logistics.com"]["upstream"] == "http://10.41.0.21:3000"
    assert routes["chat.northfield-logistics.com"]["upstream"] == "http://10.41.0.22:8065"


def test_agent_visible_names_have_no_tells() -> None:
    plan = sandbox.plan_from(MANIFEST)
    for app in plan.apps:
        for name in (app.container, app.db_container):
            assert not any(w in name for w in TELL_WORDS)
    for twin in (get_twin("gitea"), get_twin("mattermost")):
        assert twin is not None
        assert twin.static_path.startswith("/")


def test_relay_quotes_shell_arguments() -> None:
    assert _quote("it's") == "'it'\\''s'"
    assert get_twin("outline") is None
