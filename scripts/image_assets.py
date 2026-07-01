"""Image asset extraction and crop_nobg repair for Happy Figure Edit skill runs."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from PIL import Image, ImageChops, ImageStat


def materialize_element_assets(out_dir: Path, analysis: dict[str, Any]) -> Path | None:
    elements = analysis.get("elements")
    if not isinstance(elements, list):
        return None
    evidence = read_json(out_dir / "evidence.json")
    source = evidence_source_path(out_dir, evidence)
    assets_dir = out_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    generated: dict[str, Any] = {}

    with Image.open(source) as original:
        width, height = original.size
        for element in elements:
            if not isinstance(element, dict):
                continue
            strategy = element.get("asset_strategy")
            if strategy not in {"crop", "crop_nobg"}:
                continue
            box_id = str(element.get("box_id") or "").strip()
            bbox = element.get("bbox")
            if not box_id or not isinstance(bbox, list) or len(bbox) != 4:
                continue
            x, y, w, h = [int(value) for value in bbox]
            padding = crop_padding(element)
            left = max(0, x - padding)
            top = max(0, y - padding)
            right = min(width, x + w + padding)
            bottom = min(height, y + h + padding)
            if right <= left or bottom <= top:
                continue
            cropped = original.crop((left, top, right, bottom))
            if strategy == "crop_nobg":
                cropped = remove_background_alpha(cropped)
            filename = f"{safe_box_asset_stem(box_id)}.png"
            asset_path = assets_dir / filename
            cropped.save(asset_path)
            generated[box_id] = {
                "path": rel(out_dir, asset_path),
                "strategy": strategy,
                "bbox": bbox,
                "crop_bbox": [left, top, right - left, bottom - top],
            }

    if not generated:
        return None
    manifest_path = out_dir / "generated_assets.json"
    write_json(
        manifest_path,
        {
            "schema": "happyfigure.edit.generated_assets.v1",
            "assets": generated,
        },
    )
    return manifest_path


def repair_crop_nobg_boundaries(
    out_dir: Path,
    response: dict[str, Any],
    analysis: dict[str, Any],
    svg: str,
    *,
    validate_svg: Callable[[str, Path, int, int], None],
) -> Path | None:
    elements = analysis.get("elements")
    if not isinstance(elements, list):
        return None
    evidence = read_json(out_dir / "evidence.json")
    image = evidence.get("image") if isinstance(evidence.get("image"), dict) else {}
    width = require_int(image.get("width"), "evidence.image.width")
    height = require_int(image.get("height"), "evidence.image.height")
    source = evidence_source_path(out_dir, evidence)
    rendered_path = out_dir / "rendered.png"
    generated_path = out_dir / "generated_assets.json"
    generated = read_json(generated_path) if generated_path.is_file() else {"assets": {}}
    generated_assets = generated.get("assets") if isinstance(generated.get("assets"), dict) else {}
    report_path = out_dir / "crop_repair_report.json"

    if not rendered_path.is_file():
        write_json(
            report_path,
            {
                "schema": "happyfigure.edit.crop_repair_report.v1",
                "status": "unavailable",
                "reason": "rendered.png not available; resvg rendering is required for diff-guided crop repair.",
                "applied": [],
                "review": [],
            },
        )
        return report_path

    applied: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    replacements: dict[str, list[int]] = {}

    with Image.open(source) as original_image, Image.open(rendered_path) as rendered_image:
        original = original_image.convert("RGBA").resize((width, height))
        rendered = rendered_image.convert("RGBA").resize((width, height))
        raw_diff = ImageChops.difference(original.convert("RGB"), rendered.convert("RGB"))

        for element in elements:
            if not isinstance(element, dict) or element.get("asset_strategy") != "crop_nobg":
                continue
            box_id = str(element.get("box_id") or "").strip()
            bbox = element.get("bbox")
            if not box_id or not valid_image_bbox(bbox, (width, height)):
                continue
            candidate = crop_nobg_repair_candidate(out_dir, original, rendered, raw_diff, element, generated_assets)
            if candidate is None:
                continue
            if candidate["decision"] == "apply":
                candidate_bbox = candidate["bbox"]
                candidate_image = repair_candidate_image(original, bbox, candidate_bbox, candidate)
                asset_path = out_dir / "assets" / f"{safe_box_asset_stem(box_id)}.png"
                candidate_image.save(asset_path)
                element["bbox"] = candidate_bbox
                generated_assets.setdefault(box_id, {})
                generated_assets[box_id].update(
                    {
                        "path": rel(out_dir, asset_path),
                        "strategy": "crop_nobg",
                        "bbox": candidate_bbox,
                        "crop_bbox": candidate_bbox,
                        "repair": "diff_guided_connected_crop_nobg",
                    }
                )
                replacements[box_id] = candidate_bbox
                applied.append(candidate)
            else:
                review.append(candidate)

    if replacements:
        svg = rewrite_svg_image_boxes(svg, replacements)
        validate_svg(svg, out_dir, width, height)
        response["element_analysis"] = analysis
        response["svg"] = svg
        write_json(generated_path, {"schema": "happyfigure.edit.generated_assets.v1", "assets": generated_assets})

    report = {
        "schema": "happyfigure.edit.crop_repair_report.v1",
        "status": "ok",
        "method": "diff_guided_alpha_edge_connected_components",
        "policy": {
            "auto_apply_canvas_fraction_max": 0.08,
            "auto_apply_large_expansion_px_max": 16,
            "auto_apply_improvement_min": 2.0,
            "auto_apply_small_expansion_improvement_min": 1.0,
        },
        "applied": applied,
        "review": review,
    }
    write_json(report_path, report)
    return report_path


def crop_nobg_repair_candidate(
    out_dir: Path,
    original: Image.Image,
    rendered: Image.Image,
    raw_diff: Image.Image,
    element: dict[str, Any],
    generated_assets: dict[str, Any],
) -> dict[str, Any] | None:
    box_id = str(element.get("box_id") or "").strip()
    bbox = element.get("bbox")
    if not valid_image_bbox(bbox, original.size):
        return None
    generated = generated_assets.get(box_id) if isinstance(generated_assets.get(box_id), dict) else {}
    asset_path = out_dir / str(generated.get("path") or f"assets/{safe_box_asset_stem(box_id)}.png")
    if not asset_path.is_file():
        return None
    with Image.open(asset_path) as asset_image:
        alpha = asset_image.convert("RGBA").getchannel("A")
        edge_alpha = alpha_edge_fractions(alpha)

    expansion: dict[str, int] = {"left": 0, "right": 0, "top": 0, "bottom": 0}
    sides: dict[str, Any] = {}
    for side in expansion:
        alpha_fraction = edge_alpha.get(side, 0)
        values = edge_diff_values(raw_diff, bbox, side, 24)
        numeric = [value for value in values if value is not None]
        if not numeric or alpha_fraction < 0.03:
            sides[side] = {"alpha_edge_fraction": alpha_fraction, "suggest_px": 0, "values": values}
            continue
        ordered = sorted(numeric)
        median = ordered[len(ordered) // 2]
        threshold = 15.0 if alpha_fraction >= 0.05 else 18.0
        suggest = contiguous_high_prefix(values, threshold)
        expansion[side] = suggest
        sides[side] = {
            "alpha_edge_fraction": alpha_fraction,
            "median": round(median, 4),
            "threshold": threshold,
            "suggest_px": suggest,
            "values": values,
        }
    structural = structural_repair_candidate(original, bbox)
    if not any(expansion.values()) and structural is None:
        return None

    x, y, w, h = [int(value) for value in bbox]
    diff_bbox = [
        max(0, x - expansion["left"]),
        max(0, y - expansion["top"]),
        w + expansion["left"] + expansion["right"],
        h + expansion["top"] + expansion["bottom"],
    ]
    candidate_bbox = diff_bbox
    if structural is not None:
        candidate_bbox = union_bbox(candidate_bbox, structural["bbox"])
    if candidate_bbox[0] + candidate_bbox[2] > original.width:
        candidate_bbox[2] = original.width - candidate_bbox[0]
    if candidate_bbox[1] + candidate_bbox[3] > original.height:
        candidate_bbox[3] = original.height - candidate_bbox[1]
    score = score_candidate_expansion(original, rendered, bbox, candidate_bbox, structural)
    max_expand = max(expansion.values())
    area_fraction = round((candidate_bbox[2] * candidate_bbox[3]) / (original.width * original.height), 6)
    improvement = score["improvement"]
    decision = "review"
    reason = "candidate requires expert review"
    candidate_area = candidate_bbox[2] * candidate_bbox[3]
    repair_type = structural["repair_type"] if structural is not None else "diff_edge_expansion"
    if area_fraction > 0.08 and candidate_area > 8000:
        reason = "candidate covers a large canvas fraction"
    elif structural is not None and repair_type == "missing_enclosing_card":
        reason = "candidate appears to include an enclosing card/container; review strategy before expanding crop_nobg"
    elif structural is not None and repair_type == "clipped_foreground" and improvement >= 1.0:
        decision = "apply"
        reason = "structural foreground boundary extends outside bbox"
    elif improvement >= 2.0:
        decision = "apply"
        reason = "local raw diff improves enough"
    elif max_expand <= 12 and improvement >= 1.0:
        decision = "apply"
        reason = "small expansion improves local raw diff"
    elif improvement <= 0:
        reason = "candidate does not improve local raw diff"
    elif max_expand > 16:
        reason = "large expansion has weak improvement"

    return {
        "box_id": box_id,
        "decision": decision,
        "reason": reason,
        "original_bbox": bbox,
        "bbox": candidate_bbox,
        "expansion": {key: value for key, value in expansion.items() if value},
        "structural": structural,
        "repair_type": repair_type,
        "area_fraction": area_fraction,
        "area": candidate_area,
        "score": score,
        "sides": sides,
    }


def structural_repair_candidate(original: Image.Image, bbox: list[int]) -> dict[str, Any] | None:
    x, y, w, h = [int(value) for value in bbox]
    pad = 48
    roi_box = (
        max(0, x - pad),
        max(0, y - pad),
        min(original.width, x + w + pad),
        min(original.height, y + h + pad),
    )
    if roi_box[2] <= roi_box[0] or roi_box[3] <= roi_box[1]:
        return None
    roi = original.crop(roi_box).convert("RGBA")
    mask = foreground_mask(roi)
    local_bbox = [x - roi_box[0], y - roi_box[1], w, h]
    candidates: list[dict[str, Any]] = []
    for component in mask_component_bboxes(mask):
        overlap = bbox_overlap_fraction(local_bbox, component)
        contains_center = bbox_contains_point(
            component,
            local_bbox[0] + local_bbox[2] / 2,
            local_bbox[1] + local_bbox[3] / 2,
        )
        if overlap < 0.35 and not contains_center:
            continue
        global_bbox = [
            roi_box[0] + component[0],
            roi_box[1] + component[1],
            component[2],
            component[3],
        ]
        if not valid_image_bbox(global_bbox, original.size):
            continue
        growth = (global_bbox[2] * global_bbox[3]) / max(1, w * h)
        side_expansion = bbox_side_expansion(bbox, global_bbox)
        max_expand = max(side_expansion.values())
        if max_expand <= 1 or growth > 3.0 or max_expand > 64:
            continue
        expanded_sides = [side for side, value in side_expansion.items() if value >= 2]
        if not expanded_sides:
            continue
        repair_type = "clipped_foreground"
        if growth > 1.6 or sum(value >= 18 for value in side_expansion.values()) >= 2:
            repair_type = "missing_enclosing_card"
        candidates.append(
            {
                "bbox": global_bbox,
                "repair_type": repair_type,
                "area_growth": round(growth, 4),
                "side_expansion": side_expansion,
                "overlap_fraction": overlap,
                "contains_center": contains_center,
            }
        )
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            item["repair_type"] == "clipped_foreground",
            item["overlap_fraction"],
            -item["area_growth"],
        ),
        reverse=True,
    )
    return candidates[0]


def mask_component_bboxes(mask: Image.Image) -> list[list[int]]:
    width, height = mask.size
    pixels = mask.load()
    seen: set[tuple[int, int]] = set()
    boxes: list[list[int]] = []
    min_area = max(8, (width * height) // 2000)
    for y in range(height):
        for x in range(width):
            if not pixels[x, y] or (x, y) in seen:
                continue
            queue: deque[tuple[int, int]] = deque([(x, y)])
            seen.add((x, y))
            xs: list[int] = []
            ys: list[int] = []
            while queue:
                cx, cy = queue.popleft()
                xs.append(cx)
                ys.append(cy)
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if 0 <= nx < width and 0 <= ny < height and pixels[nx, ny] and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        queue.append((nx, ny))
            if len(xs) < min_area:
                continue
            boxes.append([min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1])
    return boxes


def bbox_contains_point(bbox: list[int], px: float, py: float) -> bool:
    x, y, w, h = bbox
    return x <= px <= x + w and y <= py <= y + h


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


def bbox_side_expansion(old: list[int], new: list[int]) -> dict[str, int]:
    ox, oy, ow, oh = old
    nx, ny, nw, nh = new
    return {
        "left": max(0, ox - nx),
        "right": max(0, nx + nw - (ox + ow)),
        "top": max(0, oy - ny),
        "bottom": max(0, ny + nh - (oy + oh)),
    }


def union_bbox(a: list[int], b: list[int]) -> list[int]:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    left = min(ax, bx)
    top = min(ay, by)
    right = max(ax + aw, bx + bw)
    bottom = max(ay + ah, by + bh)
    return [left, top, right - left, bottom - top]


def rewrite_svg_image_boxes(svg: str, replacements: dict[str, list[int]]) -> str:
    root = ET.fromstring(svg)
    for element in root.iter():
        if local_name(element.tag) != "image":
            continue
        href = image_href(element)
        if not href:
            continue
        box_id = Path(href).stem
        if box_id not in replacements:
            continue
        x, y, w, h = replacements[box_id]
        element.set("x", str(x))
        element.set("y", str(y))
        element.set("width", str(w))
        element.set("height", str(h))
    return ET.tostring(root, encoding="unicode")


def valid_image_bbox(value: Any, size: tuple[int, int]) -> bool:
    if not isinstance(value, list) or len(value) != 4 or not all(isinstance(item, int) for item in value):
        return False
    x, y, w, h = value
    width, height = size
    return x >= 0 and y >= 0 and w > 0 and h > 0 and x + w <= width and y + h <= height


def crop_padding(element: dict[str, Any]) -> int:
    policy = element.get("crop_policy")
    if not isinstance(policy, dict):
        return 0
    value = policy.get("padding", 0)
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, min(64, int(value)))
    return 0


def remove_background_alpha(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    if width == 0 or height == 0:
        return rgba
    pixels = rgba.load()
    samples = [
        pixels[0, 0],
        pixels[width - 1, 0],
        pixels[0, height - 1],
        pixels[width - 1, height - 1],
    ]
    bg = tuple(round(sum(pixel[channel] for pixel in samples) / len(samples)) for channel in range(3))
    threshold = 36
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) <= threshold:
                pixels[x, y] = (r, g, b, 0)
            else:
                pixels[x, y] = (r, g, b, a)
    return rgba


def foreground_mask(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    border = []
    for x in range(width):
        border.append(pixels[x, 0])
        border.append(pixels[x, height - 1])
    for y in range(height):
        border.append(pixels[0, y])
        border.append(pixels[width - 1, y])
    bg = tuple(sorted(pixel[channel] for pixel in border)[len(border) // 2] for channel in range(3))
    bg_candidate = Image.new("1", (width, height), 0)
    bg_pixels = bg_candidate.load()
    threshold = 42
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            dist = abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2])
            if a < 16 or dist <= threshold:
                bg_pixels[x, y] = 1

    reached = Image.new("1", (width, height), 0)
    reached_pixels = reached.load()
    queue: deque[tuple[int, int]] = deque()
    for x in range(width):
        for y in (0, height - 1):
            if bg_pixels[x, y] and not reached_pixels[x, y]:
                reached_pixels[x, y] = 1
                queue.append((x, y))
    for y in range(height):
        for x in (0, width - 1):
            if bg_pixels[x, y] and not reached_pixels[x, y]:
                reached_pixels[x, y] = 1
                queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height and bg_pixels[nx, ny] and not reached_pixels[nx, ny]:
                reached_pixels[nx, ny] = 1
                queue.append((nx, ny))

    mask = Image.new("L", (width, height), 0)
    mask_pixels = mask.load()
    for y in range(height):
        for x in range(width):
            if not reached_pixels[x, y] and pixels[x, y][3] >= 16:
                mask_pixels[x, y] = 255
    return remove_tiny_components(mask, min_area=max(4, (width * height) // 1000))


def remove_tiny_components(mask: Image.Image, min_area: int) -> Image.Image:
    width, height = mask.size
    src = mask.load()
    dst = Image.new("L", (width, height), 0)
    out = dst.load()
    seen: set[tuple[int, int]] = set()
    for y in range(height):
        for x in range(width):
            if not src[x, y] or (x, y) in seen:
                continue
            queue: deque[tuple[int, int]] = deque([(x, y)])
            seen.add((x, y))
            component: list[tuple[int, int]] = []
            while queue:
                cx, cy = queue.popleft()
                component.append((cx, cy))
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if 0 <= nx < width and 0 <= ny < height and src[nx, ny] and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        queue.append((nx, ny))
            if len(component) >= min_area:
                for px, py in component:
                    out[px, py] = 255
    return dst


def alpha_edge_fractions(alpha: Image.Image) -> dict[str, float]:
    width, height = alpha.size
    pixels = alpha.load()

    def fraction(side: str) -> float:
        if side == "left":
            values = [pixels[0, y] for y in range(height)]
        elif side == "right":
            values = [pixels[width - 1, y] for y in range(height)]
        elif side == "top":
            values = [pixels[x, 0] for x in range(width)]
        elif side == "bottom":
            values = [pixels[x, height - 1] for x in range(width)]
        else:
            raise ValueError(f"unknown side {side}")
        return round(sum(value > 16 for value in values) / max(1, len(values)), 4)

    return {side: fraction(side) for side in ("left", "right", "top", "bottom")}


def edge_diff_values(diff: Image.Image, bbox: list[int], side: str, max_px: int) -> list[float | None]:
    x, y, w, h = [int(value) for value in bbox]
    values: list[float | None] = []
    for offset in range(1, max_px + 1):
        if side == "left":
            box = (x - offset, y, x - offset + 1, y + h)
        elif side == "right":
            box = (x + w + offset - 1, y, x + w + offset, y + h)
        elif side == "top":
            box = (x, y - offset, x + w, y - offset + 1)
        elif side == "bottom":
            box = (x, y + h + offset - 1, x + w, y + h + offset)
        else:
            raise ValueError(f"unknown side {side}")
        if box[0] < 0 or box[1] < 0 or box[2] > diff.width or box[3] > diff.height or box[2] <= box[0] or box[3] <= box[1]:
            values.append(None)
            continue
        values.append(mean_abs(ImageStat.Stat(diff.crop(box))))
    return values


def contiguous_high_prefix(values: list[float | None], threshold: float) -> int:
    count = 0
    for value in values:
        if value is None or value < threshold:
            break
        count += 1
    return count


def connected_candidate_image(original: Image.Image, original_bbox: list[int], candidate_bbox: list[int]) -> Image.Image:
    candidate = original.crop(bbox_tuple(candidate_bbox)).convert("RGBA")
    candidate_mask = foreground_mask(candidate)
    old_crop = original.crop(bbox_tuple(original_bbox)).convert("RGBA")
    old_mask = foreground_mask(old_crop)

    old_x, old_y, _old_w, _old_h = original_bbox
    candidate_x, candidate_y, _candidate_w, _candidate_h = candidate_bbox
    seed = Image.new("L", candidate.size, 0)
    seed.paste(old_mask, (old_x - candidate_x, old_y - candidate_y))
    candidate.putalpha(keep_components_touching_seed(candidate_mask, seed))
    return candidate


def repair_candidate_image(
    original: Image.Image,
    original_bbox: list[int],
    candidate_bbox: list[int],
    candidate: dict[str, Any],
) -> Image.Image:
    structural = candidate.get("structural")
    if isinstance(structural, dict) and structural.get("repair_type") == "clipped_foreground":
        image = original.crop(bbox_tuple(candidate_bbox)).convert("RGBA")
        image.putalpha(Image.new("L", image.size, 255))
        return image
    return connected_candidate_image(original, original_bbox, candidate_bbox)


def keep_components_touching_seed(mask: Image.Image, seed: Image.Image) -> Image.Image:
    width, height = mask.size
    src = mask.load()
    seed_pixels = seed.load()
    dst = Image.new("L", (width, height), 0)
    out = dst.load()
    seen: set[tuple[int, int]] = set()
    for y in range(height):
        for x in range(width):
            if not src[x, y] or (x, y) in seen:
                continue
            queue: deque[tuple[int, int]] = deque([(x, y)])
            seen.add((x, y))
            component: list[tuple[int, int]] = []
            touches_seed = False
            while queue:
                cx, cy = queue.popleft()
                component.append((cx, cy))
                if seed_pixels[cx, cy]:
                    touches_seed = True
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if 0 <= nx < width and 0 <= ny < height and src[nx, ny] and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        queue.append((nx, ny))
            if touches_seed:
                for px, py in component:
                    out[px, py] = 255
    return dst


def score_candidate_expansion(
    original: Image.Image,
    rendered: Image.Image,
    original_bbox: list[int],
    candidate_bbox: list[int],
    structural: dict[str, Any] | None = None,
) -> dict[str, Any]:
    x, y, w, h = candidate_bbox
    old_x, old_y, old_w, old_h = original_bbox
    left = max(0, min(old_x, x) - 4)
    top = max(0, min(old_y, y) - 4)
    right = min(original.width, max(old_x + old_w, x + w) + 4)
    bottom = min(original.height, max(old_y + old_h, y + h) + 4)
    simulated = rendered.copy()
    candidate_context = {"structural": structural} if structural is not None else {}
    simulated.alpha_composite(repair_candidate_image(original, original_bbox, candidate_bbox, candidate_context), (x, y))
    original_crop = original.crop((left, top, right, bottom)).convert("RGB")
    before_crop = rendered.crop((left, top, right, bottom)).convert("RGB")
    after_crop = simulated.crop((left, top, right, bottom)).convert("RGB")
    before = mean_abs(ImageStat.Stat(ImageChops.difference(original_crop, before_crop)))
    after = mean_abs(ImageStat.Stat(ImageChops.difference(original_crop, after_crop)))
    return {
        "roi": [left, top, right - left, bottom - top],
        "before_mean_abs_diff": before,
        "after_mean_abs_diff": after,
        "improvement": round(before - after, 4),
    }


def mean_abs(stat: ImageStat.Stat) -> float:
    return round(sum(stat.mean) / len(stat.mean), 4)


def bbox_tuple(bbox: list[int]) -> tuple[int, int, int, int]:
    x, y, w, h = [int(value) for value in bbox]
    return (x, y, x + w, y + h)


def safe_box_asset_stem(box_id: str) -> str:
    chars = [ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in box_id.strip()]
    stem = "".join(chars).strip("._")
    return stem or "asset"


def evidence_source_path(out_dir: Path, evidence: dict[str, Any]) -> Path:
    artifacts = evidence.get("artifacts")
    if isinstance(artifacts, dict) and isinstance(artifacts.get("input_asset"), str):
        candidate = out_dir / artifacts["input_asset"]
        if candidate.is_file():
            return candidate.resolve(strict=True)

    image = evidence.get("image") if isinstance(evidence.get("image"), dict) else {}
    source = image.get("source")
    if not isinstance(source, str) or not source:
        raise ValueError("evidence.json must contain artifacts.input_asset or image.source")
    return Path(source).expanduser().resolve(strict=True)


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


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload
