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
OUTPUT_DIR="${OUTPUT_DIR:-$HOME/.ixl/output}"

if [[ ! -f "$ACCOUNTS_FILE" ]]; then
    echo "No accounts file found at $ACCOUNTS_FILE" >&2
    echo "Create it with one line per student:" >&2
    echo "  childname:username@school:password" >&2
    exit 1
fi

mkdir -p "$OUTPUT_DIR"
chmod 700 "$OUTPUT_DIR"

while IFS= read -r line; do
    [[ -z "$line" || "$line" == \#* ]] && continue

    # Parse name:email:password — only split on first two colons
    # so passwords containing colons are handled correctly
    name="${line%%:*}"; rest="${line#*:}"
    email="${rest%%:*}"; password="${rest#*:}"

    [[ -z "$name" ]] && continue

    echo "[$(date '+%H:%M:%S')] Scraping $name..." >&2

    # Write to temp file, validate JSON, then atomically move into place.
    # Log errors instead of suppressing with /dev/null.
    tmpfile=$(mktemp -p "$OUTPUT_DIR" ".${name}-summary.XXXXXX")
    if IXL_EMAIL="$email" IXL_PASSWORD="$password" \
        ixl summary --json > "$tmpfile" 2>>"$OUTPUT_DIR/${name}-summary.log" && \
        python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$tmpfile" 2>/dev/null; then
        mv "$tmpfile" "$OUTPUT_DIR/${name}-summary.json"
    else
        rm -f "$tmpfile"
        echo "[$(date '+%H:%M:%S')] WARN: summary failed for $name (see ${name}-summary.log)" >&2
    fi

    tmpfile=$(mktemp -p "$OUTPUT_DIR" ".${name}-assigned.XXXXXX")
    if IXL_EMAIL="$email" IXL_PASSWORD="$password" \
        ixl assigned --json > "$tmpfile" 2>>"$OUTPUT_DIR/${name}-assigned.log" && \
        python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$tmpfile" 2>/dev/null; then
        mv "$tmpfile" "$OUTPUT_DIR/${name}-assigned.json"
    else
        rm -f "$tmpfile"
        echo "[$(date '+%H:%M:%S')] WARN: assigned failed for $name (see ${name}-assigned.log)" >&2
    fi

    echo "[$(date '+%H:%M:%S')] Done: $name" >&2
done < "$ACCOUNTS_FILE"

echo "[$(date '+%H:%M:%S')] All accounts scraped → $OUTPUT_DIR/" >&2
