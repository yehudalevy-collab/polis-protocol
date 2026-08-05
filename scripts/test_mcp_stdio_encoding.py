#!/usr/bin/env python3
"""Regression test for issue #57: `polis mcp` must survive malformed stdin bytes.

MCP's stdio transport is UTF-8 by specification, so decoding stdin per the
ambient locale is wrong: under PYTHONIOENCODING=ascii a non-ASCII request line
used to kill the serve loop with UnicodeDecodeError, taking the client's whole
session down.

The contract has two halves, and both are pinned here:

* a malformed byte sequence must be REPORTED as a JSON-RPC parse error
  (-32700, id null — no request id is recoverable from unparseable input),
  never silently repaired (errors="replace" would rewrite bytes inside what
  may be a JSON string value, so the server would act on data the client
  never sent);
* a malformed byte sequence must never take the server down — the next
  well-formed request on the same stream gets its normal response.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _serve(root, stdin_bytes, cwd):
    env = dict(os.environ, PYTHONPATH=str(REPO), PYTHONIOENCODING="ascii")
    return subprocess.run(
        [sys.executable, "-m", "polis.mcp_server", "--polis-root", str(root)],
        input=stdin_bytes, capture_output=True, timeout=30, env=env, cwd=cwd)


def _make_root(tmp):
    root = Path(tmp) / "_polis"
    root.mkdir()
    (root / "CONSTITUTION.md").write_text("# The Constitution\n",
                                          encoding="utf-8")
    return root


class MCPStdioEncodingTest(unittest.TestCase):
    def test_non_ascii_stdin_under_ascii_locale_gets_a_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            request = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "tést-客户端", "version": "0"}}}
            stdin = json.dumps(request, ensure_ascii=False) + "\n"
            proc = _serve(root, stdin.encode("utf-8"), tmp)
        stderr = proc.stderr.decode("utf-8", "replace")
        self.assertEqual(proc.returncode, 0, stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertNotIn("UnicodeDecodeError", stderr)
        responses = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
        self.assertTrue(responses, "server produced no response")
        by_id = {r.get("id"): r for r in responses}
        # Valid UTF-8, so a real result — not an error response.
        self.assertIn(1, by_id)
        self.assertIn("result", by_id[1])

    def test_malformed_utf8_gets_minus_32700_and_server_survives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(tmp)
            follow_up = {"jsonrpc": "2.0", "id": 2, "method": "initialize",
                         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "ok", "version": "0"}}}
            # \xff\xfe is invalid UTF-8 — and it sits inside a JSON string
            # value, so errors="replace" would parse it "successfully" after
            # silently rewriting the client's data.
            malformed = (b'{"jsonrpc": "2.0", "id": 1, "method": "initialize",'
                         b' "params": {"name": "\xff\xfe"}}\n')
            stdin = malformed + (json.dumps(follow_up) + "\n").encode("utf-8")
            proc = _serve(root, stdin, tmp)
        stderr = proc.stderr.decode("utf-8", "replace")
        self.assertEqual(proc.returncode, 0, stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertNotIn("UnicodeDecodeError", stderr)
        responses = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
        # Reported, not repaired: a -32700 parse error with a null id.
        parse_errors = [r for r in responses
                        if (r.get("error") or {}).get("code") == -32700]
        self.assertTrue(parse_errors,
                        f"no -32700 parse-error response in {responses!r}")
        self.assertIsNone(parse_errors[0].get("id"))
        # Still alive: the follow-up request on the same stream gets its
        # normal result, not an error and not silence.
        by_id = {r.get("id"): r for r in responses}
        self.assertIn(2, by_id, f"no response to the follow-up request in {responses!r}")
        self.assertIn("result", by_id[2])


if __name__ == "__main__":
    unittest.main()
