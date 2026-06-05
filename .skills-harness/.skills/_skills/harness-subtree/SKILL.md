---
name: harness-subtree
description: "Install or update the skills-harness kit in a consumer repository as a git subtree at .skills-harness/."
triggers:
  - deploy harness as subtree
  - install harness as subtree
  - vendor skills-harness
  - update vendored harness
  - subtree pull skills-harness
  - skills harness subtree
  - add skills-harness subtree
  - migrate manual install to subtree
  - convert harness install to subtree
dependencies: []
version: "1.5.2"
---

# Harness Subtree

## When to use this skill

Load when a consumer repository wants to **vendor the entire skills-harness kit** (instead of copying files by hand) so that updates can be pulled with `git subtree pull`. Also use when an existing subtree-vendored install needs to be updated to a newer kit version.

This skill is for the **consumer** (the repo *receiving* the kit). The upstream `skills-harness` repository itself never installs into itself.

## Why subtree

- **Reproducible installs.** The upstream tree (scripts, templates, bundled skills, `_rules.md`, `_meta.yml`, `CHANGELOG.md`) is fetched as a single commit; no manual file copying.
- **Traceable updates.** `git subtree pull` brings in upstream changes as a merge commit; the local `CHANGELOG.md` (inside the vendored tree) explains what changed.
- **No submodule footguns.** Subtree files live in the consumer's history, so clones, CI, and offline checkouts work without `git submodule update --init`.
- **Per-skill versioning matters.** Because the kit can be updated mid-project, the per-skill `version` field in each `SKILL.md` frontmatter is the contract: when a kit-bundled skill bumps, it shows up after `git subtree pull` and consumers can diff against the prior vendored snapshot.

## Layout

After install, the consumer repo looks like this:

```text
<consumer-repo>/
├── .skills-harness/        ← vendored kit (subtree, do not hand-edit)
│   ├── .skills/
│   │   ├── _harness/       ← scripts + templates + _rules.md
│   │   ├── _skills/        ← kit-bundled skills (skill-template, skill-author, ...)
│   │   ├── _index.md       ← upstream index (kit skills only)
│   │   └── _meta.yml       ← upstream kit_version
│   ├── AGENTS_skills.md    ← bootstrap (copied to root once during setup)
│   ├── README.md
│   ├── CHANGELOG.md        ← read this after every `git subtree pull`
│   └── ...
├── .skills/                ← consumer-owned runtime tree
│   ├── _harness            → symlink → ../.skills-harness/.skills/_harness
│   ├── _skills/
│   │   ├── skill-template  → symlink → ../../.skills-harness/.skills/_skills/skill-template
│   │   ├── skill-author    → symlink → ../../.skills-harness/.skills/_skills/skill-author
│   │   ├── harness-upgrade → symlink → ../../.skills-harness/.skills/_skills/harness-upgrade
│   │   ├── kit-release     → symlink → ../../.skills-harness/.skills/_skills/kit-release
│   │   ├── harness-subtree → symlink → ../../.skills-harness/.skills/_skills/harness-subtree
│   │   └── <prefix>-<your-skill>/   ← real consumer-authored skill dirs
│   ├── _index.md           ← consumer-owned: kit rows + your rows
│   └── _meta.yml           ← consumer-owned: pin to vendored kit_version
└── AGENTS.md               ← Path A harness or Path B policy; see AGENTS_skills.md
```

The split is deliberate: kit-owned files live under `.skills-harness/` (overwritten on every pull), while consumer-owned files live under `.skills/`. Symlinks bridge them so the standard runtime paths (`.skills/_harness/...`, `.skills/_skills/<name>/SKILL.md`) keep working without env-var gymnastics.

## Initial install

1. **Add upstream as a remote** (one-time per clone; the remote name is local-only):

   ```bash
   git remote add skills-harness https://github.com/Gargoyle-Apps/skills-harness
   git fetch skills-harness
   ```

2. **Add the subtree at `.skills-harness/`** (one-time per repo, creates a single squash commit):

   ```bash
   git subtree add --prefix=.skills-harness skills-harness main --squash
   ```

