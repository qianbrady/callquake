"""Shared fixtures/helpers for the callquake test-suite (stdlib only).

Every temporary directory is created under ``<workspace>/.build-tmp`` so the
session workspace stays clean.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = PROJECT_ROOT.name
BUILD_TMP = PROJECT_ROOT.parents[1] / ".build-tmp"

HAS_GIT = shutil.which("git") is not None

NOW = datetime.now(timezone.utc)


def days_ago(n: int) -> datetime:
    return NOW - timedelta(days=n)


SAMPLE_FILES = {
    "pkg/util.py": (
        '"""Small helpers used across the demo repo."""\n'
        "\n"
        "\n"
        "def helper(x):\n"
        "    return x * 2\n"
        "\n"
        "\n"
        "class Widget:\n"
        "    def run(self):\n"
        "        return helper(1)\n"
        "\n"
        "    def rerun(self):\n"
        "        return self.run()\n"
    ),
    "app/main.py": (
        "from pkg.util import helper\n"
        "\n"
        "\n"
        "def main():\n"
        "    return helper(21)\n"
        "\n"
        "\n"
        "def dynamic_demo():\n"
        "    getter = getattr(main, 'main')\n"
        "    return getter()\n"
    ),
}


def fresh_dir(prefix: str = "cq") -> Path:
    """Create an isolated temp dir under ``.build-tmp``.

    Deliberately NOT ``tempfile.mkdtemp``: it creates directories with
    ``mode=0o700``, which on some Windows setups produces an ACL so tight
    that even the creating process cannot create children inside.
    """
    BUILD_TMP.mkdir(parents=True, exist_ok=True)
    while True:
        candidate = BUILD_TMP / f"{prefix}-{uuid.uuid4().hex[:12]}"
        try:
            candidate.mkdir()  # default permissions -> inherit parent ACL
            return candidate
        except FileExistsError:  # pragma: no cover - astronomically unlikely
            continue


def write_tree(root: Path, files: dict) -> None:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def sample_repo(with_git: bool = False) -> Path:
    """Materialise SAMPLE_FILES into a fresh temp dir."""
    root = fresh_dir("sample")
    write_tree(root, SAMPLE_FILES)
    if with_git:
        if not HAS_GIT:
            raise RuntimeError("git is required for this fixture")
        # Dated outside the 180d window so risk numbers stay predictable.
        git_commit_all(root, "initial import", when=days_ago(400))
    return root


def line_of(text: str, needle: str) -> int:
    """1-based line number of the first line containing *needle*."""
    for idx, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return idx
    raise AssertionError(f"needle not found in fixture text: {needle!r}")


def run_cli(args, cwd=None, env_extra=None) -> subprocess.CompletedProcess:
    """Run ``python -m <package> ...`` as a real subprocess."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    for noisy in ("PYTHONUTF8", "PYTHONLEGACYWINDOWSSTDIO"):
        env.pop(noisy, None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", PACKAGE_NAME, *args],
        capture_output=True,
        cwd=str(cwd or PROJECT_ROOT),
        env=env,
    )


def git_commit_all(root: Path, message: str, when: datetime | None = None) -> None:
    """Commit everything in *root* with a fixed author and optional date."""

    def g(*cli_args, extra_env=None):
        merged_env = dict(env)
        if extra_env:
            merged_env.update(extra_env)
        return subprocess.run(
            ["git", "-C", str(root), *cli_args],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=merged_env,
        )

    env = dict(os.environ)
    env["GIT_AUTHOR_NAME"] = "ox-alpha"
    env["GIT_AUTHOR_EMAIL"] = "ox-alpha@example.local"
    env["GIT_COMMITTER_NAME"] = "ox-alpha"
    env["GIT_COMMITTER_EMAIL"] = "ox-alpha@example.local"

    date_env = {}
    if when is not None:
        stamp = "@" + str(int(when.timestamp()))
        date_env["GIT_AUTHOR_DATE"] = stamp
        date_env["GIT_COMMITTER_DATE"] = stamp

    if not (root / ".git").exists():
        result = g("init", "-q")
        if result.returncode != 0:
            raise AssertionError(f"git init failed: {result.stderr}")
    result = g("add", "-A")
    if result.returncode != 0:
        raise AssertionError(f"git add failed: {result.stderr}")
    result = g("commit", "-q", "-m", message, extra_env=date_env)
    if result.returncode != 0:
        raise AssertionError(f"git commit failed: {result.stderr}")
