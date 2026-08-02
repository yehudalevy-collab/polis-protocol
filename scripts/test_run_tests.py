#!/usr/bin/env python3
"""Regression tests for the suite runner (scripts/run_tests.py).

These are the tests that would have caught the two historical misses where a
regression suite existed but CI never ran it: the initializer dry-run suite
(#26) and scripts/test_module_main.py (added in #29, un-run until #50).
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "scripts" / "run_tests.py"

PASSING_SUITE = "import sys\nprint('alpha ran')\nsys.exit(0)\n"
FAILING_SUITE = "import sys\nprint('beta ran')\nsys.exit(1)\n"


def _make_fake_repo(tmp: Path, suites: dict, runner_name: str = "run_tests.py") -> Path:
    """Build a throwaway repo with a copy of the real runner and given suites."""
    scripts = tmp / "scripts"
    scripts.mkdir(parents=True)
    runner = scripts / runner_name
    shutil.copy(RUNNER, runner)
    for name, body in suites.items():
        (scripts / name).write_text(body, encoding="utf-8")
    return runner


def _run(runner: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(runner)],
        capture_output=True,
        text=True,
        timeout=120,
    )


class RunnerDiscoveryTest(unittest.TestCase):
    def test_discovers_every_suite_without_any_configuration(self):
        """A suite that nothing lists anywhere still gets run — the #26/#50 bug."""
        with tempfile.TemporaryDirectory() as td:
            runner = _make_fake_repo(
                Path(td),
                {
                    "test_alpha.py": PASSING_SUITE,
                    "test_orphan.py": "print('orphan ran')\n",
                },
            )
            proc = _run(runner)
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, out)
        self.assertIn("orphan ran", out)
        self.assertIn("test_orphan.py", out)
        self.assertIn("test_alpha.py", out)

    def test_non_test_scripts_are_not_run(self):
        with tempfile.TemporaryDirectory() as td:
            runner = _make_fake_repo(
                Path(td),
                {
                    "test_alpha.py": PASSING_SUITE,
                    "helper.py": "raise SystemExit('helper must not run')\n",
                },
            )
            proc = _run(runner)
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, out)
        self.assertNotIn("helper must not run", out)

    def test_runner_does_not_execute_itself(self):
        """Even named so it matches the discovery glob, the runner skips itself."""
        with tempfile.TemporaryDirectory() as td:
            runner = _make_fake_repo(
                Path(td),
                {"test_alpha.py": PASSING_SUITE},
                runner_name="test_selfnamed.py",
            )
            proc = _run(runner)
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, out)
        self.assertIn("alpha ran", out)
        self.assertNotIn("test_selfnamed.py", out)


class RunnerFailurePropagationTest(unittest.TestCase):
    def test_failing_suite_fails_the_run_and_is_named(self):
        with tempfile.TemporaryDirectory() as td:
            runner = _make_fake_repo(
                Path(td),
                {"test_alpha.py": PASSING_SUITE, "test_beta.py": FAILING_SUITE},
            )
            proc = _run(runner)
        out = proc.stdout + proc.stderr
        self.assertNotEqual(proc.returncode, 0, out)
        self.assertIn("test_beta.py", out)
        self.assertIn("FAIL", out)
        # The passing suite must still be reported, so the summary locates the failure.
        self.assertIn("test_alpha.py", out)

    def test_empty_discovery_is_a_failure_not_a_silent_pass(self):
        with tempfile.TemporaryDirectory() as td:
            runner = _make_fake_repo(Path(td), {})
            proc = _run(runner)
        out = proc.stdout + proc.stderr
        self.assertNotEqual(proc.returncode, 0, out)
        self.assertIn("no suites", out)


class RunnerReconciliationTest(unittest.TestCase):
    def test_every_discovered_suite_is_accounted_for_in_the_summary(self):
        names = {f"test_s{i}.py": PASSING_SUITE for i in range(4)}
        with tempfile.TemporaryDirectory() as td:
            runner = _make_fake_repo(Path(td), names)
            proc = _run(runner)
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, out)
        for name in names:
            self.assertIn(name, out)
        self.assertIn(f"{len(names)} discovered", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
