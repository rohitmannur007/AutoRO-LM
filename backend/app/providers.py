"""Model providers.

demo: deterministic rules and extractive quotes. It never claims to be an LLM.
ollama: calls a local Ollama server. Missing server or model is an error.
openai_compatible: optional extension. No SDK and no embedded key.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Protocol

import httpx

from app.errors import ProviderUnavailable, UpstreamError
from app.extraction import extract_rules
from app.model_extract import adopt_model_extraction
from app.schemas import (
    SAFETY_NOTICE,
    Citation,
    ExtractionResult,
    ProviderHealth,
    ProviderMetadata,
    QAFilters,
    QAResponse,
    RetrievedChunk,
    VehicleInfo,
)
from app.textutil import find_dtcs, find_span, tokenize

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
PROCEDURE_CUES = ("torque", "specification", "spec ", "wiring diagram", "pinout", "ft-lb", "n·m", "nm ")


class ExtractionProvider(Protocol):
    name: str

    async def extract(self, text: str, vehicle: VehicleInfo | None) -> ExtractionResult: ...

    async def answer(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        filters: QAFilters,
        *,
        min_score: float,
    ) -> tuple[str, bool, str | None, list[Citation], list[str]]: ...

    async def health(self) -> ProviderHealth: ...


def validate_citations(citations: list[Citation], retrieved_ids: set[str]) -> list[str]:
    errors = []
    for citation in citations:
        if citation.chunk_id not in retrieved_ids:
            errors.append(f"citation {citation.citation_id} is not in the retrieved set")
    return errors


class DemoProvider:
    name = "demo"
    model = "rules-extractive-v1"

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            role="extraction_and_qa",
            available=True,
            is_llm=False,
            demo=True,
            model=self.model,
            detail="Deterministic rules and extractive quotes. This is not a language model.",
        )

    async def extract(self, text: str, vehicle: VehicleInfo | None) -> ExtractionResult:
        return extract_rules(text, vehicle, provider_name=self.name, demo=True, model=self.model)

    async def answer(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        filters: QAFilters,
        *,
        min_score: float,
    ) -> tuple[str, bool, str | None, list[Citation], list[str]]:
        del filters
        conflicts = _conflicts(chunks)
        if conflicts:
            return (
                "Evidence conflicts across retrieved passages, so this answer abstains rather than choosing a side.",
                True,
                "conflicting retrieved evidence",
                _citations_for_keywords(chunks, ("not", "fail", "replace")),
                conflicts,
            )
        if not chunks:
            return (
                "Evidence is not sufficient. No source passage was retrieved for this question.",
                True,
                "no retrieved evidence",
                [],
                [],
            )
        best = chunks[0].score
        lexical_best = max((c.score_detail.get("bm25", 0.0) for c in chunks), default=0.0)
        # Hybrid RRF scores are small. Gate on BM25 when it is present so a
        # purely lexical miss still abstains.
        if lexical_best < min_score and best <= 0:
            return (
                "Evidence is not sufficient. Retrieved passages are below the relevance threshold.",
                True,
                "retrieval score below threshold",
                [],
                [],
            )
        sentences = _supporting_sentences(question, chunks)
        if not sentences:
            return (
                "Evidence is not sufficient. Retrieved documents do not contain a passage that supports an answer.",
                True,
                "no supporting passage in retrieved text",
                [],
                [],
            )
        if _asks_unsupported_procedure(question, sentences):
            return (
                "Evidence is not sufficient for a repair procedure or specification. "
                "The retrieved passages do not state the requested specification.",
                True,
                "requested specification or procedure is not in the retrieved text",
                [],
                [],
            )
        citations: list[Citation] = []
        quotes: list[str] = []
        for index, (chunk, sentence) in enumerate(sentences[:3], start=1):
            citations.append(
                Citation(
                    citation_id=f"c{index}",
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    quote=sentence,
                    source_url=chunk.source_url,
                    support_status="supported",
                )
            )
            quotes.append(f"[{index}] {sentence}")
        prefix = "DEMO extractive answer from retrieved fixture or stored passages, not a language model. "
        answer = prefix + " ".join(quotes)
        return answer, False, None, citations, []


class OllamaProvider:
    def __init__(self, base_url: str, model: str, timeout: float) -> None:
        self.name = "ollama"
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def health(self) -> ProviderHealth:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            return ProviderHealth(
                name=self.name,
                role="extraction_and_qa",
                available=False,
                is_llm=True,
                demo=False,
                model=self.model,
                detail=f"Ollama is not reachable at {self.base_url}: {exc.__class__.__name__}",
            )
        names = [item.get("name", "") for item in payload.get("models", [])]
        present = self.model in names or any(name.split(":")[0] == self.model for name in names)
        return ProviderHealth(
            name=self.name,
            role="extraction_and_qa",
            available=present,
            is_llm=True,
            demo=False,
            model=self.model,
            detail="model present" if present else f"model '{self.model}' is not pulled; installed: {names or 'none'}",
        )

    async def _generate(self, prompt: str) -> str:
        health = await self.health()
        if not health.available:
            raise ProviderUnavailable(health.detail or "Ollama provider is unavailable")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={"model": self.model, "prompt": prompt, "stream": False, "format": "json"},
                )
                response.raise_for_status()
                data = response.json()
        except ProviderUnavailable:
            raise
        except Exception as exc:
            raise UpstreamError(f"Ollama request failed: {exc.__class__.__name__}") from exc
        text = data.get("response")
        if not isinstance(text, str) or not text.strip():
            raise UpstreamError("Ollama returned an empty response")
        return text

    async def extract(self, text: str, vehicle: VehicleInfo | None) -> ExtractionResult:
        hint = vehicle.model_dump() if vehicle else {}
        prompt = (
            "Extract only facts present in the TEXT. Use null for missing fields. "
            "Do not treat a DTC as proof a part failed. Return JSON with keys "
            "symptom, dtc_codes, component, suspected_component, repair_action, "
            "complaint, cause, correction, vehicle {make, model, model_year}. "
            f"Vehicle hint: {json.dumps(hint)}. TEXT:\n{text}"
        )
        raw = await self._generate(prompt)
        try:
            payload = json.loads(_json_object(raw))
        except json.JSONDecodeError as exc:
            raise UpstreamError("Ollama extraction was not valid JSON") from exc
        try:
            return adopt_model_extraction(
                text,
                payload,
                vehicle,
                provider_name=self.name,
                model=self.model,
                prompt_version="ollama-extract-v1",
            )
        except ValueError as exc:
            raise UpstreamError(str(exc)) from exc

    async def answer(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        filters: QAFilters,
        *,
        min_score: float,
    ) -> tuple[str, bool, str | None, list[Citation], list[str]]:
        del min_score
        if not chunks:
            return (
                "Evidence is not sufficient. No source passage was retrieved.",
                True,
                "no retrieved evidence",
                [],
                [],
            )
        context = [
            {"chunk_id": chunk.chunk_id, "document_id": chunk.document_id, "text": chunk.text}
            for chunk in chunks
        ]
        prompt = (
            "Answer ONLY from CONTEXT. If CONTEXT does not support an answer, "
            'return {"abstained": true, "answer": "Evidence is not sufficient.", "citations": []}. '
            "Each citation must copy a quote from a context chunk and use that chunk_id. "
            "Do not invent specifications. A DTC is not proof of component failure. "
            f"Question: {question}\nFilters: {filters.model_dump_json()}\nCONTEXT: {json.dumps(context)}"
        )
        raw = await self._generate(prompt)
        try:
            payload = json.loads(_json_object(raw))
        except json.JSONDecodeError as exc:
            raise UpstreamError("Ollama QA response was not valid JSON") from exc
        return _ground_model_answer(payload, chunks)


class OpenAICompatibleProvider:
    """Extension point for a user-configured hosted endpoint. No SDK dependency."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0) -> None:
        self.name = "openai_compatible"
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def health(self) -> ProviderHealth:
        if not self.base_url:
            detail = "No hosted base URL configured. Set AUTORO_OPENAI_COMPAT_BASE_URL to enable."
            available = False
        elif not self.api_key:
            detail = "Hosted base URL is set but AUTORO_OPENAI_COMPAT_API_KEY is empty."
            available = False
        else:
            detail = "Configured. The key is loaded from the environment and is not displayed."
            available = True
        return ProviderHealth(
            name=self.name,
            role="extraction_and_qa",
            available=available,
            is_llm=True,
            demo=False,
            model=self.model or None,
            detail=detail,
        )

    async def _chat(self, prompt: str) -> str:
        health = await self.health()
        if not health.available:
            raise ProviderUnavailable(health.detail)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
                response.raise_for_status()
                data = response.json()
        except ProviderUnavailable:
            raise
        except Exception as exc:
            raise UpstreamError(f"Hosted provider request failed: {exc.__class__.__name__}") from exc
        try:
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise UpstreamError("Hosted provider returned an unexpected payload") from exc

    async def extract(self, text: str, vehicle: VehicleInfo | None) -> ExtractionResult:
        hint = vehicle.model_dump() if vehicle else {}
        prompt = (
            "Extract only facts present in TEXT. Use null when absent. Return JSON keys "
            "symptom, dtc_codes, component, suspected_component, repair_action, complaint, cause, correction, "
            "vehicle {make, model, model_year}. "
            f"Hint: {json.dumps(hint)}. TEXT:\n{text}"
        )
        raw = await self._chat(prompt)
        try:
            payload = json.loads(_json_object(raw))
        except json.JSONDecodeError as exc:
            raise UpstreamError("Hosted extraction was not valid JSON") from exc
        try:
            return adopt_model_extraction(
                text,
                payload,
                vehicle,
                provider_name=self.name,
                model=self.model,
                prompt_version="openai-compatible-extract-v1",
            )
        except ValueError as exc:
            raise UpstreamError(str(exc)) from exc

    async def answer(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        filters: QAFilters,
        *,
        min_score: float,
    ) -> tuple[str, bool, str | None, list[Citation], list[str]]:
        del min_score
        if not chunks:
            return ("Evidence is not sufficient. No source passage was retrieved.", True, "no retrieved evidence", [], [])
        context = [{"chunk_id": c.chunk_id, "document_id": c.document_id, "text": c.text} for c in chunks]
        prompt = (
            "Answer only from CONTEXT. If unsupported, abstain. Return JSON "
            '{"abstained": bool, "answer": str, "citations": [{"chunk_id": str, "quote": str}]}. '
            f"Question: {question}\nCONTEXT: {json.dumps(context)}"
        )
        raw = await self._chat(prompt)
        try:
            payload = json.loads(_json_object(raw))
        except json.JSONDecodeError as exc:
            raise UpstreamError("Hosted QA response was not valid JSON") from exc
        return _ground_model_answer(payload, chunks)


