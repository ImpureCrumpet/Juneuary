<!-- SETUP — remove this entire section after setup is complete -->

## Setup instructions (any other tool / paste-only)

1. Open your tool's **system**, **project**, or **custom instructions** field (or a pinned note the agent always reads).
2. Paste the **Skills Harness** section below (from `# Skills Harness` through **Rules**) into that field.
3. Delete this SETUP block from what you paste — only the harness content should remain in the tool.
4. **Project `AGENTS.md` (optional):** if you use one, **append** a pointer under a `## Skills Harness` heading: `Skills: see .skills/_harness/GENERIC_template.md` (after stripping SETUP there). Do not overwrite existing instructions.
5. Delete **`AGENTS_skills.md`** from the repository root.

**Limitation:** with paste-only setup there is no automatic progressive loading; keep `.skills/_index.md` small. For MCP-based progressive loading, see the README **Optional: MCP** section.

**Native discovery:** if your tool supports skill auto-discovery from `.agents/skills/` or `.claude/skills/`, you can also run `.skills/_harness/link.sh .agents/skills` (or `.claude/skills`) to enable it alongside the paste-based harness.

**Verify:** harness is pasted into your tool; `AGENTS_skills.md` is removed.

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
