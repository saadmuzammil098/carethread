"""Threshold and wiring tests only, no real embedding model or Chroma
index built here (same "offline, fast" precedent RxGround's own CI
already follows for the identical reason, see its ci.yml's per-task
comments): downloading BAAI/bge-base-en-v1.5 in CI would work but adds
minutes and a network dependency to every PR for logic that's actually
pure math plus a threshold comparison.
"""
from src import guideline_rag


class _FakeCollection:
    def __init__(self, ids, distances, documents, metadatas):
        self._ids = ids
        self._distances = distances
        self._documents = documents
        self._metadatas = metadatas

    def query(self, query_embeddings, n_results):
        return {
            "ids": [self._ids],
            "distances": [self._distances],
            "documents": [self._documents],
            "metadatas": [self._metadatas],
        }


class _FakeClient:
    def __init__(self, collection):
        self._collection = collection

    def list_collections(self):
        return [type("C", (), {"name": guideline_rag.COLLECTION_NAME})()]

    def get_collection(self, name):
        return self._collection


class _FakeEmbedding(list):
    def tolist(self):
        return list(self)


class _FakeEmbedder:
    def encode(self, texts, normalize_embeddings=True):
        return _FakeEmbedding([0.0] for _ in texts)


def test_retrieve_returns_result_above_threshold(monkeypatch):
    # distance=0.2 -> similarity = 1 - 0.2/2 = 0.9, above threshold
    fake_collection = _FakeCollection(
        ids=["heart-failure-follow-up"],
        distances=[0.2],
        documents=["Heart Failure: ..."],
        metadatas=[{"condition": "Heart Failure"}],
    )
    monkeypatch.setattr(guideline_rag, "get_client", lambda: _FakeClient(fake_collection))
    monkeypatch.setattr(guideline_rag, "get_embedder", lambda: _FakeEmbedder())

    result = guideline_rag.retrieve_guideline("how often for heart failure follow-up")
    assert result is not None
    assert result.guideline_id == "heart-failure-follow-up"
    assert result.similarity == 0.9


def test_retrieve_returns_none_below_threshold(monkeypatch):
    # distance=1.2 -> similarity = 1 - 1.2/2 = 0.4, below NOT_COVERED_THRESHOLD (0.55)
    fake_collection = _FakeCollection(
        ids=["heart-failure-follow-up"],
        distances=[1.2],
        documents=["Heart Failure: ..."],
        metadatas=[{"condition": "Heart Failure"}],
    )
    monkeypatch.setattr(guideline_rag, "get_client", lambda: _FakeClient(fake_collection))
    monkeypatch.setattr(guideline_rag, "get_embedder", lambda: _FakeEmbedder())

    result = guideline_rag.retrieve_guideline("what is the capital of France")
    assert result is None


def test_retrieve_returns_none_when_index_empty(monkeypatch):
    fake_collection = _FakeCollection(ids=[], distances=[], documents=[], metadatas=[])
    monkeypatch.setattr(guideline_rag, "get_client", lambda: _FakeClient(fake_collection))
    monkeypatch.setattr(guideline_rag, "get_embedder", lambda: _FakeEmbedder())

    result = guideline_rag.retrieve_guideline("anything")
    assert result is None
