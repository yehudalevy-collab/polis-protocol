import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# A stdout that cannot encode anything outside ASCII: the POSIX/C locale plus an
# explicit ASCII PYTHONIOENCODING. This is what a plain `LANG=C` shell, a
# Windows code page, or some CI log capturers hand the process.
ASCII_ONLY_ENV = dict(os.environ, PYTHONIOENCODING="ascii", LC_ALL="C", LANG="C")


def _run_ascii(args, cwd=None):
    """Run `python -m polis <args>` with an ASCII-only stdout."""
    return subprocess.run(
        [sys.executable, "-m", "polis", *args],
        cwd=str(cwd or ROOT),
        capture_output=True,
        env=ASCII_ONLY_ENV,
        # Decode explicitly so these tests behave identically whatever locale
        # the *parent* interpreter happens to be running under.
        encoding="ascii",
        errors="replace",
    )


class ModuleMainTest(unittest.TestCase):
    def test_module_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "polis", "--help"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage: polis <command>", result.stdout)

    def test_module_version(self):
        result = subprocess.run(
            [sys.executable, "-m", "polis", "version"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("polis ", result.stdout)

    def test_ascii_only_env_really_is_ascii_only(self):
        # Premise guard for the two tests below. If a future Python ignored
        # PYTHONIOENCODING, they would keep passing while silently testing
        # nothing -- they would just be duplicates of test_module_help. Assert
        # the child's stdout encoding genuinely cannot represent an em dash.
        probe = subprocess.run(
            [sys.executable, "-c", "import sys; print(sys.stdout.encoding)"],
            capture_output=True,
            env=ASCII_ONLY_ENV,
            encoding="ascii",
            errors="replace",
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        with self.assertRaises(UnicodeEncodeError):
            "—".encode(probe.stdout.strip())

    def test_module_help_on_ascii_only_stdout(self):
        # Usage text must survive an ASCII-only stdout rather than dying with a
        # UnicodeEncodeError traceback out of `print(USAGE)`.
        result = _run_ascii([])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("usage: polis <command>", result.stdout)
        # Surviving is not enough: USAGE holds no character this stream cannot
        # represent, so it must arrive intact rather than pocked with "?"
        # markers. This is what keeping the source literals ASCII buys, and it
        # is why the stream reconfigure alone is not the whole fix.
        self.assertIn("- local-first control plane", result.stdout)
        self.assertNotIn(
            "?", result.stdout,
            "usage output carries an encoder replacement marker: some literal in "
            "USAGE is not ASCII (or a genuine '?' was added, in which case narrow "
            "this assertion)",
        )

    def test_user_supplied_non_ascii_output_on_ascii_only_stdout(self):
        # USAGE was only the messenger. This pins the actual repair: output
        # built from USER DATA, which no amount of ASCII-ing the source
        # literals can rescue -- a reservation note reaches stdout exactly as
        # the user typed it, so only reconfiguring the stream keeps the command
        # alive. Restoring the non-ASCII source literals fails only the test
        # above; deleting the stream reconfigure fails this one too -- so the
        # two cases together pin both halves of the fix.
        note = "café ☕ naïve"  # e-acute, hot beverage, i-diaeresis
        with tempfile.TemporaryDirectory() as tmp:
            polis_root = Path(tmp) / "_polis"
            polis_root.mkdir()
            reserved = _run_ascii([
                "reserve", "src/auth.py", "--as", "agent-a",
                "--note", note, "--polis-root", str(polis_root),
            ])
            self.assertEqual(reserved.returncode, 0, reserved.stderr)
            listed = _run_ascii(["reservations", "--polis-root", str(polis_root)])

        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertNotIn("Traceback", listed.stderr)
        # The note itself degrades to replacement markers -- unavoidable on a
        # stream that cannot represent it -- but the line and the exit status
        # both survive, which is the whole point.
        self.assertIn("agent-a: src/auth.py", listed.stdout)

    def test_module_missing_cli_fails_cleanly(self):
        # Build a throwaway `polis` package that reuses the REAL __main__.py but
        # ships no cli.py, so `from polis.cli import main` cannot resolve. The
        # entry point must exit non-zero with a clear message and NOT leak a
        # Python traceback.
        main_src = (ROOT / "polis" / "__main__.py").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "polis"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            (pkg / "__main__.py").write_text(main_src)
            result = subprocess.run(
                [sys.executable, "-m", "polis"],
                cwd=tmp,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("could not load the command-line interface", result.stderr)

if __name__ == "__main__":
    unittest.main()
