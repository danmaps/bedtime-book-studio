#!/usr/bin/env python3
"""
Bedtime Book Studio — Core Engine, Identity Registry, Storyboard Preview & Revision CLI

Capabilities:
  0. onboard / configure — Interactive or agent-driven setup stored in local `.env`
  1. identities          — Persistent character, sibling, pet, and prop profiles with
                           stable IDs, labeled references, and reality-vs-imaginary rules
  2. init                — Scaffold a new book workspace with selected cast & overrides
  3. storyboard          — Save `storyboard.json` with shared composition & transformation
                           mappings, and assemble reference-chained `prompts.md`
  4. preview             — Generate `<project_dir>/preview.html` contact sheet & alignment
                           inspector (works text-first or with draft/final illustrations)
  5. ingest              — Normalize, crop (4:3), convert to `.png` + `.webp`, and archive
                           prior versions in `assets/history/`
  6. revise / rollback   — Revise a single page (`text-only`, `reality-only`, `imaginary-only`,
                           or `paired-scene`), approve assets, or roll back to a prior version
  7. publish             — Atomically build self-contained single-file `<slug>.html` + standard
                           reader (with Bedtime Mode support) and host locally on the device
"""

from __future__ import annotations

import argparse
import base64
import datetime
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

try:
    from scripts.qr_code import render_qr_ascii, render_qr_svg
except ImportError:
    from qr_code import render_qr_ascii, render_qr_svg

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ENV_FILE = REPO_ROOT / ".env"
ENV_EXAMPLE_FILE = REPO_ROOT / ".env.example"
LOCAL_PROFILE_DIR = REPO_ROOT / "local_profile"
LOCAL_REFS_DIR = LOCAL_PROFILE_DIR / "references"
IDENTITIES_FILE = LOCAL_PROFILE_DIR / "identities.json"
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
    "DEFAULT_BEDTIME_MODE": "false",
    "DEFAULT_PAGE_COUNT": "12",
    "BOOKS_OUTPUT_DIR": "./books",
    "LOCAL_SERVER_PORT": "8765",
    "PUBLISH_WEB_ROOT": "",
    "PUBLISH_BASE_URL": "",
}

VALID_ENTITY_KINDS = ("main_character", "supporting_character", "pet", "prop")
VALID_REVISION_SCOPES = ("text-only", "reality-only", "imaginary-only", "paired-scene")


