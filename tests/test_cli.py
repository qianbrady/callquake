"""End-to-end CLI tests: exit codes, determinism, GBK console smoke."""

from __future__ import annotations

import shutil
import unittest
from datetime import datetime, timedelta, timezone

from _harness import (
    SAMPLE_FILES,
    fresh_dir,
    git_commit_all,
    line_of,
    run_cli,
    sample_repo,
    write_tree,
)


class CliImpactTest(unittest.TestCase):
    def setUp(self):
        self.root = sample_repo()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_impact_lists_callers_with_file_and_line(self):
        util_text = SAMPLE_FILES["pkg/util.py"]
        result = run_cli(["impact", "helper", "--path", str(self.root)])
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode("utf-8"))
        out = result.stdout.decode("utf-8")
        self.assertIn(f"pkg/util.py:{line_of(util_text, 'return helper(1)')}", out)
        self.assertIn("调用方 2 处:", out)
        self.assertIn("动态调用", out)

    def test_usage_errors_exit_two(self):
        for argv in ([], ["impact"], ["impact", "f", "--bogus"], ["frobnicate"]):
            with self.subTest(argv=argv):
                result = run_cli(argv)
                self.assertEqual(result.returncode, 2)

    def test_unknown_function_exit_one(self):
        result = run_cli(["impact", "ghost_function", "--path", str(self.root)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("ghost_function", result.stderr.decode("utf-8"))

    def test_version_flag(self):
        result = run_cli(["--version"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("0.1.0", result.stdout.decode("utf-8"))

    def test_gbk_console_smoke(self):
        """PYTHONIOENCODING=gbk must not crash nor mojibake the output."""
        result = run_cli(
            ["impact", "helper", "--path", str(self.root)],
            env_extra={"PYTHONIOENCODING": "gbk"},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode("utf-8"))
        out = result.stdout.decode("utf-8")
        self.assertIn("波及面", out)
        self.assertIn("调用方", out)


class CliDataErrorTest(unittest.TestCase):
    def test_empty_dir_friendly_message(self):
        empty = fresh_dir("empty")
        self.addCleanup(shutil.rmtree, empty, True)
        result = run_cli(["report", "--path", str(empty)])
        self.assertEqual(result.returncode, 1)
        err = result.stderr.decode("utf-8")
        self.assertIn(".py", err)
        self.assertNotIn("Traceback", err)

    def test_non_python_dir_friendly_message(self):
        plain = fresh_dir("plain")
        self.addCleanup(shutil.rmtree, plain, True)
        (plain / "readme.txt").write_text("nothing to see", encoding="utf-8")
        result = run_cli(["impact", "x", "--path", str(plain)])
        self.assertEqual(result.returncode, 1)
        err = result.stderr.decode("utf-8")
        self.assertIn(".py", err)
        self.assertNotIn("Traceback", err)

    def test_missing_path_exit_one(self):
        result = run_cli(["report", "--path", "Z:/definitely/not/here"])
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr.decode("utf-8"))


class CliRiskReportTest(unittest.TestCase):
    def _git_repo(self, commits):
        root = fresh_dir("riskcli")
        self.addCleanup(shutil.rmtree, root, True)
        now = datetime.now(timezone.utc)
        for message, days, patch in commits:
            write_tree(root, patch)
            git_commit_all(root, message, when=now - timedelta(days=days))
        return root

    def test_risk_low_risk_numbers(self):
        util_v2 = {"pkg/util.py": SAMPLE_FILES["pkg/util.py"] + "# churn 1\n"}
        util_v3 = {"pkg/util.py": SAMPLE_FILES["pkg/util.py"] + "# churn 1\n# churn 2\n"}
        root = self._git_repo(
            [
                ("initial import", 200, SAMPLE_FILES),
                ("refactor handler", 40, util_v2),
                ("fix handler bug", 10, util_v3),
            ],
        )
        result = run_cli(["risk", "helper", "--path", str(root)])
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode("utf-8"))
        out = result.stdout.decode("utf-8")
        self.assertIn("风险分: 26/100", out)
        self.assertIn("调用广度: 10/50（2 个调用点）", out)
        self.assertIn("历史热度: 16/50", out)
        self.assertIn("低风险，放心改", out)

    def test_risk_high_risk_advice(self):
        hot_lines = ["def hot(x):", "    return x"]
        for i in range(11):
            hot_lines += ["", f"def caller_{i}():", f"    return hot({i})"]
        base = {"hot.py": "\n".join(hot_lines) + "\n"}
        root = self._git_repo(
            [
                ("initial import", 300, base),
                ("bug b", 10, {"hot.py": "\n".join(hot_lines) + "# churn1\n"}),
                ("fix a", 1, {"hot.py": "\n".join(hot_lines) + "# churn1\n# churn2\n"}),
            ],
        )
        result = run_cli(["risk", "hot", "--path", str(root)])
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode("utf-8"))
        out = result.stdout.decode("utf-8")
        self.assertIn("风险分: 76/100", out)
        self.assertIn("有 11 个调用方 + 2 次 fix 历史，建议补测试再动", out)

    def test_report_markdown_sorted_top(self):
        alpha_text = (
            "def alpha(x):\n"
            "    return x\n"
            "\n"
            "\n"
            "def beta():\n"
            "    return 0\n"
            "\n"
            "\n"
            "def u1():\n"
            "    return alpha(1)\n"
            "\n"
            "\n"
            "def u2():\n"
            "    return alpha(2)\n"
            "\n"
            "\n"
            "def u3():\n"
            "    return alpha(3)\n"
        )
        root = fresh_dir("repcli")
        self.addCleanup(shutil.rmtree, root, True)
        write_tree(root, {"mod.py": alpha_text})

        result = run_cli(["report", "--path", str(root)])
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode("utf-8"))
        out = result.stdout.decode("utf-8")
        self.assertIn("| 排名 | 函数 | 风险分 | 调用点 | 近180天改动 | fix占比 | 建议 |", out)
        self.assertIn("`alpha`", out)
        self.assertIn("`beta`", out)
        self.assertLess(out.index("`alpha`"), out.index("`beta`"))

    def test_determinism_double_run_identical_bytes(self):
        root = sample_repo(with_git=True)
        first_impact = run_cli(["impact", "helper", "--path", str(root)]).stdout
        second_impact = run_cli(["impact", "helper", "--path", str(root)]).stdout
        self.assertEqual(first_impact, second_impact)

        first_risk = run_cli(["risk", "helper", "--path", str(root)]).stdout
        second_risk = run_cli(["risk", "helper", "--path", str(root)]).stdout
        self.assertEqual(first_risk, second_risk)


if __name__ == "__main__":
    unittest.main()
