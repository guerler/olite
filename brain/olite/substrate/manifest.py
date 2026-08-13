"""Capability manifest: the single contract the substrate enforces."""

# Default: reason (llm), local Pyodide compute, and read-only Galaxy access.
DEFAULT_CAPABILITIES = ["llm", "local", "read"]


class CapabilityManifest:
    def __init__(self, capabilities=None):
        self.granted = set(capabilities or DEFAULT_CAPABILITIES)

    def allows(self, capability):
        """True if the manifest grants this capability (None means unrestricted)."""
        if capability is None:
            return True
        return capability in self.granted

    def require(self, capability):
        from .exceptions import CapabilityError

        if not self.allows(capability):
            raise CapabilityError(
                f"Capability '{capability}' not granted",
                details={"granted": sorted(self.granted)},
            )

    def grant(self, capability):
        self.granted.add(capability)

    def to_list(self):
        return sorted(self.granted)
