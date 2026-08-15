"""The system prompt blocks adopted from Orbit, and how they reach the model."""

from datetime import date
from pathlib import Path

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


def test_the_approval_gate_keeps_all_four_stages():
    """Losing a stage silently removes the protection the gate exists for."""
    block = prompt.PLAN_CONVENTION

    assert "four-stage approval gate" in block
    for stage in ("**Draft in chat.**", "**Wait for explicit plan approval.**",
                  "**Show the parameter table in chat.**",
                  "**Wait for explicit parameters approval.**"):
        assert stage in block, f"missing gate stage: {stage}"
    assert "Only after both gates pass" in block


def test_both_gates_precede_the_record_write_and_execution():
    """Orbit's stage 5 is "write the plan, then execute" — both sit behind the gates."""
    block = prompt.PLAN_CONVENTION

    gate, _, after = block.partition("**Only after both gates pass**")
    assert after, "the gate sentence is what holds both actions back"
    assert "write the approved plan into the record" in after
    assert "begin executing it" in after
    # Before the gate, execution is named only to forbid it.
    assert "Do not start executing at this point" in gate


def test_the_plan_template_teaches_the_rigid_heading():
    block = prompt.PLAN_CONVENTION

    assert "## Plan <Letter>: <Title> [<routing>]" in block
    assert "## Plan A: chrM Variant Calling [galaxy]" in block
    # The failing forms are spelled out; the model reproduces them otherwise.
    assert "(missing letter)" in block and "(missing routing tag)" in block


def test_routing_tags_describe_only_what_this_build_can_run():
    """No local execution here, so [local] and [hybrid] cannot describe anything."""
    block = prompt.PLAN_CONVENTION

    assert "`[galaxy]` or `[remote]`" in block
    assert "[local]" not in block
    assert "[hybrid]" not in block


def test_step_anchors_are_not_taught():
    """Anchors exist to let invocation YAML reference a step; that is out of scope."""
    assert "{#plan-" not in prompt.PLAN_CONVENTION


def test_the_plan_fence_is_required_because_the_card_depends_on_it():
    """ChatPanel renders ```plan fences as the Approve/Edit/Reject card."""
    block = prompt.PLAN_CONVENTION

    assert "```plan" in block
    assert "Approve / Edit / Reject" in block


def test_every_template_step_carries_a_verification_line():
    """A step without one cannot be checked off honestly."""
    steps = [ln for ln in prompt.PLAN_CONVENTION.splitlines() if ln.startswith("- [ ] ")]
    assert len(steps) == 3
    assert prompt.PLAN_CONVENTION.count("- Verification:") == len(steps)


def test_the_identity_prompt_does_not_forbid_talking():
    """Regression: `olite.xml` told the model to communicate ONLY by calling tools."""
    xml = Path(__file__).resolve().parents[2] / "public" / "olite.xml"
    if not xml.is_file():
        pytest.skip("olite.xml not present next to the brain package")
    text = xml.read_text()

    assert "Communicate only by calling tools" not in text
    # And the blocks that need chat are still the ones asking for it.
    assert "```plan" in prompt.PLAN_CONVENTION
    assert "Show the parameter table in chat" in prompt.PLAN_CONVENTION


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
    """loom's whole system prompt is ~8K tokens; the ported subset must stay under it."""
    approx_tokens = len(prompt.system_text()) / 4
    assert approx_tokens < 4000, f"ported blocks alone are ~{approx_tokens:.0f} tokens"
