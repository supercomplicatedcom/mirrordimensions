# 0007. Built private, ready to publish: open-source practices from M0

Status: Proposed (adopted into M0 by the owner; individual choices open where noted) · Date: 2026-11-22 · Milestone: M0

## Context

The repository is private until the prototype works, then it becomes public. Publishing exposes everything committed: every file in every commit, author names and emails, and links. Practices that are cheap on day one (licence, contributor sign-off, secret scanning, dependency licence checks) are expensive or impossible to retrofit once history and outside contributions exist. The project is also a security tool: it contains a sandbox whose escapes are vulnerabilities, and attack scenarios that are dual-use.

## Decision

**1. Write for publication from the first commit.** Nothing goes into history that could not be published: no secrets, no real data, no personal details beyond what contributors choose to publish, no links that only the owner can open.

**2. Licence and contribution terms**

- Licence: **Apache-2.0** (the spec's placeholder), for its explicit patent grant, which corporate users and their lawyers expect. Confirmed by the owner before M0 merges; see Open decisions.
- Contributor terms: the **Developer Certificate of Origin** (a `Signed-off-by` line on every commit), checked in CI. A contributor licence agreement is the alternative only if a proprietary edition is ever planned. Decided before the first outside pull request.
- Every source file carries an SPDX licence identifier header; `NOTICE` lists third-party attributions.

**3. Secrets never enter history**

- gitleaks runs as a pre-commit hook and in CI on every push, with an allow-list only for deliberately fake canary values in fixtures, each marked as such.
- A real secret that is ever committed is rotated, not just deleted: deletion does not remove it from history.
- Commit author emails are GitHub noreply addresses unless a contributor chooses otherwise.

**4. Dependency and third-party licences**

- A licence check runs in CI on the Python package and the portal's front end. Allowed: permissive licences compatible with Apache-2.0. Anything copyleft (GPL, AGPL, LGPL in some uses) fails the check and needs a decision record.
- Twin software is pulled as upstream images at build time and never redistributed from this repository. Its licences (Gitea: MIT; Mattermost: AGPL-licensed source with MIT-licensed Team Edition binaries) are recorded in a decision note and reviewed by a lawyer before publication.
- The app catalog holds product names and public facts only; its README carries a trademark notice. No logos, screenshots or copied documentation (already a rule).

**5. Security-tool specifics**

- `SECURITY.md` defines what counts as a vulnerability (any sandbox escape, egress bypass, capture gap, or route from the sandbox to the host or control plane), how to report it privately (GitHub private vulnerability reporting), and a disclosure timeline (proposed: acknowledgement in 3 working days, fix or mitigation target 90 days).
- Tells (ways the agent can notice the test) are not vulnerabilities. They are public issues, recorded in `docs/tells.md`, as the product spec intends.
- An acceptable-use statement covers the dual-use content: injection and permission scenarios target synthetic companies only; no working malware, exploit code or real credentials (already a rule).
- Private scenarios are the easy default: `mirror init` creates a project whose `scenarios/` is the place for an organization's own scenarios, and the README explains that built-in scenarios are public and therefore known to models.

**6. Repository health files** (created in M0): `LICENSE`, `NOTICE`, `SECURITY.md`, `CONTRIBUTING.md` (including DCO, the AI-assistance policy and how to run tests), `CODE_OF_CONDUCT.md` (Contributor Covenant), `GOVERNANCE.md` and `MAINTAINERS.md`, `CODEOWNERS`, issue templates (bug, tell, feature, catalog entry) and a pull request template with the milestone checklist.

**7. Workflow and supply chain**

- Branch protection on `main`: pull requests only, required review, required CI.
- Conventional commit messages, a `CHANGELOG.md` and semantic versioning from the first release.
- GitHub Actions pinned to commit hashes; workflow tokens read-only by default; no `pull_request_target` with secrets.
- Dependabot or Renovate for dependency and action updates.
- From the first release: PyPI trusted publishing (no stored tokens), signed releases with build provenance attestations, an SBOM per release, OpenSSF Scorecard.

**8. AI-assisted contributions** are allowed. The contributor is responsible for every line, and commits made with an assistant say so (`Co-Authored-By`). Stated in `CONTRIBUTING.md`.

**9. Publication is a checklist, not an event.** `docs/open-source/go-public.md` lists every step. The repository becomes public only when every item is ticked.

## Consequences

- A few minutes of CI per push (secret scan, licence check, DCO check).
- Contributors must sign off commits from the start, including the owner.
- Some open decisions (name, licence, DCO or CLA, history) block publication, not development.

## Alternatives considered

- **Clean up just before publishing.** Rejected: secrets and personal data in history, and licence questions over existing contributions, cannot be fixed by a final cleanup.
- **Publish a fresh, squashed history.** Kept as an option for the go-public step; decided then.

## To verify

- The current name and availability of GitHub features used here (private vulnerability reporting, secret scanning push protection, artifact attestations) for a private repository on the organization's plan, and for public repositories.
- That `mirror` cannot be the PyPI package name (it is already taken), and that the final name is free on PyPI and clear of trademarks.
