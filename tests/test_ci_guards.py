"""Run the static CI guards as part of the test suite."""
import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_GUARD = _ROOT / "scripts" / "ci_guards.py"

_spec = importlib.util.spec_from_file_location("ci_guards", _GUARD)
assert _spec is not None and _spec.loader is not None
ci_guards = importlib.util.module_from_spec(_spec)
sys.modules["ci_guards"] = ci_guards
_spec.loader.exec_module(ci_guards)


def test_ci_guards_self_test_passes() -> None:
    assert ci_guards._self_test() == 0


def test_repo_source_has_no_enforcement_violations() -> None:
    # Source-only scan (no docs dir): the shipped src/novax must be clean.
    report = ci_guards.run_all(_ROOT, [])
    src_violations = [v for v in report.violations if v.check != "docs-threshold"]
    assert src_violations == [], "\n".join(str(v) for v in src_violations)
