#!/usr/bin/env python3
"""Static enforcement guards for the Novax research platform (Phase 0.7).

These guards make the Phase 0.7 bypasses *tamper-evident*: the runtime tests prove
the bypasses fail today; these guards stop someone re-introducing them tomorrow.

Checks (all fail-closed; any violation -> exit code 1):
  1. No direct ArtifactRegistry artifact construction (`.register(`) outside the runner.
  2. No raw `registry.log(Trial(...))` outside the runner.
  3. No public Go/No-Go API with a boolean parameter.
  4. No raw-float ATR at CostModel public boundaries (must be annotated `Pips`).
  5. No doc says "DSR > 0" without also saying "superseded".

Stdlib only. Python 3.12.

Usage:
    python scripts/ci_guards.py [--root PATH] [--docs-dir PATH ...]
    python scripts/ci_guards.py --self-test
"""
from __future__ import annotations

import argparse
import ast
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

# Files where the otherwise-forbidden constructs are legitimately defined/used.
_REGISTER_ALLOW = {"runner.py", "artifacts.py"}
_LOG_TRIAL_ALLOW = {"runner.py", "trial_registry.py"}
_COST_MODEL_FILES = {"costs.py"}
_GATE_NAME_HINTS = ("gate", "go_no_go")


@dataclass(slots=True)
class Violation:
    check: str
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"[{self.check}] {self.path}:{self.line}: {self.message}"


@dataclass(slots=True)
class GuardReport:
    violations: list[Violation] = field(default_factory=list)

    def add(self, v: Violation) -> None:
        self.violations.append(v)

    @property
    def ok(self) -> bool:
        return not self.violations


# --------------------------------------------------------------------------- #
# AST-based source checks
# --------------------------------------------------------------------------- #
def _iter_py(root: Path) -> Iterable[Path]:
    src = root / "src" / "novax"
    if not src.is_dir():
        return []
    return sorted(p for p in src.rglob("*.py") if "__pycache__" not in p.parts)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def check_no_direct_register(root: Path, report: GuardReport) -> None:
    """(1) Forbid `<something>.register(...)` outside the runner/artifacts modules."""
    for path in _iter_py(root):
        if path.name in _REGISTER_ALLOW:
            continue
        tree = _parse(path)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "register"):
                report.add(Violation(
                    "no-direct-register", str(path), node.lineno,
                    "artifact registration must go through Evaluation.emit (runner)"))


def check_no_raw_log_trial(root: Path, report: GuardReport) -> None:
    """(2) Forbid `<reg>.log(Trial(...))` outside the runner/registry modules."""
    for path in _iter_py(root):
        if path.name in _LOG_TRIAL_ALLOW:
            continue
        tree = _parse(path)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "log"):
                for arg in node.args:
                    if (isinstance(arg, ast.Call)
                            and isinstance(arg.func, ast.Name)
                            and arg.func.id == "Trial"):
                        report.add(Violation(
                            "no-raw-log-trial", str(path), node.lineno,
                            "trials must be logged by ExperimentRunner, not directly"))


def _ann_name(ann: ast.expr | None) -> str | None:
    if isinstance(ann, ast.Name):
        return ann.id
    if isinstance(ann, ast.Attribute):
        return ann.attr
    return None