3. **Create the consumer-owned `.skills/` shell:**

   ```bash
   mkdir -p .skills/_skills
   ln -s ../.skills-harness/.skills/_harness .skills/_harness
   for s in .skills-harness/.skills/_skills/*/; do
     name="$(basename "$s")"
     ln -s "../../.skills-harness/.skills/_skills/$name" ".skills/_skills/$name"
   done
   ```

4. **Seed `.skills/_index.md`** by copying the upstream index, then leave room for your own rows:

   ```bash
   cp .skills-harness/.skills/_index.md .skills/_index.md
   ```

5. **Seed `.skills/_meta.yml`** with the vendored kit version (mirror, not symlink — you may pin behind upstream intentionally):

   ```bash
   cp .skills-harness/.skills/_meta.yml .skills/_meta.yml
   ```

6. **Bootstrap.** Copy the bootstrap file to the repo root and follow it:

   ```bash
   cp .skills-harness/AGENTS_skills.md AGENTS_skills.md
   ```

   Open `AGENTS_skills.md` with your agent and complete **Path A** (single-IDE harness install) or **Path B** (agnostic policy). Delete `AGENTS_skills.md` when done.

7. **Update `.gitignore`.** The native-discovery symlink directories (`.agents/skills/`, `.claude/skills/`) are machine-local — they should already be ignored if Path A added them. Symlinks under `.skills/` and the `.skills-harness/` subtree directory itself **are** committed.

8. **Validate:**

   ```bash
   .skills/_harness/check.sh
   ```

   This should pass. The kit version assertion compares `.skills/_meta.yml` (consumer copy) against the consumer's root `README.md` and `CHANGELOG.md` if they exist; if your consumer repo doesn't surface kit version in those files, set `SKILLS_CHECK_KIT_SURFACES=0` to skip that check.

## Updating the vendored kit

1. **Pull upstream** (from the repo root, on a clean working tree):

   ```bash
   git fetch skills-harness
   git subtree pull --prefix=.skills-harness skills-harness main --squash
   ```

   This creates a merge commit. Resolve conflicts only inside `.skills-harness/` — never hand-edit subtree files outside of conflict resolution.

2. **Read `.skills-harness/CHANGELOG.md`** for the diff between your previous vendored version and the new one. Pay attention to bumped per-skill `version` fields, new bundled skills, and any removed/renamed bundled skills.

3. **Run reconcile + symlink refresh in a single dry-run** to preview everything `--apply` would change:

   ```bash
   .skills/_harness/migrate-to-subtree.sh \
     --skip-subtree --reconcile --symlink-consumer-skills
   ```

   `--skip-subtree` tells the script the kit is already vendored and to act in update-mode. The dry-run prints planned changes to `.skills/_index.md`, `.skills/_meta.yml`, and any new symlinks for consumer skills under `consumer_skills_dir:`.

4. **Apply:**

   ```bash
   .skills/_harness/migrate-to-subtree.sh \
     --skip-subtree --reconcile --symlink-consumer-skills --apply
   ```

   What this does:
   - **`--reconcile`** rewrites `.skills/_index.md` by dropping every existing kit-skill row and re-inserting upstream's rows for those names; consumer rows and intro text/comments are preserved verbatim. Bumps `kit_version` and `repo_url` in `.skills/_meta.yml` to match the subtree's copy; every other field (`role`, `prefixes`, `consumer_skills_dir`, custom keys) is preserved. Idempotent — re-running prints `ok already matches` for both files.
   - **`--symlink-consumer-skills`** (only if `consumer_skills_dir:` is declared in `_meta.yml`) walks that directory, ignores entries without a `SKILL.md` and ignores anything whose name collides with a kit skill, and creates `.skills/_skills/<name> → ../../<consumer_skills_dir>/<name>` symlinks for the rest. Pre-existing real directories are never clobbered (the script warns and skips). Idempotent.

5. **Re-run native discovery** if you set it up:

   ```bash
   .skills/_harness/link.sh .agents/skills    # or .claude/skills
   ```

   `link.sh` auto-prunes dangling symlinks left by removed kit skills.

