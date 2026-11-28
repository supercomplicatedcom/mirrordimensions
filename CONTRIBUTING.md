# Contributing

Thank you for helping. MirrorDimensions is a security tool, so the bar for changes that touch isolation, capture or what the agent can see is high. Please read the working rules in [CLAUDE.md](CLAUDE.md); they apply to people as much as to AI assistants.

## Set up

1. Install [uv](https://docs.astral.sh/uv/), [gitleaks](https://github.com/gitleaks/gitleaks) and [pre-commit](https://pre-commit.com/).
2. Clone, then:

   ```sh
   uv sync
   pre-commit install --hook-type pre-commit --hook-type commit-msg
   ```

## Before you push

```sh
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
uv run python scripts/check_imports.py
uv run python scripts/check_spdx.py
uv run python scripts/check_licenses.py
```

CI runs all of these on Linux, macOS and Windows, plus a secret scan and a DCO check.

### The portal's front end

Only needed if you change `src/mirrordimensions/portal/web/` or want the portal from a source checkout. Needs Node 22.

```sh
cd src/mirrordimensions/portal/web
npm ci
npm run typecheck
npm test                              # unit tests (Vitest)
npm run build                         # into ../static, which ships in the package
npx playwright install chromium       # once
npx playwright test                   # a browser test per screen, with an accessibility check
uv run python ../../../../scripts/check_web_licenses.py
```

For live reloading, run `mirror portal --port 7420 --no-open` in a project, open the address it prints once (to sign the browser in), then `npm run dev` and use the address Vite prints.

## Sign off every commit (DCO)

By signing off you certify the [Developer Certificate of Origin](https://developercertificate.org/): that you wrote the change or have the right to submit it under the project's licence. Use `git commit -s`, which adds:

```
Signed-off-by: Your Name <you@example.com>
```

The name and email must match the commit author. You keep the copyright in your contribution and license it under Apache-2.0.

## Licence headers

Every source file starts with its licence identifier, as a comment in the file's own syntax:

```
# SPDX-License-Identifier: Apache-2.0
```

Files carry no copyright line; [NOTICE](NOTICE) states it once for the project. By signing off a commit (below) you license your contribution under Apache-2.0.

## Dependencies

Add a dependency only when it removes real work, and say why in the pull request. Its licence must be compatible with Apache-2.0; `scripts/check_licenses.py` fails on copyleft licences, and an exception needs a decision record in `docs/decisions/`.

## Pull requests

- One milestone, or less, per pull request. Start with a short plan; end by showing each acceptance criterion passing.
- Use [Conventional Commits](https://www.conventionalcommits.org/) for commit messages and pull request titles (`feat:`, `fix:`, `docs:`, `chore:` and so on).
- Keep `README.md` and `docs/` accurate in the same pull request as the change.
- A new way for an agent to touch something is not done until it is captured, appears in the coverage section and has a reconciliation test.

## AI-assisted contributions

Welcome. You are responsible for every line you submit, whoever or whatever wrote it, and you must understand it well enough to answer review questions. Say in the pull request if an assistant wrote a substantial part, and keep `Co-Authored-By` trailers that your tools add.

## Security issues

Never in public. See [SECURITY.md](SECURITY.md).
