"""Lightweight long-term memory for the recipe assistant demo."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_MEMORY: dict[str, Any] = {
    "diet_preferences": [],
    "allergies": [],
    "disliked_ingredients": [],
    "favorite_ingredients": [],
    "common_serving_size": "",
    "recent_dishes": [],
    "rejected_patterns": [],
    "updated_at": "",
}

PREFERENCE_KEYWORDS = [
    "低脂",
    "减脂",
    "不辣",
    "清淡",
    "少油",
    "高蛋白",
    "低碳",
    "素食",
    "快手",
    "家常",
]

INGREDIENT_KEYWORDS = [
    "番茄",
    "西红柿",
    "土豆",
    "鸡蛋",
    "豆腐",
    "西兰花",
    "鸡胸肉",
    "牛肉",
    "猪肉",
    "虾",
    "冬瓜",
    "黄瓜",
    "茄子",
    "青菜",
    "白菜",
    "蘑菇",
    "洋葱",
]


class MemoryService:
    """Persist and format simple user preference memory as local JSON."""

    def __init__(self, memory_path: Path | None = None) -> None:
        src_dir = Path(__file__).resolve().parents[1]
        self.memory_path = memory_path or src_dir / "data" / "user_memory.json"

    def load_memory(self) -> dict[str, Any]:
        """Load memory from disk, creating a default file when missing."""

        if not self.memory_path.exists():
            memory = self._default_memory()
            self.save_memory(memory)
            return memory

        try:
            with self.memory_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            raw = {}

        memory = self._default_memory()
        if isinstance(raw, dict):
            memory.update({key: raw.get(key, value) for key, value in memory.items()})
        return self._normalize_memory(memory)

    def save_memory(self, memory: dict[str, Any]) -> dict[str, Any]:
        """Persist normalized memory to disk."""

        normalized = self._normalize_memory(memory)
        normalized["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        with self.memory_path.open("w", encoding="utf-8") as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2)
        return normalized

    def clear_memory(self) -> dict[str, Any]:
        """Reset memory to an empty structure."""

        return self.save_memory(self._default_memory())

    def format_memory_for_prompt(self, memory: dict[str, Any] | None = None) -> str:
        """Format memory into a concise planner prompt section."""

        memory = self._normalize_memory(memory or self.load_memory())
        lines: list[str] = []

        if memory["diet_preferences"]:
            lines.append("历史饮食偏好：" + "、".join(memory["diet_preferences"]))
        if memory["allergies"]:
            lines.append("历史过敏/禁忌：" + "、".join(memory["allergies"]))
        if memory["disliked_ingredients"]:
            lines.append("历史不喜欢食材：" + "、".join(memory["disliked_ingredients"]))
        if memory["favorite_ingredients"]:
            lines.append("常用/偏好食材：" + "、".join(memory["favorite_ingredients"]))
        if memory["common_serving_size"]:
            lines.append("常见用餐人数：" + memory["common_serving_size"])
        if memory["recent_dishes"]:
            lines.append("最近确认过的菜品：" + "、".join(memory["recent_dishes"][:8]))
        if memory["rejected_patterns"]:
            lines.append("用户曾拒绝的规划倾向：" + "、".join(memory["rejected_patterns"][:6]))

        if not lines:
            lines.append("暂无长期记忆。")

        lines.extend(
            [
                "使用规则：本次用户明确输入优先级最高；用户本轮修改意见第二；长期记忆仅作参考；如果冲突，必须以本次输入为准。",
                "不要把长期记忆中不确定的信息当作本次硬性约束。",
            ]
        )
        return "\n".join(f"- {line}" for line in lines)

    def summarize_for_ui(self, memory: dict[str, Any] | None = None) -> list[str]:
        """Return short reader-facing memory chips for the frontend."""

        memory = self._normalize_memory(memory or self.load_memory())
        items: list[str] = []
        items.extend([f"偏好：{value}" for value in memory["diet_preferences"][:5]])
        items.extend([f"忌口：{value}" for value in memory["allergies"][:4]])
        items.extend([f"常用食材：{value}" for value in memory["favorite_ingredients"][:6]])
        if memory["common_serving_size"]:
            items.append(f"常见人数：{memory['common_serving_size']}")
        if memory["recent_dishes"]:
            items.append("最近做过：" + "、".join(memory["recent_dishes"][:3]))
        return items

    def update_from_confirmation(
        self,
        user_requirement: str,
        dish_list: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Update long-term memory only after the user confirms a plan."""

        memory = self.load_memory()
        extracted = self._extract_memory_candidates(user_requirement, dish_list)

        for key in [
            "diet_preferences",
            "allergies",
            "disliked_ingredients",
            "favorite_ingredients",
            "recent_dishes",
        ]:
            memory[key] = self._merge_unique(memory.get(key, []), extracted.get(key, []), limit=20)

        if extracted.get("common_serving_size"):
            memory["common_serving_size"] = extracted["common_serving_size"]

        return self.save_memory(memory)

    def _extract_memory_candidates(
        self,
        user_requirement: str,
        dish_list: list[dict[str, Any]],
    ) -> dict[str, Any]:
        text = user_requirement or ""
        candidates: dict[str, Any] = {
            "diet_preferences": [word for word in PREFERENCE_KEYWORDS if word in text],
            "allergies": self._extract_allergies(text),
            "disliked_ingredients": self._extract_disliked_ingredients(text),
            "favorite_ingredients": [word for word in INGREDIENT_KEYWORDS if word in text],
            "common_serving_size": self._extract_serving_size(text),
            "recent_dishes": [],
        }

        for item in dish_list:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("title") or "").strip()
            if name:
                candidates["recent_dishes"].append(name)

        return candidates

    def _extract_allergies(self, text: str) -> list[str]:
        found: list[str] = []
        for ingredient in INGREDIENT_KEYWORDS:
            if f"{ingredient}过敏" in text or f"过敏{ingredient}" in text:
                found.append(ingredient)
        return found

    def _extract_disliked_ingredients(self, text: str) -> list[str]:
        found: list[str] = []
        for ingredient in INGREDIENT_KEYWORDS:
            if f"不吃{ingredient}" in text or f"不要{ingredient}" in text:
                found.append(ingredient)
        return found

    def _extract_serving_size(self, text: str) -> str:
        match = re.search(r"(一人|两人|二人|三人|四人|五人|多人|家庭)(餐|食|晚餐|午餐|早饭|晚饭)?", text)
        return match.group(0) if match else ""

    def _normalize_memory(self, memory: dict[str, Any]) -> dict[str, Any]:
        normalized = self._default_memory()
        normalized.update(memory)

        for key in [
            "diet_preferences",
            "allergies",
            "disliked_ingredients",
            "favorite_ingredients",
            "recent_dishes",
            "rejected_patterns",
        ]:
            normalized[key] = self._merge_unique([], normalized.get(key, []), limit=20)

        normalized["common_serving_size"] = str(normalized.get("common_serving_size") or "")
        normalized["updated_at"] = str(normalized.get("updated_at") or "")
        return normalized

    def _merge_unique(self, old_items: Any, new_items: Any, *, limit: int) -> list[str]:
        result: list[str] = []
        old_list = [old_items] if isinstance(old_items, str) else list(old_items or [])
        new_list = [new_items] if isinstance(new_items, str) else list(new_items or [])
        for item in old_list + new_list:
            value = str(item).strip()
            if value and value not in result:
                result.append(value)
        return result[-limit:]

    def _default_memory(self) -> dict[str, Any]:
        return deepcopy(DEFAULT_MEMORY)
