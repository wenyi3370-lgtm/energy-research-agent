from __future__ import annotations

import argparse
import json
from pathlib import Path

from _common import now_iso, read_json, write_json, find_presentation_project, presentation_project_hint
from presentation_production import (
    IMAGE_PIPELINE_ID,
    invoke_ewo_image,
    normalize_fallback_reason,
    stored_path,
)


PROMPT_SUFFIX = (
    " Vector illustration style with clean geometric forms, restrained deep navy, cobalt, cool gray, "
    "and white palette. No text, numbers, logos, watermarks, charts, graphs, tables, or UI labels. "
    "Professional energy-industry strategy presentation visual, crisp edges, high contrast, ample negative space."
)


def parse_runtime_failure(exc: Exception) -> dict[str, str]:
    try:
        payload = json.loads(str(exc))
        if isinstance(payload, dict) and payload.get("code"):
            return normalize_fallback_reason(str(payload["code"]), str(payload.get("detail") or payload["code"]))
    except ValueError:
        pass
    message = str(exc)
    code = "upstream_timeout" if isinstance(exc, TimeoutError) else "connection_unavailable"
    if "credential" in message.casefold():
        code = "credential_unavailable"
    return normalize_fallback_reason(code, message)


def resolve(project_dir: Path, requests_file: Path, *, offline_reason: str = "", presentation_project: Path | None = None) -> dict:
    payload = read_json(requests_file, {})
    requests = payload.get("requests") or []
    if not requests:
        raise ValueError("Image request manifest must contain a non-empty requests list")
    if presentation_project is None:
        presentation_project = find_presentation_project(project_dir)
    if presentation_project is None:
        raise ValueError("Presentation project directory not found")
    images_dir = presentation_project / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    offline_failure = None
    if offline_reason:
        code, _, detail = offline_reason.partition(":")
        offline_failure = normalize_fallback_reason(code, detail or code)

    records: list[dict] = []
    cover_failure: dict[str, str] | None = None
    for index, request in enumerate(requests, start=1):
        request_id = str(request.get("request_id") or f"image-{index}").strip()
        role = str(request.get("role") or "body").strip().casefold()
        if role not in {"cover", "body"}:
            raise ValueError(f"Unsupported image role for {request_id}: {role}")
        prompt = str(request.get("prompt") or "").strip()
        if len(prompt) < 24:
            raise ValueError(f"Image prompt is too short for {request_id}")
        output_format = str(request.get("output_format") or "png").strip().casefold()
        suffix = ".jpg" if output_format == "jpeg" else f".{output_format}"
        if suffix not in {".png", ".jpg", ".webp"}:
            raise ValueError(f"Unsupported output format for {request_id}: {output_format}")
        output = images_dir / f"{request_id}{suffix}"
        record = {
            "request_id": request_id,
            "role": role,
            "prompt": prompt + PROMPT_SUFFIX,
            "prompt_sha256": __import__("hashlib").sha256((prompt + PROMPT_SUFFIX).encode("utf-8")).hexdigest(),
            "requested_output": stored_path(output, project_dir),
            "status": "pending",
            "fallback": None,
        }
        failure = offline_failure
        if failure is None:
            try:
                result = invoke_ewo_image(
                    record["prompt"],
                    output,
                    size=str(request.get("size") or "1536x1024"),
                    output_format=output_format,
                    quality=str(request.get("quality") or "high"),
                    model=str(request.get("model") or "gpt-image-2"),
                )
                record.update(
                    {
                        "status": "generated",
                        "path": stored_path(output, project_dir),
                        **result,
                    }
                )
            except Exception as exc:  # provider/network boundary is intentionally normalized here
                failure = parse_runtime_failure(exc)
        if failure is not None:
            record["status"] = "fallback_vector" if role == "body" else "fallback_light_cover"
            record["fallback"] = failure
            if role == "cover":
                cover_failure = failure
        records.append(record)

    cover_generated = next((item for item in records if item["role"] == "cover" and item["status"] == "generated"), None)
    cover_decision = {
        "default_path": "A_ai_image",
        "path_taken": "A_ai_image" if cover_generated else "B_light_consulting",
        "ai_image_request_id": cover_generated["request_id"] if cover_generated else "",
        "fallback_reason": cover_failure or normalize_fallback_reason("upstream_failure", "Cover image was not generated"),
    }
    output_manifest = presentation_project / "image_acquisition_manifest.json"
    manifest = {
        "schema_version": 1,
        "created_at": now_iso(),
        "pipeline_id": IMAGE_PIPELINE_ID,
        "provider_priority": ["ewo", "native_powerpoint_vector_fallback"],
        "cover_decision": cover_decision,
        "requests": records,
        "_manifest_path": output_manifest.as_posix(),
    }
    write_json(output_manifest, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve EWO presentation illustrations with deterministic no-balance fallback.")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--requests", required=True)
    parser.add_argument("--presentation-project", default=None,
                help="High-fidelity presentation directory (auto-detected when omitted).")
    parser.add_argument(
        "--offline-reason",
        default="",
        help="Testing/global-disable path, e.g. insufficient_balance:test fixture. No EWO request is made.",
    )
    args = parser.parse_args()
    project_dir = Path(args.project_dir).resolve()
    requests_file = Path(args.requests)
    if not requests_file.is_absolute():
        requests_file = project_dir / requests_file
    presentation = None
    if args.presentation_project:
        presentation = Path(args.presentation_project).resolve()
        if not presentation.is_absolute():
            presentation = project_dir / presentation
    manifest = resolve(project_dir, requests_file.resolve(), offline_reason=args.offline_reason, presentation_project=presentation)
    print(manifest["_manifest_path"] if "_manifest_path" in manifest else "")
    print(f"Cover path: {manifest['cover_decision']['path_taken']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
