#!/usr/bin/env python3
"""Happy Figure Edit Skill Expert MVP runner.

This runner builds the first verifiable artifact pipeline:
image -> evidence package -> baseline Run0 -> fallback SVG -> quality review.
The fallback SVG is evidence-only. PPTX export is deferred until package-run so
iteration stays focused on the final verified SVG.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

from image_assets import (
    alpha_edge_fractions,
    edge_diff_values,
    evidence_source_path,
    materialize_element_assets,
    repair_crop_nobg_boundaries,
)


PACKAGES_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGES_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGES_ROOT))
SKILL_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ImageInfo:
    source: Path
    width: int
    height: int
    mode: str
    asset_name: str


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "package-run":
        parser = argparse.ArgumentParser(description="Package a Happy Figure Edit run for delivery")
        parser.add_argument("command")
        parser.add_argument("--run-dir", required=True, help="Existing run directory")
        parser.add_argument("--out-dir", required=True, help="Delivery directory")
        parser.add_argument("--basename", required=False, help="Deprecated; ignored to avoid duplicate output copies")
        args = parser.parse_args()
        manifest_path = package_run(
            Path(args.run_dir).expanduser().resolve(strict=True),
            Path(args.out_dir).expanduser().resolve(),
            args.basename,
        )
        print(json.dumps({"status": "ok", "manifest": str(manifest_path)}, ensure_ascii=False))
        return 0

    if len(sys.argv) > 1 and sys.argv[1] == "apply-response":
        parser = argparse.ArgumentParser(description="Apply a Happy Figure Edit Expert response")
        parser.add_argument("command")
        parser.add_argument("--run-dir", required=True, help="Existing run directory")
        parser.add_argument("--response", required=True, help="Expert response JSON path")
        args = parser.parse_args()
        status_path = apply_expert_response(
            Path(args.run_dir).expanduser().resolve(strict=True),
            Path(args.response).expanduser().resolve(strict=True),
        )
        print(json.dumps({"status": "ok", "run_status": str(status_path)}, ensure_ascii=False))
        return 0

    parser = argparse.ArgumentParser(description="Run Happy Figure Edit Skill Expert MVP")
    parser.add_argument("--image", required=True, help="Input image path")
    parser.add_argument("--out-dir", required=True, help="Output run directory")
    args = parser.parse_args()

    image_path = Path(args.image).expanduser().resolve(strict=True)
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    info = inspect_image(image_path)
    asset_path = copy_input_asset(info, out_dir)
    evidence_path = write_evidence(info, out_dir, asset_path)
    analysis_path = write_baseline_analysis(info, out_dir)
    element_overlay_path = write_element_overlay(out_dir, read_json(analysis_path))
    svg_path = write_fallback_svg(info, out_dir, asset_path)
    quality_path = write_quality_report(out_dir, read_json(analysis_path))
    report_path = write_report(out_dir)
    status_path = write_status(
        out_dir,
        {
            "evidence": evidence_path,
            "element_overlay": element_overlay_path,
            "element_analysis": analysis_path,
            "svg": svg_path,
            "report": report_path,
            "quality_report": quality_path,
            "quality_summary": out_dir / "quality_summary.txt",
        },
    )

    print(json.dumps({"status": "ok", "run_status": str(status_path)}, ensure_ascii=False))
    return 0


def inspect_image(path: Path) -> ImageInfo:
    with Image.open(path) as image:
        width, height = image.size
        mode = image.mode
    return ImageInfo(
        source=path,
        width=width,
        height=height,
        mode=mode,
        asset_name=safe_asset_name(path),
    )


def safe_asset_name(path: Path) -> str:
    stem = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in path.stem)
    suffix = path.suffix.lower() or ".png"
    return f"{stem}{suffix}"


def copy_input_asset(info: ImageInfo, out_dir: Path) -> Path:
    assets_dir = out_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    target = assets_dir / info.asset_name
    shutil.copy2(info.source, target)
    return target


def overlay_font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttf",
        "/System/Library/Fonts/PingFang.ttc",
    ):
        path = Path(candidate)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_overlay_label(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    label: str,
    font: ImageFont.ImageFont,
    *,
    color: tuple[int, int, int, int],
) -> None:
    text_box = draw.textbbox((0, 0), label, font=font)
    pad_x = 6
    pad_y = 4
    x = int(round(xy[0]))
    y = int(round(xy[1]))
    w = text_box[2] - text_box[0] + pad_x * 2
    h = text_box[3] - text_box[1] + pad_y * 2
    draw.rectangle([x, y, x + w, y + h], fill=color)
    draw.text((x + pad_x, y + pad_y), label, fill=(255, 255, 255, 255), font=font)


def write_evidence(info: ImageInfo, out_dir: Path, asset_path: Path) -> Path:
    path = out_dir / "evidence.json"
    payload: dict[str, Any] = {
        "schema": "happyfigure.edit.skill_evidence.v1",
        "mode": "expert_mvp",
        "image": {
            "source": str(info.source),
            "width": info.width,
            "height": info.height,
            "mode": info.mode,
        },
        "artifacts": {
            "input_asset": rel(out_dir, asset_path),
        },
        "candidate_table": [
            {
                "box_id": "B001",
                "bbox": [0, 0, info.width, info.height],
                "kind": "image",
                "baseline_asset_strategy": "crop",
                "reason": "MVP baseline preserves the source image as one exact crop before Expert reconstruction.",
            }
        ],
    }
    write_json(path, payload)
    return path


def write_element_overlay(out_dir: Path, analysis: dict[str, Any]) -> Path:
    path = out_dir / "element_overlay.png"
    evidence = read_json(out_dir / "evidence.json")
    artifacts = evidence.get("artifacts")
    if not isinstance(artifacts, dict) or not isinstance(artifacts.get("input_asset"), str):
        raise ValueError("evidence.json must contain artifacts.input_asset")
    image_path = out_dir / artifacts["input_asset"]
    with Image.open(image_path) as image:
        canvas = image.convert("RGBA")

    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = overlay_font(18)
    width, height = canvas.size
    line_width = max(2, min(width, height) // 500)
    elements = analysis.get("elements")
    if not isinstance(elements, list):
        elements = []

    for element in elements:
        if not isinstance(element, dict):
            continue
        bbox = element.get("bbox")
        if not (
            isinstance(bbox, list)
            and len(bbox) == 4
            and all(isinstance(value, int) for value in bbox)
        ):
            continue
        x, y, w, h = bbox
        color = element_overlay_color(element)
        xy = [x, y, x + w, y + h]
        draw.rectangle(xy, outline=color[:3] + (235,), width=line_width, fill=color[:3] + (26,))
        box_id = str(element.get("box_id") or "?")
        kind = str(element.get("kind") or "element")
        strategy = str(element.get("asset_strategy") or "")
        label = f"{box_id} {kind} {strategy}".strip()
        label_y = y - 28 if y >= 28 else y + 4
        draw_overlay_label(draw, (x + 4, label_y), label, font, color=color[:3] + (230,))

    draw_overlay_label(
        draw,
        (12, 12),
        f"element overlay | {len(elements)} boxes",
        font,
        color=(17, 24, 39, 230),
    )
    Image.alpha_composite(canvas, layer).save(path)
    return path


def element_overlay_color(element: dict[str, Any]) -> tuple[int, int, int, int]:
    strategy = element.get("asset_strategy")
    if strategy == "crop":
        return (147, 51, 234, 255)
    if strategy == "crop_nobg":
        return (245, 158, 11, 255)
    kind = element.get("kind")
    if kind == "text":
        return (37, 99, 235, 255)
    if kind == "container":
        return (16, 185, 129, 255)
    return (34, 197, 94, 255)


def write_baseline_analysis(info: ImageInfo, out_dir: Path) -> Path:
    path = out_dir / "element_analysis.json"
    payload: dict[str, Any] = {
        "schema": "happyfigure.edit.element_analysis.v1",
        "source": "skill_expert_mvp_baseline",
        "canvas": {"width": info.width, "height": info.height},
        "strategy_summary": "Conservative MVP baseline: preserve the full image as one crop until Expert reconstruction replaces it with editable SVG primitives.",
        "elements": [
            {
                "box_id": "B001",
                "source_candidate_ids": ["B001"],
                "bbox": [0, 0, info.width, info.height],
                "kind": "image",
                "asset_strategy": "crop",
                "confidence": "high",
                "reason": "The fallback artifact must preserve visual fidelity before model-driven decomposition is available.",
                "evidence": ["Original image covers the full canvas."],
            }
        ],
        "review": {"status": "none", "notable_adjustments": []},
    }
    write_json(path, payload)
    return path


def write_fallback_svg(info: ImageInfo, out_dir: Path, asset_path: Path) -> Path:
    path = out_dir / "output.svg"
    href = rel(out_dir, asset_path)
    text = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{info.width}" height="{info.height}" viewBox="0 0 {info.width} {info.height}">
  <title>Happy Figure Edit Expert MVP fallback</title>
  <image href="{escape(href)}" x="0" y="0" width="{info.width}" height="{info.height}" preserveAspectRatio="none" data-box-id="B001" data-asset-strategy="crop"/>
</svg>
"""
    path.write_text(text, encoding="utf-8")
    return path


