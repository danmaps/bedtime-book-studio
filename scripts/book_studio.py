#!/usr/bin/env python3
"""
Bedtime Book Studio — Core Engine & Onboarding CLI

Manages local `.env` user onboarding (main character photo and/or text description,
outfit, supporting cast, art style, and defaults) and executes the end-to-end
children's picture-book pipeline:
  0. onboard / configure — Interactive or agent-driven setup stored in local `.env`
  1. init                — Scaffold a new book workspace & copy reference photos
  2. storyboard          — Save `storyboard.json` & generate `prompts.md`
  3. ingest              — Normalize, crop (4:3), and convert art to `.png` + `.webp`
  4. publish             — Build a self-contained single-file HTML book (`<slug>.html`)
                           plus standard web assets, and host locally on the user's device
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image, ImageOps

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ENV_FILE = REPO_ROOT / ".env"
ENV_EXAMPLE_FILE = REPO_ROOT / ".env.example"
LOCAL_PROFILE_DIR = REPO_ROOT / "local_profile"
LOCAL_REFS_DIR = LOCAL_PROFILE_DIR / "references"
TEMPLATES_READER_DIR = REPO_ROOT / "templates" / "reader"

DEFAULT_ENV_VALUES: Dict[str, str] = {
    "ONBOARDING_COMPLETE": "false",
    "MAIN_CHARACTER_NAME": "",
    "MAIN_CHARACTER_AGE": "",
    "MAIN_CHARACTER_DESCRIPTION": "",
    "MAIN_CHARACTER_OUTFIT": "",
    "MAIN_CHARACTER_PHOTO_PATHS": "",
    "SUPPORTING_CHARACTERS": "",
    "RECURRING_PROPS": "",
    "DEFAULT_ART_STYLE": (
        "Children's picture-book illustration with hand-drawn warm ink outlines and "
        "soft flat watercolor washes, warm natural daylight, expressive friendly faces, "
        "4:3 horizontal landscape composition, no text or letters in the artwork."
    ),
    "DEFAULT_BOOK_MODE": "lift-the-flap",
    "DEFAULT_PAGE_COUNT": "12",
    "BOOKS_OUTPUT_DIR": "./books",
    "LOCAL_SERVER_PORT": "8765",
    "PUBLISH_WEB_ROOT": "",
    "PUBLISH_BASE_URL": "",
}


# ---------------------------------------------------------------------------
# .env Loading & Persistence
# ---------------------------------------------------------------------------

def parse_env_file(path: Path = ENV_FILE) -> Dict[str, str]:
    """Parse a .env file into a key-value dictionary without external dependencies."""
    values: Dict[str, str] = dict(DEFAULT_ENV_VALUES)
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
            val = val[1:-1]
            val = val.replace('\\"', '"').replace("\\n", "\n")
        values[key] = val
    return values


def format_env_value(val: Any) -> str:
    if val is None:
        return '""'
    text = str(val).replace("\r", "").replace("\n", " ").strip()
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_env_file(updates: Dict[str, Any], path: Path = ENV_FILE) -> Dict[str, str]:
    """Update or create the local `.env` file while preserving comments and structure."""
    current = parse_env_file(path)
    for k, v in updates.items():
        if v is not None:
            current[k] = str(v).strip()

    template_source = path if path.exists() else (ENV_EXAMPLE_FILE if ENV_EXAMPLE_FILE.exists() else None)
    written_keys = set()
    output_lines: List[str] = []

    if template_source and template_source.exists():
        for raw_line in template_source.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key, _, _ = stripped.partition("=")
                key = key.strip()
                if key in current:
                    output_lines.append(f"{key}={format_env_value(current[key])}")
                    written_keys.add(key)
                else:
                    output_lines.append(raw_line)
            else:
                output_lines.append(raw_line)

    for key, val in current.items():
        if key not in written_keys:
            output_lines.append(f"{key}={format_env_value(val)}")

    path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    return current


def resolve_repo_path(raw_path: str) -> Path:
    """Resolve a path from `.env` relative to `REPO_ROOT` if not absolute."""
    expanded = os.path.expanduser(raw_path.strip())
    p = Path(expanded)
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    return p


def parse_csv_list(raw: str) -> List[str]:
    if not raw or not raw.strip():
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Onboarding & Studio Profile
# ---------------------------------------------------------------------------

def get_studio_profile() -> Dict[str, Any]:
    """Load the user's studio configuration from `.env`."""
    env = parse_env_file(ENV_FILE)
    photo_paths = [
        str(resolve_repo_path(p))
        for p in parse_csv_list(env.get("MAIN_CHARACTER_PHOTO_PATHS", ""))
    ]
    existing_photos = [p for p in photo_paths if Path(p).exists()]

    has_char_name = bool(env.get("MAIN_CHARACTER_NAME", "").strip())
    has_char_visuals = bool(env.get("MAIN_CHARACTER_DESCRIPTION", "").strip()) or bool(existing_photos)
    is_onboarded = (
        env.get("ONBOARDING_COMPLETE", "").lower() == "true"
        or (has_char_name and has_char_visuals)
    )

    books_dir = resolve_repo_path(env.get("BOOKS_OUTPUT_DIR", "./books") or "./books")
    web_root_raw = env.get("PUBLISH_WEB_ROOT", "").strip()
    web_root = str(resolve_repo_path(web_root_raw)) if web_root_raw else ""

    return {
        "is_onboarded": is_onboarded,
        "env_file": str(ENV_FILE),
        "env_exists": ENV_FILE.exists(),
        "main_character": {
            "name": env.get("MAIN_CHARACTER_NAME", ""),
            "age": env.get("MAIN_CHARACTER_AGE", ""),
            "description": env.get("MAIN_CHARACTER_DESCRIPTION", ""),
            "outfit": env.get("MAIN_CHARACTER_OUTFIT", ""),
            "photo_paths": existing_photos,
        },
        "supporting_characters": env.get("SUPPORTING_CHARACTERS", ""),
        "recurring_props": env.get("RECURRING_PROPS", ""),
        "defaults": {
            "art_style": env.get("DEFAULT_ART_STYLE", DEFAULT_ENV_VALUES["DEFAULT_ART_STYLE"]),
            "book_mode": env.get("DEFAULT_BOOK_MODE", "lift-the-flap"),
            "page_count": int(env.get("DEFAULT_PAGE_COUNT", "12") or 12),
        },
        "paths": {
            "books_output_dir": str(books_dir),
            "local_server_port": int(env.get("LOCAL_SERVER_PORT", "8765") or 8765),
            "publish_web_root": web_root,
            "publish_base_url": env.get("PUBLISH_BASE_URL", "").rstrip("/"),
        },
    }


