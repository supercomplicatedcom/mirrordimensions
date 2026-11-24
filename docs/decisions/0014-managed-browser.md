# 0014. The managed browser: an observer that shares the browser's network namespace

Status: Proposed · Date: 2026-11-24 · Milestone: M4

## Context

In browser mode the agent's program runs in a container in the engine and drives a Chromium container over the DevTools protocol (build spec, "Agent modes"). The runner must hold a second, read-only DevTools session that records navigations, input and screenshots. That session must not run on the host: reaching DevTools from the host would need a path from the host into the agent network. The spec leaves the mechanism to a note at the start of M4.

Measured in the engine (Docker 29.10, arm64) with the Playwright 1.65.2 image's Chromium 159 headless shell, hardened as every agent-position container (no capabilities, `no-new-privileges`, default seccomp and AppArmor, unprivileged user):

- Chromium starts with `--no-sandbox` and serves DevTools on `127.0.0.1:9222`. Its own sandbox cannot start without the capabilities the container does not have. `--no-sandbox` is the usual setting for Chromium in a container.
- DevTools accepts any number of sessions at once.
- **A second session does not see the first session's commands.** DevTools has no event for "another client clicked". A read-only session can record navigations, page loads and screenshots, but not the agent's input.
- Playwright negotiates permessage-deflate on its DevTools WebSocket, so a copy of the stream has to be inflated to read it.
- Every DevTools client sees a page's `attached` flag (through `Target.getTargets`; `/json/list` does not show it). An observer that attached to a fresh tab first would set it.

## Decision

1. **The observer is its own container sharing the browser's network namespace** (`network_mode: container:<browser>`). It holds the read-only session on loopback, so the browser never listens on the office network. The observer listens on nothing but the pass-through below, has no other network, and writes events to standard output, which the control plane reads through the Docker API like every other capture source (decision 0003).

2. **The agent's DevTools connection passes through the observer, byte for byte.** The observer listens on the browser's office address, port 9222, and copies each connection to `127.0.0.1:9222` unchanged. Nothing is answered by the observer: the HTTP endpoints (`/json/version`, `/json/list`) and the WebSocket upgrade come from Chromium itself. A copy of what the agent sends is decoded (WebSocket frames, permessage-deflate) and every DevTools command becomes a `browser.action` event: method, session and parameters, with the agent's secrets redacted, kind `input`, `navigate` or `command`. This is the complete record of what the agent did to the browser, including `Runtime.evaluate`, which an input listener would miss.

3. **The read-only session** discovers targets and attaches only to pages the agent has already attached to, so the `attached` flag the agent can see is the same with or without the observer. It enables `Page` events in its own session, records main-frame navigations as `browser.navigate`, and takes a JPEG screenshot (`browser.screenshot`) of each page that changed, at most every two seconds. It injects no script, adds no binding and sets no flag the page can read.

4. **The browser's own traffic goes through the gateway** like any other: it uses the sandbox resolver, and the company root is in its NSS store (`~/.pki/nssdb`), added in an image build per install, at setup time, with no network.

5. **Names.** The browser runs as `vdi-NNNN` on the office network, an ordinary virtual-desktop host name. The agent's program runs as a workstation (`ws-NNNN`), as hosted agents do. The agent is given `BROWSER_CDP_URL=http://<address>:9222`. The address is an IP: Chromium refuses DevTools requests whose `Host` header is a name that is not `localhost`.

## Consequences

- Coverage gains a `browser` channel. The agent-to-browser link is the one connection in the sandbox that does not cross the gateway, and the observer is where it is captured.
- The observer is a second piece of mirror code on a path the agent uses, after the gateway. Like the gateway, it changes no byte the agent sees, and the naming lint and doctor treat it the same way.
- What the browser reports about itself is what a headless Chromium in a container reports anywhere: `HeadlessChrome` in the user agent, `navigator.webdriver` true under remote debugging, `--no-sandbox` and the debugging flags in `Browser.getBrowserCommandLine`. These are properties of a company's own headless browser service, not of the mirror. They are listed in `docs/tells.md` as accepted, with that reason.
- The browser image is the Playwright image (about 3.6 GB on arm64), pulled once at setup.

## Alternatives considered

- **The observer on the host.** It needs a route from the host into the agent network. Not allowed (spec).
- **Chromium listening on the office network directly, the observer as a second client.** Simpler, but the observer could not see the agent's input, and the debugging port would be bound beyond loopback with `--remote-debugging-address`, which is visible in the browser's command line.
- **`--remote-debugging-pipe` with a launcher process inside the browser container.** It hides the observer's session, but puts mirror code inside the container the agent drives. Rejected.
- **Input listeners injected into pages.** Forbidden: pages could read them.

## To verify

- The pass-through adds no difference the agent can measure beyond latency: same bytes, same headers, same close behavior (M4, unit and live tests).
- Screenshots from the observer's session do not change what the agent's session sees (focus, visibility, frame timing) on the reference agent (M4).
- The same holds on the WSL and host drivers (M6 platform pass).