6. **Validate:**

   ```bash
   .skills/_harness/check.sh
   ```

The pre-0.6.1 manual reconcile (hand-merging the index, hand-bumping `_meta.yml`, hand-creating consumer-skill shims with the right relative depth) is no longer needed. If you prefer that flow anyway, omit `--reconcile` and `--symlink-consumer-skills` and the script will print the manual checklist instead.

## Migrating an existing manual install to subtree

Use this when a repo already has `.skills/` (installed by file-copy from an earlier kit version) and you want to switch to subtree-vendored updates **without losing consumer-authored skills, the index, or `_meta.yml`**.

The kit ships a helper for this: **`.skills/_harness/migrate-to-subtree.sh`**. It is **dry-run by default** — it inventories the repo, classifies each skill as kit-bundled vs. consumer-authored, and prints exactly what it would change. Re-run with `--apply` to perform the changes.

### Bootstrapping the script on a stale install

Older harness installs (pre-0.6.0) don't ship `migrate-to-subtree.sh`. Pull it from upstream into the existing `.skills/_harness/` directory before running:

```bash
curl -sSLo .skills/_harness/migrate-to-subtree.sh \
  https://raw.githubusercontent.com/Gargoyle-Apps/skills-harness/main/.skills/_harness/migrate-to-subtree.sh
chmod +x .skills/_harness/migrate-to-subtree.sh
```

The script's dirty-tree check ignores its own untracked file plus any `*.bak/` directories, so dropping it directly into `.skills/_harness/` and running from there is fine. For a fully reproducible install, swap `main` in the URL above for a kit release tag (e.g. `v1.0.0`).

### Stale `repo_url` in `.skills/_meta.yml`

Legacy manual installs frequently carry an outdated upstream URL — typically a fork or pre-rename location that is no longer reachable (e.g. `gotalab/skills-harness`, which 404s). When migrating these repos to subtree, the script will **refuse** to vendor any URL that doesn't contain `Gargoyle-Apps/skills-harness`. **This is expected**, not a bug in the consumer's repo.

The standard fix when adopting the official upstream:

```bash
.skills/_harness/migrate-to-subtree.sh \
  --remote-url https://github.com/Gargoyle-Apps/skills-harness \
  --apply --reconcile --symlink-consumer-skills
```

`--reconcile` rewrites `.skills/_meta.yml` so `repo_url` and `kit_version` match the vendored subtree, so no manual edit is needed afterwards.

`--accept-derived-url` exists only for the rare case where a team **deliberately** maintains a private fork at the URL `_meta.yml` lists and wants to vendor that fork. **Do not use `--accept-derived-url` to silence the canonical check on a stale install** — the subtree add will fail if the URL is dead, or (worse) silently vendor the wrong tree.

### What it changes (apply mode)

