# Contributing to skills-harness

This kit is file-only with no runtime, so contributions are documentation and template changes. Here's how to work on each area.

## Changing the Rules block

The canonical Rules text lives in **`.skills/_harness/_rules.md`**. All templates reference this same set of rules, but each template embeds its own copy (so templates remain self-contained for copy-paste workflows).

When you change `_rules.md`:

1. Edit `.skills/_harness/_rules.md` with the new wording (canonical heading is `# Rules`; templates use `## Rules` plus the same bullet list).
2. Run `.skills/_harness/sync.sh --write` to propagate the updated rules into every `*_template.md`.
3. Run `.skills/_harness/check.sh` to verify all templates match the canonical source (works with macOS `/bin/bash` 3.2 and newer).

## Adding a new environment template

When a new tool gains a standard project-local config file:

1. Create `.skills/_harness/TOOLNAME_template.md` with the standard SETUP + harness body structure. Use an existing template as reference.
2. Copy the Rules block from `.skills/_harness/_rules.md` into the new template's `## Rules` section.
3. Add a row to the bootstrap table in `AGENTS_skills.md`.
4. Add a row to the **Supported tools** table in `README.md`.
5. If the tool uses special markup (like Cursor's YAML frontmatter), isolate it in that template — do not fork the Rules text.
6. Run `.skills/_harness/check.sh` to validate.

## Adding or editing a skill

Follow the bundled **skill-author** skill (`.skills/_skills/skill-author/SKILL.md`). In short:

> **Kit skills are unprefixed.** Skills added to this repo (`skills-harness`) ship as part of the kit and use bare names like `skill-author`, `harness-upgrade`. The naming-prefix convention in `skill-author` applies to **consumer repos** that install the kit — they prefix new skills with their repo initials (e.g. `uxpm-`, `gm-`). Do not add a prefix when authoring kit skills here.

1. Create `.skills/_skills/<name>/SKILL.md` using `skill-template` as a starting point.
2. Fill in YAML frontmatter (`name`, `description`, `triggers`, `dependencies`, `version`).
3. Run `.skills/_harness/build-index.sh --write` to regenerate `.skills/_index.md` from frontmatter.
4. If native discovery symlinks are set up, re-run `.skills/_harness/link.sh <target>` to include the new skill.
5. Run `.skills/_harness/check.sh` to verify index-to-directory consistency.

## Testing

There is no automated CI. Use the validation script and manual smoke testing:

- **`check.sh`** — run `.skills/_harness/check.sh` from the repo root. It checks:
  - Every index row has a matching skill directory (and vice versa)
  - Every `SKILL.md` has required frontmatter fields
  - Frontmatter `name` matches directory name
  - Rules blocks in all templates match `_rules.md`
  - When `.agents/skills/` or `.claude/skills/` exist, every harness skill in `_skills/` has a correct symlink there (and dangling extras are reported)
  - Use **`check.sh --link`** or **`SKILLS_AUTO_LINK=1`** to run `link.sh` on existing native dirs before validating (idempotent repair after new kit skills or subtree pull)

- **Manual smoke test** (before a release):
  1. Create a fresh temp directory; copy `AGENTS_skills.md` and `.skills/` into it.
  2. For at least one AGENTS-based and one sidecar template: follow SETUP; confirm destination file has no SETUP block and contains the harness.
  3. Verify the agent reads `.skills/_index.md` without preloading every `SKILL.md`.
  4. Verify the agent can follow `skill-author` to add a trivial skill.

## Versioning

- **Kit release (semver for the whole kit)** — follow the bundled **kit-release** skill (`.skills/_skills/kit-release/SKILL.md`). In one change set, update:
  - **`CHANGELOG.md`** — new `## [x.y.z] - date` section at the top of the release list
  - **`.skills/_meta.yml`** — `kit_version`
  - **`README.md`** — **Kit version** → **Current release:** `` `x.y.z` ``
  - **`AGENTS_skills.md`** — **Kit version:** `` `x.y.z` `` on the line under the main heading
  - Then run **`.skills/_harness/check.sh`** — it asserts those values match each other and the newest changelog heading.
- **Per-skill version** in each `SKILL.md` frontmatter — bump when that skill’s behaviour changes; mention significant skill bumps in the kit changelog when you cut a release.
- **`CHANGELOG.md`** — [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) for every kit release.

## Style guidelines

- Templates use **append with `## Skills Harness` heading** as the standard merge strategy.
- SETUP blocks are ephemeral; harness content is permanent. Keep them clearly separated with `<!-- SETUP -->` / `<!-- END SETUP -->` comments.
- Skills use kebab-case directory names, one-sentence descriptions, and phrase-based triggers.

## Frontmatter compatibility

All `SKILL.md` files must include `name` and `description` in YAML frontmatter per the [agentskills.io specification](https://agentskills.io/specification). These fields enable native IDE discovery across Cursor, Windsurf, Cline, Codex, Copilot, Claude Code, Gemini CLI, Roo Code, and OpenCode.

Harness-specific fields (`triggers`, `dependencies`, `version`) are recommended and used by the harness index. IDEs that don't recognize them silently ignore them.

| Field | Required by | Purpose |
|-------|-------------|---------|
| `name` | agentskills.io + harness | Must match directory name (kebab-case, 1–64 chars) |
| `description` | agentskills.io + harness | 1–1024 chars; used for native IDE matching and the index |
| `triggers` | harness only | Phrases that cause the harness to load the skill |
| `dependencies` | harness only | Other skills to load first |
| `version` | harness only | Semver for humans |

## Environment overrides

Both `check.sh` and `link.sh` derive paths from their own location. If your repo has a non-standard layout (monorepo, submodule, `tools/.skills/`), override with environment variables:

| Variable | Used by | Default |
|----------|---------|---------|
| `SKILLS_HARNESS_DIR` | check, link | directory containing the script |
| `SKILLS_DIR` | check, link | `../_skills` relative to harness |
| `SKILLS_REPO_ROOT` | check, link | two levels above harness |
| `SKILLS_INDEX` | check | `../_index.md` relative to harness |
| `SKILLS_RULES` | check | `_rules.md` in harness dir |
| `SKILLS_CHECK_KIT_SURFACES` | check | auto: `0` if `.skills-harness/` exists at repo root or `_meta.yml` has `role: consumer`; otherwise `1`. Set explicitly to override. |
| `SKILLS_AUTO_LINK` | check | `0` (default). Set to `1` to run `link.sh` on existing `.agents/skills/` and `.claude/skills/` before validating (same as `--link`). |

`check.sh` also accepts `--quiet` (suppress success footer) and `--link` (sync native discovery symlinks when those directories already exist).

## Symlink helper (`link.sh`)

`.skills/_harness/link.sh <target-dir>` creates symlinks from `<target-dir>/<skill-name>` to `.skills/_skills/<skill-name>` for every skill directory. It is idempotent (safe to re-run). Pass `--clean` to remove existing symlinks before creating new ones.

When adding a new IDE template, include a "Native discovery" SETUP step calling `link.sh` with the IDE's cross-agent path (`.agents/skills/` or `.claude/skills/`).
