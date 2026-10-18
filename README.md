# Bedtime Book Studio 📚✨

**Turn a quick photo (or character description) and a bedtime story idea into an interactive, mobile-friendly landscape children's picture book in minutes.**

| 1. Toss your agent a photo & a story idea... | 2. ...get an interactive bedtime book on your iPad! |
| :---: | :---: |
| ![Input photo of a child in a cardboard box rocket](docs/images/example-input-photo.jpg) | ![Finished bedtime book cover on an iPad in landscape mode](docs/images/example-ipad-book.jpg) |
| *"Leo turns a cardboard moving box in the living room into a rocket ship landing on the moon."* | **Single-file `.html` book** + **instant local Wi-Fi hosting** with interactive **Lift-the-Flap** pages |

**Bedtime Book Studio** is an open-source **Agent Skill** and **Model Context Protocol (MCP) server** that works with any AI coding/chat agent (Claude Code, Cursor, Antigravity, Windsurf, OpenClaw, etc.).

When your book finishes building, you get:
1. **A Single-File HTML Picture Book (`books/<slug>.html`)**:
   Every illustration (`.webp`), stylesheet, and interactive page-turn/flap script is bundled into **one self-contained `.html` file**. You can double-click it to open in any browser, AirDrop/text/email it straight to your phone or iPad for bedtime, or drop that single file onto any static web host.
2. **Instant Local Hosting on Your Device**:
   By default, Bedtime Book Studio automatically serves your books locally on your machine (`http://localhost:8765/<slug>/`) and prints your device's **local Wi-Fi URL** (`http://<your-lan-ip>:8765/<slug>/`) so you can open the book immediately on a phone or tablet on the same Wi-Fi network.
3. **Optional Custom Self-Hosting**:
   If you run your own web server or static site folder, you can optionally set `PUBLISH_WEB_ROOT` and `PUBLISH_BASE_URL` in `.env` to auto-copy new books to your server.

---

## ✨ Two Interactive Book Modes

1. **Lift-the-Flap Mode (`lift-the-flap` — Default)**:
   - Every story page shows the everyday **Reality** scene on a tactile, stitched cardboard flap.
   - Kids can tap the button, press `Space`/`F`, or drag the flap upward with their finger to lift it in 3D and reveal the **Imaginary** world underneath!
2. **Standard Picture-Book Mode (`standard`)**:
   - Classic single-illustration landscape spreads with big read-aloud typography, a `Aa Text Only` focus mode, and a celebratory *"Hooray! The End"* confetti finale.

---

## 🚀 Step-by-Step Setup (2 Minutes)

### Prerequisites
- **Python 3.10+**
- Any AI agent that supports **MCP** or **Skills** (and has access to an image generation tool/subagent).

### Step 1: Clone the Repo & Run Setup
```bash
git clone https://github.com/danmaps/bedtime-book-studio.git
cd bedtime-book-studio
./setup.sh
```

What `./setup.sh` does:
1. Creates a local Python virtual environment (`.venv/`) and installs `Pillow` + `mcp`.
2. Launches the **interactive onboarding wizard** to set up your main character and defaults, saving everything locally in `.env` (which is gitignored).
3. Prints the exact copy-paste config snippet for your AI agent.

> **Tip:** Want your AI agent to interview you in chat instead of using the terminal wizard? Run `./setup.sh --skip-onboard`. The first time you ask your agent to make a book, it will detect that `.env` isn't configured yet and walk you through onboarding right in chat!

---

### Step 2: Connect Your AI Agent

Choose **MCP Server**, **Agent Skill**, or both:

#### Option A: Connect via MCP (Claude Code, Cursor, Antigravity, Windsurf)
Add `bedtime-book-studio` to your agent's MCP config file (for example `~/.claude.json`, `.cursor/mcp.json`, or `~/.gemini/config/mcp_config.json`):

```json
{
  "mcpServers": {
    "bedtime-book-studio": {
      "command": "/absolute/path/to/bedtime-book-studio/.venv/bin/python",
      "args": [
        "/absolute/path/to/bedtime-book-studio/scripts/mcp_server.py"
      ]
    }
  }
}
```
*(Note: `./setup.sh` prints this exact JSON block with your real absolute paths filled in!)*

#### Option B: Connect via Agent Skill (`SKILL.md`)
Symlink the repo into your agent's skills folder:

```bash
mkdir -p ~/.agents/skills
ln -sfn "$(pwd)" ~/.agents/skills/bedtime-book-studio
```

---

### Step 3: Onboard Your Main Character (Photo and/or Text)

During onboarding (via `./setup.sh`, `python3 scripts/book_studio.py onboard`, or in chat with your agent), you configure your default character once:

- **Name & Age**: e.g. `Leo`, age `4`
- **Visual Reference (Photo, Text, or Both)**:
  - **Photo(s)**: Provide path(s) to 1 or more photos of your main character. They are copied into `./local_profile/references/` (gitignored) and automatically included as visual references in future books.
  - **Text Description & Outfit**: Describe their hair, eyes, skin tone, and signature outfit (e.g., *"4-year-old with curly brown hair, wearing a red striped T-shirt and denim overalls"*). You can use text alone or combine it with reference photos for rock-solid consistency.
- **Supporting Cast & Favorite Toys (Optional)**: Pets, siblings, parents, or favorite real-world toys that frequently appear in bedtime stories.
- **Book Defaults**: `lift-the-flap` vs. `standard` mode, default page count (`12`), and default illustration style.

All of these settings live in your local `.env` file. You can re-run onboarding anytime:
```bash
./.venv/bin/python scripts/book_studio.py onboard
```

---

## 📖 Making a Bedtime Book