class MlxProvider:
    """Loads a local MLX adapter. Missing weights or mlx-lm is a 503, not a demo result."""

    def __init__(self, settings) -> None:
        self.name = "mlx"
        self.settings = settings
        self.model = settings.mlx_model
        self.adapter_path = settings.resolved_adapter_dir

    async def health(self) -> ProviderHealth:
        from app.mlx_train import mlx_available, read_manifest

        ok, detail = mlx_available()
        manifest = read_manifest(self.adapter_path)
        if not ok:
            return ProviderHealth(
                name=self.name,
                role="extraction_and_qa",
                available=False,
                is_llm=True,
                demo=False,
                model=self.model,
                detail=detail,
            )
        if not manifest or not manifest.get("trained"):
            return ProviderHealth(
                name=self.name,
                role="extraction_and_qa",
                available=False,
                is_llm=True,
                demo=False,
                model=self.model,
                detail=f"No completed adapter at {self.adapter_path}. Train one or keep the demo provider.",
            )
        weights = list(self.adapter_path.glob("*.safetensors"))
        if not weights:
            return ProviderHealth(
                name=self.name,
                role="extraction_and_qa",
                available=False,
                is_llm=True,
                demo=False,
                model=manifest.get("base_model"),
                detail="Training manifest says trained, but no adapter weights were found.",
            )
        return ProviderHealth(
            name=self.name,
            role="extraction_and_qa",
            available=True,
            is_llm=True,
            demo=False,
            model=manifest.get("base_model") or self.model,
            detail="Local MLX adapter is present. This is not the deterministic demo provider.",
        )

    async def extract(self, text: str, vehicle: VehicleInfo | None) -> ExtractionResult:
        health = await self.health()
        if not health.available:
            raise ProviderUnavailable(health.detail or "MLX adapter is unavailable")
        hint = vehicle.model_dump() if vehicle else {}
        prompt = (
            "Extract only facts present in TEXT. Use null when absent. Return JSON keys "
            "symptom, dtc_codes, component, suspected_component, repair_action, complaint, cause, correction, "
            "vehicle {make, model, model_year}. "
            f"Hint: {json.dumps(hint)}. TEXT:\n{text}"
        )
        raw = await self._generate(prompt)
        try:
            payload = json.loads(_json_object(raw))
        except json.JSONDecodeError as exc:
            raise UpstreamError("MLX extraction was not valid JSON") from exc
        try:
            result = adopt_model_extraction(
                text,
                payload,
                vehicle,
                provider_name=self.name,
                model=health.model,
                prompt_version="mlx-extract-v1",
            )
        except ValueError as exc:
            raise UpstreamError(str(exc)) from exc
        result.provider.model_revision = str(self.adapter_path)
        return result

    async def answer(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        filters: QAFilters,
        *,
        min_score: float,
    ) -> tuple[str, bool, str | None, list[Citation], list[str]]:
        del min_score
        health = await self.health()
        if not health.available:
            raise ProviderUnavailable(health.detail or "MLX adapter is unavailable")
        if not chunks:
            return ("Evidence is not sufficient. No source passage was retrieved.", True, "no retrieved evidence", [], [])
        context = [{"chunk_id": c.chunk_id, "document_id": c.document_id, "text": c.text} for c in chunks]
        prompt = (
            "Answer only from CONTEXT. If unsupported, abstain. Return JSON "
            '{"abstained": bool, "answer": str, "citations": [{"chunk_id": str, "quote": str}]}. '
            f"Question: {question}\nCONTEXT: {json.dumps(context)}"
        )
        raw = await self._generate(prompt)
        try:
            payload = json.loads(_json_object(raw))
        except json.JSONDecodeError as exc:
            raise UpstreamError("MLX QA response was not valid JSON") from exc
        return _ground_model_answer(payload, chunks)

    async def _generate(self, prompt: str) -> str:
        import asyncio

        from app.mlx_train import read_manifest

        manifest = read_manifest(self.adapter_path) or {}
        base = manifest.get("base_model") or self.model

        def _run() -> str:
            from mlx_lm import generate, load

            key = (base, str(self.adapter_path))
            cached = _MLX_CACHE.get(key)
            if cached is None:
                cached = load(base, adapter_path=str(self.adapter_path))
                _MLX_CACHE[key] = cached
            model, tokenizer = cached
            return generate(model, tokenizer, prompt=prompt, max_tokens=500, verbose=False)

        return await asyncio.to_thread(_run)


