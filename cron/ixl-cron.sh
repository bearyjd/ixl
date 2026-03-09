#!/usr/bin/env bash
# ixl-cron.sh — scrape all IXL student accounts and dump JSON
#
# Reads accounts from ~/.ixl/accounts.env (one per line):
#   child1:username@school:password
#   child2:username@school:password
#
# Outputs to $OUTPUT_DIR/{name}-summary.json and {name}-assigned.json
#
# Usage:
#   ./cron/ixl-cron.sh                    # uses defaults
#   OUTPUT_DIR=/data/ixl ./cron/ixl-cron.sh

set -euo pipefail

ACCOUNTS_FILE="${ACCOUNTS_FILE:-$HOME/.ixl/accounts.env}"
OUTPUT_DIR="${OUTPUT_DIR:-/tmp/ixl}"

if [[ ! -f "$ACCOUNTS_FILE" ]]; then
    echo "No accounts file found at $ACCOUNTS_FILE" >&2
    echo "Create it with one line per student:" >&2
    echo "  childname:username@school:password" >&2
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

while IFS=: read -r name email password; do
    [[ -z "$name" || "$name" == \#* ]] && continue

    echo "[$(date '+%H:%M:%S')] Scraping $name..." >&2

    IXL_EMAIL="$email" IXL_PASSWORD="$password" \
        ixl summary --json > "$OUTPUT_DIR/${name}-summary.json" 2>/dev/null || \
        echo "[$(date '+%H:%M:%S')] WARN: summary failed for $name" >&2

    IXL_EMAIL="$email" IXL_PASSWORD="$password" \
        ixl assigned --json > "$OUTPUT_DIR/${name}-assigned.json" 2>/dev/null || \
        echo "[$(date '+%H:%M:%S')] WARN: assigned failed for $name" >&2

    echo "[$(date '+%H:%M:%S')] Done: $name" >&2
done < "$ACCOUNTS_FILE"

echo "[$(date '+%H:%M:%S')] All accounts scraped → $OUTPUT_DIR/" >&2
