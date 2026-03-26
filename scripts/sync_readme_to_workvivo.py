#!/usr/bin/env python3

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def extract_title(markdown_text: str, readme_path: Path) -> str:
    for line in markdown_text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return readme_path.stem


def render_inline(text: str) -> str:
    escaped = html.escape(text.strip())
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return escaped


def markdown_to_html(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    blocks: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    list_type: str | None = None
    first_title_skipped = False

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            text = " ".join(part.strip() for part in paragraph if part.strip())
            if text:
                blocks.append(f"<p>{render_inline(text)}</p>")
            paragraph = []

    def flush_list() -> None:
        nonlocal list_items, list_type
        if list_items and list_type:
            items = "".join(f"<li>{render_inline(item)}</li>" for item in list_items)
            blocks.append(f"<{list_type}>{items}</{list_type}>")
        list_items = []
        list_type = None

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            flush_list()
            continue

        if stripped.startswith("# "):
            flush_paragraph()
            flush_list()
            if not first_title_skipped:
                first_title_skipped = True
                continue
            blocks.append(f"<p><strong>{render_inline(stripped[2:])}</strong></p>")
            continue

        heading_match = re.match(r"^(#{2,6})\s+(.*)$", stripped)
        if heading_match:
            flush_paragraph()
            flush_list()
            blocks.append(f"<p><strong>{render_inline(heading_match.group(2))}</strong></p>")
            continue

        ordered_match = re.match(r"^\d+\.\s+(.*)$", stripped)
        bullet_match = re.match(r"^[-*]\s+(.*)$", stripped)
        if ordered_match:
            flush_paragraph()
            if list_type not in (None, "ol"):
                flush_list()
            list_type = "ol"
            list_items.append(ordered_match.group(1))
            continue
        if bullet_match:
            flush_paragraph()
            if list_type not in (None, "ul"):
                flush_list()
            list_type = "ul"
            list_items.append(bullet_match.group(1))
            continue
        if list_type and list_items and raw_line.startswith(("  ", "\t")):
            list_items[-1] = f"{list_items[-1]} {stripped}"
            continue

        flush_list()
        paragraph.append(stripped)

    flush_paragraph()
    flush_list()
    return "\n".join(blocks)


def build_payload(readme_text: str, readme_path: Path) -> dict[str, str]:
    title = os.getenv("WORKVIVO_PAGE_TITLE", "").strip() or extract_title(
        readme_text, readme_path
    )
    subtitle = os.getenv("WORKVIVO_PAGE_SUBTITLE", "").strip() or "Mirrored from README.md"

    return {
        "title": title,
        "subtitle": subtitle,
        "space_id": os.getenv("WORKVIVO_SPACE_ID", "23244").strip(),
        "html_content": markdown_to_html(readme_text),
        "is_draft": os.getenv("WORKVIVO_IS_DRAFT", "0").strip(),
    }


def update_page(
    api_base: str,
    page_id: str,
    token: str,
    organisation_id: str,
    payload: dict[str, str],
) -> None:
    encoded_payload = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{api_base.rstrip('/')}/pages/{page_id}",
        data=encoded_payload,
        method="PUT",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Workvivo-Id": organisation_id,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response_body = response.read().decode("utf-8")
            body = json.loads(response_body)
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(
            f"Workvivo request failed with status {exc.code}: {error_body}"
        ) from exc

    print(json.dumps(body, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mirror README.md content into a Workvivo page."
    )
    parser.add_argument(
        "--readme",
        default="README.md",
        help="Path to the Markdown file to mirror.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render the Workvivo payload locally without calling the API.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    readme_path = Path(args.readme)

    if not readme_path.exists():
        raise RuntimeError(f"Markdown source not found: {readme_path}")

    readme_text = readme_path.read_text(encoding="utf-8")
    payload = build_payload(readme_text, readme_path)

    if args.dry_run:
        preview = {
            "page_id": os.getenv("WORKVIVO_PAGE_ID", "76239").strip(),
            "payload": payload,
        }
        print(json.dumps(preview, indent=2))
        return 0

    token = require_env("WORKVIVO")
    organisation_id = require_env("WORKVIVO_ID")
    page_id = os.getenv("WORKVIVO_PAGE_ID", "76239").strip()
    api_base = os.getenv("WORKVIVO_API_BASE", "https://api.workvivo.com/v1").strip()

    update_page(api_base, page_id, token, organisation_id, payload)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