_MLX_CACHE: dict[tuple[str, str], tuple] = {}


def build_provider(name: str, settings) -> DemoProvider | OllamaProvider | OpenAICompatibleProvider | MlxProvider:
    if name == "demo":
        return DemoProvider()
    if name == "ollama":
        return OllamaProvider(settings.ollama_base_url, settings.ollama_model, settings.ollama_timeout_seconds)
    if name == "openai_compatible":
        return OpenAICompatibleProvider(
            settings.openai_compat_base_url,
            settings.openai_compat_api_key,
            settings.openai_compat_model,
        )
    if name == "mlx":
        return MlxProvider(settings)
    raise ProviderUnavailable(f"Unknown provider '{name}'")


def lexical_claims(answer: str, citations: list[Citation]) -> list[dict]:
    """Substring overlap between answer sentences and citation quotes.

    This is not a semantic entailment judgment. An overlapping quote can still
    fail to support a stronger diagnostic conclusion.
    """
    quotes = [citation.quote for citation in citations if citation.quote]
    claims = []
    for sentence in SENTENCE_RE.split(answer.strip()):
        text = sentence.strip()
        if len(text) < 12:
            continue
        overlap = any(text.lower() in quote.lower() or quote.lower() in text.lower() for quote in quotes)
        claims.append(
            {
                "claim": text,
                "support_status": "lexical_overlap" if overlap else "unsupported",
                "method": "substring",
                "entailment_judged": False,
            }
        )
    return claims


