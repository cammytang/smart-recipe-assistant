"""State models used by the deep research workflow."""

from dataclasses import dataclass, field
from typing import List, Optional


# @dataclass(kw_only=True)
# class LegacyTodoItem:
#     """单个待办任务项。"""

#     id: int
#     title: str
#     intent: str
#     query: str
#     status: str = field(default="pending")
#     summary: Optional[str] = field(default=None)
#     sources_summary: Optional[str] = field(default=None)
#     notices: list[str] = field(default_factory=list)
#     note_id: Optional[str] = field(default=None)
#     note_path: Optional[str] = field(default=None)
#     stream_token: Optional[str] = field(default=None)

@dataclass(kw_only=True)
class DishItem:
    """单道菜菜品任务。"""
    id: int
    name: str          # 原 title：菜品名称 dish name
    intent: str             # 本道菜定位、适配需求
    query: str       # 原 query：搜索菜谱关键词 search qurey
    status: str = field(default="pending")

    # 原有兼容字段（不能删，流式、笔记、序列化函数依赖）
    notices: List[str] = field(default_factory=list)
    note_id: Optional[str] = field(default=None)
    note_path: Optional[str] = field(default=None)
    stream_token: Optional[str] = field(default=None)
    memory_used: List[str] = field(default_factory=list)
    memory_conflicts: List[str] = field(default_factory=list)

    # ========== 菜谱专属业务字段（运行搜索+总结后回填） ==========
    ingredients: Optional[List[str]] = field(default=None)
    cook_steps: Optional[List[str]] = field(default=None)
    cook_time: str = field(default="")
    calories: int = field(default=0)
    tips: str = field(default="")
    source_links: Optional[List[str]] = field(default=None)

@dataclass(kw_only=True)
class MenuState:
    user_requirement: str
    allergy_list: list[str] = field(default_factory=list)
    exist_ingredients: list[str] = field(default_factory=list)
    dish_list: list[DishItem] = field(default_factory=list)
    all_search_context: list[str] = field(default_factory=list)
    final_menu_markdown: str = ""
    shopping_list: list[str] = field(default_factory=list)
    total_calories: int = 0
    report_note_id: Optional[str] = field(default=None)
    report_note_path: Optional[str] = field(default=None)
    research_loop_count: int = field(default=0)  # Research loop count

@dataclass(kw_only=True)
class MenuStateInput:
    research_topic: str = field(default=None)  # Report topic


@dataclass(kw_only=True)
class MenuStateOutput:
    menu_markdown: Optional[str] = field(default=None)
    dish_list: List[DishItem] = field(default_factory=list)
    shopping_list: list[str] = field(default_factory=list)
    total_calories: int = 0
