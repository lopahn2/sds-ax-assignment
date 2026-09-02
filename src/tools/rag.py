from __future__ import annotations

from langchain_core.tools import tool

from .. import retriever

# ---------------------------------------------------------------------------
# retrieve_docs (RAG)
# ---------------------------------------------------------------------------


@tool
def retrieve_docs(query: str, k: int = 4) -> list[dict]:
    """벤치마크 리서치 문서 + 사내 정책 문서에서 근거 청크를 검색한다(BM25+TF-IDF 하이브리드+RRF). 복잡도·비용·정책 주장은 반드시 이 도구의 doc_id를 인용해야 한다."""
    return retriever.retrieve(query, k=k)
