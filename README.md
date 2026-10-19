# LTX-2.5 Turbo on Runpod Serverless

API-only text-to-video worker. ComfyUI runs privately inside the container; clients send a simple Runpod job and get back an MP4.

## Repo layout (everything at the repo root)

| File | Purpose |
|---|---|
| `Dockerfile` | Worker image: Python 3.12, pinned ComfyUI, PyTorch 2.7.1 (CUDA 12.8) |
| `start.sh` | Links model files, starts ComfyUI, waits until ready, starts the handler |
| `handler.py` | Validates the request, fills the fixed workflow, returns the video |
| `workflow_api.json` | Fixed LTX-2.5 API-format graph |
| `prepare_models.sh` | Validates and links the 5 model files from the network volume |
| `preload_models.sh` | One-time helper to download models onto the volume (needs `HF_TOKEN`) |
| `model-manifest.json` | Model files and pinned revision |
| `requirements.txt` | Handler dependencies |

## Deploying from GitHub

1. Make sure `Dockerfile` is at the **top level** of the repo.
2. In the Runpod console, create or edit the endpoint and point it at this repo, branch `main`. Leave the Dockerfile path as the default.
3. Attach the network volume that holds the models, mounted at `/runpod-volume`.
4. Builds only run when you publish a new **GitHub Release**.

## API input

```json
{
  "input": {
    "prompt": "A small sailboat crossing a calm lake at sunrise, cinematic natural light",
    "duration_seconds": 2,
    "width": 512,
    "height": 320,
    "seed": 123456
  }
}
```

`prompt` is required. Width and height: 320 to 512 in steps of 64. Duration: 1 or 2 seconds. Small videos come back as base64; larger ones are uploaded to S3-compatible storage if `S3_BUCKET`, `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` are set as endpoint secrets.

## Models

Five files must exist under `/runpod-volume/ltx25-models` (see `model-manifest.json`). Use `preload_models.sh` once on a temporary Pod with the volume mounted and `HF_TOKEN` set. Never put tokens in the repo or the image.

## Status

The image build, real ComfyUI execution, VRAM fit on a 24 GB GPU and generation speed are still untested.
