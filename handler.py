from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

import runpod

COMFY_HOST = os.getenv("COMFYUI_HOST", "127.0.0.1")
COMFY_PORT = os.getenv("COMFYUI_PORT", "8188")
COMFY_URL = f"http://{COMFY_HOST}:{COMFY_PORT}"
JOB_TIMEOUT = int(os.getenv("JOB_TIMEOUT_SECONDS", "1800"))
OUTPUT_DIR = Path("/tmp/comfyui-output")
WORKFLOW_PATH = Path(os.getenv("WORKFLOW_PATH", str(Path(__file__).with_name("workflow_api.json"))))
FRAME_RATE = 24
MIN_DIMENSION = 320
MAX_DIMENSION = 512
MAX_DURATION_SECONDS = 2


def request_json(url: str, payload: dict | None = None, timeout: int = 60) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def wait_for_prompt(prompt_id: str, timeout: int) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        history = request_json(f"{COMFY_URL}/history/{prompt_id}", timeout=30)
        if isinstance(history, dict) and prompt_id in history:
            item = history[prompt_id]
            status = item.get("status", {})
            status_text = str(status.get("status_str", "")).lower()
            if status_text in {"error", "failed"}:
                raise RuntimeError(f"ComfyUI workflow failed: {status}")
            if status.get("completed") is True:
                return item
        time.sleep(2)
    raise TimeoutError(f"Timed out waiting for ComfyUI prompt {prompt_id}")


def output_files(history_item: dict) -> list[dict]:
    results = []
    for node_id, node_output in history_item.get("outputs", {}).items():
        for key in ("videos", "gifs", "images"):
            for item in node_output.get(key, []) or []:
                if item.get("filename"):
                    results.append({"node_id": node_id, "kind": key, **item})
    return results


def _input_int(payload: dict, key: str, default: int, minimum: int, maximum: int) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"input.{key} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"input.{key} must be between {minimum} and {maximum}")
    return value


def build_workflow(payload: dict) -> tuple[dict, dict]:
    """Load the fixed graph and apply bounded user-facing generation settings."""
    if "workflow" in payload:
        raise ValueError("Caller-supplied workflows are disabled; use prompt/settings with the fixed worker graph")

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("input.prompt must be a non-empty string")
    prompt = prompt.strip()
    if len(prompt) > 4000:
        raise ValueError("input.prompt must be at most 4000 characters")

    width = _input_int(payload, "width", 512, MIN_DIMENSION, MAX_DIMENSION)
    height = _input_int(payload, "height", 320, MIN_DIMENSION, MAX_DIMENSION)
    if width % 64 or height % 64:
        raise ValueError("input.width and input.height must be multiples of 64")
    duration = _input_int(payload, "duration_seconds", 2, 1, MAX_DURATION_SECONDS)
    seed = _input_int(payload, "seed", 123456, 0, (1 << 64) - 1)
    frames = 1 + 8 * round(duration * FRAME_RATE / 8)

    if not WORKFLOW_PATH.is_file():
        raise RuntimeError(f"Fixed API workflow file is missing: {WORKFLOW_PATH}")
    workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    if not isinstance(workflow, dict) or not workflow:
        raise RuntimeError("Fixed API workflow file is empty or invalid")
    workflow = deepcopy(workflow)

    # IDs are frozen by workflow_api.json and documented alongside the graph.
    workflow["432"]["inputs"]["text"] = prompt
    workflow["421"]["inputs"]["noise_seed"] = seed
    workflow["429"]["inputs"]["noise_seed"] = seed
    workflow["434"]["inputs"].update({"width": width // 2, "height": height // 2, "length": frames})
    workflow["435"]["inputs"].update({"frames_number": frames, "frame_rate": FRAME_RATE})
    workflow["430"]["inputs"]["frame_rate"] = float(FRAME_RATE)
    workflow["413"]["inputs"]["fps"] = float(FRAME_RATE)

    settings = {
        "width": width,
        "height": height,
        "duration_seconds_requested": duration,
        "frames": frames,
        "frame_rate": FRAME_RATE,
        "seed": seed,
    }
    return workflow, settings


def upload_to_object_storage(path: Path, prompt_id: str) -> dict | None:
    bucket = os.getenv("S3_BUCKET")
    if not bucket:
        return None

    import boto3

    endpoint_url = os.getenv("S3_ENDPOINT_URL") or None
    region = os.getenv("S3_REGION") or os.getenv("AWS_DEFAULT_REGION") or None
    ttl = int(os.getenv("S3_PRESIGNED_URL_TTL", "3600"))
    key = f"ltx25/{prompt_id}/{path.name}"
    client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region)
    content_type = "video/mp4" if path.suffix.lower() == ".mp4" else "application/octet-stream"
    client.upload_file(
        str(path),
        bucket,
        key,
        ExtraArgs={"ContentType": content_type},
    )
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=ttl,
    )
    return {"download_url": url, "object_key": key}