Once connected, just ask your AI agent in plain English:

> *"Make a new lift-the-flap bedtime book! Here's a photo of our cardboard box (`/path/to/box.jpg`). The story is about turning a cardboard moving box in the living room into a rocket ship landing on the moon."*

### What Happens Behind the Scenes:
1. **`create_book_project`**: Scaffolds `books/<slug>/` and copies your default character photo(s) from `.env` plus any new prop photo(s).
2. **`save_book_storyboard`**: Writes `storyboard.json` and `prompts.md` with locked character continuity and matching **Reality** + **Imaginary** scene prompts for every page.
3. **`ingest_generated_images`**: Your agent generates the illustrations, and Bedtime Book Studio center-crops every image to `1280x960` (4:3 landscape) and exports `.png` + `.webp`.
4. **`build_and_publish_book`**:
   - Generates the **single-file standalone HTML book** at `books/<slug>.html` (and `books/<slug>/<slug>.html`).
   - Generates the standard multi-file folder at `books/<slug>/index.html`.
   - Starts the **local device web server** so you can read immediately!

---

## 📱 Reading on Your Phone, Tablet, or Computer

Out of the box, you have three easy ways to read your finished book:

### 1. Open the Single-File HTML Book (`books/<slug>.html`)
- Every book produces a completely self-contained `books/<slug>.html` file (~2–4 MB total, with all illustrations embedded).
- **Double-click** `books/<slug>.html` on your computer to read in any browser.
- **AirDrop, iMessage, WhatsApp, or email** `books/<slug>.html` to your phone or tablet and tap it to open full-screen in landscape mode!

### 2. Read Over Local Wi-Fi (Built-In Local Server)
- When `publish` runs, it automatically starts a lightweight local server on port `8765` (configurable via `LOCAL_SERVER_PORT` in `.env`):
  - **On your computer**: `http://localhost:8765/<slug>/`
  - **On your phone/tablet (same Wi-Fi)**: `http://<your-computer-lan-ip>:8765/<slug>/`
- Need to restart the local server later? Run:
  ```bash
  ./.venv/bin/python scripts/book_studio.py serve
  ```

### 3. Optional Self-Hosting (Bring Your Own Web Server / Static Host)
- **Single-File Upload**: Because `books/<slug>.html` has zero external dependencies, you can drag-and-drop it onto Netlify Drop, Cloudflare Pages, GitHub Pages, S3, or any static host.
- **Automated Static Folder Copy**: If you run a local or remote web server directory (Nginx, Caddy, Tailscale Serve, etc.), set these optional variables in `.env`:
  ```env
  PUBLISH_WEB_ROOT="/var/www/my-site/books"
  PUBLISH_BASE_URL="https://example.com/books"
  ```
  Whenever a book is published, Bedtime Book Studio will automatically copy the built book into `<PUBLISH_WEB_ROOT>/<slug>` and return `<PUBLISH_BASE_URL>/<slug>`.

---

## 🛠️ CLI & MCP Tool Reference

| MCP Tool | CLI Command | Description |
| :--- | :--- | :--- |
| `get_onboarding_status` | `book_studio.py status` | Check if `.env` onboarding is complete and get onboarding instructions |
| `configure_studio` | `book_studio.py onboard` / `configure` | Save character photo(s), text description, outfit, and defaults to `.env` |
| `get_studio_profile` | `book_studio.py profile` | View the active character, identities, and studio configuration |
| `list_identities` | `book_studio.py identities` | List persistent characters, siblings, pets, and props (`local_profile/identities.json`) |
| `upsert_identity` | `book_studio.py upsert-identity` | Create/update an entity with a stable ID (`char-...`, `pet-...`, `prop-...`) and reality vs. imaginary rules |
| `manage_identity_reference` | `book_studio.py identity-ref` | Add, relabel, or include/exclude (`--active false`) an individual reference photo |
| `list_existing_books` | `book_studio.py list` | List all generated books, single-file HTML paths, preview sheets, and local URLs |
| `create_book_project` | `book_studio.py init` | Scaffold a new book project with selected `cast_ids` and per-book `entity_overrides` |
| `save_book_storyboard` | `book_studio.py storyboard` | Save `storyboard.json`, transformation mappings, and reference-chained `prompts.md` |
| `generate_book_preview` | `book_studio.py preview` | Generate `preview.html` contact sheet & interactive Reality↔Imagination alignment inspector |
| `ingest_generated_images` | `book_studio.py ingest` | Center-crop images to 4:3 (`1280x960`), export `.png` + `.webp`, and archive prior versions |
| `revise_book_page` | `book_studio.py revise` | Revise one page (`text-only`, `reality-only`, `imaginary-only`, `paired-scene`) without touching approved art |
| `approve_book_assets` | `book_studio.py approve` | Mark storyboard and/or specific illustration assets as approved |
| `rollback_book_asset` | `book_studio.py rollback` | Restore a prior archived version of an illustration from `assets/history/` |
| `get_revision_status` | *(in `revision_state.json`)* | Inspect approval state, version history, and revision log for a book |
| `build_and_publish_book` | `book_studio.py publish` | Atomically build single-file `<slug>.html` + multi-file reader (with `🌙 Bedtime Mode`) and serve locally |
| *(CLI helper)* | `book_studio.py serve` | Start or check the local device HTTP server for `BOOKS_OUTPUT_DIR` |

---

## 🔒 Privacy by Design

- `.env`, `local_profile/`, and `books/` are all gitignored in [`.gitignore`](.gitignore).
- Your personal family photos, character names, and generated books never leave your device unless you choose to share them.

---

## 📄 License

MIT License — see [LICENSE](LICENSE).
