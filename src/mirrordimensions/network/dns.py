# SPDX-License-Identifier: Apache-2.0
"""The resolver's configuration: CoreDNS, rendered from the manifest.

Every app hostname and model host resolves to the gateway. Every other name gets the
answer a host on a restricted corporate network sees: NXDOMAIN, with the root zone's SOA.
(CoreDNS runs plugins in a fixed compiled order: `hosts` answers known names and falls
through to `file`, which serves an empty root zone. A catch-all `template` would run before
`hosts`, and `hosts` alone answers unknown names with SERVFAIL.) Nothing is ever forwarded
to another resolver. Every query is logged, one line each, and becomes a `dns.query` event.
"""

from __future__ import annotations

# The log line format, parsed by network/events.py: rcode, type, name, client address.
LOG_FORMAT = "q {rcode} {type} {name} {remote}"


def render_hosts(names: list[str], gateway_ip: str) -> str:
    lines = [f"{gateway_ip} {name}" for name in sorted(set(names))]
    return "\n".join(lines) + "\n"


ROOT_ZONE = """\
$ORIGIN .
$TTL 86400
@ IN SOA a.root-servers.net. nstld.verisign-grs.com. 2026112300 1800 900 604800 86400
@ IN NS a.root-servers.net.
"""


def render_corefile() -> str:
    return f""".:53 {{
    log . "{LOG_FORMAT}"
    hosts /etc/coredns/hosts {{
        ttl 300
        no_reverse
        fallthrough
    }}
    file /etc/coredns/root.zone .
}}
"""
