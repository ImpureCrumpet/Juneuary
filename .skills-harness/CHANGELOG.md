# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.2] - 2026-05-18

### Added

- **`check.sh` — native discovery completeness.** When `.agents/skills/` or `.claude/skills/` exist, validates that every harness skill under `_skills/` has a symlink with the correct relative target; reports missing, wrong-target, and dangling symlinks.
- **`check.sh --link` / `SKILLS_AUTO_LINK=1`:** runs `link.sh` on each existing native discovery directory (idempotent), then validates. Does not create native dirs that were never set up.

### Changed

- **`harness-subtree` v1.5.2** — migration validate step documents `check.sh --link` as an alternative to manual `link.sh`.
- **`harness-upgrade` v1.1.1** — documents `check.sh --link` / completeness validation in the 0.4.0 changes table.
- **`skill-author` v1.5.3** — step 8 mentions `check.sh --link` for syncing native discovery dirs.

### Fixed

- **Kit semver matches release tags.** `kit_version`, CHANGELOG, README, and `AGENTS_skills.md` now align with git tag **`v1.1.2`**. Earlier **`v1.1.1`** / **`v1.1.2`** tags pointed at the 1.0.1 tree without matching `_meta.yml`; **`v1.1.2`** now points at this release. Prefer **`v1.1.2`** over **`v1.0.2`** (short-lived tag on the same commit before renumbering).

## [1.0.1] - 2026-05-02

