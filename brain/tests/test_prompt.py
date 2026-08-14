"""The system prompt blocks adopted from Orbit, and how they reach the model."""

from datetime import date

import pytest

from olite import prompt
from olite.runtime import BEGIN, END, _inject_context


def test_every_ported_block_is_composed():
    text = prompt.system_text()

    for heading in (
        "## Execution: remote-only (Galaxy)",
        "## Galaxy",
        "### Getting data into a Galaxy history",
        "### Invoking a Galaxy workflow",
        "## Operating discipline",
        "## Verification before completion",
        "## Parameter review",
        "## Chat formatting",
        "## Current date",
    ):
        assert heading in text, f"missing block: {heading}"


def test_no_block_promises_a_runtime_olite_does_not_have():
    """Orbit's text assumes a shell, a filesystem, and a notebook. None exist here."""
    text = prompt.system_text().replace(prompt.NO_LOCAL_SHELL, "").lower()

    for absent in (
        "conda",
        "bash",
        "notebook.md",
        "/compact",
        "~/.loom",
        "preferences → galaxy",
        "galaxy_upload_local_file",
        "bioblend",
    ):
        assert absent not in text, f"prompt refers to something olite lacks: {absent}"


def test_galaxy_tools_are_named_the_way_olite_names_them():
    """loom's text says `galaxy_invoke_workflow`; olite's tool is `invoke_workflow`."""
    text = prompt.system_text()

    assert "invoke_workflow" in text and "galaxy_invoke_workflow" not in text
    assert "upload_file_from_url" in text and "galaxy_upload_file_from_url" not in text
    assert "search_iwc_workflows" in text and "galaxy_search_iwc" not in text


def test_the_local_upload_path_is_refused_not_recommended():
    """Orbit tells the agent to upload local files; here that tool cannot work."""
    text = prompt.system_text()

    assert "no local-upload path here" in text
    assert "upload_file_from_url" in text


def test_the_date_block_carries_a_real_date():
    text = prompt.system_text(today=date(2026, 8, 14))

    assert "**2026-08-14**" in text
    assert "Never\nguess, infer, or fabricate today's date" in text or "fabricate today's date" in text


def test_todays_date_is_used_when_none_is_given():
    assert f"**{date.today().isoformat()}**" in prompt.system_text()


# --- Injection ----------------------------------------------------------------


def test_context_is_appended_to_the_shell_seeded_system_message():
    out = _inject_context([{"role": "system", "content": "identity"}, {"role": "user", "content": "hi"}], "BLOCKS")

    assert out[0]["content"].startswith("identity")
    assert "BLOCKS" in out[0]["content"]
    assert out[1] == {"role": "user", "content": "hi"}


def test_a_transcript_without_a_system_message_gets_one():
    out = _inject_context([{"role": "user", "content": "hi"}], "BLOCKS")

    assert out[0]["role"] == "system"
    assert "BLOCKS" in out[0]["content"]
    assert len(out) == 2


def test_reinjection_replaces_rather_than_appends():
    """The shell hands the persisted transcript back every turn."""
    once = _inject_context([{"role": "system", "content": "identity"}], "FIRST")
    twice = _inject_context(once, "FIRST")

    assert twice[0]["content"] == once[0]["content"]
    assert twice[0]["content"].count(BEGIN) == 1


def test_changed_context_replaces_the_old_copy_in_place():
    """The date turns over and the corpus moves; two copies would contradict."""
    once = _inject_context([{"role": "system", "content": "identity"}], "DAY ONE")
    twice = _inject_context(once, "DAY TWO")

    assert "DAY ONE" not in twice[0]["content"]
    assert "DAY TWO" in twice[0]["content"]
    assert twice[0]["content"].count(BEGIN) == 1
    assert twice[0]["content"].count(END) == 1
    # The shell-seeded identity is never disturbed.
    assert twice[0]["content"].startswith("identity")


@pytest.mark.parametrize("empty", ["", None])
def test_nothing_to_inject_leaves_the_transcript_alone(empty):
    transcripts = [{"role": "system", "content": "identity"}]
    assert _inject_context(transcripts, empty) is transcripts


def test_the_prompt_stays_within_a_sane_budget():
    """loom's whole system prompt is ~8K tokens; the ported half must not exceed it."""
    approx_tokens = len(prompt.system_text()) / 4
    assert approx_tokens < 3000, f"ported blocks alone are ~{approx_tokens:.0f} tokens"
