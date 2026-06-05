# skills-harness

A zero-dependency, file-only kit that teaches coding agents how to discover and load skills on demand. Drop `.skills/` and `AGENTS_skills.md` into any repo — the agent sets itself up, reads the index, and loads each `SKILL.md` only when the task matches its triggers.

## Quick start

1. Copy `AGENTS_skills.md` and `.skills/` into your project root.
2. Open `AGENTS_skills.md` in your agent. It will ask which environment you use, then walk through setup automatically.
3. After setup, `AGENTS_skills.md` is deleted. The harness lives in `AGENTS.md` or a sidecar file, depending on your IDE.

For repos that need to stay **IDE-neutral** (used across Cursor, Claude Code, Windsurf, etc. by different people), follow **Path B** in `AGENTS_skills.md` — skills stay portable under `.skills/` without committing to a single tool's config files.

## How it works

| Role | What it does | Implemented by |
|------|-------------|----------------|
| **User** | Sets goals, chooses the IDE, resolves conflicts | The human |
| **Agent** | Reads the index, loads skills on demand, manages files | The AI in your IDE |
| **Index** | Routes — declares what skills exist and when to trigger them | `.skills/_index.md` |
| **Skills** | Execute — step-by-step instructions for a specific task | `.skills/_skills/<name>/SKILL.md` |

The agent reads the index at the start of non-trivial work. When a task matches a skill's triggers, the agent loads that `SKILL.md` — never preemptively. If a skill lists dependencies, those are loaded first. Skills cannot override user intent or agent core behavior; they only provide domain-specific procedures.

## Supported tools

| Environment | Template |
|-------------|----------|
| Cursor | [CURSOR_template.md](.skills/_harness/CURSOR_template.md) |
| Codex | [CODEX_template.md](.skills/_harness/CODEX_template.md) |
| GitHub Copilot | [COPILOT_template.md](.skills/_harness/COPILOT_template.md) |
| Claude Code | [CLAUDE_template.md](.skills/_harness/CLAUDE_template.md) |
| Cline | [CLINE_template.md](.skills/_harness/CLINE_template.md) |
| Windsurf | [WINDSURF_template.md](.skills/_harness/WINDSURF_template.md) |
| Gemini CLI | [GEMINI_template.md](.skills/_harness/GEMINI_template.md) |
| Roo Code | [ROO_template.md](.skills/_harness/ROO_template.md) |
| OpenCode | [OPENCODE_template.md](.skills/_harness/OPENCODE_template.md) |
| Other / paste-only | [GENERIC_template.md](.skills/_harness/GENERIC_template.md) |

## Skill format

Each `SKILL.md` opens with YAML frontmatter. See [skill-template](.skills/_skills/skill-template/SKILL.md) for a complete example.

| Field | Required by | Purpose |
|-------|-------------|---------|
| `name` | agentskills.io + harness | Must match directory name (kebab-case, 1–64 chars) |
| `description` | agentskills.io + harness | One sentence for index and IDE matching (1–1024 chars) |
| `triggers` | harness only | Phrases that should cause this skill to load |
| `dependencies` | harness only | Other skill names to load first (`[]` if none) |
| `version` | harness only | Semver string (e.g. `1.0.0`) |