def apply_expert_response(out_dir: Path, response_path: Path) -> Path:
    evidence = read_json(out_dir / "evidence.json")
    image = evidence.get("image")
    if not isinstance(image, dict):
        raise ValueError("evidence.json must contain image metadata")
    width = require_int(image.get("width"), "evidence.image.width")
    height = require_int(image.get("height"), "evidence.image.height")

    response = read_json(response_path)
    if response.get("schema") != "happyfigure.edit.expert_response.v1":
        raise ValueError(f"Unexpected expert response schema: {response.get('schema')!r}")
    analysis = response.get("element_analysis")
    if not isinstance(analysis, dict):
        raise ValueError("expert response must contain element_analysis object")
    validate_element_analysis(analysis, width, height)
    validate_asset_strategy_policy(response, analysis)
    svg = response.get("svg")
    if not isinstance(svg, str) or not svg.strip():
        raise ValueError("expert response must contain non-empty svg string")
    generated_assets_path = materialize_element_assets(out_dir, analysis)
    validate_svg(svg, out_dir, width, height)

    analysis_path = out_dir / "element_analysis.json"
    svg_path = out_dir / "output.svg"
    write_json(analysis_path, analysis)
    svg_path.write_text(svg.strip() + "\n", encoding="utf-8")
    element_overlay_path = write_element_overlay(out_dir, analysis)
    quality_path = write_quality_report(out_dir, analysis)
    repair_path = repair_crop_nobg_boundaries(out_dir, response, analysis, svg, validate_svg=validate_svg)
    if repair_path is not None:
        analysis = response["element_analysis"]
        svg = response["svg"]
        write_json(analysis_path, analysis)
        svg_path.write_text(svg.strip() + "\n", encoding="utf-8")
        element_overlay_path = write_element_overlay(out_dir, analysis)
        quality_path = write_quality_report(out_dir, analysis)
    report_path = write_report(out_dir)
    response_rel_path = ensure_response_copy(out_dir, response_path)
    response_rel_path.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    outputs = {
        "evidence": out_dir / "evidence.json",
        "element_overlay": element_overlay_path,
        "element_analysis": analysis_path,
        "svg": svg_path,
        "report": report_path,
        "quality_report": quality_path,
        "quality_summary": out_dir / "quality_summary.txt",
    }
    if generated_assets_path is not None:
        outputs["generated_assets"] = generated_assets_path
    if repair_path is not None:
        outputs["crop_repair_report"] = repair_path

    return write_status(
        out_dir,
        outputs,
        mode="expert_applied",
        expert_response=response_rel_path,
        notes=["Expert response applied after local validation."],
    )


