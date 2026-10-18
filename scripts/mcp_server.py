#!/usr/bin/env python3
"""
Bedtime Book Studio — MCP Server (stdio)

Exposes onboarding, persistent character/pet/prop identity tools, storyboard
transformation/preview tools, targeted single-page revision/rollback tools, and
the local/single-file HTML publishing pipeline to any MCP-compatible AI agent.
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
    Checks whether the user has completed first-time onboarding in `.env` and `local_profile/identities.json`.
    If `is_onboarded` is false, follow `agent_onboarding_instructions` to ask the user for their
    main character details and call `configure_studio` (and `upsert_identity` for siblings/pets/props).
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
    default_bedtime_mode: Optional[bool] = None,
    default_page_count: Optional[int] = None,
    books_output_dir: Optional[str] = None,
    local_server_port: Optional[int] = None,
    publish_web_root: Optional[str] = None,
    publish_base_url: Optional[str] = None,
) -> str:
    """
    Save or update user onboarding settings in the local gitignored `.env` file and sync
    with `local_profile/identities.json`.
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
        default_bedtime_mode=default_bedtime_mode,
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
    Return the active studio profile from `.env` and `local_profile/identities.json`,
    including persistent character/pet/prop identities, default art style, book mode,
    bedtime mode preference, and local hosting paths.
    """
    return json.dumps(book_studio.get_studio_profile(), indent=2)


@mcp.tool()
def list_identities(kind: Optional[str] = None) -> str:
    """
    List persistent identities (`main_character`, `supporting_character`, `pet`, `prop`)
    with their stable IDs, labeled reference photos, reality descriptions, and imaginary
    transformations from `local_profile/identities.json`.
    """
    return json.dumps(book_studio.list_identities(kind=kind), indent=2)


@mcp.tool()
def upsert_identity(
    name: str,
    kind: str = "supporting_character",
    entity_id: Optional[str] = None,
    age_or_size: Optional[str] = None,
    appearance: Optional[str] = None,
    signature_outfit: Optional[str] = None,
    reality_description: Optional[str] = None,
    imaginary_transformation: Optional[str] = None,
    reference_photos: Optional[List[str]] = None,
    reference_labels: Optional[List[str]] = None,
    approved_sheet_path: Optional[str] = None,
) -> str:
    """
    Create or update a persistent character, sibling, pet, or recurring prop identity
    with a stable ID (`char-...`, `pet-...`, `prop-...`).
    Distinguishes real-world appearance (`reality_description`) from imaginary-world flap
    transformations (`imaginary_transformation`). Reports any existing books/pages affected
    without silently overwriting their approved illustrations.
    """
    res = book_studio.upsert_identity(
        entity_id=entity_id,
        name=name,
        kind=kind,
        age_or_size=age_or_size,
        appearance=appearance,
        signature_outfit=signature_outfit,
        reality_description=reality_description,
        imaginary_transformation=imaginary_transformation,
        reference_photos=reference_photos,
        reference_labels=reference_labels,
        approved_sheet_path=approved_sheet_path,
    )
    return json.dumps(res, indent=2)


@mcp.tool()
def manage_identity_reference(
    entity_id: str,
    action: str,
    ref_id: Optional[str] = None,
    photo_path: Optional[str] = None,
    label: Optional[str] = None,
    active: Optional[bool] = None,
    is_character_sheet: Optional[bool] = None,
) -> str:
    """
    Add (`action='add'`), update/toggle (`action='update'`, e.g. `active=False` to exclude),
    or remove (`action='remove'`) an individual reference photo on `entity_id` without
    modifying unrelated profiles.
    """
    res = book_studio.manage_identity_reference(
        entity_id=entity_id,
        action=action,
        ref_id=ref_id,
        photo_path=photo_path,
        label=label,
        active=active,
        is_character_sheet=is_character_sheet,
    )
    return json.dumps(res, indent=2)


@mcp.tool()
def list_existing_books() -> str:
    """List all bedtime picture-book projects in `BOOKS_OUTPUT_DIR`, their single-file HTML path, preview path, and local URLs."""
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
    cast_ids: Optional[List[str]] = None,
    entity_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    bedtime_mode: Optional[bool] = None,
) -> str:
    """
    Step 1: Initialize a new bedtime picture-book project workspace.
    Supports selecting persistent `cast_ids` (characters, pets, props) and passing per-book
    `entity_overrides` (e.g., special pajamas or costume for this book) without changing
    the global profile.
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
        cast_ids=cast_ids,
        entity_overrides=entity_overrides,
        bedtime_mode=bedtime_mode,
    )
    return json.dumps(res, indent=2)


@mcp.tool()
def save_book_storyboard(
    slug: str,
    storyboard: Dict[str, Any],
    supports_reference_images: bool = True,
) -> str:
    """
    Step 2: Save `storyboard.json` and assemble `prompts.md` + the two-stage generation plan.
    Automatically binds entity IDs to their labeled references, injects `shared_composition`
    and `transformation_mappings`, and chains `page-XX-reality.png` as the primary composition
    reference for `page-XX-imaginary.png` (or reports a `capability_warning` if `supports_reference_images=False`).
    """
    res = book_studio.save_storyboard(
        slug=slug,
        storyboard=storyboard,
        supports_reference_images=supports_reference_images,
    )
    return json.dumps(res, indent=2)


