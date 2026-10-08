# ThinkAR API V1 → V2 Migration Skill

Rules and reference material for AI coding agents that migrate a client app (iOS, Android, web or API client) from ThinkAR API V1 to API V2.

The same instructions ship in three formats, so every agent reads the same rules:

| File | Read by |
|---|---|
| `SKILL.md` | Claude Code (Agent Skills format). **Source of truth** |
| `AGENTS.md` | OpenAI Codex, and any agent that follows the `AGENTS.md` convention (e.g. Gemini CLI, Aider, Copilot agents, Windsurf) |
| `.cursor/rules/thinkar-v2-migration.mdc` | Cursor |
| `references/*.md` | All of them: the full migration guide, analysis, V1 inventory, V2 inventory |

## Install

### Claude Code
Copy the folder into a skills directory:
```bash
# for one project
mkdir -p <project>/.claude/skills && cp -R v2-migration-skill <project>/.claude/skills/thinkar-api-v1-to-v2-migration
# or for every project
mkdir -p ~/.claude/skills && cp -R v2-migration-skill ~/.claude/skills/thinkar-api-v1-to-v2-migration
```
Claude loads the skill automatically when the task matches. You can also ask: "use the thinkar-api-v1-to-v2-migration skill".

### Codex (and other AGENTS.md agents)
```bash
cp -R v2-migration-skill <project>/v2-migration-skill
```
- If the project has **no** `AGENTS.md`, copy it to the root: `cp <project>/v2-migration-skill/AGENTS.md <project>/AGENTS.md`.
- If the project **already has** an `AGENTS.md`, add this line to it:
  `For the ThinkAR API V1 → V2 migration, follow v2-migration-skill/AGENTS.md.`

### Cursor
```bash
cp -R v2-migration-skill <project>/v2-migration-skill
mkdir -p <project>/.cursor/rules && cp <project>/v2-migration-skill/.cursor/rules/thinkar-v2-migration.mdc <project>/.cursor/rules/
```
- The rule is "agent requested" (`alwaysApply: false`): Cursor attaches it when the task mentions the migration.
- To force it, mention `@thinkar-v2-migration` in chat, or set `alwaysApply: true`.

### Any other model or tool
Paste or attach `AGENTS.md` (plain Markdown, no tool-specific syntax) and the `references/` folder.

## Updating
1. Edit the docs in `migrate-doc/md files/`, and `SKILL.md` here if the rules change.
2. Run:
   ```bash
   python3 scripts/sync.py "../md files"   # copies the 5 docs into references/ and regenerates AGENTS.md + the Cursor rule
   ```
3. Never edit `AGENTS.md` or the `.mdc` file by hand. They are generated.

## What the skill makes the agent do
1. Find every V1 touchpoint (search patterns are included).
2. Map each one using the verified endpoint matrix. Unmapped items are never invented.
3. Migrate in a fixed order: configuration → auth → error parser → user → devices → firmware → app update → live agent → live translation.
4. Leave `TODO(v2-migration)` for the open items (SKILL.md §7.1), instead of guessing, and apply the answers for the resolved items (§7.2).
5. Build, lint and test, then finish with a standard migration report.
