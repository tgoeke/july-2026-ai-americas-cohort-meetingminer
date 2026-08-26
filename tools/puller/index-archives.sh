#!/bin/zsh
# Periodically index every archive listed in archives.txt: scans each SharePoint
# folder, refreshes its _index.json, and appends a found/missing line to its
# _index-log.txt. Also writes a top-level run marker to index-cron.log.
# Intended to be run on a schedule (cron/launchd). Does NOT download videos.
cd "$(dirname "$0")" || exit 1

NODE="$(command -v node)"
LOG="index-cron.log"
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "[$STAMP] index run starting" >> "$LOG"
while IFS= read -r url; do
  case "$url" in
    ''|\#*) continue ;;  # skip blanks and comments
  esac
  echo "[$STAMP] indexing: $url" >> "$LOG"
  "$NODE" grab-teams-transcript.js "$url" --index >> "$LOG" 2>&1
done < archives.txt
echo "[$STAMP] index run finished" >> "$LOG"
