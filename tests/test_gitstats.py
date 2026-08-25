"""Git-dimension tests: window filtering, fix ratio, graceful degradation."""

from __future__ import annotations

import shutil
import unittest
from datetime import datetime, timedelta, timezone

from callquake.gitstats import HistorySignal, git_history_for_files, is_fix_subject

from _harness import HAS_GIT, fresh_dir, git_commit_all, write_tree


def make_runner(rows, code=0, err=""):
    """Build a fake git runner emitting canned ``hash\\x1fepoch\\x1fsubject`` rows."""
    def _epoch(value):
        return int(value.timestamp()) if isinstance(value, datetime) else int(value)

    out = "".join(f"h{i}\x1f{_epoch(stamp)}\x1f{subj}\n" for i, (stamp, subj) in enumerate(rows))

    def runner(root, args):
        return code, out, err

    return runner


class FakeRunnerTest(unittest.TestCase):
    def setUp(self):
        self.root = fresh_dir("gstat")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.now = datetime(2025, 6, 1, tzinfo=timezone.utc)

    def test_window_filter_and_fix_count(self):
        day = timedelta(days=1)
        rows = [
            (self.now - 10 * day, "fix crash on empty input"),
            (self.now - 100 * day, "refactor internals"),
            (self.now - 400 * day, "fix ancient typo"),
        ]
        signal = git_history_for_files(
            self.root, ["a.py"], now=self.now, runner=make_runner(rows)
        )
        self.assertTrue(signal.available)
        self.assertEqual(signal.commits_180d, 2)
        self.assertEqual(signal.fix_commits_180d, 1)
        self.assertAlmostEqual(signal.fix_ratio, 0.5)

    def test_fix_subject_case_insensitive(self):
        day = timedelta(days=1)
        rows = [
            (self.now - day, "BUG crash"),
            (self.now - 2 * day, "hotFIX release"),
            (self.now - 3 * day, "docs only"),
        ]
        signal = git_history_for_files(
            self.root, ["a.py"], now=self.now, runner=make_runner(rows)
        )
        self.assertEqual((signal.commits_180d, signal.fix_commits_180d), (3, 2))
        self.assertAlmostEqual(signal.fix_ratio, 2 / 3)

    def test_boundary_commit_exactly_180d_included(self):
        day = timedelta(days=1)
        rows = [
            (self.now - 180 * day, "edge commit"),
            (self.now - 181 * day, "just outside"),
        ]
        signal = git_history_for_files(
            self.root, ["a.py"], now=self.now, runner=make_runner(rows)
        )
        self.assertEqual(signal.commits_180d, 1)
        self.assertEqual(signal.fix_commits_180d, 0)

    def test_runner_failure_is_graceful(self):
        signal = git_history_for_files(
            self.root,
            ["a.py"],
            now=self.now,
            runner=make_runner([], code=128, err="fatal: not a git repository"),
        )
        self.assertFalse(signal.available)
        self.assertEqual(signal.commits_180d, 0)
        self.assertEqual(signal.fix_commits_180d, 0)
        self.assertIn("not a git", signal.note)

    def test_empty_file_list_short_circuits(self):
        signal = git_history_for_files(self.root, [], now=self.now, runner=None)
        self.assertEqual(signal, HistorySignal())


@unittest.skipUnless(HAS_GIT, "git binary required")
class RealGitTest(unittest.TestCase):
    def setUp(self):
        self.root = fresh_dir("grepo")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.now = datetime.now(timezone.utc)

    def test_real_repo_history_matches_expectations(self):
        from datetime import timedelta

        write_tree(self.root, {"pkg/util.py": "def handler(x):\n    return x\n"})
        git_commit_all(self.root, "ancient fix", when=self.now - timedelta(days=400))
        write_tree(self.root, {"pkg/util.py": "def handler(x):\n    return x  # v2\n"})
        git_commit_all(self.root, "add feature", when=self.now - timedelta(days=90))
        write_tree(self.root, {"pkg/util.py": "def handler(x):\n    return x  # v3\n"})
        git_commit_all(self.root, "fix crash", when=self.now - timedelta(days=30))

        signal = git_history_for_files(self.root, ["pkg/util.py"], now=self.now)
        self.assertTrue(signal.available)
        self.assertEqual(signal.commits_180d, 2)
        self.assertEqual(signal.fix_commits_180d, 1)


class FixSubjectUnitTest(unittest.TestCase):
    def test_is_fix_subject(self):
        self.assertTrue(is_fix_subject("FIX it"))
        self.assertTrue(is_fix_subject("workaround bug"))
        self.assertFalse(is_fix_subject("release notes"))


if __name__ == "__main__":
    unittest.main()
