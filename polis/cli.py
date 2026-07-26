#!/usr/bin/env python3
"""The ``polis`` command — unified entry point for the Polis control plane.

This is the v2 surface. It currently wraps the established init / route /
reconcile logic and adds a real ``status`` summary. Further lifecycle commands
(doctor, migrate, serve, contract, citizen, review, reserve, report) land in
later v2 increments — they are intentionally not advertised until implemented.
"""
import sys
from pathlib import Path

from . import __version__

USAGE = """polis {v} — local-first control plane for coding agents

usage: polis <command> [options]

commands:
  init        Scaffold or repair a _polis/ workspace and register an agent
  route       Recommend a citizen for an open contract (use --explain)
  reconcile   Rebuild routing_stats.yml from settled contracts
  contract    Manage contracts: open | list | claim | settle | abandon | context
  bench       Polis Bench (--mode routing|learning): proof, measured honestly
  serve       Local control-plane dashboard — view + open/claim/settle/reserve (http://127.0.0.1:7341)
  mcp         Serve the polis lifecycle as an MCP server (stdio) for any agent
  report      Write a shareable Polis Replay (--format md|html, --redact)
  reflect     Mine settled history for pathologies; draft evidence-backed amendments (--apply)
  amendment   Manage constitution amendments: list | vote | tally
  guardrail   Record/list must-pass checks learned from failures (add | list)
  status      Summarize the polis: citizens, open/settled contracts, routing
  doctor      Validate the polis (schema, cards, contracts, lessons)
  verify      Check capability-card content-integrity hashes (--fix to stamp)
  migrate     Upgrade the polis schema (--plan / --apply / --rollback)
  reserve     Reserve files so other agents don't collide (--as <citizen>)
  release     Release your file reservations (--as <citizen>)
  reservations  List active file reservations
  version     Print the polis version

Run `polis <command> --help` for command-specific options.
""".format(v=__version__)


def _find_polis_root(start=None):
    """Walk up from `start` (default cwd) looking for a _polis/ workspace."""
    p = Path(start or ".").resolve()
    for cand in [p, *p.parents]:
        if (cand / "_polis" / "CONSTITUTION.md").exists():
            return cand / "_polis"
    if p.name == "_polis" and (p / "CONSTITUTION.md").exists():
        return p
    return None


def cmd_status(argv):
    import argparse
    import json

    ap = argparse.ArgumentParser(prog="polis status")
    ap.add_argument("--polis-root", default=None,
                    help="Path to _polis/ (default: auto-detect from cwd)")
    ap.add_argument("--json", action="store_true",
                    help="Print status as deterministic JSON")
    args = ap.parse_args(argv)

    from . import routing

    root = Path(args.polis_root).resolve() if args.polis_root else _find_polis_root()
    if not root or not root.exists():
        raise SystemExit("No _polis/ found. Run `polis init` first (or pass --polis-root).")

    citizens = routing.load_citizens(root)
    stats = routing.load_routing_stats(root)
    open_dir = root / "contracts" / "open"
    settled_dir = root / "contracts" / "settled"
    n_open = len(list(open_dir.glob("*.md"))) if open_dir.exists() else 0
    n_settled = len(list(settled_dir.glob("*.md"))) if settled_dir.exists() else 0
    tags = stats.get("tags", {})

    if args.json:
        payload = {
            "polis_root": str(root),
            "citizens": sorted(citizens),
            "open_contracts": n_open,
            "settled_contracts": n_settled,
            "explore_rate": stats.get("explore_rate", 0.15),
            "routing_by_tag": {
                tag: {
                    "leader": ts.get("leader"),
                    "leader_confidence": ts.get("leader_confidence", 0.0),
                }
                for tag, ts in sorted(tags.items())
            },
        }
        print(json.dumps(payload, sort_keys=True))
        return 0

    print(f"polis: {root}")
    print(f"  citizens          : {len(citizens)}")
    for cid in citizens:
        print(f"      - {cid}")
    print(f"  open contracts    : {n_open}")
    print(f"  settled contracts : {n_settled}")
    print(f"  explore_rate      : {stats.get('explore_rate', 0.15)}")
    if tags:
        print("  routing by tag (leader / confidence):")
        for tag, ts in sorted(tags.items()):
            leader = ts.get("leader", "—")
            conf = ts.get("leader_confidence", 0.0)
            try:
                conf_s = f"{float(conf):.2f}"
            except (TypeError, ValueError):
                conf_s = str(conf)
            print(f"      {tag:22s} {leader}  (conf {conf_s})")
    return 0


