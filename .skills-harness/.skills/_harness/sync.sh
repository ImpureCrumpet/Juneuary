#!/usr/bin/env bash
set -euo pipefail

# Syncs the Rules block from _rules.md into every *_template.md.
# Dry-run by default (prints drift, exits non-zero); --write performs edits.
#
# Usage: .skills/_harness/sync.sh [--write]

HARNESS_DIR="${SKILLS_HARNESS_DIR:-$(cd "$(dirname "$0")" && pwd)}"
RULES_FILE="${SKILLS_RULES:-$HARNESS_DIR/_rules.md}"

WRITE=false
for arg in "$@"; do
  case "$arg" in
    --write) WRITE=true ;;
  esac
done

if [[ ! -f "$RULES_FILE" ]]; then
  echo "ERROR: _rules.md not found at $RULES_FILE" >&2
  exit 1
fi

# Canonical bullets: everything after the `# Rules` heading, blank lines stripped.
canonical="$(sed -n '/^# Rules$/,$ p' "$RULES_FILE" | tail -n +2 | sed '/^$/d')"

drifted=0

for tmpl in "$HARNESS_DIR"/*_template.md; do
  [[ ! -f "$tmpl" ]] && continue
  tmpl_name="$(basename "$tmpl")"

  if ! grep -q '^## Rules$' "$tmpl"; then
    echo "  SKIP  $tmpl_name (no ## Rules heading)" >&2
    continue
  fi

  # Extract the current rules body (everything after `## Rules` to EOF), blank-stripped
  tmpl_rules="$(sed -n '/^## Rules$/,$ p' "$tmpl" | tail -n +2 | sed '/^$/d')"

  if [[ "$tmpl_rules" == "$canonical" ]]; then
    continue
  fi

  drifted=$((drifted + 1))

  if $WRITE; then
    # Keep everything up to and including the `## Rules` line
    head_part="$(sed -n '1,/^## Rules$/ p' "$tmpl")"
    {
      printf '%s\n\n' "$head_part"
      printf '%s\n' "$canonical"
    } > "$tmpl"
    echo "  updated  $tmpl_name"
  else
    echo "  drifted  $tmpl_name"
  fi
done

if (( drifted == 0 )); then
  echo "All templates in sync with _rules.md."
  exit 0
else
  if $WRITE; then
    echo "Updated $drifted template(s)."
  else
    echo "$drifted template(s) drifted. Run with --write to fix."
    exit 1
  fi
fi
