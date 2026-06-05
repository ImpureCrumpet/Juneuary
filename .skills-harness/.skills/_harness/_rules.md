# Rules

- Read `.skills/_index.md` at the start of any non-trivial task.
- Load a skill's full `SKILL.md` only when the task matches its triggers in the index.
- Never load skills preemptively.
- If a skill lists `dependencies`, load those skills before proceeding.
- **`.skills/_index.md` is the source of truth.** When you create, rename, or delete a skill, update the index in the same operation. Never leave the index out of sync with `.skills/_skills/`.
- If `.skills/` is missing from the repo, warn the user and do not invent skill content.
- **Subtree-vendored installs:** if `.skills-harness/` exists at the repo root, the kit is vendored as a git subtree — treat files under `.skills-harness/` as upstream-owned (do not hand-edit; updates come via `git subtree pull`) and use the **harness-subtree** skill for install/update/reconcile work.
- **Temporary bootstrap only:** While `AGENTS_skills.md` exists at the repository root (skills-harness bootstrap not finished), do not create or refactor skills or change `.skills/_index.md` for new skills — complete Path A or B in that file. Once it is removed, this rule does not apply. Path B repos may record ongoing policy in root `AGENTS.md` instead.
