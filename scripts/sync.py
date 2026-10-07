#!/usr/bin/env python3
"""Regenerate AGENTS.md and the Cursor rule from SKILL.md, and refresh references/.

Usage (from the skill folder):  python3 scripts/sync.py [path/to/migrate-doc]
If a docs folder is given, the four reference docs are copied from it first.
"""
import pathlib, shutil, sys

root = pathlib.Path(__file__).resolve().parent.parent
docs = ["api-v1-to-v2-migration-guide.md", "v1-to-v2-migration-analysis.md",
        "v1-api-endpoints.md", "v2-technical-inventory.md"]

if len(sys.argv) > 1:
    src = pathlib.Path(sys.argv[1]).expanduser().resolve()
    for d in docs:
        shutil.copy2(src / d, root / "references" / d)

body = (root / "SKILL.md").read_text().split("---\n", 2)[2].lstrip("\n")
note = ("> **Paths:** `references/...` below means the `references/` folder of this skill. "
        "If you installed the skill into a project as `v2-migration-skill/`, read them at "
        "`v2-migration-skill/references/...`.\n\n")
anchor = "## Reference documents (read these before changing code)"
body = body.replace(anchor, note + anchor, 1)
banner = "<!-- Generated from SKILL.md — edit SKILL.md, then regenerate (see README.md). -->\n"

(root / "AGENTS.md").write_text(banner + body)
desc = ("Use when migrating client code from ThinkAR API V1 (/api/v1, JWT + refresh, terminals, "
        "translate_v2) to API V2 (/v2, session token, devices). Rules, endpoint mapping, auth, "
        "errors and real-time protocol changes.")
rule = root / ".cursor" / "rules" / "thinkar-v2-migration.mdc"
rule.parent.mkdir(parents=True, exist_ok=True)
rule.write_text(f"---\ndescription: {desc}\nglobs:\nalwaysApply: false\n---\n" + banner + body)
print("Regenerated AGENTS.md and", rule.relative_to(root))
