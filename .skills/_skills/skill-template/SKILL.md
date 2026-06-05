---
name: skill-template
description: "Canonical SKILL.md format with authoring notes and refactor guide."
triggers:
  - new skill
  - skill format
  - create skill
  - reformat skill
  - convert rule
dependencies: []
version: "1.1.0"
---

# Skill Template

Use this as a starting point for any new skill.
Copy this file to `.skills/_skills/<your-skill-name>/SKILL.md` and fill it in.

## When to use this skill

Load when the user needs the canonical skill layout, is creating a new skill, or is converting an existing rule or doc into the standard format.

## Instructions

1. Copy this file to `.skills/_skills/<name>/SKILL.md`.
2. Set `name` to match the directory name exactly — kebab-case, 1–64 characters, lowercase alphanumeric and hyphens only, no leading/trailing/consecutive hyphens ([agentskills.io](https://agentskills.io/specification) `name` rules).
3. Write `description` as one sentence, 1–1024 characters — used by the harness index and native IDE skill matching ([agentskills.io](https://agentskills.io/specification) `description` rules).
4. List natural-language `triggers` users might say.
5. Fill **When to use**, **Instructions**, and **Examples** for the agent.

## Examples

- "Add a skill for our deploy checklist" → use this template, then register in `.skills/_index.md`.

---

<!--
REFACTOR GUIDE

Use this section when converting an existing file (Cursor rule, plain markdown
instructions, AGENTS.md section, etc.) into a standard SKILL.md.

Steps:
1. Identify the core capability the existing file describes
2. Extract it into a new directory: .skills/_skills/<name>/SKILL.md
3. Add YAML frontmatter (name, description, triggers, dependencies, version)
4. Rewrite the body as agent-facing instructions (not human docs)
5. Add a row to .skills/_index.md
6. Remove or replace the original content with a one-liner pointing to the skill

Common sources to refactor:
- Cursor .mdc rules → extract procedural ones as skills, keep declarative ones as rules
- AGENTS.md sections → any multi-step workflow becomes a skill
- Inline comments or README instructions → if an agent needs to follow them, they're a skill

What stays in AGENTS.md / harness files (not skills):
- Project-level conventions (naming, structure)
- Always-on constraints
- Pointers to the index

What becomes a skill:
- Any multi-step workflow
- Domain-specific knowledge (how to use a particular tool or API)
- Anything the agent should only load when relevant
-->
