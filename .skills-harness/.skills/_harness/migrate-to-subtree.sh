#!/usr/bin/env bash
set -euo pipefail

# migrate-to-subtree.sh
# Migrate an existing manual skills-harness install (file-copy or earlier kit
# version) to a git-subtree install at .skills-harness/. Safe by default:
#
#   * Reports planned actions; never destroys consumer-authored skills.
#   * Audits drift in kit-owned files (scripts, _rules.md, bundled skills),
#     consumer-skill prefix convention (per skill-author), and consumer-skill
#     frontmatter required fields.
#   * --apply flag actually performs reversible migrations:
#       - Adds the subtree at .skills-harness/ (one squash commit).
#       - Backs up the old .skills/_harness/ to .skills/_harness.bak/ and
#         replaces it with a symlink into the subtree.
#       - For each upstream-bundled kit skill: backs up the local copy to
#         .skills/_skills/<name>.bak/ and replaces with a symlink into the
#         subtree. Skips this replacement if the local copy has uncommitted
#         changes vs. the upstream copy AND --force is not set; reports the
#         drift instead so a human can review.
#       - Never touches consumer-authored skills.
#       - Touches .skills/_index.md and .skills/_meta.yml only when --reconcile
#         is also passed (and only kit-skill rows + kit_version/repo_url —
#         consumer rows and other fields stay put). See --reconcile below.
#
# Optional modes (each opt-in, each respects --apply gating):
#   --reconcile                Merge upstream kit-skill rows into local
#                              .skills/_index.md (kit names only — consumer
#                              rows untouched) and bump .skills/_meta.yml
#                              kit_version/repo_url to match the subtree.
#                              Use after a `git subtree pull` to finish the
#                              update without hand-editing.
#   --symlink-consumer-skills  Walk the path declared in `consumer_skills_dir:`
#                              (e.g. `.cursor/skills`) and create
#                              .skills/_skills/<name> -> ../../<csd>/<name>
#                              symlinks for each entry. Idempotent. Skips kit
#                              skills and any pre-existing real directories.
#   --skip-subtree             For already-vendored installs: skip the subtree
#                              add and kit-skill replacement; useful with
#                              --reconcile / --symlink-consumer-skills only.
#
# Compatibility: bash 3.2 (macOS /bin/bash), POSIX find/diff/git, no GNU-isms.
#
# Usage:
#   .skills/_harness/migrate-to-subtree.sh [--apply] [--force] \
#       [--remote-name <name>] [--remote-url <url>] [--ref <ref>] \
#       [--prefix <dir>] [--accept-upstream <name>[,<name>…]] \
#       [--reconcile] [--symlink-consumer-skills] [--skip-subtree]
#
# Defaults:
#   remote-name = skills-harness
#   remote-url  = repo_url from .skills/_meta.yml (required if not present)
#   ref         = main
#   prefix      = .skills-harness

CANONICAL_URL_SUBSTR="Gargoyle-Apps/skills-harness"

APPLY=false
FORCE=false
REMOTE_NAME="skills-harness"
REMOTE_URL=""
REF="main"
PREFIX=".skills-harness"
ACCEPT_UPSTREAM=""    # comma-separated names whose drift should be overwritten with upstream
ACCEPT_DERIVED_URL=false
RECONCILE=false               # gh issue #3, friction point 7
SYMLINK_CONSUMER_SKILLS=false # gh issue #3, friction point 8
SKIP_SUBTREE=false            # for --reconcile-only / --symlink-only on already-vendored installs

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=true ;;
    --force) FORCE=true ;;
    --remote-name) REMOTE_NAME="$2"; shift ;;
    --remote-url) REMOTE_URL="$2"; shift ;;
    --ref) REF="$2"; shift ;;
    --prefix) PREFIX="$2"; shift ;;
    --accept-upstream) ACCEPT_UPSTREAM="$2"; shift ;;
    --accept-derived-url) ACCEPT_DERIVED_URL=true ;;
    --reconcile) RECONCILE=true ;;
    --symlink-consumer-skills) SYMLINK_CONSUMER_SKILLS=true ;;
    --skip-subtree) SKIP_SUBTREE=true ;;
    -h|--help)
      sed -n '3,55p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "ERROR: unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

# Symlink-safe: derive paths from the script's invocation path without following
# symlinks (relevant after migration when .skills/_harness/ is a symlink into
# .skills-harness/.skills/_harness/). See gh issue #3, friction point 5.
script_src="${BASH_SOURCE[0]:-$0}"
script_dir="$(dirname "$script_src")"
HARNESS_DIR="${SKILLS_HARNESS_DIR:-$(cd "$script_dir" && pwd -L)}"
SKILLS_DIR="${SKILLS_DIR:-$(dirname "$HARNESS_DIR")/_skills}"
REPO_ROOT="${SKILLS_REPO_ROOT:-$(dirname "$(dirname "$HARNESS_DIR")")}"
META_FILE="$(dirname "$HARNESS_DIR")/_meta.yml"

