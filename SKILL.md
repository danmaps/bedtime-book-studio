---
name: bedtime-book-studio
description: Create, illustrate, preview, revise, and publish mobile-friendly landscape children's picture books (including interactive Lift-the-Flap Reality-vs-Imagination books and standard step-by-step picture books) from a user photo and/or text description and story idea. Supports persistent character/pet/prop identities, reality-to-imaginary reference chaining, contact-sheet previews, single-page revision with rollback, and Bedtime Mode.
---

# Bedtime Book Studio (`bedtime-book-studio`)

Turn a photo and/or character description plus a bedtime story idea into a fully illustrated, mobile-friendly landscape web picture book in minutes.

By default, every book is compiled into:
1. **A self-contained Single-File HTML Book (`<slug>.html`)**: All HTML, CSS, JavaScript, and WebP illustrations are embedded inside one portable `.html` file that opens directly in any browser, can be AirDropped/texted/emailed to a phone or tablet, or dropped onto any static host.
2. **Local Device Hosting (`http://localhost:8765/<slug>/` & `http://<lan-ip>:8765/<slug>/`)**: Automatically served locally on the user's machine so they can open it immediately on their computer or on a phone/tablet connected to the same Wi-Fi.
3. **Interactive Bedtime Mode (`🌙 Bedtime`)**: Subdued low-blue-light twilight palette, reduced motion, no confetti, and no automatic wraparound at the end of the book.

---

## Step 0: Check Onboarding & Persistent Identities (`get_onboarding_status` / `list_identities`)

Before creating a book, ALWAYS check whether the user has completed first-time onboarding:
- **Via MCP tool**: Call `get_onboarding_status()` and `list_identities()`
- **Via CLI**:
  ```bash
  python3 scripts/book_studio.py status
  python3 scripts/book_studio.py identities
  ```

### Setting Up or Updating Persistent Identities (`upsert_identity` / `manage_identity_reference`)
To prevent mixing up siblings, pets, or recurring toys across books, store each character, pet, and recurring prop with a stable ID (`char-...`, `pet-...`, `prop-...`) in gitignored `local_profile/identities.json`:
- **Main & Supporting Characters (`main_character`, `supporting_character`)**: Assign `name`, `age_or_size` (relative height/age), `appearance`, `signature_outfit`, `reality_description`, `imaginary_transformation`, and labeled `reference_photos`.
- **Pets & Recurring Props (`pet`, `prop`)**: Explicitly distinguish `reality_description` (how the toy looks in the living room/driveway) from `imaginary_transformation` (what it transforms into under the lifted flap).
- **Managing Individual References**: Use `manage_identity_reference(entity_id, action="update", ref_id="ref-02", active=False)` to include/exclude or relabel specific reference photos without altering other profiles.

---

## Step 1: Initialize the Book Project (`create_book_project`)

Initialize the new book workspace, selecting `cast_ids` and optional per-book `entity_overrides` (e.g. a special outfit for this story without changing the global profile):
- **Via MCP tool**: `create_book_project(slug, title, idea, cast_ids=[...], entity_overrides={...}, bedtime_mode=True)`
- **Via CLI**:
  ```bash
  python3 scripts/book_studio.py init \
    --slug "leos-cardboard-rocket" \
    --title "Leo's Cardboard Rocket" \
    --idea "Leo turns a cardboard moving box in the living room into a lunar rocket ship" \
    --cast-ids char-leo char-maya pet-biscuit prop-cardboard-rocket \
    --bedtime-mode
  ```

---

## Step 2: Author the Storyboard & Transformation Mappings (`save_book_storyboard`)

Write the complete storyboard JSON (see `examples/sample-storyboard.json`) and save it via `save_book_storyboard`:
1. **Per-Page Entity Binding (`entity_ids`)**: List which stable IDs (`["char-leo", "prop-cardboard-rocket"]`) appear on each page so `prompts.md` and `required_images` attach the exact labeled reference files for those entities.
2. **Convincing Flap Reveals (`shared_composition` & `transformation_mappings`)**:
   - Every `lift-the-flap` page should specify `shared_composition` (`camera_angle`, `horizon_line`, `focal_subject_placement`, `character_pose`, `key_shapes`) and `transformation_mappings` (`reality_element` -> `imaginary_element` at `spatial_anchor`).
3. **Gradual Bedtime Wind-Down**:
   - Over the final 2–3 pages, gently lower the story's energy and transition lighting toward cozy evening/bedtime, providing calm `bedtime_kicker`, `bedtime_title`, and `bedtime_subtitle` fields in `end`.

---

## Step 2b: Preview & Review Before Final Artwork (`generate_book_preview`)

Generate `<project_dir>/preview.html` via `generate_book_preview(slug)` (or `python3 scripts/book_studio.py preview --slug <slug>`):
- Works **text-first (with 0 images)** so parents can review story pacing, text, and transformation mappings before generating illustrations.
- Works with **draft thumbnails (`is_draft=True`)** or **final candidates**, providing an interactive **Reality ↔ Imaginary Opacity Alignment Inspector** and review checklist.

---

## Step 3: Two-Stage Illustration Generation & Ingestion (`ingest_generated_images`)

1. **Stage 1 — Generate Cover & Reality Scenes First**:
   - Pass each page's assigned `entity_references` to your image generator for `cover` and `page-XX-reality`.
2. **Stage 2 — Generate Imaginary Scenes Using Reality as Reference**:
   - For each `page-XX-imaginary`, pass the approved `assets/page-XX-reality.png` (`primary_composition_reference`) alongside character references so the imaginary world matches the exact framing, pose, and object positions of the reality flap!
3. **Ingest & Archive**:
   - Call `ingest_generated_images(slug, image_map)` to normalize to `1280x960` `.png` + `.webp`. Existing images are automatically archived in `assets/history/<key>/v<NNN>.png`.

---

## Step 4: Targeted Single-Page Revisions & Rollback (`revise_book_page` / `rollback_book_asset`)

Never regenerate the entire book for a small fix:
- **`text-only`**: `revise_book_page(slug, page_number=3, scope="text-only", paragraphs=[...])` updates the text and atomically rebuilds the reader without touching any artwork.
- **`reality-only` / `imaginary-only` / `paired-scene`**: Updates only the requested scene on that single page while preserving all other approved illustrations.
- **Rollback**: Call `rollback_book_asset(slug, asset_key="page-01-reality", version=1)` to restore any prior version from `assets/history/` and rebuild the reader.

---

## Step 5: Build & Host Locally (`build_and_publish_book`)

Compile the book into a **single-file standalone HTML book** (`<slug>.html`) and start the local device server:
- **Via MCP tool**: `build_and_publish_book(slug, serve_local=True, bedtime_mode=True)`
- **Via CLI**:
  ```bash
  python3 scripts/book_studio.py publish --slug "leos-cardboard-rocket"
  ```
