"""The record: one Galaxy Page per history, found again rather than recreated."""

import asyncio

from olite.drivers.loop import notebook
from olite.drivers.loop.tools import ToolSurface

HISTORY = "f2db41e1fa331b3e"


class FakeGalaxy:
    """Minimal Galaxy: a page list, plus recording of what got created."""

    def __init__(self, pages=None):
        self.pages = list(pages or [])
        self.posted = []
        self.gets = []

    async def get(self, path):
        self.gets.append(path)
        if path.startswith("api/pages?"):
            return self.pages
        if path.startswith("api/pages/"):
            page_id = path.split("/")[-1]
            return next((p for p in self.pages if p.get("id") == page_id), {})
        return {}

    async def post(self, path, payload):
        self.posted.append((path, payload))
        page = {"id": "newpage1", **payload}
        self.pages.append(page)
        return page


def run(coro):
    return asyncio.run(coro)


# --- Identity -----------------------------------------------------------------


def test_the_slug_is_derived_from_the_history_not_invented():
    assert notebook.slug_for_history(HISTORY) == f"olite-{HISTORY}"
    # Same history, same slug, every time — that is the whole resume mechanism.
    assert notebook.slug_for_history(HISTORY) == notebook.slug_for_history(HISTORY)
    assert notebook.slug_for_history("other") != notebook.slug_for_history(HISTORY)


def test_the_slug_is_a_legal_galaxy_slug():
    slug = notebook.slug_for_history(HISTORY)
    assert slug == slug.lower()
    assert all(c.isalnum() or c == "-" for c in slug)


# --- Resume -------------------------------------------------------------------


def test_a_first_call_creates_the_record_once():
    g = FakeGalaxy()
    out = run(notebook._notebook_resume(g, {"history_id": HISTORY}))

    assert out["created"] is True
    assert out["page_id"] == "newpage1"
    assert out["slug"] == f"olite-{HISTORY}"
    path, payload = g.posted[0]
    assert path == "api/pages"
    # Attached to the history, so it shows up as that history's notebook in Galaxy.
    assert payload["history_id"] == HISTORY
    assert payload["slug"] == f"olite-{HISTORY}"


def test_a_second_call_reattaches_instead_of_creating_a_second_record():
    """The reload case. A new page here would orphan the previous record silently."""
    g = FakeGalaxy()
    first = run(notebook._notebook_resume(g, {"history_id": HISTORY}))
    second = run(notebook._notebook_resume(g, {"history_id": HISTORY}))

    assert second["created"] is False
    assert second["page_id"] == first["page_id"]
    assert len(g.posted) == 1, "resume created a second page"


def test_resuming_returns_the_existing_body_so_prior_work_is_readable():
    g = FakeGalaxy([
        {"id": "p1", "slug": f"olite-{HISTORY}", "title": "olite record", "content": "## Record\n\nStep 1 done."}
    ])
    out = run(notebook._notebook_resume(g, {"history_id": HISTORY}))

    assert out["created"] is False
    assert "Step 1 done." in out["content"]


def test_a_page_that_merely_mentions_the_slug_is_not_the_record():
    """Galaxy's page search is free text over title and content; only slug identifies."""
    g = FakeGalaxy([
        {"id": "decoy", "slug": "someone-elses-page", "content": f"see olite-{HISTORY} for details"}
    ])
    out = run(notebook._notebook_resume(g, {"history_id": HISTORY}))

    assert out["created"] is True
    assert out["page_id"] != "decoy"


def test_a_record_for_another_history_is_not_reused():
    g = FakeGalaxy([{"id": "other", "slug": "olite-aaaaaaaaaaaaaaaa", "content": "not this one"}])
    out = run(notebook._notebook_resume(g, {"history_id": HISTORY}))

    assert out["created"] is True
    assert out["page_id"] != "other"


def test_a_missing_history_id_is_refused_rather_than_guessed():
    g = FakeGalaxy()
    out = run(notebook._notebook_resume(g, {}))

    assert "error" in out
    assert g.posted == [], "must not create an unattached record"


# --- Gating -------------------------------------------------------------------


class Manifest:
    def __init__(self, granted):
        self.granted = set(granted)

    def allows(self, capability):
        return capability in self.granted


class Substrate:
    def __init__(self, granted):
        self.manifest = Manifest(granted)


def test_the_record_tool_is_write_gated():
    """Creating a record is a write; a read-only session has no record to keep."""
    assert notebook.tool_schemas(Manifest(["read"])) == []
    assert notebook.tool_schemas(Manifest(["read", "write"]))


def test_the_surface_advertises_and_dispatches_notebook_resume():
    names = [t["function"]["name"] for t in ToolSurface(Substrate(["read", "write"])).schemas()]
    assert "notebook_resume" in names

    read_only = [t["function"]["name"] for t in ToolSurface(Substrate(["read"])).schemas()]
    assert "notebook_resume" not in read_only