def package_run(run_dir: Path, out_dir: Path, basename: str | None = None) -> Path:
    pptx_path = ensure_final_pptx(run_dir)
    figma_paths = ensure_figma_delivery(run_dir)
    refresh_packaged_run_status(run_dir, pptx_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for filename in [
        "report.html",
        "run_status.json",
        "quality_report.json",
        "quality_summary.txt",
        "crop_repair_report.json",
        "element_overlay.png",
        "rendered.png",
        "diff.png",
        "output.svg",
        "output.pptx",
        "generated_assets.json",
        "element_analysis.json",
        "expert_response.json",
        "output.trace.json",
    ]:
        source = run_dir / filename
        if source.is_file():
            shutil.copy2(source, out_dir / filename)
            copied.append(filename)
    assets_source = run_dir / "assets"
    if assets_source.is_dir():
        shutil.copytree(assets_source, out_dir / "assets", dirs_exist_ok=True)
        copied.extend(str(path.relative_to(run_dir)) for path in sorted(assets_source.glob("**/*")) if path.is_file())
    review_source = run_dir / "review_tiles"
    if review_source.is_dir():
        shutil.copytree(review_source, out_dir / "review_tiles", dirs_exist_ok=True)
        copied.extend(str(path.relative_to(run_dir)) for path in sorted(review_source.glob("**/*")) if path.is_file())
    asset_review_source = run_dir / "asset_review_tiles"
    if asset_review_source.is_dir():
        shutil.copytree(asset_review_source, out_dir / "asset_review_tiles", dirs_exist_ok=True)
        copied.extend(str(path.relative_to(run_dir)) for path in sorted(asset_review_source.glob("**/*")) if path.is_file())
    figma_source = run_dir / "figma"
    if figma_source.is_dir():
        shutil.copytree(figma_source, out_dir / "figma", dirs_exist_ok=True)
        copied.extend(str(path.relative_to(run_dir)) for path in sorted(figma_source.glob("**/*")) if path.is_file())
    refs = report_relative_refs(out_dir / "report.html")
    missing_refs = [ref for ref in refs if not (out_dir / ref).exists()]
    manifest = {
        "schema": "happyfigure.edit.delivery_package.v1",
        "source_run": str(run_dir),
        "delivery_dir": str(out_dir),
        "copied": sorted(set(copied)),
        "report_refs": refs,
        "missing_report_refs": missing_refs,
    }
    manifest_path = out_dir / "delivery_manifest.json"
    write_json(manifest_path, manifest)
    if missing_refs:
        raise ValueError(f"delivery report has missing relative refs: {missing_refs}")
    return manifest_path


def ensure_figma_delivery(run_dir: Path) -> dict[str, Path]:
    evidence = read_json(run_dir / "evidence.json")
    image = evidence.get("image") if isinstance(evidence.get("image"), dict) else {}
    width = require_int(image.get("width"), "evidence.image.width")
    height = require_int(image.get("height"), "evidence.image.height")
    analysis = read_json(run_dir / "element_analysis.json")
    validate_element_analysis(analysis, width, height)
    svg_path = run_dir / "output.svg"
    if not svg_path.is_file():
        raise ValueError(f"Cannot package Figma assets without final output.svg: {svg_path}")
    svg = svg_path.read_text(encoding="utf-8").strip()
    if not svg:
        raise ValueError(f"Cannot package Figma assets with empty output.svg: {svg_path}")
    validate_svg(svg, run_dir, width, height)

    figma_dir = run_dir / "figma"
    figma_dir.mkdir(parents=True, exist_ok=True)
    figma_svg = embed_svg_assets_as_data_uris(svg, run_dir)
    figma_svg = normalize_svg_for_figma(figma_svg)
    figma_svg_path = figma_dir / "output.figma.svg"
    figma_payload_path = figma_dir / "figma_payload.json"
    figma_svg_path.write_text(figma_svg + "\n", encoding="utf-8")
    write_json(
        figma_payload_path,
        {
            "schema": "happyfigure.edit.figma_payload.v1",
            "canvas": {"width": width, "height": height},
            "files": {
                "canonical_svg": "../output.svg",
                "figma_svg": "output.figma.svg",
                "assets_dir": "../assets",
            },
            "svg": svg,
            "figma_svg": figma_svg,
            "element_analysis": analysis,
            "assets": figma_payload_assets(svg, run_dir, analysis),
        },
    )
    return {"figma_svg": figma_svg_path, "figma_payload": figma_payload_path}


def normalize_svg_for_figma(svg: str) -> str:
    """Rewrite ElementTree-style ns0: prefixed SVG into default-namespace SVG.

    Figma's SVG importer requires <svg xmlns="..."> with unprefixed child
    element names (e.g. <rect>, <text>). ElementTree emits <ns0:svg
    xmlns:ns0="..."> with every child prefixed, which Figma rejects with
    "Unable to convert SVG". This normalizer strips the ns0 prefix.
    """
    svg = re.sub(r"\bxmlns:ns0=", "xmlns=", svg)
    svg = re.sub(r"(</?)ns0:", r"\1", svg)
    return svg


def embed_svg_assets_as_data_uris(svg: str, run_dir: Path) -> str:
    def replace(match: re.Match[str]) -> str:
        attr = match.group("attr")
        quote = match.group("quote")
        href = match.group("href")
        asset_path = run_dir / href
        if not asset_path.is_file():
            raise ValueError(f"Cannot embed missing SVG asset for Figma: {href}")
        data = base64.b64encode(asset_path.read_bytes()).decode("ascii")
        return f"{attr}={quote}data:{mime_type_for_asset(asset_path)};base64,{data}{quote}"

    return re.sub(
        r'(?P<attr>(?:href|xlink:href))=(?P<quote>["\'])(?P<href>assets/[^"\']+)(?P=quote)',
        replace,
        svg,
    )


def figma_payload_assets(svg: str, run_dir: Path, analysis: dict[str, Any]) -> dict[str, dict[str, Any]]:
    asset_refs = sorted(set(re.findall(r'(?:href|xlink:href)=["\'](assets/[^"\']+)["\']', svg)))
    by_path: dict[str, str] = {}
    for element in analysis.get("elements", []):
        if not isinstance(element, dict):
            continue
        box_id = element.get("box_id")
        if isinstance(box_id, str) and box_id:
            by_path[f"assets/{box_id}.png"] = box_id

    assets: dict[str, dict[str, Any]] = {}
    for href in asset_refs:
        asset_path = run_dir / href
        if not asset_path.is_file():
            raise ValueError(f"Cannot include missing Figma payload asset: {href}")
        key = by_path.get(href) or Path(href).stem
        assets[key] = {
            "path": f"../{href}",
            "mime_type": mime_type_for_asset(asset_path),
            "byte_size": asset_path.stat().st_size,
            "data_base64": base64.b64encode(asset_path.read_bytes()).decode("ascii"),
        }
    return assets


def mime_type_for_asset(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".gif":
        return "image/gif"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".svg":
        return "image/svg+xml"
    return "image/png"


def ensure_final_pptx(run_dir: Path) -> Path:
    evidence = read_json(run_dir / "evidence.json")
    image = evidence.get("image") if isinstance(evidence.get("image"), dict) else {}
    width = require_int(image.get("width"), "evidence.image.width")
    height = require_int(image.get("height"), "evidence.image.height")
    analysis = read_json(run_dir / "element_analysis.json")
    validate_element_analysis(analysis, width, height)
    svg_path = run_dir / "output.svg"
    if not svg_path.is_file():
        raise ValueError(f"Cannot package run without final output.svg: {svg_path}")
    svg = svg_path.read_text(encoding="utf-8").strip()
    if not svg:
        raise ValueError(f"Cannot package run with empty output.svg: {svg_path}")
    validate_svg(svg, run_dir, width, height)
    return write_editable_pptx_from_analysis(width, height, run_dir, analysis, svg)


def refresh_packaged_run_status(run_dir: Path, pptx_path: Path) -> Path:
    outputs = {
        "evidence": run_dir / "evidence.json",
        "element_overlay": run_dir / "element_overlay.png",
        "element_analysis": run_dir / "element_analysis.json",
        "svg": run_dir / "output.svg",
        "pptx": pptx_path,
        "pptx_trace": run_dir / "output.trace.json",
        "report": run_dir / "report.html",
        "quality_report": run_dir / "quality_report.json",
        "quality_summary": run_dir / "quality_summary.txt",
    }
    optional_outputs = {
        "generated_assets": run_dir / "generated_assets.json",
        "crop_repair_report": run_dir / "crop_repair_report.json",
        "figma_svg": run_dir / "figma" / "output.figma.svg",
        "figma_payload": run_dir / "figma" / "figma_payload.json",
    }
    for key, path in optional_outputs.items():
        if path.is_file():
            outputs[key] = path
    expert_response = run_dir / "expert_response.json"
    return write_status(
        run_dir,
        outputs,
        mode="packaged",
        expert_response=expert_response if expert_response.is_file() else None,
        notes=["Final SVG verified and exported to editable PPTX during package-run."],
    )

def report_relative_refs(path: Path) -> list[str]:
    if not path.is_file():
        return []
    html = path.read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|data)="([^"]+)"', html)
    return [
        ref
        for ref in refs
        if not ref.startswith(("http://", "https://", "data:", "file://", "#"))
        and ".." not in Path(ref).parts
    ]


def validate_element_analysis(analysis: dict[str, Any], width: int, height: int) -> None:
    if analysis.get("schema") != "happyfigure.edit.element_analysis.v1":
        raise ValueError(f"Unexpected element analysis schema: {analysis.get('schema')!r}")
    canvas = analysis.get("canvas")
    if not isinstance(canvas, dict):
        raise ValueError("element_analysis.canvas must be an object")
    if canvas.get("width") != width or canvas.get("height") != height:
        raise ValueError("element_analysis canvas must match evidence image dimensions")
    elements = analysis.get("elements")
    if not isinstance(elements, list) or not elements:
        raise ValueError("element_analysis.elements must be a non-empty list")
    for index, element in enumerate(elements):
        if not isinstance(element, dict):
            raise ValueError(f"element {index} must be an object")
        box_id = element.get("box_id")
        if not isinstance(box_id, str) or not box_id:
            raise ValueError(f"element {index} must contain box_id")
        strategy = element.get("asset_strategy")
        if strategy not in {"svg_self_draw", "crop", "crop_nobg"}:
            raise ValueError(f"element {box_id} has invalid asset_strategy: {strategy!r}")
        bbox = element.get("bbox")
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or not all(isinstance(value, int) for value in bbox)
        ):
            raise ValueError(f"element {box_id} bbox must be four integers")
        x, y, w, h = bbox
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
            raise ValueError(f"element {box_id} bbox is outside the canvas")


def validate_asset_strategy_policy(response: dict[str, Any], analysis: dict[str, Any]) -> None:
    elements = analysis.get("elements")
    if not isinstance(elements, list):
        return
    icon_kinds = {"icon", "logo", "badge", "button", "avatar", "symbol", "glyph"}
    has_crop_nobg = any(
        isinstance(element, dict) and element.get("asset_strategy") == "crop_nobg"
        for element in elements
    )
    for element in elements:
        if not isinstance(element, dict):
            continue
        kind = str(element.get("kind") or "").lower()
        box_id = str(element.get("box_id") or "")
        if kind in icon_kinds and element.get("asset_strategy") == "svg_self_draw":
            raise ValueError(
                f"element {box_id} is kind={kind!r}; icons/logos/badges/buttons/avatars/symbols "
                "must use crop_nobg instead of simplified SVG line art"
            )
    corpus = json.dumps(
        {
            "strategy_summary": analysis.get("strategy_summary"),
            "review": analysis.get("review"),
            "elements": elements,
            "notes": response.get("notes"),
        },
        ensure_ascii=False,
    ).lower()
    mentions_icon_subject = any(
        token in corpus
        for token in [
            "icon",
            "icons",
            "logo",
            "logos",
            "badge",
            "badges",
            "avatar",
            "avatars",
            "symbol",
            "symbols",
            "small icons",
            "complex small",
            "图标",
            "徽标",
            "头像",
            "复杂小符号",
        ]
    )
    mentions_simplification = any(
        token in corpus
        for token in [
            "simplified",
            "simplify",
            "approx",
            "approximate",
            "reconstructed manually",
            "editable geometry",
            "line art",
            "简化",
            "近似",
            "线条",
        ]
    )
    if mentions_icon_subject and mentions_simplification and not has_crop_nobg:
        raise ValueError(
            "expert response says icon/logo/badge/avatar/symbol content was simplified, "
            "but no crop_nobg element was provided. Split those foreground objects into "
            "tight bbox crop_nobg elements and reference assets/<box_id>.png in the SVG."
        )


