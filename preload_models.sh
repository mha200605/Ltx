#!/usr/bin/env bash
set -euo pipefail

# Run once on a trusted temporary compute instance with the target Network
# Volume mounted. For a Runpod Pod, set MODEL_DIR to /workspace/ltx25-models.
# For Serverless workers, the volume is mounted at /runpod-volume.
: "${MODEL_DIR:?Set MODEL_DIR to the mounted volume path}"
: "${HF_TOKEN:?Set HF_TOKEN in the preload environment after accepting the gated model terms}"
: "${MODEL_REVISION:=49b093a39c19169a8a81721dcc541e07e945232f}"

if [[ ! "$MODEL_REVISION" =~ ^[0-9a-f]{40}$ ]]; then
  echo "MODEL_REVISION must be an immutable 40-character Hugging Face commit SHA." >&2
  exit 1
fi

if ! command -v hf >/dev/null 2>&1; then
  echo "Install a recent huggingface_hub CLI first (hf --help)." >&2
  exit 1
fi

mkdir -p "$MODEL_DIR"

# hf reads HF_TOKEN from the environment. Do not pass the secret on the command
# line, put it in a file, bake it into an image, or use it as a Serverless input.
hf download Lightricks/LTX-2.5 \
  diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors \
  text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors \
  vae/ltx-2.5-video-vae-conv-bf16.safetensors \
  vae/ltx-2.5-audio-vae-bf16.safetensors \
  latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors \
  --revision "$MODEL_REVISION" \
  --local-dir "$MODEL_DIR"

for rel in \
  diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors \
  text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors \
  vae/ltx-2.5-video-vae-conv-bf16.safetensors \
  vae/ltx-2.5-audio-vae-bf16.safetensors \
  latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors; do
  if [[ ! -s "$MODEL_DIR/$rel" ]]; then
    echo "Expected downloaded file missing or empty: $MODEL_DIR/$rel" >&2
    exit 1
  fi
done

printf '%s\n' "$MODEL_REVISION" > "$MODEL_DIR/MODEL_REVISION.txt"
echo "Model preload complete at $MODEL_DIR; record MODEL_REVISION=$MODEL_REVISION" >&2
