"""The substrate: what olite can touch, and the gate that governs it."""

from .catalog import Catalog
from .galaxy_http import GalaxyHttp
from .llm import Llm
from .local import LocalPython
from .manifest import CapabilityManifest


class Substrate:
    def __init__(self, config):
        self.config = config
        self.manifest = CapabilityManifest(config.get("capabilities"))
        self.local = LocalPython(self.manifest)
        self.llm = Llm(config, self.manifest)
        self.galaxy = GalaxyHttp(config, self.manifest)
        self.catalog = Catalog(config, self.manifest)

    async def init(self):
        await self.catalog.init()
        return self
