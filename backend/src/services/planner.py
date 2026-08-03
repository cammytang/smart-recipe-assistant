"""Service responsible for converting the research topic into actionable tasks."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, List, Optional

from hello_agents import ToolAwareSimpleAgent

from models import MenuState, DishItem
from config import Configuration
from prompts import get_current_date, todo_planner_instructions
from utils import strip_thinking_tokens
from loguru import logger

# logger = logging.getLogger(__name__)

TOOL_CALL_PATTERN = re.compile(
    r"\[TOOL_CALL:(?P<tool>[^:]+):(?P<body>[^\]]+)\]",
    re.IGNORECASE,
)

class PlanningService:
    """Wraps the planner agent to produce structured TODO items."""

    def __init__(self, planner_agent: ToolAwareSimpleAgent, config: Configuration) -> None:
        self._agent = planner_agent
        self._config = config

    def plan_todo_list(self, state: MenuState, user_memory: str = "暂无长期记忆。") -> List[DishItem]:
        """Ask the planner agent to break the topic into actionable tasks."""

        prompt = todo_planner_instructions.format(
            current_date=get_current_date(),
            research_topic=state.user_requirement,
            user_memory=user_memory,
        )

        response = self._agent.run(prompt)
        self._agent.clear_history()

        logger.info("Planner raw output (truncated): %s", response[:500])

        print("XXXXXXXXXX Planner raw output (truncated):", response[:500])

        tasks_payload = self._extract_tasks(response)
        dish_items: List[DishItem] = []

        print("YYYYYY tasks_payload", tasks_payload)

        for idx, item in enumerate(tasks_payload, start=1):
            title = str(item.get("title") or f"菜单{idx}").strip()
            intent = str(item.get("intent") or "菜品定位").strip()
            query = str(item.get("query") or state.user_requirement).strip()

            if not query:
                query = state.user_requirement

            task = DishItem(
                id=idx,
                name=title,
                intent=intent,
                query=query,
                memory_used=self._as_string_list(item.get("memory_used")),
                memory_conflicts=self._as_string_list(item.get("memory_conflicts")),
            )
            dish_items.append(task)

        state.dish_list = dish_items

        titles = [task.name for task in dish_items]
        logger.info("Planner produced %d tasks: %s", len(dish_items), titles)

        print(f'Planner produced {len(dish_items)} tasks: {titles}')
        return dish_items

    @staticmethod
    def create_fallback_task(state: MenuState) -> DishItem:
        """Create a minimal fallback task when planning failed."""
    
        return DishItem(
            id=1,
            name="快手家常炒蛋",
            intent="利用常见食材快速做一道简单下饭家常菜，适配用户用餐需求",
            query=f"{state.user_requirement} 家常简单菜谱 详细做法" if state.user_requirement else "家常快手鸡蛋菜谱",
        )

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------
    def _extract_tasks(self, raw_response: str) -> List[dict[str, Any]]:
        """Parse planner output into a list of task dictionaries."""

        text = raw_response.strip()

        print("YYYYYY raw response", text[:500])

        if self._config.strip_thinking_tokens:
            text = strip_thinking_tokens(text)

        json_payload = self._extract_json_payload(text)
        tasks: List[dict[str, Any]] = []

        if isinstance(json_payload, dict):
            candidate = json_payload.get("tasks")
            if isinstance(candidate, list):
                for item in candidate:
                    if isinstance(item, dict):
                        tasks.append(item)
        elif isinstance(json_payload, list):
            for item in json_payload:
                if isinstance(item, dict):
                    tasks.append(item)

        if not tasks:
            tool_payload = self._extract_tool_payload(text)
            if tool_payload and isinstance(tool_payload.get("tasks"), list):
                for item in tool_payload["tasks"]:
                    if isinstance(item, dict):
                        tasks.append(item)

        return tasks

    def _extract_json_payload(self, text: str) -> Optional[dict[str, Any] | list]:
        """Try to locate and parse a JSON object or array from the text."""

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                return None

        return None

    def _extract_tool_payload(self, text: str) -> Optional[dict[str, Any]]:
        """Parse the first TOOL_CALL expression in the output."""

        match = TOOL_CALL_PATTERN.search(text)
        if not match:
            return None

        body = match.group("body")

        try:
            payload = json.loads(body)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass

        parts = [segment.strip() for segment in body.split(",") if segment.strip()]
        payload: dict[str, Any] = {}
        for part in parts:
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            payload[key.strip()] = value.strip().strip('"').strip("'")

        return payload or None

    @staticmethod
    def _as_string_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []
