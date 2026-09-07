"""Atomic, revision-checked editor transactions. No audio or model imports."""
from __future__ import annotations

import copy
import time
from typing import Callable

from .project import Project, ProjectError, new_id


class CommandError(ProjectError):
    pass


class History:
    def __init__(self, limit=100):
        self._undo, self._redo = [], []
        self.limit = limit

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    def execute(self, project: Project, action: Callable, *, command_id=None,
                base_revision=None):
        command_id = command_id or new_id("cmd")
        if command_id in project.command_ids:
            raise CommandError("This edit was already applied; the current project was kept.")
        if base_revision is not None and base_revision != project.revision:
            raise CommandError("The project changed before this edit arrived. Please try it again.")
        candidate = copy.deepcopy(project)
        result = action(candidate)
        if isinstance(result, tuple) and result and result[0] is False:
            raise CommandError(result[1])
        before = project.to_dict()
        if candidate.to_dict() == before:
            return result
        self._undo.append(before)
        del self._undo[:-self.limit]
        self._redo.clear()
        candidate.revision = project.revision + 1
        candidate.modified_at = time.time()
        candidate.command_ids = (project.command_ids + [command_id])[-1000:]
        project.__dict__.update(candidate.__dict__)
        return result

    def _travel(self, project, source, destination):
        if not source:
            return False
        destination.append(project.to_dict())
        candidate = Project.from_dict(source.pop())
        candidate.revision = project.revision + 1
        candidate.modified_at = time.time()
        candidate.command_ids = (project.command_ids + [new_id("cmd")])[-1000:]
        # Runtime disk/lease state stays on the live object, not in snapshots.
        project.__dict__.update(candidate.__dict__)
        return True

    def undo(self, project):
        return self._travel(project, self._undo, self._redo)

    def redo(self, project):
        return self._travel(project, self._redo, self._undo)

    def travel_command(self, project, kind, command_id, base_revision):
        if command_id in project.command_ids or base_revision != project.revision:
            raise CommandError("The project changed before this command arrived. Please try again.")
        changed = self.undo(project) if kind == "undo" else self.redo(project)
        if changed:
            project.command_ids[-1] = command_id
        return changed