cd "$REPO_ROOT"

trim() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

note() { printf '%s\n' "$*"; }
plan() { printf '  PLAN  %s\n' "$*"; }
do_  () { printf '  DO    %s\n' "$*"; }
warn () { printf '  WARN  %s\n' "$*" >&2; }
err  () { printf '  ERROR %s\n' "$*" >&2; ((++ERRORS)) || true; }

ERRORS=0

# --- Preconditions ---

if [[ ! -d ".git" ]]; then
  echo "ERROR: must be run from a git repository root (no .git/ here)." >&2
  exit 1
fi
if [[ ! -d ".skills" ]]; then
  echo "ERROR: no .skills/ directory found. There is nothing to migrate." >&2
  exit 1
fi
if [[ -e "$PREFIX" ]] && ! $SKIP_SUBTREE; then
  echo "ERROR: $PREFIX already exists. Either you already migrated, or pass --prefix." >&2
  echo "If the kit is already vendored and you only want --reconcile or --symlink-consumer-skills," >&2
  echo "re-run with --skip-subtree." >&2
  exit 1
fi
if $APPLY; then
  # Filter the dirty-tree check so the user can drop this script directly into
  # .skills/_harness/migrate-to-subtree.sh and run from there. We ignore the
  # script itself plus any *.bak directories (which can only exist mid-migration).
  # See gh issue #3, friction point 2.
  script_basename="$(basename "$script_src")"
  dirty="$(git status --porcelain 2>/dev/null \
    | grep -v -E "(^|/)${script_basename}\$" \
    | grep -v -E '\.bak/?$' \
    || true)"
  if [[ -n "$dirty" ]]; then
    echo "ERROR: working tree has uncommitted changes (other than the script itself):" >&2
    echo "$dirty" >&2
    echo "Commit or stash before --apply." >&2
    exit 1
  fi
fi

REMOTE_URL_SOURCE="explicit --remote-url"
if [[ -z "$REMOTE_URL" && -f "$META_FILE" ]]; then
  raw="$(grep -E '^repo_url:' "$META_FILE" | head -1 | sed 's/^repo_url://' || true)"
  raw="$(trim "$raw")"
  raw="${raw#\"}"; raw="${raw%\"}"
  REMOTE_URL="$raw"
  REMOTE_URL_SOURCE="derived from .skills/_meta.yml repo_url"
fi
if [[ -z "$REMOTE_URL" ]]; then
  echo "ERROR: no upstream URL. Pass --remote-url or set repo_url in .skills/_meta.yml." >&2
  exit 1
fi

# Stale-install safety: if repo_url was derived from _meta.yml AND it doesn't
# point at the canonical Gargoyle-Apps/skills-harness, the consumer probably
# has a stale install pointing at an old fork. Refuse unless the user
# explicitly accepts. See gh issue #3, friction point 3.
if [[ "$REMOTE_URL_SOURCE" != "explicit --remote-url" ]]; then
  if [[ "$REMOTE_URL" != *"$CANONICAL_URL_SUBSTR"* ]] && ! $ACCEPT_DERIVED_URL; then
    echo "ERROR: derived repo_url does not look like the canonical kit upstream." >&2
    echo "  derived  : $REMOTE_URL ($REMOTE_URL_SOURCE)" >&2
    echo "  expected : a URL containing '$CANONICAL_URL_SUBSTR'" >&2
    echo "" >&2
    echo "This is the EXPECTED situation when migrating a legacy manual install" >&2
    echo "whose .skills/_meta.yml was copied from an old fork or pre-rename" >&2
    echo "repo (e.g. gotalab/skills-harness, which is no longer reachable)." >&2
    echo "" >&2
    echo "Almost always, the right fix is to vendor the canonical upstream:" >&2
    echo "" >&2
    echo "  $0 \\" >&2
    echo "    --remote-url https://github.com/Gargoyle-Apps/skills-harness \\" >&2
    echo "    [--apply] [--reconcile] [--symlink-consumer-skills]" >&2
    echo "" >&2
    echo "  After --apply, --reconcile rewrites .skills/_meta.yml so repo_url" >&2
    echo "  and kit_version match the vendored subtree. No manual edit needed." >&2
    echo "" >&2
    echo "Use --accept-derived-url ONLY if you have deliberately maintained a" >&2
    echo "private fork at the URL above and you want to vendor that fork. Do" >&2
    echo "NOT use it to silence this error when the listed URL is dead or" >&2
    echo "stale — the subtree add will fail (or worse, vendor the wrong tree)." >&2
    exit 1
  fi
