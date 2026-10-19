#!/usr/bin/env bash
set -euo pipefail

: "${COMFYUI_DIR:=/opt/ComfyUI}"
: "${MODEL_DIR:=/runpod-volume/ltx25-models}"

files=(
  "diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"
  "text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"
  "vae/ltx-2.5-video-vae-conv-bf16.safetensors"
  "vae/ltx-2.5-audio-vae-bf16.safetensors"
  "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"
)

for rel in "${files[@]}"; do
  source_path="${MODEL_DIR}/${rel}"
  target_path="${COMFYUI_DIR}/models/${rel}"
  if [[ ! -s "$source_path" ]]; then
    echo "Required LTX-2.5 model file missing or empty: $source_path" >&2
    echo "Preload the files listed in model-manifest.json onto the attached volume before serving requests." >&2
    exit 1
  fi
  mkdir -p "$(dirname "$target_path")"
  ln -sfn "$source_path" "$target_path"
done

echo "Validated and linked all required LTX-2.5 model files from ${MODEL_DIR}" >&2
