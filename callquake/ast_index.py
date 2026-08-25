"""Static AST scanning: build a who-calls-whom reverse index for a repository.

Standard library only.  Known limitation (by design, documented in README):
dynamic calls -- ``getattr(obj, "name")``, ``exec``/``eval`` strings, subscript
dispatch such as ``registry[name]()`` -- are invisible to a pure AST walk and
are therefore NOT counted as call sites.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path

#: Directory names that are never descended into while scanning.
SKIP_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".eggs",
        "node_modules",
        "build",
        "dist",
        "site-packages",
    }
)


@dataclass(frozen=True)
class Definition:
    """A function/method definition found in the scanned tree."""

    name: str  # simple name, e.g. "helper"
    qualname: str  # qualified chain, e.g. "Widget.Gear.spin"
    file: str  # POSIX-style path relative to the scan root
    line: int  # 1-based line number
    kind: str  # "def" | "async"


@dataclass(frozen=True)
class CallSite:
    """A syntactic call ``X(...)`` found in the scanned tree."""

    simple: str  # tail name, e.g. "helper" for ``self.helper()``
    dotted: str  # expression as written, e.g. "self.helper"
    file: str  # POSIX-style path relative to the scan root
    line: int  # 1-based line number


@dataclass
class CodeIndex:
    """Reverse-call index over one repository snapshot."""

    definitions: tuple[Definition, ...] = ()
    callsites: tuple[CallSite, ...] = ()
    files_scanned: int = 0
    files_skipped: tuple[str, ...] = ()  # unparsable files (syntax errors)

    def definitions_of(self, name: str) -> list[Definition]:
        return [d for d in self.definitions if d.name == name]

    def callsites_of(self, name: str) -> list[CallSite]:
        return [c for c in self.callsites if c.simple == name]


def iter_python_files(root: Path):
    """Yield all ``*.py`` files under *root*, deterministically ordered."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in SKIP_DIRS and not d.endswith(".egg-info")
        )
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                yield Path(dirpath) / filename


def _dotted_name(node: ast.AST) -> str | None:
    """Best-effort dotted name of a call target; ``None`` when dynamic."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        if base is not None:
            return f"{base}.{node.attr}"
    return None


def scan_repository(root) -> CodeIndex:
    """Parse every ``*.py`` under *root* and build the reverse-call index.

    Unparsable files are recorded in :attr:`CodeIndex.files_skipped` instead of
    aborting the whole scan, so one broken file never hides the rest.
    """
    root = Path(root)
    definitions: list[Definition] = []
    callsites: list[CallSite] = []
    skipped: list[str] = []
    scanned = 0

    for path in iter_python_files(root):
        scanned += 1
        rel = path.relative_to(root).as_posix()
        try:
            source = path.read_bytes().decode("utf-8", errors="replace")
            tree = ast.parse(source, filename=rel)
        except (SyntaxError, ValueError, OSError):
            skipped.append(rel)
            continue
        _collect(tree, rel, definitions, callsites)

    definitions.sort(key=lambda d: (d.file, d.line, d.qualname))
    callsites.sort(key=lambda c: (c.file, c.line, c.dotted))
    skipped.sort()
    return CodeIndex(tuple(definitions), tuple(callsites), scanned, tuple(skipped))


def _collect(tree: ast.AST, rel: str, definitions, callsites) -> None:
    """Walk one module, collecting definitions and call sites."""
    scope: list[str] = []

    class Visitor(ast.NodeVisitor):
        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            scope.append(node.name)
            self.generic_visit(node)
            scope.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._function(node, "def")

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._function(node, "async")

        def _function(self, node, kind: str) -> None:
            qualname = ".".join([*scope, node.name])
            definitions.append(
                Definition(node.name, qualname, rel, node.lineno, kind)
            )
            # Decorator calls are picked up by generic_visit below, because
            # decorator_list is part of the FunctionDef's child fields.
            scope.append(node.name)
            self.generic_visit(node)
            scope.pop()

        def visit_Call(self, node: ast.Call) -> None:
            dotted = _dotted_name(node.func)
            if dotted is not None:
                callsites.append(
                    CallSite(dotted.rsplit(".", 1)[-1], dotted, rel, node.lineno)
                )
            self.generic_visit(node)

    Visitor().visit(tree)