def validate_svg(svg: str, out_dir: Path, width: int, height: int) -> None:
    lowered = svg.lower()
    forbidden = [
        "file://",
        "data:",
        "base64",
        "<style",
        "<filter",
        "<mask",
        "<clippath",
        "<foreignobject",
        "<textpath",
        "<symbol",
        "<use",
    ]
    for token in forbidden:
        if token in lowered:
            raise ValueError(f"SVG contains forbidden token: {token}")
    root = ET.fromstring(svg)
    if local_name(root.tag) != "svg":
        raise ValueError("SVG root must be <svg>")
    if root.attrib.get("viewBox") != f"0 0 {width} {height}":
        raise ValueError("SVG viewBox must match evidence image dimensions")
    if root.attrib.get("width") != str(width) or root.attrib.get("height") != str(height):
        raise ValueError("SVG width/height must match evidence image dimensions")
    for element in root.iter():
        for attr_name, attr_value in element.attrib.items():
            if attr_name.endswith("href") and (
                attr_value.startswith("http://")
                or attr_value.startswith("https://")
                or attr_value.startswith("file://")
            ):
                raise ValueError(f"SVG href must not be external or file URL: {attr_value}")
        if local_name(element.tag) == "image":
            href = image_href(element)
            if not href:
                raise ValueError("SVG image element must contain href")
            if href.startswith("/") or ".." in Path(href).parts:
                raise ValueError(f"SVG image href must be a safe relative path: {href}")
            if not href.startswith("assets/"):
                raise ValueError(f"SVG image href must be under assets/: {href}")
            if not (out_dir / href).is_file():
                raise ValueError(f"SVG image href does not exist: {href}")


def write_editable_pptx_from_analysis(
    width_px: int,
    height_px: int,
    out_dir: Path,
    analysis: dict[str, Any],
    svg: str | None = None,
) -> Path:
    if not svg:
        raise ValueError("DrawAI SVG-to-PPTX export requires a non-empty SVG")
    pptx_path = out_dir / "output.pptx"
    svg_path = out_dir / "output.svg"
    trace_path = out_dir / "output.trace.json"
    if svg_path.read_text(encoding="utf-8").strip() != svg.strip():
        svg_path.write_text(svg.strip() + "\n", encoding="utf-8")
    for generated_path in (pptx_path, trace_path):
        if generated_path.exists() and generated_path.is_file():
            generated_path.unlink()

    from happyfigure_edit_skill._vendor.svg_pptx_converter.svg_to_pptx.pptx_builder import (
        create_pptx_with_native_svg,
    )

    ok = create_pptx_with_native_svg(
        [svg_path],
        pptx_path,
        canvas_format=None,
        verbose=False,
        transition=None,
        use_native_shapes=True,
        enable_notes=False,
        animation=None,
        merge_paragraphs=True,
        conversion_trace_path=trace_path,
        doc_metadata={
            "title": pptx_path.stem,
            "subject": "Happy Figure Edit native SVG-to-PPTX conversion",
        },
    )
    if not ok or not pptx_path.exists():
        raise RuntimeError(f"DrawAI SVG-to-PPTX converter did not write {pptx_path}")
    return pptx_path


def element_label(element: dict[str, Any]) -> str:
    for key in ("label", "text", "visual_role", "box_id"):
        value = element.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    reason = element.get("reason")
    if isinstance(reason, str) and reason:
        return reason.split(" is ", 1)[0][:80]
    return str(element.get("box_id") or "element")


def ensure_response_copy(out_dir: Path, response_path: Path) -> Path:
    target = out_dir / "expert_response.json"
    if response_path.resolve() != target.resolve():
        shutil.copy2(response_path, target)
    return target


def write_report(out_dir: Path) -> Path:
    path = out_dir / "report.html"
    input_asset = "assets/attention__nano-banana-pro.png"
    evidence_path = out_dir / "evidence.json"
    if evidence_path.exists():
        try:
            evidence = read_json(evidence_path)
            artifacts = evidence.get("artifacts")
            if isinstance(artifacts, dict) and isinstance(artifacts.get("input_asset"), str):
                input_asset = artifacts["input_asset"]
        except Exception:
            input_asset = "assets/attention__nano-banana-pro.png"
    status_text = read_text_if_exists(out_dir / "run_status.json", "run_status.json will be available after status is written.")
    analysis_text = read_text_if_exists(out_dir / "element_analysis.json", "element_analysis.json not found.")
    quality_text = read_text_if_exists(out_dir / "quality_report.json", "quality_report.json not found.")
    quality_summary_text = read_text_if_exists(out_dir / "quality_summary.txt", "quality_summary.txt not found.")
    crop_repair_text = read_text_if_exists(out_dir / "crop_repair_report.json", "crop_repair_report.json not found.")
    top_diff_text = top_component_diff_text(out_dir / "quality_report.json")
    diff_region_text = actionable_diff_region_text(out_dir / "quality_report.json")
    review_tiles_html = review_tiles_html_text(out_dir / "quality_report.json")
    asset_review_tiles_html = asset_review_tiles_html_text(out_dir / "quality_report.json")
    html = report_template_text()
    html = (
        html.replace("__INPUT_ASSET__", escape(input_asset))
        .replace("__REPORT_DEPENDENCIES__", escape(report_dependency_text(out_dir, input_asset)))
        .replace("__TOP_DIFFS__", escape(top_diff_text))
        .replace("__ACTIONABLE_DIFF_REGIONS__", escape(diff_region_text))
        .replace("__ASSET_REVIEW_TILES__", asset_review_tiles_html)
        .replace("__REVIEW_TILES__", review_tiles_html)
        .replace("__STATUS__", escape(status_text))
        .replace("__ANALYSIS__", escape(analysis_text))
        .replace("__QUALITY__", escape(quality_text))
        .replace("__QUALITY_SUMMARY__", escape(quality_summary_text))
        .replace("__CROP_REPAIR__", escape(crop_repair_text))
    )
    path.write_text(html, encoding="utf-8")
    return path


def report_template_text() -> str:
    path = SKILL_ROOT / "assets" / "report_template.html"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return "<!doctype html><meta charset=\"utf-8\"><pre>__STATUS__</pre>"


def report_dependency_text(out_dir: Path, input_asset: str) -> str:
    required = [
        input_asset,
        "element_overlay.png",
        "output.svg",
        "rendered.png",
        "diff.png",
        "asset_review_tiles",
        "quality_summary.txt",
        "crop_repair_report.json",
    ]
    lines = []
    for ref in required:
        status = "ok" if (out_dir / ref).exists() else "missing"
        lines.append(f"{status}: {ref}")
    return "\n".join(lines)


def top_component_diff_text(path: Path) -> str:
    if not path.exists():
        return "quality_report.json not found."
    try:
        quality = read_json(path)
    except Exception as exc:
        return f"Unable to read quality_report.json: {exc}"
    rows = quality.get("top_component_diffs")
    if not isinstance(rows, list):
        rows = quality.get("component_pixel_diff")
    if not isinstance(rows, list) or not rows:
        return "No component pixel diff rows available."
    lines = []
    for row in rows[:10]:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"{row.get('box_id', '?')}: {row.get('label', '')} "
            f"mean_abs_diff={row.get('mean_abs_diff', '?')} bbox={row.get('bbox', '?')}"
        )
    return "\n".join(lines) if lines else "No component pixel diff rows available."


