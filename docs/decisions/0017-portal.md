# 0017. The portal: a local server on the service layer, a React front end shipped inside the package, and a token kept in a cookie

Status: Accepted (owner), points 2, 3, 4 and 6 · Date: 2026-11-24 · Milestone: M7

## Context

The build spec asks for a local web portal over the service layer: FastAPI on the host, bound to `127.0.0.1`, a TypeScript and React front end built with Vite to static files that ship inside the Python package, server-sent events for live updates, and a random token in the printed address. It must work with no internet access and must not be reachable from any sandbox container. It does nothing the command line cannot.

Three details the spec leaves open matter for safety or for contributors:

- A token in an address protects against other local users, but a browser adds two more ways in: a web page that points its own domain name at `127.0.0.1` (DNS rebinding), and a cross-site form or image that sends a request with the browser's credentials.
- The front end has to be built with Node, but most people install with `uv` and many will run from a source checkout.
- The design uses Inter and JetBrains Mono, which are under the SIL Open Font License, not a licence this project has accepted before.

## Decision

1. **Server.** `src/mirrordimensions/portal/server.py`.
   - FastAPI, served by uvicorn on `127.0.0.1` only. `/api/v1` follows the spec's table; each endpoint calls one service function and returns its model.
   - Live timelines are server-sent events read from the run's own `events.jsonl`, so a run started from the command line can be followed in the portal and the reverse.
   - The portal writes `.mirror/portal.json` with its port while it serves, so `mirror doctor` can probe the real port.
2. **Access.**
   - Opening the printed `/?token=…` once sets an HttpOnly, SameSite=Strict cookie and redirects to `/`, so the token leaves the address bar. Scripts may send `Authorization: Bearer <token>` instead. Every other request without one or the other gets 401.
   - The Host header must be `127.0.0.1:<port>` or `localhost:<port>`, or the answer is 421. This closes DNS rebinding.
   - Anything that changes state needs `X-Mirror-Portal: 1`, which a cross-site form or image cannot send.
   - Responses carry `Content-Security-Policy` (`default-src 'self'`, `frame-ancestors 'none'`), `nosniff`, `no-referrer` and `no-store`. Stored bodies, which an agent may have written, are served as text with `default-src 'none'` and are never rendered as HTML.
3. **Front end.**
   - `src/mirrordimensions/portal/web/`: React 19, React Router, TypeScript strict, built by Vite into `src/mirrordimensions/portal/static/`.
   - Fonts come from the `@fontsource` packages and are bundled by the build; nothing loads from a CDN.
   - The built files are not committed. The wheel build includes them (`artifacts` in `pyproject.toml`) and CI builds them before its browser tests.
   - In a source checkout without a build, `mirror portal` still serves the API and shows a page that names the two commands to build the front end.
4. **Licences.** What ships in the built files is checked by `scripts/check_web_licenses.py`, from the lockfile's non-development packages: React, React Router and their small dependencies are MIT.
   - The fonts are under OFL-1.1. It allows bundling the fonts with any software, including commercial software, provided they are not sold on their own. That is compatible with distributing the portal under Apache-2.0.
   - The test tools (Playwright, axe, Vitest) are development-only and never shipped.
5. **Tests.**
   - Python tests run the server in process: access control, every endpoint, paging, streaming, bodies.
   - Vitest covers front-end logic.
   - Playwright runs one browser test per screen against a fixture project (`tests/portal_fixture.py`) served by the real server with the built front end, and each runs axe for WCAG 2.1 A and AA. A serious or critical finding fails the test.
6. **Delivery in parts.** M7 lands as several pull requests, each mergeable on its own. M7 is accepted when the last one is merged.

**Owner's choices (2026-11-24).** The owner chose four options. Each was offered against its alternative:

- the built files are built, not committed, over committing them or building on first run;
- Inter and JetBrains Mono are bundled, over the system's fonts;
- M7 is delivered as five pull requests into `main`, over one;
- a cookie is set after the first visit, over sending the token with every request.

## Consequences

- Contributors who touch the front end need Node 22 and `npm`; everyone else does not.
- A browser that blocks cookies on `127.0.0.1` cannot use the portal; scripts can still use the bearer token.
- The token lives in a cookie for the browser session. Anyone with access to that browser profile while the portal runs can use it, which is the same exposure as the printed address.

## Alternatives considered

- **Commit the built files.** Simpler for source checkouts, but every front-end change would carry a large generated diff, and review could not tell the source from the build.
- **The token in every API call from JavaScript.** It would have to live in page memory or storage, where any script on the page can read it; an HttpOnly cookie cannot be read by scripts.
- **A system font stack.** No licence question, but the design is drawn in Inter, and offline use needs the fonts bundled either way.

## To verify

- The portal on Windows (loopback binding, the cookie, `webbrowser.open`).
- A run of 10,000 events on a slower laptop. On the owner's Mac a 10,609-event run pages in under 200 ms (`docs/platforms.md`).
