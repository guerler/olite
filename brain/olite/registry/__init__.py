"""Registry: what olite knows. Processes (crystallized agent.yml graphs) and"""

from .processes import Process, ProcessRegistry
from .skills import SkillRegistry

__all__ = ["Process", "ProcessRegistry", "SkillRegistry"]
