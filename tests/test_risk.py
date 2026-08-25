"""Risk-score formula tests plus one real-git end-to-end pipeline check."""

from __future__ import annotations

import shutil
import unittest
from datetime import datetime, timedelta, timezone

from callquake.ast_index import scan_repository
from callquake.gitstats import git_history_for_files
from callquake.risk import score_function

from _harness import HAS_GIT, fresh_dir, git_commit_all, write_tree


class FormulaTest(unittest.TestCase):
    def test_breadth_formula_and_cap(self):
        self.assertEqual(score_function(0, 0, 0).breadth_points, 0)
        self.assertEqual(score_function(3, 0, 0).breadth_points, 15)
        # 11 callers * 5 = 55 -> capped at 50
        self.assertEqual(score_function(11, 0, 0).breadth_points, 50)

    def test_churn_and_fix_points(self):
        score = score_function(2, 10, 5)
        self.assertEqual(score.churn_points, 30)  # min(30, 30)
        self.assertEqual(score.fix_points, 10)  # half-up of 20 * 0.5
        self.assertEqual(score.history_points, 40)
        self.assertEqual(score.total, 10 + 30 + 10)

        small = score_function(0, 2, 1)
        self.assertEqual(small.churn_points, 6)
        self.assertEqual(small.fix_points, 10)
        self.assertEqual(small.total, 16)

    def test_total_capped_at_100(self):
        score = score_function(999, 999, 999)
        self.assertEqual(score.breadth_points, 50)
        self.assertEqual(score.churn_points, 30)
        self.assertEqual(score.fix_points, 20)
        self.assertEqual(score.total, 100)

    def test_fix_ratio_never_exceeds_one(self):
        score = score_function(1, 3, 99)  # impossible input clamped
        self.assertEqual(score.fix_commits_180d, 3)
        self.assertEqual(score.fix_points, 20)
        self.assertEqual(score.fix_ratio_pct, 100)

    def test_advice_thresholds(self):
        low = score_function(1, 0, 0)
        self.assertLessEqual(low.total, 29)
        self.assertEqual(low.advice, "低风险，放心改")

        high = score_function(6, 0, 0)
        self.assertGreaterEqual(high.total, 30)
        self.assertIn("6 个调用方", high.advice)
        self.assertIn("建议补测试再动", high.advice)

        with_fixes = score_function(6, 4, 2)
        self.assertIn("2 次 fix 历史", with_fixes.advice)


@unittest.skipUnless(HAS_GIT, "git binary required")
class PipelineIntegrationTest(unittest.TestCase):
    def test_scan_plus_git_equals_expected_score(self):
        root = fresh_dir("pipe")
        self.addCleanup(shutil.rmtree, root, True)
        write_tree(
            root,
            {
                "pkg/util.py": "def handler(x):\n    return x\n",
                "app/main.py": (
                    "from pkg.util import handler\n"
                    "\n"
                    "def a():\n"
                    "    return handler(1)\n"
                    "\n"
                    "def b():\n"
                    "    return handler(2)\n"
                ),
            },
        )
        now = datetime.now(timezone.utc)
        git_commit_all(root, "initial import", when=now - timedelta(days=200))
        write_tree(root, {"pkg/util.py": "def handler(x):\n    return x  # v2\n"})
        git_commit_all(root, "refactor handler", when=now - timedelta(days=40))
        write_tree(root, {"pkg/util.py": "def handler(x):\n    return x  # v3\n"})
        git_commit_all(root, "fix handler bug", when=now - timedelta(days=10))

        index = scan_repository(root)
        signal = git_history_for_files(root, ["pkg/util.py"], now=now)
        score = score_function(
            len(index.callsites_of("handler")),
            signal.commits_180d,
            signal.fix_commits_180d,
        )
        self.assertEqual(score.callsites, 2)
        self.assertEqual(signal.commits_180d, 2)
        self.assertEqual(signal.fix_commits_180d, 1)
        self.assertEqual((score.breadth_points, score.churn_points, score.fix_points), (10, 6, 10))
        self.assertEqual(score.total, 26)
        self.assertEqual(score.advice, "低风险，放心改")


if __name__ == "__main__":
    unittest.main()
