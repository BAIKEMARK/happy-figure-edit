#!/usr/bin/env python3
"""Create a structured Expert response fixture for the Transformer route map.

This is a hand-authored quality target for the Skill Expert MVP. It converts the
known test image into an editable SVG response bundle without OCR/segmentation.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


W = 2752
H = 1536


@dataclass(frozen=True)
class Box:
    box_id: str
    x: int
    y: int
    w: int
    h: int
    kind: str
    label: str


BOXES = [
    Box("T001", 720, 30, 1310, 80, "text", "Transformer Technical Route Map"),
    Box("L001", 110, 785, 290, 65, "text", "Input Tokens"),
    Box("B001", 430, 910, 240, 110, "shape", "Positional Encoding"),
    Box("B002", 430, 700, 240, 125, "shape", "Token Embedding"),
    Box("G001", 765, 330, 500, 850, "container", "Encoder Stack N=6"),
    Box("B003", 855, 970, 320, 100, "shape", "Multi-Head Self-Attention"),
    Box("B004", 855, 880, 320, 58, "shape", "Add & Norm"),
    Box("B005", 855, 730, 320, 100, "shape", "Multi-Head Self-Attention"),
    Box("B006", 855, 650, 320, 58, "shape", "Add & Norm"),
    Box("B007", 855, 510, 320, 110, "shape", "Feed Forward Network"),
    Box("B008", 855, 435, 320, 58, "shape", "Add & Norm"),
    Box("G002", 1325, 205, 710, 350, "container", "Scaled Dot-Product Attention"),
    Box("B009", 1480, 280, 70, 150, "shape", "QKV attention block"),
    Box("B010", 1680, 310, 170, 80, "shape", "Parallel Attention Heads"),
    Box("B011", 1890, 310, 140, 80, "shape", "Concat + Linear"),
    Box("B012", 1760, 840, 240, 100, "shape", "Positional Encoding"),
    Box("B013", 1760, 1020, 240, 100, "shape", "Token Embedding"),
    Box("G003", 2105, 330, 470, 850, "container", "Decoder Stack N=6"),
    Box("B014", 2170, 965, 320, 120, "shape", "Masked Self-Attention"),
    Box("B015", 2170, 880, 320, 58, "shape", "Add & Norm"),
    Box("B016", 2170, 730, 320, 110, "shape", "Encoder-Decoder Attention"),
    Box("B017", 2170, 650, 320, 58, "shape", "Add & Norm"),
    Box("B018", 2170, 510, 320, 110, "shape", "Feed Forward Network"),
    Box("B019", 2170, 435, 320, 58, "shape", "Add & Norm"),
    Box("B020", 2170, 220, 320, 56, "shape", "Linear + Softmax"),
    Box("G004", 265, 1310, 1040, 150, "container", "Training"),
    Box("G005", 1370, 1310, 540, 150, "container", "Evaluation"),
    Box("G006", 1970, 1310, 750, 150, "container", "Advantages"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Transformer route map Expert response fixture")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve(strict=True)
    output = Path(args.output).expanduser().resolve()
    evidence = json.loads((run_dir / "evidence.json").read_text(encoding="utf-8"))
    image = evidence.get("image", {})
    if image.get("width") != W or image.get("height") != H:
        raise ValueError("Transformer fixture only supports the 2752x1536 target image")

    payload = {
        "schema": "happyfigure.edit.expert_response.v1",
        "element_analysis": element_analysis(),
        "svg": svg_document(),
        "notes": [
            "Hand-authored Expert fixture for the Transformer Technical Route Map target image.",
            "No OCR or segmentation was used; visible structure was encoded directly.",
        ],
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(output)}, ensure_ascii=False))
    return 0


def element_analysis() -> dict[str, Any]:
    return {
        "schema": "happyfigure.edit.element_analysis.v1",
        "source": "skill_expert_fixture_transformer",
        "canvas": {"width": W, "height": H},
        "strategy_summary": "The target is a structured technical diagram, so the fixture reconstructs major containers, module boxes, token groups, labels, and connectors as editable SVG primitives and text.",
        "elements": [
            {
                "box_id": box.box_id,
                "source_candidate_ids": [],
                "bbox": [box.x, box.y, box.w, box.h],
                "kind": box.kind,
                "label": box.label,
                "asset_strategy": "svg_self_draw",
                "confidence": "medium",
                "reason": f"{box.label} is readable structured diagram content and should remain editable.",
                "evidence": ["Visible in the Transformer technical route map image."],
            }
            for box in BOXES
        ],
        "review": {"status": "ok", "notable_adjustments": []},
    }


def svg_document() -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        "<title>Transformer Technical Route Map - Happy Figure Edit fixture</title>",
        "<rect x=\"0\" y=\"0\" width=\"2752\" height=\"1536\" fill=\"#ffffff\"/>",
        defs(),
        text(1376, 72, "Transformer Technical Route Map", 58, anchor="middle", weight="700"),
        text(165, 555, "Sequence Transduction", 36),
        text(210, 830, "Input Tokens", 36, anchor="middle"),
        token_row(85, 735, 8),
        arrow(360, 765, 425, 765),
        rounded_box(430, 700, 240, 125, "#d7ebff", "Token\nEmbedding", "B002", font_size=34),
        arrow(670, 765, 760, 765),
        text(550, 1085, "Positional\nEncoding", 34, anchor="middle"),
        pos_encoding_box(430, 910, 240, 110),
        arrow(550, 910, 550, 825),
        encoder_stack(),
        attention_panel(),
        decoder_inputs(),
        decoder_stack(),
        top_output(),
        bottom_cards(),
        long_connectors(),
        "</svg>",
    ]
    return "\n".join(parts)


def defs() -> str:
    return """<defs>
  <linearGradient id="blueZone" x1="0" x2="1"><stop offset="0" stop-color="#eef8ff"/><stop offset="1" stop-color="#dcefff"/></linearGradient>
  <linearGradient id="purpleZone" x1="0" x2="1"><stop offset="0" stop-color="#f5efff"/><stop offset="1" stop-color="#eadcff"/></linearGradient>
  <linearGradient id="orangeBox" x1="0" x2="1"><stop offset="0" stop-color="#ffe7c8"/><stop offset="1" stop-color="#ffd3a4"/></linearGradient>
  <linearGradient id="greenBox" x1="0" x2="1"><stop offset="0" stop-color="#e9f8de"/><stop offset="1" stop-color="#d8f1c9"/></linearGradient>
  <linearGradient id="blueBox" x1="0" x2="1"><stop offset="0" stop-color="#cfe9ff"/><stop offset="1" stop-color="#b9dfff"/></linearGradient>
  <linearGradient id="lavBox" x1="0" x2="1"><stop offset="0" stop-color="#e3e8ff"/><stop offset="1" stop-color="#d2d8f5"/></linearGradient>
