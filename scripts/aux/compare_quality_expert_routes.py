#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import zipfile
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Happy Figure Edit quality routes")
    parser.add_argument("--fixture-run", required=True)
    parser.add_argument("--quality-expert-run", required=True)
    parser.add_argument("--drawai-run", required=False)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    routes = {
        "fixture": summarize_run(Path(args.fixture_run).expanduser().resolve(), "手写样例"),
        "quality_expert": summarize_run(Path(args.quality_expert_run).expanduser().resolve(), "高质量专家路线"),
    }
    if args.drawai_run:
        routes["drawai_reference"] = summarize_run(Path(args.drawai_run).expanduser().resolve(), "DrawAI 参考")

    payload = {
        "schema": "happyfigure.edit.quality_comparison.v1",
        "routes": routes,
        "notes": [
            "Quality wins over cost in this phase.",
            "DrawAI reference is comparison-only and may be absent.",
        ],
    }
    (out_dir / "comparison_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "comparison_report.html").write_text(render_html(payload), encoding="utf-8")
    print(json.dumps({"status": "ok", "comparison_report": str(out_dir / "comparison_report.json")}, ensure_ascii=False))
    return 0


def summarize_run(run_dir: Path, label: str) -> dict[str, Any]:
    quality = read_json(run_dir / "quality_report.json")
    status = read_json(run_dir / "run_status.json")
    pptx = pptx_summary(run_dir / "output.pptx")
    pixel = quality.get("pixel_diff") if isinstance(quality.get("pixel_diff"), dict) else {}
    return {
        "label": label,
        "run_dir": str(run_dir),
        "status": status.get("status"),
        "mode": status.get("mode", "baseline"),
        "mean_abs_diff": pixel.get("mean_abs_diff"),
        "component_count": quality.get("component_count"),
        "top_component_diffs": quality.get("top_component_diffs", [])[:10],
        "pptx_media_count": pptx["media_count"],
        "pptx_shape_count": pptx["shape_count"],
        "pptx_connector_count": pptx["connector_count"],
        "report": str(run_dir / "report.html") if (run_dir / "report.html").exists() else "",
    }


def pptx_summary(path: Path) -> dict[str, int]:
    if not path.exists():
        return {"media_count": 0, "shape_count": 0, "connector_count": 0}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        slide = archive.read("ppt/slides/slide1.xml").decode("utf-8") if "ppt/slides/slide1.xml" in names else ""
    return {
        "media_count": sum(1 for name in names if name.startswith("ppt/media/")),
        "shape_count": slide.count("<p:sp>"),
        "connector_count": slide.count("<p:cxnSp>"),
    }


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def render_html(payload: dict[str, Any]) -> str:
    rows = []
    routes = payload.get("routes") if isinstance(payload.get("routes"), dict) else {}
    for key, route in routes.items():
        if not isinstance(route, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(route.get('label') or key))}</td>"
            f"<td>{html.escape(str(route.get('mode') or ''))}</td>"
            f"<td>{html.escape(str(route.get('mean_abs_diff') or ''))}</td>"
            f"<td>{html.escape(str(route.get('component_count') or ''))}</td>"
            f"<td>{html.escape(str(route.get('pptx_media_count') or 0))}</td>"
            f"<td>{html.escape(str(route.get('pptx_shape_count') or 0))}</td>"
            f"<td>{html.escape(str(route.get('pptx_connector_count') or 0))}</td>"
            "</tr>"
        )
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<title>Happy Figure Edit 对比报告</title>"
        "<h1>Happy Figure Edit 对比报告</h1>"
        "<table border='1' cellspacing='0' cellpadding='6'>"
        "<thead><tr><th>路线</th><th>模式</th><th>全图差异</th><th>组件数</th>"
        "<th>PPTX媒体</th><th>PPTX形状</th><th>PPTX连接线</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


if __name__ == "__main__":
    raise SystemExit(main())