def handle_job(job: dict) -> dict:
    payload = job.get("input", {})
    if not isinstance(payload, dict):
        raise ValueError("job.input must be an object")
    workflow, settings = build_workflow(payload)
    client_id = str(payload.get("client_id") or uuid.uuid4())
    timeout = min(_input_int(payload, "timeout_seconds", JOB_TIMEOUT, 1, JOB_TIMEOUT), JOB_TIMEOUT)

    queued = request_json(f"{COMFY_URL}/prompt", {"prompt": workflow, "client_id": client_id}, timeout=60)
    prompt_id = queued.get("prompt_id") if isinstance(queued, dict) else None
    if not prompt_id:
        raise RuntimeError(f"ComfyUI rejected the workflow: {queued}")

    history_item = wait_for_prompt(prompt_id, timeout)
    files = output_files(history_item)
    if not files:
        raise RuntimeError("Workflow completed but returned no video/image outputs")

    # Runpod documents a 10 MB maximum payload for /run. Base64 expands binary
    # data by about 4/3, so use a 6 MiB raw-file ceiling for inline responses.
    # Larger videos are uploaded to S3-compatible storage when configured.
    hard_inline_limit = 6 * 1024 * 1024
    requested_limit = int(os.getenv("MAX_RETURN_BYTES", str(hard_inline_limit)))
    max_bytes = min(requested_limit, hard_inline_limit)
    outputs = []
    inline_total = 0
    for item in files:
        subfolder = Path(str(item.get("subfolder") or ""))
        filename = item["filename"]
        if (
            subfolder.is_absolute()
            or ".." in subfolder.parts
            or "\\" in str(subfolder)
            or Path(filename).name != filename
            or "\\" in filename
        ):
            raise ValueError("ComfyUI returned an unsafe output path")
        path = OUTPUT_DIR / subfolder / filename
        if not path.is_file():
            continue

        size = path.stat().st_size
        content_type = "video/mp4" if path.suffix.lower() == ".mp4" else "application/octet-stream"
        stored = upload_to_object_storage(path, prompt_id)
        if stored:
            outputs.append({
                "filename": path.name,
                "kind": item["kind"],
                "mime_type": content_type,
                "size_bytes": size,
                **stored,
            })
            continue

        if inline_total + size > max_bytes:
            raise ValueError(
                f"Inline output total would exceed MAX_RETURN_BYTES={max_bytes}. "
                "Configure S3_BUCKET and S3-compatible storage credentials to return a download URL."
            )
        inline_total += size
        outputs.append({
            "filename": path.name,
            "kind": item["kind"],
            "mime_type": content_type,
            "size_bytes": size,
            "data_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
        })

    if not outputs:
        raise RuntimeError("ComfyUI reported outputs, but no output files were found")
    return {"prompt_id": prompt_id, "settings": settings, "outputs": outputs}


def handler(job: dict) -> dict:
    try:
        return handle_job(job)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:4000]
        raise RuntimeError(f"ComfyUI HTTP {exc.code}: {detail}") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-comfyui", action="store_true")
    args = parser.parse_args()
    if args.start_comfyui:
        runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
