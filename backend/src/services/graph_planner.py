"""Service entrypoint for the LangGraph recipe assistant variant."""

from __future__ import annotations

from config import Configuration
from graphs.recipe_graph import RecipeWorkflowGraph
from models import MenuStateOutput
from services.memory import MemoryService


class GraphRecipeAgent:
    """Parallel LangGraph implementation of the recipe assistant workflow."""

    def __init__(
        self,
        config: Configuration | None = None,
        memory_service: MemoryService | None = None,
    ) -> None:
        self.workflow = RecipeWorkflowGraph(
            config=config,
            memory_service=memory_service,
        )

    def run(self, topic: str) -> MenuStateOutput:
        """Run the LangGraph workflow for one user requirement."""
        return self.workflow.invoke(topic)


def run_graph_recipe_agent(
    topic: str,
    config: Configuration | None = None,
    memory_service: MemoryService | None = None,
) -> MenuStateOutput:
    """Convenience function mirroring agent.run_deep_research."""
    return GraphRecipeAgent(config=config, memory_service=memory_service).run(topic)
