"""Command-line interface: ``impact`` / ``risk`` / ``report``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .ast_index import CodeIndex, scan_repository
from .gitstats import HISTORY_DAYS, HistorySignal, git_history_for_files
from .risk import RiskScore, score_function

_COMMANDS = {}


class DataError(Exception):
    """Recoverable data problem -> exit code 1."""


def _reconfigure_stdio() -> None:
    """Force UTF-8 stdio so legacy consoles (e.g. GBK) never crash the CLI."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _command(name):
    def register(func):
        _COMMANDS[name] = func
        return func

    return register


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="callquake",
        description="改一行代码前先看波及面：AST 调用链 + git 历史 = 0-100 风险分。",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    sub = parser.add_subparsers(
        dest="command", required=True, metavar="{impact,risk,report}"
    )

    p_impact = sub.add_parser(
        "impact", help="列出调用某函数的所有位置（AST 反向索引）"
    )
    p_impact.add_argument("function", help="函数/方法名")
    p_impact.add_argument("--path", default=".", help="目标仓库路径（默认当前目录）")

    p_risk = sub.add_parser("risk", help="输出某函数的 0-100 风险分与分项建议")
    p_risk.add_argument("function", help="函数/方法名")
    p_risk.add_argument("--path", default=".", help="目标仓库路径（默认当前目录）")

    p_report = sub.add_parser(
        "report", help="全仓 Top-10 高风险函数（Markdown 表格）"
    )
    p_report.add_argument("--path", default=".", help="目标仓库路径（默认当前目录）")
    return parser


def _load(path_value: str) -> tuple[CodeIndex, Path]:
    """Scan the target directory, raising DataError on unusable input."""
    root = Path(path_value)
    if not root.exists():
        raise DataError(f"路径不存在: {root}")
    if not root.is_dir():
        raise DataError(f"不是目录: {root}")
    index = scan_repository(root)
    if index.files_scanned == 0:
        raise DataError(f"{root} 下没有任何 .py 文件，无法分析")
    return index, root


def _lookup(index: CodeIndex, name: str):
    defs = index.definitions_of(name)
    sites = index.callsites_of(name)
    if not defs and not sites:
        raise DataError(f"未找到 '{name}' 的定义或调用点")
    return defs, sites


@_command("impact")
def _cmd_impact(args) -> int:
    index, _root = _load(args.path)
    defs, sites = _lookup(index, args.function)

    lines = [
        f"函数 '{args.function}' 的波及面（扫描 {index.files_scanned} 个 .py 文件）",
        f"定义 {len(defs)} 处:",
    ]
    for d in defs:
        prefix = "async " if d.kind == "async" else ""
        lines.append(f"  {d.file}:{d.line}  {prefix}{d.qualname}")
    lines.append(f"调用方 {len(sites)} 处:")
    for c in sites:
        lines.append(f"  {c.file}:{c.line}  {c.dotted}(...)")
    lines.append("注: 动态调用（getattr/exec/字符串反射）对 AST 不可见，不计入。")
    print("\n".join(lines))
    return 0


@_command("risk")
def _cmd_risk(args) -> int:
    index, root = _load(args.path)
    defs, sites = _lookup(index, args.function)

    signal = git_history_for_files(root, [d.file for d in defs])
    score = score_function(len(sites), signal.commits_180d, signal.fix_commits_180d)

    lines = [
        f"函数 '{args.function}' 风险分: {score.total}/100",
        f"  调用广度: {score.breadth_points}/50（{score.callsites} 个调用点）",
        (
            f"  历史热度: {score.history_points}/50"
            f"（近 {HISTORY_DAYS} 天改动 {score.commits_180d} 次；"
            f"fix/bug 提交 {score.fix_commits_180d} 次，占 {score.fix_ratio_pct}%）"
        ),
        f"建议: {score.advice}",
    ]
    if not signal.available:
        lines.insert(
            1,
            f"  提示: 未检测到可用 git 仓库（{signal.note}），历史热度按 0 计。",
        )
    print("\n".join(lines))
    return 0


@_command("report")
def _cmd_report(args) -> int:
    index, root = _load(args.path)

    rows: list[tuple[RiskScore, str]] = []
    git_missing = False
    for name in sorted({d.name for d in index.definitions}):
        defs = index.definitions_of(name)
        sites = index.callsites_of(name)
        signal = git_history_for_files(root, {d.file for d in defs})
        git_missing = git_missing or not signal.available
        score = score_function(len(sites), signal.commits_180d, signal.fix_commits_180d)
        rows.append((score, name))

    rows.sort(key=lambda item: (-item[0].total, item[1]))
    top = rows[:10]

    lines = [
        "# 高风险函数 Top 10",
        "",
        f"共评估 {len(rows)} 个函数名；风险分 = 调用广度(0-50) + 历史热度(0-50)。",
        "",
        "| 排名 | 函数 | 风险分 | 调用点 | 近180天改动 | fix占比 | 建议 |",
        "|---:|---|---:|---:|---:|---:|---|",
    ]
    for rank, (score, name) in enumerate(top, start=1):
        lines.append(
            f"| {rank} | `{name}` | {score.total} | {score.callsites} "
            f"| {score.commits_180d} | {score.fix_ratio_pct}% | {score.advice} |"
        )
    if git_missing:
        lines.append("")
        lines.append("（部分目录未检测到可用 git 仓库，历史热度按 0 计。）")
    print("\n".join(lines))
    return 0


def main(argv=None) -> int:
    """CLI entry point; returns the process exit code."""
    _reconfigure_stdio()
    parser = _build_parser()
    args = parser.parse_args(argv)  # usage errors -> argparse exits 2
    handler = _COMMANDS[args.command]
    try:
        return handler(args)
    except DataError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
