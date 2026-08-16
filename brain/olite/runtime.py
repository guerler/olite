"""Entry point the JS shell awaits: build the substrate, run the loop driver."""

import logging

from olite import prompt
from olite.drivers import LoopDriver
from olite.registry import ProcessRegistry, SkillRegistry
from olite.substrate import Substrate, cancellation, confirm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run(config, inputs, on_event=None):
    substrate = await Substrate(config).init()
    processes = ProcessRegistry().load_packaged()
    skills = SkillRegistry().load_packaged()
    driver = LoopDriver(substrate, processes, skills, confirm.from_js())
    # The shell seeds the identity prompt; the brain appends discipline and the router.
    context = "\n\n".join(t for t in (prompt.system_text(), skills.router_text()) if t)
    transcripts = _inject_context(inputs["transcripts"], context)
    try:
        result = await driver.run(transcripts, on_event, cancellation.from_js())
    except Exception as e:
        # A failed turn is a result, not a crash: the shell can say what went wrong,
        # where a raised exception reaches the user as a Pyodide traceback.
        logger.exception("turn failed")
        return {
            "logs": [],
            "messages": inputs["transcripts"],
            "new_messages": [],
            "error": {"message": str(e), "status_code": getattr(e, "status_code", None)},
        }
    # Diagnostics for the shell to surface.
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
