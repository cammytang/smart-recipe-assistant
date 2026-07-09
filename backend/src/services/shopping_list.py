"""Helpers for building a structured shopping list from recipe tasks."""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Iterable

from models import DishItem


SERVING_INGREDIENT_RE = re.compile(r"每份用量：(.+?)(?:\n|$)")
STOP_MARKERS = ("烹饪步骤：", "附加内容：", "必备原料和工具：", "简介：", "难度：", "热量：")


def extract_serving_ingredients(text: str) -> list[str]:
    """Extract serving-size ingredients from retrieved RAG context."""
    if not text:
        return []

    ingredients: list[str] = []
    for match in SERVING_INGREDIENT_RE.finditer(text):
        segment = match.group(1).strip()
        for marker in STOP_MARKERS:
            if marker in segment:
                segment = segment.split(marker, 1)[0].strip()
        ingredients.extend(split_ingredient_segment(segment))

    return dedupe_preserve_order(ingredients)


def split_ingredient_segment(segment: str) -> list[str]:
    """Split a Chinese ingredient list while keeping useful quantity text."""
    if not segment:
        return []

    candidates = re.split(r"[、；;]\s*", segment)
    return [clean_ingredient(item) for item in candidates if clean_ingredient(item)]


def clean_ingredient(item: str) -> str:
    item = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s*", "", item)
    item = re.sub(r"\s+", " ", item)
    return item.strip(" ，,。；;")


def dedupe_preserve_order(items: Iterable[str]) -> list[str]:
    seen: OrderedDict[str, None] = OrderedDict()
    for item in items:
        cleaned = clean_ingredient(item)
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen.keys())


def build_shopping_list(dish_list: Iterable[DishItem]) -> list[str]:
    """
    Build a stable shopping list from task.ingredients.

    This intentionally does not do unit arithmetic yet. If two dishes use the
    same ingredient with different units or quantities, preserving both lines is
    clearer than pretending to merge them incorrectly.
    """
    item_sources: OrderedDict[str, list[str]] = OrderedDict()

    for task in dish_list:
        for ingredient in task.ingredients or []:
            cleaned = clean_ingredient(ingredient)
            if not cleaned:
                continue
            item_sources.setdefault(cleaned, [])
            if task.name and task.name not in item_sources[cleaned]:
                item_sources[cleaned].append(task.name)

    shopping_items = []
    for item, sources in item_sources.items():
        source_text = "、".join(sources)
        shopping_items.append(f"{item}（用于：{source_text}）" if source_text else item)

    return shopping_items
