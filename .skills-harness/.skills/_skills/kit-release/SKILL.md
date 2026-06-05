---
name: kit-release
description: "Bump the skills-harness kit semver and keep CHANGELOG, README, AGENTS_skills.md, and _meta.yml in sync."
triggers:
  - bump kit version
  - bump harness version
  - release skills harness
  - cut a harness release
  - skills-harness version
  - kit release
dependencies: []
version: "1.1.0"
---

# Kit release

## When to use

Working on the **skills-harness** upstream repository (or a maintained fork) when shipping a new **kit** semver. This is not for bumping `version` inside individual `SKILL.md` files unless you also document that in the changelog.

## Steps

1. Choose the new semver (patch, minor, or major) per [Semantic Versioning](https://semver.org/).

2. **`CHANGELOG.md`** — Add `## [x.y.z] - YYYY-MM-DD` immediately after the Keep a Changelog intro (above prior releases). Fill **Added** / **Changed** / **Fixed** as appropriate ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/)).

3. **`.skills/_meta.yml`** — Set `kit_version` to the same `x.y.z` (quoted string).

4. **`README.md`** — Under **Kit version**, set the line **Current release:** `` `x.y.z` `` exactly (backticks, no extra spaces). This must match `_meta.yml`.

5. **`AGENTS_skills.md`** — Set **Kit version:** `` `x.y.z` `` on the dedicated line below the main heading (same pattern as the previous release).

6. **`.skills/_index.md`** — If any prose mentions a numeric kit version, update it; otherwise the index may keep pointing at `_meta.yml` only.

7. Run **`.skills/_harness/check.sh`** from the repo root. It confirms `kit_version`, the newest `CHANGELOG` release heading, **README**, and **AGENTS_skills.md** all agree.

8. If the release changes skill behaviour or adds skills, bump the affected per-skill `version` fields in frontmatter and mention them under the changelog entry.

## Notes

- Downstream projects that copy only part of the kit may omit `CHANGELOG.md` or customize `README.md`; the release check applies to the full canonical tree.
- For per-skill authoring and index registration, use **skill-author** and [CONTRIBUTING.md](CONTRIBUTING.md).
- **Subtree consumers depend on this release contract.** Repos that vendor the kit via `git subtree` (see **harness-subtree**) update by pulling whatever is on `main` (or a pinned tag). They diff their pinned `kit_version` against the new top entry of `CHANGELOG.md` to decide whether the upgrade is safe. Therefore: every release **must** land in `CHANGELOG.md` with accurate Added/Changed/Fixed sections, and any kit-bundled skill whose behaviour changed **must** have its per-skill `version` bumped — that bump is the signal subtree consumers see when they reconcile their `.skills/_index.md`.
- **Tagging:** if the upstream repo uses git tags for releases, create the tag (`git tag vX.Y.Z`) and push it (`git push origin vX.Y.Z`) so subtree consumers can pin with `git subtree pull --prefix=.skills-harness skills-harness vX.Y.Z --squash`.
