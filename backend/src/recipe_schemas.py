"""HTTP models for the recipe and memory API."""
from typing import Any
from pydantic import BaseModel, Field, ConfigDict
from config import SearchAPI

class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    """Payload for triggering a research run."""

    topic: str = Field(..., description="Research topic supplied by the user")
    search_api: SearchAPI | None = Field(
        default=None,
        description="Override the default search backend configured via env",
    )


class DishItemPayload(BaseModel):
    """Dish item accepted from the menu planning confirmation step."""

    id: int
    name: str
    intent: str = ""
    query: str = ""
    status: str = "pending"
    note_id: str | None = None
    note_path: str | None = None
    stream_token: str | None = None
    memory_used: list[str] = Field(default_factory=list)
    memory_conflicts: list[str] = Field(default_factory=list)


class MenuStreamRequest(ResearchRequest):
    """Payload for streaming a menu run after optional user confirmation."""

    dish_list: list[DishItemPayload] | None = Field(
        default=None,
        description="User-confirmed dish list. If omitted, backend plans automatically.",
    )


class MenuPlanResponse(BaseModel):
    """Response containing only the planned dish list."""

    dish_list: list[dict[str, Any]] = Field(default_factory=list)
    memory_summary: list[str] = Field(default_factory=list)
    memory: dict[str, Any] = Field(default_factory=dict)


class MemoryConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    """Payload for writing confirmed planning outcomes to long-term memory."""

    user_requirement: str
    dish_list: list[dict[str, Any]] = Field(default_factory=list)


class MemoryResponse(BaseModel):
    """Memory state returned to the frontend."""

    memory: dict[str, Any] = Field(default_factory=dict)
    memory_summary: list[str] = Field(default_factory=list)


class ResearchResponse(BaseModel):
    """HTTP response containing the generated report and structured tasks."""

    menu_markdown: str = Field(
        ..., description="Markdown-formatted menu report including sections"
    )
    dish_list: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Structured dish items with notes and sources",
    )
    shopping_list: list[str] = Field(
        default_factory=list,
        description="Structured shopping list generated from selected recipes",
    )