@mcp.tool()
def validate_book_storyboard(slug: str, require_assets: bool = False) -> str:
    """
    Validate a book's `storyboard.json` against the canonical schema (and optionally check
    that all required PNG/WebP assets exist on disk when `require_assets=True`).
    Returns structured `valid`, `errors`, `warnings`, and `page_count`.
    """
    res = book_studio.validate_book_storyboard(slug=slug, require_assets=require_assets)
    return json.dumps(res, indent=2)


@mcp.tool()
def generate_book_preview(slug: str) -> str:
    """
    Step 2b / Review: Generate `<project_dir>/preview.html`, an interactive HTML contact sheet
    that works text-first (0 images) or with draft/final thumbnails, including side-by-side
    Reality vs. Imaginary cards, an interactive Overlay Alignment Inspector, and a Local Wi-Fi QR code.
    """
    res = book_studio.generate_book_preview(slug=slug)
    return json.dumps(res, indent=2)


@mcp.tool()
def ingest_generated_images(
    slug: str,
    image_map: Dict[str, str],
    is_draft: bool = False,
    note: str = "",
) -> str:
    """
    Step 3: Normalize, center-crop to 1280x960 (4:3 landscape), and save `.png` + `.webp`
    for the provided `image_map` keys (`cover`, `page-01-reality`, `page-01-imaginary`, ...).
    Automatically archives any prior version in `assets/history/<key>/v<NNN>.png` for rollback.
    """
    res = book_studio.ingest_book_images(
        slug=slug,
        image_map=image_map,
        is_draft=is_draft,
        note=note,
    )
    return json.dumps(res, indent=2)


@mcp.tool()
def revise_book_page(
    slug: str,
    page_number: int,
    scope: str,
    title: Optional[str] = None,
    paragraphs: Optional[List[str]] = None,
    refrain: Optional[str] = None,
    flap_prompt: Optional[str] = None,
    imagination_label: Optional[str] = None,
    reality_prompt: Optional[str] = None,
    imaginary_prompt: Optional[str] = None,
    shared_composition: Optional[Dict[str, Any]] = None,
    transformation_mappings: Optional[List[Dict[str, Any]]] = None,
    entity_ids: Optional[List[str]] = None,
    revision_note: str = "",
) -> str:
    """
    Targeted single-page revision (`scope` in `'text-only'`, `'reality-only'`, `'imaginary-only'`, `'paired-scene'`).
    Preserves all unrelated pages and approved illustrations. `text-only` edits immediately
    rebuild the reader without triggering image generation.
    """
    res = book_studio.revise_book_page(
        slug=slug,
        page_number=page_number,
        scope=scope,
        title=title,
        paragraphs=paragraphs,
        refrain=refrain,
        flap_prompt=flap_prompt,
        imagination_label=imagination_label,
        reality_prompt=reality_prompt,
        imaginary_prompt=imaginary_prompt,
        shared_composition=shared_composition,
        transformation_mappings=transformation_mappings,
        entity_ids=entity_ids,
        revision_note=revision_note,
    )
    return json.dumps(res, indent=2)


@mcp.tool()
def approve_book_assets(
    slug: str,
    asset_keys: Optional[List[str]] = None,
    approve_storyboard: Optional[bool] = None,
    note: str = "",
) -> str:
    """Mark the storyboard and/or specific illustration asset keys as approved in `revision_state.json`."""
    res = book_studio.approve_book_assets(
        slug=slug,
        asset_keys=asset_keys,
        approve_storyboard=approve_storyboard,
        note=note,
    )
    return json.dumps(res, indent=2)


@mcp.tool()
def rollback_book_asset(
    slug: str,
    asset_key: str,
    version: Optional[int] = None,
) -> str:
    """Restore a previous archived version of `asset_key` from `assets/history/` and atomically rebuild the reader."""
    res = book_studio.rollback_book_asset(
        slug=slug,
        asset_key=asset_key,
        version=version,
    )
    return json.dumps(res, indent=2)


@mcp.tool()
def get_revision_status(slug: str) -> str:
    """Return the current approval state, version history, and revision log (`revision_state.json`) for a book."""
    return json.dumps(book_studio.get_revision_status(slug=slug), indent=2)


@mcp.tool()
def build_and_publish_book(
    slug: str,
    serve_local: bool = True,
    deploy_static: bool = True,
    port: Optional[int] = None,
    bedtime_mode: Optional[bool] = None,
) -> str:
    """
    Step 4: Atomically compile the book into:
      1. A self-contained single-file HTML book (`<slug>.html` with all CSS, JS, and images embedded).
      2. A multi-file web reader (`index.html`, `styles.css`, `script.js`, `assets/`).
      3. By default (`serve_local=True`), hosts the book immediately on the local device.
    """
    res = book_studio.publish_book(
        slug=slug,
        serve_local=serve_local,
        deploy_static=deploy_static,
        port=port,
        bedtime_mode=bedtime_mode,
    )
    return json.dumps(res, indent=2)


if __name__ == "__main__":
    mcp.run()
