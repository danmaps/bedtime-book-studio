#!/usr/bin/env python3
"""
Automated test suite for Bedtime Book Studio covering:
  - Issue #1: Persistent character, sibling, pet, and prop identities across books
  - Issue #2: Reality↔Imagination transformation mappings, shared composition & reference chaining
  - Issue #3: Targeted single-page revision (text-only, reality-only, imaginary-only), version history & rollback
  - Issue #4: Bedtime mode calm ending, reduced motion & no-wraparound reader output
  - Issue #5: Storyboard & alignment contact-sheet preview (text-first, draft, and approved states)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import book_studio


class BedtimeBookStudioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env_file = self.root / ".env"
        self.local_profile_dir = self.root / "local_profile"
        self.local_refs_dir = self.local_profile_dir / "references"
        self.identities_file = self.local_profile_dir / "identities.json"
        self.books_dir = self.root / "books"

        self.patchers = [
            mock.patch.object(book_studio, "ENV_FILE", self.env_file),
            mock.patch.object(book_studio, "LOCAL_PROFILE_DIR", self.local_profile_dir),
            mock.patch.object(book_studio, "LOCAL_REFS_DIR", self.local_refs_dir),
            mock.patch.object(book_studio, "IDENTITIES_FILE", self.identities_file),
        ]
        for p in self.patchers:
            p.start()

        book_studio.configure_studio(
            main_character_name="Leo",
            main_character_age="4",
            main_character_description="Curly brown hair, hazel eyes",
            main_character_outfit="Red striped T-shirt and denim overalls",
            books_output_dir=str(self.books_dir),
        )

    def tearDown(self) -> None:
        for p in reversed(self.patchers):
            p.stop()
        self.tmp.cleanup()

    def _make_sample_image(self, name: str, color: tuple[int, int, int]) -> Path:
        p = self.root / name
        im = Image.new("RGB", (640, 480), color=color)
        im.save(p, format="PNG")
        return p

    def test_issue1_two_siblings_two_pets_across_two_books_and_ref_management(self) -> None:
        leo_ref1 = self._make_sample_image("leo1.png", (220, 50, 50))
        leo_ref2 = self._make_sample_image("leo2.png", (200, 60, 60))
        maya_ref = self._make_sample_image("maya.png", (120, 80, 200))
        biscuit_ref = self._make_sample_image("biscuit.png", (210, 170, 90))
        mochi_ref = self._make_sample_image("mochi.png", (30, 30, 35))

        book_studio.upsert_identity(
            entity_id="char-leo",
            name="Leo",
            kind="main_character",
            age_or_size="4yo, toddler height",
            appearance="Curly brown hair, hazel eyes",
            signature_outfit="Red striped tee, denim overalls",
            reality_description="Red striped tee and denim overalls",
            imaginary_transformation="Commander Leo in a bubble space helmet",
            reference_photos=[str(leo_ref1), str(leo_ref2)],
            reference_labels=["Leo front smile", "Leo side profile"],
        )
        book_studio.upsert_identity(
            entity_id="char-maya",
            name="Maya",
            kind="supporting_character",
            age_or_size="6yo, half a head taller than Leo",
            appearance="Braided pigtails, round glasses",
            signature_outfit="Lavender sweater",
            reference_photos=[str(maya_ref)],
            reference_labels=["Maya with glasses"],
        )
        book_studio.upsert_identity(
            entity_id="pet-biscuit",
            name="Biscuit",
            kind="pet",
            age_or_size="Small scruffy golden terrier",
            appearance="Wire-haired golden fur, red collar",
            reference_photos=[str(biscuit_ref)],
            reference_labels=["Biscuit sitting"],
        )
        book_studio.upsert_identity(
            entity_id="pet-mochi",
            name="Mochi",
            kind="pet",
            age_or_size="Plump black-and-white tuxedo cat",
            appearance="Black fur, white paws, green eyes",
            reference_photos=[str(mochi_ref)],
            reference_labels=["Mochi curled up"],
        )

        # Exclude leo's second reference without affecting Maya, Biscuit, or Mochi
        book_studio.manage_identity_reference(
            entity_id="char-leo",
            action="update",
            ref_id="ref-02",
            active=False,
        )

        # Book 1 uses default outfits; Book 2 overrides Leo's outfit to star pajamas without mutating global profile
        b1 = book_studio.init_book_project(
            slug="book-one",
            title="Book One",
            idea="Backyard campout",
            cast_ids=["char-leo", "char-maya", "pet-biscuit", "pet-mochi"],
        )
        b2 = book_studio.init_book_project(
            slug="book-two",
            title="Book Two",
            idea="Moonlight train",
            cast_ids=["char-leo", "char-maya", "pet-biscuit", "pet-mochi"],
            entity_overrides={"char-leo": {"reality_description": "Blue star pajamas"}},
        )

        # Verify active refs for char-leo only include ref-01 (since ref-02 was excluded)
        self.assertEqual(len(b1["entity_reference_manifest"]["char-leo"]), 1)
        self.assertEqual(b1["entity_reference_manifest"]["char-leo"][0]["label"], "Leo front smile")
        self.assertEqual(len(b1["entity_reference_manifest"]["char-maya"]), 1)
        self.assertEqual(len(b1["entity_reference_manifest"]["pet-biscuit"]), 1)
        self.assertEqual(len(b1["entity_reference_manifest"]["pet-mochi"]), 1)

        # Global profile for char-leo is still "Red striped tee and denim overalls"
        global_leo = book_studio.load_identities()["char-leo"]
        self.assertEqual(global_leo["reality_description"], "Red striped tee and denim overalls")
        self.assertEqual(b2["entity_overrides"]["char-leo"]["reality_description"], "Blue star pajamas")

    def test_issue2_and_5_transformation_mappings_reference_chaining_and_preview(self) -> None:
        sample_sb = json.loads((REPO_ROOT / "examples" / "sample-storyboard.json").read_text(encoding="utf-8"))
        book_studio.init_book_project(
            slug="leos-cardboard-rocket",
            title=sample_sb["title"],
            idea="Cardboard box rocket to the moon",
        )

        # Save storyboard with reference support enabled
        sb_res = book_studio.save_storyboard("leos-cardboard-rocket", sample_sb, supports_reference_images=True)
        reqs = {r["key"]: r for r in sb_res["required_images"]}

        p1_real = reqs["page-01-reality"]
        p1_imag = reqs["page-01-imaginary"]
        self.assertEqual(p1_imag["depends_on"], "page-01-reality")
        self.assertTrue(p1_imag["primary_composition_reference"].endswith("assets/page-01-reality.png"))
        self.assertIn("Shared Scene Composition Lock", p1_real["prompt"])
        self.assertIn("Flap Reveal 1-to-1 Element Transformations", p1_imag["prompt"])
        self.assertIn("prop-cardboard-rocket", p1_imag["prompt"])

        # Verify capability warning when image tool does not support reference images
        sb_no_ref = book_studio.save_storyboard("leos-cardboard-rocket", sample_sb, supports_reference_images=False)
        self.assertGreater(len(sb_no_ref["capability_warnings"]), 0)

        # Verify text-first preview works before any images are generated
        prev1 = book_studio.generate_book_preview("leos-cardboard-rocket")
        preview_html = Path(prev1["preview_html"]).read_text(encoding="utf-8")
        self.assertIn("TEXT-FIRST (NO IMAGE YET)", preview_html)
        self.assertIn("prop-cardboard-rocket", preview_html)

    def test_issue3_and_4_targeted_revision_rollback_and_bedtime_mode(self) -> None:
        sample_sb = json.loads((REPO_ROOT / "examples" / "sample-storyboard.json").read_text(encoding="utf-8"))
        book_studio.init_book_project(
            slug="leos-cardboard-rocket",
            title=sample_sb["title"],
            idea="Cardboard box rocket",
        )
        book_studio.save_storyboard("leos-cardboard-rocket", sample_sb)

        # Ingest v1 images (red for p1-reality, green for p2-reality)
        img_red = self._make_sample_image("red.png", (240, 20, 20))
        img_blue = self._make_sample_image("blue.png", (20, 60, 240))
        img_green = self._make_sample_image("green.png", (20, 200, 60))

        book_studio.ingest_book_images(
            "leos-cardboard-rocket",
            {
                "cover": str(img_red),
                "page-01-reality": str(img_red),
                "page-01-imaginary": str(img_blue),
                "page-02-reality": str(img_green),
            },
            note="v1 initial art",
        )
        book_studio.approve_book_assets("leos-cardboard-rocket", asset_keys=["page-02-reality"])

        # 1. Text-only revision on Page 1 does NOT trigger image generation and preserves approved Page 2
        rev_text = book_studio.revise_book_page(
            slug="leos-cardboard-rocket",
            page_number=1,
            scope="text-only",
            paragraphs=["Updated read-aloud line one.", "Updated line two."],
        )
        self.assertFalse(rev_text["requires_image_generation"])
        self.assertEqual(rev_text["affected_assets"], [])
        standalone_html = (self.books_dir / "leos-cardboard-rocket.html").read_text(encoding="utf-8")
        self.assertIn("Updated read-aloud line one.", standalone_html)
        self.assertIn('data-default-bedtime="true"', standalone_html)
        self.assertIn("🌙 GOODNIGHT, COMMANDER LEO", standalone_html)

        # 2. Ingest v2 for page-01-reality (blue) and then roll back to v1 (red)
        book_studio.ingest_book_images(
            "leos-cardboard-rocket",
            {"page-01-reality": str(img_blue)},
            note="v2 test change",
        )
        active_p1 = self.books_dir / "leos-cardboard-rocket" / "assets" / "page-01-reality.png"
        with Image.open(active_p1) as im:
            r, g, b = im.getpixel((10, 10))
            self.assertGreater(b, r)  # Blue v2 active

        rb_res = book_studio.rollback_book_asset("leos-cardboard-rocket", "page-01-reality", version=1)
        self.assertEqual(rb_res["restored_version"], 1)
        with Image.open(active_p1) as im:
            r, g, b = im.getpixel((10, 10))
            self.assertGreater(r, b)  # Red v1 restored!

        # Page 2's approved status was completely preserved
        rev_status = book_studio.get_revision_status("leos-cardboard-rocket")
        self.assertEqual(rev_status["assets"]["page-02-reality"]["status"], "approved")

    def test_issue9_qr_code_generation_for_local_wifi(self) -> None:
        sample_sb = json.loads((REPO_ROOT / "examples" / "sample-storyboard.json").read_text(encoding="utf-8"))
        # Trim to 1 page for fast full-asset publish test
        sample_sb["pages"] = [sample_sb["pages"][0]]
        book_studio.init_book_project(
            slug="qr-test-book",
            title="QR Test Book",
            idea="Testing QR delivery",
            page_count=1,
        )
        book_studio.save_storyboard("qr-test-book", sample_sb)

        img = self._make_sample_image("sample.png", (100, 150, 220))
        book_studio.ingest_book_images(
            "qr-test-book",
            {
                "cover": str(img),
                "page-01-reality": str(img),
                "page-01-imaginary": str(img),
            },
        )

        pub = book_studio.publish_book("qr-test-book", serve_local=False, deploy_static=False)
        self.assertTrue(pub["lan_url"].endswith("/qr-test-book.html"))
        self.assertTrue(pub["cover_data_uri"].startswith("data:image/webp;base64,"))
        self.assertFalse((self.books_dir / "qr-test-book" / "index.html").exists())
        self.assertFalse((self.books_dir / "qr-test-book" / "qr-test-book.html").exists())
        self.assertTrue((self.books_dir / "qr-test-book.html").exists())
        qr_svg_path = Path(pub["lan_qr_svg_path"])
        self.assertTrue(qr_svg_path.exists())
        svg_text = qr_svg_path.read_text(encoding="utf-8")
        self.assertIn("<svg", svg_text)
        self.assertIn(pub["lan_url"], svg_text)
        self.assertIn("█", pub["lan_qr_ascii"])

    def test_issue10_storyboard_schema_validation_aliases_and_publish_guard(self) -> None:
        book_studio.init_book_project(
            slug="schema-test-book",
            title="Schema Test Book",
            idea="Testing schema validation",
            page_count=1,
        )

        # 1. Malformed storyboard (missing title and missing imaginary_prompt in lift-the-flap mode) fails fast
        invalid_sb = {
            "mode": "lift-the-flap",
            "cover": {"prompt": "Cover prompt"},
            "pages": [
                {
                    "number": 1,
                    "title": "Page 1",
                    "paragraphs": ["Hello world"],
                    "reality_prompt": "Real scene",
                    # missing imaginary_prompt!
                }
            ],
        }
        with self.assertRaises(book_studio.StoryboardValidationError) as ctx:
            book_studio.save_storyboard("schema-test-book", invalid_sb)
        err_msg = str(ctx.exception)
        self.assertIn("root.title", err_msg)
        self.assertIn("imaginary_prompt", err_msg)

        # 2. Legacy aliases ('cover_prompt', 'text', 'real_prompt', 'imaginary_caption', 'flap_hint') normalize cleanly with warnings
        legacy_sb = {
            "title": "Legacy Alias Book",
            "mode": "lift-the-flap",
            "cover_prompt": "A warm cover prompt",
            "pages": [
                {
                    "number": 1,
                    "title": "Page One",
                    "text": "Single string paragraph that gets normalized to list.",
                    "real_prompt": "Everyday living room scene.",
                    "imaginary_prompt": "Magical outer space scene.",
                    "imaginary_caption": "Outer Space!",
                    "flap_hint": "Lift the rocket flap!",
                }
            ],
        }
        saved = book_studio.save_storyboard("schema-test-book", legacy_sb)
        self.assertGreaterEqual(len(saved["validation_warnings"]), 5)
        saved_on_disk = json.loads(Path(saved["storyboard_path"]).read_text(encoding="utf-8"))
        self.assertEqual(saved_on_disk["cover"]["prompt"], "A warm cover prompt")
        self.assertEqual(
            saved_on_disk["pages"][0]["paragraphs"],
            ["Single string paragraph that gets normalized to list."],
        )
        self.assertEqual(saved_on_disk["pages"][0]["reality_prompt"], "Everyday living room scene.")
        self.assertEqual(saved_on_disk["pages"][0]["imagination_label"], "Outer Space!")
        self.assertEqual(saved_on_disk["pages"][0]["flap_prompt"], "Lift the rocket flap!")

        # 3. Pre-publish asset guard refuses to publish when required images are missing on disk
        with self.assertRaises(book_studio.StoryboardValidationError) as pub_ctx:
            book_studio.publish_book("schema-test-book", serve_local=False, deploy_static=False)
        self.assertIn("assets/cover.png", str(pub_ctx.exception))
        self.assertIn("assets/page-01-reality.png", str(pub_ctx.exception))
        self.assertIn("assets/page-01-imaginary.png", str(pub_ctx.exception))

    def test_issue11_art_style_presets_and_aliases(self) -> None:
        presets_info = book_studio.list_style_presets()
        self.assertGreaterEqual(presets_info["count"], 6)
        preset_keys = {p["key"] for p in presets_info["presets"]}
        self.assertIn("watercolor-ink", preset_keys)
        self.assertIn("bold-gouache", preset_keys)
        self.assertIn("claymation", preset_keys)
        self.assertIn("paper-cutout", preset_keys)
        self.assertIn("crayon-storybook", preset_keys)
        self.assertIn("retro-midcentury", preset_keys)

        # Verify natural aliases resolve to canonical preset keys
        maisy = book_studio.resolve_art_style(style_preset="maisy", style_notes="Extra bright yellow accents.")
        self.assertEqual(maisy["style_preset"], "bold-gouache")
        self.assertIn("Maisy", maisy["art_style"])
        self.assertIn("Extra bright yellow accents.", maisy["art_style"])

        clay = book_studio.resolve_art_style(style_preset="stop-motion")
        self.assertEqual(clay["style_preset"], "claymation")
        self.assertIn("polymer-clay and plasticine", clay["art_style"])

        # Configure studio default preset to bold-gouache, then override per-book with claymation
        book_studio.configure_studio(
            main_character_name="Leo",
            main_character_description="4-year-old with curly brown hair",
            default_style_preset="maisy",
        )
        profile = book_studio.get_studio_profile()
        self.assertEqual(profile["defaults"]["style_preset"], "bold-gouache")

        meta = book_studio.init_book_project(
            slug="clay-adventure",
            title="Leo's Clay Adventure",
            idea="Sculpting a castle on the kitchen table",
            style_preset="claymation",
            style_notes="Warm miniature desk lamp glow.",
            page_count=1,
        )
        self.assertEqual(meta["style_preset"], "claymation")
        self.assertIn("polymer-clay and plasticine", meta["art_style"])
        self.assertIn("Warm miniature desk lamp glow.", meta["art_style"])

        # Global profile default must remain bold-gouache
        self.assertEqual(book_studio.get_studio_profile()["defaults"]["style_preset"], "bold-gouache")

    def test_issue12_editable_book_plan_dry_run_and_apply_roundtrip(self) -> None:
        book_studio.configure_studio(
            main_character_name="Leo",
            main_character_age="4",
            main_character_description="curly brown hair, denim overalls",
        )
        book_studio.upsert_identity(
            entity_id="prop-cardboard-rocket",
            name="Cardboard Box Rocket",
            kind="prop",
            reality_description="Brown corrugated cardboard moving box with crayon stars",
            imaginary_transformation="Gleaming silver-and-red lunar command module",
        )

        # 1. Generate dry-run book-plan.md (2 pages)
        plan_res = book_studio.generate_book_plan(
            slug="dry-run-rocket",
            title="Leo's Dry-Run Rocket",
            idea="Leo turns a cardboard box into a moon rocket",
            page_count=2,
            style_preset="watercolor-ink",
            bedtime_mode=True,
        )
        self.assertTrue(plan_res["dry_run"])
        self.assertEqual(plan_res["images_generated"], 0)
        self.assertFalse(plan_res["site_built"])

        plan_path = Path(plan_res["book_plan_path"])
        self.assertTrue(plan_path.exists())
        project_dir = plan_path.parent
        # Verify dry-run did not build index.html or standalone html
        self.assertFalse((project_dir / "index.html").exists())
        self.assertFalse((project_dir / "dry-run-rocket.html").exists())

        md_text = plan_path.read_text(encoding="utf-8")
        self.assertIn("## How to Edit & Execute This Plan", md_text)
        self.assertIn("- **Style Preset**: watercolor-ink", md_text)
        self.assertIn("### Page 01:", md_text)
        self.assertIn("### Page 02:", md_text)

        # 2. Simulate user editing book-plan.md:
        #    - Switch style preset to 'maisy' (bold-gouache)
        #    - Add custom Style Notes
        #    - Edit Page 1 Story Text & Imaginary Visual Direction
        #    - Append a new Page 03 section
        edited_md = md_text.replace(
            "- **Style Preset**: watercolor-ink",
            "- **Style Preset**: maisy",
        ).replace(
            "- **Style Notes**: ",
            "- **Style Notes**: Keep outlines extra bold and playful.",
        ).replace(
            "[Page 1 — Setting Up the Adventure] Leo explores the next step of the adventure: Leo turns a cardboard box into a moon rocket",
            "Leo climbed into the big brown moving box on the living room rug.\n\nHe tapped the paper-plate dials twice: BEEP-BOOP!",
        )

        page3_block = """### Page 03: Touchdown on the Pillow Moon