def get_onboarding_status() -> Dict[str, Any]:
    """Check whether first-time onboarding has been completed and return setup guidance."""
    profile = get_studio_profile()
    missing: List[str] = []
    mc = profile["main_character"]
    if not mc["name"]:
        missing.append("main_character_name")
    if not mc["description"] and not mc["photo_paths"]:
        missing.append("main_character_description_or_photo")

    return {
        "is_onboarded": profile["is_onboarded"],
        "env_exists": profile["env_exists"],
        "env_file": profile["env_file"],
        "missing_recommended_fields": missing,
        "profile": profile,
        "agent_onboarding_instructions": (
            "If `is_onboarded` is false (or the user wants to update their defaults), "
            "walk the user through a quick friendly setup before creating their first book:\n"
            "1. Ask for the main character's name and age.\n"
            "2. Ask for a reference photo path AND/OR a short text description of what they look like "
            "(hair, eyes, skin tone, glasses, etc.) plus their signature outfit.\n"
            "3. Optionally ask about supporting characters (parents, siblings, pets) or favorite toys/props.\n"
            "4. Ask if they prefer 'lift-the-flap' (Reality flap lifts to reveal Imaginary world) or 'standard' pages.\n"
            "5. Call `configure_studio(...)` to save these defaults to the local `.env` file."
        ),
    }


