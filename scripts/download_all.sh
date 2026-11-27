#!/usr/bin/env bash
# Downloads all 9,726 soundscape recordings (~4.3 GB) in a single request.
#
# Kaggle limits downloads of single files (download_sample.sh): after a few
# hundred it allows about 32 every 30 minutes, days for the whole set. This
# script asks for the whole competition archive instead (12.4 GB) and extracts
# only train_soundscapes/ while it arrives, so the archive is never stored:
# it needs ~4.5 GB of free disk. About 15 minutes at 9 MB/s.
# Recordings already present are kept as they are.
#
# Needs: curl, bsdtar (macOS has it; on Debian/Ubuntu: libarchive-tools), a
# Kaggle token in ~/.kaggle/access_token and the competition rules accepted.
#
# Usage (from the project root):
#   bash scripts/download_all.sh

set -euo pipefail

COMPETITION="birdclef-2025"
TOKEN_FILE="$HOME/.kaggle/access_token"
DEST_DIR="data/raw/birdclef/train_soundscapes"
STAGE_DIR="data/raw/birdclef/_download_all" # new and empty: the archive is not ours

# 1. Pre-flight checks
for tool in curl bsdtar; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "ERROR: '$tool' not found."
    exit 1
  fi
done
if [ ! -f "$TOKEN_FILE" ]; then
  echo "ERROR: Kaggle token not found in $TOKEN_FILE"
  exit 1
fi
if [ -e "$STAGE_DIR" ]; then
  echo "ERROR: $STAGE_DIR exists (left by a stopped run?); remove it and retry"
  exit 1
fi

# 2. Kaggle answers with a redirect to a signed, short-lived link to the archive
url=$(curl -sS --max-time 60 -o /dev/null -w '%{redirect_url}' \
  -H "Authorization: Bearer $(cat "$TOKEN_FILE")" \
  "https://www.kaggle.com/api/v1/competitions/data/download-all/$COMPETITION")
if [ -z "$url" ]; then
  echo "ERROR: Kaggle gave no download link (token valid? rules accepted?)"
  exit 1
fi

# 3. Download and extract at once, keeping only the soundscapes
mkdir -p "$STAGE_DIR" "$DEST_DIR"
echo ">> Downloading the $COMPETITION archive (~12 GB) and extracting train_soundscapes/"
curl -fsS "$url" | bsdtar -xf - -C "$STAGE_DIR" 'train_soundscapes/*'

# 4. Move in the recordings not already present
moved=0
for file in "$STAGE_DIR"/train_soundscapes/*.ogg; do
  name=$(basename "$file")
  if [ ! -e "$DEST_DIR/$name" ]; then
    mv "$file" "$DEST_DIR/$name"
    moved=$((moved + 1))
  fi
done
rm -r "$STAGE_DIR"

# 5. Summary
echo
echo ">> New recordings: $moved"
echo ">> Recordings in $DEST_DIR: $(find "$DEST_DIR" -name '*.ogg' | wc -l | tr -d ' ') ($(du -sh "$DEST_DIR" | cut -f1))"