async def run_qa(
    provider,
    question: str,
    chunks: list[RetrievedChunk],
    filters: QAFilters,
    *,
    min_score: float,
    retrieval_meta: dict,
) -> QAResponse:
    started = time.perf_counter()
    answer, abstained, reason, citations, conflicts = await provider.answer(
        question, chunks, filters, min_score=min_score
    )
    retrieved_ids = {chunk.chunk_id for chunk in chunks}
    bad = validate_citations(citations, retrieved_ids)
    if bad:
        abstained = True
        reason = "model citations failed validation and were removed"
        citations = [c for c in citations if c.chunk_id in retrieved_ids]
        if not citations:
            answer = "Evidence is not sufficient. The model cited passages that were not retrieved, so the answer was discarded."
    for citation in citations:
        chunk = next(item for item in chunks if item.chunk_id == citation.chunk_id)
        if find_span(chunk.text, citation.quote) is None:
            abstained = True
            reason = "citation quote is not contained in the retrieved passage"
            answer = "Evidence is not sufficient. A citation quote could not be verified in the retrieved text."
            citations = []
            break
    health_demo = getattr(provider, "name", "") == "demo"
    latency = (time.perf_counter() - started) * 1000
    claims = lexical_claims(answer, citations)
    return QAResponse(
        request_id=f"qa_{uuid.uuid4().hex[:12]}",
        question=question,
        filters=filters,
        answer=answer,
        abstained=abstained,
        abstain_reason=reason,
        citations=citations,
        retrieved_chunk_ids=[chunk.chunk_id for chunk in chunks],
        retrieved=chunks,
        provider=ProviderMetadata(
            provider=getattr(provider, "name", "unknown"),
            model=getattr(provider, "model", None),
            is_llm=not health_demo and getattr(provider, "name", "") != "deterministic_demo",
            demo=health_demo,
            caveats=[] if not health_demo else ["Deterministic demo provider. Not an LLM."],
        ),
        latency_ms=round(latency, 2),
        demo=health_demo or any(chunk.demo for chunk in chunks),
        safety_notice=SAFETY_NOTICE,
        evaluation={"retrieval": retrieval_meta},
        conflicts=conflicts,
        claims=claims,
    )


