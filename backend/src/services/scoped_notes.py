"""Constrain every NoteTool file access to its server-selected workspace."""
import re
from hello_agents.tools.builtin.note_tool import NoteTool


class ScopedNoteTool(NoteTool):
    def _get_note_path(self, note_id):
        if not isinstance(note_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', note_id):
            raise ValueError('Invalid note identifier')
        root = self.workspace.resolve()
        path = (root / f'{note_id}.md').resolve()
        if path.parent != root:
            raise ValueError('Note outside current workspace')
        return path
