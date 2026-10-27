"""Embeddings + vector search. In-memory for learning; Azure AI Search or Cosmos DB vector search for real use."""
from __future__ import annotations

import os

from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.vectorstores import InMemoryVectorStore


def make_embeddings():
    """EMBEDDINGS_PROVIDER=azure uses your Azure OpenAI embedding deployment (set AZURE_OPENAI_EMBEDDING_DEPLOYMENT).
    Anything else uses fake embeddings: same plumbing, but similarity is meaningless. For offline tests only."""
    if os.getenv("EMBEDDINGS_PROVIDER") == "azure":
        from langchain_openai import OpenAIEmbeddings
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
        return OpenAIEmbeddings(model=os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
                                base_url=f"{endpoint}/openai/v1/",
                                api_key=os.environ["AZURE_OPENAI_API_KEY"],
                                check_embedding_ctx_length=False)
    return DeterministicFakeEmbedding(size=256)


def build_store(chunks: list[dict], embeddings) -> InMemoryVectorStore:
    store = InMemoryVectorStore(embeddings)
    store.add_documents([Document(page_content=c["text"], metadata={**c["metadata"], "chunk_id": c["id"]}) for c in chunks])
    return store


def retrieve(store: InMemoryVectorStore, query: str, k: int = 3) -> list[dict]:
    hits = store.similarity_search_with_score(query, k=k)
    return [{"chunk_id": d.metadata["chunk_id"], "clause": d.metadata.get("clause"), "score": round(float(s), 4),
             "text": d.page_content} for d, s in hits]


def recall_at_k(store: InMemoryVectorStore, labelled: list[dict], k: int = 3) -> float:
    """How often does the right clause appear in the top k results?
    labelled: [{'query': 'Is hernia covered in year one?', 'relevant_clause': 'Waiting periods'}, ...]"""
    hits = 0
    for item in labelled:
        found = retrieve(store, item["query"], k=k)
        if any(h["clause"] == item["relevant_clause"] for h in found):
            hits += 1
    return round(hits / len(labelled), 3)
