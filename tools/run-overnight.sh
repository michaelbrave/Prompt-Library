#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

SERVER_URL="http://127.0.0.1:8080"
PYTHON="python3"
LOG="/tmp/style-gen-$(date +%Y%m%d).log"

echo "[$(date)] Starting overnight style generation..." | tee -a "$LOG"

# Check if llama-server is responding
if ! curl -sf "$SERVER_URL/health" >/dev/null 2>&1; then
    echo "[$(date)] ERROR: llama-server not running at $SERVER_URL" | tee -a "$LOG" >&2
    echo "Start it first:" | tee -a "$LOG" >&2
    echo "  llama-server --model ~/image-workflow/models/qwen3.6-27b-q4_k_m.gguf --host 127.0.0.1 --port 8080 --n-gpu-layers 999 --ctx-size 4096 &>/tmp/llama-server.log &" | tee -a "$LOG" >&2
    exit 1
fi

BATCH=0
TOTAL=0
while true; do
    BATCH=$((BATCH + 1))
    echo "[$(date)] Batch $BATCH (total so far: $TOTAL)..." | tee -a "$LOG"

    output=$($PYTHON tools/generate_missing_styles.py \
        --prompt-set publish-curated-styles-1000 \
        --limit 60 \
        --allow-wildcard-drop \
        --strip-extra-wildcards \
        --llm-cmd "$PYTHON tools/llama_style_worker.py --server $SERVER_URL" \
        2>&1) || true

    echo "$output" >> "$LOG"

    # Count completed in this batch
    completed=$(echo "$output" | grep -c "^Completed" || true)
    failed=$(echo "$output" | grep -c "^Failed" || true)
    TOTAL=$((TOTAL + completed))
    echo "[$(date)] Batch $BATCH: $completed completed, $failed failed" | tee -a "$LOG"

    # Stop conditions
    if echo "$output" | grep -q "No missing style variants found"; then
        echo "[$(date)] All done! No more jobs." | tee -a "$LOG"
        break
    fi

    processed=$(echo "$output" | grep -oP 'processed \K\d+' | tail -1)
    if [ "${processed:-0}" = "0" ]; then
        echo "[$(date)] No progress made, stopping." | tee -a "$LOG"
        break
    fi

    sleep 2
done

echo "[$(date)] Finished. Total completed this session: $TOTAL" | tee -a "$LOG"
$PYTHON tools/generate_missing_styles.py --prompt-set publish-curated-styles-1000 --stats 2>&1 | tee -a "$LOG"
