# Going public: checklist

The repository stays private until every item is ticked. See decision 0007. Add items as they are found; never remove one without a note.

## Name and legal

- [x] Name chosen: MirrorDimensions; package `mirrordimensions`, command `mirror`; domain `mirrordimensions.com` owned (2026-11-23)
- [ ] Trademark search done, including against Google's "Mirror Dimension for Agents"
- [ ] Package `mirrordimensions` claimed on PyPI with a real first release (not a placeholder); trademark registered by Supercomplicated LLC; `mirrordimensions` GitHub organization claimed; `TRADEMARKS.md` published
- [ ] No cloud-service code, configuration or references anywhere in the repository or its history
- [x] Licence confirmed: Apache-2.0 (2026-11-23)
- [ ] `LICENSE`, `NOTICE` and SPDX headers match it, naming Supercomplicated LLC as copyright holder
- [ ] DCO (or CLA) decided and enforced in CI
- [ ] Lawyer review: licence, twin software licences (Gitea, Mattermost), catalog trademark use, dual-use scenarios, the product spec's "cloning third-party SaaS" risk

## History and content

- [ ] gitleaks run over the full history with no findings; any secret ever committed has been rotated
- [ ] Decided: keep history, or publish a fresh squashed history
- [ ] No personal emails in commit authors that their owners have not agreed to publish
- [ ] No links only the owner can open; the design reference is readable from the repository alone
- [ ] Public docs stand alone: references to the product spec and build spec (kept outside the repository) are replaced by public architecture and how-to docs
- [ ] A dedicated contact address for code-of-conduct reports, named in `CODE_OF_CONDUCT.md`
- [ ] No internal bylines or personal details in docs (bylines on the two specs; the owner's hardware in decision 0006 and `docs/platforms.md`)
- [ ] No real organization's data or exports anywhere, including test fixtures
- [ ] README explains that built-in scenarios are public, and that organizations should keep their own scenarios private

## Repository settings

- [ ] **Self-hosted runner on the owner's Mac removed, or restricted to manual triggers and workflows that need approval for outside contributors.** A self-hosted runner on a public repository runs other people's code
- [ ] Branch protection on `main`: required review and CI
- [ ] Secret scanning with push protection on
- [ ] Private vulnerability reporting on; `SECURITY.md` points to it
- [ ] Dependabot alerts and updates on
- [ ] Issues and Discussions on, with templates
- [ ] OpenSSF Scorecard running

## Release

- [ ] First release built by CI with PyPI trusted publishing, signed, with provenance attestation and an SBOM
- [ ] `CHANGELOG.md` up to date
- [ ] Announcement written