def _supporting_sentences(question: str, chunks: list[RetrievedChunk]) -> list[tuple[RetrievedChunk, str]]:
    q_tokens = set(tokenize(question))
    q_codes = {code.lower() for code in find_dtcs(question)}
    ranked: list[tuple[float, RetrievedChunk, str]] = []
    for rank, chunk in enumerate(chunks):
        for sentence in SENTENCE_RE.split(chunk.text.strip()):
            sentence = sentence.strip()
            if len(sentence) < 20:
                continue
            overlap = len(q_tokens & set(tokenize(sentence)))
            if overlap <= 0:
                continue
            code_bonus = 4.0 if q_codes and any(code in sentence.lower() for code in q_codes) else 0.0
            ranked.append((overlap + code_bonus + max(0, 2 - rank) * 0.1, chunk, sentence))
    if q_codes:
        focused = [item for item in ranked if any(code in item[2].lower() for code in q_codes)]
        if focused:
            ranked = focused
    ranked.sort(key=lambda item: item[0], reverse=True)
    picked: list[tuple[RetrievedChunk, str]] = []
    seen: set[str] = set()
    for overlap, chunk, sentence in ranked:
        if overlap < 1:
            continue
        if sentence in seen:
            continue
        seen.add(sentence)
        picked.append((chunk, sentence))
        if len(picked) >= 3:
            break
    return picked


def _asks_unsupported_procedure(question: str, sentences: list[tuple[RetrievedChunk, str]]) -> bool:
    lowered = question.lower()
    if not any(cue in lowered for cue in PROCEDURE_CUES):
        return False
    blob = " ".join(sentence for _chunk, sentence in sentences).lower()
    has_spec = bool(re.search(r"\d+\s?(nm|n·m|ft-?lb|lb-?ft)", blob))
    return not has_spec


def _conflicts(chunks: list[RetrievedChunk]) -> list[str]:
    blob = " ".join(chunk.text.lower() for chunk in chunks)
    if "must replace" in blob and "do not replace" in blob:
        return ["Retrieved text contains both 'must replace' and 'do not replace'."]
    return []


def _citations_for_keywords(chunks: list[RetrievedChunk], keywords: tuple[str, ...]) -> list[Citation]:
    citations: list[Citation] = []
    for chunk in chunks:
        for sentence in SENTENCE_RE.split(chunk.text):
            if any(word in sentence.lower() for word in keywords):
                citations.append(
                    Citation(
                        citation_id=f"c{len(citations)+1}",
                        chunk_id=chunk.chunk_id,
                        document_id=chunk.document_id,
                        quote=sentence.strip(),
                        source_url=chunk.source_url,
                    )
                )
                break
        if len(citations) >= 2:
            break
    return citations


def _json_object(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _ground_model_answer(payload: dict, chunks: list[RetrievedChunk]) -> tuple[str, bool, str | None, list[Citation], list[str]]:
    by_id = {chunk.chunk_id: chunk for chunk in chunks}
    citations: list[Citation] = []
    for item in payload.get("citations") or []:
        if not isinstance(item, dict):
            continue
        chunk_id = str(item.get("chunk_id", ""))
        quote = str(item.get("quote", "")).strip()
        chunk = by_id.get(chunk_id)
        if chunk is None or not quote or find_span(chunk.text, quote) is None:
            continue
        citations.append(
            Citation(
                citation_id=f"c{len(citations)+1}",
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                quote=quote,
                source_url=chunk.source_url,
            )
        )
    abstained = bool(payload.get("abstained")) or not citations
    answer = str(payload.get("answer") or "").strip()
    if abstained:
        return (
            answer or "Evidence is not sufficient.",
            True,
            "model abstained or citations could not be verified",
            citations,
            [],
        )
    if not answer:
        answer = " ".join(citation.quote for citation in citations)
    return answer, False, None, citations, []