fi

note "skills-harness migrate-to-subtree"
note "  repo root  : $REPO_ROOT"
note "  upstream   : $REMOTE_URL ($REF)"
note "  subtree at : $PREFIX"
note "  mode       : $($APPLY && echo APPLY || echo dry-run)"
note ""

# --- Step 1: add subtree (apply only) -----------------------------------------

SUBTREE_SKILLS=""
add_subtree() {
  if ! git remote get-url "$REMOTE_NAME" >/dev/null 2>&1; then
    do_ "git remote add $REMOTE_NAME $REMOTE_URL"
    git remote add "$REMOTE_NAME" "$REMOTE_URL"
  fi
  do_ "git fetch $REMOTE_NAME"
  git fetch "$REMOTE_NAME" --quiet
  do_ "git subtree add --prefix=$PREFIX $REMOTE_NAME $REF --squash"
  git subtree add --prefix="$PREFIX" "$REMOTE_NAME" "$REF" --squash --message "subtree: vendor skills-harness ($REF)" >/dev/null
}

if $SKIP_SUBTREE; then
  if [[ -d "$PREFIX/.skills/_skills" ]]; then
    SUBTREE_SKILLS="$PREFIX/.skills/_skills"
    note "  --skip-subtree: subtree already vendored at $PREFIX (skipping subtree add)"
  else
    echo "ERROR: --skip-subtree but $PREFIX/.skills/_skills does not exist." >&2
    echo "Run without --skip-subtree to add the subtree first." >&2
    exit 1
  fi
elif $APPLY; then
  add_subtree
  SUBTREE_SKILLS="$PREFIX/.skills/_skills"
else
  plan "git remote add $REMOTE_NAME $REMOTE_URL  (if missing)"
  plan "git fetch $REMOTE_NAME"
  plan "git subtree add --prefix=$PREFIX $REMOTE_NAME $REF --squash"
  note "  (dry-run cannot inspect upstream-bundled kit skills until --apply runs the subtree add;"
  note "   drift checks below use a built-in fallback list of known kit skills)"
  note ""
fi

# --- Step 2: determine the set of upstream-bundled kit skills -----------------

