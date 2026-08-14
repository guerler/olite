"""Entry point the JS shell awaits."""

import logging

from olite import prompt
from olite.drivers import LoopDriver
from olite.registry import ProcessRegistry, SkillRegistry
from olite.substrate import Substrate

logging.basicConfig(level=logging.INFO)


async def run(config, inputs, on_event=None):
    substrate = await Substrate(config).init()
    processes = ProcessRegistry().load_packaged()
    skills = SkillRegistry().load_packaged()
    driver = LoopDriver(substrate, processes, skills)
    # The shell seeds the identity prompt (olite.xml `ai_prompt`); the brain appends
    context = "\n\n".join(t for t in (prompt.system_text(), skills.router_text()) if t)
    transcripts = _inject_context(inputs["transcripts"], context)
    result = await driver.run(transcripts, on_event)
    # Diagnostics for the shell to surface (e.g. whether the Galaxy catalog loaded).
    result["diagnostics"] = {
        "catalog": substrate.catalog.status(),
        "capabilities": substrate.manifest.to_list(),
    }
    return result


BEGIN = "<!-- olite:context -->"
END = "<!-- /olite:context -->"


def _inject_context(transcripts, text):
    """Put the brain's context blocks in the system message, between markers."""
    if not text or not transcripts:
        return transcripts
    block = f"{BEGIN}\n{text}\n{END}"
    first = transcripts[0]
    if first.get("role") != "system":
        return [{"role": "system", "content": block}, *transcripts]

    content = first.get("content") or ""
    start, stop = content.find(BEGIN), content.find(END)
    if start != -1 and stop > start:
        content = content[:start] + block + content[stop + len(END):]
    else:
        content = f"{content}\n\n{block}"
    merged = dict(first)
    merged["content"] = content.strip()
    return [merged, *transcripts[1:]]
