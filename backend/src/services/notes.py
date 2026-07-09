"""Helpers for coordinating note tool usage instructions."""

from __future__ import annotations

import json

from models import DishItem


def build_note_guidance(task: DishItem) -> str:
    """Generate note tool usage guidance for a specific task."""

    tags_list = ["recipe_assistant", f"task_{task.id}"]
    tags_literal = json.dumps(tags_list, ensure_ascii=False)

    if task.note_id:
        read_payload = json.dumps({"action": "read", "note_id": task.note_id}, ensure_ascii=False)
        update_payload = json.dumps(
            {
                "action": "update",
                "note_id": task.note_id,
                "task_id": task.id,
                "title": f"菜品 {task.id}: {task.name}",
                "note_type": "task_state",
                "tags": tags_list,
                "content": "请将本轮菜品用料、步骤、热量、小贴士等新增信息补充到菜品详情中",
            },
            ensure_ascii=False,
        )

        return (
            "笔记协作指引：\n"
            f"- 当前菜品笔记 ID：{task.note_id}。\n"
            f"- 在整理菜品详情前必须调用：[TOOL_CALL:note:{read_payload}] 获取已有内容。\n"
            f"- 提炼完整菜品信息后调用：[TOOL_CALL:note:{update_payload}] 同步增量信息。\n"
            "- 更新时保留原有结构，新增食材、步骤、热量、小贴士在对应位置追加补充。\n"
            f"- 标签固定使用 {tags_literal}，方便其他 Agent 检索本菜品笔记。\n"
            "- 信息写入笔记完成后，再输出面向用户的菜品整理总结。\n"
        )

    create_payload = json.dumps(
        {
            "action": "create",
            "task_id": task.id,
            "title": f"菜品 {task.id}: {task.name}",
            "note_type": "task_state",
            "tags": tags_list,
            "content": "记录本道菜需求定位、搜索信息、完整用料、烹饪步骤、热量与实操小贴士",
        },
        ensure_ascii=False,
    )

    return (
        "笔记协作指引：\n"
        f"- 尚未为本菜品创建笔记，整理信息第一步调用：[TOOL_CALL:note:{create_payload}] 创建菜品专属笔记\n"
        "- 创建成功后记录返回的 note_id，并在后续所有更新中复用。\n"
        "- 同步笔记后，再输出面向用户的总结。\n"
    )