KIT_SKILL_NAMES=""
if [[ -n "$SUBTREE_SKILLS" && -d "$SUBTREE_SKILLS" ]]; then
  for d in "$SUBTREE_SKILLS"/*/; do
    [[ -d "$d" ]] || continue
    KIT_SKILL_NAMES="$KIT_SKILL_NAMES $(basename "$d")"
  done
else
  # Fallback for dry-run: known-bundled kit skills as of 0.6.0+.
  # Update this list when the upstream kit adds or removes bundled skills.
  KIT_SKILL_NAMES="harness-subtree harness-upgrade kit-release skill-author skill-template"
fi

is_kit_skill() {
  local name="$1" k
  for k in $KIT_SKILL_NAMES; do
    [[ "$k" == "$name" ]] && return 0
  done
  return 1
}

# --- Step 3: replace .skills/_harness/ with a symlink into the subtree --------

migrate_harness_dir() {
  local target_rel="../$PREFIX/.skills/_harness"
  local local_dir=".skills/_harness"
  if [[ -L "$local_dir" ]]; then
    note "  ok    .skills/_harness is already a symlink"
    return
  fi
  if [[ ! -d "$local_dir" ]]; then
    plan "create symlink $local_dir -> $target_rel"
    if $APPLY; then ln -s "$target_rel" "$local_dir"; do_ "linked $local_dir"; fi
    return
  fi
  if $APPLY; then
    do_ "backup $local_dir -> $local_dir.bak"
    mv "$local_dir" "$local_dir.bak"
    do_ "ln -s $target_rel $local_dir"
    ln -s "$target_rel" "$local_dir"
  else
    plan "backup .skills/_harness -> .skills/_harness.bak then symlink to $target_rel"
  fi
}

if ! $SKIP_SUBTREE; then
  note "Step: kit-owned harness directory (.skills/_harness/)"
  migrate_harness_dir
  note ""
fi

# --- Step 4: process each kit-bundled skill -----------------------------------

migrate_kit_skill() {
  local name="$1"
  local local_path=".skills/_skills/$name"
  local target_rel="../../$PREFIX/.skills/_skills/$name"

  if [[ -L "$local_path" ]]; then
    note "  ok    $name (already symlink)"
    return
  fi
  if [[ ! -d "$local_path" ]]; then
    plan "create symlink $local_path -> $target_rel"
    if $APPLY; then ln -s "$target_rel" "$local_path"; do_ "linked $local_path"; fi
    return
  fi

  # Per-skill upstream acceptance via --accept-upstream (gh issue #3, friction point 4).
  # Comma-separated list of kit-skill names whose drift should be overwritten with
  # upstream. Cleaner than --force, which sledgehammers every drifted skill.
  accept_this=false
  if [[ -n "$ACCEPT_UPSTREAM" ]]; then
    saved_ifs="$IFS"; IFS=','
    for n in $ACCEPT_UPSTREAM; do
      n="$(trim "$n")"
      [[ "$n" == "$name" ]] && accept_this=true
    done
    IFS="$saved_ifs"
  fi

  # Compare to upstream copy if the subtree exists yet.
  if [[ -n "$SUBTREE_SKILLS" && -d "$SUBTREE_SKILLS/$name" ]]; then
    if diff -r -q "$local_path" "$SUBTREE_SKILLS/$name" >/dev/null 2>&1; then
      if $APPLY; then
        do_ "identical to upstream — backup $local_path -> $local_path.bak, then symlink"
        mv "$local_path" "$local_path.bak"
        ln -s "$target_rel" "$local_path"
      else
        plan "$name is identical to upstream → backup + symlink"
      fi
    else
      if ($FORCE || $accept_this) && $APPLY; then
        reason="$($accept_this && echo "[--accept-upstream]" || echo "[--force]")"
        do_ "$reason backup local-modified $local_path -> $local_path.bak, then symlink"
        mv "$local_path" "$local_path.bak"
        ln -s "$target_rel" "$local_path"
      else
        warn "$name differs from upstream — kept local copy."
        warn "      Review with: diff -ru $local_path $SUBTREE_SKILLS/$name"
        warn "      To accept upstream for this skill only:  --accept-upstream $name --apply"
        warn "      To accept upstream for ALL drifted kit skills:  --force --apply"
      fi
    fi
  else
    plan "$name is bundled by the kit — drift will be checked after --apply runs the subtree add"
  fi
}

if ! $SKIP_SUBTREE; then
  note "Step: kit-bundled skills"
  for name in $KIT_SKILL_NAMES; do
    migrate_kit_skill "$name"
  done
  note ""
fi

# --- Step 4b: --skip-subtree kit-link refresh ---------------------------------
#
# Update-mode (--skip-subtree) doesn't run migrate_kit_skill, so when an
# upstream `git subtree pull` adds a new bundled skill, the consumer's
# .skills/_skills/<new-kit-skill> symlink is never created and check.sh later
# fails. Refresh kit symlinks here:
#   * missing entry → create symlink to the subtree copy
#   * symlink whose target no longer exists in the subtree (e.g. a kit skill
#     was removed/renamed upstream) → remove (with note)
#   * pre-existing real directory → leave alone, surface a hint so the user
#     can re-run the full migration without --skip-subtree if they want it
#     converted to a symlink
# Idempotent: correct symlinks print "ok".

refresh_kit_skill_link() {
  local name="$1"
  local local_path=".skills/_skills/$name"
  local target_rel="../../$PREFIX/.skills/_skills/$name"
  local subtree_path="$PREFIX/.skills/_skills/$name"

  if [[ -L "$local_path" ]]; then
    if [[ -e "$local_path" ]]; then
      note "  ok    $name (symlink resolves)"
    else
      if $APPLY; then
        rm "$local_path"
        do_ "removed dangling symlink $local_path (target no longer in subtree)"
      else
        plan "remove dangling symlink $local_path (target $target_rel missing)"
      fi
    fi
    return
  fi

  if [[ -d "$local_path" ]]; then
    note "  skip  $name is a real directory (re-run without --skip-subtree to convert)"
    return
  fi

  if [[ ! -d "$subtree_path" ]]; then
    warn "kit skill '$name' listed but $subtree_path is missing — skipping"
    return
  fi

  if $APPLY; then
    ln -s "$target_rel" "$local_path"
    do_ "linked $local_path -> $target_rel"
  else
    plan "create symlink $local_path -> $target_rel"
  fi
}

if $SKIP_SUBTREE; then
  note "Step: refresh kit-bundled skill symlinks (update mode)"
  for name in $KIT_SKILL_NAMES; do
    refresh_kit_skill_link "$name"
  done
  note ""
fi

# --- Step 5: audit consumer-authored skills (never modify) --------------------

derive_prefix() {
  # Split repo dir name on '-', '_', and whitespace; take the first letter of
  # each non-empty lowercase segment; append '-'. Whitespace handling fixes
  # gh issue #3, friction point 9 (e.g. "Media Library" → "ml-", not "m-").
  local dir="$1" out="" seg ch
  # Normalize all separators to '-'.
  local norm="$(printf '%s' "$dir" | tr '_ \t' '---')"
  local saved_ifs="$IFS"
  IFS='-'
  for seg in $norm; do
    [[ -z "$seg" ]] && continue
    ch="$(printf '%s' "$seg" | cut -c1 | tr '[:upper:]' '[:lower:]')"
    out="$out$ch"
  done
  IFS="$saved_ifs"
  printf '%s-' "$out"
}

REPO_DIR_NAME="$(basename "$REPO_ROOT")"
DERIVED_PREFIX="$(derive_prefix "$REPO_DIR_NAME")"

# Multi-prefix support: if .skills/_meta.yml declares `prefixes:`, parse it as
# a YAML list and use those instead of the auto-derived single prefix.
# Minimal parser — supports the canonical form documented in skill-author:
#
#   prefixes:
#     - bld-
#     - bin-
#
# Entries may be quoted with single or double quotes. Anything outside that
# shape (flow-style lists, anchors) is not supported; declare prefixes in the
# block-style form above.
DECLARED_PREFIXES=""
if [[ -f "$META_FILE" ]] && grep -q '^prefixes:' "$META_FILE"; then
  in_list=false
  while IFS= read -r line; do
    if [[ "$line" =~ ^prefixes: ]]; then in_list=true; continue; fi
    if $in_list; then
      # Stop at the next top-level key (no leading whitespace, contains a colon)
      if [[ "$line" =~ ^[A-Za-z_] ]]; then break; fi
      # Match indented "- value" entries
      if [[ "$line" =~ ^[[:space:]]*-[[:space:]]*(.*)$ ]]; then
        val="${BASH_REMATCH[1]}"
        val="$(trim "$val")"
        val="${val#\"}"; val="${val%\"}"
        val="${val#\'}"; val="${val%\'}"
        [[ -n "$val" ]] && DECLARED_PREFIXES="$DECLARED_PREFIXES $val"
      fi
    fi
  done < "$META_FILE"
fi

if [[ -n "$DECLARED_PREFIXES" ]]; then
  ALLOWED_PREFIXES="$DECLARED_PREFIXES"
  PREFIX_SOURCE="declared in .skills/_meta.yml"
else
  ALLOWED_PREFIXES=" $DERIVED_PREFIX"
  PREFIX_SOURCE="derived from repo dir name '$REPO_DIR_NAME'"
fi

# Trim leading space for display
ALLOWED_PREFIXES_DISPLAY="$(printf '%s' "$ALLOWED_PREFIXES" | sed 's/^ //; s/ /, /g')"

prefix_match() {
  # Returns 0 if $1 starts with any prefix in $ALLOWED_PREFIXES, else 1.
  local name="$1" p
  for p in $ALLOWED_PREFIXES; do
    [[ "$name" == "$p"* ]] && return 0
  done
  return 1
}

# Optional: consumer_skills_dir hint. When the consumer keeps real skill bodies
# outside .skills/_skills/ (e.g. .cursor/skills/) and uses .skills/_skills/<name>/
# as a thin symlink shim, surface that during the audit so the user knows the
# script won't generate those symlinks (gh issue #3, friction point 8 — auto-
# symlinking from a foreign tree is deferred to a follow-up release).
CONSUMER_SKILLS_DIR=""
if [[ -f "$META_FILE" ]]; then
  raw_csd="$(grep -E '^consumer_skills_dir:' "$META_FILE" | head -1 | sed 's/^consumer_skills_dir://' || true)"
  raw_csd="$(trim "$raw_csd")"
  raw_csd="${raw_csd#\"}"; raw_csd="${raw_csd%\"}"
  raw_csd="${raw_csd#\'}"; raw_csd="${raw_csd%\'}"
  CONSUMER_SKILLS_DIR="$raw_csd"
fi

note "Step: audit consumer-authored skills"
note "  repo dir name    : $REPO_DIR_NAME"
note "  allowed prefixes : $ALLOWED_PREFIXES_DISPLAY  ($PREFIX_SOURCE)"
if [[ -n "$CONSUMER_SKILLS_DIR" ]]; then
  note "  consumer_skills_dir declared in _meta.yml: $CONSUMER_SKILLS_DIR"
  note "    (real skill bodies live there; .skills/_skills/<name>/ should be symlinks pointing at them)"
  if ! $SYMLINK_CONSUMER_SKILLS; then
    note "    Pass --symlink-consumer-skills [--apply] to generate the shims with correct relative depth."
  fi
fi

REQUIRED_FIELDS="name description triggers dependencies version"
prefix_violations=0
frontmatter_violations=0

if [[ -d ".skills/_skills" ]]; then
  for d in .skills/_skills/*/; do
    [[ -d "$d" ]] || continue
    name="$(basename "$d")"
    [[ -L "${d%/}" ]] && continue
    if is_kit_skill "$name"; then continue; fi

    # Prefix audit (multi-prefix aware)
    if ! prefix_match "$name"; then
      if [[ -n "$DECLARED_PREFIXES" ]]; then
        warn "consumer skill '$name' does not start with any declared prefix ($ALLOWED_PREFIXES_DISPLAY)"
        warn "      → choose the family this skill belongs to and rename: <prefix>$name"
        warn "        (also update SKILL.md frontmatter 'name' and .skills/_index.md)"
      else
        warn "consumer skill '$name' is missing prefix '$DERIVED_PREFIX'"
        warn "      → suggested rename: $DERIVED_PREFIX$name (also update SKILL.md frontmatter 'name' and .skills/_index.md)"
      fi
      prefix_violations=$((prefix_violations + 1))
    fi

    # Frontmatter audit
    skill_md="${d}SKILL.md"
    if [[ ! -f "$skill_md" ]]; then
      warn "consumer skill '$name' has no SKILL.md"
      continue
    fi

    in_fm=false; closed=false; seen="|"; fm_name=""
    while IFS= read -r line; do
      if [[ "$line" == "---" ]]; then
        if $in_fm; then closed=true; break; else in_fm=true; continue; fi
      fi
      $in_fm || continue
      key="$(trim "$(printf '%s' "$line" | cut -d: -f1)")"
      for f in $REQUIRED_FIELDS; do
        if [[ "$key" == "$f" ]]; then
          seen="${seen}${f}|"
          [[ "$f" == "name" ]] && fm_name="$(trim "$(printf '%s' "$line" | cut -d: -f2-)")"
        fi
      done
    done < "$skill_md"

    if ! $closed; then
      warn "consumer skill '$name': SKILL.md frontmatter is missing or unterminated"
      frontmatter_violations=$((frontmatter_violations + 1))
      continue
    fi
    for f in $REQUIRED_FIELDS; do
      if [[ "$seen" != *"|${f}|"* ]]; then
        warn "consumer skill '$name': frontmatter missing required field '$f'"
        frontmatter_violations=$((frontmatter_violations + 1))
      fi
    done
    if [[ -n "$fm_name" && "$fm_name" != "$name" ]]; then
      warn "consumer skill '$name': frontmatter name '$fm_name' does not match directory"
      frontmatter_violations=$((frontmatter_violations + 1))
    fi
  done
