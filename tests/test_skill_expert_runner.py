import json
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image
from pptx import Presentation


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_expert_mvp.py"
SAMPLE = Path("/Users/zdl/Downloads/attention__nano-banana-pro.png")


class SkillExpertRunnerTest(unittest.TestCase):
    def assert_openable_pptx_without_repair_prone_minimal_package(self, path: Path) -> None:
        presentation = Presentation(str(path))
        self.assertEqual(len(presentation.slides), 1)
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
        for required in [
            "ppt/theme/theme1.xml",
            "ppt/slideMasters/slideMaster1.xml",
            "ppt/slideLayouts/slideLayout1.xml",
        ]:
            self.assertIn(required, names)

    def assert_pptx_has_no_raster_media(self, path: Path) -> None:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            slide = archive.read("ppt/slides/slide1.xml").decode("utf-8")
        self.assertFalse(any(name.startswith("ppt/media/") for name in names), names)
        self.assertNotIn("<p:pic>", slide)

    def test_prompt_templates_exist(self) -> None:
        prompts_dir = ROOT / "prompts"
        expected = {
            "expert_structure.md": ["原图结构", "element_analysis.json", "svg_self_draw"],
            "expert_svg.md": ["output.svg", "viewBox", "PPTX"],
        }
        for filename, required_texts in expected.items():
            text = (prompts_dir / filename).read_text(encoding="utf-8")
            for required in required_texts:
                self.assertIn(required, text)

    def test_skill_workflow_keeps_runner_commands_constrained(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for required in [
            "Keep the shell working directory at the directory containing this `SKILL.md`",
            "Do not `cd` into `outputs/<image-stem>_work`",
            "Do not inspect `scripts/`, `_vendor/`, or converter source during a normal reconstruction",
            ".venv/bin/python outputs/<image-stem>_work/build_expert_response.py",
            "Re-run `apply-response` from the skill root",
        ]:
            self.assertIn(required, skill)

    def test_expert_runner_generates_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "run"

            subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--image",
                    str(SAMPLE),
                    "--out-dir",
                    str(out_dir),
                ],
                check=True,
            )

            evidence = json.loads((out_dir / "evidence.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["schema"], "happyfigure.edit.skill_evidence.v1")
            self.assertEqual(evidence["image"]["width"], 2752)
            self.assertEqual(evidence["image"]["height"], 1536)
            self.assertNotIn("overlay", evidence["artifacts"])

            analysis = json.loads((out_dir / "element_analysis.json").read_text(encoding="utf-8"))
            self.assertEqual(analysis["schema"], "happyfigure.edit.element_analysis.v1")
            self.assertEqual(analysis["source"], "skill_expert_mvp_baseline")
            self.assertEqual(analysis["elements"][0]["asset_strategy"], "crop")
            self.assertEqual(analysis["elements"][0]["bbox"], [0, 0, 2752, 1536])

            self.assertFalse((out_dir / "expert_prompt.md").exists())

            svg_path = out_dir / "output.svg"
            root = ET.parse(svg_path).getroot()
            self.assertEqual(root.attrib["viewBox"], "0 0 2752 1536")
            self.assertEqual(root.attrib["width"], "2752")
            self.assertEqual(root.attrib["height"], "1536")
            self.assertIn("attention__nano-banana-pro.png", svg_path.read_text(encoding="utf-8"))

            self.assertFalse((out_dir / "output.pptx").exists())
            self.assertFalse((out_dir / "output.trace.json").exists())

            status = json.loads((out_dir / "run_status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "ok")
            self.assertEqual(
                sorted(status["outputs"]),
                [
                    "element_analysis",
                    "element_overlay",
                    "evidence",
                    "quality_report",
                    "quality_summary",
                    "report",
                    "svg",
                ],
            )
            self.assertTrue((out_dir / "element_overlay.png").exists())
            self.assertTrue((out_dir / "report.html").exists())
            report = (out_dir / "report.html").read_text(encoding="utf-8")
            self.assertIn("happyfigure.edit.skill_run_status.v1", report)
            self.assertIn("element_analysis.json", report)
            self.assertIn("element_overlay.png", report)
            self.assertIn("Report Dependencies", report)
            self.assertTrue((out_dir / "quality_report.json").exists())
            self.assertTrue((out_dir / "quality_summary.txt").exists())

    def test_package_run_preserves_report_dependencies_without_duplicate_renamed_copies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_dir = root / "run"
            delivery_dir = root / "delivery"

            subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--image",
                    str(SAMPLE),
                    "--out-dir",
                    str(out_dir),
                ],
                check=True,
            )
            response = out_dir / "expert_response.json"
            response.write_text(
                json.dumps(
                    {
                        "schema": "happyfigure.edit.expert_response.v1",
                        "element_analysis": {
                            "schema": "happyfigure.edit.element_analysis.v1",
                            "source": "skill_expert_model",
                            "canvas": {"width": 2752, "height": 1536},
                            "strategy_summary": "Simple editable package smoke response.",
                            "elements": [
                                {
                                    "box_id": "T001",
                                    "source_candidate_ids": [],
                                    "bbox": [0, 0, 2752, 160],
                                    "kind": "text",
                                    "asset_strategy": "svg_self_draw",
                                    "confidence": "medium",
                                    "reason": "Title is editable text.",
                                    "evidence": ["Visible title at top."],
                                }
                            ],
                        },
                        "svg": '<svg xmlns="http://www.w3.org/2000/svg" width="2752" height="1536" viewBox="0 0 2752 1536"><rect x="0" y="0" width="2752" height="1536" fill="white"/><text x="1376" y="90" text-anchor="middle" font-size="56">Transformer Technical Route Map</text></svg>',
                        "notes": ["package smoke"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [sys.executable, str(RUNNER), "apply-response", "--run-dir", str(out_dir), "--response", str(response)],
                check=True,
            )
            self.assertFalse((out_dir / "output.pptx").exists())
            self.assertFalse((out_dir / "output.trace.json").exists())
            subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "package-run",
                    "--run-dir",
                    str(out_dir),
                    "--out-dir",
                    str(delivery_dir),
                    "--basename",
                    "docs2kg_rebuild",
                ],
                check=True,
            )
            self.assertTrue((out_dir / "output.pptx").exists())
            self.assertTrue((out_dir / "output.trace.json").exists())

            for required in [
                "report.html",
                "output.svg",
                "output.pptx",
                "element_overlay.png",
                "rendered.png",
                "diff.png",
                "quality_summary.txt",
                "quality_report.json",
                "run_status.json",
                "assets/attention__nano-banana-pro.png",
            ]:
                self.assertTrue((delivery_dir / required).exists(), required)
            self.assertFalse((delivery_dir / "docs2kg_rebuild.svg").exists())
            self.assertFalse((delivery_dir / "docs2kg_rebuild.pptx").exists())
            self.assert_openable_pptx_without_repair_prone_minimal_package(delivery_dir / "output.pptx")
            self.assert_pptx_has_no_raster_media(delivery_dir / "output.pptx")

            html = (delivery_dir / "report.html").read_text(encoding="utf-8")
            refs = re.findall(r'(?:src|data)="([^"]+)"', html)
            for ref in refs:
                if ref.startswith(("http://", "https://", "data:", "file://", "#")):
                    continue
                self.assertTrue((delivery_dir / ref).exists(), ref)

            manifest = json.loads((delivery_dir / "delivery_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], "happyfigure.edit.delivery_package.v1")
            self.assertEqual(manifest["missing_report_refs"], [])
            self.assertNotIn("docs2kg_rebuild.svg", manifest["copied"])
            self.assertNotIn("docs2kg_rebuild.pptx", manifest["copied"])

    def test_package_run_writes_figma_delivery_payload_without_mutating_canonical_svg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "input.png"
            canvas = Image.new("RGB", (120, 100), "white")
            for x in range(30, 50):
                for y in range(20, 40):
                    canvas.putpixel((x, y), (220, 30, 40))
            canvas.save(image)

            out_dir = root / "run"
            delivery_dir = root / "delivery"
            subprocess.run([sys.executable, str(RUNNER), "--image", str(image), "--out-dir", str(out_dir)], check=True)

            response = out_dir / "expert_response.json"
            canonical_svg = (
                '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="100" viewBox="0 0 120 100">'
                '<rect x="0" y="0" width="120" height="100" fill="white"/>'
                '<image href="assets/IMG001.png" x="30" y="20" width="20" height="20"/>'
                '<text x="60" y="70" text-anchor="middle" font-size="12">Editable label</text>'
                "</svg>"
            )
            response.write_text(
                json.dumps(
                    {
                        "schema": "happyfigure.edit.expert_response.v1",
                        "element_analysis": {
                            "schema": "happyfigure.edit.element_analysis.v1",
                            "source": "skill_expert_model",
                            "canvas": {"width": 120, "height": 100},
                            "strategy_summary": "Figma package smoke response.",
                            "elements": [
                                {
                                    "box_id": "IMG001",
                                    "source_candidate_ids": [],
                                    "bbox": [30, 20, 20, 20],
                                    "kind": "image",
                                    "asset_strategy": "crop",
                                    "confidence": "high",
                                    "reason": "Dense raster patch.",
                                    "evidence": ["Red square."],
                                },
                                {
                                    "box_id": "T001",
                                    "source_candidate_ids": [],
                                    "bbox": [20, 58, 80, 18],
                                    "kind": "text",
                                    "asset_strategy": "svg_self_draw",
                                    "confidence": "high",
                                    "reason": "Editable label.",
                                    "evidence": ["Bottom label."],
                                },
                            ],
                        },
                        "svg": canonical_svg,
                        "notes": ["figma package smoke"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [sys.executable, str(RUNNER), "apply-response", "--run-dir", str(out_dir), "--response", str(response)],
                check=True,
            )

            subprocess.run(
                [sys.executable, str(RUNNER), "package-run", "--run-dir", str(out_dir), "--out-dir", str(delivery_dir)],
                check=True,
            )

            self.assertEqual((delivery_dir / "output.svg").read_text(encoding="utf-8").strip(), canonical_svg)
            self.assertNotIn("data:image/png;base64", (delivery_dir / "output.svg").read_text(encoding="utf-8"))

            figma_svg_path = delivery_dir / "figma" / "output.figma.svg"
            figma_payload_path = delivery_dir / "figma" / "figma_payload.json"
            self.assertTrue(figma_svg_path.exists())
            self.assertTrue(figma_payload_path.exists())
            figma_svg = figma_svg_path.read_text(encoding="utf-8").strip()
            self.assertIn("data:image/png;base64,", figma_svg)
            self.assertNotIn('href="assets/IMG001.png"', figma_svg)

            payload = json.loads(figma_payload_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], "happyfigure.edit.figma_payload.v1")
            self.assertEqual(payload["canvas"], {"width": 120, "height": 100})
            self.assertEqual(payload["files"]["canonical_svg"], "../output.svg")
            self.assertEqual(payload["files"]["figma_svg"], "output.figma.svg")
            self.assertEqual(payload["svg"], canonical_svg)
            self.assertEqual(payload["figma_svg"], figma_svg)
            self.assertEqual(payload["element_analysis"]["elements"][0]["box_id"], "IMG001")
            asset = payload["assets"]["IMG001"]
            self.assertEqual(asset["path"], "../assets/IMG001.png")
            self.assertEqual(asset["mime_type"], "image/png")
            self.assertTrue(asset["data_base64"])

            manifest = json.loads((delivery_dir / "delivery_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("figma/output.figma.svg", manifest["copied"])
            self.assertIn("figma/figma_payload.json", manifest["copied"])

            status = json.loads((delivery_dir / "run_status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["outputs"]["figma_svg"], "figma/output.figma.svg")
            self.assertEqual(status["outputs"]["figma_payload"], "figma/figma_payload.json")

    def test_apply_response_materializes_crop_assets_before_svg_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "input.png"
            canvas = Image.new("RGB", (120, 100), "white")
            for x in range(20, 40):
                for y in range(15, 35):
                    canvas.putpixel((x, y), (220, 20, 30))
            for x in range(50, 70):
                for y in range(10, 30):
                    canvas.putpixel((x, y), (20, 80, 220))
            canvas.save(image)

            out_dir = root / "run"
            subprocess.run([sys.executable, str(RUNNER), "--image", str(image), "--out-dir", str(out_dir)], check=True)

            response = out_dir / "expert_response.json"
            response.write_text(
                json.dumps(
                    {
                        "schema": "happyfigure.edit.expert_response.v1",
                        "element_analysis": {
                            "schema": "happyfigure.edit.element_analysis.v1",
                            "source": "skill_expert_model",
                            "canvas": {"width": 120, "height": 100},
                            "strategy_summary": "One crop and one foreground crop.",
                            "elements": [
                                {
                                    "box_id": "IMG001",
                                    "source_candidate_ids": [],
                                    "bbox": [50, 10, 20, 20],
                                    "kind": "image",
                                    "asset_strategy": "crop",
                                    "confidence": "high",
                                    "reason": "Dense raster patch.",
                                    "evidence": ["Blue patch."],
                                },
                                {
                                    "box_id": "I001",
                                    "source_candidate_ids": [],
                                    "bbox": [20, 15, 20, 20],
                                    "kind": "icon",
                                    "asset_strategy": "crop_nobg",
                                    "crop_policy": {"padding": 2, "remove_background": True},
                                    "confidence": "high",
                                    "reason": "Foreground object should sit on SVG background.",
                                    "evidence": ["Red object on white background."],
                                },
                            ],
                        },
                        "svg": (
                            '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="100" viewBox="0 0 120 100">'
                            '<rect x="0" y="0" width="120" height="100" fill="white"/>'
                            '<image href="assets/IMG001.png" x="50" y="10" width="20" height="20"/>'
                            '<image href="assets/I001.png" x="18" y="13" width="24" height="24"/>'
                            "</svg>"
                        ),
                        "notes": ["crop asset smoke"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            subprocess.run(
                [sys.executable, str(RUNNER), "apply-response", "--run-dir", str(out_dir), "--response", str(response)],
                check=True,
            )

            crop = out_dir / "assets" / "IMG001.png"
            crop_nobg = out_dir / "assets" / "I001.png"
            self.assertTrue(crop.exists())
            self.assertTrue(crop_nobg.exists())
            with Image.open(crop) as crop_image:
                self.assertEqual(crop_image.size, (20, 20))
            with Image.open(crop_nobg) as nobg:
                self.assertEqual(nobg.mode, "RGBA")
                self.assertEqual(nobg.size, (24, 24))
                self.assertEqual(nobg.getpixel((0, 0))[3], 0)

            generated = json.loads((out_dir / "generated_assets.json").read_text(encoding="utf-8"))
            self.assertEqual(generated["assets"]["IMG001"]["path"], "assets/IMG001.png")
            self.assertEqual(generated["assets"]["I001"]["path"], "assets/I001.png")
            status = json.loads((out_dir / "run_status.json").read_text(encoding="utf-8"))
            self.assertIn("generated_assets", status["outputs"])

    def test_apply_response_uses_copied_input_asset_after_original_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "input.png"
            canvas = Image.new("RGB", (120, 100), "white")
            for x in range(25, 45):
                for y in range(20, 40):
                    canvas.putpixel((x, y), (30, 120, 210))
            canvas.save(image)

            out_dir = root / "run"
            subprocess.run([sys.executable, str(RUNNER), "--image", str(image), "--out-dir", str(out_dir)], check=True)
            image.unlink()

            response = out_dir / "expert_response.json"
            response.write_text(
                json.dumps(
                    {
                        "schema": "happyfigure.edit.expert_response.v1",
                        "element_analysis": {
                            "schema": "happyfigure.edit.element_analysis.v1",
                            "source": "skill_expert_model",
                            "canvas": {"width": 120, "height": 100},
                            "strategy_summary": "Crop must be materialized from the copied run asset.",
                            "elements": [
                                {
                                    "box_id": "IMG001",
                                    "source_candidate_ids": [],
                                    "bbox": [25, 20, 20, 20],
                                    "kind": "image",
                                    "asset_strategy": "crop",
                                    "confidence": "high",
                                    "reason": "Dense raster patch.",
                                    "evidence": ["Blue square."],
                                }
                            ],
                        },
                        "svg": (
                            '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="100" viewBox="0 0 120 100">'
                            '<rect x="0" y="0" width="120" height="100" fill="white"/>'
                            '<image href="assets/IMG001.png" x="25" y="20" width="20" height="20"/>'
                            "</svg>"
                        ),
                        "notes": ["source asset fallback smoke"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            subprocess.run(
                [sys.executable, str(RUNNER), "apply-response", "--run-dir", str(out_dir), "--response", str(response)],
                check=True,
            )

            self.assertTrue((out_dir / "assets" / "IMG001.png").exists())
            quality = json.loads((out_dir / "quality_report.json").read_text(encoding="utf-8"))
            self.assertEqual(quality["pixel_diff"]["status"], "ok")

    def test_quality_report_flags_unassigned_high_diff_regions_for_missing_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "input.png"
            canvas = Image.new("RGB", (120, 100), "white")
            for x in range(18, 62):
                for y in range(20, 31):
                    canvas.putpixel((x, y), (0, 0, 0))
            canvas.save(image)

            out_dir = root / "run"
            subprocess.run([sys.executable, str(RUNNER), "--image", str(image), "--out-dir", str(out_dir)], check=True)

            response = out_dir / "expert_response.json"
            response.write_text(
                json.dumps(
                    {
                        "schema": "happyfigure.edit.expert_response.v1",
                        "element_analysis": {
                            "schema": "happyfigure.edit.element_analysis.v1",
                            "source": "skill_expert_model",
                            "canvas": {"width": 120, "height": 100},
                            "strategy_summary": "A text-like source region was accidentally omitted.",
                            "elements": [
                                {
                                    "box_id": "T001",
                                    "source_candidate_ids": [],
                                    "bbox": [80, 70, 20, 14],
                                    "kind": "text",
                                    "asset_strategy": "svg_self_draw",
                                    "confidence": "medium",
                                    "reason": "Placeholder editable text.",
                                    "evidence": ["Small bottom label."],
                                }
                            ],
                        },
                        "svg": (
                            '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="100" viewBox="0 0 120 100">'
                            '<rect x="0" y="0" width="120" height="100" fill="white"/>'
                            "</svg>"
                        ),
                        "notes": ["missing content smoke"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            subprocess.run(
                [sys.executable, str(RUNNER), "apply-response", "--run-dir", str(out_dir), "--response", str(response)],
                check=True,
            )

            quality = json.loads((out_dir / "quality_report.json").read_text(encoding="utf-8"))
            self.assertTrue(quality["diff_regions"])
            unassigned = quality["unassigned_diff_regions"]
            self.assertTrue(unassigned)
            self.assertIn("missing_text_or_unmodeled_element", unassigned[0]["suggestion"])
            report = (out_dir / "report.html").read_text(encoding="utf-8")
            self.assertIn("Actionable Diff Regions", report)
            self.assertIn("missing_text_or_unmodeled_element", report)
            self.assertTrue((out_dir / "quality_summary.txt").exists())
            review_tiles = quality["review_tiles"]
            self.assertTrue(review_tiles)
            self.assertTrue((out_dir / review_tiles[0]["path"]).exists())

    def test_quality_report_flags_high_diff_inside_broad_zone_as_declared_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "input.png"
            canvas = Image.new("RGB", (140, 100), "white")
            for x in range(45, 95):
                for y in range(36, 54):
                    canvas.putpixel((x, y), (0, 0, 0))
            canvas.save(image)

            out_dir = root / "run"
            subprocess.run([sys.executable, str(RUNNER), "--image", str(image), "--out-dir", str(out_dir)], check=True)

            response = out_dir / "expert_response.json"
            response.write_text(
                json.dumps(
                    {
                        "schema": "happyfigure.edit.expert_response.v1",
                        "element_analysis": {
                            "schema": "happyfigure.edit.element_analysis.v1",
                            "source": "skill_expert_model",
                            "canvas": {"width": 140, "height": 100},
                            "strategy_summary": "Only a broad zone was declared, hiding missing internal content.",
                            "elements": [
                                {
                                    "box_id": "Z001",
                                    "source_candidate_ids": [],
                                    "bbox": [20, 20, 100, 60],
                                    "kind": "zone",
                                    "asset_strategy": "svg_self_draw",
                                    "confidence": "medium",
                                    "reason": "Broad zone container.",
                                    "evidence": ["Large panel."],
                                }
                            ],
                        },
                        "svg": (
                            '<svg xmlns="http://www.w3.org/2000/svg" width="140" height="100" viewBox="0 0 140 100">'
                            '<rect x="0" y="0" width="140" height="100" fill="white"/>'
                            '<rect x="20" y="20" width="100" height="60" fill="white" stroke="black"/>'
                            "</svg>"
                        ),
                        "notes": ["broad zone review smoke"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            subprocess.run(
                [sys.executable, str(RUNNER), "apply-response", "--run-dir", str(out_dir), "--response", str(response)],
                check=True,
            )

            quality = json.loads((out_dir / "quality_report.json").read_text(encoding="utf-8"))
            declared = quality["declared_region_review"]
            self.assertTrue(declared)
            self.assertEqual(declared[0]["coverage_status"], "weakly_covered")
            self.assertIn("declared_region_review", declared[0]["suggestion"])
            self.assertTrue(quality["review_tiles"])
            self.assertTrue((out_dir / quality["review_tiles"][0]["path"]).exists())
            summary = (out_dir / "quality_summary.txt").read_text(encoding="utf-8")
            self.assertIn("declared_region_review", summary)
            report = (out_dir / "report.html").read_text(encoding="utf-8")
            self.assertIn("Review Tiles", report)
            self.assertIn("review_tiles/", report)

    def test_quality_report_does_not_let_large_text_component_hide_high_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "input.png"
            canvas = Image.new("RGB", (180, 120), "white")
            for x in range(50, 130):
                for y in range(45, 65):
                    canvas.putpixel((x, y), (0, 0, 0))
            canvas.save(image)

            out_dir = root / "run"
            subprocess.run([sys.executable, str(RUNNER), "--image", str(image), "--out-dir", str(out_dir)], check=True)

            response = out_dir / "expert_response.json"
            response.write_text(
                json.dumps(
                    {
                        "schema": "happyfigure.edit.expert_response.v1",
                        "element_analysis": {
                            "schema": "happyfigure.edit.element_analysis.v1",
                            "source": "skill_expert_model",
                            "canvas": {"width": 180, "height": 120},
                            "strategy_summary": "All labels were incorrectly grouped into one large text bbox.",
                            "elements": [
                                {
                                    "box_id": "TALL",
                                    "source_candidate_ids": [],
                                    "bbox": [0, 0, 180, 120],
                                    "kind": "text",
                                    "asset_strategy": "svg_self_draw",
                                    "confidence": "medium",
                                    "reason": "Over-broad text declaration.",
                                    "evidence": ["Text-like content across the image."],
                                }
                            ],
                        },
                        "svg": (
                            '<svg xmlns="http://www.w3.org/2000/svg" width="180" height="120" viewBox="0 0 180 120">'
                            '<rect x="0" y="0" width="180" height="120" fill="white"/>'
                            "</svg>"
                        ),
                        "notes": ["large text coverage smoke"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            subprocess.run(
                [sys.executable, str(RUNNER), "apply-response", "--run-dir", str(out_dir), "--response", str(response)],
                check=True,
            )

            quality = json.loads((out_dir / "quality_report.json").read_text(encoding="utf-8"))
            declared = quality["declared_region_review"]
            self.assertTrue(declared)
            self.assertEqual(declared[0]["coverage_status"], "weakly_covered")
            self.assertIn("declared_region_review", declared[0]["suggestion"])
            warnings = quality["granularity_warnings"]
            self.assertTrue(any(row["box_id"] == "TALL" for row in warnings))
            summary = (out_dir / "quality_summary.txt").read_text(encoding="utf-8")
            self.assertIn("granularity_warnings", summary)

    def test_quality_report_flags_suspicious_crop_nobg_asset_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "input.png"
            canvas = Image.new("RGB", (120, 100), "white")
            for x in range(35, 72):
                for y in (35, 70):
                    canvas.putpixel((x, y), (0, 0, 0))
            for y in range(35, 71):
                for x in (35, 72):
                    canvas.putpixel((x, y), (0, 0, 0))
            for x in range(43, 58):
                for y in range(43, 58):
                    canvas.putpixel((x, y), (210, 40, 40))
            canvas.save(image)

            out_dir = root / "run"
            subprocess.run([sys.executable, str(RUNNER), "--image", str(image), "--out-dir", str(out_dir)], check=True)

            response = out_dir / "expert_response.json"
            response.write_text(
                json.dumps(
                    {
                        "schema": "happyfigure.edit.expert_response.v1",
                        "element_analysis": {
                            "schema": "happyfigure.edit.element_analysis.v1",
                            "source": "skill_expert_model",
                            "canvas": {"width": 120, "height": 100},
                            "strategy_summary": "Only the foreground icon was cropped; card border was missed.",
                            "elements": [
                                {
                                    "box_id": "I001",
                                    "source_candidate_ids": [],
                                    "bbox": [43, 43, 15, 15],
                                    "kind": "icon",
                                    "asset_strategy": "crop_nobg",
                                    "confidence": "medium",
                                    "reason": "Foreground icon inside a larger card.",
                                    "evidence": ["Red square foreground."],
                                }
                            ],
                        },
                        "svg": (
                            '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="100" viewBox="0 0 120 100">'
                            '<rect x="0" y="0" width="120" height="100" fill="white"/>'
                            '<image href="assets/I001.png" x="43" y="43" width="15" height="15"/>'
                            "</svg>"
                        ),
                        "notes": ["asset integrity smoke"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            subprocess.run(
                [sys.executable, str(RUNNER), "apply-response", "--run-dir", str(out_dir), "--response", str(response)],
                check=True,
            )

            quality = json.loads((out_dir / "quality_report.json").read_text(encoding="utf-8"))
            asset_review = quality["asset_integrity_review"]
            self.assertTrue(asset_review)
            self.assertEqual(asset_review[0]["box_id"], "I001")
            self.assertIn("missing icon/card background", asset_review[0]["suggestion"])
            self.assertTrue((out_dir / asset_review[0]["review_tile"]).exists())
            summary = (out_dir / "quality_summary.txt").read_text(encoding="utf-8")
            self.assertIn("asset_integrity_review", summary)

    def test_apply_response_rejects_simplified_icon_line_art(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "input.png"
            Image.new("RGB", (120, 100), "white").save(image)

            out_dir = root / "run"
            subprocess.run([sys.executable, str(RUNNER), "--image", str(image), "--out-dir", str(out_dir)], check=True)

            response = out_dir / "expert_response.json"
            response.write_text(
                json.dumps(
                    {
                        "schema": "happyfigure.edit.expert_response.v1",
                        "element_analysis": {
                            "schema": "happyfigure.edit.element_analysis.v1",
                            "source": "skill_expert_model",
                            "canvas": {"width": 120, "height": 100},
                            "strategy_summary": "Small icons are simplified as editable geometry.",
                            "elements": [
                                {
                                    "box_id": "I001",
                                    "source_candidate_ids": [],
                                    "bbox": [20, 20, 30, 30],
                                    "kind": "icon",
                                    "asset_strategy": "svg_self_draw",
                                    "confidence": "medium",
                                    "reason": "Kept small icons as simplified editable geometry.",
                                    "evidence": ["Complex source icon."],
                                }
                            ],
                        },
                        "svg": (
                            '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="100" viewBox="0 0 120 100">'
                            '<rect x="0" y="0" width="120" height="100" fill="white"/>'
                            '<circle cx="35" cy="35" r="12" fill="none" stroke="black"/>'
                            "</svg>"
                        ),
                        "notes": ["Kept small icons as simplified editable geometry."],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(RUNNER), "apply-response", "--run-dir", str(out_dir), "--response", str(response)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("crop_nobg", result.stderr + result.stdout)

    def test_apply_response_repairs_diff_detected_crop_nobg_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "input.png"
            canvas = Image.new("RGB", (140, 100), "white")
            for x in range(20, 62):
                for y in range(30, 65):
                    if ((x - 42) / 22) ** 2 + ((y - 47) / 17) ** 2 <= 1:
                        canvas.putpixel((x, y), (210, 40, 45))
            canvas.save(image)

            out_dir = root / "run"
            subprocess.run([sys.executable, str(RUNNER), "--image", str(image), "--out-dir", str(out_dir)], check=True)

            response = out_dir / "expert_response.json"
            response.write_text(
                json.dumps(
                    {
                        "schema": "happyfigure.edit.expert_response.v1",
                        "element_analysis": {
                            "schema": "happyfigure.edit.element_analysis.v1",
                            "source": "skill_expert_model",
                            "canvas": {"width": 140, "height": 100},
                            "strategy_summary": "Foreground crop is accidentally clipped on the left.",
                            "elements": [
                                {
                                    "box_id": "OBJ001",
                                    "source_candidate_ids": [],
                                    "bbox": [32, 30, 30, 35],
                                    "kind": "glyph",
                                    "asset_strategy": "crop_nobg",
                                    "confidence": "medium",
                                    "reason": "Complex foreground object.",
                                    "evidence": ["Red oval object."],
                                }
                            ],
                        },
                        "svg": (
                            '<svg xmlns="http://www.w3.org/2000/svg" width="140" height="100" viewBox="0 0 140 100">'
                            '<rect x="0" y="0" width="140" height="100" fill="white"/>'
                            '<image href="assets/OBJ001.png" x="32" y="30" width="30" height="35"/>'
                            "</svg>"
                        ),
                        "notes": ["truncated crop smoke"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            subprocess.run(
                [sys.executable, str(RUNNER), "apply-response", "--run-dir", str(out_dir), "--response", str(response)],
                check=True,
            )

            repair = json.loads((out_dir / "crop_repair_report.json").read_text(encoding="utf-8"))
            applied = {row["box_id"]: row for row in repair["applied"]}
            self.assertIn("OBJ001", applied)
            self.assertLess(applied["OBJ001"]["bbox"][0], 32)

            svg_text = (out_dir / "output.svg").read_text(encoding="utf-8")
            repaired_x = applied["OBJ001"]["bbox"][0]
            self.assertIn(f'x="{repaired_x}"', svg_text)
            analysis = json.loads((out_dir / "element_analysis.json").read_text(encoding="utf-8"))
            self.assertEqual(analysis["elements"][0]["bbox"][0], repaired_x)
            generated = json.loads((out_dir / "generated_assets.json").read_text(encoding="utf-8"))
            self.assertEqual(generated["assets"]["OBJ001"]["bbox"][0], repaired_x)
            self.assertTrue((out_dir / "assets" / "OBJ001.png").exists())

    def test_apply_response_repairs_structural_crop_nobg_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "input.png"
            canvas = Image.new("RGB", (120, 100), "white")
            for x in range(20, 83):
                for y in (20, 82):
                    canvas.putpixel((x, y), (0, 0, 0))
            for y in range(20, 83):
                for x in (20, 82):
                    canvas.putpixel((x, y), (0, 0, 0))
            for x in range(32, 55):
                for y in range(36, 39):
                    canvas.putpixel((x, y), (130, 130, 130))
            for x in range(32, 68):
                for y in range(50, 53):
                    canvas.putpixel((x, y), (130, 130, 130))
            canvas.save(image)

            out_dir = root / "run"
            subprocess.run([sys.executable, str(RUNNER), "--image", str(image), "--out-dir", str(out_dir)], check=True)

            response = out_dir / "expert_response.json"
            response.write_text(
                json.dumps(
                    {
                        "schema": "happyfigure.edit.expert_response.v1",
                        "element_analysis": {
                            "schema": "happyfigure.edit.element_analysis.v1",
                            "source": "skill_expert_model",
                            "canvas": {"width": 120, "height": 100},
                            "strategy_summary": "Document icon bbox is clipped on right and bottom.",
                            "elements": [
                                {
                                    "box_id": "DOC001",
                                    "source_candidate_ids": [],
                                    "bbox": [20, 20, 55, 55],
                                    "kind": "icon",
                                    "asset_strategy": "crop_nobg",
                                    "confidence": "medium",
                                    "reason": "Document icon foreground.",
                                    "evidence": ["Document icon."],
                                }
                            ],
                        },
                        "svg": (
                            '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="100" viewBox="0 0 120 100">'
                            '<rect x="0" y="0" width="120" height="100" fill="white"/>'
                            '<image href="assets/DOC001.png" x="20" y="20" width="55" height="55"/>'
                            "</svg>"
                        ),
                        "notes": ["structural crop repair smoke"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            subprocess.run(
                [sys.executable, str(RUNNER), "apply-response", "--run-dir", str(out_dir), "--response", str(response)],
                check=True,
            )

            repair = json.loads((out_dir / "crop_repair_report.json").read_text(encoding="utf-8"))
            applied = {row["box_id"]: row for row in repair["applied"]}
            self.assertIn("DOC001", applied)
            self.assertEqual(applied["DOC001"]["repair_type"], "clipped_foreground")
            self.assertGreater(applied["DOC001"]["bbox"][2], 55)
            self.assertGreater(applied["DOC001"]["bbox"][3], 55)
            self.assertEqual(applied["DOC001"]["structural"]["repair_type"], "clipped_foreground")

    def test_expert_response_bundle_replaces_fallback_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "run"

            subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--image",
                    str(SAMPLE),
                    "--out-dir",
                    str(out_dir),
                ],
                check=True,
            )

            response = out_dir / "expert_response.json"
            response.write_text(
                json.dumps(
                    {
                        "schema": "happyfigure.edit.expert_response.v1",
                        "element_analysis": {
                            "schema": "happyfigure.edit.element_analysis.v1",
                            "source": "skill_expert_model",
                            "canvas": {"width": 2752, "height": 1536},
                            "strategy_summary": "Simple editable smoke response.",
                            "elements": [
                                {
                                    "box_id": "T001",
                                    "source_candidate_ids": [],
                                    "bbox": [0, 0, 2752, 160],
                                    "kind": "text",
                                    "asset_strategy": "svg_self_draw",
                                    "confidence": "medium",
                                    "reason": "Title is editable text.",
                                    "evidence": ["Visible title at top."],
                                }
                            ],
                        },
                        "svg": '<svg xmlns="http://www.w3.org/2000/svg" width="2752" height="1536" viewBox="0 0 2752 1536"><rect x="0" y="0" width="2752" height="1536" fill="white"/><text x="1376" y="90" text-anchor="middle" font-size="56">Transformer Technical Route Map</text></svg>',
                        "notes": ["smoke"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "apply-response",
                    "--run-dir",
                    str(out_dir),
                    "--response",
                    str(response),
                ],
                check=True,
            )

            analysis = json.loads((out_dir / "element_analysis.json").read_text(encoding="utf-8"))
            self.assertEqual(analysis["source"], "skill_expert_model")
            self.assertEqual(analysis["elements"][0]["box_id"], "T001")

            svg_text = (out_dir / "output.svg").read_text(encoding="utf-8")
            self.assertIn("Transformer Technical Route Map", svg_text)
            self.assertNotIn("attention__nano-banana-pro.png", svg_text)

            status = json.loads((out_dir / "run_status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["mode"], "expert_applied")
            self.assertEqual(status["expert_response"], "expert_response.json")
            self.assertIn("report", status["outputs"])
            self.assertIn("quality_report", status["outputs"])
            self.assertNotIn("pptx", status["outputs"])
            self.assertNotIn("pptx_trace", status["outputs"])
            self.assertFalse((out_dir / "output.pptx").exists())
            self.assertFalse((out_dir / "output.trace.json").exists())
            report = (out_dir / "report.html").read_text(encoding="utf-8")
            self.assertIn("output.svg", report)
            self.assertIn("skill_expert_model", report)
            quality = json.loads((out_dir / "quality_report.json").read_text(encoding="utf-8"))
            self.assertEqual(quality["schema"], "happyfigure.edit.quality_report.v1")
            self.assertEqual(quality["component_count"], 1)
            self.assertEqual(quality["pixel_diff"]["status"], "ok")
            self.assertTrue((out_dir / quality["pixel_diff"]["rendered_png"]).exists())
            self.assertTrue((out_dir / quality["pixel_diff"]["diff_png"]).exists())

            delivery_dir = Path(tmp) / "delivery"
            subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "package-run",
                    "--run-dir",
                    str(out_dir),
                    "--out-dir",
                    str(delivery_dir),
                ],
                check=True,
            )
            with zipfile.ZipFile(out_dir / "output.pptx") as archive:
                names = archive.namelist()
                slide = archive.read("ppt/slides/slide1.xml").decode("utf-8")
            self.assertFalse(any(name.startswith("ppt/media/") for name in names), names)
            self.assertGreaterEqual(slide.count("<p:sp>"), 1)
            self.assertIn("Transformer Technical Route Map", slide)
            self.assertIn('prst="rect"', slide)
            self.assert_openable_pptx_without_repair_prone_minimal_package(out_dir / "output.pptx")
            self.assert_openable_pptx_without_repair_prone_minimal_package(delivery_dir / "output.pptx")

    def test_normalize_svg_for_figma_strips_ns0_prefix(self) -> None:
        probe = (
            "import sys\n"
            "sys.path.insert(0, r'" + str(RUNNER.parent) + "')\n"
            "import runpy\n"
            "ns = runpy.run_path(r'" + str(RUNNER) + "', run_name='rem_probe')\n"
            "normalize = ns['normalize_svg_for_figma']\n"
            "prefixed = ('<ns0:svg xmlns:ns0=\"http://www.w3.org/2000/svg\" width=\"10\" height=\"10\" viewBox=\"0 0 10 10\">'\n"
            "            '<ns0:rect x=\"0\" y=\"0\" width=\"10\" height=\"10\" fill=\"#fff\" />'\n"
            "            '<ns0:text x=\"5\" y=\"5\">Hi</ns0:text>'\n"
            "            '</ns0:svg>')\n"
            "normalized = normalize(prefixed)\n"
            "assert 'ns0:' not in normalized, normalized\n"
            "assert normalized.startswith('<svg xmlns=\"http://www.w3.org/2000/svg\"'), normalized\n"
            "assert '<rect ' in normalized and '<text ' in normalized and '</svg>' in normalized, normalized\n"
            "clean = '<svg xmlns=\"http://www.w3.org/2000/svg\"><rect/></svg>'\n"
            "assert normalize(clean) == clean\n"
            "print('ok')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout.strip(), "ok")

if __name__ == "__main__":
    unittest.main()
