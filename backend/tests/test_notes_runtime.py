"""Offline regression checks for report note calls."""
import pytest

from config import Configuration
from models import DishItem, MenuState
from services.reporter import ReportingService
from services.scoped_notes import ScopedNoteTool


@pytest.mark.parametrize('note_id', [None, '', '<note_id>', '../secret', 'note.md'])
def test_invalid_note_call_returns_corrective_result(tmp_path, note_id):
    tool = ScopedNoteTool(workspace=str(tmp_path))
    result = tool.run({'action': 'read', 'note_id': note_id})
    assert '真实 ID' in result
    with pytest.raises(ValueError):
        tool._get_note_path(note_id)


def test_created_note_can_be_read(tmp_path):
    tool = ScopedNoteTool(workspace=str(tmp_path))
    tool.run({'action': 'create', 'title': '菜单', 'content': '清炒土豆丝'})
    note_id = tool.notes_index['notes'][0]['id']
    assert '清炒土豆丝' in tool.run({'action': 'read', 'note_id': note_id})


@pytest.mark.parametrize('note_id', [None, 'note_20260921_120000_0'])
def test_report_uses_available_note_ids_only(note_id):
    class ReportAgent:
        def run(self, prompt):
            self.prompt = prompt
            return '菜谱'

        def clear_history(self):
            pass

    agent = ReportAgent()
    state = MenuState(user_requirement='做午饭', dish_list=[
        DishItem(id=1, name='土豆丝', intent='午餐', query='土豆丝', note_id=note_id),
    ])
    assert ReportingService(agent, Configuration()).generate_report(state) == '菜谱'
    assert '<note_id>' not in agent.prompt
    if note_id:
        assert f'"note_id": "{note_id}"' in agent.prompt
    else:
        assert '"action": "read"' not in agent.prompt
        assert '没有可用笔记时跳过读取' in agent.prompt