- Adds the upstream remote (`skills-harness` by default; URL pulled from `.skills/_meta.yml` `repo_url` or `--remote-url`).
- Runs `git subtree add --prefix=.skills-harness <remote> <ref> --squash` (one squash commit, fully reversible with `git revert`).
- For each **kit-owned** target:
  - `.skills/_harness/` is moved aside to `.skills/_harness.bak/` and replaced with a symlink into the subtree.
  - For each kit-bundled skill (`skill-template`, `skill-author`, `harness-upgrade`, `kit-release`, `harness-subtree`): if the local copy is **byte-identical** to upstream, it is moved to `<name>.bak/` and replaced with a symlink. If the local copy **differs** (you hand-edited it, or you're on an older kit version), the script **leaves the local copy in place** and prints the diff command. Two ways to accept upstream after review:
    - `--accept-upstream <name>[,<name>…] --apply` — surgical: backup-and-symlink only the listed skills.
    - `--force --apply` — sledgehammer: backup-and-symlink **every** drifted kit skill in one pass.

### What it never touches

- **Consumer-authored skills** (any directory under `.skills/_skills/` whose name is not in the kit-bundled set) — left exactly as they are.
- **`.skills/_index.md`** and **`.skills/_meta.yml`** — consumer-owned. By default the script prints a reconcile checklist instead of editing them. Pass **`--reconcile`** to opt in to automated kit-row merge + `kit_version`/`repo_url` bump (consumer rows and other `_meta.yml` fields stay verbatim).
- **Native discovery symlink directories** (`.agents/skills/`, `.claude/skills/`).

### What it audits (warns, never modifies)

- **Prefix convention** (per **skill-author**): for every consumer-authored skill, the script checks the name against the repo's allowed prefix set:
  - **Default (single-prefix repos):** the expected prefix is derived from the repo's root directory name (split on `-`/`_`, first letter of each segment, lowercased, append `-`). In a repo named `eng-package-management`, a skill called `deploy-checklist` triggers `→ suggested rename: epm-deploy-checklist`.
  - **Multi-prefix repos:** if `.skills/_meta.yml` declares a `prefixes:` list (e.g. `[bld-, bin-]`), the script accepts **any** of those prefixes and ignores the auto-derived one. A violation message lists all declared prefixes so the user can pick the family the skill belongs to. Kit-bundled skills stay unprefixed in either mode.

  Renaming is a manual, deliberate step — the script never renames automatically because the index, frontmatter, and any cross-skill `dependencies` references all need to update together.
- **Frontmatter shape**: each consumer SKILL.md is checked for the five required fields (`name`, `description`, `triggers`, `dependencies`, `version`) and that `name` matches the directory. Missing fields are reported so you can patch them up against the current `skill-template`.

### Workflow

1. **Audit first** (no changes):

   ```bash
   .skills/_harness/migrate-to-subtree.sh
   ```

   Read the output. Note any kit skills flagged as drifted, and any consumer skills flagged for prefix or frontmatter issues.

2. **Decide on drifted kit skills.** For each drift report, run the suggested `diff -ru` command. If your edits should be upstreamed, contribute them and pull a new release later. If your edits are throwaway/local and you want the upstream version, plan to re-run with `--accept-upstream <name>` (per-skill) or `--force` (all drifted skills).

3. **Fix prefix and frontmatter issues** *before* the migration if possible — it keeps the index reconcile (step 6) cleaner. For each prefix warning:
   - `git mv .skills/_skills/<name> .skills/_skills/<prefix><name>`
   - Edit `<prefix><name>/SKILL.md` frontmatter: set `name: <prefix><name>`
   - Update `.skills/_index.md` row name
   - Search for `dependencies:` mentions of the old name across `.skills/_skills/*/SKILL.md` and update them
   - Run `.skills/_harness/check.sh` to confirm

4. **Apply** (clean working tree required; the script ignores its own untracked file and `*.bak/` dirs):

   ```bash
   .skills/_harness/migrate-to-subtree.sh --apply
   .skills/_harness/migrate-to-subtree.sh --apply --accept-upstream skill-author,skill-template
   .skills/_harness/migrate-to-subtree.sh --apply --force
   ```

   To collapse steps 6–7 (manual `_index.md` reconcile and `_meta.yml` bump) into the same run, add `--reconcile`. To also generate `.skills/_skills/<name>/` shim symlinks when `consumer_skills_dir:` is declared, add `--symlink-consumer-skills`. Both are dry-run-friendly; preview first, then re-run with `--apply`.

5. **Inspect the backups.** The script left `.skills/_harness.bak/` and any `.skills/_skills/<name>.bak/` directories so you can confirm nothing important was lost. Once happy, `rm -rf` them in a follow-up commit (or keep them on a separate branch).

6. **Reconcile `.skills/_index.md`.** Open `.skills-harness/.skills/_index.md` (the upstream, kit-only index) side by side with your `.skills/_index.md`. Make sure every kit-bundled skill row in the upstream index appears in your local index, and that every consumer-authored skill row in your local index is preserved. Do **not** simply overwrite — your local file is the union.

7. **Bump `.skills/_meta.yml`** `kit_version` to match `.skills-harness/.skills/_meta.yml` (or pin lower and document why).

8. **Re-link native discovery** if you use it (`link.sh` is now a symlink into the subtree, so just call it):

   ```bash
   .skills/_harness/link.sh .agents/skills    # or .claude/skills
   # or sync every existing native dir and validate in one step:
   .skills/_harness/check.sh --link
   ```

9. **Validate:**

   ```bash
   .skills/_harness/check.sh
   ```

10. **Commit.** Two commits are usually clearest: the squashed `subtree add` commit (created by step 4) and a follow-up commit for the symlinks, index reconcile, `_meta.yml` bump, and `.bak` cleanup.

From this point on, updates are `git subtree pull` (see **Updating the vendored kit** above).

## Pinning to a specific kit version

To vendor a specific release instead of `main`:

```bash
git subtree add --prefix=.skills-harness skills-harness <tag-or-sha> --squash
# later
git subtree pull --prefix=.skills-harness skills-harness <new-tag-or-sha> --squash
```

Tags follow the kit's semver (see upstream `CHANGELOG.md` and `_meta.yml`).

## Notes and gotchas

- **Do not edit files inside `.skills-harness/`.** Local edits are silently overwritten on the next `git subtree pull`. Contribute changes upstream instead, or use Path B and override behaviour in your own consumer-owned skills.
- **Consumer skills always live outside the subtree** (real directories under `.skills/_skills/<prefix>-<name>/`). Apply the prefix convention from `skill-author`.
- **`AGENTS_skills.md` is ephemeral.** It is copied from `.skills-harness/AGENTS_skills.md` only during bootstrap and removed afterwards. It will reappear in `.skills-harness/` after each pull — that's fine; do not copy it back to root unless you are re-bootstrapping.
- **`check.sh` works through symlinks.** No env-var overrides are needed for the symlinked layout above. Use `SKILLS_*` env vars only if you choose a non-symlink layout (e.g. running scripts directly out of `.skills-harness/`).
- **Kit-bundled skill IDs stay unprefixed** (`skill-author`, `harness-upgrade`, etc.). Your own skills are prefixed per `skill-author`'s naming convention. The two coexist in `.skills/_index.md`.
- **Per-skill `version` is the consumer's contract** with kit skills. When `git subtree pull` brings in a skill bump, treat it like any vendored dependency upgrade: read the changelog, run `check.sh`, and smoke-test the affected skill.
- **`check.sh` is symlink-safe (0.6.0+).** Path resolution uses the script's invocation path with `pwd -L`, so running `.skills/_harness/check.sh` after migration correctly inspects the consumer's `_skills/` and `_index.md` rather than the subtree's. No wrapper script needed.
- **Consumer/kit role is auto-detected (0.6.0+).** `check.sh` skips the kit-surface assertions (CHANGELOG/README/AGENTS_skills.md kit-version markers) automatically when `.skills-harness/` exists at the repo root or `.skills/_meta.yml` declares `role: consumer`. Set `SKILLS_CHECK_KIT_SURFACES=1` to force the kit-author checks anyway, or `SKILLS_CHECK_KIT_SURFACES=0` to suppress them on a non-subtree consumer install.
- **`consumer_skills_dir:` schema (optional).** If real skill bodies live outside `.skills/_skills/` (for example a Cursor-style repo that keeps them under `.cursor/skills/<name>/`), record the path in `.skills/_meta.yml`:

  ```yaml
  consumer_skills_dir: .cursor/skills
  ```

  Then `migrate-to-subtree.sh --symlink-consumer-skills [--apply]` generates the `.skills/_skills/<name> → ../../<consumer_skills_dir>/<name>` shims with correct relative depth. Idempotent. Refuses to clobber real directories at the link path (warns and skips). Skips entries without a `SKILL.md` and any name that collides with a kit skill. (0.6.1+)
- **`--reconcile` automates `_index.md` and `_meta.yml` merge.** Drops every kit-skill row from your local `_index.md` and re-inserts upstream's rows for those names; bumps `kit_version`/`repo_url` in `_meta.yml` to match the subtree. Consumer rows, intro text, table comments, and other `_meta.yml` fields (`role`, `prefixes`, `consumer_skills_dir`) are preserved verbatim. Use after every `git subtree pull`; combine with `--symlink-consumer-skills` for a single-command update. (0.6.1+)
