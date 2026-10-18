#!/usr/bin/env python3
"""
Bedtime Book Studio — MCP Server (stdio)

Exposes onboarding tools (`get_onboarding_status`, `configure_studio`) and the
complete bedtime picture-book creation & publishing pipeline to any MCP-compatible
AI agent (Claude Code, Antigravity, Cursor, OpenClaw, Windsurf, etc.).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP

import book_studio

mcp = FastMCP("bedtime-book-studio")


@mcp.tool()
def get_onboarding_status() -> str:
    """
    Call this FIRST when starting a session.
    Checks whether the user has completed first-time onboarding in `.env` (main character
    name, reference photo(s) and/or text appearance description, outfit, art style, and
    default book mode). If `is_onboarded` is false, follow `agent_onboarding_instructions`
    to ask the user for their main character details and call `configure_studio`.
    """
    return json.dumps(book_studio.get_onboarding_status(), indent=2)


@mcp.tool()
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
) -> str:
    """
    Save or update user onboarding settings in the local gitignored `.env` file.
    Copies any `main_character_photos` into `local_profile/references/` so every future
    book automatically has access to the main character's reference photo(s) and/or
    text description.
    """
    res = book_studio.configure_studio(
        main_character_name=main_character_name,
        main_character_age=main_character_age,
        main_character_description=main_character_description,
        main_character_outfit=main_character_outfit,
        main_character_photos=main_character_photos,
        supporting_characters=supporting_characters,
        recurring_props=recurring_props,
        default_art_style=default_art_style,
        default_book_mode=default_book_mode,
        default_page_count=default_page_count,
        books_output_dir=books_output_dir,
        local_server_port=local_server_port,
        publish_web_root=publish_web_root,
        publish_base_url=publish_base_url,
    )
    return json.dumps(res, indent=2)


@mcp.tool()
def get_studio_profile() -> str:
    """
    Return the active studio profile from `.env`, including main character details
    (name, age, text description, outfit, reference photo paths), supporting cast,
    default art style, default book mode, and local hosting paths.
    """
    return json.dumps(book_studio.get_studio_profile(), indent=2)


@mcp.tool()
def list_existing_books() -> str:
    """List all bedtime picture-book projects in `BOOKS_OUTPUT_DIR`, their single-file HTML path, and local URLs."""
    return json.dumps(book_studio.list_books(), indent=2)


@mcp.tool()
def create_book_project(
    slug: str,
    title: str,
    idea: str,
    mode: Optional[str] = None,
    character_name: Optional[str] = None,
    character_description: Optional[str] = None,
    reference_images: Optional[List[str]] = None,
    page_count: Optional[int] = None,
) -> str:
    """
    Step 1: Initialize a new bedtime picture-book project workspace.
    Any omitted fields (`mode`, `character_name`, `character_description`, `page_count`)
    automatically inherit the user's defaults from `.env`, and default character reference
    photos are automatically copied alongside any book-specific `reference_images`.
    """
    res = book_studio.init_book_project(
        slug=slug,
        title=title,
        idea=idea,
        mode=mode,
        character_name=character_name,
        character_description=character_description,
        reference_images=reference_images,
        page_count=page_count,
    )
    return json.dumps(res, indent=2)


@mcp.tool()
def save_book_storyboard(slug: str, storyboard: Dict[str, Any]) -> str:
    """
    Step 2: Save the complete `storyboard.json` for a book and generate `prompts.md`
    plus the exact list of required image keys (`cover`, `page-01-reality`, `page-01-imaginary`, ...).
    """
    res = book_studio.save_storyboard(slug, storyboard)
    return json.dumps(res, indent=2)


@mcp.tool()
def ingest_generated_images(slug: str, image_map: Dict[str, str]) -> str:
    """
    Step 3: After generating illustrations (via subagents or image tools), pass a dictionary
    mapping asset keys (e.g. `{"cover": "/path/to/img.jpg", "page-01-reality": "..."}`)
    to normalize, center-crop to 1280x960 (4:3 landscape), and save both `.png` and `.webp`.
    """
    res = book_studio.ingest_book_images(slug, image_map)
    return json.dumps(res, indent=2)


@mcp.tool()
def build_and_publish_book(
    slug: str,
    serve_local: bool = True,
    deploy_static: bool = True,
    port: Optional[int] = None,
) -> str:
    """
    Step 4: Compile the book into:
      1. A self-contained single-file HTML book (`<slug>.html` with all CSS, JS, and images embedded)
         that can be opened directly in any browser or AirDropped/shared to a phone or tablet.
      2. A multi-file web reader (`index.html`, `styles.css`, `script.js`, `assets/`).
      3. By default (`serve_local=True`), hosts the book immediately on the local device at
         `http://localhost:<port>/<slug>/` and `http://<lan-ip>:<port>/<slug>/` for phones on Wi-Fi.
      4. Optionally copies to `PUBLISH_WEB_ROOT` if the user configured custom self-hosting in `.env`.
    """
    res = book_studio.publish_book(
        slug=slug,
        serve_local=serve_local,
        deploy_static=deploy_static,
        port=port,
    )
    return json.dumps(res, indent=2)


if __name__ == "__main__":
    mcp.run()