fi

note ""
note "Audit summary:"
note "  prefix violations      : $prefix_violations"
note "  frontmatter violations : $frontmatter_violations"

# --- Step 6: --reconcile (gh issue #3, friction point 7) ----------------------
#
# Merge upstream kit-skill rows into the consumer's .skills/_index.md and bump
# kit_version + repo_url in .skills/_meta.yml to match the subtree. Strategy:
#   * Index: drop every row whose `name` (first cell) is in the kit-skill set,
#     then append the upstream rows for those names. Consumer rows (those whose
#     name is NOT in the kit-skill set) are passed through verbatim and keep
#     their original position relative to the table header.
#   * _meta.yml: rewrite the kit_version and repo_url lines in place. All other
#     fields (role, prefixes, consumer_skills_dir, custom keys) are preserved.
# Idempotent: running --reconcile twice produces the same output as once.

reconcile_meta() {
  local upstream_meta="$PREFIX/.skills/_meta.yml"
  if [[ ! -f "$upstream_meta" ]]; then
    warn "--reconcile: $upstream_meta not found, skipping _meta.yml bump"
    return 0
  fi
  if [[ ! -f ".skills/_meta.yml" ]]; then
    warn "--reconcile: .skills/_meta.yml not found, skipping bump"
    return 0
  fi
  # `|| true` on each grep keeps `set -euo pipefail` from aborting when an
  # optional key is absent — the append-if-missing logic below depends on
  # being able to observe an empty cur_kv / cur_url.
  local up_kv up_url
  up_kv="$( { grep -E '^kit_version:' "$upstream_meta" || true; } | head -1 | sed 's/^kit_version://')"
  up_kv="$(trim "$up_kv")"
  up_url="$( { grep -E '^repo_url:' "$upstream_meta" || true; } | head -1 | sed 's/^repo_url://')"
  up_url="$(trim "$up_url")"

  local cur_kv cur_url
  cur_kv="$( { grep -E '^kit_version:' .skills/_meta.yml || true; } | head -1 | sed 's/^kit_version://')"
  cur_kv="$(trim "$cur_kv")"
  cur_url="$( { grep -E '^repo_url:' .skills/_meta.yml || true; } | head -1 | sed 's/^repo_url://')"
  cur_url="$(trim "$cur_url")"

  if [[ "$cur_kv" == "$up_kv" && "$cur_url" == "$up_url" ]]; then
    note "  ok    .skills/_meta.yml already matches upstream (kit_version=$up_kv)"
    return 0
  fi

  if ! $APPLY; then
    plan ".skills/_meta.yml: bump kit_version $cur_kv -> $up_kv"
    if [[ "$cur_url" != "$up_url" ]]; then
      plan ".skills/_meta.yml: update repo_url $cur_url -> $up_url"
    fi
    return 0
  fi

  # Use a tmp file + sed to rewrite in place, preserving every other line.
  local tmp
  tmp="$(mktemp)"
  awk -v new_kv="kit_version: $up_kv" -v new_url="repo_url: $up_url" '
    /^kit_version:/ { print new_kv; next }
    /^repo_url:/    { print new_url; next }
    { print }
  ' .skills/_meta.yml > "$tmp"
  # If kit_version/repo_url didn't exist in the file at all, append them.
  grep -q '^kit_version:' "$tmp" || printf 'kit_version: %s\n' "$up_kv" >> "$tmp"
  grep -q '^repo_url:'    "$tmp" || printf 'repo_url: %s\n'    "$up_url" >> "$tmp"
  mv "$tmp" .skills/_meta.yml
  do_ ".skills/_meta.yml updated to kit_version=$up_kv, repo_url=$up_url"
  return 0
}

