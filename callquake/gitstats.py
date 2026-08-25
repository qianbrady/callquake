"""Git-history signals feeding the risk model (standard library only)."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

#: How far back the churn window reaches.
HISTORY_DAYS = 180

_FIX_RE = re.compile(r"fix|bug", re.IGNORECASE)
_RECORD_SEP = "\x1f"


@dataclass(frozen=True)
class HistorySignal:
    """Churn/fix statistics for a set of files over the recent window."""

    commits_180d: int = 0
    fix_commits_180d: int = 0
    available: bool = True  # False => git missing / not a repository
    note: str = ""

    @property
    def fix_ratio(self) -> float:
        if self.commits_180d <= 0:
            return 0.0
        return max(0.0, min(1.0, self.fix_commits_180d / self.commits_180d))


def is_fix_subject(subject: str) -> bool:
    """True when a commit message subject mentions ``fix`` or ``bug``."""
    return bool(_FIX_RE.search(subject))


def git_history_for_files(
    root,
    files,
    *,
    now: datetime | None = None,
    runner=None,
) -> HistorySignal:
    """Aggregate git log statistics for *files* inside repository *root*.

    ``runner(root, args) -> (returncode, stdout, stderr)`` is injectable so
    tests can run without a real git binary.  Commits are filtered client-side
    on the author date (%ad) against the ``HISTORY_DAYS`` window ending at
    *now* (defaults to the current UTC time).
    """
    unique_files = sorted({str(f).replace("\\", "/") for f in files})
    if not unique_files:
        return HistorySignal()

    if runner is None:
        runner = _default_runner
    args = [
        "log",
        "--date=unix",
        f"--pretty=%H{_RECORD_SEP}%ad{_RECORD_SEP}%s",
        "--",
        *unique_files,
    ]
    code, out, err = runner(Path(root), args)
    if code != 0:
        return HistorySignal(available=False, note=(err or "git log failed").strip())

    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=HISTORY_DAYS)

    commits = 0
    fixes = 0
    for line in out.splitlines():
        parts = line.split(_RECORD_SEP)
        if len(parts) != 3:
            continue
        try:
            stamp = int(parts[1])
        except ValueError:
            continue
        committed_at = datetime.fromtimestamp(stamp, tz=timezone.utc)
        if committed_at >= cutoff:
            commits += 1
            if is_fix_subject(parts[2]):
                fixes += 1
    return HistorySignal(commits, fixes, True)


def _default_runner(root: Path, args: list[str]):
    """Run a git command, never crashing even when git is not installed."""
    cmd = ["git", "-C", str(root), *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:  # FileNotFoundError and friends
        return 127, "", f"git unavailable: {exc}"
    return proc.returncode, proc.stdout or "", proc.stderr or ""
