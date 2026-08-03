"""LangGraph implementation of the recipe planning workflow."""

from __future__ import annotations

import logging
import os
from typing import Any, TypedDict

try:
    from langgraph.graph import END, START, StateGraph
except ImportError as exc:  # pragma: no cover - dependency guard
    raise ImportError(
        "LangGraph is required for graphs.recipe_graph. "
        "Install backend requirements or run: pip install langgraph"
    ) from exc

from agent import DEFAULT_RECIPE_RAG_LIMIT, DeepResearchAgent
from config import Configuration
from models import DishItem, MenuState, MenuStateOutput
from services.memory import MemoryService
from services.recipe_rag import format_recipe_context, get_recipe_rag_service
from services.search import dispatch_search, prepare_research_context
from services.shopping_list import build_shopping_list, extract_serving_ingredients

logger = logging.getLogger(__name__)


class RecipeGraphState(TypedDict, total=False):
    """Shared state passed between LangGraph nodes."""

    user_requirement: str
    memory_context: str
    menu_state: MenuState
    dish_contexts: dict[int, str]
    search_backends: dict[int, str]
    errors: list[str]
    final_output: MenuStateOutput


class RecipeWorkflowGraph:
    """Small LangGraph wrapper around the existing recipe services."""

    def __init__(
        self,
        *,
        config: Configuration | None = None,
        memory_service: MemoryService | None = None,
    ) -> None:
        self.agent = DeepResearchAgent(config=config)
        if memory_service is not None:
            self.agent.memory = memory_service
        self.app = self._build_graph()

    def invoke(self, user_requirement: str) -> MenuStateOutput:
        """Run the graph and return the same output shape as DeepResearchAgent.run."""
        initial_state: RecipeGraphState = {
            "user_requirement": user_requirement,
            "errors": [],
            "dish_contexts": {},
            "search_backends": {},
        }
        result = self.app.invoke(initial_state)
        final_output = result.get("final_output")
        if not final_output:
            menu_state = result.get("menu_state") or MenuState(user_requirement=user_requirement)
            final_output = MenuStateOutput(
                menu_markdown=menu_state.final_menu_markdown,
                dish_list=menu_state.dish_list,
                shopping_list=menu_state.shopping_list,
                total_calories=menu_state.total_calories,
            )
        return final_output

    def _build_graph(self) -> Any:
        workflow = StateGraph(RecipeGraphState)

        workflow.add_node("load_memory", self._load_memory)
        workflow.add_node("plan_menu", self._plan_menu)
        workflow.add_node("retrieve_recipes", self._retrieve_recipes)
        workflow.add_node("summarize_dishes", self._summarize_dishes)
        workflow.add_node("build_shopping_list", self._build_shopping_list)
        workflow.add_node("write_report", self._write_report)
        workflow.add_node("persist_report", self._persist_report)

        workflow.add_edge(START, "load_memory")
        workflow.add_edge("load_memory", "plan_menu")
        workflow.add_edge("plan_menu", "retrieve_recipes")
        workflow.add_edge("retrieve_recipes", "summarize_dishes")
        workflow.add_edge("summarize_dishes", "build_shopping_list")
        workflow.add_edge("build_shopping_list", "write_report")
        workflow.add_edge("write_report", "persist_report")
        workflow.add_edge("persist_report", END)

        return workflow.compile()

    def _load_memory(self, state: RecipeGraphState) -> RecipeGraphState:
        memory_context = self.agent.memory.format_memory_for_prompt()
        menu_state = MenuState(user_requirement=state["user_requirement"])
        return {
            "memory_context": memory_context,
            "menu_state": menu_state,
        }

    def _plan_menu(self, state: RecipeGraphState) -> RecipeGraphState:
        menu_state = state["menu_state"]
        menu_state.dish_list = self.agent.planner.plan_todo_list(
            menu_state,
            state.get("memory_context", "暂无长期记忆。"),
        )
        self.agent._drain_tool_events(menu_state)

        if not menu_state.dish_list:
            menu_state.dish_list = [self.agent.planner.create_fallback_task(menu_state)]

        return {"menu_state": menu_state}

    def _retrieve_recipes(self, state: RecipeGraphState) -> RecipeGraphState:
        menu_state = state["menu_state"]
        dish_contexts: dict[int, str] = {}
        search_backends: dict[int, str] = {}
        errors = list(state.get("errors") or [])

        for task in menu_state.dish_list:
            try:
                sources_summary, context, backend = self._retrieve_one_task(task)
                task.sources_summary = sources_summary
                if not task.ingredients:
                    task.ingredients = extract_serving_ingredients(context)
                dish_contexts[task.id] = context
                search_backends[task.id] = backend
                menu_state.all_search_context.append(context)
            except Exception as exc:  # pragma: no cover - defensive guardrail
                logger.exception("Graph recipe retrieval failed for task %s", task.id)
                task.status = "skipped"
                errors.append(f"task_{task.id}_retrieval_failed: {exc}")

        return {
            "menu_state": menu_state,
            "dish_contexts": dish_contexts,
            "search_backends": search_backends,
            "errors": errors,
        }

    def _summarize_dishes(self, state: RecipeGraphState) -> RecipeGraphState:
        menu_state = state["menu_state"]
        dish_contexts = state.get("dish_contexts") or {}
        errors = list(state.get("errors") or [])

        for task in menu_state.dish_list:
            context = dish_contexts.get(task.id)
            if not context:
                continue

            task.status = "in_progress"
            try:
                summary = self.agent.summarizer.summarize_task(menu_state, task, context)
                task.cook_steps = [summary]
                task.status = "completed"
                self.agent._drain_tool_events(menu_state)
            except Exception as exc:  # pragma: no cover - defensive guardrail
                logger.exception("Graph recipe summarization failed for task %s", task.id)
                task.status = "failed"
                errors.append(f"task_{task.id}_summary_failed: {exc}")

        return {"menu_state": menu_state, "errors": errors}

    def _build_shopping_list(self, state: RecipeGraphState) -> RecipeGraphState:
        menu_state = state["menu_state"]
        menu_state.shopping_list = build_shopping_list(menu_state.dish_list)
        return {"menu_state": menu_state}

    def _write_report(self, state: RecipeGraphState) -> RecipeGraphState:
        menu_state = state["menu_state"]
        report = self.agent.reporting.generate_report(menu_state)
        self.agent._drain_tool_events(menu_state)
        menu_state.final_menu_markdown = report
        return {"menu_state": menu_state}

    def _persist_report(self, state: RecipeGraphState) -> RecipeGraphState:
        menu_state = state["menu_state"]
        self.agent._persist_final_report(menu_state, menu_state.final_menu_markdown)
        output = MenuStateOutput(
            menu_markdown=menu_state.final_menu_markdown,
            dish_list=menu_state.dish_list,
            shopping_list=menu_state.shopping_list,
            total_calories=menu_state.total_calories,
        )
        return {"menu_state": menu_state, "final_output": output}

    def _retrieve_one_task(self, task: DishItem) -> tuple[str, str, str]:
        rag_payload = self._try_recipe_rag(task)
        if rag_payload:
            return rag_payload

        search_result, _notices, answer_text, backend = dispatch_search(
            task.query,
            self.agent.config,
            0,
        )
        if not search_result or not search_result.get("results"):
            return "", "", backend

        sources_summary, context = prepare_research_context(
            search_result,
            answer_text,
            self.agent.config,
        )
        return sources_summary, context, backend

    @staticmethod
    def _try_recipe_rag(task: DishItem) -> tuple[str, str, str] | None:
        try:
            limit = int(os.getenv("RECIPE_RAG_LIMIT", DEFAULT_RECIPE_RAG_LIMIT))
        except ValueError:
            limit = DEFAULT_RECIPE_RAG_LIMIT

        raw_threshold = os.getenv("RECIPE_RAG_SCORE_THRESHOLD")
        try:
            score_threshold = float(raw_threshold) if raw_threshold else None
        except ValueError:
            score_threshold = None

        try:
            results = get_recipe_rag_service().search(
                task.query,
                limit=limit,
                score_threshold=score_threshold,
            )
        except Exception as exc:
            logger.warning("Recipe RAG lookup failed; falling back to web search: %s", exc)
            return None

        if not results:
            return None

        context = format_recipe_context(results)
        source_lines = [
            f"- {result.dish_name or result.recipe_id} "
            f"({result.chunk_type or 'chunk'}, score={result.score:.4f})"
            for result in results
        ]
        sources_summary = "本地菜谱库 RAG 检索结果：\n" + "\n".join(source_lines)
        return sources_summary, context, "recipe_rag"


def create_recipe_graph(
    *,
    config: Configuration | None = None,
    memory_service: MemoryService | None = None,
) -> Any:
    """Create a compiled LangGraph recipe workflow."""
    return RecipeWorkflowGraph(config=config, memory_service=memory_service).app
