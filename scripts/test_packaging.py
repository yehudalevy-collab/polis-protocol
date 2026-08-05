#!/usr/bin/env python3
"""Guards that bundled package data (polis/_data/) stays byte-identical to the
canonical repo-root files, so a pip / uvx / pipx install ships the same
templates and `polis init` works after install (no repo checkout required)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PAIRS = [
    ("SKILL.md", "polis/_data/SKILL.md"),
    ("templates/POLIS_CONSTITUTION.md", "polis/_data/templates/POLIS_CONSTITUTION.md"),
    ("templates/bridge_pointer.md", "polis/_data/templates/bridge_pointer.md"),
]

# scripts/init_polis.py is the standalone, dependency-free init that ships inside
# the skill bundle (a skill install has no `polis` package to import). It must stay
# byte-identical to the package's polis/initializer.py so offline founding produces
# exactly the same _polis/ as `uvx polis-protocol init`. Edit initializer.py, then
# re-copy it over scripts/init_polis.py.
INIT_SYNC = ("polis/initializer.py", "scripts/init_polis.py")

# editors/antigravity/media/polis/ is a vendored copy of the polis/ package that
# the Antigravity extension executes via media/route_contract.py (sys.path.insert
# + `from polis.routing import main`). Nothing about that consumption requires any
# file to differ from polis/ — the hardcoded __version__ there is drift, not a
# need — so there are NO exceptions: the trees must match byte-for-byte. This is
# the safety net for issue #58: it stays red until the (separately sequenced)
# generation change re-syncs the vendored tree.
VENDORED_TREE = ("polis", "editors/antigravity/media/polis")


def _tree_files(base):
    return sorted(
        str(p.relative_to(base))
        for p in base.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )


class PackagingSyncTest(unittest.TestCase):
    def test_bundled_files_exist(self):
        for _root, bundled in PAIRS:
            self.assertTrue((ROOT / bundled).exists(), f"missing bundled data: {bundled}")

    def test_bundled_data_in_sync(self):
        for root, bundled in PAIRS:
            self.assertEqual(
                (ROOT / root).read_text(encoding="utf-8"),
                (ROOT / bundled).read_text(encoding="utf-8"),
                f"{bundled} is out of sync with {root}; re-copy it into polis/_data/",
            )

    def test_initializer_resolves_to_bundled_data(self):
        from polis import initializer
        # data_path must point inside the package, not the repo root.
        self.assertTrue(str(initializer.data_path("SKILL.md")).endswith("polis/_data/SKILL.md"))
        self.assertTrue(initializer.data_path("templates").is_dir())

    def test_skill_init_in_sync_with_package(self):
        source, bundled = INIT_SYNC
        self.assertTrue((ROOT / bundled).exists(), f"missing skill-bundled init: {bundled}")
        self.assertEqual(
            (ROOT / source).read_text(encoding="utf-8"),
            (ROOT / bundled).read_text(encoding="utf-8"),
            f"{bundled} is out of sync with {source}; re-copy it "
            f"(cp {source} {bundled}) so the offline skill init matches the package.",
        )

    def test_vendored_polis_tree_matches_package(self):
        source_rel, vendored_rel = VENDORED_TREE
        source, vendored = ROOT / source_rel, ROOT / vendored_rel
        self.assertTrue(vendored.is_dir(), f"missing vendored tree: {vendored_rel}")
        source_files = _tree_files(source)
        vendored_files = _tree_files(vendored)
        problems = []
        for rel in source_files:
            if rel not in vendored_files:
                problems.append(f"MISSING  {rel} (in {source_rel}/ but not in {vendored_rel}/)")
            elif (source / rel).read_bytes() != (vendored / rel).read_bytes():
                problems.append(f"DIFFERS  {rel}")
        for rel in vendored_files:
            if rel not in source_files:
                problems.append(f"EXTRA    {rel} (only in {vendored_rel}/)")
        self.assertEqual(
            problems,
            [],
            f"{vendored_rel}/ is out of sync with {source_rel}/ (issue #58); "
            f"re-sync the vendored copy when the generation change lands:\n  "
            + "\n  ".join(problems),
        )

    def test_skill_init_is_standalone(self):
        # The skill-bundled init must not import the polis package (a skill install
        # ships no package), so founding works with stdlib only.
        text = (ROOT / INIT_SYNC[1]).read_text(encoding="utf-8")
        offenders = [
            line.strip()
            for line in text.splitlines()
            if line.lstrip().startswith(("import ", "from "))
            and "polis" in line
        ]
        self.assertEqual(offenders, [], f"skill init must be stdlib-only; found: {offenders}")


if __name__ == "__main__":
    unittest.main()
