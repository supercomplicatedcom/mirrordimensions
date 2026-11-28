# SPDX-License-Identifier: Apache-2.0
"""Mattermost's scenario vocabulary: overlays, deliveries and checks (build spec, "Scenario
file").

People post as themselves: the runner signs in with the person's password, as they would,
so messages raise the same notifications and live events a colleague's message does.
Checks compare the state before the agent started with the state after it stopped
(`facts["before"]`, `facts["after"]`), so only what changed during the run counts.
"""

# Product APIs return untyped JSON.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from mirrordimensions.errors import MirrorError
from mirrordimensions.twins.base import CheckOutcome, Operations, RunContext, StateObject


def _base(run: RunContext) -> str:
    return f"http://{run.ctx.app_ip}:8065/api/v4"


def _session(run: RunContext, username: str) -> str:
    """A session for a person, signed in with their password (kept for the run)."""
    sessions: dict[str, str] = run.facts.setdefault("_mm_sessions", {})
    if username in sessions:
        return sessions[username]
    password = run.ctx.secrets.get(f"user:{username}") or run.ctx.secrets["user_password"]
    resp = run.relay.request(
        "POST",
        f"{_base(run)}/users/login",
        body={"login_id": username, "password": password},
        with_headers=True,
    )
    token = resp.headers.get("token")
    if resp.status != 200 or not token:
        raise MirrorError(
            f"{username} could not sign in to chat for the scenario.",
            f"HTTP {resp.status}: {resp.body[:200]!r}",
            "Check the person exists in the world: mirror world show",
        )
    sessions[username] = token
    return token


def _api(run: RunContext, username: str, method: str, path: str, body: Any = None) -> Any:
    resp = run.relay.request(
        method,
        f"{_base(run)}{path}",
        body=body,
        headers={"Authorization": f"Bearer {_session(run, username)}"},
    )
    if resp.status not in (200, 201):
        raise MirrorError(
            f"Mattermost refused {method} {path} for the scenario.",
            f"HTTP {resp.status}: {resp.body[:200]!r}",
            "Check the scenario's names against the world: mirror world show",
        )
    return resp.json() if resp.body else None


def _who(run: RunContext, spec: Any) -> Any:
    return run.acts_as if spec in (None, "acts_as") else run.person(dict(spec))


def _channel_id(run: RunContext, username: str, name: str) -> str:
    me = _api(run, username, "GET", "/users/me/teams")
    for team in me:
        resp = run.relay.request(
            "GET",
            f"{_base(run)}/teams/{team['id']}/channels/name/{name}",
            headers={"Authorization": f"Bearer {_session(run, username)}"},
        )
        if resp.status == 200:
            return str(resp.json()["id"])
    raise MirrorError(f"No channel {name!r} that {username} can post in.", "", "Fix the scenario.")


def _dm_id(run: RunContext, a: str, b: str) -> str:
    ids = [str(_api(run, a, "GET", f"/users/username/{u}")["id"]) for u in (a, b)]
    return str(_api(run, a, "POST", "/channels/direct", ids)["id"])


def _post(
    run: RunContext, username: str, channel_id: str, message: str, root: str | None
) -> dict[str, Any]:
    body: dict[str, Any] = {"channel_id": channel_id, "message": message}
    if root:
        body["root_id"] = root
    return dict(_api(run, username, "POST", "/posts", body))


# -- overlays and deliveries ------------------------------------------------------------------


def post(run: RunContext, args: dict[str, Any]) -> None:
    """A message from a person, in a channel or to someone directly; recorded as a fact."""
    author = _who(run, args.get("author"))
    if "to" in args:
        channel = _dm_id(run, author.username, _who(run, args["to"]).username)
    else:
        channel = _channel_id(run, author.username, args["channel"])
    root = run.facts.get(args["reply_to"], {}).get("post") if args.get("reply_to") else None
    created = _post(run, author.username, channel, args["message"], root)
    if args.get("key"):
        run.facts[args["key"]] = {"post": created["id"], "channel": channel}


def _member(run: RunContext, spec: Any, channel: str) -> Any:
    """The sender: the first person matching `from` who is in the channel (only members can
    post there)."""
    if spec in (None, "acts_as") or run.people is None:
        return _who(run, spec)
    members = next((set(c.members) for c in run.world.channels if c.name == channel), set[str]())
    candidates = run.people(dict(spec))
    return next((p for p in candidates if p.id in members), candidates[0])


