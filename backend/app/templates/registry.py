"""Templates available to sources: starter pack plus approved user templates (SPEC 4).

Loaded at startup. Drafts are never loaded. A template that fails validation or its own
tests is reported (admins see the problems) and is simply not available.
"""

from pathlib import Path

from app.templates.loader import LoadProblem, load_all
from app.templates.tables import LookupTable, load_tables
from app.templates.validator import Template

# <repo>/templates/starter in development; the image copies it to /srv/templates/starter.
STARTER_DIR = Path(__file__).resolve().parents[3] / "templates" / "starter"


class TemplateRegistry:
    def __init__(self, starter_dir: Path, user_dir: Path) -> None:
        self._starter = starter_dir
        self._user = user_dir
        self._templates: dict[str, Template] = {}
        self.tables: dict[str, LookupTable] = {}
        self.problems: list[LoadProblem] = []
        self.starter_ids: frozenset[str] = frozenset()
        self.reload()

    def reload(self) -> None:
        self.tables, table_problems = load_tables(self._starter / "maps")
        self._templates, self.problems = load_all(self._starter, self._user, self.tables)
        # Starter files are named by id (drafts.py relies on the same rule).
        self.starter_ids = frozenset(
            t for t in self._templates if (self._starter / f"{t}.yaml").is_file()
        )
        self.problems = [LoadProblem(f"maps/{f}", m) for f, m in table_problems] + self.problems

    @property
    def starter_dir(self) -> Path:
        return self._starter

    @property
    def user_dir(self) -> Path:
        return self._user

    def get(self, template_id: str) -> Template | None:
        return self._templates.get(template_id)

    def all(self) -> list[Template]:
        return sorted(self._templates.values(), key=lambda t: t.id)