def check_no_bool_gate_params(root: Path, report: GuardReport) -> None:
    """(3) Forbid boolean parameters in any public Go/No-Go function."""
    for path in _iter_py(root):
        tree = _parse(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            name = node.name.lower()
            if not any(h in name for h in _GATE_NAME_HINTS):
                continue
            if name.startswith("_"):
                continue
            args = node.args
            all_args = [*args.posonlyargs, *args.args, *args.kwonlyargs]
            for a in all_args:
                if _ann_name(a.annotation) == "bool":
                    report.add(Violation(
                        "no-bool-gate-param", str(path), node.lineno,
                        f"Go/No-Go function '{node.name}' takes bool param '{a.arg}'; "
                        "verdicts must be computed from artifacts"))


def check_no_raw_float_atr(root: Path, report: GuardReport) -> None:
    """(4) CostModel public methods must annotate any `atr` param as `Pips`."""
    for path in _iter_py(root):
        if path.name not in _COST_MODEL_FILES:
            continue
        tree = _parse(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                continue
            args = node.args
            all_args = [*args.posonlyargs, *args.args, *args.kwonlyargs]
            for a in all_args:
                if "atr" in a.arg.lower():
                    ann = _ann_name(a.annotation)
                    if ann != "Pips":
                        report.add(Violation(
                            "no-raw-float-atr", str(path), node.lineno,
                            f"'{node.name}' param '{a.arg}' must be annotated Pips, "
                            f"got {ann!r}"))


# --------------------------------------------------------------------------- #
# Docs check
# --------------------------------------------------------------------------- #
def _iter_docs(dirs: Iterable[Path]) -> Iterable[Path]:
    for d in dirs:
        if d.is_dir():
            yield from sorted(p for p in d.rglob("*.md"))


def check_docs_threshold(doc_dirs: Iterable[Path], report: GuardReport) -> None:
    """(5) "DSR > 0" must not appear without "superseded" nearby in the same file."""
    for path in _iter_docs(doc_dirs):
        text = path.read_text(encoding="utf-8")
        if "DSR > 0" in text and "superseded" not in text.lower():
            line = next((i + 1 for i, ln in enumerate(text.splitlines())
                         if "DSR > 0" in ln), 1)
            report.add(Violation(
                "docs-threshold", str(path), line,
                'doc states "DSR > 0" without marking it superseded (bar is > 0.95)'))


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def run_all(root: Path, doc_dirs: list[Path]) -> GuardReport:
    report = GuardReport()
    check_no_direct_register(root, report)
    check_no_raw_log_trial(root, report)
    check_no_bool_gate_params(root, report)
    check_no_raw_float_atr(root, report)
    default_docs = [root / "docs"]
    check_docs_threshold([*default_docs, *doc_dirs], report)
    return report


# --------------------------------------------------------------------------- #
# Minimal self-tests (hermetic; use temp dirs)
# --------------------------------------------------------------------------- #
def _self_test() -> int:
    failures: list[str] = []

    def expect(cond: bool, msg: str) -> None:
        if not cond:
            failures.append(msg)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        pkg = root / "src" / "novax"
        pkg.mkdir(parents=True)
        docs = root / "docs"
        docs.mkdir()

        # --- positive controls: code that SHOULD trip each guard ---
        (pkg / "bad_register.py").write_text(
            "def f(arts):\n    arts.register(run_id='r')\n")
        (pkg / "bad_log.py").write_text(
            "def f(reg):\n    reg.log(Trial(1))\n")
        (pkg / "bad_gate.py").write_text(
            "def evaluate_gate(*, ok: bool) -> int:\n    return 1\n")
        (pkg / "costs.py").write_text(
            "class CostModel:\n"
            "    def round_trip_cost_pips(self, sym: str, *, atr: float = 0.0) -> float:\n"
            "        return atr\n")
        (docs / "old.md").write_text("- Require DSR > 0 always.\n")

        rep = run_all(root, [])
        kinds = {v.check for v in rep.violations}
        for k in ("no-direct-register", "no-raw-log-trial", "no-bool-gate-param",
                  "no-raw-float-atr", "docs-threshold"):
            expect(k in kinds, f"self-test: guard '{k}' failed to fire")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        pkg = root / "src" / "novax"
        pkg.mkdir(parents=True)
        docs = root / "docs"
        docs.mkdir()

        # --- negative controls: compliant code that should NOT trip ---
        (pkg / "runner.py").write_text(  # allowed to register/log
            "def f(arts, reg):\n    arts.register()\n    reg.log(Trial())\n")
        (pkg / "gate.py").write_text(
            "def evaluate_gate(*, run_id: str) -> int:\n    return 1\n")
        (pkg / "costs.py").write_text(
            "class CostModel:\n"
            "    def round_trip_cost_pips(self, sym: str, *, atr: Pips = _Z) -> float:\n"
            "        return 0.0\n")
        (docs / "fixed.md").write_text(
            "- Require DSR > 0 (superseded: the real bar is probability > 0.95).\n")

        rep = run_all(root, [])
        expect(rep.ok, f"self-test: compliant code tripped guards: "
                       f"{[str(v) for v in rep.violations]}")

    if failures:
        print("SELF-TEST FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print("ci_guards self-test: OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Novax static enforcement guards")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent,
                    help="repo root containing src/novax (default: parent of scripts/)")
    ap.add_argument("--docs-dir", type=Path, action="append", default=[],
                    help="extra docs directory to scan (repeatable)")
    ap.add_argument("--self-test", action="store_true", help="run hermetic self-tests")
    ns = ap.parse_args(argv)

    if ns.self_test:
        return _self_test()

    report = run_all(ns.root, list(ns.docs_dir))
    if report.ok:
        print("ci_guards: OK (no enforcement violations)")
        return 0
    print(f"ci_guards: {len(report.violations)} violation(s):")
    for v in report.violations:
        print("  ", v)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
