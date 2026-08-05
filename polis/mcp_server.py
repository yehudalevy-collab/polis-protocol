"""`polis mcp` — the polis lifecycle as an MCP server (stdio transport).

Zero dependencies, like `polis serve`: MCP's stdio transport is newline-
delimited JSON-RPC 2.0, which the stdlib covers. Any MCP client (Claude Code,
Codex, Cursor, ...) can connect and drive the same shared application layer
the CLI and dashboard use — contracts, routing, reservations, context packets,
guardrails. Nothing here hand-edits `_polis/` files.

    claude mcp add polis -- uvx --from polis-protocol polis mcp

Tools mirror the CLI lifecycle; resources expose read-only state:

    polis://state             full JSON state (same shape as /api/state)
    polis://replay            the markdown Polis Replay
    polis://replay/redacted   the sanitized, shareable Replay
    polis://constitution      the polis CONSTITUTION.md

stdout is strictly protocol; diagnostics go to stderr.
"""
import json
import sys
from pathlib import Path

from . import __version__

# Newest first; initialize echoes the client's version when we support it.
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = (
    "Polis is the local-first control plane for coding agents: tasks are "
    "claimed contracts record owners and can record evidence, advisory file "
    "reservations flag overlapping claims, "
    "and settled work produces lessons/guardrails that improve future routing. "
    "Typical flow: polis_status -> polis_open_contract -> polis_route -> "
    "polis_claim_contract -> (work, with polis_context + polis_reserve) -> "
    "polis_settle_contract."
)


def _strlist(description):
    return {"type": "array", "items": {"type": "string"}, "description": description}


def _tool(name, description, properties=None, required=None):
    schema = {"type": "object", "properties": properties or {}}
    if required:
        schema["required"] = required
    return {"name": name, "description": description, "inputSchema": schema}


