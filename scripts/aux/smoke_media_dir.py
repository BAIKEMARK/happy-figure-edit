#!/usr/bin/env python3
"""Run local artifact smoke checks for a directory of media images."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Happy Figure Edit Skill Expert on a media directory")
    parser.add_argument("--media-dir", required=True, help="Directory containing source images")
    parser.add_argument("--out-root", required=True, help="Directory where smoke runs will be written")
    args = parser.parse_args()

    media_dir = Path(args.media_dir).expanduser().resolve(strict=True)
    out_root = Path(args.out_root).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    runner = Path(__file__).resolve().parent.parent / "run_expert_mvp.py"
    rows = []
    for image in sorted(media_dir.iterdir()):
        if not image.is_file() or image.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        run_dir = out_root / safe_run_name(image)
        run_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                sys.executable,
                str(runner),
                "--image",
                str(image),
                "--out-dir",
                str(run_dir),
            ],
            check=True,
        )
        rows.append(summarize_run(image, run_dir))

    summary_path = out_root / "summary.json"
    summary = {
        "schema": "happyfigure.edit.media_smoke_summary.v1",
        "media_dir": str(media_dir),
        "out_root": str(out_root),
        "count": len(rows),
        "runs": rows,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "summary": str(summary_path), "count": len(rows)}, ensure_ascii=False))
    return 0


def safe_run_name(image: Path) -> str:
    stem = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in image.stem)
    return stem or "image"


def summarize_run(image: Path, run_dir: Path) -> dict[str, Any]:
    quality = read_json(run_dir / "quality_report.json")
    pixel_diff = quality.get("pixel_diff") if isinstance(quality.get("pixel_diff"), dict) else {}
    with zipfile.ZipFile(run_dir / "output.pptx") as archive:
        names = archive.namelist()
        slide = archive.read("ppt/slides/slide1.xml").decode("utf-8")
    media_entries = [name for name in names if name.startswith("ppt/media/")]
    return {
        "image": str(image),
        "run_dir": str(run_dir),
        "status": read_json(run_dir / "run_status.json").get("status"),
        "svg_exists": (run_dir / "output.svg").is_file(),
        "pptx_exists": (run_dir / "output.pptx").is_file(),
        "report_exists": (run_dir / "report.html").is_file(),
        "rendered_png_exists": (run_dir / str(pixel_diff.get("rendered_png", ""))).is_file()
        if isinstance(pixel_diff.get("rendered_png"), str)
        else False,
        "diff_png_exists": (run_dir / str(pixel_diff.get("diff_png", ""))).is_file()
        if isinstance(pixel_diff.get("diff_png"), str)
        else False,
        "pixel_diff_status": pixel_diff.get("status"),
        "mean_abs_diff": pixel_diff.get("mean_abs_diff"),
        "pptx_media_count": len(media_entries),
        "pptx_shape_count": slide.count("<p:sp>"),
        "pptx_connector_count": slide.count("<p:cxnSp>"),
    }


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
