# Running Qwen 3.6 (llama-server)

## Start the server

```bash
llama-server \
  --model ~/image-workflow/models/qwen3.6-27b-q4_k_m.gguf \
  --host 127.0.0.1 \
  --port 8080 \
  --n-gpu-layers 999 \
  --ctx-size 4096 \
  &>/tmp/llama-server.log &
```

## Check it's responding

```bash
curl http://127.0.0.1:8080/health
```

## Run overnight style generation

```bash
bash tools/run-overnight.sh
```

This runs in a loop, generating missing prompt style variants in batches of 60. Logs go to `/tmp/style-gen-$(date +%Y%m%d).log`.

## Stop the server

```bash
pkill llama-server
```
