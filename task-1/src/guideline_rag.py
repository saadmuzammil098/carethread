"""Small RAG index over CareThread's own clinical follow-up guidelines.

The guidelines in `task-3/guidelines/guidelines.json` are illustrative
reference text written for this project, paraphrased general clinical
guidance, not sourced from or attributed to any specific real guideline
body (matching RxGround's own scope: reference lookup, never diagnostic
or prescriptive advice, and never presented as an authoritative
clinical source). Their follow-up-interval numbers were written to
match `care_flagger.py`'s `FOLLOW_UP_WINDOWS_DAYS` table exactly, so
the agent can retrieve *why* a flag's window is what it is, grounded in
a cited guideline entry, not just surface the bare number Task 1
already computes.

Same shape as RxGround's index: sentence-transformers embeddings in a
Chroma collection, a similarity gate that refuses instead of guessing
when nothing relevant is indexed (`RxGround's README documents the
same threshold reasoning), same model (`BAAI/bge-base-en-v1.5`) for
stack consistency across every RAG index in this roadmap.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

GUIDELINES_PATH = (
    Path(__file__).resolve().parents[2] / "task-3" / "guidelines" / "guidelines.json"
)
COLLECTION_NAME = "carethread_guidelines"
EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
NOT_COVERED_THRESHOLD = 0.55

# Lambda's filesystem is read-only except /tmp (LAMBDA_TASK_ROOT is set
# by the runtime whenever this is actually running as a Lambda
# function). PersistentClient needs to write its sqlite file
# somewhere, and every cold start gets a fresh /tmp anyway, so the
# index rebuilds itself on first use in that environment, see
# build_index()'s call from retrieve_guideline() below.
_CHROMA_DB_PATH = (
    "/tmp/carethread_guideline_chroma_db"
    if os.environ.get("LAMBDA_TASK_ROOT")
    else str(Path(__file__).resolve().parents[1] / "guideline_chroma_db")
)

_embedder: SentenceTransformer | None = None
_client: chromadb.ClientAPI | None = None


def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(EMBEDDING_MODEL)
    return _embedder


def get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=_CHROMA_DB_PATH)
    return _client


def build_index() -> None:
    guidelines = json.loads(GUIDELINES_PATH.read_text())
    client = get_client()
    client.delete_collection(COLLECTION_NAME) if COLLECTION_NAME in {
        c.name for c in client.list_collections()
    } else None
    collection = client.create_collection(COLLECTION_NAME)

    embedder = get_embedder()
    texts = [f"{g['condition']}: {g['text']}" for g in guidelines]
    embeddings = embedder.encode(texts, normalize_embeddings=True).tolist()

    collection.add(
        ids=[g["id"] for g in guidelines],
        embeddings=embeddings,
        documents=texts,
        metadatas=[{"condition": g["condition"]} for g in guidelines],
    )


@dataclass
class GuidelineResult:
    guideline_id: str
    condition: str
    text: str
    similarity: float


def retrieve_guideline(query: str, top_k: int = 1) -> GuidelineResult | None:
    client = get_client()
    if COLLECTION_NAME not in {c.name for c in client.list_collections()}:
        build_index()
    collection = client.get_collection(COLLECTION_NAME)

    embedder = get_embedder()
    query_embedding = embedder.encode([query], normalize_embeddings=True).tolist()

    results = collection.query(query_embeddings=query_embedding, n_results=top_k)
    if not results["ids"] or not results["ids"][0]:
        return None

    # Chroma returns squared L2 distance for normalized embeddings;
    # cosine similarity = 1 - distance/2, same conversion RxGround's
    # own retrieve.py uses for the identical reason.
    distance = results["distances"][0][0]
    similarity = 1 - distance / 2

    if similarity < NOT_COVERED_THRESHOLD:
        return None

    return GuidelineResult(
        guideline_id=results["ids"][0][0],
        condition=results["metadatas"][0][0]["condition"],
        text=results["documents"][0][0],
        similarity=similarity,
    )
