from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import yaml
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .config import DOCS_DIR

_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")

# 구어체·오탈자 질의를 코퍼스 용어로 확장한다 (Day2 "쿼리 확장" 패턴).
_QUERY_EXPANSIONS = {
    "복잡": "복잡도 COMPLEX 축",
    "간단": "간단 SIMPLE 축",
    "왜": "이유 근거",
    "잔액": "잔액 예산 balance",
    "돈": "예산 비용",
    "취소": "취소 정책 캔슬",
    "나눠": "분해 FE BE 분리",
    "나누": "분해 FE BE 분리",
    "합쳐": "풀스택 통합",
    "슬롯": "슬롯 마감 동시 충돌",
    "가격": "가격 변동 프로모션가",
}


@dataclass
class Chunk:
    doc_id: str
    title: str
    text: str


def _expand_query(query: str) -> str:
    extra = [v for k, v in _QUERY_EXPANSIONS.items() if k in query]
    return query if not extra else query + " " + " ".join(extra)


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _parse_markdown(path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    meta = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return meta, body


def _load_chunks() -> list[Chunk]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800, chunk_overlap=120, separators=["\n## ", "\n### ", "\n\n", "\n", " "]
    )
    chunks: list[Chunk] = []
    for md_path in sorted(DOCS_DIR.rglob("*.md")):
        meta, body = _parse_markdown(md_path)
        doc_id = meta.get("doc_id", md_path.relative_to(DOCS_DIR).as_posix())
        title = meta.get("title", doc_id)
        for piece in splitter.split_text(body):
            piece = piece.strip()
            if piece:
                chunks.append(Chunk(doc_id=doc_id, title=title, text=piece))
    return chunks


class HybridRetriever:
    """BM25(키워드) + TF-IDF(벡터공간) 하이브리드 검색을 RRF로 결합한다.

    임베딩 API(Voyage/Bedrock 등) 없이도 동작하도록 밀집 신호는 TF-IDF 코사인 유사도로 대체했다.
    실제 임베딩 모델을 붙이려면 `_dense_scores()`만 교체하면 된다.
    """

    def __init__(self) -> None:
        self.chunks = _load_chunks()
        tokenized = [_tokenize(c.text) for c in self.chunks]
        self.bm25 = BM25Okapi(tokenized)
        self.vectorizer = TfidfVectorizer(tokenizer=_tokenize, lowercase=False)
        self.tfidf_matrix = self.vectorizer.fit_transform([c.text for c in self.chunks])

    def _bm25_ranks(self, query: str) -> list[int]:
        scores = self.bm25.get_scores(_tokenize(query))
        return sorted(range(len(scores)), key=lambda i: -scores[i])

    def _dense_scores(self, query: str):
        q_vec = self.vectorizer.transform([query])
        return cosine_similarity(q_vec, self.tfidf_matrix)[0]

    def _dense_ranks(self, query: str) -> list[int]:
        scores = self._dense_scores(query)
        return sorted(range(len(scores)), key=lambda i: -scores[i])

    def search(self, query: str, k: int = 4, rrf_k: int = 60) -> list[dict]:
        expanded = _expand_query(query)
        bm25_ranks = self._bm25_ranks(expanded)
        dense_ranks = self._dense_ranks(expanded)

        rrf_scores: dict[int, float] = {}
        for rank, idx in enumerate(bm25_ranks):
            rrf_scores[idx] = rrf_scores.get(idx, 0.0) + 1.0 / (rrf_k + rank + 1)
        for rank, idx in enumerate(dense_ranks):
            rrf_scores[idx] = rrf_scores.get(idx, 0.0) + 1.0 / (rrf_k + rank + 1)

        ranked = sorted(rrf_scores.items(), key=lambda kv: -kv[1])
        doc_counts: dict[str, int] = {}
        results = []
        for idx, score in ranked:
            chunk = self.chunks[idx]
            # 같은 문서의 청크가 상위권을 독점하지 않도록 문서당 최대 2개까지만 허용
            if doc_counts.get(chunk.doc_id, 0) >= 2:
                continue
            doc_counts[chunk.doc_id] = doc_counts.get(chunk.doc_id, 0) + 1
            results.append({"doc_id": chunk.doc_id, "title": chunk.title, "text": chunk.text, "score": round(score, 4)})
            if len(results) >= k:
                break
        return results


@lru_cache(maxsize=1)
def get_retriever() -> HybridRetriever:
    return HybridRetriever()


def retrieve(query: str, k: int = 4) -> list[dict]:
    return get_retriever().search(query, k=k)
