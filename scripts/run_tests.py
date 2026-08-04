#!/usr/bin/env python3
"""Discover and run every Python regression suite under scripts/.

CI used to enumerate each `scripts/test_*.py` as its own hand-written workflow
step, so a suite added without the matching workflow edit stayed dead in CI —
silently. That happened twice: the initializer dry-run suite (#26) and
`scripts/test_module_main.py` (added in #29, un-run until #50).

This runner discovers the suites from the filesystem instead, so a new
`scripts/test_*.py` is covered with zero workflow edits. It deliberately has no
skip/exclude list: an exclusion mechanism is the same bug wearing a different
hat. Two further guards keep "discovered" from drifting away from "actually
executed":

* an empty discovery is a failure, not a silent pass;
* the final summary reconciles the executed set against the discovered set and
  fails on any suite that was discovered but produced no result.

Stdlib only, by design — the repo's dependency-review gate should never have to
weigh in on the test harness.

Usage (from anywhere; paths resolve relative to this file):

    python3 scripts/run_tests.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

SELF = Path(__file__).resolve()
SCRIPTS_DIR = SELF.parent
REPO_ROOT = SCRIPTS_DIR.parent
SUITE_GLOB = "test_*.py"

_IN_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"
_RULE = "-" * 62


def discover_suites() -> list[Path]:
    """Every scripts/test_*.py, sorted, never including this runner itself."""
    return sorted(
        path
        for path in SCRIPTS_DIR.glob(SUITE_GLOB)
        if path.is_file() and path.resolve() != SELF
    )


def _group(title: str) -> None:
    if _IN_ACTIONS:
        print(f"::group::{title}", flush=True)
    else:
        print(f"\n=== {title} ===", flush=True)


def _endgroup() -> None:
    if _IN_ACTIONS:
        print("::endgroup::", flush=True)


def _annotate_failure(path: Path, code: int) -> None:
    if _IN_ACTIONS:
        rel = path.relative_to(REPO_ROOT).as_posix()
        print(f"::error file={rel}::{rel} failed (exit {code})", flush=True)


def run_suite(path: Path) -> tuple[int, float]:
    """Run one suite in its own process, streaming its output through."""
    started = time.monotonic()
    proc = subprocess.run([sys.executable, str(path)], cwd=str(REPO_ROOT))
    return proc.returncode, time.monotonic() - started


def _print_summary(
    suites: list[Path],
    results: dict[str, tuple[int, float]],
    unrun: list[str],
) -> None:
    print(f"\n{_RULE}")
    print(f"suite summary - {len(suites)} discovered")
    print(_RULE)
    for path in suites:
        name = path.name
        if name in results:
            code, elapsed = results[name]
            status = "PASS" if code == 0 else "FAIL"
            detail = "" if code == 0 else f"  (exit {code})"
            print(f"{status}  {elapsed:6.2f}s  {name}{detail}")
        else:
            print(f"UNRUN      --  {name}  (discovered but never executed)")
    failed = [p.name for p in suites if results.get(p.name, (0, 0.0))[0] != 0]
    print(_RULE)
    print(
        f"{len(suites)} discovered, "
        f"{len(results) - len(failed)} passed, "
        f"{len(failed)} failed, "
        f"{len(unrun)} not run"
    )
    if failed:
        print("FAILED: " + ", ".join(failed))
    if unrun:
        print("NOT RUN: " + ", ".join(unrun))
    sys.stdout.flush()


def main() -> int:
    suites = discover_suites()
    if not suites:
        print(
            f"run_tests: no suites matched {SCRIPTS_DIR}/{SUITE_GLOB} - "
            "discovery is broken, refusing to report success",
            file=sys.stderr,
        )
        return 1

    # flush=True throughout: the suites write to the same fd we do, so anything
    # left in our buffer would surface after their output in a piped CI log.
    print(f"run_tests: {len(suites)} suite(s) discovered in {SCRIPTS_DIR}", flush=True)
    results: dict[str, tuple[int, float]] = {}
    try:
        for path in suites:
            _group(path.name)
            code, elapsed = run_suite(path)
            results[path.name] = (code, elapsed)
            _endgroup()
            if code != 0:
                _annotate_failure(path, code)
    except Exception as exc:  # noqa: BLE001 — the harness must not swallow a suite
        _endgroup()
        print(f"run_tests: aborted while running suites: {exc!r}", file=sys.stderr)

    unrun = [p.name for p in suites if p.name not in results]
    _print_summary(suites, results, unrun)

    failed = [name for name, (code, _) in results.items() if code != 0]
    return 1 if failed or unrun else 0


if __name__ == "__main__":
    sys.exit(main())
