#!/usr/bin/env bash
set -euo pipefail

# Regenerates the table rows in _index.md from SKILL.md frontmatter.
# Dry-run by default (prints drift, exits non-zero); --write performs edits.
#
# Usage: .skills/_harness/build-index.sh [--write]

HARNESS_DIR="${SKILLS_HARNESS_DIR:-$(cd "$(dirname "$0")" && pwd)}"
SKILLS_DIR="${SKILLS_DIR:-$(dirname "$HARNESS_DIR")/_skills}"
INDEX_FILE="${SKILLS_INDEX:-$(dirname "$HARNESS_DIR")/_index.md}"

WRITE=false
for arg in "$@"; do
  case "$arg" in
    --write) WRITE=true ;;
  esac
done

if [[ ! -d "$SKILLS_DIR" ]]; then
  echo "ERROR: _skills directory not found at $SKILLS_DIR" >&2
  exit 1
fi

if [[ ! -f "$INDEX_FILE" ]]; then
  echo "ERROR: _index.md not found at $INDEX_FILE" >&2
  exit 1
fi

# --- Read frontmatter from every SKILL.md ---

rows=""
for skill_dir in "$SKILLS_DIR"/*/; do
  [[ ! -d "$skill_dir" ]] && continue
  skill_file="$skill_dir/SKILL.md"
  [[ ! -f "$skill_file" ]] && continue

  fm_name="" fm_desc="" fm_triggers=""
  in_fm=false

  while IFS= read -r line; do
    if [[ "$line" == "---" ]]; then
      if $in_fm; then break; else in_fm=true; continue; fi
    fi
    $in_fm || continue

    key="${line%%:*}"
    key="$(echo "$key" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    val="${line#*:}"
    val="$(echo "$val" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed 's/^"//;s/"$//')"

    case "$key" in
      name) fm_name="$val" ;;
      description) fm_desc="$val" ;;
      triggers)
        if [[ "$val" =~ ^\[.*\]$ ]]; then
          fm_triggers="$(echo "$val" | sed 's/^\[//;s/\]$//;s/,  */ /g' | sed 's/^ *//;s/ *$//')"
        elif [[ -z "$val" ]]; then
          while IFS= read -r tline; do
            tline_trimmed="$(echo "$tline" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
            [[ "$tline_trimmed" != -* ]] && break
            item="${tline_trimmed#- }"
            item="$(echo "$item" | sed 's/^"//;s/"$//')"
            if [[ -n "$fm_triggers" ]]; then
              fm_triggers="$fm_triggers, $item"
            else
              fm_triggers="$item"
            fi
          done
        fi
        ;;
    esac
  done < "$skill_file"

  if [[ -n "$fm_name" ]]; then
    rows="${rows}| ${fm_name} | ${fm_desc} | ${fm_triggers} |
"
  fi
done

# --- Reconstruct the index preserving intro and trailing prose ---

# Find the table header line number
table_header_line="$(grep -n '^| name ' "$INDEX_FILE" | head -1 | cut -d: -f1)"
if [[ -z "$table_header_line" ]]; then
  echo "ERROR: no table header (| name ...) found in $INDEX_FILE" >&2
  exit 1
fi

# Intro = everything before the table header (preserved verbatim, including trailing blank lines)
intro="$(head -n $((table_header_line - 1)) "$INDEX_FILE" && printf x)"
intro="${intro%x}"

# Find where the table ends: first line after header that doesn't start with |
total_lines="$(wc -l < "$INDEX_FILE")"
after_table_start=""
line_num=$((table_header_line + 1))  # skip header
while (( line_num <= total_lines )); do
  cur="$(sed -n "${line_num}p" "$INDEX_FILE")"
  if [[ "$cur" == "|"* ]]; then
    line_num=$((line_num + 1))
    continue
  fi
  after_table_start="$line_num"
  break
done

trailing=""
if [[ -n "$after_table_start" ]]; then
  trailing="$(tail -n +$after_table_start "$INDEX_FILE")"
fi

# Build new index
new_index="${intro}| name | description | triggers |
|------|-------------|----------|
${rows}${trailing}
"

current="$(cat "$INDEX_FILE")
"

if [[ "$new_index" == "$current" ]]; then
  echo "Index is in sync with skill frontmatter."
  exit 0
fi

if $WRITE; then
  printf '%s' "$new_index" > "$INDEX_FILE"
  echo "Updated _index.md."
else
  echo "Index drifted from skill frontmatter. Run with --write to fix."
  exit 1
fi