def message(run: RunContext, args: dict[str, Any]) -> dict[str, Any]:
    """Work as a message in a channel that mentions the agent's person."""
    where = args["in"]  # the delivery's own `channel` names this operation
    sender = _member(run, args.get("from"), where)
    channel = _channel_id(run, sender.username, where)
    text = args["text"]
    mention = f"@{run.acts_as.username}"
    if mention not in text:
        text = f"{mention} {text}"
    created = _post(run, sender.username, channel, text, None)
    run.facts["delivered"] = {"post": created["id"], "channel": channel, "name": where}
    return {
        "channel": "mattermost.message",
        "in": where,
        "from": sender.username,
        "to": run.acts_as.username,
        "post": created["id"],
    }


def direct_message(run: RunContext, args: dict[str, Any]) -> dict[str, Any]:
    """Work as a direct message to the agent's person."""
    sender = _who(run, args.get("from"))
    channel = _dm_id(run, sender.username, run.acts_as.username)
    created = _post(run, sender.username, channel, args["text"], None)
    run.facts["delivered"] = {"post": created["id"], "channel": channel, "direct": True}
    return {
        "channel": "mattermost.direct_message",
        "from": sender.username,
        "to": run.acts_as.username,
        "post": created["id"],
    }


# -- checks against what changed ---------------------------------------------------------------


def _new_posts(run: RunContext) -> list[dict[str, Any]]:
    """Posts that appeared during the run: (where, user, message, thread)."""

    def flatten(dump: dict[str, Any]) -> Counter[str]:
        out: Counter[str] = Counter()
        for team in dump.get("teams", []):
            for ch in team["channels"]:
                for p in ch["posts"]:
                    out[json.dumps({"where": ch["name"], **p}, sort_keys=True)] += 1
        for dm in dump.get("direct", []):
            for p in dm["posts"]:
                out[
                    json.dumps(
                        {"where": "@" + ",".join(dm["members"]), "direct": True, **p},
                        sort_keys=True,
                    )
                ] += 1
        return out

    before = flatten(run.facts.get("before", {}))
    after = flatten(run.facts.get("after", {}))
    return [json.loads(k) for k in sorted((after - before).elements())]


def message_posted(run: RunContext, args: dict[str, Any]) -> CheckOutcome:
    who = _who(run, args.get("by"))
    hits = [
        p
        for p in _new_posts(run)
        if p["user"] == who.username
        and ("channel" not in args or p["where"] == args["channel"])
        and args.get("contains", "").lower() in p["message"].lower()
        and (not args.get("in_thread") or p["thread"])
    ]
    where = args.get("channel", "any channel")
    return CheckOutcome(bool(hits), f"{len(hits)} new message(s) by {who.username} in {where}")


def message_contains(run: RunContext, args: dict[str, Any]) -> CheckOutcome:
    """Matches when any message posted during the run contains the text (used as forbidden)."""
    hits = [p for p in _new_posts(run) if args["text"] in p["message"]]
    return CheckOutcome(
        bool(hits),
        f"{len(hits)} new message(s) contain the text"
        + (f" (in {hits[0]['where']})" if hits else ""),
    )


def direct_message_sent(run: RunContext, args: dict[str, Any]) -> CheckOutcome:
    """Matches when the person (default: the agent's) sent any direct message during the run."""
    who = _who(run, args.get("by"))
    hits = [p for p in _new_posts(run) if p.get("direct") and p["user"] == who.username]
    return CheckOutcome(bool(hits), f"{len(hits)} direct message(s) sent by {who.username}")


def _members(dump: dict[str, Any], channel: str | None, team: str | None) -> set[str]:
    for t in dump.get("teams", []):
        if channel is None and t["name"] == team:
            return set(t["members"])
        for ch in t["channels"]:
            if ch["name"] == channel:
                return set(ch["members"])
    return set()


def channel_member(run: RunContext, args: dict[str, Any]) -> CheckOutcome:
    who = _who(run, args["user"])
    members = _members(run.facts.get("after", {}), args.get("channel"), args.get("team"))
    where = args.get("channel") or args.get("team")
    return CheckOutcome(
        who.username in members,
        f"{who.username} {'is' if who.username in members else 'is not'} in {where}",
    )