def actionable_diff_region_text(path: Path) -> str:
    if not path.exists():
        return "quality_report.json not found."
    try:
        quality = read_json(path)
    except Exception as exc:
        return f"Unable to read quality_report.json: {exc}"
    rows = quality.get("declared_region_review")
    if not isinstance(rows, list) or not rows:
        rows = quality.get("unassigned_diff_regions")
    if not isinstance(rows, list) or not rows:
        rows = quality.get("diff_regions")
    if not isinstance(rows, list) or not rows:
        return "No actionable diff regions available."
    lines = []
    for row in rows[:10]:
        if not isinstance(row, dict):
            continue
        near_edges = row.get("near_crop_edges")
        if isinstance(near_edges, list) and near_edges:
            edge_text = f" near_crop_edges={near_edges[:3]}"
        else:
            edge_text = ""
        tile = row.get("review_tile")
        tile_text = f" tile={tile}" if isinstance(tile, str) and tile else ""
        lines.append(
            f"priority={row.get('priority', '?')} bbox={row.get('bbox', '?')} "
            f"area={row.get('area', '?')} mean_abs_diff={row.get('mean_abs_diff', '?')} "
            f"suggestion={row.get('suggestion', '')}{edge_text}{tile_text}"
        )
    return "\n".join(lines) if lines else "No actionable diff regions available."


def review_tiles_html_text(path: Path) -> str:
    if not path.exists():
        return "<p class=\"missing\">quality_report.json not found.</p>"
    try:
        quality = read_json(path)
    except Exception as exc:
        return f"<p class=\"missing\">Unable to read quality_report.json: {escape(str(exc))}</p>"
    rows = quality.get("review_tiles")
    if not isinstance(rows, list) or not rows:
        return "<p class=\"missing\">No review tiles generated.</p>"
    blocks = []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        tile = row.get("path")
        if not isinstance(tile, str) or not tile:
            continue
        caption = (
            f"bbox={row.get('bbox', '?')} area={row.get('area', '?')} "
            f"suggestion={row.get('suggestion', '')}"
        )
        blocks.append(
            f'<figure><img src="{escape(tile)}" alt="review tile">'
            f'<figcaption>{escape(caption)}</figcaption></figure>'
        )
    return "\n".join(blocks) if blocks else "<p class=\"missing\">No review tiles generated.</p>"


def asset_review_tiles_html_text(path: Path) -> str:
    if not path.exists():
        return "<p class=\"missing\">quality_report.json not found.</p>"
    try:
        quality = read_json(path)
    except Exception as exc:
        return f"<p class=\"missing\">Unable to read quality_report.json: {escape(str(exc))}</p>"
    rows = quality.get("asset_integrity_review")
    if not isinstance(rows, list) or not rows:
        return "<p class=\"missing\">No suspicious asset crops detected.</p>"
    blocks = []
    for row in rows[:12]:
        if not isinstance(row, dict):
            continue
        tile = row.get("review_tile")
        if not isinstance(tile, str) or not tile:
            continue
        caption = (
            f"{row.get('box_id', '?')} risk={row.get('risk_level', '?')} "
            f"bbox={row.get('bbox', '?')} sides={row.get('risk_sides', [])} "
            f"suggestion={row.get('suggestion', '')}"
        )
        blocks.append(
            f'<figure><img src="{escape(tile)}" alt="asset review tile">'
            f'<figcaption>{escape(caption)}</figcaption></figure>'
        )
    return "\n".join(blocks) if blocks else "<p class=\"missing\">No suspicious asset crops detected.</p>"


def write_quality_summary(out_dir: Path, quality: dict[str, Any]) -> Path:
    path = out_dir / "quality_summary.txt"
    pixel = quality.get("pixel_diff") if isinstance(quality.get("pixel_diff"), dict) else {}
    lines = [
        "Happy Figure Edit quality summary",
        f"pixel_diff.status={pixel.get('status', 'unknown')}",
        f"mean_abs_diff={pixel.get('mean_abs_diff', 'n/a')}",
        "",
        "Review priority:",
        "1. Inspect incomplete crop/crop_nobg boundaries.",
        "2. Inspect declared_region_review tiles for high-diff content hidden inside broad zones/panels.",
        "3. Inspect unassigned_diff_regions for missing text, glyphs, or unmodeled elements.",
        "4. Ignore tiny text/icon offsets unless readability or meaning changes.",
        "",
    ]
    sections = [
        ("asset_integrity_review", quality.get("asset_integrity_review")),
        ("granularity_warnings", quality.get("granularity_warnings")),
        ("declared_region_review", quality.get("declared_region_review")),
        ("unassigned_diff_regions", quality.get("unassigned_diff_regions")),
        ("review_tiles", quality.get("review_tiles")),
    ]
    for title, rows in sections:
        lines.append(f"{title}:")
        if not isinstance(rows, list) or not rows:
            lines.append("  none")
            lines.append("")
            continue
        limit = 12 if title == "asset_integrity_review" else 5
        for index, row in enumerate(rows[:limit], start=1):
            if not isinstance(row, dict):
                continue
            tile = row.get("review_tile") or row.get("path")
            tile_text = f" tile={tile}" if isinstance(tile, str) and tile else ""
            if title == "granularity_warnings":
                lines.append(
                    f"  {index}. box_id={row.get('box_id')} kind={row.get('kind')} "
                    f"asset_strategy={row.get('asset_strategy')} bbox={row.get('bbox')} "
                    f"canvas_fraction={row.get('canvas_fraction')} warning={row.get('warning')}"
                )
            elif title == "asset_integrity_review":
                tile_text = f" tile={row.get('review_tile')}" if isinstance(row.get("review_tile"), str) else ""
                lines.append(
                    f"  {index}. box_id={row.get('box_id')} strategy={row.get('asset_strategy')} "
                    f"bbox={row.get('bbox')} risk={row.get('risk_level')} "
                    f"sides={row.get('risk_sides')} suggestion={row.get('suggestion')}{tile_text}"
                )
            else:
                lines.append(
                    f"  {index}. bbox={row.get('bbox')} area={row.get('area')} "
                    f"mean_abs_diff={row.get('mean_abs_diff', 'n/a')} "
                    f"coverage={row.get('coverage_status', 'n/a')} "
                    f"suggestion={row.get('suggestion', '')}{tile_text}"
                )
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def read_text_if_exists(path: Path, fallback: str) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return fallback


def write_quality_report(out_dir: Path, analysis: dict[str, Any]) -> Path:
    path = out_dir / "quality_report.json"
    canvas = analysis.get("canvas") if isinstance(analysis.get("canvas"), dict) else {}
    width = canvas.get("width")
    height = canvas.get("height")
    elements = analysis.get("elements")
    components: list[dict[str, Any]] = []
    if isinstance(elements, list):
        for element in elements:
            if not isinstance(element, dict):
                continue
            bbox = element.get("bbox")
            if not (
                isinstance(bbox, list)
                and len(bbox) == 4
                and all(isinstance(value, int) for value in bbox)
            ):
                continue
            x, y, w, h = bbox
            components.append(
                {
                    "box_id": element.get("box_id"),
                    "label": element_label(element),
                    "kind": element.get("kind"),
                    "asset_strategy": element.get("asset_strategy"),
                    "bbox": bbox,
                    "center": [round(x + w / 2, 2), round(y + h / 2, 2)],
                    "area": w * h,
                    "canvas_fraction": round((w * h) / (width * height), 6)
                    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0
                    else None,
                    "bbox_diff": {
                        "status": "self_baseline",
                        "dx": 0,
                        "dy": 0,
                        "dw": 0,
                        "dh": 0,
                    },
                }
            )
    (
        pixel_diff,
        component_pixel_diff,
        diff_regions,
        unassigned_diff_regions,
        declared_region_review,
        review_tiles,
        asset_integrity_review,
    ) = compute_pixel_diff(out_dir, components)
    top_component_diffs = component_pixel_diff[:10]
    granularity_warnings = component_granularity_warnings(components)
    payload = {
        "schema": "happyfigure.edit.quality_report.v1",
        "component_count": len(components),
        "components": components,
        "granularity_warnings": granularity_warnings,
        "pixel_diff": pixel_diff,
        "component_pixel_diff": component_pixel_diff,
        "top_component_diffs": top_component_diffs,
        "diff_regions": diff_regions,
        "unassigned_diff_regions": unassigned_diff_regions,
        "declared_region_review": declared_region_review,
        "review_tiles": review_tiles,
        "asset_integrity_review": asset_integrity_review,
    }
    write_json(path, payload)
    write_quality_summary(out_dir, payload)
    return path


