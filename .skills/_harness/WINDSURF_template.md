<!-- SETUP — remove this entire section after setup is complete -->

## Setup instructions (Windsurf)

1. Copy the **Skills Harness** section below (from `# Skills Harness` through **Rules**) into a new file at the repository root named `.windsurfrules`, **or** append to an existing `.windsurfrules` under a `## Skills Harness` heading.
2. Delete this SETUP block from `.windsurfrules` when done.
3. **Project `AGENTS.md`:** append a pointer to `.windsurfrules`. If `AGENTS.md` does not exist, create it with the block below. If it already exists, **append** the pointer under a `## Skills Harness` heading — do not erase existing content.

```markdown
## Skills Harness

Skills: see [.windsurfrules](./.windsurfrules).
```

4. **Native discovery:** run `.skills/_harness/link.sh .agents/skills` from the repo root. Add `.agents/skills/` to `.gitignore` if not already present. After linking, skills appear in Windsurf's built-in skill panel and support `@skill-name` invocation.
5. Delete **`AGENTS_skills.md`** from the repository root.

**Verify:** `.windsurfrules` contains the Skills Harness section; `AGENTS.md` has the pointer; `.agents/skills/` contains symlinks to `.skills/_skills/`; this SETUP block is gone; `AGENTS_skills.md` is removed.

<!-- END SETUP -->

---

# Skills Harness

Skills are in `.skills/_skills/`. The index is at `.skills/_index.md`.

## Rules

- Read `.skills/_index.md` at the start of any non-trivial task.
- Load a skill's full `SKILL.md` only when the task matches its triggers in the index.
- Never load skills preemptively.
- If a skill lists `dependencies`, load those skills before proceeding.
- **`.skills/_index.md` is the source of truth.** When you create, rename, or delete a skill, update the index in the same operation. Never leave the index out of sync with `.skills/_skills/`.
- If `.skills/` is missing from the repo, warn the user and do not invent skill content.
- **Subtree-vendored installs:** if `.skills-harness/` exists at the repo root, the kit is vendored as a git subtree — treat files under `.skills-harness/` as upstream-owned (do not hand-edit; updates come via `git subtree pull`) and use the **harness-subtree** skill for install/update/reconcile work.
- **Temporary bootstrap only:** While `AGENTS_skills.md` exists at the repository root (skills-harness bootstrap not finished), do not create or refactor skills or change `.skills/_index.md` for new skills — complete Path A or B in that file. Once it is removed, this rule does not apply. Path B repos may record ongoing policy in root `AGENTS.md` instead.