def thread_reply(run: RunContext, args: dict[str, Any]) -> CheckOutcome:
    """A reply by the person in the thread of the delivered message, containing any of
    `contains_any` (case-insensitive)."""
    who = _who(run, args.get("by"))
    root = run.facts.get("delivered", {}).get("post")
    if not root:
        return CheckOutcome(False, "no delivered message to reply to")
    thread = _api(run, who.username, "GET", f"/posts/{root}/thread")
    me = str(_api(run, who.username, "GET", "/users/me")["id"])
    replies = [
        p for pid, p in thread.get("posts", {}).items() if pid != root and p.get("user_id") == me
    ]
    wanted = [w.lower() for w in args.get("contains_any", [])]
    good = [p for p in replies if not wanted or any(w in p["message"].lower() for w in wanted)]
    return CheckOutcome(
        bool(good),
        f"{len(replies)} reply(ies) by {who.username} in the thread; {len(good)} with the answer",
    )


def message_lists(run: RunContext, args: dict[str, Any]) -> CheckOutcome:
    """A new message by the person (in `channel`, if given) that mentions every item of
    `includes` and none of `excludes`."""
    who = _who(run, args.get("by"))
    posts = [
        p
        for p in _new_posts(run)
        if p["user"] == who.username and ("channel" not in args or p["where"] == args["channel"])
    ]
    for p in posts:
        text = p["message"].lower()
        if all(str(i).lower() in text for i in args.get("includes", [])) and not any(
            str(x).lower() in text for x in args.get("excludes", [])
        ):
            return CheckOutcome(True, f"a message by {who.username} lists what was asked")
    return CheckOutcome(
        False, f"{len(posts)} new message(s) by {who.username}; none lists exactly what was asked"
    )


def members_added(run: RunContext, args: dict[str, Any]) -> CheckOutcome:
    """The channel gained exactly these members during the run."""
    before = _members(run.facts.get("before", {}), args["channel"], None)
    after = _members(run.facts.get("after", {}), args["channel"], None)
    wanted = {_who(run, u).username if isinstance(u, dict) else str(u) for u in args["users"]}
    added = after - before
    return CheckOutcome(added == wanted, f"#{args['channel']} gained {sorted(added) or 'nobody'}")


def operations() -> Operations:
    return Operations(
        overlays={"post": post},
        deliveries={"message": message, "direct_message": direct_message},
        delivery_needs={"message": lambda args: {"channels": [str(args["in"])]}},
        checks={
            "message_posted": message_posted,
            "message_contains": message_contains,
            "direct_message_sent": direct_message_sent,
            "channel_member": channel_member,
            "thread_reply": thread_reply,
            "message_lists": message_lists,
            "members_added": members_added,
        },
    )


# -- state as objects -----------------------------------------------------------------------


def _post_keys(prefix: str, posts: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    seen: Counter[str] = Counter()
    out: list[tuple[str, dict[str, Any]]] = []
    for p in posts:
        digest = hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:12]
        seen[digest] += 1
        out.append((f"{prefix}/post:{p['user']}:{digest}:{seen[digest]}", p))
    return out


def state_objects(dump: dict[str, Any]) -> list[StateObject]:
    out: list[StateObject] = []
    for user in dump.get("users", []):
        out.append(StateObject(f"user:{user['username']}", {"user": user["username"]}, user))
    for login, tokens in dump.get("tokens", {}).items():
        out.append(StateObject(f"tokens:{login}", {"user": login}, tokens))
    for team in dump.get("teams", []):
        out.append(
            StateObject(f"team:{team['name']}/members", {"team": team["name"]}, team["members"])
        )
        for ch in team["channels"]:
            scope = {"team": team["name"], "channel": ch["name"]}
            prefix = f"team:{team['name']}/channel:{ch['name']}"
            out.append(StateObject(f"{prefix}/members", scope, ch["members"]))
            for key, p in _post_keys(prefix, ch["posts"]):
                out.append(StateObject(key, {**scope, "author": p["user"]}, p))
    for dm in dump.get("direct", []):
        names = ",".join(dm["members"])
        prefix = f"direct:{names}"
        for key, p in _post_keys(prefix, dm["posts"]):
            out.append(StateObject(key, {"direct": names, "author": p["user"]}, p))
    return out
