---
name: skill-author
description: "How to write a new SKILL.md from scratch and register it in the index."
triggers:
  - write a skill
  - author a skill
  - new skill
  - add a skill
dependencies:
  - skill-template
version: "1.5.3"
---

# Skill Author

## Prerequisites

Skill authoring must not be blocked after the temporary bootstrap file is removed.

1. **If `AGENTS_skills.md` exists** at the repository root — bootstrap is **not** finished. Do not follow these steps until **`AGENTS_skills.md`** Path A or Path B is completed and that file is removed (see **`AGENTS_skills.md`**).

2. **If `AGENTS_skills.md` does not exist** — the repo has finished bootstrap. Proceed **unless** the project’s own docs forbid it: check root **`AGENTS.md`**, **README**, or **CONTRIBUTING** for a Path B “skills / authoring” policy or any project-specific gate. Path B repos usually record policy in **`AGENTS.md`** so agents still see the rules without relying on a deleted bootstrap file.

Do **not** treat “`AGENTS_skills.md` missing” as an error — it is expected after setup. Rely on **`AGENTS_skills.md`** only while it is present.

Load `skill-template` first if you need the canonical layout and refactor notes.

## Naming convention

Skills authored in a **consumer repo** (any repository that has installed this kit) **must** be prefixed with the consumer repo's initials, followed by `-`. Skills shipped as part of the **skills-harness kit itself** (the upstream repo, directory named `skills-harness`) are **unprefixed**.

**Deriving the prefix from the repo's root directory name:**

- Split on `-`, `_`, and whitespace (consecutive separators are collapsed)
- Take the first letter of each non-empty segment, lowercase
- Append `-`

Examples:

| Repo directory      | Prefix   |
|---------------------|----------|
| `ux-package-management` | `uxpm-` |
| `eng-package-management` | `epm-` |
| `git-minder`        | `gm-`    |
| `warehouse`         | `w-`     |
| `ware_house`        | `wh-`    |
| `Media Library`     | `ml-`    |
| `skills-harness`    | *(none — kit itself)* |

**Why:** When the kit is installed into a consumer repo, prefixes make it obvious which skills came from the kit vs. were added by the consumer, and avoid name collisions across repos that happen to share initials with the kit (`skills-harness` and `so-high` would both yield `sh-`, so the kit deliberately stays unprefixed).

**How to apply:** Before creating `.skills/_skills/<name>/`, derive the prefix from the current repo's root directory name and prepend it to `<name>`. The frontmatter `name` field and the index row use the prefixed form. Renames of pre-existing unprefixed consumer skills are out of scope unless the user asks.

### Multiple prefixes (per-repo override)

Some consumer repos host **multiple distinct skill families** that should be namespaced separately — e.g. a build-pipeline repo with a `bld-` family for build steps and a `bin-` family for binary-publishing steps. The single auto-derived prefix is too coarse for those repos.

To support this, a consumer repo may **declare an explicit list of allowed prefixes** in **`.skills/_meta.yml`**:

```yaml
kit_version: "1.0.0"
repo_url: "https://github.com/example/build-tools"
prefixes:
  - bld-
  - bin-
```

Rules when `prefixes:` is present:

- Every consumer-authored skill **must** start with one of the listed prefixes. Choose the prefix that matches the family the skill belongs to.
- The auto-derived single prefix is **not** required and **not** preferred — the explicit list is the source of truth.
- Each prefix entry must end with `-` and contain only lowercase alphanumerics and hyphens (same character set as `name`).
- Kit-bundled skills (`skill-author`, `harness-subtree`, `kit-release`, etc.) remain **unprefixed** regardless of what the consumer declares; the list applies only to consumer-authored skills.

Rules when `prefixes:` is absent (default / single-family repos):

- Use the single auto-derived prefix from the repo directory name (rules in the section above).
- This is the right choice for the vast majority of repos. Only declare `prefixes:` when one prefix genuinely cannot describe the families in the repo.

**Overriding the auto-derived prefix on a single-family repo:** if the auto-derivation gives the wrong answer for your repo (e.g. you want `ml-` but the dir name `media` derives `m-`, or you've informally settled on a different prefix), declare a single-entry list:

```yaml
prefixes:
  - ml-
```

That makes the override explicit and machine-readable for the audit, instead of relying on contributors to remember the unwritten convention.

**Authoring against a multi-prefix repo:** before creating a new skill, read `.skills/_meta.yml`. If `prefixes:` is present, ask the user (or pick from context) which family the new skill belongs to and use that prefix. If absent, derive the single prefix as before. The bundled `migrate-to-subtree.sh` audit reads the same list and accepts any of the declared prefixes.

## Steps

1. Create directory: `.skills/_skills/<prefix><name>/` (see **Naming convention** above; the kit itself uses no prefix)
2. Copy `.skills/_skills/skill-template/SKILL.md` as your starting point
3. Fill in frontmatter — `name` must match directory name exactly (including any prefix)
4. Write the body as agent-facing instructions, not human documentation
5. Choose triggers carefully — these are what cause the skill to be loaded
6. Run `.skills/_harness/build-index.sh --write` to regenerate `.skills/_index.md` from frontmatter — the index is the source of truth at runtime and must always be in sync with `.skills/_skills/`
7. If this skill depends on another, list it in `dependencies`
8. If native discovery symlinks are configured, re-run `.skills/_harness/link.sh` with the appropriate target (e.g. `.agents/skills`), or `.skills/_harness/check.sh --link` to sync all existing native dirs and validate
9. Run `.skills/_harness/check.sh` to validate index and frontmatter consistency (if your environment supports script execution)

## Renaming or deleting a skill

When renaming or removing an existing skill, update `.skills/_index.md` in the same operation:

- **Rename:** update the directory name, the frontmatter `name` field, and the index row together.
- **Delete:** remove the directory and its index row together.

Never leave the index out of sync with the skills directory.

## Frontmatter checklist

- [ ] `name` matches directory name
- [ ] `description` is one sentence, suitable for an index
- [ ] `triggers` covers the natural language phrases that should invoke this skill
- [ ] `dependencies` is present (empty list `[]` if none)
- [ ] `version` is set

## Body structure

Use these sections as needed — not all are required:

- **When to use this skill** — conditions for loading
- **Instructions** — step-by-step agent directions
- **Examples** — concrete usage examples
- **Notes** — edge cases, caveats, or references

## What makes a good trigger

Triggers should match how a user would naturally ask for the task, not internal
jargon. Prefer phrases over single words. Think about what someone would type
before they knew this skill existed.

## Circular dependencies

Avoid cycles in `dependencies`. If you detect a cycle, load skills in alphabetical order by `name` and stop after one full pass — then tell the user to fix the dependency graph.