def cmd_doctor(argv):
    import argparse

    ap = argparse.ArgumentParser(prog="polis doctor")
    ap.add_argument("--polis-root", default=None,
                    help="Path to _polis/ (default: auto-detect from cwd)")
    ap.add_argument("--write-config", action="store_true",
                    help="Create/update _polis/polis.yml from defaults, then validate")
    args = ap.parse_args(argv)

    root = Path(args.polis_root).resolve() if args.polis_root else _find_polis_root()
    if not root or not root.exists():
        raise SystemExit("No _polis/ found. Run `polis init` first (or pass --polis-root).")

    from . import doctor, config as _config

    if args.write_config:
        existing = _config.load_config(root) if _config.has_config(root) else None
        path = _config.write_config(root, existing)
        print(f"wrote {path}")

    result = doctor.run_doctor(root)
    for item in result["info"]:
        print(f"  info : {item}")
    for warning in result["warnings"]:
        print(f"  warn : {warning}")
    for error in result["errors"]:
        print(f"  ERROR: {error}")

    if result["ok"]:
        suffix = f" ({len(result['warnings'])} warning(s))" if result["warnings"] else ""
        print(f"\npolis doctor: OK{suffix}")
        return 0
    print(f"\npolis doctor: {len(result['errors'])} error(s)")
    return 1


