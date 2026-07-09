"""Service that consolidates task results into the final report."""

from __future__ import annotations

import json

from hello_agents import ToolAwareSimpleAgent

from models import MenuState
from config import Configuration
from utils import strip_thinking_tokens
from services.text_processing import strip_tool_calls


class ReportingService:
    """Generates the final structured report."""

    def __init__(self, report_agent: ToolAwareSimpleAgent, config: Configuration) -> None:
        self._agent = report_agent
        self._config = config

    def generate_report(self, state: MenuState) -> str:
        """Generate a structured report based on completed tasks."""

        tasks_block = []
        for task in state.dish_list:
            summary_block = task.cook_steps or "暂无可用信息"
            sources_block = task.source_links or "暂无来源"
            tasks_block.append(
                f"### 菜单任务 {task.id}: {task.name}\n"
                f"- 菜单定位：{task.intent}\n"
                f"- 检索查询：{task.query}\n"
                f"- 执行状态：{task.status}\n"
                f"- 菜单步骤：\n{summary_block}\n"
                f"- 来源概览：\n{sources_block}\n"
            )

        note_references = []
        for task in state.dish_list:
            if task.note_id:
                note_references.append(
                    f"- 菜单 {task.id}《{task.name}》：note_id={task.note_id}"
                )

        notes_section = "\n".join(note_references) if note_references else "- 暂无可用任务笔记"
        shopping_section = (
            "\n".join(f"- {item}" for item in state.shopping_list)
            if state.shopping_list
            else "- 暂无结构化购物清单"
        )

        read_template = json.dumps({"action": "read", "note_id": "<note_id>"}, ensure_ascii=False)
        create_conclusion_template = json.dumps(
            {
                "action": "create",
                "title": f"用户需求：{state.user_requirement}",
                "note_type": "conclusion",
                "tags": ["recipe_assistant", "report"],
                "content": "请在此沉淀最终菜谱",
            },
            ensure_ascii=False,
        )

        prompt = (
            f"用户原始需求：{state.user_requirement}\n"
            f"菜单概览：\n{''.join(tasks_block)}\n"
            f"结构化购物清单：\n{shopping_section}\n"
            f"可用笔记：\n{notes_section}\n"
            f"请针对每条任务笔记使用格式：[TOOL_CALL:note:{read_template}] 读取内容，整合所有信息后撰写菜谱。\n"
            f"如需输出汇总菜谱，可追加调用：[TOOL_CALL:note:{create_conclusion_template}] 保存最终菜谱。"
        )

        response = self._agent.run(prompt)
        self._agent.clear_history()

        report_text = response.strip()
        if self._config.strip_thinking_tokens:
            report_text = strip_thinking_tokens(report_text)

        report_text = strip_tool_calls(report_text).strip()

        return report_text or "菜谱生成失败，请检查输入。"
