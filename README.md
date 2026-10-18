# Bedtime Book Studio 📚✨

**Bedtime Book Studio** is an open-source Agent Skill and **Model Context Protocol (MCP) server** that lets you toss any AI coding agent (Claude Code, Antigravity, Cursor, OpenClaw, Windsurf, etc.) a photo and/or character description plus a bedtime story idea—and get a fully illustrated, mobile-friendly **landscape children's picture book** in minutes.

It supports two interactive book formats out of the box:
1. **Lift-the-Flap Mode (`lift-the-flap`)**: Every story page displays the everyday **Reality** scene on a tactile, hinged cardboard flap; kids can tap or drag the flap upward to reveal the **Imaginary** world underneath!
2. **Standard Picture-Book Mode (`standard`)**: Classic single-illustration landscape spreads with big read-aloud typography, Focus Text mode, and a celebratory "Hooray! The End" confetti finale.

---

## ✨ Features

- **Guided First-Time Onboarding (`.env`)**:
  - Set up your main character once—using **reference photo(s)**, a **text appearance description**, or **both**—along with their signature outfit, supporting cast (family, pets), favorite recurring toys/props, art style, and default page count.
  - Stored locally in a gitignored `.env` file (and `local_profile/references/` for copied reference photos) so your personal photos and family details never leave your machine or get committed to git.
  - Works both **interactively in the terminal** (`./setup.sh` or `python3 scripts/book_studio.py onboard`) and **conversationally through your AI agent** (`get_onboarding_status` -> `configure_studio`).
- **Mobile-First Landscape Web Reader**:
  - Side-by-side artwork stage + read-aloud story panel designed for phones and tablets held horizontally at bedtime.
  - Smooth 3D CSS/pointer-drag **Lift-the-Flap** mechanics (`Space` / `F` shortcut, tap button, or drag up/down).
  - Keyboard navigation (`←` / `→`), swipe gestures, Focus Text toggle, image preloading, and a confetti celebration finale.
- **Image Normalization & WebP Pipeline**:
  - Automatically center-crops generated illustrations to `1280x960` (4:3 landscape) and exports both `.png` and optimized `.webp` assets.
- **Flexible Publishing**:
  - Preview locally with one command, spin up a self-contained Nginx Docker container, or automatically copy to a static website folder for instant unlisted sharing (`https://yourdomain.com/<book-slug>`).

---

## 🚀 Quick Start & Onboarding

### 1. Clone & Run Setup
```bash
git clone https://github.com/danmaps/bedtime-book-studio.git
cd bedtime-book-studio
./setup.sh
```

`./setup.sh` will:
1. Create a local Python virtual environment (`.venv`) and install `Pillow` + `mcp`.
2. Launch the **interactive onboarding wizard** (`python3 scripts/book_studio.py onboard`), walking you through:
   - **Main character details**: Name, age, reference photo path(s) (optional), text description (optional if photo provided, or use both!), and default outfit.
   - **Supporting characters & favorite props**: Pets, siblings, parents, or favorite toys to keep consistent across books.
   - **Book & art style defaults**: `lift-the-flap` vs. `standard` mode, default page count, and illustration style prompt.
   - **Publishing defaults**: Local output folder (`./books`) and optional static web root / base URL.
3. Save your configuration to `.env` (gitignored) and print ready-to-paste MCP & Skill config snippets.

> **Prefer to onboard through your AI agent instead?**
> Skip the terminal wizard with `./setup.sh --skip-onboard`. The first time you ask your agent to make a book, it will call `get_onboarding_status()`, see that onboarding isn't complete yet, ask you for your character's photo/description and preferences in chat, and save them to `.env` via `configure_studio()`.

---

## 🔌 Connecting to Your AI Agent

### Option A: MCP Server (Claude Code, Antigravity, Cursor, Windsurf)

Add `bedtime-book-studio` to your MCP configuration file (e.g., `~/.claude.json`, `~/.gemini/config/mcp_config.json`, or `.cursor/mcp.json`):

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

### Option B: Agent Skill (`SKILL.md`)

Symlink the repository into your agent's skills directory:

```bash
mkdir -p ~/.agents/skills
ln -sfn /absolute/path/to/bedtime-book-studio ~/.agents/skills/bedtime-book-studio
```

---

## 🛠️ Available MCP Tools & CLI Commands

| MCP Tool | CLI Command | Description |
| :--- | :--- | :--- |
| `get_onboarding_status` | `book_studio.py status` | Check if `.env` onboarding is complete and retrieve onboarding instructions |
| `configure_studio` | `book_studio.py configure` / `onboard` | Save main character photo(s), text description, outfit, and defaults to `.env` |
| `get_studio_profile` | `book_studio.py profile` | View the active character and studio configuration loaded from `.env` |
| `list_existing_books` | `book_studio.py list` | List all generated books and their workspace/live paths |
| `create_book_project` | `book_studio.py init` | Scaffold a new book project and copy character/prop reference photos |
| `save_book_storyboard` | `book_studio.py storyboard` | Validate and save `storyboard.json` and generate `prompts.md` |
| `ingest_generated_images` | `book_studio.py ingest` | Center-crop generated images to 4:3 (`1280x960`) and export `.png` + `.webp` |
| `build_and_publish_book` | `book_studio.py publish` | Build the interactive landscape reader and deploy to static web root or Docker |

---

## 📖 Example Prompt at Bedtime

Once connected, just tell your agent:

> *"Use bedtime-book-studio to make a new 12-page lift-the-flap bedtime book! Here's a photo of our cardboard box rocket (`/path/to/box.jpg`). The story is about turning a moving box in the living room into a lunar lander on the moon."*

Your agent will:
1. Load your main character's photo/description and style defaults from `.env`.
2. Scaffold the book workspace and write a 12-page Reality-vs-Imagination storyboard (`storyboard.json`).
3. Generate the cover and page illustrations with character continuity locked.
4. Ingest the images into `.png` + `.webp` and compile the interactive lift-the-flap web reader!

---

## 🔒 Privacy by Design

- `.env`, `local_profile/`, and `books/` are all listed in `.gitignore`.
- Your personal reference photos, character names, and generated family books stay strictly on your local filesystem.

---

## 📄 License

MIT License — see [LICENSE](LICENSE).
