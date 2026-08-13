"""Skill registry: markdown know-how injected into the system prompt."""

from importlib import resources


class SkillRegistry:
    def __init__(self):
        self._skills = {}

    def register(self, name, text):
        self._skills[name] = text

    def load_packaged(self):
        """Load every *.md under this package's skills/ directory."""
        root = resources.files("olite.registry").joinpath("skills")
        if not root.is_dir():
            return self
        for entry in root.iterdir():
            if entry.name.endswith(".md"):
                self.register(entry.name[:-3], entry.read_text())
        return self

    def names(self):
        return sorted(self._skills)

    def prompt_text(self):
        return "\n\n".join(self._skills[name] for name in self.names())
