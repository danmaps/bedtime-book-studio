---
name: bedtime-book-studio
description: Create, illustrate, and publish mobile-friendly landscape children's picture books (including interactive Lift-the-Flap Reality-vs-Imagination books and standard step-by-step picture books) from a user photo and/or text description and story idea. Includes built-in first-time onboarding stored in a local `.env` file.
---

# Bedtime Book Studio (`bedtime-book-studio`)

Turn a photo and/or character description plus a bedtime story idea into a fully illustrated, mobile-friendly landscape web picture book in minutes.

---

## Step 0: Check Onboarding Status First (`get_onboarding_status`)

Before creating a book, ALWAYS check whether the user has completed first-time onboarding:
- **Via MCP tool**: Call `get_onboarding_status()`
- **Via CLI**:
  ```bash
  python3 scripts/book_studio.py status
  ```

### If `is_onboarded` is `false` (or the user wants to update their defaults):
Walk the user through a quick, friendly onboarding conversation (or ask them to run `python3 scripts/book_studio.py onboard`):
1. **Main Character Name & Age**: e.g., *"Leo"*, age *"4"*.
2. **Main Character Visuals (Photo and/or Text)**:
   - Ask if they have **one or more reference photos** of the main character (`main_character_photos`), **and/or** a **text appearance description** (`main_character_description` — hair, eyes, skin tone, glasses, etc.) and **signature default outfit** (`main_character_outfit`).
   - Either photo(s), text description, or both work seamlessly. Any reference photos are copied into the gitignored `local_profile/references/` folder.
3. **Supporting Cast & Favorite Props (Optional)**:
   - Family members, pets (`supporting_characters`), or favorite toys (`recurring_props`).
4. **Book Format & Style Defaults**:
   - `default_book_mode`: `"lift-the-flap"` (Reality scene on top flap, lifts up to reveal the Imaginary world underneath) or `"standard"` (single illustration per page).
   - `default_page_count`: typically `10`–`16` pages (default `12`).
   - `default_art_style`: defaults to warm hand-drawn ink outlines with soft watercolor fills.
5. **Publishing Defaults (Optional)**:
   - `books_output_dir`: local directory for book workspaces (defaults to `./books`).
   - `publish_web_root` & `publish_base_url`: optional static site directory and base URL for one-command unlisted web deployment.

Save these settings to the local `.env` file via:
- **MCP tool**: `configure_studio(...)`
- **CLI**:
  ```bash
  python3 scripts/book_studio.py configure \
    --name "Leo" \
    --age "4" \
    --description "Curious 4-year-old with curly brown hair and bright hazel eyes" \
    --outfit "Red striped T-shirt, denim overalls, yellow sneakers" \
    --photos "/path/to/photo.jpg" \
    --mode "lift-the-flap" \
    --pages 12
  ```

---

## Step 1: Initialize the Book Project (`create_book_project`)

Once onboarding is complete, initialize the new book workspace. Any fields you omit (`mode`, `character_name`, `character_description`, `page_count`) automatically inherit the user's `.env` defaults, and default character reference photos are copied automatically alongside any new prop/scene photos passed in `reference_images`:

- **Via MCP tool**: `create_book_project(slug, title, idea, mode=..., reference_images=[...])`
- **Via CLI**:
  ```bash
  python3 scripts/book_studio.py init \
    --slug "leos-cardboard-rocket" \
    --title "Leo's Cardboard Rocket" \
    --idea "Leo turns a big cardboard moving box in the living room into a lunar rocket ship" \
    --refs "/optional/path/to/prop-photo.jpg"
  ```

---

## Step 2: Author the Storyboard & Continuity Lock (`save_book_storyboard`)

Write the complete storyboard JSON (see `examples/sample-storyboard.json` for a complete example) and save it via `save_book_storyboard` (or `python3 scripts/book_studio.py storyboard --slug <slug> --file storyboard.json`):

1. **Character & Prop Continuity Lock (`character_bible`)**:
   - Combine the user's `.env` character description/outfit with any visual details observed in the reference photo(s).
   - Explicitly distinguish real-world props vs. imaginary-world transformations when using `lift-the-flap` mode.
2. **Page Structure (`pages` array)**:
   - Keep `paragraphs` short and punchy for bedtime read-aloud (1–3 sentences per page).
   - Include a catchy `refrain` on key action pages.
   - For `lift-the-flap` mode, provide both `reality_prompt` and `imaginary_prompt` with matching camera angles so lifting the flap feels like a magical transformation.
   - Every prompt must specify: *"4:3 horizontal landscape picture-book illustration, no text or letters in the image."*

---

## Step 3: Generate Illustrations & Ingest (`ingest_generated_images`)

1. **Generate the Cover + Page 1 Anchor First**:
   - Pass the user's reference photo(s) from `<project_dir>/assets/references/` to your image generator when generating `cover` and `page-01-reality`.
2. **Generate Remaining Pages in Parallel Batches**:
   - Pass `cover` and `page-01-reality` as visual style/character anchors to all subsequent image generation calls so every page stays visually consistent.
3. **Ingest & Optimize**:
   - Call `ingest_generated_images(slug, image_map)` (or `python3 scripts/book_studio.py ingest --slug <slug> --map-json <map.json>`) to center-crop all images to `1280x960` (4:3) and generate both `.png` and `.webp` files in `assets/`.

---

## Step 4: Build & Publish the Reader (`build_and_publish_book`)

Compile the mobile-friendly landscape book reader (`index.html`, `styles.css`, `script.js`):
- **Via MCP tool**: `build_and_publish_book(slug, deploy_static=True, deploy_docker=False)`
- **Via CLI**:
  ```bash
  python3 scripts/book_studio.py publish --slug "leos-cardboard-rocket"
  ```
- If `PUBLISH_WEB_ROOT` and `PUBLISH_BASE_URL` are configured in `.env`, the book is immediately copied to `<PUBLISH_WEB_ROOT>/<slug>` and available at `<PUBLISH_BASE_URL>/<slug>`.
- Otherwise, preview locally right away with the returned `local_preview_command` (`python3 -m http.server 8080 --directory <workspace_dir>`) or pass `--docker` to launch a local Nginx container.