TOOLS = [
    _tool("polis_status",
          "Summarize the polis: citizens, open/settled contract counts, and the "
          "current routing leader per capability tag."),
    _tool("polis_list_contracts",
          "List contracts by state.",
          {"state": {"type": "string", "enum": ["open", "settled", "abandoned"],
                     "description": "Which contracts to list (default: open)."}}),
    _tool("polis_open_contract",
          "Open a new contract (a task with acceptance criteria and required "
          "capability tags). Matching guardrails learned from past failures are "
          "inherited as must-pass acceptance criteria automatically.",
          {"title": {"type": "string", "description": "Short imperative title."},
           "required_tags": _strlist("Capability tags the work needs, e.g. ['python', 'testing']."),
           "opened_by": {"type": "string", "description": "Citizen id opening the contract."},
           "stakes": {"type": "string", "enum": ["low", "medium", "high"]},
           "cost_ceiling": {"type": "string", "enum": ["low", "medium", "high"]},
           "acceptance": _strlist("Acceptance criteria (one per entry)."),
           "deadline": {"type": "string", "description": "Optional deadline (free-form)."}},
          required=["title", "opened_by"]),
    _tool("polis_route",
          "Recommend which citizen should take an open contract, with the full "
          "per-citizen score breakdown (history, self-rating, cost fit, "
          "availability, applied lessons) so the choice is explainable.",
          {"contract_id": {"type": "string"},
           "seed": {"type": "integer", "description": "Random seed for reproducible exploration."}},
          required=["contract_id"]),
    _tool("polis_claim_contract",
          "Claim an open contract for a citizen (sets owner, status=claimed).",
          {"contract_id": {"type": "string"},
           "citizen": {"type": "string", "description": "Citizen id taking ownership."},
           "force": {"type": "boolean", "description": "Override an existing owner."}},
          required=["contract_id", "citizen"]),
    _tool("polis_settle_contract",
          "Settle a contract with an outcome (quality 1-5, optional minutes). "
          "Settled contracts feed routing via reconciliation.",
          {"contract_id": {"type": "string"},
           "quality": {"type": "integer", "minimum": 1, "maximum": 5},
           "minutes": {"type": "integer", "description": "Actual minutes spent."},
           "by": {"type": "string", "description": "Citizen settling (defaults to the owner)."}},
          required=["contract_id", "quality"]),
    _tool("polis_abandon_contract",
          "Abandon an open contract (moved aside so it never pollutes routing stats).",
          {"contract_id": {"type": "string"},
           "reason": {"type": "string"}},
          required=["contract_id"]),
    _tool("polis_context",
          "Get the context packet for a contract: acceptance criteria, must-pass "
          "guardrails, and every lesson the team already learned about this kind "
          "of work. Read this BEFORE starting the work.",
          {"contract_id": {"type": "string"}},
          required=["contract_id"]),
    _tool("polis_reserve",
          "Reserve files/directories for a citizen so other agents can't collide. "
          "Rejects (and names the holder) if any path is already held.",
          {"citizen": {"type": "string"},
           "paths": _strlist("File or directory paths to reserve."),
           "ttl_minutes": {"type": "integer", "description": "Auto-expire after N minutes."},
           "note": {"type": "string", "description": "Why you're reserving these paths."}},
          required=["citizen", "paths"]),
    _tool("polis_release",
          "Release a citizen's file reservations (all of them, or specific paths).",
          {"citizen": {"type": "string"},
           "paths": _strlist("Paths to release (omit to release all of the citizen's reservations.)")},
          required=["citizen"]),
    _tool("polis_reservations",
          "List all active file reservations (who holds what, until when)."),
    _tool("polis_add_guardrail",
          "Record a must-pass check learned from a failure. Future contracts whose "
          "tags match inherit it as an acceptance criterion automatically.",
          {"text": {"type": "string", "description": "The must-pass check (one line)."},
           "tags": _strlist("Capability tags it applies to (empty = applies to any)."),
           "source_contract": {"type": "string", "description": "Contract id this failure came from."}},
          required=["text"]),
    _tool("polis_list_amendments",
          "List proposed and ratified amendments."),
    _tool("polis_vote_amendment",
          "Vote on a proposed amendment.",
          {"amendment_id": {"type": "string", "description": "The amendment ID to vote on (e.g., YYYY-MM-DD-slug)."},
           "citizen": {"type": "string", "description": "Citizen casting the vote."},
           "vote": {"type": "string", "enum": ["agree", "disagree", "abstain", "request_changes"],
                    "description": "Vote option."},
           "rationale": {"type": "string", "description": "Optional rationale explaining the vote."}},
          required=["amendment_id", "citizen", "vote"]),
    _tool("polis_tally_amendments",
          "Tally proposed amendments and update their status (ratified, rejected, expired).",
          {"citizen": {"type": "string", "description": "Optional citizen performing the tally (defaults to 'polis-tally')."}}),
]

RESOURCES = [
    {"uri": "polis://state", "name": "Polis state",
     "description": "Full polis state as JSON: citizens, contracts, routing stats, "
                    "lessons, guardrails, reservations.",
     "mimeType": "application/json"},
    {"uri": "polis://replay", "name": "Polis Replay",
     "description": "Markdown report of what the team did and learned.",
     "mimeType": "text/markdown"},
    {"uri": "polis://replay/redacted", "name": "Polis Replay (redacted)",
     "description": "The Replay sanitized for public sharing (anonymous citizens, "
                    "free text dropped).",
     "mimeType": "text/markdown"},
    {"uri": "polis://constitution", "name": "Constitution",
     "description": "The polis CONSTITUTION.md.",
     "mimeType": "text/markdown"},
]