reconcile_index() {
  local upstream_index="$PREFIX/.skills/_index.md"
  local local_index=".skills/_index.md"
  if [[ ! -f "$upstream_index" ]]; then
    warn "--reconcile: $upstream_index not found, skipping _index.md merge"
    return 0
  fi
  if [[ ! -f "$local_index" ]]; then
    warn "--reconcile: $local_index not found, skipping merge"
    return 0
  fi

  # Build the set of kit-skill names from $KIT_SKILL_NAMES (already populated above).
  is_kit() {
    local n="$1" k
    for k in $KIT_SKILL_NAMES; do
      [[ "$n" == "$k" ]] && return 0
    done
    return 1
  }

  # Walk both files and produce the merged output:
  #   1. Pass through every line of local_index, dropping any data row whose
  #      first cell (after `| `) is in the kit set.
  #   2. After processing, append upstream's kit rows in the order they appear
  #      upstream. (We append rather than insert at original position because
  #      kit rows in a stale local index may not be in canonical order; this
  #      gives a deterministic, idempotent result.)
  local tmp
  tmp="$(mktemp)"
  local in_table_body=false dropped=0 added=0

  while IFS= read -r line; do
    # Detect the table header separator |---|---|---|; everything after it is body
    if [[ "$line" =~ ^\|[[:space:]-]+\| ]]; then
      in_table_body=true
      printf '%s\n' "$line" >> "$tmp"
      continue
    fi

    if $in_table_body && [[ "$line" =~ ^\|[[:space:]]*([a-zA-Z0-9_-]+)[[:space:]]*\| ]]; then
      row_name="${BASH_REMATCH[1]}"
      if is_kit "$row_name"; then
        dropped=$((dropped + 1))
        continue
      fi
    fi

    printf '%s\n' "$line" >> "$tmp"
  done < "$local_index"

  # Now extract kit rows from upstream and append in upstream order.
  local up_kit_rows
  up_kit_rows="$(awk -v kit_set="|$(echo "$KIT_SKILL_NAMES" | tr ' ' '|')|" '
    /^\|[[:space:]-]+\|/ { in_body=1; next }
    in_body && /^\|/ {
      n=$0
      sub(/^\|[[:space:]]*/, "", n)
      sub(/[[:space:]]*\|.*/, "", n)
      if (kit_set ~ "\\|" n "\\|") print
    }
  ' "$upstream_index")"

  if [[ -n "$up_kit_rows" ]]; then
    # If the local file ended without a trailing newline, the table won't be valid;
    # the awk pass above already wrote complete lines so we can safely append.
    while IFS= read -r kr; do
      printf '%s\n' "$kr" >> "$tmp"
      added=$((added + 1))
    done <<< "$up_kit_rows"
  fi

  if ! $APPLY; then
    # Compare the would-be result to the live file, not just dropped/added
    # counts: a drop+add of byte-identical rows produces an unchanged file,
    # and we want dry-run to honour the same "ok already matches" promise as
    # apply-mode (the cmp below).
    if cmp -s "$tmp" "$local_index"; then
      note "  ok    .skills/_index.md kit rows already match upstream (no merge needed)"
    else
      plan ".skills/_index.md: drop $dropped stale kit rows, add $added current kit rows"
    fi
    rm -f "$tmp"
    return 0
  fi

  # Compare; only overwrite if changed (keeps mtime stable when idempotent).
  if cmp -s "$tmp" "$local_index"; then
    note "  ok    .skills/_index.md kit rows already match upstream"
    rm -f "$tmp"
  else
    mv "$tmp" "$local_index"
    do_ ".skills/_index.md merged: dropped $dropped stale kit rows, added $added current kit rows"
  fi
  return 0
}