- **Badge**: Page 3
- **Active Entities**: char-leo, prop-cardboard-rocket
- **Refrain**: Shhh... moon landing complete.
- **Flap Prompt**: Lift the flap to see the tranquil lunar sea!
- **Imagination Label**: Inside Leo's Sleepy Moon World

#### Story Text
The rocket glided down onto a pile of soft bedtime pillows.

#### Shared Composition Lock
- **Camera Angle**: Wide twilight shot
- **Horizon Line**: Lower third
- **Subject Placement**: Center
- **Character Pose**: Curled up cozily inside the box
- **Key Shapes**: Box silhouette, pillow craters

#### Flap Transformation Mappings
- `[prop-cardboard-rocket] @ Center`: Cardboard box nestled in pillows -> Lunar lander resting on a glowing velvet moon crater

#### Reality Visual Direction
Cozy evening living room with Leo resting inside the cardboard box surrounded by soft pillows.

#### Imaginary Visual Direction
Matching the exact composition, the lunar lander rests peacefully on a glowing moon crater under starry skies.

---

## 5. End Card"""

        edited_md = edited_md.replace("## 5. End Card", page3_block)
        plan_path.write_text(edited_md, encoding="utf-8")

        # 3. Apply the edited book-plan.md
        applied = book_studio.apply_book_plan("dry-run-rocket")
        self.assertEqual(applied["status"], "book_plan_applied")
        self.assertEqual(applied["style_preset"], "bold-gouache")
        self.assertEqual(applied["page_count"], 3)
        self.assertEqual(applied["total_images_needed"], 1 + 3 * 2)  # 1 cover + 3*(reality+imaginary)
        self.assertTrue(Path(applied["storyboard_path"]).exists())
        self.assertTrue(Path(applied["prompts_markdown_path"]).exists())
        self.assertTrue(Path(applied["preview_html_path"]).exists())

        sb_after = json.loads(Path(applied["storyboard_path"]).read_text(encoding="utf-8"))
        self.assertEqual(sb_after["style_preset"], "bold-gouache")
        self.assertIn("Keep outlines extra bold and playful.", sb_after["art_style"])
        self.assertEqual(len(sb_after["pages"]), 3)
        self.assertEqual(
            sb_after["pages"][0]["paragraphs"],
            [
                "Leo climbed into the big brown moving box on the living room rug.",
                "He tapped the paper-plate dials twice: BEEP-BOOP!",
            ],
        )
        self.assertEqual(sb_after["pages"][2]["title"], "Touchdown on the Pillow Moon")
        self.assertEqual(
            sb_after["pages"][2]["transformation_mappings"][0]["imaginary_element"],
            "Lunar lander resting on a glowing velvet moon crater",
        )


if __name__ == "__main__":
    unittest.main()

