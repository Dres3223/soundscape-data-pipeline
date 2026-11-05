#!/usr/bin/env bash
# Downloads soundscape recordings for local development.
#   - No arguments: the fixed sample in scripts/dev_sample.txt (16 files, ~8 MB).
#   - Site codes:   every recording of those sites (~178 per site, ~85 MB each),
#                   taken from file_list_full.txt (made by scripts/list_files.sh).
#
# Usage (from the project root):
#   uv run bash scripts/download_sample.sh
#   uv run bash scripts/download_sample.sh H02 H24 O203 H85

set -euo pipefail

COMPETITION="birdclef-2025"
LIST_FILE="scripts/dev_sample.txt"
FULL_LIST="data/raw/birdclef/file_list_full.txt"
DEST_DIR="data/raw/birdclef/train_soundscapes"

# 1. Pre-flight checks
if ! command -v kaggle >/dev/null 2>&1; then
  echo "ERROR: 'kaggle' command not found."
  echo "Install the dependencies with: uv sync"
  echo "and run the script with:       uv run bash scripts/download_sample.sh"
  exit 1
fi

if [ $# -gt 0 ]; then
  # One recording name per line for each requested site (e.g. H02_20230422_014500.ogg)
  if [ ! -f "$FULL_LIST" ]; then
    echo "ERROR: $FULL_LIST not found; create it with: uv run bash scripts/list_files.sh"
    exit 1
  fi
  pattern="^($(IFS='|'; echo "$*"))_[0-9]{8}_[0-9]{6}\.ogg$"
  files=$(grep -oE '[A-Z]+[0-9]+_[0-9]{8}_[0-9]{6}\.ogg' "$FULL_LIST" | grep -E "$pattern" | sort -u)
  if [ -z "$files" ]; then
    echo "ERROR: no recordings found for sites: $*"
    exit 1
  fi
  echo ">> $(echo "$files" | wc -l | tr -d ' ') recordings for sites: $*"
else
  if [ ! -f "$LIST_FILE" ]; then
    echo "ERROR: list file $LIST_FILE not found"
    exit 1
  fi
  files=$(cat "$LIST_FILE")
fi

mkdir -p "$DEST_DIR"

# 2. Download (skips files already present, so the script can be re-run safely)
downloaded=0
skipped=0
while read -r file; do
  case "$file" in ''|\#*) continue ;; esac

  if [ -f "$DEST_DIR/$file" ]; then
    skipped=$((skipped + 1))
    continue
  fi
  echo ">> Downloading $file"
  # Kaggle keeps the file's subfolder, so we download into the parent folder
  kaggle competitions download -c "$COMPETITION" -f "train_soundscapes/$file" -p "$(dirname "$DEST_DIR")" -q
  if [ -f "$DEST_DIR/$file.zip" ]; then
    unzip -o -q "$DEST_DIR/$file.zip" -d "$DEST_DIR"
    rm "$DEST_DIR/$file.zip"
  fi
  downloaded=$((downloaded + 1))
done <<< "$files"

# 3. Summary
echo
echo ">> Downloaded: $downloaded | Already present: $skipped"
echo ">> Recordings in $DEST_DIR: $(find "$DEST_DIR" -name '*.ogg' | wc -l | tr -d ' ') ($(du -sh "$DEST_DIR" | cut -f1))"