def cmd_verify(argv):
    import argparse

    ap = argparse.ArgumentParser(prog="polis verify")
    ap.add_argument("--polis-root", default=None,
                    help="Path to _polis/ (default: auto-detect from cwd)")
    ap.add_argument("--fix", action="store_true",
                    help="(Re)stamp every capability card with a fresh content_hash")
    args = ap.parse_args(argv)

    root = Path(args.polis_root).resolve() if args.polis_root else _find_polis_root()
    if not root or not root.exists():
        raise SystemExit("No _polis/ found. Run `polis init` first (or pass --polis-root).")

    import yaml  # noqa: F401  (cards are YAML; integrity needs it)
    from . import integrity

    citizens_dir = root / "citizens"
    cards = sorted(citizens_dir.glob("*/capability_card.yml")) if citizens_dir.exists() else []
    if not cards:
        print("No capability cards found.")
        return 0

    bad = 0
    for card_path in cards:
        cid = card_path.parent.name
        if args.fix:
            integrity.stamp_card_file(card_path)
            print(f"  stamped: {cid}")
            continue
        try:
            card = yaml.safe_load(card_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            print(f"  ERROR  {cid}: cannot parse card ({e})")
            bad += 1
            continue
        res = integrity.verify_card(card)
        state = res["state"]
        if state == "ok":
            print(f"  ok     {cid}")
        elif state == "mismatch":
            print(f"  CHANGED {cid}: content_hash does not match — card edited since stamped")
            bad += 1
        elif state == "legacy":
            print(f"  legacy {cid}: old signature field — run `polis verify --fix` to migrate")
        else:
            print(f"  unstamped {cid}: run `polis verify --fix` to add a content_hash")

    if args.fix:
        print(f"\nStamped {len(cards)} card(s).")
        return 0
    if bad:
        print(f"\npolis verify: {bad} card(s) failed integrity check")
        return 1
    print(f"\npolis verify: {len(cards)} card(s) checked")
    return 0


def cmd_migrate(argv):
    import argparse

    ap = argparse.ArgumentParser(prog="polis migrate")
    ap.add_argument("--polis-root", default=None,
                    help="Path to _polis/ (default: auto-detect from cwd)")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--plan", action="store_true", help="Show what would change (default)")
    group.add_argument("--apply", action="store_true", help="Apply the migration (snapshots a backup first)")
    group.add_argument("--rollback", action="store_true", help="Restore from the most recent backup")
    args = ap.parse_args(argv)

    root = Path(args.polis_root).resolve() if args.polis_root else _find_polis_root()
    if not root or not root.exists():
        raise SystemExit("No _polis/ found. Run `polis init` first (or pass --polis-root).")

    from . import migrate

    if args.rollback:
        res = migrate.rollback(root)
        if res.get("error"):
            print(f"polis migrate: {res['error']}")
            return 1
        for item in res["restored"]:
            print(f"  restored: {item}")
        print(f"\nRolled back from {res['backup']} ({len(res['restored'])} change(s)).")
        return 0

    actions = migrate.plan_migration(root)
    if not actions:
        print("polis migrate: already up to date (schema v2).")
        return 0

    if args.apply:
        res = migrate.apply_migration(root, actions)
        for action in res["applied"]:
            print(f"  {action['action']}: {action['detail']}")
        print(f"\nApplied {len(res['applied'])} change(s). Backup: {res['backup']}")
        print("Undo with: polis migrate --rollback")
        return 0

    print("Planned migration (dry run — re-run with --apply):")
    for action in actions:
        print(f"  {action['action']}: {action['detail']}")
    return 0


def cmd_serve(argv):
    import argparse

    ap = argparse.ArgumentParser(prog="polis serve")
    ap.add_argument("--port", type=int, default=7341)
    ap.add_argument("--polis-root", default=None)
    a = ap.parse_args(argv)
    root = _resolve_root(a.polis_root)
    from . import serve as _serve
    _serve.serve(root, port=a.port)
    return 0


def cmd_report(argv):
    import argparse

    ap = argparse.ArgumentParser(prog="polis report")
    ap.add_argument("--format", choices=["md", "html"], default="md")
    ap.add_argument("--redact", action="store_true", help="Anonymize citizens and drop free text for sharing")
    ap.add_argument("--out", default=None)
    ap.add_argument("--polis-root", default=None)
    a = ap.parse_args(argv)
    root = _resolve_root(a.polis_root)
    from . import report as _report
    path = _report.write_report(root, fmt=a.format, redacted=a.redact, out_path=a.out)
    print(f"wrote {path}")
    return 0


def cmd_reflect(argv):
    import argparse

    ap = argparse.ArgumentParser(prog="polis reflect")
    ap.add_argument("--apply", action="store_true",
                    help="Write proposed amendments to amendments/proposed/ (default: preview only)")
    ap.add_argument("--min-evidence", type=int, default=None,
                    help="Settled contracts needed before a pattern counts as recurring (default 3)")
    ap.add_argument("--polis-root", default=None)
    a = ap.parse_args(argv)
    root = _resolve_root(a.polis_root)
    from . import reflect as _reflect
    kwargs = {"apply": a.apply}
    if a.min_evidence is not None:
        kwargs["min_evidence"] = a.min_evidence
    results = _reflect.reflect(root, **kwargs)
    if not results:
        print("No process pathologies found — nothing to propose.")
        return 0
    verb = "Proposed" if a.apply else "Would propose"
    for r in results:
        if a.apply and r["already_proposed"]:
            print(f"  · already on file: {r['amendment_id']} ({r['kind']})")
            continue
        mark = "+" if (a.apply and r["written"]) else "?"
        print(f"  {mark} {verb}: {r['title']}")
        print(f"      kind={r['kind']}  evidence={', '.join(r['evidence_contracts'])}")
    if not a.apply:
        print("\nRe-run with --apply to file these for the citizens to vote on.")
    return 0


def cmd_guardrail(argv):
    import argparse

    sub = argv[0] if argv else ""
    rest = argv[1:]
    from . import guardrails

    if sub == "add":
        ap = argparse.ArgumentParser(prog="polis guardrail add")
        ap.add_argument("--text", required=True, help="The must-pass check (one line)")
        ap.add_argument("--tags", default="", help="comma-separated capability tags it applies to")
        ap.add_argument("--from", dest="source", default=None, help="contract id this failure came from")
        ap.add_argument("--polis-root", default=None)
        a = ap.parse_args(rest)
        root = _resolve_root(a.polis_root)
        tags = [t.strip() for t in a.tags.split(",") if t.strip()]
        res = guardrails.add_guardrail(root, a.text, tags, source_contract=a.source)
        print(f"Added guardrail {res['guardrail_id']} (applies to: {', '.join(tags) or 'any'})")
        return 0

    if sub == "list":
        ap = argparse.ArgumentParser(prog="polis guardrail list")
        ap.add_argument("--polis-root", default=None)
        a = ap.parse_args(rest)
        root = _resolve_root(a.polis_root)
        gs = guardrails.list_guardrails(root)
        if not gs:
            print("No guardrails yet.")
            return 0
        for g in gs:
            print(f"  ⚠️ {g['text']}  [{', '.join(g['tags'])}]")
        return 0

    print("usage: polis guardrail <add|list> [...]")
    return 2


def cmd_bench(argv):
    import argparse

    ap = argparse.ArgumentParser(prog="polis bench")
    ap.add_argument("--mode", choices=["routing", "learning"], default="routing",
                    help="routing: learned vs baseline routing; learning: repeat-error over time")
    ap.add_argument("--contracts", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--citizens", type=int, default=4)
    ap.add_argument("--tags", type=int, default=5)
    ap.add_argument("--csv", default=None, help="Write per-contract learning curves to this CSV")
    args = ap.parse_args(argv)

    from . import bench
    if args.mode == "learning":
        result = bench.run_learning_benchmark(n_contracts=args.contracts, seed=args.seed)
        print(bench.format_learning_report(result))
        return 0
    result = bench.run_benchmark(n_contracts=args.contracts, n_citizens=args.citizens,
                                 n_tags=args.tags, seed=args.seed)
    print(bench.format_report(result))
    if args.csv:
        print(f"\nwrote learning curves: {bench.write_csv(result, args.csv)}")
    return 0


def _resolve_root(value):
    root = Path(value).resolve() if value else _find_polis_root()
    if not root or not root.exists():
        raise SystemExit("No _polis/ found. Run `polis init` first (or pass --polis-root).")
    return root


def cmd_contract(argv):
    import argparse

    sub = argv[0] if argv else ""
    rest = argv[1:]
    from . import contracts

    if sub == "list":
        ap = argparse.ArgumentParser(prog="polis contract list")
        ap.add_argument("--state", default="open", choices=["open", "settled", "abandoned"])
        ap.add_argument("--polis-root", default=None)
        a = ap.parse_args(rest)
        root = _resolve_root(a.polis_root)
        rows = contracts.list_contracts(root, a.state)
        if not rows:
            print(f"No {a.state} contracts.")
            return 0
        for r in rows:
            owner = r["owner"] or "—"
            print(f"  {r['contract_id']:32s} [{r['status']:9s}] owner={owner}  {r['title']}")
        return 0

    if sub == "open":
        ap = argparse.ArgumentParser(prog="polis contract open")
        ap.add_argument("--title", required=True)
        ap.add_argument("--tags", default="", help="comma-separated required_tags")
        ap.add_argument("--by", required=True, help="opened_by citizen")
        ap.add_argument("--stakes", default="medium", choices=["low", "medium", "high"])
        ap.add_argument("--cost-ceiling", default="medium", choices=["low", "medium", "high"])
        ap.add_argument("--deadline", default=None)
        ap.add_argument("--polis-root", default=None)
        a = ap.parse_args(rest)
        root = _resolve_root(a.polis_root)
        tags = [t.strip() for t in a.tags.split(",") if t.strip()]
        res = contracts.open_contract(root, a.title, tags, a.by, stakes=a.stakes,
                                      cost_ceiling=a.cost_ceiling, deadline=a.deadline)
        print(f"Opened contract {res['contract_id']} -> {res['path']}")
        return 0

    if sub in ("claim", "settle", "abandon"):
        ap = argparse.ArgumentParser(prog=f"polis contract {sub}")
        ap.add_argument("contract_id")
        ap.add_argument("--polis-root", default=None)
        if sub == "claim":
            ap.add_argument("--as", dest="citizen", required=True)
            ap.add_argument("--force", action="store_true")
        if sub == "settle":
            ap.add_argument("--quality", type=int, required=True, help="quality score 1-5")
            ap.add_argument("--minutes", type=int, default=None)
            ap.add_argument("--by", default=None)
        if sub == "abandon":
            ap.add_argument("--reason", default=None)
        a = ap.parse_args(rest)
        root = _resolve_root(a.polis_root)
        if sub == "claim":
            res = contracts.claim_contract(root, a.contract_id, a.citizen, force=a.force)
        elif sub == "settle":
            res = contracts.settle_contract(root, a.contract_id, a.quality, minutes=a.minutes, by=a.by)
        else:
            res = contracts.abandon_contract(root, a.contract_id, reason=a.reason)
        if not res["ok"]:
            print(f"{sub} failed: {res['reason']}")
            return 1
        print(f"{sub}: {a.contract_id} ok")
        return 0

    if sub == "context":
        ap = argparse.ArgumentParser(prog="polis contract context")
        ap.add_argument("contract_id")
        ap.add_argument("--polis-root", default=None)
        a = ap.parse_args(rest)
        root = _resolve_root(a.polis_root)
        from . import context
        print(context.format_packet(context.build_packet(root, a.contract_id)))
        return 0

    print("usage: polis contract <open|list|claim|settle|abandon|context> [...]")
    return 2


def cmd_reserve(argv):
    import argparse

    ap = argparse.ArgumentParser(prog="polis reserve")
    ap.add_argument("paths", nargs="+", help="File or directory paths to reserve")
    ap.add_argument("--as", dest="citizen", required=True, help="Citizen making the reservation")
    ap.add_argument("--ttl-min", type=int, default=None, help="Auto-expire after N minutes")
    ap.add_argument("--note", default=None, help="Why you're reserving these paths")
    ap.add_argument("--polis-root", default=None)
    args = ap.parse_args(argv)

    root = Path(args.polis_root).resolve() if args.polis_root else _find_polis_root()
    if not root or not root.exists():
        raise SystemExit("No _polis/ found. Run `polis init` first (or pass --polis-root).")

    from . import reservations
    res = reservations.reserve(root, args.citizen, args.paths, ttl_minutes=args.ttl_min, note=args.note)
    if not res["ok"]:
        print("Reservation REJECTED — these paths are held by other citizens:")
        for c in res["conflicts"]:
            print(f"  {c['path']}  ← held by {c['holder']} (as {c['held_path']})")
        return 1
    ttl = f", expires in {args.ttl_min}m" if args.ttl_min else ""
    print(f"Reserved {len(res['reservation']['paths'])} path(s) for {args.citizen}{ttl}.")
    return 0


def cmd_release(argv):
    import argparse

    ap = argparse.ArgumentParser(prog="polis release")
    ap.add_argument("paths", nargs="*", help="Paths to release (default: all of yours)")
    ap.add_argument("--as", dest="citizen", required=True, help="Citizen releasing the reservation")
    ap.add_argument("--polis-root", default=None)
    args = ap.parse_args(argv)

    root = Path(args.polis_root).resolve() if args.polis_root else _find_polis_root()
    if not root or not root.exists():
        raise SystemExit("No _polis/ found. Run `polis init` first (or pass --polis-root).")

    from . import reservations
    n = reservations.release(root, args.citizen, args.paths or None)
    print(f"Released {n} reservation(s) for {args.citizen}.")
    return 0


def cmd_reservations(argv):
    import argparse

    ap = argparse.ArgumentParser(prog="polis reservations")
    ap.add_argument("--polis-root", default=None)
    args = ap.parse_args(argv)

    root = Path(args.polis_root).resolve() if args.polis_root else _find_polis_root()
    if not root or not root.exists():
        raise SystemExit("No _polis/ found. Run `polis init` first (or pass --polis-root).")

    from . import reservations
    active = reservations.active_reservations(root)
    if not active:
        print("No active reservations.")
        return 0
    print("Active reservations:")
    for res in active:
        exp = res.get("expires_at") or "no expiry"
        note = f"  — {res['note']}" if res.get("note") else ""
        print(f"  {res.get('citizen')}: {', '.join(res.get('paths', []))}  (expires: {exp}){note}")
    return 0


def cmd_amendment(argv):
    import argparse

    sub = argv[0] if argv else ""
    rest = argv[1:]
    from . import amendments

    if sub == "list":
        ap = argparse.ArgumentParser(prog="polis amendment list")
        ap.add_argument("--polis-root", default=None)
        a = ap.parse_args(rest)
        root = _resolve_root(a.polis_root)
        rows = amendments.list_amendments(root)
        if not rows:
            print("No proposed or ratified amendments.")
            return 0
        for r in rows:
            votes = r.get("votes", {})
            agrees = len(votes.get("agree", []))
            disagrees = len(votes.get("disagree", []))
            req_changes = len(votes.get("request_changes", []))
            print(f"  {r['amendment_id']:32s} [{r['status']:9s}] votes: agree={agrees} disagree={disagrees} request_changes={req_changes}  {r['title']}")
        return 0

    if sub == "vote":
        ap = argparse.ArgumentParser(prog="polis amendment vote")
        ap.add_argument("amendment_id")
        ap.add_argument("--as", dest="citizen", required=True, help="Citizen casting the vote")
        ap.add_argument("--vote", required=True, choices=["agree", "disagree", "abstain", "request_changes"])
        ap.add_argument("--rationale", default=None, help="Explanation for the vote")
        ap.add_argument("--polis-root", default=None)
        a = ap.parse_args(rest)
        root = _resolve_root(a.polis_root)
        try:
            res = amendments.vote_amendment(root, a.amendment_id, a.citizen, a.vote, rationale=a.rationale)
            print(f"Vote cast successfully: {a.citizen} voted {a.vote} on {a.amendment_id}.")
            return 0
        except ValueError as e:
            print(f"Vote failed: {e}")
            return 1

    if sub == "tally":
        ap = argparse.ArgumentParser(prog="polis amendment tally")
        ap.add_argument("--as", dest="citizen", default="polis-tally", help="Author of the chronicle entry")
        ap.add_argument("--polis-root", default=None)
        a = ap.parse_args(rest)
        root = _resolve_root(a.polis_root)
        results = amendments.tally_amendments(root, proposer_or_default_citizen=a.citizen)
        if not results:
            print("No amendments tallied.")
            return 0
        for r in results:
            print(f"  [{r['action'].upper()}] {r['amendment_id']}: {r['detail']}")
            if r['action'] == "ratified":
                print(f"      [IMPORTANT] Please manually incorporate the amendment into CONSTITUTION.md!")
        return 0

    print("usage: polis amendment <list|vote|tally> [...]")
    return 2


def _delegate(module_name, argv, prepend=None):
    """Run a legacy module's main() by reconstructing sys.argv."""
    from . import routing, initializer  # noqa: F401

    mod = {"routing": routing, "initializer": initializer}[module_name]
    saved = sys.argv
    try:
        sys.argv = ["polis", *(prepend or []), *argv]
        return mod.main()
    finally:
        sys.argv = saved


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0

    cmd, rest = argv[0], argv[1:]
    if cmd in ("version", "-V", "--version"):
        print(f"polis {__version__}")
        return 0
    if cmd == "init":
        return _delegate("initializer", rest)
    if cmd == "route":
        return _delegate("routing", rest)
    if cmd == "reconcile":
        return _delegate("routing", rest, prepend=["--reconcile"])
    if cmd == "status":
        return cmd_status(rest)
    if cmd == "contract":
        return cmd_contract(rest)
    if cmd == "bench":
        return cmd_bench(rest)
    if cmd == "guardrail":
        return cmd_guardrail(rest)
    if cmd == "serve":
        return cmd_serve(rest)
    if cmd == "mcp":
        from . import mcp_server
        return mcp_server.main(rest)
    if cmd == "report":
        return cmd_report(rest)
    if cmd == "reflect":
        return cmd_reflect(rest)
    if cmd == "amendment":
        return cmd_amendment(rest)
    if cmd == "doctor":
        return cmd_doctor(rest)
    if cmd == "verify":
        return cmd_verify(rest)
    if cmd == "migrate":
        return cmd_migrate(rest)
    if cmd == "reserve":
        return cmd_reserve(rest)
    if cmd == "release":
        return cmd_release(rest)
    if cmd == "reservations":
        return cmd_reservations(rest)

    print(f"Unknown command: {cmd}\n")
    print(USAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
