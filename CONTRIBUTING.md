# Contributing to Polis Protocol

Welcome. Polis is small, opinionated, and meant to stay readable end-to-end. That shapes what kinds of contributions are most useful.

## What we want

- **Bug reports** with a minimal reproducible polis (a tarball or a few-file gist is plenty).
- **Protocol amendments.** If you've actually used Polis on a real project and a rule didn't fit, that's the most valuable kind of feedback. File it as an issue tagged `amendment-proposal` and describe: the situation, the rule that failed, your suggested change, and the consequences.
- **Cross-tool bridge improvements.** New entry pointers (e.g., for Aider, opencode, Zed, Devin) are welcome — keep them under 30 lines and pointing at `_polis/CONSTITUTION.md`.
- **Reference docs and examples.** A worked polis under `examples/` showing a real team setup teaches faster than abstract docs.
- **Routing-policy variants.** If you have a better bandit (UCB, Thompson sampling, contextual) wire it up as a *separate* router script and benchmark it in the PR description.

## What we will probably push back on

- **New required fields in the constitution** without a worked-example PR showing why the old shape failed.
- **Vendor-specific features** that other vendors can't implement. Polis is vendor-agnostic by design.
- **Replacing the markdown-only invariant** with a database, a service, or anything that requires runtime infra. The whole point is that any tool that reads markdown can participate.

## How to propose a change

1. **Open an issue first** for anything more than a typo. A 3-sentence "is this a fit?" thread saves you from writing a PR that gets bounced.
2. **One change per PR.** Easier to review, easier to revert.
3. **Touch tests if you touch parsers.** `python3 scripts/test_reconcile_parsing.py` runs in under a second.
4. **Update the spec.** If your PR changes a file format, edit `references/protocol-spec.md` in the same PR. If it changes a rule, edit `templates/POLIS_CONSTITUTION.md` too.

## Running Locally

During development, you can run the CLI directly from the repository root:
- Primary method (if the package is installed in editable mode): `polis`
- Module fallback: `python -m polis` (useful for troubleshooting or without installing)
- Exact entrypoint fallback: `python -m polis.cli`

## Running the tests

One command runs every Python regression suite, the same way CI does:

```
python3 scripts/run_tests.py
```

It discovers `scripts/test_*.py` from the filesystem, runs each in its own
process, and prints a per-suite PASS/FAIL summary; it exits non-zero if any
suite fails. **Adding a new `scripts/test_*.py` needs no workflow edit** — it is
picked up automatically, so a new test can't quietly go un-run. (The Node
editor test stays separate: `node editors/antigravity/test_state.js`.)

## Style

- **Python**: stdlib first. `route_contract.py` is the only file that needs `PyYAML`. Keep it that way unless there's a compelling reason.
- **Markdown**: the templates are deliberately rigid. Match the existing line shapes, especially the chronicle line format (`- YYYY-MM-DD HH:MM | <agent-id> | <verb-phrase> | [[<wikilink>]] | <note>`).
- **Prose**: write for someone who's read the README once and is now deciding whether to actually use this. Concrete examples beat abstract claims.

## Code of conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). The TL;DR: this is a small project; act like a citizen.

## Security

See [SECURITY.md](SECURITY.md). Report vulnerabilities privately first.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
