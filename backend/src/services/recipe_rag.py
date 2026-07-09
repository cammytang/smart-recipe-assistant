"""Recipe RAG retrieval service backed by local Qdrant."""

from __future__ import annotations

import atexit
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse


BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_QDRANT_PATH = BACKEND_DIR / "qdrant_data"
DEFAULT_COLLECTION = "recipes"
DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_DASHSCOPE_MODEL = "text-embedding-v4"


@dataclass
class RecipeSearchResult:
    score: float
    text: str
    recipe_id: Optional[str]
    dish_name: Optional[str]
    category: Optional[str]
    chunk_type: Optional[str]
    source_path: Optional[str]

    @classmethod
    def from_qdrant_point(cls, point: Any) -> "RecipeSearchResult":
        payload = point.payload or {}
        return cls(
            score=float(point.score),
            text=str(payload.get("text") or ""),
            recipe_id=payload.get("recipe_id"),
            dish_name=payload.get("dish_name"),
            category=payload.get("category"),
            chunk_type=payload.get("chunk_type"),
            source_path=payload.get("source_path"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "text": self.text,
            "recipe_id": self.recipe_id,
            "dish_name": self.dish_name,
            "category": self.category,
            "chunk_type": self.chunk_type,
            "source_path": self.source_path,
        }


class RecipeRAGService:
    """Search recipe chunks from the local Qdrant collection."""

    def __init__(
        self,
        collection_name: str = DEFAULT_COLLECTION,
        qdrant_path: str | Path = DEFAULT_QDRANT_PATH,
        embedding_model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        load_dotenv(BACKEND_DIR / ".env")

        self.collection_name = collection_name
        self.qdrant_path = Path(qdrant_path)
        self.embedding_model = embedding_model or resolve_embedding_model(base_url)
        self.embedding_client = OpenAI(
            api_key=resolve_api_key(api_key),
            base_url=resolve_base_url(base_url),
        )
        self.qdrant_client = QdrantClient(path=str(self.qdrant_path))
        self._closed = False
        atexit.register(self.close)

    def embed_query(self, query: str) -> list[float]:
        query = query.strip()
        if not query:
            raise ValueError("Query cannot be empty.")

        response = self.embedding_client.embeddings.create(
            model=self.embedding_model,
            input=[query],
        )
        return response.data[0].embedding

    def search(
        self,
        query: str,
        limit: int = 5,
        score_threshold: Optional[float] = None,
    ) -> list[RecipeSearchResult]:
        """Vector search recipe chunks by a natural language query."""
        if not self.qdrant_client.collection_exists(self.collection_name):
            raise ValueError(
                f"Qdrant collection '{self.collection_name}' does not exist. "
                "Run scripts/index_recipes.py --recreate first."
            )

        query_vector = self.embed_query(query)
        points = self._search_points(query_vector, limit, score_threshold)
        return [RecipeSearchResult.from_qdrant_point(point) for point in points]

    def build_context(
        self,
        query: str,
        limit: int = 5,
        score_threshold: Optional[float] = None,
    ) -> str:
        """Return retrieved chunks as prompt-ready context text."""
        results = self.search(query=query, limit=limit, score_threshold=score_threshold)
        return format_recipe_context(results)

    def close(self) -> None:
        """Close Qdrant resources before Python interpreter shutdown."""
        if self._closed:
            return
        self.qdrant_client.close()
        self._closed = True

    def _search_points(
        self,
        query_vector: list[float],
        limit: int,
        score_threshold: Optional[float],
    ) -> list[Any]:
        try:
            return self.qdrant_client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit,
                score_threshold=score_threshold,
                with_payload=True,
                with_vectors=False,
            )
        except AttributeError:
            response = self.qdrant_client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=limit,
                score_threshold=score_threshold,
                with_payload=True,
                with_vectors=False,
            )
            return list(response.points)
        except UnexpectedResponse as exc:
            raise RuntimeError(f"Qdrant search failed: {exc}") from exc


def resolve_api_key(api_key: Optional[str] = None) -> str:
    resolved = api_key or os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not resolved:
        raise ValueError("Missing embedding API key. Set EMBEDDING_API_KEY, OPENAI_API_KEY, or LLM_API_KEY.")
    return resolved


def resolve_base_url(base_url: Optional[str] = None) -> Optional[str]:
    return base_url or os.getenv("EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL")


def resolve_embedding_model(base_url: Optional[str] = None) -> str:
    env_model = os.getenv("EMBEDDING_MODEL")
    if env_model:
        return env_model

    resolved_base_url = resolve_base_url(base_url) or ""
    if "dashscope.aliyuncs.com" in resolved_base_url:
        return DEFAULT_DASHSCOPE_MODEL

    return DEFAULT_MODEL


def format_recipe_context(results: list[RecipeSearchResult]) -> str:
    if not results:
        return "未检索到相关菜谱。"

    blocks = []
    for index, result in enumerate(results, start=1):
        title = result.dish_name or result.recipe_id or "未知菜谱"
        meta = [
            f"相似度：{result.score:.4f}",
            f"分类：{result.category}" if result.category else "",
            f"片段：{result.chunk_type}" if result.chunk_type else "",
            f"来源：{result.source_path}" if result.source_path else "",
        ]
        blocks.append(
            "\n".join(
                [
                    f"[{index}] {title}",
                    "；".join(item for item in meta if item),
                    result.text,
                ]
            )
        )

    return "\n\n".join(blocks)


_DEFAULT_SERVICE: RecipeRAGService | None = None


def get_recipe_rag_service() -> RecipeRAGService:
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        _DEFAULT_SERVICE = RecipeRAGService()
    return _DEFAULT_SERVICE


def search_recipes(
    query: str,
    limit: int = 5,
    score_threshold: Optional[float] = None,
) -> list[dict[str, Any]]:
    """Convenience function for API/agent code."""
    service = get_recipe_rag_service()
    return [
        result.to_dict()
        for result in service.search(
            query=query,
            limit=limit,
            score_threshold=score_threshold,
        )
    ]


def build_recipe_context(
    query: str,
    limit: int = 5,
    score_threshold: Optional[float] = None,
) -> str:
    """Convenience function returning prompt-ready retrieved context."""
    service = get_recipe_rag_service()
    return service.build_context(
        query=query,
        limit=limit,
        score_threshold=score_threshold,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Search recipe chunks from Qdrant.")
    parser.add_argument("query", help="Natural language recipe query.")
    parser.add_argument("--limit", type=int, default=5, help="Number of chunks to retrieve.")
    parser.add_argument("--score-threshold", type=float, default=None, help="Optional minimum similarity score.")
    args = parser.parse_args()

    service = RecipeRAGService()
    try:
        print(service.build_context(args.query, limit=args.limit, score_threshold=args.score_threshold))
    finally:
        service.close()