</defs>"""


def encoder_stack() -> str:
    return "\n".join(
        [
            text(510, 665, "ZONE 1", 46, anchor="middle"),
            text(1015, 300, "ZONE 2", 46, anchor="middle"),
            dashed_container(765, 330, 500, 850, "url(#blueZone)", "Encoder Stack N=6"),
            rounded_box(855, 970, 320, 100, "url(#orangeBox)", "Multi-Head\nSelf-Attention", "B003", font_size=28),
            rounded_box(855, 880, 320, 58, "#e9e9e9", "Add & Norm", "B004", font_size=26),
            rounded_box(855, 730, 320, 100, "url(#orangeBox)", "Multi-Head\nSelf-Attention", "B005", font_size=28),
            rounded_box(855, 650, 320, 58, "#e9e9e9", "Add & Norm", "B006", font_size=26),
            rounded_box(855, 510, 320, 110, "url(#greenBox)", "Feed Forward\nNetwork", "B007", font_size=28),
            rounded_box(855, 435, 320, 58, "#e9e9e9", "Add & Norm", "B008", font_size=26),
            arrow(1015, 1070, 1015, 970),
            arrow(1015, 880, 1015, 830),
            arrow(1015, 730, 1015, 708),
            arrow(1015, 650, 1015, 620),
            arrow(1015, 510, 1015, 493),
            polyline([(800, 980), (800, 855), (855, 855), (855, 908)], dashed=False),
            polyline([(1175, 760), (1225, 760), (1225, 830), (1175, 830)], dashed=False),
        ]
    )


def attention_panel() -> str:
    return "\n".join(
        [
            text(1690, 185, "ZONE 4", 46, anchor="middle"),
            container(1325, 205, 710, 350, "#f9f9f9", stroke="#222", radius=18),
            text(1490, 270, "Scaled Dot-Product\nAttention", 30, anchor="middle"),
            text(1765, 270, "Parallel\nAttention\nHeads", 30, anchor="middle"),
            text(1390, 365, "Q", 30),
            text(1390, 420, "K", 30),
            text(1390, 475, "V", 30),
            rounded_rect(1480, 335, 70, 150, "url(#lavBox)", "#222", 10, "B009"),
            arrow(1425, 365, 1480, 365),
            arrow(1425, 420, 1480, 420),
            arrow(1425, 475, 1480, 475),
            arrow(1550, 420, 1620, 420),
            stack_cards(1680, 365),
            text(1765, 420, "...", 34, anchor="middle", weight="700"),
            arrow(1850, 420, 1890, 420),
            rounded_box(1890, 365, 140, 80, "#e9e9e9", "Concat\n+ Linear", "B011", font_size=26),
            dashed_line(1260, 765, 1340, 555),
            dashed_line(1260, 835, 1510, 555),
            text(1690, 610, "ZONE 4", 46, anchor="middle"),
        ]
    )


def decoder_inputs() -> str:
    return "\n".join(
        [
            token_row(1420, 1080, 8),
            text(1570, 1180, "Output Tokens\nshifted right", 34, anchor="middle"),
            arrow(1680, 1100, 1760, 1100),
            rounded_box(1760, 1020, 240, 100, "url(#blueBox)", "Token\nEmbedding", "B013", font_size=32),
            rounded_box(1760, 840, 240, 100, "url(#lavBox)", "Positional\nEncoding", "B012", font_size=32),
            circle_text(2050, 1085, "+"),
            arrow(1880, 1020, 1880, 940),
            arrow(1880, 940, 2050, 1085),
            arrow(2000, 1070, 2050, 1085),
            arrow(2050, 1085, 2170, 1025),
        ]
    )


def decoder_stack() -> str:
    return "\n".join(
        [
            dashed_container(2105, 330, 470, 850, "url(#purpleZone)", "Decoder Stack N=6"),
            rounded_box(2170, 965, 320, 120, "url(#orangeBox)", "Masked\nSelf-Attention", "B014", font_size=28),
            rounded_box(2170, 880, 320, 58, "#e9e9e9", "Add & Norm", "B015", font_size=26),
            rounded_box(2170, 730, 320, 110, "url(#orangeBox)", "Encoder-Decoder\nAttention", "B016", font_size=28),
            rounded_box(2170, 650, 320, 58, "#e9e9e9", "Add & Norm", "B017", font_size=26),
            rounded_box(2170, 510, 320, 110, "url(#greenBox)", "Feed Forward\nNetwork", "B018", font_size=28),
            rounded_box(2170, 435, 320, 58, "#e9e9e9", "Add & Norm", "B019", font_size=26),
            arrow(2330, 1085, 2330, 965),
            arrow(2330, 880, 2330, 840),
            arrow(2330, 730, 2330, 708),
            arrow(2330, 650, 2330, 620),
            arrow(2330, 510, 2330, 493),
            arrow(2050, 765, 2170, 785),
            dashed_line(2030, 420, 2105, 675),
            dashed_line(2040, 420, 2105, 1010),
        ]
    )


def top_output() -> str:
    return "\n".join(
        [
            rounded_box(2170, 220, 320, 56, "#e9e9e9", "Linear + Softmax", "B020", font_size=30),
            arrow(2330, 435, 2330, 276),
            arrow(2330, 220, 2330, 105),
            text(2130, 95, "Predicted\nTokens", 30, anchor="middle"),
            token_row(2200, 70, 8, size=30, gap=10),
            arrow(2470, 85, 2540, 85),
            text(2635, 95, "Translation\nOutput", 30, anchor="middle"),
        ]
    )


def bottom_cards() -> str:
    return "\n".join(
        [
            container(265, 1310, 1040, 150, "#f7f7f7", radius=14),
            text(785, 1355, "Training", 36, anchor="middle"),
            small_pill(295, 1385, 210, 78, "WMT 2014\nEN-DE"),
            small_pill(525, 1385, 210, 78, "WMT 2014\nEN-FR"),
            small_pill(760, 1385, 210, 78, "Adam +\nWarmup"),
            small_pill(990, 1385, 300, 78, "Dropout +\nLabel Smoothing"),
            container(1370, 1310, 540, 150, "#f7f7f7", radius=14),
            text(1640, 1355, "Evaluation", 36, anchor="middle"),
            small_pill(1390, 1385, 230, 78, "BLEU"),
            small_pill(1645, 1385, 230, 78, "Constituency\nParsing"),
            container(1970, 1310, 750, 150, "#f7f7f7", radius=14),
            text(2345, 1355, "Advantages", 36, anchor="middle"),
            text(2025, 1420, "No Recurrence\nNo Convolution", 30),
            text(2385, 1420, "Parallelizable\nShort Dependency Paths", 30),
            text(95, 1395, "ZONE 5", 42),
        ]
    )


def long_connectors() -> str:
    return "\n".join(
        [
            arrow(1265, 790, 1370, 790),
            token_row(1370, 755, 5, size=42, gap=14),
            text(1475, 870, "Encoded\nRepresentations", 34, anchor="middle"),
            arrow(1520, 790, 2170, 790),
            polyline([(1015, 1180), (1015, 1215), (2325, 1215), (2325, 1180)], dashed=False, stroke="#aaa", arrow_end=False),
            polyline([(785, 1310), (785, 1215), (2325, 1215)], dashed=False, stroke="#aaa", arrow_end=False),
            polyline([(1640, 1310), (1640, 1215)], dashed=False, stroke="#aaa", arrow_end=False),
            polyline([(2345, 1310), (2345, 1215)], dashed=False, stroke="#aaa", arrow_end=False),
        ]
    )


def dashed_container(x: int, y: int, w: int, h: int, fill: str, title: str) -> str:
    return "\n".join(
        [
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="22" fill="{fill}" stroke="#222" stroke-width="3" stroke-dasharray="14 14"/>',
            text(x + w / 2, y + 45, title, 36, anchor="middle"),
        ]
    )


def container(x: int, y: int, w: int, h: int, fill: str, stroke: str = "#222", radius: int = 12) -> str:
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="3"/>'


def rounded_box(x: int, y: int, w: int, h: int, fill: str, label: str, box_id: str, font_size: int = 32) -> str:
    return "\n".join(
        [
            rounded_rect(x, y, w, h, fill, "#222", 12, box_id),
            multiline_text(x + w / 2, y + h / 2, label, font_size),
        ]
    )


def rounded_rect(x: int, y: int, w: int, h: int, fill: str, stroke: str, radius: int, box_id: str) -> str:
    return f'<rect id="{box_id}" x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="3"/>'


def small_pill(x: int, y: int, w: int, h: int, label: str) -> str:
    return "\n".join([container(x, y, w, h, "#eeeeee", radius=12), multiline_text(x + w / 2, y + h / 2, label, 28)])


def pos_encoding_box(x: int, y: int, w: int, h: int) -> str:
    lines = [container(x, y, w, h, "#e5f1fb", radius=12)]
    for i in range(1, 8):
        xx = x + i * w / 8
        lines.append(f'<line x1="{xx:.1f}" y1="{y}" x2="{xx:.1f}" y2="{y+h}" stroke="#b9c8d6" stroke-width="2"/>')
    for i in range(1, 4):
        yy = y + i * h / 4
        lines.append(f'<line x1="{x}" y1="{yy:.1f}" x2="{x+w}" y2="{yy:.1f}" stroke="#b9c8d6" stroke-width="2"/>')
    points = []
    for i in range(0, 120):
        px = x + i * w / 119
        py = y + h / 2 - 42 * __import__("math").sin(i / 119 * 2 * __import__("math").pi)
        points.append(f"{px:.1f},{py:.1f}")
    lines.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="#5588c8" stroke-width="5"/>')
    return "\n".join(lines)


def stack_cards(x: int, y: int) -> str:
    return "\n".join(
        [
            rounded_rect(x, y + 10, 130, 70, "url(#lavBox)", "#222", 10, "heads-a"),
            rounded_rect(x + 18, y + 25, 130, 70, "url(#lavBox)", "#222", 10, "heads-b"),
            rounded_rect(x + 36, y + 40, 130, 70, "url(#lavBox)", "#222", 10, "heads-c"),
        ]
    )


def token_row(x: int, y: int, count: int, size: int = 42, gap: int = 12) -> str:
    parts = []
    for i in range(count):
        parts.append(f'<rect x="{x + i * (size + gap)}" y="{y}" width="{size}" height="{size}" rx="7" fill="url(#blueBox)" stroke="#222" stroke-width="3"/>')
    return "\n".join(parts)


def text(x: float, y: float, value: str, size: int, anchor: str = "start", weight: str = "400") -> str:
    if "\n" in value:
        return multiline_text(x, y, value, size, anchor=anchor, weight=weight)
    return f'<text x="{x:.1f}" y="{y:.1f}" font-family="Arial, Helvetica, sans-serif" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" fill="#111">{escape(value)}</text>'


def multiline_text(x: float, y: float, value: str, size: int, anchor: str = "middle", weight: str = "400") -> str:
    lines = value.split("\n")
    start_y = y - (len(lines) - 1) * size * 0.56
    tspans = []
    for idx, line in enumerate(lines):
        dy = 0 if idx == 0 else size * 1.1
        tspans.append(f'<tspan x="{x:.1f}" dy="{dy:.1f}">{escape(line)}</tspan>')
    return f'<text x="{x:.1f}" y="{start_y:.1f}" font-family="Arial, Helvetica, sans-serif" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" dominant-baseline="middle" fill="#111">{"".join(tspans)}</text>'


def circle_text(x: int, y: int, value: str) -> str:
    return f'<circle cx="{x}" cy="{y}" r="26" fill="#f4f4f4" stroke="#222" stroke-width="3"/>{text(x, y + 10, value, 36, anchor="middle")}'


def arrow(x1: int, y1: int, x2: int, y2: int, stroke: str = "#111") -> str:
    return "\n".join(
        [
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="5"/>',
            arrow_head(x1, y1, x2, y2, stroke),
        ]
    )


def arrow_head(x1: int, y1: int, x2: int, y2: int, fill: str) -> str:
    import math

    angle = math.atan2(y2 - y1, x2 - x1)
    length = 22
    spread = 0.55
    p1 = (x2, y2)
    p2 = (x2 - length * math.cos(angle - spread), y2 - length * math.sin(angle - spread))
    p3 = (x2 - length * math.cos(angle + spread), y2 - length * math.sin(angle + spread))
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in [p1, p2, p3])
    return f'<polygon points="{pts}" fill="{fill}"/>'


def dashed_line(x1: int, y1: int, x2: int, y2: int) -> str:
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#666" stroke-width="3" stroke-dasharray="12 12"/>'


def polyline(points: list[tuple[int, int]], dashed: bool, stroke: str = "#111", arrow_end: bool = True) -> str:
    attr = ' stroke-dasharray="12 12"' if dashed else ""
    point_text = " ".join(f"{x},{y}" for x, y in points)
    parts = [f'<polyline points="{point_text}" fill="none" stroke="{stroke}" stroke-width="4"{attr}/>']
    if arrow_end and len(points) >= 2:
        x1, y1 = points[-2]
        x2, y2 = points[-1]
        parts.append(arrow_head(x1, y1, x2, y2, stroke))
    return "\n".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
