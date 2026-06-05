#!/usr/bin/env sh
# Creates symlinks from a target directory into .skills/_skills/ so IDEs
# with native skill discovery can find harness-managed skills.
#
# Usage: .skills/_harness/link.sh [--clean] <target-dir>
#        .skills/_harness/link.sh <target-dir> [--clean]
#
#   <target-dir>  Relative path from repo root (e.g. .agents/skills)
#   --clean       Remove existing symlinks in target before creating

set -eu

HARNESS_DIR="${SKILLS_HARNESS_DIR:-$(cd "$(dirname "$0")" && pwd)}"
SKILLS_DIR="${SKILLS_DIR:-$(dirname "$HARNESS_DIR")/_skills}"
REPO_ROOT="${SKILLS_REPO_ROOT:-$(dirname "$(dirname "$HARNESS_DIR")")}"

usage() {
  echo "Usage: $(basename "$0") [--clean] <target-dir>" >&2
  echo "  <target-dir>  Relative path from repo root (e.g. .agents/skills)" >&2
  exit 1
}

TARGET_REL=""
CLEAN=false
for arg in "$@"; do
  case "$arg" in
    --clean) CLEAN=true ;;
    -*)      echo "Unknown option: $arg" >&2; usage ;;
    *)
      [ -n "$TARGET_REL" ] && usage
      TARGET_REL="$arg"
      ;;
  esac
done
[ -z "$TARGET_REL" ] && usage

TARGET_ABS="$REPO_ROOT/$TARGET_REL"

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    echo "WARNING: Symlinks on Windows require 'git config core.symlinks true'" >&2
    echo "         and may need elevated privileges." >&2
    ;;
esac

if $CLEAN && [ -d "$TARGET_ABS" ]; then
  for item in "$TARGET_ABS"/*/; do
    [ ! -L "${item%/}" ] && continue
    rm -f "${item%/}"
    echo "  removed  $TARGET_REL/$(basename "${item%/}")"
  done
fi

mkdir -p "$TARGET_ABS"

# Compute relative path from target back to .skills/_skills.
# Each segment in TARGET_REL needs one "../" to climb back to repo root.
rel_prefix=""
tmp="$TARGET_REL"
while [ "$tmp" != "." ] && [ -n "$tmp" ]; do
  rel_prefix="../$rel_prefix"
  parent="$(dirname "$tmp")"
  [ "$parent" = "$tmp" ] && break
  tmp="$parent"
done
REL_SKILLS="${rel_prefix}.skills/_skills"

linked=0
skipped=0
updated=0
pruned=0

for skill_dir in "$SKILLS_DIR"/*/; do
  [ ! -d "$skill_dir" ] && continue
  name="$(basename "$skill_dir")"

  # Skip _-prefixed directories (harness internal)
  case "$name" in
    _*) continue ;;
  esac

  target_link="$TARGET_ABS/$name"
  expected_target="$REL_SKILLS/$name"

  if [ -L "$target_link" ]; then
    actual_target="$(readlink "$target_link")"
    if [ "$actual_target" = "$expected_target" ]; then
      skipped=$((skipped + 1))
      continue
    fi
    echo "  update  $TARGET_REL/$name (was -> $actual_target)"
    rm -f "$target_link"
    ln -s "$expected_target" "$target_link"
    updated=$((updated + 1))
    continue
  fi

  if [ -e "$target_link" ]; then
    echo "  SKIP  $TARGET_REL/$name (not a symlink)" >&2
    skipped=$((skipped + 1))
    continue
  fi

  ln -s "$expected_target" "$target_link"
  echo "  linked  $TARGET_REL/$name"
  linked=$((linked + 1))
done

# Prune dangling symlinks (targets that no longer exist)
for item in "$TARGET_ABS"/*/; do
  [ ! -L "${item%/}" ] && continue
  if [ ! -d "${item%/}" ]; then
    link_target="$(readlink "${item%/}")"
    echo "  pruned  $TARGET_REL/$(basename "${item%/}") (dangling -> $link_target)"
    rm -f "${item%/}"
    pruned=$((pruned + 1))
  fi
done

echo ""
summary="Done: $linked linked, $skipped unchanged"
if [ "$updated" -gt 0 ]; then
  summary="$summary, $updated updated"
fi
if [ "$pruned" -gt 0 ]; then
  summary="$summary, $pruned pruned"
fi
echo "$summary."
if [ "$linked" -gt 0 ]; then
  echo "Ensure '$TARGET_REL/' is in .gitignore."
fi
