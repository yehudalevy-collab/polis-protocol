#!/usr/bin/env python3
"""Tests for the contract lifecycle (open -> claim -> settle / abandon)."""
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from polis import contracts as C  # noqa: E402
from polis.cli import USAGE, cmd_contract  # noqa: E402
from polis.routing import parse_frontmatter  # noqa: E402


def _fm(path):
    return parse_frontmatter(Path(path).read_text(encoding="utf-8"))[0]


class ContractLifecycleTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "_polis"
        self.root.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_open_creates_proposed_contract(self):
        res = C.open_contract(self.root, "Add login page", ["react", "css"], "alice")
        self.assertEqual(res["contract_id"], "add-login-page")
        fm = _fm(res["path"])
        self.assertEqual(fm["status"], "proposed")
        self.assertIsNone(fm["owner"])
        self.assertEqual(fm["required_tags"], ["react", "css"])

    def test_unique_ids(self):
        a = C.open_contract(self.root, "Same Title", [], "alice")["contract_id"]
        b = C.open_contract(self.root, "Same Title", [], "alice")["contract_id"]
        self.assertNotEqual(a, b)
        self.assertTrue(b.endswith("-2"))

    def test_claim_then_settle_moves_to_settled(self):
        cid = C.open_contract(self.root, "Build API", ["python"], "alice")["contract_id"]
        self.assertTrue(C.claim_contract(self.root, cid, "bob")["ok"])
        path, state = C.find_contract(self.root, cid)
        self.assertEqual(state, "open")
        self.assertEqual(_fm(path)["owner"], "bob")
        self.assertEqual(_fm(path)["status"], "claimed")

        res = C.settle_contract(self.root, cid, quality=4, minutes=120, by="bob")
        self.assertTrue(res["ok"])
        path, state = C.find_contract(self.root, cid)
        self.assertEqual(state, "settled")
        fm = _fm(path)
        self.assertEqual(fm["status"], "settled")
        self.assertEqual(fm["quality_score"], 4)
        self.assertEqual(fm["actual_minutes"], 120)
        # no longer in open/
        self.assertFalse((self.root / "contracts" / "open" / f"{cid}.md").exists())

    def test_claim_conflict_rejected_without_force(self):
        cid = C.open_contract(self.root, "Task", [], "alice")["contract_id"]
        self.assertTrue(C.claim_contract(self.root, cid, "bob")["ok"])
        res = C.claim_contract(self.root, cid, "carol")
        self.assertFalse(res["ok"])
        self.assertIn("already owned by bob", res["reason"])
        self.assertTrue(C.claim_contract(self.root, cid, "carol", force=True)["ok"])

    def test_settle_clamps_quality(self):
        cid = C.open_contract(self.root, "Q", [], "alice")["contract_id"]
        C.settle_contract(self.root, cid, quality=99)
        path, _ = C.find_contract(self.root, cid)
        self.assertEqual(_fm(path)["quality_score"], 5)

    def test_abandon_moves_out_of_routing_path(self):
        cid = C.open_contract(self.root, "Doomed", [], "alice")["contract_id"]
        res = C.abandon_contract(self.root, cid, reason="descoped")
        self.assertTrue(res["ok"])
        path, state = C.find_contract(self.root, cid)
        self.assertEqual(state, "abandoned")
        self.assertEqual(_fm(path)["status"], "abandoned")
        # not in settled/ (so reconcile never sees it)
        self.assertFalse((self.root / "contracts" / "settled" / f"{cid}.md").exists())

    def test_cannot_settle_already_settled(self):
        cid = C.open_contract(self.root, "Once", [], "alice")["contract_id"]
        C.settle_contract(self.root, cid, quality=3)
        res = C.settle_contract(self.root, cid, quality=5)
        self.assertFalse(res["ok"])

    def test_list_filters_by_state(self):
        C.open_contract(self.root, "Open one", [], "alice")
        cid = C.open_contract(self.root, "Done one", [], "alice")["contract_id"]
        C.settle_contract(self.root, cid, quality=4)
        self.assertEqual(len(C.list_contracts(self.root, "open")), 1)
        self.assertEqual(len(C.list_contracts(self.root, "settled")), 1)


class ContractShowTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "_polis"
        self.root.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _show(self, *argv):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cmd_contract(["show", *argv, "--polis-root", str(self.root)])
        return code, out.getvalue(), err.getvalue()

    def test_show_open_contract_prints_path_then_raw_body(self):
        cid = C.open_contract(self.root, "Add login page", ["react"], "alice")["contract_id"]
        path, state = C.find_contract(self.root, cid)
        self.assertEqual(state, "open")

        code, out, err = self._show(cid)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(out, f"{path}\n" + path.read_text(encoding="utf-8"))

    def test_show_finds_settled_and_abandoned_contracts(self):
        settled = C.open_contract(self.root, "Done one", [], "alice")["contract_id"]
        C.settle_contract(self.root, settled, quality=4)
        abandoned = C.open_contract(self.root, "Doomed", [], "alice")["contract_id"]
        C.abandon_contract(self.root, abandoned, reason="descoped")

        for cid, expected_state in ((settled, "settled"), (abandoned, "abandoned")):
            path, state = C.find_contract(self.root, cid)
            self.assertEqual(state, expected_state)
            code, out, err = self._show(cid)
            self.assertEqual(code, 0, err)
            self.assertEqual(out, f"{path}\n" + path.read_text(encoding="utf-8"))
            self.assertIn(f"contract_id: {cid}", out)
            self.assertIn(f"status: {expected_state}", out)

    def test_show_unknown_id_errors_on_stderr_and_exits_nonzero(self):
        code, out, err = self._show("no-such-contract")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("not found", err)
        self.assertIn("no-such-contract", err)

    def test_usage_lines_mention_show(self):
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(cmd_contract([]), 2)
        self.assertIn("show", out.getvalue())

        contract_line = next(line for line in USAGE.splitlines()
                             if line.strip().startswith("contract "))
        self.assertIn("show", contract_line)


if __name__ == "__main__":
    unittest.main()