class PolisMCPServer:
    """Handles parsed JSON-RPC messages; transport-agnostic for testability."""

    def __init__(self, polis_root):
        self.root = Path(polis_root)

    # ---- tool implementations (each returns a JSON-friendly dict) ----

    def _tool_status(self, args):
        from . import routing
        citizens = routing.load_citizens(self.root)
        stats = routing.load_routing_stats(self.root)
        open_dir = self.root / "contracts" / "open"
        settled_dir = self.root / "contracts" / "settled"
        return {
            "polis_root": str(self.root),
            "citizens": sorted(citizens.keys()),
            "open_contracts": len(list(open_dir.glob("*.md"))) if open_dir.exists() else 0,
            "settled_contracts": len(list(settled_dir.glob("*.md"))) if settled_dir.exists() else 0,
            "explore_rate": stats.get("explore_rate", 0.15),
            "routing_leaders": {tag: {"leader": ts.get("leader"),
                                      "confidence": ts.get("leader_confidence", 0.0)}
                                for tag, ts in (stats.get("tags") or {}).items()},
        }

    def _tool_list_contracts(self, args):
        from . import contracts
        state = args.get("state") or "open"
        return {"state": state, "contracts": contracts.list_contracts(self.root, state)}

    def _tool_open_contract(self, args):
        from . import contracts
        return contracts.open_contract(
            self.root, args["title"], args.get("required_tags") or [], args["opened_by"],
            stakes=args.get("stakes", "medium"),
            cost_ceiling=args.get("cost_ceiling", "medium"),
            acceptance=args.get("acceptance"), deadline=args.get("deadline"))

    def _tool_route(self, args):
        from . import routing
        return routing.recommend(self.root, args["contract_id"], seed=args.get("seed"))

    def _tool_claim(self, args):
        from . import contracts
        return contracts.claim_contract(self.root, args["contract_id"], args["citizen"],
                                        force=bool(args.get("force")))

    def _tool_settle(self, args):
        from . import contracts
        return contracts.settle_contract(self.root, args["contract_id"], args["quality"],
                                         minutes=args.get("minutes"), by=args.get("by"))

    def _tool_abandon(self, args):
        from . import contracts
        return contracts.abandon_contract(self.root, args["contract_id"],
                                          reason=args.get("reason"))

    def _tool_context(self, args):
        from . import context
        packet = context.build_packet(self.root, args["contract_id"])
        if not packet.get("ok"):
            return packet
        return {"ok": True, "markdown": context.format_packet(packet), "packet": packet}

    def _tool_reserve(self, args):
        from . import reservations
        return reservations.reserve(self.root, args["citizen"], args["paths"],
                                    ttl_minutes=args.get("ttl_minutes"), note=args.get("note"))

    def _tool_release(self, args):
        from . import reservations
        n = reservations.release(self.root, args["citizen"], args.get("paths") or None)
        return {"ok": True, "released": n}

    def _tool_reservations(self, args):
        from . import reservations
        return {"reservations": reservations.active_reservations(self.root)}

    def _tool_add_guardrail(self, args):
        from . import guardrails
        return guardrails.add_guardrail(self.root, args["text"], args.get("tags") or [],
                                        source_contract=args.get("source_contract"))

    def _tool_list_amendments(self, args):
        from . import amendments
        return {"amendments": amendments.list_amendments(self.root)}

    def _tool_vote_amendment(self, args):
        from . import amendments
        return amendments.vote_amendment(
            self.root, args["amendment_id"], args["citizen"], args["vote"],
            rationale=args.get("rationale"))

    def _tool_tally_amendments(self, args):
        from . import amendments
        citizen = args.get("citizen") or "polis-tally"
        results = amendments.tally_amendments(self.root, proposer_or_default_citizen=citizen)
        return {"ok": True, "results": results}

    _TOOL_HANDLERS = {
        "polis_status": _tool_status,
        "polis_list_contracts": _tool_list_contracts,
        "polis_open_contract": _tool_open_contract,
        "polis_route": _tool_route,
        "polis_claim_contract": _tool_claim,
        "polis_settle_contract": _tool_settle,
        "polis_abandon_contract": _tool_abandon,
        "polis_context": _tool_context,
        "polis_reserve": _tool_reserve,
        "polis_release": _tool_release,
        "polis_reservations": _tool_reservations,
        "polis_add_guardrail": _tool_add_guardrail,
        "polis_list_amendments": _tool_list_amendments,
        "polis_vote_amendment": _tool_vote_amendment,
        "polis_tally_amendments": _tool_tally_amendments,
    }

    # ---- resources ----

    def _read_resource(self, uri):
        from . import report as _report
        if uri == "polis://state":
            from . import serve as _serve
            return json.dumps(_serve._state(self.root), default=str, indent=2), "application/json"
        if uri == "polis://replay":
            return _report.render_markdown(_report.gather(self.root)), "text/markdown"
        if uri == "polis://replay/redacted":
            return _report.render_markdown(_report.redact(_report.gather(self.root))), "text/markdown"
        if uri == "polis://constitution":
            path = self.root / "CONSTITUTION.md"
            if not path.exists():
                return None, None
            return path.read_text(encoding="utf-8"), "text/markdown"
        return None, None

    # ---- JSON-RPC dispatch ----

    def handle(self, msg):
        """Handle one parsed message. Returns a response dict, or None for notifications."""
        msg_id = msg.get("id")
        method = msg.get("method")
        is_notification = "id" not in msg

        try:
            result = self._dispatch(method, msg.get("params") or {})
        except _RPCError as e:
            if is_notification:
                return None
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": e.code, "message": e.message}}
        except Exception as e:  # never crash the server on a bad request
            if is_notification:
                return None
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32603, "message": f"internal error: {e}"}}

        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _dispatch(self, method, params):
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            return {"protocolVersion": version,
                    "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {"name": "polis-protocol", "version": __version__},
                    "instructions": INSTRUCTIONS}
        if method in ("notifications/initialized", "notifications/cancelled"):
            return None
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "tools/call":
            return self._call_tool(params.get("name"), params.get("arguments") or {})
        if method == "resources/list":
            return {"resources": RESOURCES}
        if method == "resources/read":
            uri = params.get("uri")
            text, mime = self._read_resource(uri)
            if text is None:
                raise _RPCError(-32002, f"resource not found: {uri}")
            return {"contents": [{"uri": uri, "mimeType": mime, "text": text}]}
        raise _RPCError(-32601, f"method not found: {method}")

    def _call_tool(self, name, arguments):
        handler = self._TOOL_HANDLERS.get(name)
        if handler is None:
            raise _RPCError(-32602, f"unknown tool: {name}")
        try:
            result = handler(self, arguments)
        except KeyError as e:
            return _tool_error(f"missing required argument: {e}")
        except Exception as e:
            return _tool_error(f"{type(e).__name__}: {e}")
        if isinstance(result, dict) and result.get("ok") is False:
            return _tool_error(result.get("reason", "failed"))
        text = result if isinstance(result, str) else json.dumps(result, default=str, indent=2)
        return {"content": [{"type": "text", "text": text}], "isError": False}