def configure_studio(
    main_character_name: Optional[str] = None,
    main_character_age: Optional[str] = None,
    main_character_description: Optional[str] = None,
    main_character_outfit: Optional[str] = None,
    main_character_photos: Optional[List[str]] = None,
    supporting_characters: Optional[str] = None,
    recurring_props: Optional[str] = None,
    default_art_style: Optional[str] = None,
    default_book_mode: Optional[str] = None,
    default_page_count: Optional[int] = None,
    books_output_dir: Optional[str] = None,
    local_server_port: Optional[int] = None,
    publish_web_root: Optional[str] = None,
    publish_base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Save character details, reference photos, and studio defaults to the local `.env` file."""
    updates: Dict[str, Any] = {"ONBOARDING_COMPLETE": "true"}

    if main_character_name is not None:
        updates["MAIN_CHARACTER_NAME"] = main_character_name
    if main_character_age is not None:
        updates["MAIN_CHARACTER_AGE"] = main_character_age
    if main_character_description is not None:
        updates["MAIN_CHARACTER_DESCRIPTION"] = main_character_description
    if main_character_outfit is not None:
        updates["MAIN_CHARACTER_OUTFIT"] = main_character_outfit
    if supporting_characters is not None:
        updates["SUPPORTING_CHARACTERS"] = supporting_characters
    if recurring_props is not None:
        updates["RECURRING_PROPS"] = recurring_props
    if default_art_style is not None:
        updates["DEFAULT_ART_STYLE"] = default_art_style
    if default_book_mode is not None:
        if default_book_mode not in ("lift-the-flap", "standard"):
            raise ValueError("default_book_mode must be 'lift-the-flap' or 'standard'")
        updates["DEFAULT_BOOK_MODE"] = default_book_mode
    if default_page_count is not None:
        updates["DEFAULT_PAGE_COUNT"] = str(default_page_count)
    if books_output_dir is not None:
        updates["BOOKS_OUTPUT_DIR"] = books_output_dir
    if local_server_port is not None:
        updates["LOCAL_SERVER_PORT"] = str(local_server_port)
    if publish_web_root is not None:
        updates["PUBLISH_WEB_ROOT"] = publish_web_root
    if publish_base_url is not None:
        updates["PUBLISH_BASE_URL"] = publish_base_url.rstrip("/")

    copied_photos: List[str] = []
    if main_character_photos is not None:
        LOCAL_REFS_DIR.mkdir(parents=True, exist_ok=True)
        stored_rel_paths: List[str] = []
        for idx, raw_path in enumerate(main_character_photos, start=1):
            if not raw_path or not raw_path.strip():
                continue
            src = Path(os.path.expanduser(raw_path.strip())).resolve()
            if not src.exists():
                raise FileNotFoundError(f"Reference photo not found: {raw_path}")
            ext = src.suffix.lower() or ".jpg"
            safe_stem = re.sub(r"[^a-z0-9_-]+", "-", src.stem.lower()).strip("-") or f"char-ref-{idx}"
            dest = LOCAL_REFS_DIR / f"{safe_stem}{ext}"
            if src != dest.resolve():
                shutil.copy2(src, dest)
            rel_dest = f"./local_profile/references/{dest.name}"
            stored_rel_paths.append(rel_dest)
            copied_photos.append(str(dest))
        updates["MAIN_CHARACTER_PHOTO_PATHS"] = ",".join(stored_rel_paths)

    write_env_file(updates, ENV_FILE)
    profile = get_studio_profile()
    LOCAL_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    (LOCAL_PROFILE_DIR / "profile.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")

    return {
        "status": "configured",
        "env_file": str(ENV_FILE),
        "copied_reference_photos": copied_photos,
        "profile": profile,
    }


def _prompt_input(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{label}{suffix}: ").strip()
    except EOFError:
        val = ""
    return val if val else default


def run_interactive_onboarding() -> Dict[str, Any]:
    """Interactive CLI onboarding wizard for new users."""
    current = get_studio_profile()
    mc = current["main_character"]
    defaults = current["defaults"]
    paths = current["paths"]

    print("\n============================================================")
    print("  Bedtime Book Studio — First-Time Setup & Onboarding")
    print("============================================================")
    print("All settings and character details are stored locally in `.env`")
    print("(which is gitignored and never committed to git).\n")

    print("--- 1. Main Character Setup (Photo and/or Text) ---")
    name = _prompt_input("Main character's name (e.g. Leo, Maya)", mc["name"])
    age = _prompt_input("Main character's age (e.g. 4)", mc["age"])

    existing_photos_str = ", ".join(mc["photo_paths"])
    raw_photos = _prompt_input(
        "Path(s) to reference photo(s) of main character (comma-separated, or leave blank for text-only)",
        existing_photos_str,
    )
    photo_list = parse_csv_list(raw_photos) if raw_photos else []

    desc = _prompt_input(
        "Physical appearance description (hair, eyes, skin tone — used alongside or instead of photo)",
        mc["description"],
    )
    outfit = _prompt_input(
        "Signature default outfit (e.g. cobalt-blue T-shirt, green shorts, blue sneakers)",
        mc["outfit"],
    )

    print("\n--- 2. Supporting Cast & Favorite Props (Optional) ---")
    supporting = _prompt_input(
        "Supporting characters / family / pets (e.g. Mom with glasses; golden retriever Max)",
        current["supporting_characters"],
    )
    props = _prompt_input(
        "Favorite recurring toys or props (e.g. wooden tricycle, stuffed bunny)",
        current["recurring_props"],
    )

    print("\n--- 3. Book Format & Art Style Defaults ---")
    mode = _prompt_input(
        "Default book mode ('lift-the-flap' or 'standard')",
        defaults["book_mode"] or "lift-the-flap",
    ).lower()
    if mode not in ("lift-the-flap", "standard"):
        mode = "lift-the-flap"

    page_count_str = _prompt_input("Default story page count", str(defaults["page_count"] or 12))
    try:
        page_count = int(page_count_str)
    except ValueError:
        page_count = 12

    art_style = _prompt_input("Default illustration style", defaults["art_style"])

    print("\n--- 4. Local Output & Hosting Defaults ---")
    books_dir = _prompt_input("Directory where generated books are saved", paths["books_output_dir"] or "./books")
    port_str = _prompt_input("Local device web server port", str(paths["local_server_port"] or 8765))
    try:
        local_port = int(port_str)
    except ValueError:
        local_port = 8765

    result = configure_studio(
        main_character_name=name,
        main_character_age=age,
        main_character_description=desc,
        main_character_outfit=outfit,
        main_character_photos=photo_list if raw_photos != existing_photos_str else None,
        supporting_characters=supporting,
        recurring_props=props,
        default_art_style=art_style,
        default_book_mode=mode,
        default_page_count=page_count,
        books_output_dir=books_dir,
        local_server_port=local_port,
    )

    print("\n✅ Onboarding complete! Saved local configuration to:")
    print(f"   {result['env_file']}")
    if result["copied_reference_photos"]:
        print("   Copied reference photos to:")
        for p in result["copied_reference_photos"]:
            print(f"     - {p}")
    print()
    return result


# ---------------------------------------------------------------------------
# Book Project Pipeline (list, init, storyboard, ingest, publish)
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "bedtime-book"


def get_books_dir() -> Path:
    profile = get_studio_profile()
    out = Path(profile["paths"]["books_output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    return out


def list_books() -> List[Dict[str, Any]]:
    books_dir = get_books_dir()
    profile = get_studio_profile()
    local_port = profile["paths"]["local_server_port"]
    web_root = Path(profile["paths"]["publish_web_root"]) if profile["paths"]["publish_web_root"] else None
    base_url = profile["paths"]["publish_base_url"]

    books: List[Dict[str, Any]] = []
    if not books_dir.exists():
        return books

    for child in sorted(books_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        index_html = child / "index.html"
        storyboard_json = child / "storyboard.json"
        if not (index_html.exists() or storyboard_json.exists()):
            continue

        slug = child.name
        standalone_html = child / f"{slug}.html"
        published_dir = (web_root / slug) if web_root else None
        is_published = bool(published_dir and (published_dir / "index.html").exists())
        live_url = f"{base_url}/{slug}" if (is_published and base_url) else None

        books.append({
            "slug": slug,
            "workspace_dir": str(child),
            "single_file_html": str(standalone_html) if standalone_html.exists() else None,
            "has_storyboard": storyboard_json.exists(),
            "has_reader": index_html.exists(),
            "local_url": f"http://localhost:{local_port}/{slug}/" if index_html.exists() else None,
            "custom_live_url": live_url,
        })
    return books


def init_book_project(
    slug: str,
    title: str,
    idea: str,
    mode: Optional[str] = None,
    character_name: Optional[str] = None,
    character_description: Optional[str] = None,
    reference_images: Optional[List[str]] = None,
    page_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Initialize a new book project workspace using `.env` defaults when arguments are omitted."""
    profile = get_studio_profile()
    mc = profile["main_character"]
    defaults = profile["defaults"]

    slug = slugify(slug or title)
    project_dir = get_books_dir() / slug
    assets_dir = project_dir / "assets"
    refs_dir = assets_dir / "references"
    refs_dir.mkdir(parents=True, exist_ok=True)

    resolved_mode = mode or defaults["book_mode"] or "lift-the-flap"
    resolved_pages = int(page_count or defaults["page_count"] or 12)
    resolved_char_name = character_name or mc["name"] or "Our Hero"

    default_desc_parts = []
    if mc["age"]:
        default_desc_parts.append(f"{mc['age']}-year-old")
    if mc["description"]:
        default_desc_parts.append(mc["description"])
    if mc["outfit"]:
        default_desc_parts.append(f"wearing {mc['outfit']}")
    resolved_char_desc = character_description or ", ".join(default_desc_parts) or "Friendly young child"

    all_input_refs: List[str] = list(mc["photo_paths"])
    if reference_images:
        for r in reference_images:
            if r and r not in all_input_refs:
                all_input_refs.append(r)

    copied_refs: List[str] = []
    for idx, ref_path_str in enumerate(all_input_refs, start=1):
        src = Path(os.path.expanduser(ref_path_str)).resolve()
        if src.exists():
            ext = src.suffix.lower() or ".jpg"
            dest = refs_dir / f"ref-{idx:02d}-{src.stem}{ext}"
            shutil.copy2(src, dest)
            copied_refs.append(str(dest))

    meta = {
        "slug": slug,
        "title": title,
        "idea": idea,
        "mode": resolved_mode,
        "character_name": resolved_char_name,
        "character_description": resolved_char_desc,
        "supporting_characters": profile["supporting_characters"],
        "recurring_props": profile["recurring_props"],
        "art_style": defaults["art_style"],
        "page_count": resolved_pages,
        "reference_images": copied_refs,
        "project_dir": str(project_dir),
    }

    (project_dir / "book_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    prompt_guide = f"""# Storyboard Generation Guide for "{title}"

- **Slug**: `{slug}`
- **Book Mode**: `{resolved_mode}` (`lift-the-flap` = Reality flap + Imaginary world underneath; `standard` = single scene per page)
- **Target Pages**: {resolved_pages} story pages + 1 cover
- **Main Character**: {resolved_char_name} ({resolved_char_desc})
- **Supporting Characters**: {profile['supporting_characters'] or 'None specified'}
- **Recurring Props**: {profile['recurring_props'] or 'None specified'}
- **Art Style**: {defaults['art_style']}
- **Story Idea**: {idea}
- **Copied Reference Photos**: {', '.join(copied_refs) if copied_refs else 'None (use text description)'}

## Next Step
Create `{project_dir}/storyboard.json` (or call `save_storyboard`) with:
- `title`, `subtitle`, `kicker`, `mode`
- `character_bible`: visual lock rules for {resolved_char_name}, supporting cast, and key props
- `cover`: `prompt`
- `pages`: array of {resolved_pages} pages, each with:
  - `number` (1..{resolved_pages})
  - `badge` (e.g. `"Page 1"` or `"Step 1"`)
  - `title` (short scene title)
  - `paragraphs` (array of 1–2 short read-aloud strings)
  - `refrain` (optional highlighted sound effect / refrain)
  - `flap_prompt` (short teaser for the flap button in `lift-the-flap` mode)
  - `imagination_label` (caption revealed when the flap is lifted)
  - `reality_prompt` (full 4:3 landscape image generation prompt, no text in image)
  - `imaginary_prompt` (full 4:3 landscape image generation prompt for under the flap, matching the composition of `reality_prompt`)
"""
    (project_dir / "STORYBOARD_PROMPT.md").write_text(prompt_guide, encoding="utf-8")
    return meta


def save_storyboard(slug: str, storyboard: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and save `storyboard.json` and generate `prompts.md`."""
    project_dir = get_books_dir() / slugify(slug)
    project_dir.mkdir(parents=True, exist_ok=True)
    sb_path = project_dir / "storyboard.json"
    sb_path.write_text(json.dumps(storyboard, indent=2, ensure_ascii=False), encoding="utf-8")

    mode = storyboard.get("mode", "lift-the-flap")
    title = storyboard.get("title", slug)
    char_bible = storyboard.get("character_bible", "")
    cover_prompt = (storyboard.get("cover") or {}).get("prompt", "")
    pages = storyboard.get("pages") or []

    md_lines = [
        f"# {title} — Illustration Prompts (`{mode}`)",
        "",
        "## Character & Style Continuity Lock",
        char_bible if isinstance(char_bible, str) else json.dumps(char_bible, indent=2),
        "",
        "## Cover (`assets/cover.png`)",
        f"- **Prompt**: {cover_prompt}",
        "",
        "## Story Pages",
        "",
    ]

    required_images: List[Dict[str, str]] = [
        {"key": "cover", "target": str(project_dir / "assets" / "cover.png"), "prompt": cover_prompt}
    ]

    for p in pages:
        num = int(p.get("number", 0))
        p_title = p.get("title", f"Page {num}")
        r_prompt = p.get("reality_prompt") or p.get("prompt") or ""
        i_prompt = p.get("imaginary_prompt") or ""

        md_lines.append(f"### Page {num:02d} — {p_title}")
        if mode == "lift-the-flap":
            md_lines.append(f"- **Reality (`assets/page-{num:02d}-reality.png`)**: {r_prompt}")
            md_lines.append(f"- **Imaginary (`assets/page-{num:02d}-imaginary.png`)**: {i_prompt}")
            required_images.append({
                "key": f"page-{num:02d}-reality",
                "target": str(project_dir / "assets" / f"page-{num:02d}-reality.png"),
                "prompt": r_prompt,
            })
            required_images.append({
                "key": f"page-{num:02d}-imaginary",
                "target": str(project_dir / "assets" / f"page-{num:02d}-imaginary.png"),
                "prompt": i_prompt,
            })
        else:
            md_lines.append(f"- **Scene (`assets/page-{num:02d}-reality.png`)**: {r_prompt}")
            required_images.append({
                "key": f"page-{num:02d}-reality",
                "target": str(project_dir / "assets" / f"page-{num:02d}-reality.png"),
                "prompt": r_prompt,
            })
        md_lines.append("")

    prompts_md_path = project_dir / "prompts.md"
    prompts_md_path.write_text("\n".join(md_lines), encoding="utf-8")

    return {
        "slug": slugify(slug),
        "storyboard_path": str(sb_path),
        "prompts_markdown_path": str(prompts_md_path),
        "total_images_needed": len(required_images),
        "required_images": required_images,
    }


def ingest_book_images(
    slug: str,
    image_map: Dict[str, str],
    width: int = 1280,
    height: int = 960,
) -> Dict[str, Any]:
    """Crop/resize generated images to 4:3 landscape and save both `.png` and `.webp` in `assets/`."""
    project_dir = get_books_dir() / slugify(slug)
    assets_dir = project_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    processed: List[Dict[str, str]] = []
    for key, src_path_str in sorted(image_map.items()):
        src = Path(os.path.expanduser(src_path_str)).resolve()
        if not src.exists():
            raise FileNotFoundError(f"Missing source image for '{key}': {src}")

        stem = key[:-4] if key.endswith(".png") else key
        png_path = assets_dir / f"{stem}.png"
        webp_path = assets_dir / f"{stem}.webp"

        with Image.open(src) as im:
            im = im.convert("RGB")
            fitted = ImageOps.fit(im, (width, height), method=Image.Resampling.LANCZOS)
            fitted.save(png_path, format="PNG", optimize=True)
            fitted.save(webp_path, format="WEBP", quality=84, method=6)

        processed.append({"key": stem, "png": str(png_path), "webp": str(webp_path)})

    return {
        "slug": slugify(slug),
        "assets_dir": str(assets_dir),
        "processed_count": len(processed),
        "processed": processed,
    }


def _encode_asset_as_data_uri(project_dir: Path, rel_asset_path: str) -> str:
    """Convert an asset path (preferring .webp for compact single-file HTML) to a base64 data URI."""
    candidate = project_dir / rel_asset_path
    webp_candidate = candidate.with_suffix(".webp")
    if webp_candidate.exists():
        raw = webp_candidate.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:image/webp;base64,{b64}"
    if candidate.exists():
        mime = "image/png" if candidate.suffix.lower() == ".png" else "image/jpeg"
        raw = candidate.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{b64}"
    return rel_asset_path


def _resolve_asset_ref(project_dir: Path, stem: str, inline_data_uris: bool) -> str:
    webp_rel = f"assets/{stem}.webp"
    png_rel = f"assets/{stem}.png"
    chosen_rel = webp_rel if (project_dir / webp_rel).exists() else png_rel
    if inline_data_uris:
        return _encode_asset_as_data_uri(project_dir, chosen_rel)
    return chosen_rel


def _build_reader_pages_js(
    storyboard: Dict[str, Any],
    project_dir: Path,
    inline_data_uris: bool = False,
) -> List[Dict[str, Any]]:
    mode = storyboard.get("mode", "lift-the-flap")
    title = storyboard.get("title", "Bedtime Story")
    subtitle = storyboard.get("subtitle", "A Bedtime Picture Book")

    pages_js: List[Dict[str, Any]] = [
        {
            "label": "Cover",
            "title": title,
            "subtitle": subtitle,
            "coverImage": _resolve_asset_ref(project_dir, "cover", inline_data_uris),
            "hasFlap": False,
            "text": [subtitle],
        }
    ]

    for p in storyboard.get("pages") or []:
        num = int(p.get("number", 1))
        has_flap = mode == "lift-the-flap" and bool(
            p.get("imaginary_prompt") or p.get("imaginaryImg") or p.get("imaginaryImage")
        )
        real_src = _resolve_asset_ref(project_dir, f"page-{num:02d}-reality", inline_data_uris)
        imag_src = (
            _resolve_asset_ref(project_dir, f"page-{num:02d}-imaginary", inline_data_uris)
            if has_flap
            else real_src
        )
        paragraphs = p.get("paragraphs") or p.get("text") or []
        if isinstance(paragraphs, str):
            paragraphs = [paragraphs]

        pages_js.append({
            "label": p.get("badge") or p.get("label") or f"Page {num}",
            "title": p.get("title") or f"Page {num}",
            "realImage": real_src,
            "imaginaryImage": imag_src,
            "imaginaryCaption": (
                p.get("imagination_label")
                or p.get("imaginaryCaption")
                or ("✨ Imaginary World" if has_flap else "")
            ),
            "flapHint": (
                p.get("flap_prompt")
                or p.get("flapHint")
                or ("Lift the flap to see the imaginary world!" if has_flap else "")
            ),
            "hasFlap": has_flap,
            "refrain": p.get("refrain") or "",
            "text": paragraphs,
        })

    end_info = storyboard.get("end") or {}
    pages_js.append({
        "kind": "the-end",
        "label": "Finish",
        "kicker": end_info.get("kicker") or "HOORAY!",
        "title": end_info.get("title") or "The End",
        "hasFlap": False,
        "text": [
            end_info.get("subtitle")
            or f"Great reading! Ready to read {title} again?"
        ],
    })
    return pages_js


def _get_lan_ip() -> str:
    """Detect the device's local LAN IP address so phones/tablets on Wi-Fi can open the book."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def ensure_local_server(books_dir: Path, port: int = 8765) -> Dict[str, Any]:
    """Ensure a background HTTP server is serving `books_dir` on `0.0.0.0:<port>`."""
    books_dir.mkdir(parents=True, exist_ok=True)
    already_running = _is_port_open(port)
    if not already_running:
        subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port), "--bind", "0.0.0.0", "--directory", str(books_dir)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(10):
            if _is_port_open(port):
                break
            time.sleep(0.1)

    lan_ip = _get_lan_ip()
    return {
        "running": _is_port_open(port),
        "port": port,
        "books_dir": str(books_dir),
        "localhost_base": f"http://localhost:{port}",
        "lan_base": f"http://{lan_ip}:{port}",
    }


def publish_book(
    slug: str,
    serve_local: bool = True,
    deploy_static: bool = True,
    port: Optional[int] = None,
    web_root_override: Optional[str] = None,
    base_url_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build:
      1. A self-contained single-file HTML book (`<slug>.html`) with all CSS, JS, and images inlined.
      2. A standard multi-file web reader (`index.html`, `styles.css`, `script.js`, `assets/`).
      3. By default, host locally on the user's device (`http://localhost:<port>/<slug>/` and LAN URL).
      4. Optionally copy to `PUBLISH_WEB_ROOT` if configured in `.env`.
    """
    slug = slugify(slug)
    books_dir = get_books_dir()
    project_dir = books_dir / slug
    sb_path = project_dir / "storyboard.json"
    if not sb_path.exists():
        raise FileNotFoundError(f"Missing storyboard.json in {project_dir}")

    storyboard = json.loads(sb_path.read_text(encoding="utf-8"))
    title = storyboard.get("title", slug)
    subtitle = storyboard.get("subtitle", "An Interactive Landscape Picture Book")
    kicker = storyboard.get("kicker", "Interactive Bedtime Book")
    story_pages = storyboard.get("pages") or []

    index_tpl = (TEMPLATES_READER_DIR / "index.html").read_text(encoding="utf-8")
    styles_css = (TEMPLATES_READER_DIR / "styles.css").read_text(encoding="utf-8")
    script_tpl = (TEMPLATES_READER_DIR / "script.js").read_text(encoding="utf-8")

    base_html = (
        index_tpl.replace("__BOOK_TITLE__", html.escape(title))
        .replace("__BOOK_SUBTITLE__", html.escape(subtitle))
        .replace("__BOOK_KICKER__", html.escape(kicker))
    )

    # 1. Build standard multi-file reader in <project_dir>/
    pages_external = _build_reader_pages_js(storyboard, project_dir, inline_data_uris=False)
    rendered_script_external = re.sub(
        r"/\*\s*__TOTAL_STORY_PAGES__\s*\*/\s*\d+",
        str(len(story_pages)),
        script_tpl,
    ).replace(
        "/* __BOOK_PAGES_JSON__ */ []",
        json.dumps(pages_external, indent=2, ensure_ascii=False),
    )

    (project_dir / "index.html").write_text(base_html, encoding="utf-8")
    (project_dir / "styles.css").write_text(styles_css, encoding="utf-8")
    (project_dir / "script.js").write_text(rendered_script_external, encoding="utf-8")

    # 2. Build self-contained SINGLE-FILE HTML book (<slug>.html) with inlined CSS, JS, and base64 WebP art
    pages_inlined = _build_reader_pages_js(storyboard, project_dir, inline_data_uris=True)
    rendered_script_inlined = re.sub(
        r"/\*\s*__TOTAL_STORY_PAGES__\s*\*/\s*\d+",
        str(len(story_pages)),
        script_tpl,
    ).replace(
        "/* __BOOK_PAGES_JSON__ */ []",
        json.dumps(pages_inlined, ensure_ascii=False),
    )

    single_file_html_content = (
        base_html.replace(
            '<link rel="stylesheet" href="styles.css" />',
            f"<style>\n{styles_css}\n</style>",
        ).replace(
            '<script src="script.js"></script>',
            f"<script>\n{rendered_script_inlined}\n</script>",
        )
    )

    standalone_file_in_project = project_dir / f"{slug}.html"
    standalone_file_in_root = books_dir / f"{slug}.html"
    standalone_file_in_project.write_text(single_file_html_content, encoding="utf-8")
    shutil.copy2(standalone_file_in_project, standalone_file_in_root)

    profile = get_studio_profile()
    paths_cfg = profile["paths"]
    chosen_port = int(port or paths_cfg["local_server_port"] or 8765)

    result: Dict[str, Any] = {
        "slug": slug,
        "workspace_dir": str(project_dir),
        "single_file_html": str(standalone_file_in_project),
        "single_file_html_copy": str(standalone_file_in_root),
        "file_url": f"file://{standalone_file_in_project}",
        "local_url": None,
        "local_single_file_url": None,
        "lan_url": None,
        "lan_single_file_url": None,
        "custom_static_site_dir": None,
        "custom_live_url": None,
    }

    # 3. Default Local Device Hosting
    if serve_local:
        srv = ensure_local_server(books_dir, chosen_port)
        result["local_url"] = f"{srv['localhost_base']}/{slug}/"
        result["local_single_file_url"] = f"{srv['localhost_base']}/{slug}.html"
        result["lan_url"] = f"{srv['lan_base']}/{slug}/"
        result["lan_single_file_url"] = f"{srv['lan_base']}/{slug}.html"

    # 4. Optional Custom Static Web Root Copy (for users who self-host a web root)
    web_root_str = web_root_override if web_root_override is not None else paths_cfg["publish_web_root"]
    base_url_str = (
        base_url_override.rstrip("/")
        if base_url_override is not None
        else paths_cfg["publish_base_url"]
    )
    if deploy_static and web_root_str:
        target_dir = Path(os.path.expanduser(web_root_str)).resolve() / slug
        target_assets = target_dir / "assets"
        target_assets.mkdir(parents=True, exist_ok=True)
        for fname in ("index.html", "styles.css", "script.js", f"{slug}.html"):
            src_f = project_dir / fname
            if src_f.exists():
                shutil.copy2(src_f, target_dir / fname)
        src_assets = project_dir / "assets"
        if src_assets.exists():
            for asset_file in src_assets.iterdir():
                if asset_file.is_file() and asset_file.suffix.lower() in (".png", ".webp", ".jpg", ".jpeg"):
                    shutil.copy2(asset_file, target_assets / asset_file.name)
        result["custom_static_site_dir"] = str(target_dir)
        if base_url_str:
            result["custom_live_url"] = f"{base_url_str}/{slug}"

    return result


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bedtime Book Studio — Onboarding & Children's Picture Book Builder"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("onboard", help="Run the interactive terminal onboarding wizard")
    sub.add_parser("status", help="Show onboarding status and current .env profile as JSON")
    sub.add_parser("profile", help="Print the active studio profile from .env")
    sub.add_parser("list", help="List all books in BOOKS_OUTPUT_DIR")

    p_srv = sub.add_parser("serve", help="Start or check the local device web server for all books")
    p_srv.add_argument("--port", type=int, default=None, help="Override LOCAL_SERVER_PORT")

    p_cfg = sub.add_parser("configure", help="Non-interactively save character & studio defaults to .env")
    p_cfg.add_argument("--name", help="Main character name")
    p_cfg.add_argument("--age", help="Main character age")
    p_cfg.add_argument("--description", help="Main character physical description")
    p_cfg.add_argument("--outfit", help="Main character signature outfit")
    p_cfg.add_argument("--photos", nargs="*", help="Paths to main character reference photos")
    p_cfg.add_argument("--supporting", help="Supporting characters description")
    p_cfg.add_argument("--props", help="Recurring toys/props description")
    p_cfg.add_argument("--style", help="Default art style prompt")
    p_cfg.add_argument("--mode", choices=["lift-the-flap", "standard"], help="Default book mode")
    p_cfg.add_argument("--pages", type=int, help="Default story page count")
    p_cfg.add_argument("--books-dir", help="Output directory for generated books")
    p_cfg.add_argument("--port", type=int, help="Local device web server port")
    p_cfg.add_argument("--web-root", help="Optional static site web root directory for self-hosting")
    p_cfg.add_argument("--base-url", help="Optional public base URL matching --web-root")

    p_init = sub.add_parser("init", help="Initialize a new book workspace")
    p_init.add_argument("--slug", required=True)
    p_init.add_argument("--title", required=True)
    p_init.add_argument("--idea", required=True)
    p_init.add_argument("--mode", choices=["lift-the-flap", "standard"], default=None)
    p_init.add_argument("--character-name", default=None)
    p_init.add_argument("--character-description", default=None)
    p_init.add_argument("--refs", nargs="*", default=None)
    p_init.add_argument("--pages", type=int, default=None)

    p_sb = sub.add_parser("storyboard", help="Validate storyboard.json and generate prompts.md")
    p_sb.add_argument("--slug", required=True)
    p_sb.add_argument("--file", required=True, help="Path to storyboard JSON file")

    p_ing = sub.add_parser("ingest", help="Normalize and convert generated images into assets/")
    p_ing.add_argument("--slug", required=True)
    p_ing.add_argument("--map-json", required=True, help="JSON string or path to JSON file mapping key->path")

    p_pub = sub.add_parser(
        "publish",
        help="Build single-file HTML book (<slug>.html) + standard reader and host locally on this device",
    )
    p_pub.add_argument("--slug", required=True)
    p_pub.add_argument("--no-local-server", action="store_true", help="Do not auto-start the local device HTTP server")
    p_pub.add_argument("--no-static", action="store_true", help="Skip copying to PUBLISH_WEB_ROOT even if set")
    p_pub.add_argument("--port", type=int, default=None, help="Override local HTTP server port")
    p_pub.add_argument("--web-root", default=None)
    p_pub.add_argument("--base-url", default=None)

    args = parser.parse_args()

    if args.cmd == "onboard":
        run_interactive_onboarding()
    elif args.cmd == "status":
        print(json.dumps(get_onboarding_status(), indent=2))
    elif args.cmd == "profile":
        print(json.dumps(get_studio_profile(), indent=2))
    elif args.cmd == "list":
        print(json.dumps(list_books(), indent=2))
    elif args.cmd == "serve":
        profile = get_studio_profile()
        port = int(args.port or profile["paths"]["local_server_port"] or 8765)
        res = ensure_local_server(get_books_dir(), port)
        print(json.dumps(res, indent=2))
    elif args.cmd == "configure":
        res = configure_studio(
            main_character_name=args.name,
            main_character_age=args.age,
            main_character_description=args.description,
            main_character_outfit=args.outfit,
            main_character_photos=args.photos,
            supporting_characters=args.supporting,
            recurring_props=args.props,
            default_art_style=args.style,
            default_book_mode=args.mode,
            default_page_count=args.pages,
            books_output_dir=args.books_dir,
            local_server_port=args.port,
            publish_web_root=args.web_root,
            publish_base_url=args.base_url,
        )
        print(json.dumps(res, indent=2))
    elif args.cmd == "init":
        res = init_book_project(
            slug=args.slug,
            title=args.title,
            idea=args.idea,
            mode=args.mode,
            character_name=args.character_name,
            character_description=args.character_description,
            reference_images=args.refs,
            page_count=args.pages,
        )
        print(json.dumps(res, indent=2))
    elif args.cmd == "storyboard":
        sb_data = json.loads(Path(args.file).read_text(encoding="utf-8"))
        res = save_storyboard(args.slug, sb_data)
        print(json.dumps(res, indent=2))
    elif args.cmd == "ingest":
        raw_map = args.map_json
        if Path(raw_map).exists():
            image_map = json.loads(Path(raw_map).read_text(encoding="utf-8"))
        else:
            image_map = json.loads(raw_map)
        res = ingest_book_images(args.slug, image_map)
        print(json.dumps(res, indent=2))
    elif args.cmd == "publish":
        res = publish_book(
            slug=args.slug,
            serve_local=not args.no_local_server,
            deploy_static=not args.no_static,
            port=args.port,
            web_root_override=args.web_root,
            base_url_override=args.base_url,
        )
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
