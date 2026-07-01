---
name: happy-figure-edit
description: Convert existing bitmap figures into editable SVG and PPTX. Use when Codex needs to rebuild, vectorize, editabilize, or redraw scientific figures, workflow diagrams, architecture diagrams, AI-generated diagrams, screenshots, or slide-like graphics while preserving dense raster regions such as logos, icons, photos, heatmaps, screenshots, and plots.
---

# Happy Figure Edit

Convert one input image into a faithful, editable `output.svg`, then export `output.pptx` only after the SVG passes review.

You are the reconstruction expert. The runner prepares evidence, validates your JSON, materializes cropped assets, renders diffs, and converts SVG to PPTX. It does not replace your visual judgment.

## Setup Check

Run commands from the directory containing this `SKILL.md`. If `.venv/bin/python` is missing, install once:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
brew install resvg
```

Use `.venv/bin/python` for all scripts. `resvg` is used only for `rendered.png`, `diff.png`, and the pixel-diff section of `quality_report.json`; SVG/PPTX generation still works if it is missing.

## Main Workflow

All normal outputs must stay under the skill directory:

- Work directory: `outputs/<image-stem>_work`
- Delivery directory: `outputs/<image-stem>`

Do not write reconstruction outputs to `/tmp`, `~/Documents`, or the caller's
current working directory unless the user explicitly asks for that path.

Execution discipline:

- Keep the shell working directory at the directory containing this `SKILL.md` for every runner command.
- Do not `cd` into `outputs/<image-stem>_work` and then repair relative paths by trial and error.
- Use only `.venv/bin/python scripts/run_expert_mvp.py ...` from the skill root for normal commands.
- Do not inspect `scripts/`, `_vendor/`, or converter source during a normal reconstruction. Read source code only when a runner command fails or the user asks to debug the skill itself.
- If a temporary helper script is useful for writing `expert_response.json`, put it under `outputs/<image-stem>_work/`, but execute it from the skill root, for example `.venv/bin/python outputs/<image-stem>_work/build_expert_response.py`. Do not package helper scripts as deliverables.

1. Prepare a run directory:

   ```bash
   .venv/bin/python scripts/run_expert_mvp.py \
     --image <absolute-image-path> \
     --out-dir outputs/<image-stem>_work
   ```

   This writes `evidence.json`, a conservative baseline `element_analysis.json`, fallback `output.svg`, `report.html`, `quality_report.json`, and `quality_summary.txt`. It also writes a baseline `element_overlay.png`, but that overlay usually contains only the full-canvas fallback box and is not useful for visual decomposition. It does not generate PPTX during preparation.

2. Read the required inputs before writing anything:

   - Open the original image with `view_image` at high detail.
   - Read `outputs/<image-stem>_work/evidence.json` for exact canvas width and height.
   - Read `prompts/expert_structure.md` for element decomposition and asset strategy rules.
   - Read `prompts/expert_svg.md` for SVG constraints.
   - Do not open the initial baseline `element_overlay.png` when it only shows the conservative full-canvas fallback. Use the original image for decomposition.
   - Do not read runner or converter implementation files unless the normal workflow errors.

3. Decompose the figure by eye:

   - Identify titles, labels, section containers, panels, tables, axes, nodes, arrows, legends, callouts, icons, logos, screenshots, photos, heatmaps, and dense plots.
   - Split every icon, logo, badge, button, avatar, app/document glyph, and complex small symbol into its own tight `crop_nobg` element unless it is only a primitive mark such as a plain circle or line.
   - Estimate each element bbox as integer pixels `[x, y, w, h]` in the original canvas coordinate system.
   - Keep text, simple shapes, arrows, tables, axes, formulas, and panels editable whenever they can be faithfully redrawn.

4. Write `outputs/<image-stem>_work/expert_response.json` manually using the schema below. The SVG must reference cropped rasters as `assets/<box_id>.png`; `apply-response` creates those files from the element bbox.

5. Apply and review SVG:

   ```bash
   .venv/bin/python scripts/run_expert_mvp.py apply-response \
     --run-dir outputs/<image-stem>_work \
     --response outputs/<image-stem>_work/expert_response.json
   ```

   During `apply-response`, the runner materializes assets, validates `output.svg`,
   renders it to `rendered.png`, computes `diff.png`, writes review tiles, and
   performs one deterministic `crop_nobg` boundary repair pass. It does not
   generate PPTX. Iterate on SVG quality first; PPTX export happens only in
   `package-run` after the final SVG review is acceptable.

6. Verify visually:

   - Open the original image, the regenerated `outputs/<image-stem>_work/element_overlay.png`, `outputs/<image-stem>_work/rendered.png`, and `outputs/<image-stem>_work/diff.png`.
   - Read `outputs/<image-stem>_work/quality_summary.txt` first. Use `quality_report.json` only when the summary is not enough.
   - Inspect `asset_integrity_review` in `quality_summary.txt` first. Open the listed `asset_review_tiles/` files before generic `review_tiles/`; these are dedicated checks for clipped icons, missing card backgrounds, and bad `crop_nobg` bboxes.
   - Inspect at most the top five files listed under `outputs/<image-stem>_work/review_tiles/`. These local original/rendered/diff tiles are for high-value checks, not for exhaustively reviewing every diff.
   - Prioritize `asset_integrity_review`, then `granularity_warnings`, then review tiles before global pixel diff scores. Large `text`/`group`/`panel` bboxes can hide missing icons, missing card backgrounds, and wrong connectors.
   - Review in this order: incomplete `crop`/`crop_nobg` assets; missing icon/card/container backgrounds; graph node shape and edge topology mistakes; missing characters/content; small text/icon offsets.
   - Prioritize `declared_region_review` for high-diff content hidden inside broad zones/panels, `unassigned_diff_regions` for missing glyphs/unmodeled elements, and `diff_regions[].near_crop_edges` for incomplete `crop` or `crop_nobg` bboxes.
   - Read `outputs/<image-stem>_work/crop_repair_report.json`; accept applied repairs unless visual review shows overreach, and inspect `review` candidates before manually changing bbox or strategy.
   - Iterate first on incomplete crops, missing card backgrounds, wrong graph shapes/links, missing characters, and unmodeled elements. Treat tiny text/icon offsets as acceptable unless they materially change readability or meaning.
   - Re-run `apply-response` from the skill root after each `expert_response.json` update. Do not run commands from inside the work directory.

7. Package the run for delivery instead of manually copying selected files:

   ```bash
   .venv/bin/python scripts/run_expert_mvp.py package-run \
     --run-dir outputs/<image-stem>_work \
     --out-dir outputs/<image-stem>
   ```

   This generates the final `output.pptx` from the reviewed `output.svg`, then
   preserves the canonical filenames used by `report.html`: `output.svg`,
   `output.pptx`, `element_overlay.png`, `rendered.png`, `diff.png`,
   `quality_summary.txt`, `quality_report.json`, `crop_repair_report.json`,
   `run_status.json`, `review_tiles/`, and `assets/`. Do not create renamed
   copies of `output.svg` or `output.pptx` unless the user explicitly asks for
   duplicate filenames.

## Asset Strategy Rules

Choose exactly one strategy per element:

| Strategy | Use for | Avoid |
| --- | --- | --- |
| `svg_self_draw` | Text, labels, boxes, panels, tables, axes, arrows, connectors, formulas, simple geometry | Dense images or complex icons that would be visually wrong if redrawn |
| `crop_nobg` | Separable foreground objects: icons, logos, badges, buttons, avatars, app/document glyphs, complex small symbols | Whole cards, screenshots, plots, or objects whose background must remain |
| `crop` | Photos, screenshots, heatmaps, microscopy, textures, complex 3D renders, statistical/function plots, dense raster regions | Text/boxes/arrows that should remain editable |

Decision order:

1. If SVG primitives can redraw it faithfully, use `svg_self_draw`.
2. If redraw would distort it but the foreground can be separated, use `crop_nobg` with a tight bbox around the object only.
3. If fidelity matters and the background must stay, use `crop`.
4. Do not simplify these foreground objects into editable line art and do not hide them inside a larger `svg_self_draw` panel.
5. Do not make one crop larger than 75% of the canvas; keep decomposing the figure.
6. Do not use one giant `text`, `group`, `connector`, or panel bbox to cover many internal labels/icons; split by semantic element so review artifacts can expose missing pieces.
7. For icon cards, separate the editable SVG card/container from the `crop_nobg` foreground icon, or use `crop` when the card background must remain raster-faithful.
8. For network/KG regions, preserve node shape categories and edge topology explicitly; square nodes must not become circles unless the source uses circles.

## expert_response.json Contract

The response must validate against `happyfigure.edit.expert_response.v1`:

```json
{
  "schema": "happyfigure.edit.expert_response.v1",
  "element_analysis": {
    "schema": "happyfigure.edit.element_analysis.v1",
    "source": "skill_expert_agent",
    "canvas": {"width": 1376, "height": 768},
    "strategy_summary": "Short decomposition summary.",
    "elements": [
      {
        "box_id": "T001",
        "source_candidate_ids": ["T001"],
        "bbox": [10, 20, 120, 32],
        "kind": "text",
        "asset_strategy": "svg_self_draw",
        "confidence": "high",
        "reason": "Readable title redrawn as editable SVG text.",
        "evidence": ["Visible title at top left."]
      }
    ],
    "review": {"status": "none", "notable_adjustments": []}
  },
  "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1376\" height=\"768\" viewBox=\"0 0 1376 768\">...</svg>",
  "notes": ["Short implementation notes."]
}
```

Validation constraints:

- `canvas.width` and `canvas.height` must match `evidence.json`.
- Every `bbox` must be four integers inside the canvas.
- Every element must use one of `svg_self_draw`, `crop`, or `crop_nobg`.
- SVG root `width`, `height`, and `viewBox` must match the canvas.
- SVG must not contain `file://`, `data:`, `base64`, external URLs, `<style>`, `<filter>`, `<mask>`, `<clipPath>`, `<foreignObject>`, `<textPath>`, `<symbol>`, or `<use>`.
- Raster `<image>` href values must be relative `assets/<box_id>.png` paths.

## Mainline Boundaries

Use only `scripts/run_expert_mvp.py`, `scripts/run_expert_mvp.py apply-response`, and `scripts/run_expert_mvp.py package-run` for normal reconstruction and delivery.

Do not describe fallback outputs as final high-quality editable reconstructions.