`name` and `description` follow the [agentskills.io specification](https://agentskills.io/specification) and are used by IDEs with native skill discovery. The harness adds `triggers`, `dependencies`, and `version`; IDEs that don't recognize them silently ignore them.

## Native IDE discovery

Most IDEs auto-discover skills from standard directories. After setup, run the symlink helper to enable native features (`@skill-name` mentions, auto-invocation, skill panels):

```bash
# Most IDEs (Cursor, Codex, Copilot, Windsurf, Gemini CLI, Roo Code, OpenCode)
.skills/_harness/link.sh .agents/skills

# Claude Code and Cline
.skills/_harness/link.sh .claude/skills
```

Symlinks point from the cross-agent discovery path back to `.skills/_skills/`. Add the target directory to `.gitignore` — symlinks are machine-local, not committed.

The harness index and native discovery work side by side: native gives IDE integration, the index gives trigger keywords and dependency chains.

### Swapping IDEs

Skills stay in `.skills/_skills/` regardless of IDE. To switch:

1. Follow the new IDE's template to install harness rules.
2. Run `link.sh` with the appropriate target if not already done.
3. `.agents/skills/` and `.claude/skills/` symlinks can coexist.

For upgrading from an older harness version, use the bundled **harness-upgrade** skill.

## Adding a skill

1. Copy [skill-template](.skills/_skills/skill-template/SKILL.md) to `.skills/_skills/<name>/SKILL.md` and edit.
2. Add a row to [`.skills/_index.md`](.skills/_index.md).
3. Re-run `.skills/_harness/link.sh` if native discovery symlinks are set up.
4. For the full checklist, load the **skill-author** skill.

## Updating the kit

Merge or replace `.skills/_harness/` and bundled skills from upstream. Keep your custom skills under `.skills/_skills/` and your index rows. See the **harness-upgrade** skill for guided migration.

For repos that vendor the entire kit via `git subtree pull` (see **Deploying as a git subtree** below), updates are a single command and the **harness-subtree** skill walks through the post-pull reconcile.

## Deploying as a git subtree

Manual file-copy installs work, but `git subtree` is the recommended way to vendor `skills-harness` into a consumer repo when you want **traceable, single-command updates** and **no submodule fragility**. The full procedure (and post-pull reconcile) is documented in the bundled **harness-subtree** skill — load it with a phrase like *"vendor skills-harness as a subtree"*. The summary:

### Layout

The kit is vendored as-is into `.skills-harness/`. The consumer's runtime tree under `.skills/` stays in place and uses **symlinks** to point its kit-managed pieces at the vendored copy:

```text
<consumer-repo>/
├── .skills-harness/        ← vendored kit (subtree; do not hand-edit)
│   └── .skills/{_harness,_skills,_index.md,_meta.yml}
├── .skills/
│   ├── _harness            → symlink → ../.skills-harness/.skills/_harness
│   ├── _skills/
│   │   ├── <kit-skill>     → symlinks → ../../.skills-harness/.skills/_skills/<name>
│   │   └── <prefix>-<own>/ ← real consumer-owned skill dirs
│   ├── _index.md           ← consumer-owned (kit rows + own rows)
│   └── _meta.yml           ← consumer-owned, mirrors vendored kit_version
└── AGENTS.md               ← Path A harness or Path B policy
```

This keeps the kit pieces overwritable on every pull while consumer-authored skills, the index, and the local `_meta.yml` stay independent.

### One-time install

```bash
git remote add skills-harness https://github.com/Gargoyle-Apps/skills-harness
git fetch skills-harness
git subtree add --prefix=.skills-harness skills-harness main --squash
```

Then create the symlinked `.skills/` shell, copy `.skills-harness/AGENTS_skills.md` to repo root, complete bootstrap (Path A or B), delete the bootstrap file, and run `.skills/_harness/check.sh`. The **harness-subtree** skill has the exact commands.

### Updating

```bash
git fetch skills-harness
git subtree pull --prefix=.skills-harness skills-harness main --squash
```

Read `.skills-harness/CHANGELOG.md` for the diff, refresh kit-skill symlinks (idempotent loop in **harness-subtree**), reconcile any new rows into your `.skills/_index.md`, bump `.skills/_meta.yml` `kit_version`, and re-run `check.sh`.

### Migrating an existing manual install

If a repo already has `.skills/` from a file-copy install and you want to switch to subtree updates, run `.skills/_harness/migrate-to-subtree.sh` (dry-run by default; `--apply` to perform). It vendors the subtree, replaces kit-owned pieces with symlinks, and — unless `--reconcile` is also passed — **never touches consumer-authored skills, the index, or `_meta.yml`**. It also audits consumer skills against the prefix convention (per **skill-author**) and required frontmatter fields, and prints rename/patch suggestions for you to apply manually.

Pass `--reconcile` (and optionally `--symlink-consumer-skills`) to fold the post-migration index/`_meta.yml` reconcile and consumer-skill shim creation into the same run. Full procedure (including drift handling with `--accept-upstream <name>` or `--force`) lives in **harness-subtree**.

**Bootstrapping on a stale install** (pre-0.6.0 doesn't ship the script):

```bash
curl -sSLo .skills/_harness/migrate-to-subtree.sh \
  https://raw.githubusercontent.com/Gargoyle-Apps/skills-harness/main/.skills/_harness/migrate-to-subtree.sh
chmod +x .skills/_harness/migrate-to-subtree.sh
.skills/_harness/migrate-to-subtree.sh        # dry-run first
```

Swap `main` for a release tag (e.g. `v1.0.0`) for a reproducible install. The script ignores its own untracked status and any `*.bak/` directories during the dirty-tree check, so running it from `.skills/_harness/` is fine.

### Pinning

Pin to a specific kit release with `git subtree add/pull --prefix=.skills-harness skills-harness <tag-or-sha> --squash`. Kit tags follow the semver in **`.skills/_meta.yml`** and root **`CHANGELOG.md`** — which is exactly why the next two sections matter so much for subtree consumers.

### Why versioning matters more under subtree

Because the kit can be updated mid-project with a single command, **per-skill `version` fields and the kit `CHANGELOG.md` are the contract** between this repo and every vendored consumer:

- A bumped kit-bundled skill `version` signals consumers that behaviour they previously relied on may have changed.
- The kit-level semver in `.skills/_meta.yml` and the top entry in `CHANGELOG.md` are what consumers diff against their pinned version.
- `kit-release` (this repo) and `harness-subtree` / `harness-upgrade` (consumer side) are the two halves of that contract.

## Validation

Run `.skills/_harness/check.sh` to verify index/directory consistency, frontmatter, template sync, and native-discovery symlink completeness (when `.agents/skills/` or `.claude/skills/` exist). After adding kit skills or a subtree pull, run **`check.sh --link`** to sync those dirs via `link.sh`, then validate.

The kit-version surface checks (CHANGELOG/README/AGENTS_skills.md must agree on `kit_version`) only make sense in this upstream repo. **Consumer repos auto-skip them** when either `.skills-harness/` exists at the repo root (subtree install) or `.skills/_meta.yml` declares `role: consumer`. Override with `SKILLS_CHECK_KIT_SURFACES=1` (force checks) or `SKILLS_CHECK_KIT_SURFACES=0` (suppress) when the auto-detect gets it wrong. See [CONTRIBUTING.md — Environment overrides](CONTRIBUTING.md#environment-overrides) for the full list.

## Optional: MCP

For progressive skill loading via MCP, see [skillport](https://github.com/gotalab/skillport). This kit does not ship a server.

## Kit version

**Current release:** `1.1.2`

- **Canonical:** [`kit_version` in `.skills/_meta.yml`](.skills/_meta.yml)
- **History:** [CHANGELOG.md](CHANGELOG.md)
- **Bootstrap:** [`AGENTS_skills.md`](AGENTS_skills.md) shows the same release for agents during setup

When bumping the kit in this repository, load the **kit-release** skill and update the changelog, `_meta.yml`, this section, and `AGENTS_skills.md` together, then run `.skills/_harness/check.sh`. See [CONTRIBUTING.md — Versioning](CONTRIBUTING.md#versioning).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

See [LICENSE](LICENSE).
