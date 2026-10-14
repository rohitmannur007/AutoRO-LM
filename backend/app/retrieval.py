"""Lexical BM25, local TF-IDF cosine, and reciprocal-rank-fusion hybrid.

TF-IDF is a classical vector index that ships with scikit-learn. It is not a
neural embedding model and does not download weights. If scikit-learn cannot
be imported, searches fall back to BM25.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from app.schemas import DocumentChunk, QAFilters, RetrievedChunk, SourceDocument
from app.textutil import find_dtcs, term_highlights, tokenize


def _tokens(text: str) -> list[str]:
    tokens = tokenize(text)
    # Keep DTC codes whole; the tokenizer already emits p0420 from "P0420".
    return tokens


@dataclass
class IndexedChunk:
    chunk: DocumentChunk
    document: SourceDocument
    tokens: list[str]


@dataclass
class RetrievalIndex:
    chunks: list[IndexedChunk] = field(default_factory=list)
    k1: float = 1.5
    b: float = 0.75
    fusion_k: int = 60
    vector_ready: bool = False
    _df: dict[str, int] = field(default_factory=dict)
    _avgdl: float = 0.0
    _tfidf: object | None = None
    _matrix: object | None = None

    def build(self, documents: list[SourceDocument], chunks: list[DocumentChunk]) -> None:
        by_id = {doc.document_id: doc for doc in documents}
        indexed: list[IndexedChunk] = []
        df: Counter[str] = Counter()
        total = 0
        for chunk in chunks:
            document = by_id.get(chunk.document_id)
            if document is None:
                continue
            tokens = _tokens(chunk.text)
            indexed.append(IndexedChunk(chunk=chunk, document=document, tokens=tokens))
            total += len(tokens)
            for token in set(tokens):
                df[token] += 1
        self.chunks = indexed
        self._df = dict(df)
        self._avgdl = (total / len(indexed)) if indexed else 0.0
        self._fit_tfidf()

    def _fit_tfidf(self) -> None:
        self.vector_ready = False
        self._tfidf = None
        self._matrix = None
        if not self.chunks:
            return
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
        except Exception:
            return
        corpus = [" ".join(item.tokens) for item in self.chunks]
        vectorizer = TfidfVectorizer(token_pattern=r"[a-z0-9]+")
        try:
            matrix = vectorizer.fit_transform(corpus)
        except ValueError:
            return
        self._tfidf = vectorizer
        self._matrix = matrix
        self.vector_ready = True

    def status(self) -> dict:
        return {
            "chunk_count": len(self.chunks),
            "lexical": "bm25",
            "vector": "tfidf_cosine" if self.vector_ready else "unavailable",
            "vector_is_neural": False,
            "hybrid": "reciprocal_rank_fusion" if self.vector_ready else "unavailable",
            "fusion_k": self.fusion_k,
            "bm25_k1": self.k1,
            "bm25_b": self.b,
        }

    def search(
        self,
        query: str,
        *,
        filters: QAFilters | None = None,
        top_k: int = 5,
        mode: str = "hybrid",
    ) -> tuple[list[RetrievedChunk], dict]:
        filters = filters or QAFilters()
        eligible = [item for item in self.chunks if _passes(item.document, item.chunk, filters)]
        excluded = len(self.chunks) - len(eligible)
        if not eligible:
            return [], {"excluded_by_filter": excluded, "mode": mode, "reason": "no chunks matched filters"}
        lexical = self._bm25(query, eligible)
        chosen_mode = mode
        if mode == "vector" and not self.vector_ready:
            chosen_mode = "lexical"
        if mode == "hybrid" and not self.vector_ready:
            chosen_mode = "lexical"
        vector_ranks: list[IndexedChunk] = []
        if chosen_mode in {"vector", "hybrid"} and self.vector_ready:
            vector_ranks = self._vector(query, eligible)
        if chosen_mode == "vector":
            ordered = vector_ranks
            score_of = {id(item): 1.0 / (index + 1) for index, item in enumerate(ordered)}
        elif chosen_mode == "hybrid":
            ordered, score_of = self._fuse(lexical, vector_ranks)
        else:
            ordered = [item for item, _score in lexical]
            score_of = {id(item): score for item, score in lexical}
        lexical_scores = {id(item): score for item, score in lexical}
        vector_scores = {}
        if vector_ranks and self.vector_ready:
            vector_scores = self._vector_scores(query, eligible)
        results: list[RetrievedChunk] = []
        for rank, item in enumerate(ordered[:top_k], start=1):
            score = float(score_of.get(id(item), 0.0))
            detail = {"bm25": float(lexical_scores.get(id(item), 0.0))}
            if id(item) in vector_scores:
                detail["tfidf_cosine"] = float(vector_scores[id(item)])
            if chosen_mode == "hybrid":
                detail["rrf"] = score
            results.append(
                RetrievedChunk(
                    chunk_id=item.chunk.chunk_id,
                    document_id=item.document.document_id,
                    text=item.chunk.text,
                    start_offset=item.chunk.start_offset,
                    end_offset=item.chunk.end_offset,
                    score=score,
                    rank=rank,
                    source_url=item.document.source_url,
                    source_name=item.document.source_name,
                    source_type=item.document.source_type,
                    demo=item.document.demo,
                    make=item.document.make,
                    model=item.document.model,
                    model_year=item.document.model_year,
                    highlights=term_highlights(item.chunk.text, query),
                    retrieval=chosen_mode,
                    score_detail=detail,
                )
            )
        return results, {
            "excluded_by_filter": excluded,
            "mode": chosen_mode,
            "requested_mode": mode,
            "eligible": len(eligible),
        }

    def _bm25(self, query: str, eligible: list[IndexedChunk]) -> list[tuple[IndexedChunk, float]]:
        q_tokens = _tokens(query)
        q_codes = set(find_dtcs(query))
        n_docs = len(self.chunks) or 1
        scored: list[tuple[IndexedChunk, float]] = []
        for item in eligible:
            tf = Counter(item.tokens)
            dl = len(item.tokens) or 1
            score = 0.0
            for token in q_tokens:
                if token not in tf:
                    continue
                df = self._df.get(token, 0)
                idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                freq = tf[token]
                denom = freq + self.k1 * (1 - self.b + self.b * dl / (self._avgdl or 1))
                score += idf * (freq * (self.k1 + 1)) / denom
            # A DTC is a high-precision token. Shared prose ("code", "failed")
            # should not outrank a chunk that actually contains the asked code.
            if q_codes and q_codes & set(find_dtcs(item.chunk.text)):
                score += 8.0
            scored.append((item, score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored

    def _vector(self, query: str, eligible: list[IndexedChunk]) -> list[IndexedChunk]:
        scores = self._vector_scores(query, eligible)
        ranked = sorted(eligible, key=lambda item: scores.get(id(item), 0.0), reverse=True)
        return ranked

    def _vector_scores(self, query: str, eligible: list[IndexedChunk]) -> dict[int, float]:
        if not self.vector_ready or self._tfidf is None or self._matrix is None:
            return {}
        from sklearn.metrics.pairwise import cosine_similarity

        q_vec = self._tfidf.transform([" ".join(_tokens(query))])
        # Map eligible items back to row indexes in the full matrix.
        index_of = {id(item): pos for pos, item in enumerate(self.chunks)}
        pairs = [(item, index_of[id(item)]) for item in eligible if id(item) in index_of]
        if not pairs:
            return {}
        rows = [row for _item, row in pairs]
        sim = cosine_similarity(q_vec, self._matrix[rows]).ravel()
        return {id(pairs[i][0]): float(sim[i]) for i in range(len(pairs))}

    def _fuse(
        self,
        lexical: list[tuple[IndexedChunk, float]],
        vector_ranks: list[IndexedChunk],
    ) -> tuple[list[IndexedChunk], dict[int, float]]:
        scores: dict[int, float] = defaultdict(float)
        objects: dict[int, IndexedChunk] = {}
        positive = [(item, score) for item, score in lexical if score > 0]
        for rank, (item, _score) in enumerate(positive, start=1):
            scores[id(item)] += 1.0 / (self.fusion_k + rank)
            objects[id(item)] = item
        for rank, item in enumerate(vector_ranks, start=1):
            scores[id(item)] += 1.0 / (self.fusion_k + rank)
            objects[id(item)] = item
        ordered_ids = sorted(scores, key=lambda key: scores[key], reverse=True)
        return [objects[key] for key in ordered_ids], scores


def _passes(document: SourceDocument, chunk: DocumentChunk, filters: QAFilters) -> bool:
    if filters.make and (document.make or "").lower() != filters.make.lower():
        return False
    if filters.model and (document.model or "").lower() != filters.model.lower():
        return False
    if filters.model_year and document.model_year != filters.model_year:
        return False
    if filters.document_type and document.source_type != filters.document_type:
        return False
    if filters.component:
        blob = f"{document.component or ''} {chunk.text}".lower()
        if filters.component.lower() not in blob:
            return False
    if filters.dtc:
        code = filters.dtc.lower().replace(" ", "").replace("-", "")
        blob = f"{' '.join(document.dtc_codes)} {chunk.text}".lower().replace(" ", "").replace("-", "")
        if code not in blob:
            return False
    return True
