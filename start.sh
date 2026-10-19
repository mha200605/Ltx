#!/usr/bin/env bash
set -euo pipefail

: "${COMFYUI_DIR:=/opt/ComfyUI}"
: "${COMFYUI_HOST:=127.0.0.1}"
: "${COMFYUI_PORT:=8188}"
: "${STARTUP_TIMEOUT_SECONDS:=900}"
: "${COMFYUI_LOWVRAM:=1}"

mkdir -p /tmp/comfyui-output /tmp/comfyui-input

# Strict by default so a worker never accepts jobs with missing weights.
# Set SKIP_MODEL_LINKS=1 only for model-free local checks.
if [[ "${SKIP_MODEL_LINKS:-0}" != "1" ]]; then
  /app/prepare_models.sh
fi

cd "$COMFYUI_DIR"
COMFY_ARGS=(--listen "$COMFYUI_HOST" --port "$COMFYUI_PORT"
  --output-directory /tmp/comfyui-output
  --input-directory /tmp/comfyui-input
  --disable-auto-launch)
if [[ "$COMFYUI_LOWVRAM" == "1" ]]; then
  COMFY_ARGS+=(--lowvram)
fi
python main.py "${COMFY_ARGS[@]}" &
COMFY_PID=$!

cleanup() {
  kill "$COMFY_PID" 2>/dev/null || true
}
trap cleanup EXIT TERM INT

# Do not start the Runpod handler until its private backend is ready.
python - <<'PY'
import os, sys, time, urllib.request
host = os.getenv("COMFYUI_HOST", "127.0.0.1")
port = os.getenv("COMFYUI_PORT", "8188")
timeout = int(os.getenv("STARTUP_TIMEOUT_SECONDS", "900"))
url = f"http://{host}:{port}/system_stats"
end = time.monotonic() + timeout
while time.monotonic() < end:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            if r.status == 200:
                print("ComfyUI is ready; starting Runpod handler", flush=True)
                sys.exit(0)
    except Exception:
        pass
    time.sleep(2)
print(f"ComfyUI did not become ready within {timeout}s", file=sys.stderr, flush=True)
sys.exit(1)
PY

python /app/handler.py --start-comfyui &
HANDLER_PID=$!
wait "$HANDLER_PID"
