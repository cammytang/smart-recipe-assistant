from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams


BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_PATH = BACKEND_DIR / "original_data" / "data" / "dishes.json"
DEFAULT_QDRANT_PATH = BACKEND_DIR / "qdrant_data"
DEFAULT_COLLECTION = "recipes"
DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_DASHSCOPE_MODEL = "text-embedding-v4"


def stable_point_id(value: str) -> int:
    """Create a deterministic unsigned 64-bit id accepted by Qdrant."""
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def join_items(items: Iterable[str]) -> str:
    return "、".join(item.strip() for item in items if item and item.strip())


def build_chunk_text(recipe: dict[str, Any], chunk_type: str, body: str) -> str:
    base = [
        f"菜名：{recipe.get('dish_name', '')}",
        f"分类：{recipe.get('category', '')}",
        f"片段类型：{chunk_type}",
        body.strip(),
    ]
    return "\n".join(part for part in base if part).strip()


def build_recipe_chunks(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    """Build semantic chunks from one structured recipe."""
    chunks: list[dict[str, Any]] = []

    summary_parts = [
        f"简介：{recipe.get('description', '')}",
        f"难度：{recipe.get('difficulty', '')}",
        f"热量：{recipe.get('calories', '')}",
    ]
    summary_body = "\n".join(part for part in summary_parts if not part.endswith("："))
    if summary_body:
        chunks.append(
            {
                "chunk_type": "summary",
                "text": build_chunk_text(recipe, "summary", summary_body),
            }
        )

    ingredients = join_items(recipe.get("ingredients", []))
    serving_ingredients = join_items(recipe.get("serving_ingredients", []))
    ingredient_body = "\n".join(
        part
        for part in [
            f"必备原料和工具：{ingredients}" if ingredients else "",
            f"每份用量：{serving_ingredients}" if serving_ingredients else "",
        ]
        if part
    )
    if ingredient_body:
        chunks.append(
            {
                "chunk_type": "ingredients",
                "text": build_chunk_text(recipe, "ingredients", ingredient_body),
            }
        )

    steps = recipe.get("steps") or []
    if steps:
        step_lines = [f"{idx}. {step}" for idx, step in enumerate(steps, start=1)]
        chunks.append(
            {
                "chunk_type": "steps",
                "text": build_chunk_text(recipe, "steps", "烹饪步骤：\n" + "\n".join(step_lines)),
            }
        )

    tips = recipe.get("tips") or []
    if tips:
        chunks.append(
            {
                "chunk_type": "tips",
                "text": build_chunk_text(recipe, "tips", f"附加内容：{join_items(tips)}"),
            }
        )

    search_text = recipe.get("search_text")
    if search_text:
        chunks.append(
            {
                "chunk_type": "full",
                "text": build_chunk_text(recipe, "full", search_text),
            }
        )

    for chunk_index, chunk in enumerate(chunks):
        chunk["chunk_index"] = chunk_index
        chunk["recipe_id"] = recipe.get("id")
        chunk["dish_name"] = recipe.get("dish_name")
        chunk["category"] = recipe.get("category")
        chunk["source_path"] = recipe.get("source_path")

    return chunks


def load_recipes(data_path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    with data_path.open("r", encoding="utf-8") as f:
        recipes = json.load(f)

    if not isinstance(recipes, list):
        raise ValueError(f"{data_path} should contain a JSON array.")

    return recipes[:limit] if limit else recipes


def ensure_collection(
    client: QdrantClient,
    collection_name: str,
    vector_size: int,
    recreate: bool,
) -> None:
    exists = client.collection_exists(collection_name)
    if exists and recreate:
        client.delete_collection(collection_name)
        exists = False

    if not exists:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )


def get_embedding_client(args: argparse.Namespace) -> OpenAI:
    """Create an OpenAI-compatible embedding client."""
    api_key = args.api_key or os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    base_url = args.base_url or os.getenv("EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL")

    if not api_key:
        raise ValueError(
            "Missing embedding API key. Set EMBEDDING_API_KEY, OPENAI_API_KEY, or LLM_API_KEY."
        )

    return OpenAI(api_key=api_key, base_url=base_url)


def resolve_embedding_model(args: argparse.Namespace) -> str:
    """Resolve embedding model after .env is loaded."""
    if args.model:
        return args.model

    env_model = os.getenv("EMBEDDING_MODEL")
    if env_model:
        return env_model

    base_url = args.base_url or os.getenv("EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL") or ""
    if "dashscope.aliyuncs.com" in base_url:
        return DEFAULT_DASHSCOPE_MODEL

    return DEFAULT_MODEL


def embed_texts(
    embedding_client: OpenAI,
    model: str,
    texts: list[str],
    batch_size: int,
) -> list[list[float]]:
    vectors: list[list[float]] = []
    total = len(texts)
    batch_size = min(batch_size, 10)

    for start in range(0, total, batch_size):
        batch = texts[start : start + batch_size]
        response = embedding_client.embeddings.create(model=model, input=batch)
        vectors.extend(item.embedding for item in response.data)
        print(f"Embedding progress: {min(start + batch_size, total)}/{total}")

    return vectors


def build_points(
    recipes: list[dict[str, Any]],
    embedding_client: OpenAI,
    embedding_model: str,
    batch_size: int,
) -> list[PointStruct]:
    chunks = [chunk for recipe in recipes for chunk in build_recipe_chunks(recipe)]
    texts = [chunk["text"] for chunk in chunks]
    vectors = embed_texts(embedding_client, embedding_model, texts, batch_size)

    points: list[PointStruct] = []
    for chunk, vector in zip(chunks, vectors):
        recipe_id = chunk.get("recipe_id") or chunk.get("source_path") or chunk.get("dish_name")
        chunk_key = f"{recipe_id}:{chunk['chunk_type']}:{chunk['chunk_index']}"
        payload = {
            "text": chunk["text"],
            "recipe_id": chunk.get("recipe_id"),
            "dish_name": chunk.get("dish_name"),
            "category": chunk.get("category"),
            "chunk_type": chunk.get("chunk_type"),
            "chunk_index": chunk.get("chunk_index"),
            "source_path": chunk.get("source_path"),
        }
        points.append(
            PointStruct(
                id=stable_point_id(chunk_key),
                vector=vector,
                payload=payload,
            )
        )

    return points


def index_recipes(args: argparse.Namespace) -> None:
    data_path = Path(args.data_path).resolve()
    qdrant_path = Path(args.qdrant_path).resolve()

    recipes = load_recipes(data_path, args.limit)
    if not recipes:
        raise ValueError(f"No recipes found in {data_path}.")

    embedding_model = resolve_embedding_model(args)
    embedding_client = get_embedding_client(args)
    sample_vector = embed_texts(embedding_client, embedding_model, [recipes[0]["search_text"]], 1)[0]
    vector_size = len(sample_vector)

    qdrant_path.mkdir(parents=True, exist_ok=True)
    client = QdrantClient(path=str(qdrant_path))
    ensure_collection(client, args.collection, vector_size, args.recreate)

    points = build_points(recipes, embedding_client, embedding_model, args.batch_size)
    client.upsert(collection_name=args.collection, points=points)

    print(f"菜谱数量：{len(recipes)}")
    print(f"Chunk 数量：{len(points)}")
    print(f"Collection：{args.collection}")
    print(f"Embedding 模型：{embedding_model}")
    print(f"Qdrant 路径：{qdrant_path}")
    print("入库完成")


def parse_args() -> argparse.Namespace:
    load_dotenv(BACKEND_DIR / ".env")

    parser = argparse.ArgumentParser(description="Index recipe JSON chunks into local Qdrant.")
    parser.add_argument("--data-path", default=str(DEFAULT_DATA_PATH), help="Path to dishes.json.")
    parser.add_argument("--qdrant-path", default=str(DEFAULT_QDRANT_PATH), help="Local Qdrant data path.")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help="Qdrant collection name.")
    parser.add_argument("--model", default=None, help="Embedding model name. Defaults to EMBEDDING_MODEL or provider default.")
    parser.add_argument("--api-key", default=None, help="Embedding API key. Defaults to env.")
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible embedding base URL. Defaults to env.")
    parser.add_argument("--batch-size", type=int, default=10, help="Embedding batch size. DashScope supports up to 10.")
    parser.add_argument("--limit", type=int, default=None, help="Index only first N recipes for testing.")
    parser.add_argument("--recreate", action="store_true", help="Delete and recreate collection before indexing.")
    return parser.parse_args()


if __name__ == "__main__":
    index_recipes(parse_args())
