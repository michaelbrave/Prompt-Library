#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

SERVER_URL="${SERVER_URL:-http://127.0.0.1:8080}"
PYTHON="${PYTHON:-python3}"
LIMIT="${LIMIT:-40}"
LOG="${LOG:-/tmp/style-cleanup-$(date +%Y%m%d).log}"

echo "[$(date)] Starting failed style cleanup against $SERVER_URL..." | tee -a "$LOG"

if ! curl -sf "$SERVER_URL/health" >/dev/null 2>&1; then
    echo "[$(date)] ERROR: llama-server not running at $SERVER_URL" | tee -a "$LOG" >&2
    echo "Start llama-server first:" | tee -a "$LOG" >&2
    echo "  llama-server --model ~/image-workflow/models/qwen3.6-27b-q4_k_m.gguf --host 127.0.0.1 --port 8080 --n-gpu-layers 999 --ctx-size 4096 &" | tee -a "$LOG" >&2
    exit 1
fi

BATCH=0
TOTAL=0
while true; do
    BATCH=$((BATCH + 1))
    echo "[$(date)] Cleanup batch $BATCH (total fixed so far: $TOTAL)..." | tee -a "$LOG"

    output=$($PYTHON tools/generate_missing_styles.py \
        --failed-only \
        --limit "$LIMIT" \
        --allow-wildcard-drop \
        --strip-extra-wildcards \
        --llm-cmd "$PYTHON tools/llama_style_worker.py --server $SERVER_URL" \
        2>&1) || true

    echo "$output" >> "$LOG"

    completed=$(echo "$output" | grep -c "^Completed" || true)
    failed=$(echo "$output" | grep -c "^Failed" || true)
    TOTAL=$((TOTAL + completed))
    echo "[$(date)] Cleanup batch $BATCH: $completed fixed, $failed still failed" | tee -a "$LOG"

    if echo "$output" | grep -q "No missing style variants found"; then
        echo "[$(date)] Cleanup done. No failed jobs left for selected styles." | tee -a "$LOG"
        break
    fi

    processed=$(echo "$output" | grep -oP 'processed \K\d+' | tail -1)
    if [ "${processed:-0}" = "0" ]; then
        echo "[$(date)] No cleanup progress made, stopping." | tee -a "$LOG"
        break
    fi

    sleep 2
done

echo "[$(date)] Finished cleanup. Total fixed this session: $TOTAL" | tee -a "$LOG"
$PYTHON tools/generate_missing_styles.py --stats 2>&1 | tee -a "$LOG"