class _RPCError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _tool_error(message):
    return {"content": [{"type": "text", "text": message}], "isError": True}


def serve_stdio(polis_root):
    """Run the MCP server over stdio until EOF. stdout carries protocol only."""
    server = PolisMCPServer(polis_root)
    print(f"polis mcp — serving {server.root} over stdio", file=sys.stderr)
    # MCP's stdio transport is UTF-8 by specification, so decode stdin as
    # bytes ourselves: decoding per the ambient locale crashes the loop on
    # non-UTF-8-locale clients (issue #57). Decode STRICTLY — errors="replace"
    # would rewrite bytes inside what may be a JSON string value, so the
    # server would act on data the client never sent. A malformed sequence is
    # a JSON-RPC parse error (-32700, id null — no request id is recoverable),
    # reported without ever escaping the loop. A caller may have substituted
    # a text stream without .buffer; those lines arrive already decoded.
    byte_stream = getattr(sys.stdin, "buffer", sys.stdin)
    for raw_line in byte_stream:
        try:
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            line = line.strip()
            if not line:
                continue
            msg = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            resp = {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32700, "message": "parse error"}}
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
            continue
        resp = server.handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, default=str) + "\n")
            sys.stdout.flush()


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(prog="polis mcp",
                                 description="Serve the polis lifecycle over MCP (stdio).")
    ap.add_argument("--polis-root", default=None,
                    help="Path to _polis/ (default: auto-detect from cwd)")
    args = ap.parse_args(argv)

    from .cli import _find_polis_root
    root = Path(args.polis_root).resolve() if args.polis_root else _find_polis_root()
    if not root or not root.exists():
        raise SystemExit("No _polis/ found. Run `polis init` first (or pass --polis-root).")
    serve_stdio(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
