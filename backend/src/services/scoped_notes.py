"""Constrain every NoteTool file access to its server-selected workspace."""
import re
from hello_agents.tools.builtin.note_tool import NoteTool


class ScopedNoteTool(NoteTool):
    def run(self, parameters):
        if parameters.get('action') in {'read', 'update', 'delete'}:
            note_id = parameters.get('note_id')
            if not isinstance(note_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', note_id):
                return ('❌ note_id 无效：请使用创建笔记返回的真实 ID，'
                        '不要使用 <note_id>、文件路径或文件名。'
                        '可先用 action=list 查询；没有笔记时跳过读取。')
        return super().run(parameters)

    def _get_note_path(self, note_id):
        if not isinstance(note_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', note_id):
            raise ValueError('Invalid note identifier')
        root = self.workspace.resolve()
        path = (root / f'{note_id}.md').resolve()
        if path.parent != root:
            raise ValueError('Note outside current workspace')
        return path