class StoryboardValidationError(ValueError):
    """Raised when a storyboard fails schema validation or is missing required image assets."""

    def __init__(self, errors: List[str], warnings: Optional[List[str]] = None) -> None:
        self.errors = errors
        self.warnings = warnings or []
        msg = "Storyboard validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        if self.warnings:
            msg += "\nWarnings:\n" + "\n".join(f"  - {w}" for w in self.warnings)
        super().__init__(msg)


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _atomic_write_text(target: Path, content: str, encoding: str = "utf-8") -> None:
    """Write text to a temporary file and atomically replace target so interrupted writes never corrupt files."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f".{target.name}.tmp.{os.getpid()}")
    tmp_path.write_text(content, encoding=encoding)
    os.replace(tmp_path, target)


def slugify(text: str, prefix: str = "") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = slug or "item"
    if prefix and not slug.startswith(f"{prefix}-"):
        return f"{prefix}-{slug}"
    return slug


def validate_and_normalize_storyboard(
    storyboard: Dict[str, Any],
    project_dir: Optional[Path] = None,
    require_assets: bool = False,
) -> Dict[str, Any]:
    """
    Validate a storyboard dictionary against the canonical Bedtime Book Studio schema,
    normalizing legacy field aliases and recording actionable deprecation warnings.
    Raises `StoryboardValidationError` if required fields or (when `require_assets=True`)
    required image files are missing or malformed.
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(storyboard, dict):
        raise StoryboardValidationError(["Root storyboard payload must be a JSON object."])

    sb = json.loads(json.dumps(storyboard))

    title = sb.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append("root.title: Missing or empty required string field 'title'.")

    mode = sb.get("mode", "lift-the-flap")
    if mode not in ("lift-the-flap", "standard"):
        errors.append(f"root.mode: Invalid mode '{mode}'. Must be 'lift-the-flap' or 'standard'.")
    else:
        sb["mode"] = mode

    # Normalize cover
    cover = sb.get("cover")
    if not isinstance(cover, dict):
        cover = {}
    if not cover.get("prompt") and sb.get("cover_prompt"):
        cover["prompt"] = sb.pop("cover_prompt")
        warnings.append("root.cover_prompt: Deprecated top-level field normalized to 'cover.prompt'.")
    if not isinstance(cover.get("prompt"), str) or not cover.get("prompt", "").strip():
        errors.append("cover.prompt: Missing or empty required cover illustration prompt ('cover.prompt').")
    sb["cover"] = cover

    # Normalize end card
    end_info = sb.get("end")
    if not isinstance(end_info, dict):
        end_info = {}
    if "end_kicker" in sb and not end_info.get("kicker"):
        end_info["kicker"] = sb.pop("end_kicker")
        warnings.append("root.end_kicker: Deprecated field normalized to 'end.kicker'.")
    if "end_subtitle" in sb and not end_info.get("subtitle"):
        end_info["subtitle"] = sb.pop("end_subtitle")
        warnings.append("root.end_subtitle: Deprecated field normalized to 'end.subtitle'.")
    if end_info:
        sb["end"] = end_info

    pages = sb.get("pages")
    if not isinstance(pages, list) or len(pages) == 0:
        errors.append("root.pages: Must be a non-empty array of story page objects.")
        pages = []

    seen_numbers: set[int] = set()
    normalized_pages: List[Dict[str, Any]] = []

    for idx, raw_p in enumerate(pages):
        loc = f"pages[{idx}]"
        if not isinstance(raw_p, dict):
            errors.append(f"{loc}: Page entry must be a JSON object.")
            continue
        p = dict(raw_p)

        raw_num = p.get("number")
        if raw_num is None:
            errors.append(f"{loc}.number: Missing required 1-based integer field 'number'.")
            num = idx + 1
        else:
            try:
                num = int(raw_num)
                if num < 1:
                    errors.append(f"{loc}.number: Page number must be >= 1 (got {raw_num}).")
            except (TypeError, ValueError):
                errors.append(f"{loc}.number: Page number must be an integer (got {raw_num!r}).")
                num = idx + 1
        if num in seen_numbers:
            errors.append(f"{loc}.number: Duplicate page number {num}.")
        seen_numbers.add(num)
        p["number"] = num

        # Title
        if not isinstance(p.get("title"), str) or not p.get("title", "").strip():
            errors.append(f"{loc} (Page {num}).title: Missing or empty required string field 'title'.")

        # Badge alias
        if not p.get("badge") and p.get("label"):
            p["badge"] = p.pop("label")
            warnings.append(f"{loc} (Page {num}).label: Deprecated alias normalized to 'badge'.")
        elif not p.get("badge"):
            p["badge"] = f"Page {num}"

        # Paragraphs alias ('text' -> 'paragraphs')
        if "paragraphs" not in p and "text" in p:
            p["paragraphs"] = p.pop("text")
            warnings.append(f"{loc} (Page {num}).text: Deprecated alias normalized to 'paragraphs'.")
        elif "paragraphs" in p and "text" in p:
            p.pop("text", None)

        paras = p.get("paragraphs")
        if isinstance(paras, str) and paras.strip():
            p["paragraphs"] = [paras.strip()]
            warnings.append(f"{loc} (Page {num}).paragraphs: String value normalized to 1-element string array.")
        elif isinstance(paras, list) and len(paras) > 0 and all(isinstance(x, str) and x.strip() for x in paras):
            p["paragraphs"] = [x.strip() for x in paras]
        else:
            errors.append(f"{loc} (Page {num}).paragraphs: Missing or empty required array of story text strings.")

        # Reality prompt alias ('real_prompt' / 'prompt' -> 'reality_prompt')
        if not p.get("reality_prompt"):
            if p.get("real_prompt"):
                p["reality_prompt"] = p.pop("real_prompt")
                warnings.append(f"{loc} (Page {num}).real_prompt: Deprecated alias normalized to 'reality_prompt'.")
            elif p.get("prompt"):
                p["reality_prompt"] = p.pop("prompt")
                warnings.append(f"{loc} (Page {num}).prompt: Deprecated alias normalized to 'reality_prompt'.")

        if not isinstance(p.get("reality_prompt"), str) or not p.get("reality_prompt", "").strip():
            errors.append(f"{loc} (Page {num}).reality_prompt: Missing or empty required 'reality_prompt'.")

        # Lift-the-flap fields & aliases
        if not p.get("imagination_label"):
            for alias in ("imaginary_caption", "imaginaryCaption"):
                if p.get(alias):
                    p["imagination_label"] = p.pop(alias)
                    warnings.append(f"{loc} (Page {num}).{alias}: Deprecated alias normalized to 'imagination_label'.")
                    break

        if not p.get("flap_prompt"):
            for alias in ("flap_hint", "flapHint"):
                if p.get(alias):
                    p["flap_prompt"] = p.pop(alias)
                    warnings.append(f"{loc} (Page {num}).{alias}: Deprecated alias normalized to 'flap_prompt'.")
                    break

        if mode == "lift-the-flap":
            if not isinstance(p.get("imaginary_prompt"), str) or not p.get("imaginary_prompt", "").strip():
                errors.append(
                    f"{loc} (Page {num}).imaginary_prompt: Required in 'lift-the-flap' mode but missing or empty."
                )

        normalized_pages.append(p)

    # Check sequential numbering 1..N
    if normalized_pages and not errors:
        expected = list(range(1, len(normalized_pages) + 1))
        actual = [int(p["number"]) for p in normalized_pages]
        if actual != expected:
            errors.append(
                f"root.pages: Page numbers must be sequential 1..{len(normalized_pages)} (got {actual})."
            )

    sb["pages"] = normalized_pages

    # Check required image assets on disk if requested (e.g. before publish)
    if require_assets and project_dir is not None:
        assets_dir = project_dir / "assets"
        if not ((assets_dir / "cover.png").exists() or (assets_dir / "cover.webp").exists()):
            errors.append(f"assets/cover.png: Missing required cover image in {assets_dir}")
        for p in normalized_pages:
            num = int(p["number"])
            r_stem = f"page-{num:02d}-reality"
            if not ((assets_dir / f"{r_stem}.png").exists() or (assets_dir / f"{r_stem}.webp").exists()):
                errors.append(f"assets/{r_stem}.png: Missing required reality image for Page {num} in {assets_dir}")
            if mode == "lift-the-flap":
                i_stem = f"page-{num:02d}-imaginary"
                if not ((assets_dir / f"{i_stem}.png").exists() or (assets_dir / f"{i_stem}.webp").exists()):
                    errors.append(
                        f"assets/{i_stem}.png: Missing required imaginary flap image for Page {num} in {assets_dir}"
                    )

    if errors:
        raise StoryboardValidationError(errors=errors, warnings=warnings)

    return {
        "valid": True,
        "normalized_storyboard": sb,
        "warnings": warnings,
        "page_count": len(normalized_pages),
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

    _atomic_write_text(path, "\n".join(output_lines) + "\n")
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
# Persistent Character, Pet & Prop Identity Registry (Issue #1)
# ---------------------------------------------------------------------------

def _migrate_env_to_identities(env: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    """Seed structured identities from legacy `.env` fields if `identities.json` does not exist yet."""
    entities: Dict[str, Dict[str, Any]] = {}
    mc_name = env.get("MAIN_CHARACTER_NAME", "").strip()
    if mc_name:
        mc_id = slugify(mc_name, prefix="char")
        photo_paths = [
            str(resolve_repo_path(p))
            for p in parse_csv_list(env.get("MAIN_CHARACTER_PHOTO_PATHS", ""))
        ]
        refs = []
        for idx, p in enumerate(photo_paths, start=1):
            if Path(p).exists():
                refs.append({
                    "ref_id": f"ref-{idx:02d}",
                    "path": p,
                    "label": f"{mc_name} reference {idx}",
                    "active": True,
                    "is_character_sheet": False,
                })
        entities[mc_id] = {
            "id": mc_id,
            "kind": "main_character",
            "name": mc_name,
            "age_or_size": env.get("MAIN_CHARACTER_AGE", "").strip(),
            "appearance": env.get("MAIN_CHARACTER_DESCRIPTION", "").strip(),
            "signature_outfit": env.get("MAIN_CHARACTER_OUTFIT", "").strip(),
            "reality_description": env.get("MAIN_CHARACTER_OUTFIT", "").strip(),
            "imaginary_transformation": "",
            "approved_sheet_path": "",
            "references": refs,
            "updated_at": _utc_now_iso(),
        }

    for item in [s.strip() for s in env.get("SUPPORTING_CHARACTERS", "").split(";") if s.strip()]:
        name_part, _, desc_part = item.partition(":")
        name_clean = name_part.strip()[:40] or "Supporting Character"
        desc_clean = desc_part.strip() if desc_part else item
        is_pet = any(w in item.lower() for w in ("dog", "cat", "puppy", "kitten", "retriever", "terrier", "pet", "bunny", "hamster"))
        kind = "pet" if is_pet else "supporting_character"
        prefix = "pet" if is_pet else "char"
        eid = slugify(name_clean, prefix=prefix)
        entities[eid] = {
            "id": eid,
            "kind": kind,
            "name": name_clean,
            "age_or_size": "",
            "appearance": desc_clean,
            "signature_outfit": "",
            "reality_description": desc_clean,
            "imaginary_transformation": "",
            "approved_sheet_path": "",
            "references": [],
            "updated_at": _utc_now_iso(),
        }

    for item in [s.strip() for s in env.get("RECURRING_PROPS", "").split(";") if s.strip()]:
        name_part, _, desc_part = item.partition(":")
        name_clean = name_part.strip()[:40] if desc_part else " ".join(item.split()[:4])
        desc_clean = desc_part.strip() if desc_part else item
        eid = slugify(name_clean, prefix="prop")
        entities[eid] = {
            "id": eid,
            "kind": "prop",
            "name": name_clean,
            "age_or_size": "",
            "appearance": desc_clean,
            "signature_outfit": "",
            "reality_description": desc_clean,
            "imaginary_transformation": "",
            "approved_sheet_path": "",
            "references": [],
            "updated_at": _utc_now_iso(),
        }

    return entities


def load_identities() -> Dict[str, Dict[str, Any]]:
    """Load the persistent entity identity registry from `local_profile/identities.json`."""
    if IDENTITIES_FILE.exists():
        try:
            data = json.loads(IDENTITIES_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "entities" in data:
                return data["entities"]
        except Exception:
            pass

    env = parse_env_file(ENV_FILE)
    seeded = _migrate_env_to_identities(env)
    if seeded:
        save_identities(seeded)
    return seeded


def save_identities(entities: Dict[str, Dict[str, Any]]) -> None:
    LOCAL_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "updated_at": _utc_now_iso(),
        "entities": entities,
    }
    _atomic_write_text(IDENTITIES_FILE, json.dumps(payload, indent=2, ensure_ascii=False))


def list_identities(kind: Optional[str] = None) -> Dict[str, Any]:
    """List all persistent character, pet, and prop identities."""
    entities = load_identities()
    items = list(entities.values())
    if kind:
        items = [e for e in items if e.get("kind") == kind]
    return {
        "identities_file": str(IDENTITIES_FILE),
        "count": len(items),
        "entities": items,
    }


def _flag_books_affected_by_identity(entity_id: str) -> List[Dict[str, Any]]:
    """
    Find existing books and pages that reference `entity_id` and flag them in their
    `revision_state.json` without silently overwriting or regenerating their artwork.
    """
    affected: List[Dict[str, Any]] = []
    books_dir = get_books_dir()
    if not books_dir.exists():
        return affected

    for child in sorted(books_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        sb_path = child / "storyboard.json"
        meta_path = child / "book_meta.json"
        if not (sb_path.exists() or meta_path.exists()):
            continue

        cast_ids: List[str] = []
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                cast_ids.extend(meta.get("cast_ids") or [])
            except Exception:
                pass

        affected_pages: List[int] = []
        if sb_path.exists():
            try:
                sb = json.loads(sb_path.read_text(encoding="utf-8"))
                cast_ids.extend(sb.get("cast_ids") or [])
                for p in sb.get("pages") or []:
                    p_eids = p.get("entity_ids") or []
                    t_eids = [m.get("entity_id") for m in (p.get("transformation_mappings") or []) if m.get("entity_id")]
                    if entity_id in p_eids or entity_id in t_eids:
                        affected_pages.append(int(p.get("number", 0)))
            except Exception:
                pass

        if entity_id in cast_ids or affected_pages:
            rev_state = _load_revision_state(child)
            flagged_list = rev_state.setdefault("flagged_identity_updates", [])
            if entity_id not in flagged_list:
                flagged_list.append(entity_id)
            for pnum in affected_pages:
                for suffix in ("reality", "imaginary"):
                    akey = f"page-{pnum:02d}-{suffix}"
                    if akey in rev_state.get("assets", {}):
                        rev_state["assets"][akey]["identity_updated_flag"] = True
            _save_revision_state(child, rev_state)
            affected.append({
                "slug": child.name,
                "affected_pages": sorted(set(affected_pages)),
            })

    return affected


def upsert_identity(
    entity_id: Optional[str] = None,
    name: str = "",
    kind: str = "supporting_character",
    age_or_size: Optional[str] = None,
    appearance: Optional[str] = None,
    signature_outfit: Optional[str] = None,
    reality_description: Optional[str] = None,
    imaginary_transformation: Optional[str] = None,
    reference_photos: Optional[List[str]] = None,
    reference_labels: Optional[List[str]] = None,
    approved_sheet_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create or update a persistent character, sibling, pet, or recurring prop identity
    with a stable ID (`char-...`, `pet-...`, `prop-...`) in `local_profile/identities.json`.
    """
    if kind not in VALID_ENTITY_KINDS:
        raise ValueError(f"kind must be one of {VALID_ENTITY_KINDS}")

    entities = load_identities()
    prefix_map = {
        "main_character": "char",
        "supporting_character": "char",
        "pet": "pet",
        "prop": "prop",
    }
    resolved_id = slugify(entity_id or name, prefix=prefix_map[kind])
    existing = entities.get(resolved_id, {
        "id": resolved_id,
        "kind": kind,
        "name": name or resolved_id,
        "age_or_size": "",
        "appearance": "",
        "signature_outfit": "",
        "reality_description": "",
        "imaginary_transformation": "",
        "approved_sheet_path": "",
        "references": [],
    })

    if name:
        existing["name"] = name
    existing["kind"] = kind
    if age_or_size is not None:
        existing["age_or_size"] = age_or_size
    if appearance is not None:
        existing["appearance"] = appearance
    if signature_outfit is not None:
        existing["signature_outfit"] = signature_outfit
    if reality_description is not None:
        existing["reality_description"] = reality_description
    if imaginary_transformation is not None:
        existing["imaginary_transformation"] = imaginary_transformation

    entity_ref_dir = LOCAL_REFS_DIR / resolved_id
    if approved_sheet_path is not None:
        if approved_sheet_path.strip():
            src_sheet = Path(os.path.expanduser(approved_sheet_path.strip())).resolve()
            if not src_sheet.exists():
                raise FileNotFoundError(f"Approved sheet not found: {approved_sheet_path}")
            entity_ref_dir.mkdir(parents=True, exist_ok=True)
            dest_sheet = entity_ref_dir / f"character-sheet{src_sheet.suffix.lower() or '.png'}"
            if src_sheet != dest_sheet.resolve():
                shutil.copy2(src_sheet, dest_sheet)
            existing["approved_sheet_path"] = str(dest_sheet)
        else:
            existing["approved_sheet_path"] = ""

    if reference_photos is not None:
        entity_ref_dir.mkdir(parents=True, exist_ok=True)
        refs_list: List[Dict[str, Any]] = list(existing.get("references") or [])
        next_idx = len(refs_list) + 1
        for i, raw_p in enumerate(reference_photos):
            if not raw_p or not raw_p.strip():
                continue
            src = Path(os.path.expanduser(raw_p.strip())).resolve()
            if not src.exists():
                raise FileNotFoundError(f"Reference photo not found: {raw_p}")
            ext = src.suffix.lower() or ".jpg"
            ref_id = f"ref-{next_idx:02d}"
            next_idx += 1
            safe_stem = re.sub(r"[^a-z0-9_-]+", "-", src.stem.lower()).strip("-") or ref_id
            dest = entity_ref_dir / f"{ref_id}-{safe_stem}{ext}"
            if src != dest.resolve():
                shutil.copy2(src, dest)
            label = (
                reference_labels[i]
                if (reference_labels and i < len(reference_labels) and reference_labels[i])
                else f"{existing['name']} ({ref_id})"
            )
            refs_list.append({
                "ref_id": ref_id,
                "path": str(dest),
                "label": label,
                "active": True,
                "is_character_sheet": False,
            })
        existing["references"] = refs_list

    existing["updated_at"] = _utc_now_iso()
    entities[resolved_id] = existing
    save_identities(entities)

    affected_books = _flag_books_affected_by_identity(resolved_id)
    return {
        "status": "saved",
        "entity": existing,
        "affected_books": affected_books,
    }


def manage_identity_reference(
    entity_id: str,
    action: str,
    ref_id: Optional[str] = None,
    photo_path: Optional[str] = None,
    label: Optional[str] = None,
    active: Optional[bool] = None,
    is_character_sheet: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Add, update, enable/exclude (`active=True/False`), or remove an individual reference photo
    on a specific entity ID without changing unrelated profiles.
    """
    entities = load_identities()
    if entity_id not in entities:
        raise KeyError(f"Entity ID '{entity_id}' not found in local_profile/identities.json")

    entity = entities[entity_id]
    refs: List[Dict[str, Any]] = list(entity.get("references") or [])

    if action == "add":
        if not photo_path:
            raise ValueError("photo_path is required when action='add'")
        src = Path(os.path.expanduser(photo_path.strip())).resolve()
        if not src.exists():
            raise FileNotFoundError(f"Reference photo not found: {photo_path}")
        entity_ref_dir = LOCAL_REFS_DIR / entity_id
        entity_ref_dir.mkdir(parents=True, exist_ok=True)
        new_ref_id = ref_id or f"ref-{len(refs) + 1:02d}"
        ext = src.suffix.lower() or ".jpg"
        dest = entity_ref_dir / f"{new_ref_id}-{src.stem}{ext}"
        if src != dest.resolve():
            shutil.copy2(src, dest)
        refs.append({
            "ref_id": new_ref_id,
            "path": str(dest),
            "label": label or f"{entity['name']} ({new_ref_id})",
            "active": True if active is None else bool(active),
            "is_character_sheet": bool(is_character_sheet),
        })
    elif action == "update":
        if not ref_id:
            raise ValueError("ref_id is required when action='update'")
        matched = False
        for r in refs:
            if r.get("ref_id") == ref_id:
                matched = True
                if label is not None:
                    r["label"] = label
                if active is not None:
                    r["active"] = bool(active)
                if is_character_sheet is not None:
                    r["is_character_sheet"] = bool(is_character_sheet)
        if not matched:
            raise KeyError(f"Reference '{ref_id}' not found on entity '{entity_id}'")
    elif action == "remove":
        if not ref_id:
            raise ValueError("ref_id is required when action='remove'")
        refs = [r for r in refs if r.get("ref_id") != ref_id]
    else:
        raise ValueError("action must be 'add', 'update', or 'remove'")

    entity["references"] = refs
    entity["updated_at"] = _utc_now_iso()
    entities[entity_id] = entity
    save_identities(entities)
    return {"status": "updated", "entity": entity}


# ---------------------------------------------------------------------------
# Onboarding & Studio Profile
# ---------------------------------------------------------------------------

def get_studio_profile() -> Dict[str, Any]:
    """Load the user's studio configuration from `.env` and `local_profile/identities.json`."""
    env = parse_env_file(ENV_FILE)
    identities = load_identities()

    photo_paths = [
        str(resolve_repo_path(p))
        for p in parse_csv_list(env.get("MAIN_CHARACTER_PHOTO_PATHS", ""))
    ]
    existing_photos = [p for p in photo_paths if Path(p).exists()]

    has_char_name = bool(env.get("MAIN_CHARACTER_NAME", "").strip()) or any(
        e.get("kind") == "main_character" for e in identities.values()
    )
    has_char_visuals = (
        bool(env.get("MAIN_CHARACTER_DESCRIPTION", "").strip())
        or bool(existing_photos)
        or any(
            e.get("kind") == "main_character" and (e.get("appearance") or e.get("references"))
            for e in identities.values()
        )
    )
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
        "identities_file": str(IDENTITIES_FILE),
        "main_character": {
            "name": env.get("MAIN_CHARACTER_NAME", ""),
            "age": env.get("MAIN_CHARACTER_AGE", ""),
            "description": env.get("MAIN_CHARACTER_DESCRIPTION", ""),
            "outfit": env.get("MAIN_CHARACTER_OUTFIT", ""),
            "photo_paths": existing_photos,
        },
        "supporting_characters": env.get("SUPPORTING_CHARACTERS", ""),
        "recurring_props": env.get("RECURRING_PROPS", ""),
        "identities": list(identities.values()),
        "defaults": {
            "art_style": env.get("DEFAULT_ART_STYLE", DEFAULT_ENV_VALUES["DEFAULT_ART_STYLE"]),
            "book_mode": env.get("DEFAULT_BOOK_MODE", "lift-the-flap"),
            "bedtime_mode": env.get("DEFAULT_BEDTIME_MODE", "false").lower() == "true",
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
    has_main_entity = any(e.get("kind") == "main_character" for e in profile.get("identities", []))
    if not mc["name"] and not has_main_entity:
        missing.append("main_character_name")
    if not mc["description"] and not mc["photo_paths"] and not has_main_entity:
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
            "5. Call `configure_studio(...)` (and `upsert_identity(...)` for distinct siblings/pets/props) to save these defaults."
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
    default_bedtime_mode: Optional[bool] = None,
    default_page_count: Optional[int] = None,
    books_output_dir: Optional[str] = None,
    local_server_port: Optional[int] = None,
    publish_web_root: Optional[str] = None,
    publish_base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Save character details, reference photos, and studio defaults to `.env` and sync with `identities.json`."""
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
    if default_bedtime_mode is not None:
        updates["DEFAULT_BEDTIME_MODE"] = "true" if default_bedtime_mode else "false"
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

    env_after = write_env_file(updates, ENV_FILE)

    # Also sync main character into persistent identities registry
    mc_name = env_after.get("MAIN_CHARACTER_NAME", "").strip()
    if mc_name:
        upsert_identity(
            entity_id=slugify(mc_name, prefix="char"),
            name=mc_name,
            kind="main_character",
            age_or_size=env_after.get("MAIN_CHARACTER_AGE", ""),
            appearance=env_after.get("MAIN_CHARACTER_DESCRIPTION", ""),
            signature_outfit=env_after.get("MAIN_CHARACTER_OUTFIT", ""),
            reality_description=env_after.get("MAIN_CHARACTER_OUTFIT", ""),
            reference_photos=copied_photos if main_character_photos is not None else None,
        )

    profile = get_studio_profile()
    LOCAL_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(LOCAL_PROFILE_DIR / "profile.json", json.dumps(profile, indent=2))

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
    print("and `local_profile/` (which are gitignored and never committed).\n")

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
        "Supporting characters / family / pets (e.g. Mom: glasses; Max: golden retriever)",
        current["supporting_characters"],
    )
    props = _prompt_input(
        "Favorite recurring toys or props (e.g. wooden tricycle; stuffed bunny)",
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
    print(f"   {IDENTITIES_FILE}")
    if result["copied_reference_photos"]:
        print("   Copied reference photos to:")
        for p in result["copied_reference_photos"]:
            print(f"     - {p}")
    print()
    return result


# ---------------------------------------------------------------------------
# Revision State & Version History Helpers (Issue #3 & #5)
# ---------------------------------------------------------------------------

def _load_revision_state(project_dir: Path) -> Dict[str, Any]:
    rev_file = project_dir / "revision_state.json"
    if rev_file.exists():
        try:
            return json.loads(rev_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "schema_version": 1,
        "storyboard_approved": False,
        "updated_at": _utc_now_iso(),
        "flagged_identity_updates": [],
        "page_notes": {},
        "revision_log": [],
        "assets": {},
    }


def _save_revision_state(project_dir: Path, state: Dict[str, Any]) -> None:
    state["updated_at"] = _utc_now_iso()
    _atomic_write_text(project_dir / "revision_state.json", json.dumps(state, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Book Project Pipeline (list, init, storyboard, preview, ingest, revise, publish)
# ---------------------------------------------------------------------------

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
        preview_html = child / "preview.html"
        published_dir = (web_root / slug) if web_root else None
        is_published = bool(published_dir and (published_dir / "index.html").exists())
        live_url = f"{base_url}/{slug}" if (is_published and base_url) else None

        books.append({
            "slug": slug,
            "workspace_dir": str(child),
            "single_file_html": str(standalone_html) if standalone_html.exists() else None,
            "preview_html": str(preview_html) if preview_html.exists() else None,
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
    cast_ids: Optional[List[str]] = None,
    entity_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    bedtime_mode: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Initialize a new book project workspace.
    Supports selecting persistent `cast_ids` from `local_profile/identities.json` and
    providing per-book `entity_overrides` (e.g. special outfit for this book) without
    mutating the global family profile.
    """
    profile = get_studio_profile()
    mc = profile["main_character"]
    defaults = profile["defaults"]
    identities = load_identities()

    slug = slugify(slug or title)
    project_dir = get_books_dir() / slug
    assets_dir = project_dir / "assets"
    refs_dir = assets_dir / "references"
    refs_dir.mkdir(parents=True, exist_ok=True)

    resolved_mode = mode or defaults["book_mode"] or "lift-the-flap"
    resolved_pages = int(page_count or defaults["page_count"] or 12)
    resolved_bedtime = defaults.get("bedtime_mode", False) if bedtime_mode is None else bool(bedtime_mode)

    selected_cast_ids = list(cast_ids) if cast_ids is not None else list(identities.keys())
    overrides = dict(entity_overrides or {})

    # Resolve character name & description
    resolved_char_name = character_name or mc["name"]
    if not resolved_char_name:
        for eid in selected_cast_ids:
            ent = identities.get(eid)
            if ent and ent.get("kind") == "main_character":
                resolved_char_name = ent.get("name")
                break
    resolved_char_name = resolved_char_name or "Our Hero"

    default_desc_parts = []
    if mc["age"]:
        default_desc_parts.append(f"{mc['age']}-year-old")
    if mc["description"]:
        default_desc_parts.append(mc["description"])
    if mc["outfit"]:
        default_desc_parts.append(f"wearing {mc['outfit']}")
    resolved_char_desc = character_description or ", ".join(default_desc_parts) or "Friendly young child"

    # Copy active references per entity into assets/references/<entity_id>/ so they remain unambiguously labeled
    entity_ref_manifest: Dict[str, List[Dict[str, str]]] = {}
    copied_refs: List[str] = []

    for eid in selected_cast_ids:
        ent = identities.get(eid)
        if not ent:
            continue
        ent_refs: List[Dict[str, str]] = []
        if ent.get("approved_sheet_path") and Path(ent["approved_sheet_path"]).exists():
            src_s = Path(ent["approved_sheet_path"]).resolve()
            dest_s = refs_dir / f"{eid}-approved-sheet{src_s.suffix.lower() or '.png'}"
            shutil.copy2(src_s, dest_s)
            copied_refs.append(str(dest_s))
            ent_refs.append({
                "ref_id": "approved-sheet",
                "label": f"{ent['name']} approved character sheet",
                "path": str(dest_s),
            })
        for r in ent.get("references") or []:
            if not r.get("active", True):
                continue
            src_r = Path(r.get("path", "")).resolve()
            if src_r.exists():
                rid = r.get("ref_id", "ref")
                dest_r = refs_dir / f"{eid}-{rid}{src_r.suffix.lower() or '.jpg'}"
                shutil.copy2(src_r, dest_r)
                copied_refs.append(str(dest_r))
                ent_refs.append({
                    "ref_id": rid,
                    "label": r.get("label") or f"{ent['name']} ({rid})",
                    "path": str(dest_r),
                })
        if ent_refs:
            entity_ref_manifest[eid] = ent_refs

    # Also copy any ad-hoc book-specific reference_images
    adhoc_refs: List[str] = []
    if reference_images:
        for idx, ref_path_str in enumerate(reference_images, start=1):
            src = Path(os.path.expanduser(ref_path_str)).resolve()
            if src.exists():
                ext = src.suffix.lower() or ".jpg"
                dest = refs_dir / f"book-ref-{idx:02d}-{src.stem}{ext}"
                shutil.copy2(src, dest)
                copied_refs.append(str(dest))
                adhoc_refs.append(str(dest))

    meta = {
        "slug": slug,
        "title": title,
        "idea": idea,
        "mode": resolved_mode,
        "bedtime_mode": resolved_bedtime,
        "character_name": resolved_char_name,
        "character_description": resolved_char_desc,
        "cast_ids": selected_cast_ids,
        "entity_overrides": overrides,
        "entity_reference_manifest": entity_ref_manifest,
        "adhoc_reference_images": adhoc_refs,
        "supporting_characters": profile["supporting_characters"],
        "recurring_props": profile["recurring_props"],
        "art_style": defaults["art_style"],
        "page_count": resolved_pages,
        "reference_images": copied_refs,
        "project_dir": str(project_dir),
    }

    _atomic_write_text(project_dir / "book_meta.json", json.dumps(meta, indent=2, ensure_ascii=False))

    cast_lines = []
    for eid in selected_cast_ids:
        base_ent = identities.get(eid)
        if not base_ent:
            continue
        merged = dict(base_ent)
        merged.update(overrides.get(eid) or {})
        refs_str = ", ".join(f"{r['label']}: `{r['path']}`" for r in entity_ref_manifest.get(eid, [])) or "Text-only"
        cast_lines.append(
            f"- **`{eid}` ({merged.get('name')} — {merged.get('kind')})**: "
            f"Size/Age: {merged.get('age_or_size') or 'N/A'} | Appearance: {merged.get('appearance')} | "
            f"Outfit/Reality: {merged.get('reality_description') or merged.get('signature_outfit')} | "
            f"Imaginary Transformation: {merged.get('imaginary_transformation') or 'Same as reality'} | "
            f"References: {refs_str}"
        )

    cast_section = "\n".join(cast_lines) if cast_lines else f"- **Main Character**: {resolved_char_name} ({resolved_char_desc})"

    prompt_guide = f"""# Storyboard Generation Guide for "{title}"

- **Slug**: `{slug}`
- **Book Mode**: `{resolved_mode}` (`lift-the-flap` = Reality flap + Imaginary world underneath; `standard` = single scene per page)
- **Bedtime Mode Default**: `{resolved_bedtime}` (wind down gently across the final 2–3 pages)
- **Target Pages**: {resolved_pages} story pages + 1 cover
- **Art Style**: {defaults['art_style']}
- **Story Idea**: {idea}

## Assigned Cast & Prop Identities (with Per-Book Overrides)
{cast_section}

## Next Step
Create `{project_dir}/storyboard.json` (or call `save_storyboard`) with:
- `title`, `subtitle`, `kicker`, `mode`, `bedtime_mode`, `cast_ids`
- `character_bible`: visual continuity rules
- `cover`: `prompt`
- `pages`: array of {resolved_pages} pages, each with:
  - `number` (1..{resolved_pages}), `badge`, `title`, `paragraphs`, `refrain`
  - `entity_ids`: array of entity IDs appearing on this page (e.g. `["char-leo", "prop-cardboard-rocket"]`)
  - `shared_composition`: `camera_angle`, `horizon_line`, `focal_subject_placement`, `character_pose`, `key_shapes`
  - `transformation_mappings`: array of `{{"entity_id": "...", "reality_element": "...", "imaginary_element": "...", "spatial_anchor": "..."}}`
  - `reality_prompt` and `imaginary_prompt`
- `end`: `kicker`, `title`, `subtitle`, `bedtime_kicker`, `bedtime_title`, `bedtime_subtitle`
"""
    _atomic_write_text(project_dir / "STORYBOARD_PROMPT.md", prompt_guide)
    return meta


def _resolve_book_entities(project_dir: Path, storyboard: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Combine global `local_profile/identities.json`, inline `storyboard.identities`,
    and per-book `entity_overrides` from `book_meta.json` / `storyboard.json` without
    mutating the global profile.
    """
    resolved: Dict[str, Dict[str, Any]] = {}
    for eid, ent in load_identities().items():
        resolved[eid] = json.loads(json.dumps(ent))

    for inline_ent in storyboard.get("identities") or []:
        if isinstance(inline_ent, dict) and inline_ent.get("id"):
            eid = inline_ent["id"]
            base = resolved.get(eid, {"id": eid, "references": []})
            base.update(inline_ent)
            resolved[eid] = base

    meta_path = project_dir / "book_meta.json"
    book_overrides: Dict[str, Dict[str, Any]] = {}
    ref_manifest: Dict[str, List[Dict[str, str]]] = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            book_overrides.update(meta.get("entity_overrides") or {})
            ref_manifest.update(meta.get("entity_reference_manifest") or {})
        except Exception:
            pass
    book_overrides.update(storyboard.get("entity_overrides") or {})

    for eid, ov in book_overrides.items():
        if eid in resolved and isinstance(ov, dict):
            resolved[eid].update(ov)
        elif isinstance(ov, dict):
            resolved[eid] = {"id": eid, **ov}

    # Attach book-copied reference paths if available
    for eid, ent in resolved.items():
        if eid in ref_manifest:
            ent["book_references"] = ref_manifest[eid]
        else:
            active_refs = [
                {"ref_id": r.get("ref_id", "ref"), "label": r.get("label", ent.get("name", eid)), "path": r.get("path", "")}
                for r in (ent.get("references") or [])
                if r.get("active", True) and r.get("path")
            ]
            if ent.get("approved_sheet_path"):
                active_refs.insert(0, {
                    "ref_id": "approved-sheet",
                    "label": f"{ent.get('name', eid)} approved character sheet",
                    "path": ent["approved_sheet_path"],
                })
            ent["book_references"] = active_refs

    return resolved


def _assemble_page_prompts(
    page: Dict[str, Any],
    mode: str,
    resolved_entities: Dict[str, Dict[str, Any]],
    project_dir: Path,
    art_style: str,
    supports_reference_images: bool = True,
) -> Dict[str, Any]:
    """
    Assemble complete Reality and Imaginary prompt packages for a single page,
    binding entity IDs -> descriptions & labeled reference paths, shared composition
    constraints, transformation mappings, and reality->imaginary reference chaining.
    """
    num = int(page.get("number", 1))
    raw_reality = page.get("reality_prompt") or page.get("real_prompt") or page.get("prompt") or ""
    raw_imaginary = page.get("imaginary_prompt") or ""

    # Determine which entity IDs appear on this page
    page_entity_ids: List[str] = list(page.get("entity_ids") or [])
    for m in page.get("transformation_mappings") or []:
        eid = m.get("entity_id")
        if eid and eid not in page_entity_ids:
            page_entity_ids.append(eid)

    if not page_entity_ids and resolved_entities:
        # Auto-match entities whose name appears in the prompt or text
        combined_text = f"{raw_reality} {raw_imaginary} {' '.join(page.get('paragraphs') or page.get('text') or [])}".lower()
        for eid, ent in resolved_entities.items():
            ename = (ent.get("name") or "").lower()
            if ename and ename in combined_text:
                page_entity_ids.append(eid)

    entity_assignments: List[Dict[str, Any]] = []
    reality_cast_lines: List[str] = []
    imaginary_cast_lines: List[str] = []
    labeled_reference_files: List[Dict[str, str]] = []

    for eid in page_entity_ids:
        ent = resolved_entities.get(eid)
        if not ent:
            continue
        name = ent.get("name", eid)
        kind = ent.get("kind", "entity")
        size = ent.get("age_or_size", "")
        app = ent.get("appearance", "")
        outfit = ent.get("signature_outfit", "")
        r_desc = ent.get("reality_description") or outfit or app
        i_desc = ent.get("imaginary_transformation") or r_desc
        refs = ent.get("book_references") or []

        for r in refs:
            labeled_reference_files.append({
                "entity_id": eid,
                "entity_name": name,
                "ref_id": r.get("ref_id", "ref"),
                "label": r.get("label", name),
                "path": r.get("path", ""),
            })

        entity_assignments.append({
            "entity_id": eid,
            "name": name,
            "kind": kind,
            "age_or_size": size,
            "appearance": app,
            "reality_description": r_desc,
            "imaginary_transformation": i_desc,
            "references": refs,
        })

        size_clause = f" ({size})" if size else ""
        reality_cast_lines.append(f"- [{eid}] {name}{size_clause}: {app}. In Reality: {r_desc}".strip())
        imaginary_cast_lines.append(f"- [{eid}] {name}{size_clause}: {app}. In Imagination: {i_desc}".strip())

    comp = page.get("shared_composition") or {}
    comp_lines: List[str] = []
    if comp:
        if comp.get("camera_angle"):
            comp_lines.append(f"Camera Angle: {comp['camera_angle']}")
        if comp.get("horizon_line"):
            comp_lines.append(f"Horizon Line: {comp['horizon_line']}")
        if comp.get("focal_subject_placement"):
            comp_lines.append(f"Subject Placement: {comp['focal_subject_placement']}")
        if comp.get("character_pose"):
            comp_lines.append(f"Character Pose: {comp['character_pose']}")
        if comp.get("key_shapes"):
            shapes = ", ".join(comp["key_shapes"]) if isinstance(comp["key_shapes"], list) else str(comp["key_shapes"])
            comp_lines.append(f"Key Shapes/Silhouettes: {shapes}")

    mappings = page.get("transformation_mappings") or []
    mapping_lines: List[str] = []
    for m in mappings:
        r_el = m.get("reality_element", "")
        i_el = m.get("imaginary_element", "")
        anchor = m.get("spatial_anchor", "same position")
        meid = f" [{m['entity_id']}]" if m.get("entity_id") else ""
        mapping_lines.append(f"-{meid} At {anchor}: '{r_el}' (Reality) -> transforms into -> '{i_el}' (Imaginary)")

    # Assemble full Reality prompt
    assembled_reality_parts = [raw_reality]
    if reality_cast_lines:
        assembled_reality_parts.append("Character & Prop Continuity:\n" + "\n".join(reality_cast_lines))
    if comp_lines:
        assembled_reality_parts.append("Shared Scene Composition Lock:\n" + "\n".join(f"- {c}" for c in comp_lines))
    assembled_reality_parts.append(f"Style: {art_style}")
    assembled_reality_prompt = "\n\n".join(p for p in assembled_reality_parts if p)

    # Assemble full Imaginary prompt with Reality reference chaining
    reality_target_path = str(project_dir / "assets" / f"page-{num:02d}-reality.png")
    capability_warning: Optional[str] = None
    if mode == "lift-the-flap" and not supports_reference_images:
        capability_warning = (
            "Image generator reported `supports_reference_images=False`: cannot pass "
            f"`{reality_target_path}` as an image-to-image/composition reference. Falling back "
            "to strict text-based spatial anchor and geometry lock instructions."
        )

    assembled_imaginary_parts = [raw_imaginary]
    if imaginary_cast_lines:
        assembled_imaginary_parts.append("Character & Prop Continuity (Imaginary State):\n" + "\n".join(imaginary_cast_lines))
    if comp_lines:
        assembled_imaginary_parts.append(
            "Match Page Reality Composition Exactly (same camera angle, horizon, and character placement):\n"
            + "\n".join(f"- {c}" for c in comp_lines)
        )
    if mapping_lines:
        assembled_imaginary_parts.append(
            "Flap Reveal 1-to-1 Element Transformations:\n" + "\n".join(mapping_lines)
        )
    assembled_imaginary_parts.append(f"Style: {art_style}")
    assembled_imaginary_prompt = "\n\n".join(p for p in assembled_imaginary_parts if p)

    return {
        "page_number": num,
        "entity_assignments": entity_assignments,
        "labeled_reference_files": labeled_reference_files,
        "shared_composition": comp,
        "transformation_mappings": mappings,
        "reality_target": reality_target_path,
        "imaginary_target": str(project_dir / "assets" / f"page-{num:02d}-imaginary.png"),
        "primary_composition_reference_for_imaginary": reality_target_path if supports_reference_images else None,
        "capability_warning": capability_warning,
        "assembled_reality_prompt": assembled_reality_prompt,
        "assembled_imaginary_prompt": assembled_imaginary_prompt,
    }


def validate_book_storyboard(
    slug: str,
    require_assets: bool = False,
) -> Dict[str, Any]:
    """Validate an existing book's `storyboard.json` (and optionally its required image assets on disk)."""
    slug = slugify(slug)
    project_dir = get_books_dir() / slug
    sb_path = project_dir / "storyboard.json"
    if not sb_path.exists():
        raise FileNotFoundError(f"Missing storyboard.json in {project_dir}")

    raw_sb = json.loads(sb_path.read_text(encoding="utf-8"))
    try:
        res = validate_and_normalize_storyboard(
            raw_sb,
            project_dir=project_dir,
            require_assets=require_assets,
        )
        return {
            "slug": slug,
            "valid": True,
            "require_assets": require_assets,
            "errors": [],
            "warnings": res["warnings"],
            "page_count": res["page_count"],
        }
    except StoryboardValidationError as exc:
        return {
            "slug": slug,
            "valid": False,
            "require_assets": require_assets,
            "errors": exc.errors,
            "warnings": exc.warnings,
        }


def save_storyboard(
    slug: str,
    storyboard: Dict[str, Any],
    supports_reference_images: bool = True,
) -> Dict[str, Any]:
    """
    Validate and normalize `storyboard.json` against the canonical schema (converting any
    legacy field aliases with warnings), resolve persistent entity identities and
    transformation mappings, and generate `prompts.md` + the structured image generation plan.
    """
    slug = slugify(slug)
    project_dir = get_books_dir() / slug
    project_dir.mkdir(parents=True, exist_ok=True)

    val_res = validate_and_normalize_storyboard(
        storyboard,
        project_dir=project_dir,
        require_assets=False,
    )
    storyboard = val_res["normalized_storyboard"]
    validation_warnings = val_res["warnings"]

    sb_path = project_dir / "storyboard.json"
    _atomic_write_text(sb_path, json.dumps(storyboard, indent=2, ensure_ascii=False))

    profile = get_studio_profile()
    art_style = storyboard.get("art_style") or profile["defaults"]["art_style"]
    mode = storyboard.get("mode", "lift-the-flap")
    title = storyboard.get("title", slug)
    char_bible = storyboard.get("character_bible", "")
    cover_prompt = (storyboard.get("cover") or {}).get("prompt") or ""
    pages = storyboard.get("pages") or []

    resolved_entities = _resolve_book_entities(project_dir, storyboard)

    md_lines = [
        f"# {title} — Illustration Prompts & Flap Transformation Plan (`{mode}`)",
        "",
        "## 1. Persistent Cast & Prop Identities (`entity_id` -> Reference Map)",
    ]

    if resolved_entities:
        for eid, ent in resolved_entities.items():
            refs_desc = ", ".join(
                f"[{r['ref_id']}: {r['label']}]({r['path']})"
                for r in (ent.get("book_references") or [])
            ) or "Text description only"
            md_lines.append(
                f"- **`{eid}` — {ent.get('name')} ({ent.get('kind')})**: "
                f"{ent.get('age_or_size') or ''} | {ent.get('appearance') or ''} | "
                f"**Reality**: {ent.get('reality_description') or ent.get('signature_outfit') or 'N/A'} | "
                f"**Imaginary**: {ent.get('imaginary_transformation') or 'Same as reality'} | "
                f"**Refs**: {refs_desc}"
            )
    else:
        md_lines.append(char_bible if isinstance(char_bible, str) else json.dumps(char_bible, indent=2))

    if char_bible:
        md_lines.extend(["", "### Continuity Notes", str(char_bible)])

    md_lines.extend([
        "",
        "## 2. Cover (`assets/cover.png`)",
        f"- **Prompt**: {cover_prompt}",
        "",
        "## 3. Story Pages & Reality↔Imagination Transformation Mappings",
        "",
    ])

    all_cover_refs = [
        {"entity_id": eid, "label": r["label"], "path": r["path"]}
        for eid, ent in resolved_entities.items()
        for r in (ent.get("book_references") or [])
    ]

    required_images: List[Dict[str, Any]] = [
        {
            "key": "cover",
            "stage": 1,
            "target": str(project_dir / "assets" / "cover.png"),
            "prompt": cover_prompt,
            "entity_references": all_cover_refs,
            "depends_on": None,
            "primary_composition_reference": None,
        }
    ]

    capability_warnings: List[str] = []

    for p in pages:
        num = int(p.get("number", 0))
        p_title = p.get("title", f"Page {num}")
        pkg = _assemble_page_prompts(
            page=p,
            mode=mode,
            resolved_entities=resolved_entities,
            project_dir=project_dir,
            art_style=art_style,
            supports_reference_images=supports_reference_images,
        )
        if pkg["capability_warning"]:
            capability_warnings.append(f"Page {num:02d}: {pkg['capability_warning']}")

        md_lines.append(f"### Page {num:02d} — {p_title}")
        if pkg["entity_assignments"]:
            e_summary = ", ".join(f"`{e['entity_id']}` ({e['name']})" for e in pkg["entity_assignments"])
            md_lines.append(f"- **Active Entities**: {e_summary}")
        if pkg["labeled_reference_files"]:
            r_summary = ", ".join(
                f"`{r['entity_id']}:{r['ref_id']}` -> `{r['path']}`"
                for r in pkg["labeled_reference_files"]
            )
            md_lines.append(f"- **Assigned Reference Files**: {r_summary}")
        if pkg["shared_composition"]:
            md_lines.append(f"- **Shared Composition Lock**: `{json.dumps(pkg['shared_composition'], ensure_ascii=False)}`")
        if pkg["transformation_mappings"]:
            md_lines.append("- **Flap Transformation Mappings**:")
            for m in pkg["transformation_mappings"]:
                md_lines.append(
                    f"  - `{m.get('spatial_anchor', 'Scene')}`: **{m.get('reality_element')}** ➡️ **{m.get('imaginary_element')}**"
                )

        if mode == "lift-the-flap":
            md_lines.append(f"- **Stage 1 — Reality (`assets/page-{num:02d}-reality.png`)**:\n  {pkg['assembled_reality_prompt']}")
            md_lines.append(
                f"- **Stage 2 — Imaginary (`assets/page-{num:02d}-imaginary.png`)** "
                f"*(uses `assets/page-{num:02d}-reality.png` as composition reference)*:\n  {pkg['assembled_imaginary_prompt']}"
            )
            if pkg["capability_warning"]:
                md_lines.append(f"  - ⚠️ **Capability Warning**: {pkg['capability_warning']}")

            required_images.append({
                "key": f"page-{num:02d}-reality",
                "stage": 1,
                "page_number": num,
                "target": pkg["reality_target"],
                "prompt": pkg["assembled_reality_prompt"],
                "entity_references": pkg["labeled_reference_files"],
                "shared_composition": pkg["shared_composition"],
                "depends_on": None,
                "primary_composition_reference": None,
            })
            required_images.append({
                "key": f"page-{num:02d}-imaginary",
                "stage": 2,
                "page_number": num,
                "target": pkg["imaginary_target"],
                "prompt": pkg["assembled_imaginary_prompt"],
                "entity_references": pkg["labeled_reference_files"],
                "shared_composition": pkg["shared_composition"],
                "transformation_mappings": pkg["transformation_mappings"],
                "depends_on": f"page-{num:02d}-reality",
                "primary_composition_reference": pkg["primary_composition_reference_for_imaginary"],
                "capability_warning": pkg["capability_warning"],
            })
        else:
            md_lines.append(f"- **Scene (`assets/page-{num:02d}-reality.png`)**:\n  {pkg['assembled_reality_prompt']}")
            required_images.append({
                "key": f"page-{num:02d}-reality",
                "stage": 1,
                "page_number": num,
                "target": pkg["reality_target"],
                "prompt": pkg["assembled_reality_prompt"],
                "entity_references": pkg["labeled_reference_files"],
                "shared_composition": pkg["shared_composition"],
                "depends_on": None,
                "primary_composition_reference": None,
            })
        md_lines.append("")

    prompts_md_path = project_dir / "prompts.md"
    _atomic_write_text(prompts_md_path, "\n".join(md_lines))

    # Initialize any new asset keys in revision_state.json without overwriting existing approved states
    rev_state = _load_revision_state(project_dir)
    assets_state = rev_state.setdefault("assets", {})
    for req in required_images:
        k = req["key"]
        target_p = Path(req["target"])
        if k not in assets_state:
            assets_state[k] = {
                "status": "draft" if target_p.exists() else "missing",
                "current_version": 1 if target_p.exists() else 0,
                "versions": [],
                "identity_updated_flag": False,
            }
    _save_revision_state(project_dir, rev_state)

    return {
        "slug": slug,
        "storyboard_path": str(sb_path),
        "prompts_markdown_path": str(prompts_md_path),
        "validation_warnings": validation_warnings,
        "supports_reference_images": supports_reference_images,
        "capability_warnings": capability_warnings,
        "total_images_needed": len(required_images),
        "required_images": required_images,
    }


def ingest_book_images(
    slug: str,
    image_map: Dict[str, str],
    width: int = 1280,
    height: int = 960,
    is_draft: bool = False,
    note: str = "",
) -> Dict[str, Any]:
    """
    Crop/resize generated images to 4:3 landscape and save `.png` + `.webp` in `assets/`.
    Automatically archives any existing image into `assets/history/<key>/v<NNN>.png`
    so approved or prior versions can always be restored via `rollback_book_asset`.
    """
    slug = slugify(slug)
    project_dir = get_books_dir() / slug
    assets_dir = project_dir / "assets"
    history_root = assets_dir / "history"
    assets_dir.mkdir(parents=True, exist_ok=True)

    rev_state = _load_revision_state(project_dir)
    assets_state = rev_state.setdefault("assets", {})

    processed: List[Dict[str, Any]] = []
    for key, src_path_str in sorted(image_map.items()):
        src = Path(os.path.expanduser(src_path_str)).resolve()
        if not src.exists():
            raise FileNotFoundError(f"Missing source image for '{key}': {src}")

        stem = key[:-4] if key.endswith(".png") else key
        png_path = assets_dir / f"{stem}.png"
        webp_path = assets_dir / f"{stem}.webp"

        entry = assets_state.setdefault(stem, {
            "status": "missing",
            "current_version": 0,
            "versions": [],
            "identity_updated_flag": False,
        })
        versions: List[Dict[str, Any]] = entry.setdefault("versions", [])

        # If an image already exists on disk and wasn't archived yet as v1, archive it before overwriting
        key_hist_dir = history_root / stem
        key_hist_dir.mkdir(parents=True, exist_ok=True)
        if png_path.exists() and len(versions) == 0:
            v1_png = key_hist_dir / "v001.png"
            v1_webp = key_hist_dir / "v001.webp"
            shutil.copy2(png_path, v1_png)
            if webp_path.exists():
                shutil.copy2(webp_path, v1_webp)
            versions.append({
                "version": 1,
                "png": str(v1_png),
                "webp": str(v1_webp) if v1_webp.exists() else "",
                "timestamp": _utc_now_iso(),
                "is_draft": False,
                "note": "Initial version",
            })

        new_ver_num = len(versions) + 1
        ver_png = key_hist_dir / f"v{new_ver_num:03d}.png"
        ver_webp = key_hist_dir / f"v{new_ver_num:03d}.webp"

        with Image.open(src) as im:
            im = im.convert("RGB")
            fitted = ImageOps.fit(im, (width, height), method=Image.Resampling.LANCZOS)
            fitted.save(ver_png, format="PNG", optimize=True)
            fitted.save(ver_webp, format="WEBP", quality=84, method=6)

        # Atomically copy new version into active assets/
        tmp_png = assets_dir / f".{stem}.png.tmp.{os.getpid()}"
        tmp_webp = assets_dir / f".{stem}.webp.tmp.{os.getpid()}"
        shutil.copy2(ver_png, tmp_png)
        shutil.copy2(ver_webp, tmp_webp)
        os.replace(tmp_png, png_path)
        os.replace(tmp_webp, webp_path)

        ver_record = {
            "version": new_ver_num,
            "png": str(ver_png),
            "webp": str(ver_webp),
            "timestamp": _utc_now_iso(),
            "is_draft": bool(is_draft),
            "note": note or ("Draft thumbnail" if is_draft else f"Version {new_ver_num}"),
        }
        versions.append(ver_record)
        entry["current_version"] = new_ver_num
        entry["status"] = "draft" if is_draft else "generated"
        entry["identity_updated_flag"] = False

        processed.append({
            "key": stem,
            "version": new_ver_num,
            "status": entry["status"],
            "png": str(png_path),
            "webp": str(webp_path),
            "archived_png": str(ver_png),
        })

    _save_revision_state(project_dir, rev_state)

    return {
        "slug": slug,
        "assets_dir": str(assets_dir),
        "processed_count": len(processed),
        "processed": processed,
    }


# ---------------------------------------------------------------------------
# Targeted Single-Page Revision, Approval & Rollback (Issue #3)
# ---------------------------------------------------------------------------

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
) -> Dict[str, Any]:
    """
    Perform a targeted revision on a single page (`page_number`) without touching
    unrelated pages or regenerating approved illustrations.
    Scopes:
      - `text-only`: updates text/labels and immediately rebuilds the reader (`requires_image_generation: False`).
      - `reality-only`: updates reality prompt/composition for page N, marks `page-NN-reality` for regeneration,
                        and flags `page-NN-imaginary` as `check_alignment`.
      - `imaginary-only`: updates imaginary prompt/mappings for page N, keeping `page-NN-reality` locked as
                          the composition reference.
      - `paired-scene`: updates both reality and imaginary scenes for page N.
    """
    if scope not in VALID_REVISION_SCOPES:
        raise ValueError(f"scope must be one of {VALID_REVISION_SCOPES}")

    slug = slugify(slug)
    project_dir = get_books_dir() / slug
    sb_path = project_dir / "storyboard.json"
    if not sb_path.exists():
        raise FileNotFoundError(f"Missing storyboard.json in {project_dir}")

    storyboard = json.loads(sb_path.read_text(encoding="utf-8"))
    pages = storyboard.get("pages") or []
    target_page: Optional[Dict[str, Any]] = None
    for idx, p in enumerate(pages):
        if int(p.get("number", idx + 1)) == int(page_number):
            target_page = p
            break
    if target_page is None:
        raise KeyError(f"Page {page_number} not found in {sb_path}")

    # Apply text edits (allowed in any scope)
    if title is not None:
        target_page["title"] = title
    if paragraphs is not None:
        target_page["paragraphs"] = paragraphs
        if "text" in target_page:
            target_page["text"] = paragraphs
    if refrain is not None:
        target_page["refrain"] = refrain
    if flap_prompt is not None:
        target_page["flap_prompt"] = flap_prompt
    if imagination_label is not None:
        target_page["imagination_label"] = imagination_label
    if entity_ids is not None:
        target_page["entity_ids"] = entity_ids

    affected_assets: List[str] = []
    alignment_check_assets: List[str] = []
    r_key = f"page-{page_number:02d}-reality"
    i_key = f"page-{page_number:02d}-imaginary"

    if scope in ("reality-only", "paired-scene") and reality_prompt is not None:
        target_page["reality_prompt"] = reality_prompt
    if scope in ("imaginary-only", "paired-scene") and imaginary_prompt is not None:
        target_page["imaginary_prompt"] = imaginary_prompt
    if scope in ("reality-only", "imaginary-only", "paired-scene"):
        if shared_composition is not None:
            target_page["shared_composition"] = shared_composition
        if transformation_mappings is not None:
            target_page["transformation_mappings"] = transformation_mappings

    if scope == "reality-only":
        affected_assets = [r_key]
        if storyboard.get("mode", "lift-the-flap") == "lift-the-flap":
            alignment_check_assets = [i_key]
    elif scope == "imaginary-only":
        affected_assets = [i_key]
    elif scope == "paired-scene":
        affected_assets = [r_key]
        if storyboard.get("mode", "lift-the-flap") == "lift-the-flap":
            affected_assets.append(i_key)

    # Save updated storyboard & re-assemble prompts.md
    sb_res = save_storyboard(slug, storyboard)

    # Update revision_state.json for affected assets only
    rev_state = _load_revision_state(project_dir)
    if revision_note:
        rev_state.setdefault("page_notes", {})[str(page_number)] = revision_note
    rev_state.setdefault("revision_log", []).append({
        "timestamp": _utc_now_iso(),
        "page_number": page_number,
        "scope": scope,
        "affected_assets": affected_assets,
        "note": revision_note,
    })

    assets_state = rev_state.setdefault("assets", {})
    for akey in affected_assets:
        entry = assets_state.setdefault(akey, {"status": "missing", "current_version": 0, "versions": []})
        entry["status"] = "needs_revision"
    for akey in alignment_check_assets:
        entry = assets_state.setdefault(akey, {"status": "missing", "current_version": 0, "versions": []})
        if entry.get("status") == "approved":
            entry["status"] = "check_alignment"
    _save_revision_state(project_dir, rev_state)

    # If text-only (or if reader already exists), atomically rebuild reader immediately
    rebuilt_reader = None
    if scope == "text-only" or (project_dir / "index.html").exists():
        rebuilt_reader = publish_book(slug, serve_local=False, deploy_static=False, strict_assets=False)

    tasks_for_affected = [
        req for req in sb_res["required_images"] if req["key"] in affected_assets
    ]

    return {
        "slug": slug,
        "page_number": page_number,
        "scope": scope,
        "requires_image_generation": len(affected_assets) > 0,
        "affected_assets": affected_assets,
        "alignment_check_assets": alignment_check_assets,
        "generation_tasks": tasks_for_affected,
        "rebuilt_reader": rebuilt_reader,
    }


def approve_book_assets(
    slug: str,
    asset_keys: Optional[List[str]] = None,
    approve_storyboard: Optional[bool] = None,
    note: str = "",
) -> Dict[str, Any]:
    """Mark storyboard and/or specific illustration assets (`cover`, `page-01-reality`, ...) as approved."""
    slug = slugify(slug)
    project_dir = get_books_dir() / slug
    rev_state = _load_revision_state(project_dir)

    if approve_storyboard is not None:
        rev_state["storyboard_approved"] = bool(approve_storyboard)

    assets_state = rev_state.setdefault("assets", {})
    approved_list: List[str] = []
    target_keys = asset_keys if asset_keys is not None else list(assets_state.keys())
    for k in target_keys:
        entry = assets_state.setdefault(k, {"status": "missing", "current_version": 0, "versions": []})
        entry["status"] = "approved"
        entry["identity_updated_flag"] = False
        if note:
            entry["approval_note"] = note
        approved_list.append(k)

    _save_revision_state(project_dir, rev_state)
    return {
        "slug": slug,
        "storyboard_approved": rev_state["storyboard_approved"],
        "approved_assets": approved_list,
        "revision_state": rev_state,
    }


def rollback_book_asset(
    slug: str,
    asset_key: str,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Restore a previous archived version of `asset_key` (e.g., `page-01-reality`)
    from `assets/history/<asset_key>/` and atomically rebuild the book reader.
    """
    slug = slugify(slug)
    project_dir = get_books_dir() / slug
    assets_dir = project_dir / "assets"
    stem = asset_key[:-4] if asset_key.endswith(".png") else asset_key

    rev_state = _load_revision_state(project_dir)
    entry = (rev_state.get("assets") or {}).get(stem)
    if not entry or not entry.get("versions"):
        raise KeyError(f"No version history found for asset '{stem}' in {project_dir}")

    versions: List[Dict[str, Any]] = entry["versions"]
    if version is None:
        if len(versions) < 2:
            target_ver = versions[-1]
        else:
            target_ver = versions[-2]
    else:
        matched = [v for v in versions if int(v.get("version", 0)) == int(version)]
        if not matched:
            raise KeyError(f"Version {version} not found for asset '{stem}'")
        target_ver = matched[0]

    src_png = Path(target_ver["png"])
    src_webp = Path(target_ver["webp"]) if target_ver.get("webp") else src_png.with_suffix(".webp")
    if not src_png.exists():
        raise FileNotFoundError(f"Archived image missing on disk: {src_png}")

    dest_png = assets_dir / f"{stem}.png"
    dest_webp = assets_dir / f"{stem}.webp"
    tmp_png = assets_dir / f".{stem}.png.tmp.{os.getpid()}"
    shutil.copy2(src_png, tmp_png)
    os.replace(tmp_png, dest_png)

    if src_webp.exists():
        tmp_webp = assets_dir / f".{stem}.webp.tmp.{os.getpid()}"
        shutil.copy2(src_webp, tmp_webp)
        os.replace(tmp_webp, dest_webp)

    entry["current_version"] = int(target_ver["version"])
    entry["status"] = "approved"
    _save_revision_state(project_dir, rev_state)

    rebuilt = None
    if (project_dir / "storyboard.json").exists():
        rebuilt = publish_book(slug, serve_local=False, deploy_static=False, strict_assets=False)

    return {
        "slug": slug,
        "asset_key": stem,
        "restored_version": entry["current_version"],
        "png": str(dest_png),
        "webp": str(dest_webp),
        "rebuilt_reader": rebuilt,
    }


def get_revision_status(slug: str) -> Dict[str, Any]:
    """Return the full revision, version history, and approval state for a book."""
    slug = slugify(slug)
    project_dir = get_books_dir() / slug
    return _load_revision_state(project_dir)


# ---------------------------------------------------------------------------
# Storyboard & Flap Alignment Contact-Sheet Preview (`preview.html` — Issues #2, #5 & #9)
# ---------------------------------------------------------------------------

def generate_book_preview(slug: str) -> Dict[str, Any]:
    """
    Generate an interactive HTML contact-sheet preview (`<project_dir>/preview.html`)
    that works before any final artwork exists (text-first mode) or with draft/final
    thumbnails, including a Reality↔Imagination Overlay Alignment Inspector, review checklist,
    and a scannable Local Wi-Fi QR code for iPad/phone testing.
    """
    slug = slugify(slug)
    project_dir = get_books_dir() / slug
    sb_path = project_dir / "storyboard.json"
    if not sb_path.exists():
        raise FileNotFoundError(f"Missing storyboard.json in {project_dir}")

    storyboard = json.loads(sb_path.read_text(encoding="utf-8"))
    rev_state = _load_revision_state(project_dir)
    profile = get_studio_profile()
    art_style = storyboard.get("art_style") or profile["defaults"]["art_style"]
    mode = storyboard.get("mode", "lift-the-flap")
    title = storyboard.get("title", slug)
    subtitle = storyboard.get("subtitle", "")
    resolved_entities = _resolve_book_entities(project_dir, storyboard)
    assets_state = rev_state.get("assets") or {}

    local_port = int(profile["paths"]["local_server_port"] or 8765)
    lan_ip = _get_lan_ip()
    lan_book_url = f"http://{lan_ip}:{local_port}/{slug}/"
    qr_svg_path = project_dir / "qr-lan.svg"
    _atomic_write_text(qr_svg_path, render_qr_svg(lan_book_url, title=f"Scan to open {title}"))

    def _badge_html(status: str, is_draft: bool = False) -> str:
        st = "draft" if is_draft and status == "generated" else status
        colors = {
            "approved": ("#166534", "#dcfce7", "APPROVED"),
            "generated": ("#1e40af", "#dbeafe", "FINAL CANDIDATE"),
            "draft": ("#854d0e", "#fef9c3", "DRAFT THUMBNAIL"),
            "needs_revision": ("#991b1b", "#fee2e2", "NEEDS REVISION"),
            "check_alignment": ("#9a3412", "#ffedd5", "CHECK FLAP ALIGNMENT"),
            "missing": ("#475569", "#f1f5f9", "TEXT-FIRST (NO IMAGE YET)"),
        }
        fg, bg, label = colors.get(st, ("#334155", "#e2e8f0", st.upper()))
        return f'<span class="status-pill" style="color:{fg};background:{bg};">{html.escape(label)}</span>'

    def _thumb_html(stem: str, label: str, prompt_text: str) -> str:
        a_info = assets_state.get(stem) or {}
        ver_list = a_info.get("versions") or []
        cur_ver = a_info.get("current_version", 0)
        is_draft = bool(ver_list and ver_list[-1].get("is_draft"))
        status = a_info.get("status") or ("generated" if (project_dir / f"assets/{stem}.png").exists() else "missing")
        if (project_dir / f"assets/{stem}.webp").exists():
            img_tag = f'<img src="assets/{stem}.webp?v={int(time.time())}" alt="{html.escape(label)}" class="thumb-img {'is-draft-img' if is_draft else ''}" />'
        elif (project_dir / f"assets/{stem}.png").exists():
            img_tag = f'<img src="assets/{stem}.png?v={int(time.time())}" alt="{html.escape(label)}" class="thumb-img {'is-draft-img' if is_draft else ''}" />'
        else:
            img_tag = f'<div class="thumb-placeholder"><span>📝 Text-First Preview</span><small>No image generated yet for <code>{html.escape(stem)}</code></small></div>'
        ver_badge = f"<small>v{cur_ver}</small>" if cur_ver else ""
        return f"""
        <div class="thumb-card">
          <div class="thumb-header">
            <strong>{html.escape(label)} (<code>{html.escape(stem)}</code>) {ver_badge}</strong>
            {_badge_html(status, is_draft)}
          </div>
          <div class="thumb-frame">{img_tag}</div>
          <details class="prompt-details">
            <summary>Assembled Prompt</summary>
            <pre>{html.escape(prompt_text)}</pre>
          </details>
        </div>
        """

    cast_cards: List[str] = []
    for eid, ent in resolved_entities.items():
        refs_str = ", ".join(html.escape(r["label"]) for r in (ent.get("book_references") or [])) or "Text-only"
        cast_cards.append(f"""
        <div class="cast-chip">
          <div><strong>{html.escape(ent.get('name', eid))}</strong> <code>{html.escape(eid)}</code> ({html.escape(ent.get('kind', ''))})</div>
          <div class="cast-meta">{html.escape(ent.get('age_or_size', ''))} — {html.escape(ent.get('appearance', ''))}</div>
          <div class="cast-meta"><strong>Reality:</strong> {html.escape(ent.get('reality_description') or ent.get('signature_outfit') or '—')}</div>
          <div class="cast-meta"><strong>Imaginary:</strong> {html.escape(ent.get('imaginary_transformation') or 'Same as reality')}</div>
          <div class="cast-meta"><strong>Refs:</strong> {refs_str}</div>
        </div>
        """)

    page_sections: List[str] = []
    for p in storyboard.get("pages") or []:
        num = int(p.get("number", 1))
        pkg = _assemble_page_prompts(p, mode, resolved_entities, project_dir, art_style)
        paragraphs = p.get("paragraphs") or p.get("text") or []
        if isinstance(paragraphs, str):
            paragraphs = [paragraphs]
        text_html = "".join(f"<p>{html.escape(line)}</p>" for line in paragraphs)
        refrain_html = f'<div class="refrain-call">Refrain: {html.escape(p["refrain"])}</div>' if p.get("refrain") else ""
        note_str = (rev_state.get("page_notes") or {}).get(str(num), "")
        note_html = f'<div class="rev-note">📌 <strong>Revision Note:</strong> {html.escape(note_str)}</div>' if note_str else ""

        r_stem = f"page-{num:02d}-reality"
        i_stem = f"page-{num:02d}-imaginary"
        thumbs_html = _thumb_html(r_stem, "Reality Layer (Top Flap)", pkg["assembled_reality_prompt"])
        overlay_inspector_html = ""
        if mode == "lift-the-flap":
            thumbs_html += _thumb_html(i_stem, "Imaginary Layer (Under Flap)", pkg["assembled_imaginary_prompt"])
            r_exists = (project_dir / f"assets/{r_stem}.png").exists()
            i_exists = (project_dir / f"assets/{i_stem}.png").exists()
            if r_exists and i_exists:
                overlay_inspector_html = f"""
                <div class="alignment-inspector">
                  <div class="inspector-header">
                    <strong>🔍 Interactive Flap Reveal Alignment Inspector</strong>
                    <label>Scrub Reality ↔ Imaginary Opacity:
                      <input type="range" min="0" max="100" value="50" oninput="this.closest('.alignment-inspector').querySelector('.overlay-imag').style.opacity = this.value / 100" />
                    </label>
                  </div>
                  <div class="overlay-stage">
                    <img src="assets/{r_stem}.png?v={int(time.time())}" alt="Reality base" class="overlay-real" />
                    <img src="assets/{i_stem}.png?v={int(time.time())}" alt="Imaginary overlay" class="overlay-imag" style="opacity:0.5;" />
                  </div>
                </div>
                """

        mappings_rows = "".join(
            f"<tr><td><code>{html.escape(m.get('entity_id', '—'))}</code></td>"
            f"<td>{html.escape(m.get('spatial_anchor', '—'))}</td>"
            f"<td>{html.escape(m.get('reality_element', ''))}</td>"
            f"<td>➡️ {html.escape(m.get('imaginary_element', ''))}</td></tr>"
            for m in (pkg["transformation_mappings"] or [])
        )
        mappings_table = (
            f"""<table class="mapping-table">
              <thead><tr><th>Entity ID</th><th>Spatial Anchor</th><th>Reality Element</th><th>Imaginary Transformation</th></tr></thead>
              <tbody>{mappings_rows}</tbody>
            </table>"""
            if mappings_rows
            else ""
        )

        comp = pkg["shared_composition"] or {}
        comp_summary = (
            f"<div class='comp-box'><strong>Shared Composition Lock:</strong> "
            f"Camera: {html.escape(comp.get('camera_angle', '—'))} | "
            f"Horizon: {html.escape(comp.get('horizon_line', '—'))} | "
            f"Placement: {html.escape(comp.get('focal_subject_placement', '—'))} | "
            f"Pose: {html.escape(comp.get('character_pose', '—'))}</div>"
            if comp
            else ""
        )

        page_sections.append(f"""
        <section class="page-preview-card" id="page-{num:02d}">
          <div class="page-preview-header">
            <h2>Page {num:02d}: {html.escape(p.get('title', f'Page {num}'))}</h2>
            <span class="entity-list">Entities: {', '.join(f'<code>{html.escape(e["entity_id"])}</code>' for e in pkg['entity_assignments']) or '—'}</span>
          </div>
          {note_html}
          <div class="story-copy-box">
            {text_html}
            {refrain_html}
          </div>
          {comp_summary}
          {mappings_table}
          <div class="thumbs-grid">{thumbs_html}</div>
          {overlay_inspector_html}
          <div class="checklist-row">
            <span><strong>Review Checklist:</strong></span>
            <label><input type="checkbox" /> Pacing & read-aloud text</label>
            <label><input type="checkbox" /> Character & prop ID accuracy</label>
            <label><input type="checkbox" /> Reality ↔ Imaginary pose & horizon alignment</label>
          </div>
        </section>
        """)

    sb_status_badge = _badge_html("approved" if rev_state.get("storyboard_approved") else "draft")
    cover_prompt = (storyboard.get("cover") or {}).get("prompt") or storyboard.get("cover_prompt") or ""
    cover_thumb = _thumb_html("cover", "Book Cover", cover_prompt)

    preview_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Storyboard & Alignment Preview — {html.escape(title)}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; margin: 0; padding: 24px; background: #f8fafc; color: #0f172a; }}
    .container {{ max-width: 1200px; margin: 0 auto; display: grid; gap: 24px; }}
    header {{ background: #fff; padding: 20px 24px; border-radius: 16px; box-shadow: 0 4px 16px rgba(15,23,42,0.06); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }}
    h1 {{ margin: 0 0 6px; font-size: 1.6rem; }}
    .status-pill {{ display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 0.75rem; font-weight: 800; letter-spacing: 0.04em; }}
    .qr-banner {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 16px; padding: 16px 20px; display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }}
    .qr-banner img {{ width: 96px; height: 96px; border-radius: 8px; border: 1px solid #cbd5e1; }}
    .cast-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }}
    .cast-chip {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px; font-size: 0.85rem; display: grid; gap: 4px; }}
    .cast-meta {{ color: #475569; }}
    .page-preview-card {{ background: #fff; border-radius: 16px; padding: 20px; box-shadow: 0 4px 16px rgba(15,23,42,0.06); display: grid; gap: 14px; border: 1px solid #e2e8f0; }}
    .page-preview-header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px; }}
    .page-preview-header h2 {{ margin: 0; font-size: 1.25rem; }}
    .story-copy-box {{ background: #fffbeb; border-left: 4px solid #f59e0b; padding: 12px 16px; border-radius: 8px; font-size: 1.05rem; }}
    .story-copy-box p {{ margin: 4px 0; }}
    .refrain-call {{ font-weight: 800; color: #d97706; margin-top: 6px; }}
    .rev-note {{ background: #fef2f2; border: 1px solid #fecaca; color: #991b1b; padding: 10px 14px; border-radius: 8px; font-size: 0.9rem; }}
    .comp-box {{ background: #f1f5f9; padding: 10px 14px; border-radius: 8px; font-size: 0.86rem; color: #334155; }}
    .mapping-table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
    .mapping-table th, .mapping-table td {{ border: 1px solid #e2e8f0; padding: 8px 10px; text-align: left; }}
    .mapping-table th {{ background: #f8fafc; }}
    .thumbs-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
    .thumb-card {{ border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px; background: #f8fafc; display: grid; gap: 8px; }}
    .thumb-header {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 0.85rem; }}
    .thumb-frame {{ aspect-ratio: 4 / 3; background: #e2e8f0; border-radius: 8px; overflow: hidden; display: flex; align-items: center; justify-content: center; }}
    .thumb-img {{ width: 100%; height: 100%; object-fit: cover; }}
    .thumb-img.is-draft-img {{ outline: 4px dashed #eab308; outline-offset: -4px; }}
    .thumb-placeholder {{ text-align: center; padding: 20px; color: #64748b; display: grid; gap: 6px; }}
    .prompt-details summary {{ cursor: pointer; font-size: 0.8rem; font-weight: 700; color: #475569; }}
    .prompt-details pre {{ white-space: pre-wrap; font-size: 0.76rem; background: #fff; padding: 8px; border-radius: 6px; border: 1px solid #e2e8f0; max-height: 160px; overflow-y: auto; }}
    .alignment-inspector {{ border: 1px solid #cbd5e1; border-radius: 12px; padding: 12px; background: #f1f5f9; display: grid; gap: 10px; }}
    .inspector-header {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; font-size: 0.88rem; }}
    .overlay-stage {{ position: relative; max-width: 520px; aspect-ratio: 4 / 3; border-radius: 8px; overflow: hidden; margin: 0 auto; width: 100%; background: #000; }}
    .overlay-stage img {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }}
    .checklist-row {{ display: flex; gap: 16px; flex-wrap: wrap; align-items: center; font-size: 0.85rem; color: #334155; padding-top: 6px; border-top: 1px dashed #e2e8f0; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>Storyboard & Flap Alignment Contact Sheet: {html.escape(title)}</h1>
        <div>{html.escape(subtitle)} — Mode: <code>{html.escape(mode)}</code></div>
      </div>
      <div>Storyboard Approval: {sb_status_badge}</div>
    </header>
    <section class="qr-banner">
      <img src="qr-lan.svg" alt="Local Wi-Fi QR Code" />
      <div>
        <strong>📱 Open on iPad or Phone over Local Wi-Fi</strong>
        <div>Scan with the iPad/iPhone Camera app to open in Mobile Safari with full lift-the-flap touch support:</div>
        <div><a href="{html.escape(lan_book_url)}"><code>{html.escape(lan_book_url)}</code></a></div>
      </div>
    </section>
    <section>
      <h3>Assigned Cast & Prop Identities</h3>
      <div class="cast-grid">{''.join(cast_cards) or '<div>No structured entities assigned.</div>'}</div>
    </section>
    <section class="page-preview-card">
      <h2>Cover</h2>
      <div class="thumbs-grid">{cover_thumb}</div>
    </section>
    {''.join(page_sections)}
  </div>
</body>
</html>
"""
    preview_path = project_dir / "preview.html"
    _atomic_write_text(preview_path, preview_doc)
    return {
        "slug": slug,
        "preview_html": str(preview_path),
        "lan_qr_svg_path": str(qr_svg_path),
        "lan_book_url": lan_book_url,
        "storyboard_approved": rev_state.get("storyboard_approved", False),
        "page_count": len(storyboard.get("pages") or []),
    }


# ---------------------------------------------------------------------------
# Reader Build & Local Device Hosting
# ---------------------------------------------------------------------------

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
                or p.get("imaginary_caption")
                or p.get("imaginaryCaption")
                or ("✨ Imaginary World" if has_flap else "")
            ),
            "flapHint": (
                p.get("flap_prompt")
                or p.get("flap_hint")
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
        "kicker": end_info.get("kicker") or storyboard.get("end_kicker") or "HOORAY!",
        "title": end_info.get("title") or "The End",
        "bedtimeKicker": end_info.get("bedtime_kicker") or "🌙 GOODNIGHT",
        "bedtimeTitle": end_info.get("bedtime_title") or "Sweet Dreams",
        "bedtimeSubtitle": (
            end_info.get("bedtime_subtitle")
            or end_info.get("subtitle")
            or storyboard.get("end_subtitle")
            or f"Time to close our eyes and drift off to sleep. Goodnight!"
        ),
        "hasFlap": False,
        "text": [
            end_info.get("subtitle")
            or storyboard.get("end_subtitle")
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
    lan_base = f"http://{lan_ip}:{port}"
    return {
        "running": _is_port_open(port),
        "port": port,
        "books_dir": str(books_dir),
        "localhost_base": f"http://localhost:{port}",
        "lan_base": lan_base,
        "lan_qr_ascii": render_qr_ascii(lan_base),
    }


def publish_book(
    slug: str,
    serve_local: bool = True,
    deploy_static: bool = True,
    port: Optional[int] = None,
    web_root_override: Optional[str] = None,
    base_url_override: Optional[str] = None,
    bedtime_mode: Optional[bool] = None,
    strict_assets: bool = True,
) -> Dict[str, Any]:
    """
    Validate storyboard and required image assets, then atomically build:
      1. A self-contained single-file HTML book (`<slug>.html`) with all CSS, JS, and images inlined.
      2. A standard multi-file web reader (`index.html`, `styles.css`, `script.js`, `assets/`).
      3. By default, host locally on the user's device (`http://localhost:<port>/<slug>/` and LAN URL)
         and generate a scannable Local Wi-Fi QR code (`<project_dir>/qr-lan.svg` + `lan_qr_ascii`).
      4. Optionally copy to `PUBLISH_WEB_ROOT` if configured in `.env`.
    """
    slug = slugify(slug)
    books_dir = get_books_dir()
    project_dir = books_dir / slug
    sb_path = project_dir / "storyboard.json"
    if not sb_path.exists():
        raise FileNotFoundError(f"Missing storyboard.json in {project_dir}")

    profile = get_studio_profile()
    raw_storyboard = json.loads(sb_path.read_text(encoding="utf-8"))

    # Validate storyboard schema & required image assets BEFORE overwriting any published reader files
    val_res = validate_and_normalize_storyboard(
        raw_storyboard,
        project_dir=project_dir,
        require_assets=strict_assets,
    )
    storyboard = val_res["normalized_storyboard"]

    title = storyboard.get("title", slug)
    subtitle = storyboard.get("subtitle", "An Interactive Landscape Picture Book")
    kicker = storyboard.get("kicker", "Interactive Bedtime Book")
    story_pages = storyboard.get("pages") or []
    is_bedtime = (
        bool(bedtime_mode)
        if bedtime_mode is not None
        else bool(storyboard.get("bedtime_mode", profile["defaults"].get("bedtime_mode", False)))
    )

    index_tpl = (TEMPLATES_READER_DIR / "index.html").read_text(encoding="utf-8")
    styles_css = (TEMPLATES_READER_DIR / "styles.css").read_text(encoding="utf-8")
    script_tpl = (TEMPLATES_READER_DIR / "script.js").read_text(encoding="utf-8")

    base_html = (
        index_tpl.replace("__BOOK_TITLE__", html.escape(title))
        .replace("__BOOK_SUBTITLE__", html.escape(subtitle))
        .replace("__BOOK_KICKER__", html.escape(kicker))
        .replace("__BEDTIME_MODE_DEFAULT__", "true" if is_bedtime else "false")
    )

    # 1. Atomically build standard multi-file reader in <project_dir>/
    pages_external = _build_reader_pages_js(storyboard, project_dir, inline_data_uris=False)
    rendered_script_external = re.sub(
        r"/\*\s*__TOTAL_STORY_PAGES__\s*\*/\s*\d+",
        str(len(story_pages)),
        script_tpl,
    ).replace(
        "/* __BOOK_PAGES_JSON__ */ []",
        json.dumps(pages_external, indent=2, ensure_ascii=False),
    )

    _atomic_write_text(project_dir / "index.html", base_html)
    _atomic_write_text(project_dir / "styles.css", styles_css)
    _atomic_write_text(project_dir / "script.js", rendered_script_external)

    # 2. Atomically build self-contained SINGLE-FILE HTML book (<slug>.html)
    pages_inlined = _build_reader_pages_js(storyboard, project_dir, inline_data_uris=True)
    rendered_script_inlined = re.sub(
        r"/\*\s*__TOTAL_STORY_PAGES__\s*\*/\s*\d+",
        str(len(story_pages)),
        script_tpl,
    ).replace(
        "/* __BOOK_PAGES_JSON__ */ []",
        json.dumps(pages_inlined, ensure_ascii=False),
    )

    single_file_html_content = re.sub(
        r'<link\s+rel="stylesheet"\s+href="[^"]*styles\.css[^"]*"\s*/?>',
        lambda _: f"<style>\n{styles_css}\n</style>",
        base_html,
    )
    single_file_html_content = re.sub(
        r'<script\s+src="[^"]*script\.js[^"]*"></script>',
        lambda _: f"<script>\n{rendered_script_inlined}\n</script>",
        single_file_html_content,
    )

    standalone_file_in_project = project_dir / f"{slug}.html"
    standalone_file_in_root = books_dir / f"{slug}.html"
    _atomic_write_text(standalone_file_in_project, single_file_html_content)
    _atomic_write_text(standalone_file_in_root, single_file_html_content)

    paths_cfg = profile["paths"]
    chosen_port = int(port or paths_cfg["local_server_port"] or 8765)
    lan_ip = _get_lan_ip()
    lan_url = f"http://{lan_ip}:{chosen_port}/{slug}/"
    qr_svg_path = project_dir / "qr-lan.svg"
    _atomic_write_text(qr_svg_path, render_qr_svg(lan_url, title=f"Scan to read {title}"))
    lan_qr_ascii = render_qr_ascii(lan_url)

    result: Dict[str, Any] = {
        "slug": slug,
        "bedtime_mode_default": is_bedtime,
        "validation_warnings": val_res["warnings"],
        "workspace_dir": str(project_dir),
        "single_file_html": str(standalone_file_in_project),
        "single_file_html_copy": str(standalone_file_in_root),
        "file_url": f"file://{standalone_file_in_project}",
        "local_url": None,
        "local_single_file_url": None,
        "lan_url": lan_url,
        "lan_single_file_url": f"http://{lan_ip}:{chosen_port}/{slug}.html",
        "lan_qr_svg_path": str(qr_svg_path),
        "lan_qr_ascii": lan_qr_ascii,
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

    # 4. Optional Custom Static Web Root Copy
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
        for fname in ("index.html", "styles.css", "script.js", f"{slug}.html", "qr-lan.svg"):
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
        description="Bedtime Book Studio — Onboarding, Persistent Identities & Picture Book Builder"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("onboard", help="Run the interactive terminal onboarding wizard")
    sub.add_parser("status", help="Show onboarding status and current .env profile as JSON")
    sub.add_parser("profile", help="Print the active studio profile from .env")
    sub.add_parser("list", help="List all books in BOOKS_OUTPUT_DIR")

    p_ids = sub.add_parser("identities", help="List persistent character, pet, and prop identities")
    p_ids.add_argument("--kind", choices=list(VALID_ENTITY_KINDS), default=None)

    p_uid = sub.add_parser("upsert-identity", help="Create or update a character, pet, or prop identity")
    p_uid.add_argument("--id", dest="entity_id", default=None, help="Stable ID (e.g. char-leo, pet-biscuit)")
    p_uid.add_argument("--name", required=True)
    p_uid.add_argument("--kind", choices=list(VALID_ENTITY_KINDS), default="supporting_character")
    p_uid.add_argument("--age-or-size", default=None)
    p_uid.add_argument("--appearance", default=None)
    p_uid.add_argument("--outfit", default=None)
    p_uid.add_argument("--reality", default=None, help="How this entity/prop appears in real life")
    p_uid.add_argument("--imaginary", default=None, help="How this entity/prop transforms under the flap")
    p_uid.add_argument("--photos", nargs="*", default=None)
    p_uid.add_argument("--labels", nargs="*", default=None)
    p_uid.add_argument("--approved-sheet", default=None)

    p_ref = sub.add_parser("identity-ref", help="Add, update, enable/disable, or remove an entity reference photo")
    p_ref.add_argument("--entity-id", required=True)
    p_ref.add_argument("--action", choices=["add", "update", "remove"], required=True)
    p_ref.add_argument("--ref-id", default=None)
    p_ref.add_argument("--photo", default=None)
    p_ref.add_argument("--label", default=None)
    p_ref.add_argument("--active", choices=["true", "false"], default=None)
    p_ref.add_argument("--sheet", choices=["true", "false"], default=None)

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
    p_cfg.add_argument("--bedtime-mode", choices=["true", "false"], default=None)
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
    p_init.add_argument("--cast-ids", nargs="*", default=None, help="Entity IDs to include in this book")
    p_init.add_argument("--overrides-json", default=None, help="JSON dict of per-book entity overrides")
    p_init.add_argument("--refs", nargs="*", default=None)
    p_init.add_argument("--pages", type=int, default=None)
    p_init.add_argument("--bedtime-mode", action="store_true", default=None)

    p_sb = sub.add_parser("storyboard", help="Validate storyboard.json and generate prompts.md")
    p_sb.add_argument("--slug", required=True)
    p_sb.add_argument("--file", required=True, help="Path to storyboard JSON file")
    p_sb.add_argument("--no-ref-support", action="store_true", help="Indicate image tool cannot take image refs")

    p_val = sub.add_parser("validate", help="Validate storyboard.json schema and optionally required assets")
    p_val.add_argument("--slug", required=True)
    p_val.add_argument("--require-assets", action="store_true", help="Also verify all required PNG/WebP assets exist")

    p_prev = sub.add_parser("preview", help="Generate HTML contact-sheet preview and alignment inspector")
    p_prev.add_argument("--slug", required=True)

    p_ing = sub.add_parser("ingest", help="Normalize and convert generated images into assets/ with history")
    p_ing.add_argument("--slug", required=True)
    p_ing.add_argument("--map-json", required=True, help="JSON string or path to JSON file mapping key->path")
    p_ing.add_argument("--draft", action="store_true", help="Mark ingested images as draft thumbnails")
    p_ing.add_argument("--note", default="", help="Version note")

    p_rev = sub.add_parser("revise", help="Revise a single page while preserving unrelated approved work")
    p_rev.add_argument("--slug", required=True)
    p_rev.add_argument("--page", type=int, required=True, help="1-based page number to revise")
    p_rev.add_argument("--scope", choices=list(VALID_REVISION_SCOPES), required=True)
    p_rev.add_argument("--title", default=None)
    p_rev.add_argument("--paragraphs", nargs="*", default=None)
    p_rev.add_argument("--refrain", default=None)
    p_rev.add_argument("--flap-prompt", default=None)
    p_rev.add_argument("--imagination-label", default=None)
    p_rev.add_argument("--reality-prompt", default=None)
    p_rev.add_argument("--imaginary-prompt", default=None)
    p_rev.add_argument("--note", default="")

    p_app = sub.add_parser("approve", help="Approve storyboard and/or specific illustration assets")
    p_app.add_argument("--slug", required=True)
    p_app.add_argument("--keys", nargs="*", default=None, help="Asset keys to approve (e.g. cover page-01-reality)")
    p_app.add_argument("--storyboard", action="store_true", help="Mark storyboard as approved")
    p_app.add_argument("--note", default="")

    p_rb = sub.add_parser("rollback", help="Restore a previous archived version of an asset")
    p_rb.add_argument("--slug", required=True)
    p_rb.add_argument("--key", required=True, help="Asset key (e.g. page-01-reality)")
    p_rb.add_argument("--version", type=int, default=None, help="Version number to restore (defaults to previous)")

    p_pub = sub.add_parser(
        "publish",
        help="Build single-file HTML book (<slug>.html) + standard reader and host locally on this device",
    )
    p_pub.add_argument("--slug", required=True)
    p_pub.add_argument("--no-local-server", action="store_true", help="Do not auto-start the local device HTTP server")
    p_pub.add_argument("--no-static", action="store_true", help="Skip copying to PUBLISH_WEB_ROOT even if set")
    p_pub.add_argument("--allow-missing-assets", action="store_true", help="Build reader even if some image assets are missing")
    p_pub.add_argument("--bedtime-mode", choices=["true", "false"], default=None)
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
    elif args.cmd == "identities":
        print(json.dumps(list_identities(kind=args.kind), indent=2))
    elif args.cmd == "upsert-identity":
        res = upsert_identity(
            entity_id=args.entity_id,
            name=args.name,
            kind=args.kind,
            age_or_size=args.age_or_size,
            appearance=args.appearance,
            signature_outfit=args.outfit,
            reality_description=args.reality,
            imaginary_transformation=args.imaginary,
            reference_photos=args.photos,
            reference_labels=args.labels,
            approved_sheet_path=args.approved_sheet,
        )
        print(json.dumps(res, indent=2))
    elif args.cmd == "identity-ref":
        res = manage_identity_reference(
            entity_id=args.entity_id,
            action=args.action,
            ref_id=args.ref_id,
            photo_path=args.photo,
            label=args.label,
            active=(args.active == "true") if args.active is not None else None,
            is_character_sheet=(args.sheet == "true") if args.sheet is not None else None,
        )
        print(json.dumps(res, indent=2))
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
            default_bedtime_mode=(args.bedtime_mode == "true") if args.bedtime_mode is not None else None,
            default_page_count=args.pages,
            books_output_dir=args.books_dir,
            local_server_port=args.port,
            publish_web_root=args.web_root,
            publish_base_url=args.base_url,
        )
        print(json.dumps(res, indent=2))
    elif args.cmd == "init":
        overrides = json.loads(args.overrides_json) if args.overrides_json else None
        res = init_book_project(
            slug=args.slug,
            title=args.title,
            idea=args.idea,
            mode=args.mode,
            character_name=args.character_name,
            character_description=args.character_description,
            reference_images=args.refs,
            page_count=args.pages,
            cast_ids=args.cast_ids,
            entity_overrides=overrides,
            bedtime_mode=args.bedtime_mode,
        )
        print(json.dumps(res, indent=2))
    elif args.cmd == "storyboard":
        sb_data = json.loads(Path(args.file).read_text(encoding="utf-8"))
        res = save_storyboard(
            args.slug,
            sb_data,
            supports_reference_images=not args.no_ref_support,
        )
        print(json.dumps(res, indent=2))
    elif args.cmd == "validate":
        res = validate_book_storyboard(args.slug, require_assets=args.require_assets)
        print(json.dumps(res, indent=2))
        if not res["valid"]:
            sys.exit(1)
    elif args.cmd == "preview":
        res = generate_book_preview(args.slug)
        print(json.dumps(res, indent=2))
    elif args.cmd == "ingest":
        raw_map = args.map_json
        if Path(raw_map).exists():
            image_map = json.loads(Path(raw_map).read_text(encoding="utf-8"))
        else:
            image_map = json.loads(raw_map)
        res = ingest_book_images(
            args.slug,
            image_map,
            is_draft=args.draft,
            note=args.note,
        )
        print(json.dumps(res, indent=2))
    elif args.cmd == "revise":
        res = revise_book_page(
            slug=args.slug,
            page_number=args.page,
            scope=args.scope,
            title=args.title,
            paragraphs=args.paragraphs,
            refrain=args.refrain,
            flap_prompt=args.flap_prompt,
            imagination_label=args.imagination_label,
            reality_prompt=args.reality_prompt,
            imaginary_prompt=args.imaginary_prompt,
            revision_note=args.note,
        )
        print(json.dumps(res, indent=2))
    elif args.cmd == "approve":
        res = approve_book_assets(
            slug=args.slug,
            asset_keys=args.keys,
            approve_storyboard=True if args.storyboard else None,
            note=args.note,
        )
        print(json.dumps(res, indent=2))
    elif args.cmd == "rollback":
        res = rollback_book_asset(
            slug=args.slug,
            asset_key=args.key,
            version=args.version,
        )
        print(json.dumps(res, indent=2))
    elif args.cmd == "publish":
        bm = (args.bedtime_mode == "true") if args.bedtime_mode is not None else None
        res = publish_book(
            slug=args.slug,
            serve_local=not args.no_local_server,
            deploy_static=not args.no_static,
            port=args.port,
            web_root_override=args.web_root,
            base_url_override=args.base_url,
            bedtime_mode=bm,
            strict_assets=not args.allow_missing_assets,
        )
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