if $RECONCILE; then
  note "Step: --reconcile  (writes to .skills/_index.md and .skills/_meta.yml)"
  reconcile_meta
  reconcile_index
  note ""
fi

# --- Step 7: --symlink-consumer-skills (gh issue #3, friction point 8) --------
#
# When the consumer keeps real skill bodies under <consumer_skills_dir>/<name>/
# (e.g. .cursor/skills/<name>/) and uses .skills/_skills/<name>/ as a symlink
# shim, generate those shims with correct relative depth (../../<csd>/<name>).
# Idempotent. Skips kit skills, real directories, and any sources without a
# SKILL.md (so empty/junk subdirs aren't silently linked).

symlink_consumer_skills() {
  if [[ -z "$CONSUMER_SKILLS_DIR" ]]; then
    warn "--symlink-consumer-skills: no consumer_skills_dir declared in .skills/_meta.yml"
    warn "      Add 'consumer_skills_dir: <path>' (e.g. .cursor/skills) and re-run."
    return 0
  fi
  if [[ ! -d "$CONSUMER_SKILLS_DIR" ]]; then
    warn "--symlink-consumer-skills: declared consumer_skills_dir does not exist: $CONSUMER_SKILLS_DIR"
    return 0
  fi

  mkdir -p .skills/_skills

  # Relative depth from .skills/_skills/<name> back to repo root is "../../",
  # so the symlink target is "../../<consumer_skills_dir>/<name>". This depth
  # is fixed: .skills/_skills/<name> always sits exactly two levels deep.
  local target_prefix="../../$CONSUMER_SKILLS_DIR"
  local linked=0 skipped_kit=0 skipped_real=0 skipped_no_skill=0 already=0

  for src in "$CONSUMER_SKILLS_DIR"/*/; do
    [[ -d "$src" ]] || continue
    local name
    name="$(basename "$src")"

    if is_kit_skill "$name"; then
      skipped_kit=$((skipped_kit + 1))
      continue
    fi
    if [[ ! -f "$src/SKILL.md" ]]; then
      skipped_no_skill=$((skipped_no_skill + 1))
      continue
    fi

    local link=".skills/_skills/$name"
    local desired="$target_prefix/$name"

    if [[ -L "$link" ]]; then
      local current
      current="$(readlink "$link")"
      if [[ "$current" == "$desired" ]]; then
        already=$((already + 1))
        continue
      fi
      if $APPLY; then
        rm "$link"
        ln -s "$desired" "$link"
        do_ "updated $link -> $desired (was -> $current)"
        linked=$((linked + 1))
      else
        plan "update $link -> $desired (currently -> $current)"
      fi
      continue
    fi

    if [[ -e "$link" ]]; then
      # Real directory or file at the link path — refuse to clobber.
      warn "$link exists as a real entry; not symlinking. Resolve manually."
      skipped_real=$((skipped_real + 1))
      continue
    fi

    if $APPLY; then
      ln -s "$desired" "$link"
      do_ "linked $link -> $desired"
      linked=$((linked + 1))
    else
      plan "link $link -> $desired"
    fi
  done

  note "  summary: linked=$linked  already-correct=$already  skipped-kit=$skipped_kit  skipped-real=$skipped_real  skipped-no-SKILL.md=$skipped_no_skill"
  return 0
}

if $SYMLINK_CONSUMER_SKILLS; then
  note "Step: --symlink-consumer-skills  (writes symlinks under .skills/_skills/)"
  symlink_consumer_skills
  note ""
fi

# --- Step 8: post-action reminders --------------------------------------------

note ""
if $RECONCILE && $SYMLINK_CONSUMER_SKILLS; then
  note "Done. Next steps:"
elif $RECONCILE || $SYMLINK_CONSUMER_SKILLS; then
  note "Reconcile / symlink steps complete. Other reminders:"
else
  note "Step: manual reconcile (or re-run with --reconcile to automate this)"
  note "  1. .skills/_index.md  — merge new kit-skill rows from $PREFIX/.skills/_index.md"
  note "  2. .skills/_meta.yml  — bump kit_version to match $PREFIX/.skills/_meta.yml"
  note "       Both of the above can be done with: --reconcile --apply"
fi
note "  - Re-run native discovery if you use it:"
note "        .skills/_harness/link.sh .agents/skills    # or .claude/skills"
note "  - Validate:"
note "        .skills/_harness/check.sh"

if (( ERRORS > 0 )); then
  echo ""
  echo "$ERRORS error(s) — see above."
  exit 1
fi

if ! $APPLY; then
  note ""
  note "(dry-run) Re-run with --apply to perform the planned actions."
fi