Discoverability fix for [issue #4](https://github.com/Gargoyle-Apps/skills-harness/issues/4): legacy manual installs whose `.skills/_meta.yml` `repo_url` points at an old fork (e.g. `gotalab/skills-harness`, which now 404s) hit the canonical-URL guard during migration, and the previous error didn't make clear that **`--remote-url https://github.com/Gargoyle-Apps/skills-harness`** is the **normal** fix when adopting the official upstream — not an exotic override.

### Changed

- **`migrate-to-subtree.sh` — clearer canonical-URL error.** The refusal message now (a) frames the situation as the **expected** legacy-install path, (b) shows the full canonical-upstream invocation including `--reconcile --symlink-consumer-skills`, (c) notes that `--reconcile` will rewrite `_meta.yml` to the canonical `repo_url`/`kit_version` after apply (so no manual edit is needed), and (d) explicitly warns that `--accept-derived-url` is **unsafe** when the listed URL is dead or stale and should only be used for deliberately maintained private forks.
- **`harness-subtree` v1.5.1** — "Stale `repo_url` in `.skills/_meta.yml`" section rewritten with the canonical-upstream command block, the `--reconcile` rewrite guarantee, and the same `--accept-derived-url` safety note.

## [1.0.0] - 2026-05-02

First **stable** kit release for multi-repo deployment. Intended behaviour matches **0.6.1**; the major version marks production readiness of the subtree workflow (`migrate-to-subtree.sh`, `--skip-subtree`, `--reconcile`, `--symlink-consumer-skills`), optional `prefixes:` / `consumer_skills_dir:` in `.skills/_meta.yml`, symlink-safe `check.sh`, consumer/kit role autodetection, and the upgrade/migration skills — after validation beyond the initial test consumers.

### Changed

- **Pinning examples** in **README** and **harness-subtree** now cite `v1.0.0` for reproducible curl/bootstrap and subtree pulls.
- **`harness-subtree` v1.5.0** — frontmatter bump; bootstrap/curl examples aligned with the `v1.0.0` tag.
- **`skill-author` v1.5.2** — example `_meta.yml` snippet: `kit_version` set to `1.0.0`.

## [0.6.1] - 2026-05-02

Closes the two follow-ups from [issue #3](https://github.com/Gargoyle-Apps/skills-harness/issues/3) (originally deferred from 0.6.0). Verified end-to-end against the same consumer (`Minecraft Minder`) that produced the original report; ImpureCrumpet flagged `--symlink-consumer-skills` as the single biggest UX win in the validation comment.

### Added

- **`migrate-to-subtree.sh --reconcile`** — automates the previously-manual post-`git subtree pull` reconcile. Drops every existing kit-skill row from `.skills/_index.md` and re-inserts upstream's rows for those names; bumps `kit_version` and `repo_url` in `.skills/_meta.yml` to match the subtree. Consumer rows, intro text, table comments, and other `_meta.yml` fields (`role`, `prefixes`, `consumer_skills_dir`, custom keys) are preserved verbatim. Idempotent — re-running prints `ok already matches` for both files. Dry-run by default; `--apply` writes.
- **`migrate-to-subtree.sh --symlink-consumer-skills`** — for repos that declare `consumer_skills_dir:` in `_meta.yml` (e.g. `.cursor/skills`), generates `.skills/_skills/<name> → ../../<consumer_skills_dir>/<name>` symlinks with correct relative depth. Skips entries without a `SKILL.md`, skips kit-skill name collisions, refuses to clobber pre-existing real directories (warns and skips). Idempotent. Eliminates the relative-depth foot-gun (`../../../` vs `../../`) flagged in the original report.
- **`migrate-to-subtree.sh --skip-subtree`** — companion flag for already-vendored installs: skips the subtree-add and kit-skill replacement steps so `--reconcile` and `--symlink-consumer-skills` can run in update-mode against an existing `.skills-harness/` tree without re-vendoring.
- **`harness-subtree` v1.4.0** — "Updating the vendored kit" section rewritten around the new single-command flow: `migrate-to-subtree.sh --skip-subtree --reconcile --symlink-consumer-skills --apply`. Notes section updated to mark both `consumer_skills_dir` auto-symlink and `_index.md`/`_meta.yml` reconcile as shipped (0.6.1+).

### Fixed

- **`migrate-to-subtree.sh` — `set -e` traps in helper functions.** New helpers (`reconcile_meta`, `reconcile_index`, `symlink_consumer_skills`) used bare `return` after conditional commands, which under `set -e` could propagate the conditional's exit status and abort the script mid-run. All bare `return`s in the new helpers now use explicit `return 0`. Same pattern applied as a defensive fix in pre-existing helpers.

## [0.6.0] - 2026-05-02

### Fixed

Real-world subtree-migration friction reported in [issue #3](https://github.com/Gargoyle-Apps/skills-harness/issues/3) (first-time migration of a stale 0.3.1 install). The fixes below close the critical and high-priority items from that report; `--reconcile` and auto-symlinking from `consumer_skills_dir` are deferred to a follow-up release.

- **`check.sh` — symlink-safe paths.** Path resolution now uses `${BASH_SOURCE[0]}` + `pwd -L` instead of `cd "$(dirname "$0")" && pwd`, so running `.skills/_harness/check.sh` after a subtree migration (where `.skills/_harness/` is a symlink into `.skills-harness/.skills/_harness/`) correctly resolves the consumer's `_skills/`/`_index.md`/repo root rather than the subtree's. Without this fix, every consumer-authored skill row in `_index.md` was reported as missing. Eliminates the wrapper-script workaround.
- **`check.sh` — auto consumer/kit role detection.** The kit-surface assertions (CHANGELOG/README/AGENTS_skills.md kit-version markers) are now skipped automatically when either `.skills-harness/` exists at the repo root or `.skills/_meta.yml` declares `role: consumer`. `SKILLS_CHECK_KIT_SURFACES` env var still wins when set explicitly. Documented in README's Validation section and CONTRIBUTING's Environment overrides table.
- **`migrate-to-subtree.sh` — dirty-tree check ignores self + `*.bak/`.** The dirty-tree precondition now filters out the script's own untracked path and any `*.bak/` directories, so dropping the script directly into `.skills/_harness/migrate-to-subtree.sh` and running from there with `--apply` works without moving it to `/tmp` first.
- **`migrate-to-subtree.sh` — stale `repo_url` safety.** When the upstream URL is derived from `.skills/_meta.yml` (no `--remote-url`) and doesn't match `Gargoyle-Apps/skills-harness`, the script now refuses to proceed and explains how to override (`--remote-url <canonical>` or `--accept-derived-url`). Stale installs that pointed at archived forks (e.g. `gotalab/skills-harness`) would previously vendor the wrong project silently.
- **`migrate-to-subtree.sh` — `--accept-upstream <name>[,<name>…]`.** New per-skill flag for accepting upstream on selected drifted kit skills, instead of `--force`'s sledgehammer that overwrites every drifted skill at once.
- **`migrate-to-subtree.sh` — prefix derivation also splits on whitespace.** A repo dir name like `Media Library` now correctly derives `ml-` instead of `m-`. The split collapses runs of `-`, `_`, and whitespace.
- **`migrate-to-subtree.sh` — surfaces `consumer_skills_dir:` from `_meta.yml`.** When declared (e.g. for Cursor-style repos that keep real bodies under `.cursor/skills/`), the audit prints a reminder that `.skills/_skills/<name>/` symlink shims must be created manually. Auto-symlinking is planned but not yet implemented.

### Added

- **`skill-author` v1.5.1 — explicit single-prefix override + whitespace split.** Derivation now documents whitespace as a separator (matching the script). Also documents the `prefixes: [single-prefix-]` pattern as the recommended way to override the auto-derived prefix on single-family repos where the heuristic gives the wrong answer.
- **`_meta.yml` schema (optional fields):** `role: consumer|kit`, `consumer_skills_dir: <path>`, `prefixes: [...]`. All three are read by the kit (`role` by `check.sh`, the others by `migrate-to-subtree.sh` and `skill-author`); none are required.
- **`skill-author` v1.5.0 — multi-prefix repos:** new "Multiple prefixes (per-repo override)" section. Consumer repos that host distinct skill families can declare an explicit `prefixes:` list in `.skills/_meta.yml` (e.g. `[bld-, bin-]`); when present, every consumer-authored skill must start with one of those prefixes and the auto-derived single prefix is bypassed. Absent the list, the existing single-derived-prefix rule applies. Kit-bundled skills stay unprefixed in both modes. The same convention is mirrored in `AGENTS_skills.md` so consumers see it during bootstrap.
- **`migrate-to-subtree.sh` — multi-prefix audit:** the prefix audit now reads `prefixes:` from `.skills/_meta.yml` (minimal block-style YAML parser, bash 3.2-safe) and accepts any declared prefix. Violation messages list the full allowed set so the user can pick the right family for each skill. Falls back to the single auto-derived prefix when no list is declared.
- **`migrate-to-subtree.sh`:** new helper script under `.skills/_harness/` that migrates a manual file-copy install to a subtree-vendored install **non-destructively**. Dry-run by default; `--apply` performs the actions. Adds the subtree at `.skills-harness/`, backs up `.skills/_harness/` and each kit-bundled skill to `*.bak/` and replaces them with symlinks into the subtree, and **never touches consumer-authored skills, `.skills/_index.md`, or `.skills/_meta.yml`**. Drifted kit skills are kept (the script prints `diff` commands); `--force --apply` accepts upstream after review. Audits consumer skills against the **skill-author** prefix convention (derives expected prefix from the repo's directory name and reports renames) and against the five required frontmatter fields; both audits are warn-only — renames stay manual because the index, frontmatter `name`, and `dependencies` references must move together.
- **`harness-subtree` skill (v1.3.0):** documents installing, updating, and **migrating to** the kit in a consumer repo as a `git subtree` at `.skills-harness/`, with a symlinked `.skills/` shell so kit-managed pieces stay overwritable while consumer-authored skills, the index, and `_meta.yml` remain independent. Covers initial install, `git subtree pull` updates, post-pull symlink/index reconcile, version pinning, and gotchas. Includes a 10-step **Migrating an existing manual install to subtree** workflow that leans on `migrate-to-subtree.sh` for the safe parts and walks through audit, drift handling, prefix/frontmatter cleanup, apply, backup inspection, index reconcile, native-discovery re-link, and validation. Issue #3 follow-ups land here too: curl-bootstrap line for stale installs, stale-`repo_url` safety, `--accept-upstream` vs `--force`, the symlink-safe `check.sh` (no wrapper needed), consumer/kit auto-detect, optional `consumer_skills_dir:` schema, and explicit call-outs for the deferred `--reconcile` and auto-symlinking follow-ups. Triggers include *migrate manual install to subtree* and *convert harness install to subtree*.
- **`README.md`:** new **Migrating an existing manual install** subsection under Deploying as a git subtree pointing at the helper script and the skill.
- **`README.md`:** new top-level **Deploying as a git subtree** section with layout diagram, install commands, update commands, pinning notes, and a "Why versioning matters more under subtree" subsection that ties consumer pulls to the per-skill `version` and `CHANGELOG` contract.
- **`AGENTS_skills.md`:** new **How this repo got the kit** section so agents detect manual-copy vs. subtree installs (presence of `.skills-harness/`) and route to **harness-upgrade** vs. **harness-subtree** accordingly.
- **`_rules.md` (and all `*_template.md` via `sync.sh`):** new bullet declaring that `.skills-harness/` is upstream-owned in subtree installs and pointing at **harness-subtree** for any reconcile work.

### Changed

- **`kit-release` v1.1.0:** new Notes bullets emphasizing that subtree consumers diff against `CHANGELOG.md` and per-skill `version` bumps on every `git subtree pull`, plus optional tagging guidance for consumers who pin to a release tag.
- **`harness-upgrade` v1.1.0:** "When to use" now defers to **harness-subtree** when `.skills-harness/` is present, so subtree-vendored repos don't follow the file-copy migration path.

## [0.5.2] - 2026-04-29

### Added

- **`skill-author` v1.4.0:** new "Naming convention" section. Skills authored in **consumer repos** must be prefixed with the repo's initials (split repo dir name on `-`/`_`, take first letter of each segment, lowercased, append `-`; e.g. `ux-package-management` → `uxpm-`, `git-minder` → `gm-`, `warehouse` → `w-`). The kit itself (`skills-harness`) deliberately stays unprefixed to avoid collisions with consumer repos that share initials (e.g. `so-high`).
- **`AGENTS_skills.md`:** new "Skill naming in consumer repos" section above the hard gate so consumers see the convention during bootstrap.
- **`CONTRIBUTING.md`:** callout in "Adding or editing a skill" clarifying that kit skills (added to this repo) stay unprefixed.

## [0.5.1] - 2026-04-16

### Changed

- **`README.md`:** "Skill format" table column changed from "Required" (all yes) to "Required by" (agentskills.io + harness vs harness only), matching the CONTRIBUTING.md style.
- **`AGENTS_skills.md`:** added upstream maintainer HTML comment explaining why the file remains in the canonical repo. Collapsed Path A template table into a pointer to the README "Supported tools" table; added Roo Code and OpenCode to the Path A environment list.

## [0.5.0] - 2026-04-16

### Added

- **`sync.sh`:** new script regenerates the Rules block in all `*_template.md` files from `_rules.md`. Dry-run by default; `sync.sh --write` performs edits. Replaces the manual copy-paste step in CONTRIBUTING.md.
- **`build-index.sh`:** new script regenerates `_index.md` table rows from SKILL.md frontmatter. Dry-run by default; `build-index.sh --write` performs edits. Frontmatter is now the author-time source of truth for index content.

### Changed

- **`CONTRIBUTING.md`:** "Changing the Rules block" step 2 now references `sync.sh --write`; "Adding or editing a skill" step 3 now references `build-index.sh --write`.
- **`skill-author` v1.3.0:** step 6 updated to run `build-index.sh --write` instead of manually adding an index row.
- **`_index.md`:** table rows regenerated from frontmatter (richer descriptions and full trigger lists).

## [0.4.2] - 2026-04-16

### Added

- **`check.sh --quiet`:** suppresses success footer for clean CI/hook output.
- **`SKILLS_CHECK_KIT_SURFACES=0`:** env var to skip README and `AGENTS_skills.md` version assertions (for downstream kits with custom surfaces).
- **Env-var overrides:** `check.sh` and `link.sh` accept `SKILLS_HARNESS_DIR`, `SKILLS_DIR`, `SKILLS_REPO_ROOT` (plus `SKILLS_INDEX`, `SKILLS_RULES` for check) to support non-standard repo layouts without forking scripts.
- **`link.sh` dangling-symlink pruning:** re-running `link.sh` without `--clean` now auto-removes broken symlinks left by deleted or renamed skills.

### Changed

- **`CONTRIBUTING.md`:** new "Environment overrides" section documenting env vars and `--quiet`.

## [0.4.1] - 2026-04-12

### Added

- **`kit-release` skill (v1.0.0):** procedure to bump kit semver while keeping `CHANGELOG.md`, `.skills/_meta.yml`, `README.md`, and `AGENTS_skills.md` aligned; validated by `check.sh`.

### Changed

- **`README.md`**, **`AGENTS_skills.md`:** surface **Current release** / **Kit version** matching the changelog and `_meta.yml`.
- **`check.sh`:** verifies kit version consistency across `_meta.yml`, top `CHANGELOG` release, `README`, and `AGENTS_skills.md`.
- **`CONTRIBUTING.md`:** versioning section references **kit-release** and the shared surfaces.

## [0.4.0] - 2026-04-07

### Added

- **`link.sh`:** symlink helper script that creates symlinks from native IDE discovery paths (`.agents/skills/`, `.claude/skills/`) into `.skills/_skills/`, enabling auto-invocation, `@skill-name` mentions, and skill panels across 9 IDEs.
- **`ROO_template.md`:** Roo Code environment template.
- **`OPENCODE_template.md`:** OpenCode environment template.
- **`harness-upgrade` skill (v1.0.0):** guides upgrading older harness installations to v0.4.0+ with native IDE discovery; includes IDE swap instructions.
- **`.gitignore`:** `.agents/skills/` and `.claude/skills/` entries for generated symlink directories.

### Changed

- **All templates:** SETUP sections now include a "Native discovery" step calling `link.sh` with the IDE-appropriate target directory.
- **`check.sh`:** added optional symlink validation for `.agents/skills/` and `.claude/skills/` directories.
- **`skill-template` v1.1.0:** added [agentskills.io](https://agentskills.io/specification) frontmatter constraints (`name` length/format, `description` length) to authoring instructions.
- **`skill-author` v1.2.0:** added step to re-run `link.sh` after creating a new skill.
- **`link.sh`:** stale symlink detection (auto-updates wrong targets), `_`-prefixed directory filter, flexible `--clean` arg position.
- **`AGENTS_skills.md`:** bootstrap table now includes Roo Code and OpenCode rows.
- **`README.md`:** added native IDE discovery section with `link.sh` usage and IDE swap guide; updated supported tools table.
- **`CONTRIBUTING.md`:** added frontmatter compatibility requirements and symlink helper guidance.

## [0.3.2] - 2026-04-04

### Changed

- **Rules:** replaced "Add new skills to the index when you create them" with a stronger obligation — `.skills/_index.md` is the source of truth; agents must update it on create, rename, or delete, and never leave it out of sync.
- **`skill-author` v1.1.0:** added "Renaming or deleting a skill" section reinforcing index sync on all lifecycle operations.
- **Index:** removed stale `ghost` placeholder row.

## [0.3.1] - 2026-04-03

### Fixed

- **`check.sh`:** `err()` no longer aborts on the first failure under `set -e` (use pre-increment for the error counter). Replaced bash 4 associative arrays with a portable marker string so the script runs on macOS `/bin/bash` 3.2.

## [0.3.0] - 2026-04-03

### Added

- **`_rules.md`:** canonical Rules block as a single source of truth under `.skills/_harness/`. All templates embed a copy; `_rules.md` is the maintainer reference.
- **`check.sh`:** validation script that verifies index-to-directory consistency, frontmatter completeness, `name` field matching, and Rules block sync across all templates.
- **`CONTRIBUTING.md`:** contributor guidance covering Rules changes, new templates, skill authoring, testing, and versioning.
- **`_meta.yml` `repo_url`:** added `repo_url` so embedded kits can trace their origin.

### Changed

- **Split `AGENTS_template.md`** into three separate files: `CURSOR_template.md`, `CODEX_template.md`, `COPILOT_template.md`. Each template is self-contained — no more stripping unused environment blocks.
- **Standardized merge guidance:** all templates now use "append under a `## Skills Harness` heading" as the default merge strategy instead of listing multiple options.
- **Template SETUP blocks:** each now ends with a **Verify** checklist for post-setup confirmation.
- **Bootstrap table (`AGENTS_skills.md`):** updated to reference the new split template filenames.
- **README:** updated supported tools table for split templates; added **Validation** and **Contributing** sections.
- **`ref/skills-harness-plan.md`:** updated to reflect current state — `AGENTS_skills.md` naming, split templates, `_rules.md`, `check.sh`, corrected frontmatter examples, and marked as historical design reference.

### Removed

- **`AGENTS_template.md`:** replaced by `CURSOR_template.md`, `CODEX_template.md`, `COPILOT_template.md`.
- **`.gitignore` `!.env.example`:** removed stale exception for a file that does not exist.

## [0.2.2] - 2026-04-02

### Changed

- **Path B (`AGENTS_skills.md`):** Clarify no harness-template paste into `AGENTS.md`; existing `AGENTS.md` stays the project contract; optional **Skills (agnostic)** section example; `_harness/` is reference-only for Path B.
- **`skill-author`:** Prerequisites no longer imply a permanent dependency on `AGENTS_skills.md`; after bootstrap removal, check root **`AGENTS.md`** / README for Path B policy.
- **Harness templates:** Rules bullet rewritten so the bootstrap gate applies **only while** `AGENTS_skills.md` exists; Path B may record policy in `AGENTS.md`.

## [0.2.1] - 2026-04-02

### Added

- **`AGENTS_skills.md` Path B — agnostic / multi-ecosystem:** author portable skills under `.skills/` without installing a tool-specific harness in the repo; document in README/CONTRIBUTING and remove bootstrap.
- **README:** subsection for agnostic repositories and downstream harness usage.

### Changed

- **`skill-author` prerequisites:** allow completion via Path A or Path B (`AGENTS_skills.md`).

## [0.2.0] - 2026-04-02

### Changed

- **Bootstrap renamed to `AGENTS_skills.md`** so it does not overwrite an existing project `AGENTS.md`. It is removed after setup.
- **AGENTS-based harness:** templates now require **merging** into existing `AGENTS.md` when that file already exists; sidecar templates merge pointers into `AGENTS.md` the same way.
- **`AGENTS_skills.md` gate:** explicit rules that the user must **declare the environment** before any skill creation, refactor, or index registration; runtime harness rules repeat this while the bootstrap file is present.
- **skill-author:** prerequisites section pointing at the bootstrap gate.

## [0.1.0] - 2026-04-02

### Added

- Bootstrap `AGENTS.md` and `.skills/` layout: index, bundled skills (`skill-template`, `skill-author`), and environment templates under `.skills/_harness/`.
- Human-facing `README` with quick start, supported tools, and optional MCP pointer.
