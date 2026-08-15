"""The running record, kept as a Galaxy Page used directly."""

import logging

logger = logging.getLogger(__name__)

# Galaxy slugs are lowercase alphanumerics and hyphens.
SLUG_PREFIX = "olite"

STARTER = """## Record

This page is the running record for this analysis, maintained by olite. It holds the
plan, what was executed, and what the results showed.

_No entries yet._
"""


def slug_for_history(history_id):
    return f"{SLUG_PREFIX}-{history_id}"


def title_for_history(history_id):
    return f"olite record ({history_id[:8]})"


async def _find_by_slug(g, slug):
    """The page with this slug, or None."""
    pages = await g.get("api/pages?limit=500") or []
    if not isinstance(pages, list):
        return None
    for page in pages:
        if isinstance(page, dict) and page.get("slug") == slug:
            return page
    return None


async def _notebook_resume(g, args):
    history_id = (args or {}).get("history_id")
    if not history_id:
        return {"error": "history_id is required to resume this history's record."}

    slug = slug_for_history(history_id)
    existing = await _find_by_slug(g, slug)

    if existing:
        page_id = existing.get("id")
        # `get_page` withholds content unless asked; the record is only useful read.
        full = await g.get(f"api/pages/{page_id}") or {}
        content = full.get("content") if isinstance(full, dict) else None
        return {
            "created": False,
            "page_id": page_id,
            "slug": slug,
            "title": existing.get("title"),
            "content": content or "",
        }

    created = await g.post(
        "api/pages",
        {
            "title": title_for_history(history_id),
            "slug": slug,
            "history_id": history_id,
            "content": STARTER,
        },
    )
    if not isinstance(created, dict) or not created.get("id"):
        return {"error": f"Could not create the record page for history {history_id}."}
    logger.info("created record page %s for history %s", created.get("id"), history_id)
    return {
        "created": True,
        "page_id": created.get("id"),
        "slug": slug,
        "title": created.get("title"),
        "content": STARTER,
    }


NOTEBOOK_RESUME = {
    "type": "function",
    "function": {
        "name": "notebook_resume",
        "description": (
            "Find or create THE record page for a history, and return its id and current "
            "content. The record is this analysis's durable log: the approved plan, what "
            "was executed, and what the results showed. Call this once, before writing "
            "anything to the record, so you attach to the existing page instead of "
            "starting a second one — the page is addressed by a fixed per-history slug, "
            "so a reload finds the same record. Write to it afterwards with "
            "update_page(page_id, content)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "history_id": {
                    "type": "string",
                    "description": "Encoded id of the history this analysis belongs to.",
                }
            },
            "required": ["history_id"],
        },
    },
}

# Creating the record is a write, so a read-only session is not offered the tool.
CAPABILITY = "write"
HANDLERS = {"notebook_resume": _notebook_resume}


def tool_schemas(manifest):
    return [NOTEBOOK_RESUME] if manifest.allows(CAPABILITY) else []


def get_handler(name):
    return HANDLERS.get(name)
