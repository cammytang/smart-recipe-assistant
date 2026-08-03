"""Orchestrator coordinating the deep research workflow."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from queue import Empty, Queue
from threading import Lock, Thread
from typing import Any, Callable, Iterator

from hello_agents import HelloAgentsLLM, ToolAwareSimpleAgent
from hello_agents.tools import ToolRegistry
from hello_agents.tools.builtin.note_tool import NoteTool

from config import Configuration
from prompts import (
    report_writer_instructions,
    task_summarizer_instructions,
    todo_planner_system_prompt,
)
from models import MenuState, MenuStateOutput, DishItem
from services.planner import PlanningService
from services.recipe_rag import format_recipe_context, get_recipe_rag_service
from services.reporter import ReportingService
from services.search import dispatch_search, prepare_research_context
from services.shopping_list import build_shopping_list, extract_serving_ingredients
from services.summarizer import SummarizationService
from services.tool_events import ToolCallTracker
from services.memory import MemoryService

logger = logging.getLogger(__name__)

DEFAULT_RECIPE_RAG_LIMIT = 5


class DeepResearchAgent:
    """Coordinator orchestrating TODO-based research workflow using HelloAgents."""

    def __init__(self, config: Configuration | None = None) -> None:
        """Initialise the coordinator with configuration and shared tools."""
        self.config = config or Configuration.from_env()
        self.llm = self._init_llm()

        self.note_tool = (
            NoteTool(workspace=self.config.notes_workspace)
            if self.config.enable_notes
            else None
        )
        self.tools_registry: ToolRegistry | None = None
        if self.note_tool:
            registry = ToolRegistry()
            registry.register_tool(self.note_tool)
            self.tools_registry = registry

        self._tool_tracker = ToolCallTracker(
            self.config.notes_workspace if self.config.enable_notes else None
        )
        self._tool_event_sink_enabled = False
        self._state_lock = Lock()

        self.todo_agent = self._create_tool_aware_agent(
            name="菜谱规划专家",
            system_prompt=todo_planner_system_prompt.strip(),
        )
        self.report_agent = self._create_tool_aware_agent(
            name="菜单撰写专家",
            system_prompt=report_writer_instructions.strip(),
        )

        self._summarizer_factory: Callable[[], ToolAwareSimpleAgent] = lambda: self._create_tool_aware_agent(  # noqa: E501
            name="菜品信息提炼专家",
            system_prompt=task_summarizer_instructions.strip(),
        )

        self.planner = PlanningService(self.todo_agent, self.config)
        self.summarizer = SummarizationService(self._summarizer_factory, self.config)
        self.reporting = ReportingService(self.report_agent, self.config)
        self.memory = MemoryService()
        self._last_search_notices: list[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def _init_llm(self) -> HelloAgentsLLM:
        """Instantiate HelloAgentsLLM following configuration preferences."""
        llm_kwargs: dict[str, Any] = {"temperature": 0.0}

        model_id = self.config.llm_model_id or self.config.local_llm
        if model_id:
            llm_kwargs["model"] = model_id

        provider = (self.config.llm_provider or "").strip()
        if provider:
            llm_kwargs["provider"] = provider

        if provider == "ollama":
            llm_kwargs["base_url"] = self.config.sanitized_ollama_url()
            if self.config.llm_api_key:
                llm_kwargs["api_key"] = self.config.llm_api_key
            else:
                llm_kwargs["api_key"] = "ollama"
        elif provider == "lmstudio":
            llm_kwargs["base_url"] = self.config.lmstudio_base_url
            if self.config.llm_api_key:
                llm_kwargs["api_key"] = self.config.llm_api_key
        else:
            if self.config.llm_base_url:
                llm_kwargs["base_url"] = self.config.llm_base_url
            if self.config.llm_api_key:
                llm_kwargs["api_key"] = self.config.llm_api_key

        return HelloAgentsLLM(**llm_kwargs)

    def _create_tool_aware_agent(self, *, name: str, system_prompt: str) -> ToolAwareSimpleAgent:
        """Instantiate a ToolAwareSimpleAgent sharing tool registry and tracker."""
        return ToolAwareSimpleAgent(
            name=name,
            llm=self.llm,
            system_prompt=system_prompt,
            enable_tool_calling=self.tools_registry is not None,
            tool_registry=self.tools_registry,
            tool_call_listener=self._tool_tracker.record,
        )

    def _set_tool_event_sink(self, sink: Callable[[dict[str, Any]], None] | None) -> None:
        """Enable or disable immediate tool event callbacks."""
        self._tool_event_sink_enabled = sink is not None
        self._tool_tracker.set_event_sink(sink)

    def run(self, topic: str) -> MenuStateOutput:
        """Execute the research workflow and return the final report."""
        state = MenuState(user_requirement=topic)
        state.dish_list = self.planner.plan_todo_list(
            state,
            self.memory.format_memory_for_prompt(),
        )
        self._drain_tool_events(state)

        if not state.dish_list:
            logger.info("No TODO items generated; falling back to single task")
            state.dish_list = [self.planner.create_fallback_task(state)]

        for task in state.dish_list:
            for _ in self._execute_task(state, task, emit_stream=False):
                pass

        state.shopping_list = build_shopping_list(state.dish_list)
        report = self.reporting.generate_report(state)
        self._drain_tool_events(state)
        # state.structured_report = report
        # state.running_summary = report
        self._persist_final_report(state, report)

        return MenuStateOutput(
            menu_markdown=report,
            dish_list=state.dish_list,
            shopping_list=state.shopping_list,
            total_calories=state.total_calories
        )

    def plan_menu(self, topic: str, user_memory: str | None = None) -> list[dict[str, Any]]:
        """Plan menu dishes without executing search and summarization."""
        state = MenuState(user_requirement=topic)
        memory_context = user_memory or self.memory.format_memory_for_prompt()
        state.dish_list = self.planner.plan_todo_list(state, memory_context)
        self._drain_tool_events(state, step=0)
        if not state.dish_list:
            state.dish_list = [self.planner.create_fallback_task(state)]
        return [self._serialize_task(task) for task in state.dish_list]

    def run_stream(
        self,
        topic: str,
        dish_list: list[DishItem] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Execute the workflow yielding incremental progress events."""
        state = MenuState(user_requirement=topic)
        logger.debug("Starting streaming research: topic=%s", topic)
        yield {"type": "status", "message": "初始化菜谱分析流程"}

        if dish_list is None:
            state.dish_list = self.planner.plan_todo_list(
                state,
                self.memory.format_memory_for_prompt(),
            )
            for event in self._drain_tool_events(state, step=0):
                yield event
            if not state.dish_list:
                state.dish_list = [self.planner.create_fallback_task(state)]
        else:
            state.dish_list = dish_list

        channel_map: dict[int, dict[str, Any]] = {}
        for index, task in enumerate(state.dish_list, start=1):
            token = f"task_{task.id}"
            task.stream_token = token
            channel_map[task.id] = {"step": index, "token": token}

        yield {
            "type": "todo_list",
            "tasks": [self._serialize_task(t) for t in state.dish_list],
            "step": 0,
        }

        event_queue: Queue[dict[str, Any]] = Queue()

        def enqueue(
            event: dict[str, Any],
            *,
            task: DishItem | None = None,
            step_override: int | None = None,
        ) -> None:
            payload = dict(event)
            target_task_id = payload.get("task_id")
            if task is not None:
                target_task_id = task.id
                payload["task_id"] = task.id

            channel = channel_map.get(target_task_id) if target_task_id is not None else None
            if channel:
                payload.setdefault("step", channel["step"])
                payload["stream_token"] = channel["token"]
            if step_override is not None:
                payload["step"] = step_override
            event_queue.put(payload)

        def tool_event_sink(event: dict[str, Any]) -> None:
            enqueue(event)

        self._set_tool_event_sink(tool_event_sink)

        threads: list[Thread] = []

        def worker(task: DishItem, step: int) -> None:
            try:
                enqueue(
                    {
                        "type": "task_status",
                        "task_id": task.id,
                        "status": "in_progress",
                        "title": task.name,
                        "intent": task.intent,
                        "note_id": task.note_id,
                        "note_path": task.note_path,
                    },
                    task=task,
                )

                for event in self._execute_task(state, task, emit_stream=True, step=step):
                    enqueue(event, task=task)
            except Exception as exc:  # pragma: no cover - defensive guardrail
                logger.exception("Task execution failed", exc_info=exc)
                enqueue(
                    {
                        "type": "task_status",
                        "task_id": task.id,
                        "status": "failed",
                        "detail": str(exc),
                        "title": task.name,
                        "intent": task.intent,
                        "note_id": task.note_id,
                        "note_path": task.note_path,
                    },
                    task=task,
                )
            finally:
                enqueue({"type": "__task_done__", "task_id": task.id})

        for task in state.dish_list:
            step = channel_map.get(task.id, {}).get("step", 0)
            thread = Thread(target=worker, args=(task, step), daemon=True)
            threads.append(thread)
            thread.start()

        active_workers = len(state.dish_list)
        finished_workers = 0

        try:
            while finished_workers < active_workers:
                event = event_queue.get()
                if event.get("type") == "__task_done__":
                    finished_workers += 1
                    continue
                yield event

            while True:
                try:
                    event = event_queue.get_nowait()
                except Empty:
                    break
                if event.get("type") != "__task_done__":
                    yield event
        finally:
            self._set_tool_event_sink(None)
            for thread in threads:
                thread.join()

        state.shopping_list = build_shopping_list(state.dish_list)
        yield {
            "type": "shopping_list",
            "items": state.shopping_list,
            "step": len(state.dish_list) + 1,
        }

        report = self.reporting.generate_report(state)
        final_step = len(state.dish_list) + 1
        for event in self._drain_tool_events(state, step=final_step):
            yield event
        state.structured_report = report
        state.running_summary = report

        note_event = self._persist_final_report(state, report)
        if note_event:
            yield note_event

        yield {
            "type": "final_report",
            "report": report,
            "note_id": state.report_note_id,
            "note_path": state.report_note_path,
        }
        yield {"type": "done"}

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------
    def _execute_task(
        self,
        state: MenuState,
        task: DishItem,
        *,
        emit_stream: bool,
        step: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Run search + summarization for a single task."""
        task.status = "in_progress"

        notices: list[str] = []
        rag_payload = self._try_recipe_rag(task)

        if rag_payload:
            sources_summary, context, backend = rag_payload
            self._last_search_notices = []
            task.notices = []
        else:
            search_result, notices, answer_text, backend = dispatch_search(
                task.query,
                self.config,
                0, # 菜谱不需要迭代
            )
            self._last_search_notices = notices
            task.notices = notices

            if emit_stream:
                for event in self._drain_tool_events(state, step=step):
                    yield event
            else:
                self._drain_tool_events(state)

            if notices and emit_stream:
                for notice in notices:
                    if notice:
                        yield {
                            "type": "status",
                            "message": notice,
                            "task_id": task.id,
                            "step": step,
                        }

            if not search_result or not search_result.get("results"):
                task.status = "skipped"
                if emit_stream:
                    for event in self._drain_tool_events(state, step=step):
                        yield event
                    yield {
                        "type": "task_status",
                        "task_id": task.id,
                        "status": "skipped",
                        "title": task.name,
                        "intent": task.intent,
                        "note_id": task.note_id,
                        "note_path": task.note_path,
                        "step": step,
                    }
                else:
                    self._drain_tool_events(state)
                return
            else:
                if not emit_stream:
                    self._drain_tool_events(state)

            sources_summary, context = prepare_research_context(
                search_result,
                answer_text,
                self.config,
            )

        task.sources_summary = sources_summary
        if not task.ingredients:
            task.ingredients = extract_serving_ingredients(context)

        with self._state_lock:
            # state.web_research_results.append(context)
            # state.sources_gathered.append(sources_summary)
            # state.research_loop_count += 1
            state.all_search_context.append(context)

        summary_text: str | None = None

        if emit_stream:
            for event in self._drain_tool_events(state, step=step):
                yield event
            yield {
                "type": "sources",
                "task_id": task.id,
                "latest_sources": sources_summary,
                "raw_context": context,
                "step": step,
                "backend": backend,
                "note_id": task.note_id,
                "note_path": task.note_path,
            }

            summary_stream, summary_getter = self.summarizer.stream_task_summary(state, task, context)
            try:
                for event in self._drain_tool_events(state, step=step):
                    yield event
                for chunk in summary_stream:
                    if chunk:
                        yield {
                            "type": "task_summary_chunk",
                            "task_id": task.id,
                            "content": chunk,
                            "note_id": task.note_id,
                            "step": step,
                        }
                    for event in self._drain_tool_events(state, step=step):
                        yield event
            finally:
                summary_text = summary_getter()
        else:
            summary_text = self.summarizer.summarize_task(state, task, context)
            self._drain_tool_events(state)

        # task.summary = summary_text.strip() if summary_text else "暂无可用信息"
        task.status = "completed"

        if emit_stream:
            for event in self._drain_tool_events(state, step=step):
                yield event
            yield {
                "type": "task_status",
                "task_id": task.id,
                "status": "completed",
                "summary": summary_text if summary_text else "暂无可用信息",
                "sources_summary": task.sources_summary,
                "note_id": task.note_id,
                "note_path": task.note_path,
                "step": step,
            }
        else:
            self._drain_tool_events(state)

    def _try_recipe_rag(self, task: DishItem) -> tuple[str, str, str] | None:
        """Try local recipe RAG before falling back to web search."""
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

    def _drain_tool_events(
        self,
        state: MenuState,
        *,
        step: int | None = None,
    ) -> list[dict[str, Any]]:
        """Proxy to the shared tool call tracker."""
        events = self._tool_tracker.drain(state, step=step)
        if self._tool_event_sink_enabled:
            return []
        return events

    @property
    def _tool_call_events(self) -> list[dict[str, Any]]:
        """Expose recorded tool events for legacy integrations."""
        return self._tool_tracker.as_dicts()

    def _serialize_task(self, task: DishItem) -> dict[str, Any]:
        """Convert task dataclass to serializable dict for frontend."""
        return {
            "id": task.id,
            "name": task.name,
            "intent": task.intent,
            "query": task.query,
            "status": task.status,
            # "summary": task.summary,
            # "sources_summary": task.sources_summary,
            "note_id": task.note_id,
            "note_path": task.note_path,
            "stream_token": task.stream_token,
            "memory_used": task.memory_used,
            "memory_conflicts": task.memory_conflicts,
        }
    
    #  id: int
    # name: str
    # intent: str
    # query: str
    # status: str = field(default="pending")
    # # 运行后回填结果
    # ingredients: list[str] = None   # 食材列表
    # cook_steps: list[str] = None
    # cook_time: str = ""
    # calories: int = 0               # 卡路里
    # tips: str = ""
    # source_links: list[str] = None  # 参考菜谱来源

    def _persist_final_report(self, state: MenuState, report: str) -> dict[str, Any] | None:
        if not self.note_tool or not report or not report.strip():
            return None

        note_title = f"研究报告：{state.user_requirement}".strip() or "研究报告"
        tags = ["deep_research", "report"]
        content = report.strip()

        note_id = self._find_existing_report_note_id(state)
        response = ""

        if note_id:
            response = self.note_tool.run(
                {
                    "action": "update",
                    "note_id": note_id,
                    "title": note_title,
                    "note_type": "conclusion",
                    "tags": tags,
                    "content": content,
                }
            )
            if response.startswith("❌"):
                note_id = None

        if not note_id:
            response = self.note_tool.run(
                {
                    "action": "create",
                    "title": note_title,
                    "note_type": "conclusion",
                    "tags": tags,
                    "content": content,
                }
            )
            note_id = self._extract_note_id_from_text(response)

        if not note_id:
            return None

        state.report_note_id = note_id
        if self.config.notes_workspace:
            note_path = Path(self.config.notes_workspace) / f"{note_id}.md"
            state.report_note_path = str(note_path)
        else:
            note_path = None

        payload = {
            "type": "report_note",
            "note_id": note_id,
            "title": note_title,
            "content": content,
        }
        if note_path:
            payload["note_path"] = str(note_path)

        return payload

    def _find_existing_report_note_id(self, state: MenuState) -> str | None:
        if state.report_note_id:
            return state.report_note_id

        for event in reversed(self._tool_tracker.as_dicts()):
            if event.get("tool") != "note":
                continue

            parameters = event.get("parsed_parameters") or {}
            if not isinstance(parameters, dict):
                continue

            action = parameters.get("action")
            if action not in {"create", "update"}:
                continue

            note_type = parameters.get("note_type")
            if note_type != "conclusion":
                title = parameters.get("title")
                if not (isinstance(title, str) and title.startswith("研究报告")):
                    continue

            note_id = parameters.get("note_id")
            if not note_id:
                note_id = self._tool_tracker._extract_note_id(event.get("result", ""))  # type: ignore[attr-defined]

            if note_id:
                return note_id

        return None

    @staticmethod
    def _extract_note_id_from_text(response: str) -> str | None:
        if not response:
            return None

        match = re.search(r"ID:\s*([^\n]+)", response)
        if not match:
            return None

        return match.group(1).strip()


def run_deep_research(topic: str, config: Configuration | None = None) -> MenuStateOutput:
    """Convenience function mirroring the class-based API."""
    agent = DeepResearchAgent(config=config)
    return agent.run(topic)
