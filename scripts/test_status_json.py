#!/usr/bin/env python3
"""Tests for `polis status --json`."""
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from polis.cli import cmd_status  # noqa: E402


def _make_empty_polis(root: Path):
    root.mkdir(parents=True)
    (root / "CONSTITUTION.md").write_text("# c\n", encoding="utf-8")


def _write_card(root: Path, agent_id: str):
    cdir = root / "citizens" / agent_id
    cdir.mkdir(parents=True)
    (cdir / "capability_card.yml").write_text(
        f"agent_id: {agent_id}\nvendor: test\ncapability_tags:\n  dev: {{self_rating: 4}}\n",
        encoding="utf-8")


class StatusJsonTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        # .resolve() because the CLI resolves --polis-root before echoing it
        # back, and on macOS the tempdir sits under /var, a symlink to
        # /private/var. Without this the expected and actual paths differ by
        # that prefix and every path assertion below fails locally while
        # passing on Linux CI.
        self.root = Path(self._tmp.name).resolve() / "_polis"
        _make_empty_polis(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def _run_json_tool(self, text: str):
        return subprocess.run(
            [sys.executable, "-m", "json.tool"],
            input=text,
            capture_output=True,
            text=True,
            check=True,
        )

    def test_empty_polis_json_round_trips(self):
        result = subprocess.run(
            [sys.executable, "-m", "polis", "status", "--polis-root", str(self.root), "--json"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        pretty = self._run_json_tool(result.stdout)
        self.assertIn('"citizens": []', pretty.stdout)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "polis_root": str(self.root),
                "citizens": [],
                "open_contracts": 0,
                "settled_contracts": 0,
                "explore_rate": 0.15,
                "routing_by_tag": {},
            },
        )

    def test_populated_polis_json_round_trips_with_sorted_keys(self):
        _write_card(self.root, "zeta")
        _write_card(self.root, "alpha")
        open_dir = self.root / "contracts" / "open"
        settled_dir = self.root / "contracts" / "settled"
        open_dir.mkdir(parents=True)
        settled_dir.mkdir(parents=True)
        (open_dir / "o1.md").write_text("open\n", encoding="utf-8")
        (settled_dir / "s1.md").write_text("settled\n", encoding="utf-8")
        (settled_dir / "s2.md").write_text("settled\n", encoding="utf-8")
        (self.root / "contracts" / "routing_stats.yml").write_text(
            "explore_rate: 0.25\n"
            "tags:\n"
            "  zebra:\n"
            "    leader: zeta\n"
            "    leader_confidence: 0.9\n"
            "  alpha:\n"
            "    leader: alpha\n"
            "    leader_confidence: 0.75\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [sys.executable, "-m", "polis", "status", "--polis-root", str(self.root), "--json"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self._run_json_tool(result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["citizens"], ["alpha", "zeta"])
        self.assertEqual(payload["open_contracts"], 1)
        self.assertEqual(payload["settled_contracts"], 2)
        self.assertEqual(payload["explore_rate"], 0.25)
        self.assertEqual(list(payload["routing_by_tag"]), ["alpha", "zebra"])
        self.assertEqual(
            payload["routing_by_tag"]["alpha"],
            {"leader": "alpha", "leader_confidence": 0.75},
        )

    def test_default_status_text_output_is_unchanged(self):
        _write_card(self.root, "alpha")
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(cmd_status(["--polis-root", str(self.root)]), 0)

        self.assertEqual(
            out.getvalue(),
            f"polis: {self.root}\n"
            "  citizens          : 1\n"
            "      - alpha\n"
            "  open contracts    : 0\n"
            "  settled contracts : 0\n"
            "  explore_rate      : 0.15\n",
        )

    def test_help_mentions_json_flag(self):
        result = subprocess.run(
            [sys.executable, "-m", "polis", "status", "--help"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--json", result.stdout)


if __name__ == "__main__":
    unittest.main()
