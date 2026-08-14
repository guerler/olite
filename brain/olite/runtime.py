"""Entry point the JS shell awaits."""

import logging

from olite.drivers import LoopDriver
from olite.registry import ProcessRegistry, SkillRegistry
from olite.substrate import Substrate

logging.basicConfig(level=logging.INFO)


async def run(config, inputs, on_event=None):
    substrate = await Substrate(config).init()
    processes = ProcessRegistry().load_packaged()
    skills = SkillRegistry().load_packaged()
    driver = LoopDriver(substrate, processes)
    transcripts = _inject_skills(inputs["transcripts"], skills.prompt_text())
    result = await driver.run(transcripts, on_event)
    # Diagnostics for the shell to surface (e.g. whether the Galaxy catalog loaded).
    result["diagnostics"] = {
        "catalog": substrate.catalog.status(),
        "capabilities": substrate.manifest.to_list(),
    }
    return result


def _inject_skills(transcripts, skill_text):
    """Append skill know-how to the system message (or add one if absent)."""
    if not skill_text or not transcripts:
        return transcripts
    first = transcripts[0]
    if first.get("role") == "system":
        if skill_text.strip() in (first.get("content") or ""):
            return transcripts
        merged = dict(first)
        merged["content"] = f"{first.get('content', '')}\n\n{skill_text}".strip()
        return [merged, *transcripts[1:]]
    return [{"role": "system", "content": skill_text}, *transcripts]
