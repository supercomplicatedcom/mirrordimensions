# SPDX-License-Identifier: Apache-2.0
"""Prove that a committed credential is rejected, both by the pre-commit hook and by the
CI scan, without ever committing a credential to this repository.

A fake access key is generated at run time inside a throwaway repository. The test
passes only if both checks reject it.
"""

from __future__ import annotations

import secrets
import shutil
import string
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def fake_key() -> str:
    alphabet = string.ascii_uppercase + "234567"
    return "AKIA" + "".join(secrets.choice(alphabet) for _ in range(16))


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)


def main() -> int:
    if shutil.which("gitleaks") is None:
        print("FAIL  gitleaks is not installed")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "ci@users.noreply.github.com")
        git(repo, "config", "user.name", "CI")
        shutil.copy(ROOT / ".pre-commit-config.yaml", repo / ".pre-commit-config.yaml")
        (repo / "settings.py").write_text(
            f'AWS_ACCESS_KEY_ID = "{fake_key()}"\n'
            f'AWS_SECRET_ACCESS_KEY = "{secrets.token_urlsafe(30)}"\n',
            encoding="utf-8",
        )
        git(repo, "add", ".")

        hook = subprocess.run(
            ["pre-commit", "run", "gitleaks-system", "--files", "settings.py"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        hook_rejected = (
            hook.returncode != 0 and "leaks found" in (hook.stdout + hook.stderr).lower()
        )

        git(repo, "commit", "-q", "--no-verify", "-m", "add settings")
        scan = subprocess.run(
            ["gitleaks", "git", "--redact", "--no-banner", str(repo)],
            capture_output=True,
            text=True,
            check=False,
        )
        scan_rejected = scan.returncode != 0

    print(f"{'ok' if hook_rejected else 'FAIL':<6}pre-commit hook rejects a staged credential")
    print(f"{'ok' if scan_rejected else 'FAIL':<6}CI scan rejects a committed credential")
    if not hook_rejected:
        print(hook.stdout[-2000:], hook.stderr[-2000:])
    return 0 if hook_rejected and scan_rejected else 1


if __name__ == "__main__":
    sys.exit(main())