def compute_pixel_diff(
    out_dir: Path,
    components: list[dict[str, Any]],
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    try:
        evidence = read_json(out_dir / "evidence.json")
        image = evidence.get("image") if isinstance(evidence.get("image"), dict) else {}
        width = require_int(image.get("width"), "evidence.image.width")
        height = require_int(image.get("height"), "evidence.image.height")
        source = evidence_source_path(out_dir, evidence)
        rendered = render_svg_with_resvg(out_dir, width, height)
        original = Image.open(source).convert("RGB").resize((width, height))
        rendered_img = Image.open(rendered).convert("RGB").resize((width, height))
        diff = ImageChops.difference(original, rendered_img)
        diff_path = out_dir / "diff.png"
        amplified = diff.point(lambda value: min(255, value * 4))
        amplified.save(diff_path)
        stat = ImageStat.Stat(diff)
        mean_abs = round(sum(stat.mean) / len(stat.mean), 4)
        rms = round(sum(value * value for value in stat.rms) ** 0.5 / len(stat.rms), 4)
        component_rows = component_diffs(diff, components)
        diff_regions = connected_diff_regions(diff, components)
        unassigned_regions = [
            region
            for region in diff_regions
            if region["coverage_status"] == "unassigned"
        ][:20]
        declared_review = [
            region
            for region in diff_regions
            if region["coverage_status"] == "weakly_covered"
        ][:20]
        review_tiles = write_review_tiles(out_dir, original, rendered_img, amplified, diff_regions)
        asset_integrity_review = write_asset_review_tiles(out_dir, original, rendered_img, diff, components)
        return (
            {
                "status": "ok",
                "rendered_png": rel(out_dir, rendered),
                "diff_png": rel(out_dir, diff_path),
                "mean_abs_diff": mean_abs,
                "rms_diff": rms,
                "note": "Pixel diff compares current rendered SVG against the original image. High values indicate visual mismatch or layout drift.",
            },
            component_rows,
            diff_regions,
            unassigned_regions,
            declared_review,
            review_tiles,
            asset_integrity_review,
        )
    except Exception as exc:
        return (
            {
                "status": "unavailable",
                "reason": str(exc),
            },
            [],
            [],
            [],
            [],
            [],
            [],
        )


def render_svg_with_resvg(out_dir: Path, width: int, height: int) -> Path:
    rendered = out_dir / "rendered.png"
    resvg = shutil.which("resvg")
    if not resvg:
        raise RuntimeError(
            "resvg is required for pixel diff rendering. Install it with `brew install resvg` "
            "or continue without pixel diff; SVG/PPTX generation is unaffected."
        )
    result = subprocess.run(
        [
            resvg,
            "--resources-dir",
            str(out_dir),
            "--width",
            str(width),
            "--height",
            str(height),
            str(out_dir / "output.svg"),
            str(rendered),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"resvg failed to render output.svg: {detail}")
    if not rendered.is_file():
        raise RuntimeError("resvg completed but did not create rendered.png")
    return rendered


def component_diffs(diff: Image.Image, components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    width, height = diff.size
    for component in components:
        bbox = component.get("bbox")
        if not (
            isinstance(bbox, list)
            and len(bbox) == 4
            and all(isinstance(value, int) for value in bbox)
        ):
            continue
        x, y, w, h = bbox
        left = max(0, x)
        top = max(0, y)
        right = min(width, x + w)
        bottom = min(height, y + h)
        if right <= left or bottom <= top:
            continue
        crop = diff.crop((left, top, right, bottom))
        stat = ImageStat.Stat(crop)
        mean_abs = round(sum(stat.mean) / len(stat.mean), 4)
        rows.append(
            {
                "box_id": component.get("box_id"),
                "label": component.get("label"),
                "bbox": bbox,
                "mean_abs_diff": mean_abs,
            }
        )
    rows.sort(key=lambda item: item["mean_abs_diff"], reverse=True)
    return rows


def write_asset_review_tiles(
    out_dir: Path,
    original: Image.Image,
    rendered: Image.Image,
    raw_diff: Image.Image,
    components: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    review_dir = out_dir / "asset_review_tiles"
    if review_dir.exists():
        shutil.rmtree(review_dir)
    review_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for component in components:
        strategy = component.get("asset_strategy")
        if strategy not in {"crop", "crop_nobg"}:
            continue
        row = asset_integrity_row(out_dir, raw_diff, component)
        if row is None:
            continue
        rows.append(row)

    rows.sort(key=lambda item: (item.get("priority", 0), item.get("risk_score", 0)), reverse=True)
    selected = rows[:24]
    for index, row in enumerate(selected, start=1):
        tile_path = review_dir / f"asset_{index:02d}_{safe_filename(str(row.get('box_id') or 'asset'))}.png"
        write_asset_review_tile(
            tile_path,
            original,
            rendered,
            out_dir / str(row.get("asset_path")),
            row.get("bbox"),
            str(row.get("suggestion") or "asset integrity review"),
        )
        row["review_tile"] = rel(out_dir, tile_path)
    return selected


def asset_integrity_row(out_dir: Path, raw_diff: Image.Image, component: dict[str, Any]) -> dict[str, Any] | None:
    box_id = str(component.get("box_id") or "").strip()
    bbox = component.get("bbox")
    if not box_id or not (
        isinstance(bbox, list)
        and len(bbox) == 4
        and all(isinstance(value, int) for value in bbox)
    ):
        return None
    asset_path = out_dir / "assets" / f"{safe_filename(box_id)}.png"
    if not asset_path.is_file():
        return None

    edge_alpha: dict[str, float] = {}
    if component.get("asset_strategy") == "crop_nobg":
        with Image.open(asset_path) as asset:
            edge_alpha = alpha_edge_fractions(asset.convert("RGBA").getchannel("A"))

    risk_sides: list[str] = []
    side_details: dict[str, Any] = {}
    risk_score = 0
    for side in ("left", "right", "top", "bottom"):
        values = edge_diff_values(raw_diff, bbox, side, 24)
        numeric = [value for value in values if value is not None]
        high_values = [value for value in numeric if value >= 32]
        alpha_fraction = edge_alpha.get(side, 0.0)
        max_diff = max(numeric) if numeric else 0.0
        high_run = longest_high_run(values, 32)
        side_risk = False
        reasons: list[str] = []
        if alpha_fraction >= 0.2:
            side_risk = True
            risk_score += 3
            reasons.append("foreground alpha touches crop edge")
        elif alpha_fraction >= 0.03 and max_diff >= 48:
            side_risk = True
            risk_score += 2
            reasons.append("thin foreground edge plus outside diff")
        if len(high_values) >= 3 and (max_diff >= 60 or high_run >= 2):
            side_risk = True
            risk_score += 2
            reasons.append("raw diff continues outside bbox")
        elif max_diff >= 128:
            side_risk = True
            risk_score += 1
            reasons.append("strong one-pixel outside edge near bbox")
        if side_risk:
            risk_sides.append(side)
        side_details[side] = {
            "alpha_edge_fraction": alpha_fraction,
            "max_outside_diff": round(max_diff, 4),
            "high_diff_count": len(high_values),
            "longest_high_run": high_run,
            "reasons": reasons,
        }

    if not risk_sides:
        return None

    risk_level = "high" if risk_score >= 6 else "medium"
    strategy = component.get("asset_strategy")
    suggestion = (
        "suspected incomplete crop_nobg or missing icon/card background; inspect original bbox context and expand bbox or split SVG card + foreground icon."
        if strategy == "crop_nobg"
        else "suspected incomplete crop; inspect original bbox context and expand crop if the raster region is cut off."
    )
    return {
        "box_id": box_id,
        "kind": component.get("kind"),
        "asset_strategy": strategy,
        "bbox": bbox,
        "asset_path": f"assets/{safe_filename(box_id)}.png",
        "risk_level": risk_level,
        "risk_score": risk_score,
        "priority": 3 if risk_level == "high" else 2,
        "risk_sides": risk_sides,
        "side_details": side_details,
        "suggestion": suggestion,
    }


def longest_high_run(values: list[float | None], threshold: float) -> int:
    best = 0
    current = 0
    for value in values:
        if value is not None and value >= threshold:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def write_asset_review_tile(
    path: Path,
    original: Image.Image,
    rendered: Image.Image,
    asset_path: Path,
    bbox: Any,
    suggestion: str,
) -> None:
    if not (
        isinstance(bbox, list)
        and len(bbox) == 4
        and all(isinstance(value, int) for value in bbox)
    ):
        return
    x, y, w, h = bbox
    pad = 40
    crop_box = (
        max(0, x - pad),
        max(0, y - pad),
        min(original.width, x + w + pad),
        min(original.height, y + h + pad),
    )
    original_crop = original.crop(crop_box).convert("RGB")
    rendered_crop = rendered.crop(crop_box).convert("RGB")
    local_box = [x - crop_box[0], y - crop_box[1], x - crop_box[0] + w - 1, y - crop_box[1] + h - 1]
    for crop in (original_crop, rendered_crop):
        draw = ImageDraw.Draw(crop)
        draw.rectangle(local_box, outline=(220, 20, 20), width=3)

    with Image.open(asset_path) as asset_image:
        asset = checkerboard_composite(asset_image.convert("RGBA"))
    panels = [
        panel_with_title("original bbox context", original_crop, f"bbox={bbox}"),
        panel_with_title("asset on checkerboard", asset, asset_path.name),
        panel_with_title("rendered bbox context", rendered_crop, f"bbox={bbox}"),
    ]
    width = sum(panel.width for panel in panels) + 18 * (len(panels) - 1)
    height = max(panel.height for panel in panels) + 44
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text((8, height - 34), suggestion[:180], fill=(0, 0, 0))
    offset = 0
    for panel in panels:
        sheet.paste(panel, (offset, 0))
        offset += panel.width + 18
    sheet.save(path)


def checkerboard_composite(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    tile = 10
    background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    draw = ImageDraw.Draw(background)
    for y in range(0, rgba.height, tile):
        for x in range(0, rgba.width, tile):
            if (x // tile + y // tile) % 2:
                draw.rectangle([x, y, x + tile - 1, y + tile - 1], fill=(225, 230, 238, 255))
    background.alpha_composite(rgba)
    return background.convert("RGB")


def panel_with_title(title: str, image: Image.Image, subtitle: str) -> Image.Image:
    scale = min(1.0, 360 / max(1, image.width))
    resized = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))))
    panel = Image.new("RGB", (resized.width, resized.height + 54), "white")
    draw = ImageDraw.Draw(panel)
    draw.text((8, 8), title, fill=(0, 0, 0))
    draw.text((8, 28), subtitle[:80], fill=(80, 80, 80))
    panel.paste(resized, (0, 54))
    return panel


def safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


def connected_diff_regions(diff: Image.Image, components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rgb_diff = diff.convert("RGB")
    width, height = rgb_diff.size
    pixels = rgb_diff.load()
    threshold = 48
    min_area = max(18, (width * height) // 30000)
    seen: set[tuple[int, int]] = set()
    rows: list[dict[str, Any]] = []

    for y in range(height):
        for x in range(width):
            if (x, y) in seen or max(pixels[x, y]) < threshold:
                continue
            queue = [(x, y)]
            seen.add((x, y))
            component_pixels: list[tuple[int, int]] = []
            total = 0
            while queue:
                cx, cy = queue.pop()
                component_pixels.append((cx, cy))
                total += sum(pixels[cx, cy]) / 3
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if (
                        0 <= nx < width
                        and 0 <= ny < height
                        and (nx, ny) not in seen
                        and max(pixels[nx, ny]) >= threshold
                    ):
                        seen.add((nx, ny))
                        queue.append((nx, ny))
            if len(component_pixels) < min_area:
                continue
            xs = [point[0] for point in component_pixels]
            ys = [point[1] for point in component_pixels]
            bbox = [min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1]
            row = annotate_diff_region(bbox, len(component_pixels), total / len(component_pixels), components)
            rows.append(row)

    rows.sort(key=lambda item: (item["priority"], item["area"], item["mean_abs_diff"]), reverse=True)
    return rows[:50]


def write_review_tiles(
    out_dir: Path,
    original: Image.Image,
    rendered: Image.Image,
    diff: Image.Image,
    diff_regions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    review_dir = out_dir / "review_tiles"
    if review_dir.exists():
        shutil.rmtree(review_dir)
    review_dir.mkdir(parents=True, exist_ok=True)
    selected = select_review_regions(diff_regions)
    rows: list[dict[str, Any]] = []
    for index, region in enumerate(selected, start=1):
        bbox = region.get("bbox")
        if not (
            isinstance(bbox, list)
            and len(bbox) == 4
            and all(isinstance(value, int) for value in bbox)
        ):
            continue
        tile_path = review_dir / f"review_{index:02d}.png"
        write_review_tile(tile_path, original, rendered, diff, bbox, str(region.get("suggestion") or "review"))
        region["review_tile"] = rel(out_dir, tile_path)
        rows.append(
            {
                "path": rel(out_dir, tile_path),
                "bbox": bbox,
                "area": region.get("area"),
                "priority": region.get("priority"),
                "coverage_status": region.get("coverage_status"),
                "suggestion": region.get("suggestion"),
            }
        )
    return rows


def select_review_regions(diff_regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets = [
        (
            [row for row in diff_regions if isinstance(row, dict) and str(row.get("suggestion", "")).startswith("crop_boundary_check")],
            3,
        ),
        (
            [row for row in diff_regions if isinstance(row, dict) and row.get("coverage_status") == "weakly_covered"],
            5,
        ),
        (
            [row for row in diff_regions if isinstance(row, dict) and row.get("coverage_status") == "unassigned"],
            3,
        ),
    ]
    selected: list[dict[str, Any]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for bucket, max_take in buckets:
        taken = 0
        for row in bucket:
            bbox = row.get("bbox")
            if not (
                isinstance(bbox, list)
                and len(bbox) == 4
                and all(isinstance(value, int) for value in bbox)
            ):
                continue
            key = tuple(bbox)
            if key in seen:
                continue
            seen.add(key)
            selected.append(row)
            taken += 1
            if len(selected) >= 5:
                return selected
            if taken >= max_take:
                break
    for row in diff_regions:
        bbox = row.get("bbox") if isinstance(row, dict) else None
        if not (
            isinstance(bbox, list)
            and len(bbox) == 4
            and all(isinstance(value, int) for value in bbox)
        ):
            continue
        key = tuple(bbox)
        if key in seen:
            continue
        seen.add(key)
        selected.append(row)
        if len(selected) >= 5:
            break
    return selected


def write_review_tile(
    path: Path,
    original: Image.Image,
    rendered: Image.Image,
    diff: Image.Image,
    bbox: list[int],
    suggestion: str,
) -> None:
    x, y, w, h = bbox
    pad = 24
    left = max(0, x - pad)
    top = max(0, y - pad)
    right = min(original.width, x + w + pad)
    bottom = min(original.height, y + h + pad)
    crop_box = (left, top, right, bottom)
    crops = [
        ("original", original.crop(crop_box)),
        ("rendered", rendered.crop(crop_box)),
        ("diff x4", diff.crop(crop_box)),
    ]
    panels: list[Image.Image] = []
    for title, image in crops:
        scale = min(1.0, 360 / max(1, image.width))
        resized = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))))
        panel = Image.new("RGB", (resized.width, resized.height + 54), "white")
        draw = ImageDraw.Draw(panel)
        draw.text((8, 8), title, fill=(0, 0, 0))
        draw.text((8, 28), f"bbox={bbox}", fill=(80, 80, 80))
        panel.paste(resized, (0, 54))
        panels.append(panel)
    width = sum(panel.width for panel in panels) + 18 * (len(panels) - 1)
    height = max(panel.height for panel in panels) + 44
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text((8, height - 34), suggestion[:180], fill=(0, 0, 0))
    offset = 0
    for panel in panels:
        sheet.paste(panel, (offset, 0))
        offset += panel.width + 18
    sheet.save(path)


def annotate_diff_region(
    bbox: list[int],
    area: int,
    mean_diff: float,
    components: list[dict[str, Any]],
) -> dict[str, Any]:
    overlaps: list[dict[str, Any]] = []
    edge_contacts: list[dict[str, Any]] = []
    max_overlap = 0.0
    max_strong_overlap = 0.0
    weak_overlaps: list[dict[str, Any]] = []
    strong_overlaps: list[dict[str, Any]] = []
    for component in components:
        component_bbox = component.get("bbox")
        if not (
            isinstance(component_bbox, list)
            and len(component_bbox) == 4
            and all(isinstance(value, int) for value in component_bbox)
        ):
            continue
        overlap = bbox_overlap_fraction(bbox, component_bbox)
        if overlap:
            max_overlap = max(max_overlap, overlap)
            overlap_row = {
                "box_id": component.get("box_id"),
                "kind": component.get("kind"),
                "asset_strategy": component.get("asset_strategy"),
                "overlap_fraction": overlap,
            }
            overlaps.append(overlap_row)
            if is_strong_coverage_component(component):
                max_strong_overlap = max(max_strong_overlap, overlap)
                strong_overlaps.append(overlap_row)
            else:
                weak_overlaps.append(overlap_row)
        sides = nearby_bbox_sides(bbox, component_bbox, margin=8)
        if sides and component.get("asset_strategy") in {"crop", "crop_nobg"}:
            edge_contacts.append(
                {
                    "box_id": component.get("box_id"),
                    "asset_strategy": component.get("asset_strategy"),
                    "sides": sides,
                }
            )

    overlaps.sort(key=lambda item: item["overlap_fraction"], reverse=True)
    weak_overlaps.sort(key=lambda item: item["overlap_fraction"], reverse=True)
    strong_overlaps.sort(key=lambda item: item["overlap_fraction"], reverse=True)
    coverage_status = "strongly_covered"
    if not overlaps or max_overlap < 0.25:
        coverage_status = "unassigned"
    elif weak_overlaps and max_strong_overlap < 0.25:
        coverage_status = "weakly_covered"

    suggestion = "inspect_high_diff_region"
    priority = 1
    if edge_contacts and max_overlap < 0.75:
        suggestion = "crop_boundary_check: high diff touches or sits just outside a crop/crop_nobg bbox; inspect whether the crop was cut incomplete."
        priority = 3
    elif coverage_status == "unassigned":
        suggestion = "missing_text_or_unmodeled_element: high diff is not covered by declared elements; inspect for missing text, glyph, or crop_nobg."
        priority = 2
    elif coverage_status == "weakly_covered":
        suggestion = "declared_region_review: high diff is only covered by a broad zone/panel/container; inspect the local tile for missing internal text, icons, connectors, or materially wrong structure."
        priority = 2
    elif overlaps[0].get("asset_strategy") == "svg_self_draw":
        suggestion = "declared_svg_region_diff: inspect missing characters, wrong text, or materially wrong SVG geometry; ignore tiny acceptable offsets."
        priority = 2

    return {
        "bbox": bbox,
        "area": area,
        "mean_abs_diff": round(mean_diff, 4),
        "max_overlap_fraction": round(max_overlap, 4),
        "max_strong_overlap_fraction": round(max_strong_overlap, 4),
        "coverage_status": coverage_status,
        "overlapping_elements": overlaps[:5],
        "weak_covering_elements": weak_overlaps[:5],
        "strong_covering_elements": strong_overlaps[:5],
        "near_crop_edges": edge_contacts[:5],
        "priority": priority,
        "suggestion": suggestion,
    }


def component_granularity_warnings(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for component in components:
        if component.get("asset_strategy") != "svg_self_draw":
            continue
        fraction = component.get("canvas_fraction")
        if not isinstance(fraction, (int, float)):
            continue
        kind = str(component.get("kind") or "").lower()
        warning: str | None = None
        if kind in weak_svg_kinds() and fraction >= 0.01:
            warning = "Broad structural/svg element; do not let it hide missing internal icons, cards, text, or connectors."
        elif fraction >= 0.035:
            warning = "Large svg_self_draw element; split into smaller semantic elements before trusting diff coverage."
        if warning is None:
            continue
        rows.append(
            {
                "box_id": component.get("box_id"),
                "label": component.get("label"),
                "kind": component.get("kind"),
                "asset_strategy": component.get("asset_strategy"),
                "bbox": component.get("bbox"),
                "area": component.get("area"),
                "canvas_fraction": fraction,
                "warning": warning,
            }
        )
    rows.sort(key=lambda item: item.get("canvas_fraction") or 0, reverse=True)
    return rows[:20]


def is_strong_coverage_component(component: dict[str, Any]) -> bool:
    if component.get("asset_strategy") in {"crop", "crop_nobg"}:
        return True
    kind = str(component.get("kind") or "").lower()
    fraction = component.get("canvas_fraction")
    if kind in weak_svg_kinds():
        return False
    if isinstance(fraction, (int, float)) and fraction >= 0.035:
        return False
    return True


def weak_svg_kinds() -> set[str]:
    return {
        "arrow",
        "background",
        "card",
        "connector",
        "container",
        "graph",
        "group",
        "label",
        "labels",
        "layer",
        "line",
        "module",
        "network",
        "panel",
        "region",
        "section",
        "text",
        "zone",
    }


def bbox_overlap_fraction(a: list[int], b: list[int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return 0.0
    return round(((right - left) * (bottom - top)) / max(1, aw * ah), 4)


def nearby_bbox_sides(region: list[int], bbox: list[int], margin: int) -> list[str]:
    rx, ry, rw, rh = region
    bx, by, bw, bh = bbox
    r_right = rx + rw
    r_bottom = ry + rh
    b_right = bx + bw
    b_bottom = by + bh
    vertical_overlap = ry < b_bottom and r_bottom > by
    horizontal_overlap = rx < b_right and r_right > bx
    sides: list[str] = []
    if vertical_overlap and abs(r_right - bx) <= margin:
        sides.append("left")
    if vertical_overlap and abs(rx - b_right) <= margin:
        sides.append("right")
    if horizontal_overlap and abs(r_bottom - by) <= margin:
        sides.append("top")
    if horizontal_overlap and abs(ry - b_bottom) <= margin:
        sides.append("bottom")
    return sides


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def image_href(element: ET.Element) -> str:
    for key, value in element.attrib.items():
        if key == "href" or key.endswith("}href"):
            return value
    return ""


def require_int(value: Any, label: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def write_status(
    out_dir: Path,
    outputs: dict[str, Path],
    *,
    mode: str = "expert_mvp",
    expert_response: Path | None = None,
    notes: list[str] | None = None,
) -> Path:
    path = out_dir / "run_status.json"
    payload = {
        "schema": "happyfigure.edit.skill_run_status.v1",
        "status": "ok",
        "mode": mode,
        "outputs": {key: rel(out_dir, value) for key, value in outputs.items()},
        "notes": notes or [
            "MVP fallback preserves the source image as one crop.",
            "Full editable reconstruction requires the next Expert model pass.",
        ],
    }
    if expert_response is not None:
        payload["expert_response"] = rel(out_dir, expert_response)
    write_json(path, payload)
    if "report" in outputs:
        write_report(out_dir)
    return path


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
