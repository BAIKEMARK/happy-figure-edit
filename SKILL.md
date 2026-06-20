---
name: happy-figure-edit
description: Convert bitmap figures, screenshots, AI-generated images, or scientific diagrams into editable SVG and PPTX with Happy Figure Edit Skill Expert. Use when the user asks to rebuild, vectorize, editabilize, or convert an existing image into editable SVG/PPTX, especially for Happy Figure workflows.
---

# Happy Figure Edit

Use this skill to convert an existing image into editable SVG and PPTX.

## How This Skill Works

You (the agent running this skill) are the Expert. You have vision: you can open the
image with `view_image` and read its structure directly. That is exactly how the first
high-quality output was produced. Do not wait for an external model API and do not stop
at the conservative fallback. Look at the image, encode what you see as an editable SVG
response, and apply it.

The runner provides two roles only: it prepares an evidence bundle plus a conservative
fallback (`run_expert_mvp.py --image ... --out-dir ...`), and it validates and converts
your response (`run_expert_mvp.py apply-response ...`). The actual reconstruction is your
visual judgment, written into `expert_response.json`.

## Mainline Only

For normal skill execution, use only the mainline script:

```bash
scripts/run_expert_mvp.py --image <image> --out-dir <run-dir>
scripts/run_expert_mvp.py apply-response --run-dir <run-dir> --response <run-dir>/expert_response.json
```

Do not use scripts under `scripts/aux/` as the normal reconstruction path. They are
auxiliary tools kept out of the mainline to avoid confusing future optimization:

- `scripts/aux/make_transformer_fixture.py` is a one-image regression fixture with
  hard-coded coordinates. It is not a general reconstruction method.
- `scripts/aux/smoke_media_dir.py` is only for batch smoke checks.
- `scripts/aux/compare_quality_expert_routes.py` is only for comparing existing run
  directories.

## Expert Workflow (run for every image)

1. Prepare the run bundle:
   `scripts/run_expert_mvp.py --image <image> --out-dir <run-dir>`.
   This writes `evidence.json` (with canvas width/height), `element_overlay.png` (the
   current bbox overlay), a baseline `element_analysis.json`, and a conservative
   fallback `output.svg`/`output.pptx`.
2. Read the inputs. Open the original image with `view_image` (detail=high) and read
   `<run-dir>/evidence.json` for the exact canvas dimensions. Also read
   `prompts/expert_structure.md` and `prompts/expert_svg.md` for the reconstruction rules.
3. Decompose the figure by eye. Identify the title, labeled zones, dashed containers,
   module boxes, token groups, connectors/arrows, callout panels, and bottom summary
   cards. Estimate each element's pixel `bbox` `[x, y, w, h]` against the real canvas.
4. Write `<run-dir>/expert_response.json` yourself (see schema below). Re-draw text,
   boxes, arrows, panels, and simple geometry as native SVG primitives. Use `crop` for
   regions that would be materially worse as vectors (photos, dense textures, heatmaps),
   and `crop_nobg` for separable foreground subjects such as logos or complex icons.
   Reference generated raster assets as `assets/<box_id>.png`; `apply-response`
   materializes those files from each element bbox before SVG validation.
5. Apply and convert:
   `scripts/run_expert_mvp.py apply-response --run-dir <run-dir> --response <run-dir>/expert_response.json`.
   This validates the schema, writes `element_analysis.json`/`output.svg`, and produces
   `output.pptx` via the vendored SVG→PPTX converter plus `quality_report.json`.
6. Verify visually. Open `<run-dir>/element_overlay.png`, `<run-dir>/rendered.png`,
   and `<run-dir>/diff.png` with `view_image`, compare against the original, and check
   `quality_report.json` for the highest-diff components. Iterate on coordinates, font sizes, and colors in
   `expert_response.json` and re-apply until the layout matches.
7. Deliver `output.svg`, `output.pptx`, `report.html`, and `run_status.json`.

## expert_response.json Schema

The response must validate against `happyfigure.edit.expert_response.v1`:

```json
{
  "schema": "happyfigure.edit.expert_response.v1",
  "element_analysis": {
    "schema": "happyfigure.edit.element_analysis.v1",
    "source": "skill_expert_agent",
    "canvas": {"width": <image_width>, "height": <image_height>},
    "strategy_summary": "<one sentence on how the figure was decomposed>",
    "elements": [
      {
        "box_id": "T001",
        "source_candidate_ids": ["T001"],
        "bbox": [x, y, w, h],
        "kind": "text | shape | container | image",
        "asset_strategy": "svg_self_draw | crop | crop_nobg",
        "confidence": "high | medium | low",
        "reason": "<why this strategy>",
        "evidence": ["<what you saw in the image>"]
      }
    ],
    "review": {"status": "none", "notable_adjustments": []}
  },
  "svg": "<svg xmlns=... width=W height=H viewBox=\"0 0 W H\"> ... </svg>",
  "notes": ["<short notes about decisions>"]
}
```

Hard validation rules enforced by `apply-response`:
- `canvas.width`/`canvas.height` must equal the evidence image dimensions.
- Every `bbox` is four integers, inside the canvas (`x>=0`, `y>=0`, `w>0`, `h>0`,
  `x+w<=width`, `y+h<=height`).
- Each element uses exactly one `asset_strategy`: `svg_self_draw`, `crop`, or `crop_nobg`.
- SVG root must use `viewBox="0 0 W H"` with matching `width`/`height`.
- SVG must not contain `file://`, `data:`, `base64`, `<style>`, `<filter>`, `<mask>`,
  `<clipPath>`, `<foreignObject>`, `<textPath>`, `<symbol>`, or `<use>`.
- Any raster `<image>` href must be a relative path under `assets/`. Use
  `assets/<box_id>.png` for `crop` and `crop_nobg` elements so the runner can generate it.

For directory-level smoke checks, run:

```bash
scripts/aux/smoke_media_dir.py --media-dir <media-dir> --out-root <out-root>
```

Use this only to verify local artifact generation across multiple images. Do not describe
fallback smoke outputs as full editable reconstructions.

## Expert Principles

- Treat the original image as visual truth.
- Use preprocessing evidence as evidence, not truth.
- Preserve stable `box_id` values.
- Choose exactly one asset strategy per element: `svg_self_draw`, `crop`, or `crop_nobg`.
  - `svg_self_draw`: text, boxes, panels, tables, axes, arrows, and simple geometry that SVG primitives can redraw faithfully.
  - `crop_nobg`: separable foreground objects (icons, logos, badges, buttons, avatars, complex small symbols) whose redraw would be inaccurate; the runner removes the background. Keep the bbox tight to the object. Do not simplify complex icons into editable line art.
  - `crop`: dense raster regions where fidelity beats editability and the background should stay (photos, screenshots, heatmaps, microscopy, textures, complex 3D renders, statistical/function plots).
- Keep SVG canvas dimensions identical to the original image.
- Do not use external URLs, absolute image hrefs, `file://`, or base64 image data in SVG output.
- Keep text, arrows, tables, panels, formulas, axes, and simple geometry editable when generating a full reconstruction.

## References

- DrawAI prompt analysis: `references/drawai-prompts.md`.
