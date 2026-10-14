import { useState } from "react";
import { api } from "../api";
import { Badge, Banner, Button, Field, controlClass, highlight } from "../components/ui";
import type { QAResponse } from "../types";

const ANSWERABLE = "What does DTC P0420 indicate, and does the code alone prove the catalytic converter failed?";
const UNANSWERABLE = "What is the cylinder head bolt torque specification for a 2019 Toyota Camry?";

export default function Ask() {
  const [question, setQuestion] = useState("");
  const [make, setMake] = useState("");
  const [model, setModel] = useState("");
  const [year, setYear] = useState("");
  const [dtc, setDtc] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<QAResponse | null>(null);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (question.trim().length < 8) {
      setError("Enter a question. The text stays in the field.");
      return;
    }
    setError("");
    setBusy(true);
    try {
      const body = await api<QAResponse>("/api/v1/ask", {
        method: "POST",
        body: JSON.stringify({
          question,
          filters: {
            make: make || null,
            model: model || null,
            model_year: year ? Number(year) : null,
            dtc: dtc || null,
          },
        }),
      });
      setResult(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={onSubmit} className="space-y-3 rounded-lg border border-line bg-panel p-4">
        <Field label="Question">
          <textarea aria-label="Question" className={`${controlClass} min-h-24`} value={question} onChange={(event) => setQuestion(event.target.value)} />
        </Field>
        <div className="grid gap-3 sm:grid-cols-4">
          <Field label="Make filter"><input className={controlClass} value={make} onChange={(event) => setMake(event.target.value)} /></Field>
          <Field label="Model filter"><input className={controlClass} value={model} onChange={(event) => setModel(event.target.value)} /></Field>
          <Field label="Year filter"><input className={controlClass} value={year} onChange={(event) => setYear(event.target.value)} /></Field>
          <Field label="DTC filter"><input className={controlClass} value={dtc} onChange={(event) => setDtc(event.target.value)} /></Field>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" tone="ghost" onClick={() => setQuestion(ANSWERABLE)}>DEMO answerable question</Button>
          <Button type="button" tone="ghost" onClick={() => setQuestion(UNANSWERABLE)}>DEMO unanswerable question</Button>
          <Button type="submit" disabled={busy} aria-busy={busy}>{busy ? "Retrieving…" : "Ask"}</Button>
        </div>
        {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
      </form>
      {result ? (
        <section className="space-y-3" aria-live="polite">
          {result.abstained ? (
            <Banner tone="warn">
              <strong>Evidence not sufficient.</strong> {result.abstain_reason || result.answer}
            </Banner>
          ) : (
            <Banner tone="info">Answer is limited to retrieved passages.</Banner>
          )}
          <article className="rounded-lg border border-line bg-panel p-4">
            <div className="mb-2 flex flex-wrap gap-2">
              {result.demo ? <Badge tone="demo">DEMO</Badge> : null}
              <Badge tone={result.abstained ? "warn" : "ok"}>{result.abstained ? "Abstained" : "Answered"}</Badge>
              <span className="text-xs text-mist">{result.latency_ms} ms · {result.provider.provider}</span>
            </div>
            <p className="text-sm leading-6">{result.answer}</p>
            <p className="mt-3 text-xs text-mist">{result.safety_notice}</p>
            {result.claims && result.claims.length > 0 ? (
              <ul className="mt-3 space-y-1 text-xs text-mist">
                {result.claims.map((claim) => (
                  <li key={claim.claim}>
                    {claim.support_status} · substring check, not an entailment judgment · {claim.claim}
                  </li>
                ))}
              </ul>
            ) : null}
            {result.citations.length ? (
              <ol className="mt-3 space-y-2 text-sm">
                {result.citations.map((citation) => (
                  <li key={citation.citation_id} id={`cite-${citation.citation_id}`}>
                    <a className="text-teal" href={`#chunk-${citation.chunk_id}`}>[{citation.citation_id}]</a>{" "}
                    {citation.quote}
                  </li>
                ))}
              </ol>
            ) : null}
          </article>
          <div className="grid gap-3 lg:grid-cols-2">
            {result.retrieved.map((chunk) => (
              <article key={chunk.chunk_id} id={`chunk-${chunk.chunk_id}`} className="rounded-lg border border-line bg-panel p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-sm font-semibold">{chunk.source_name}</h3>
                  {chunk.demo ? <Badge tone="demo">DEMO</Badge> : <Badge tone="ok">Source</Badge>}
                </div>
                <p className="mt-1 font-mono text-[11px] text-mist">{chunk.document_id} · {chunk.retrieval} · score {chunk.score.toFixed(3)}</p>
                <p className="mt-1 text-xs text-mist">
                  {[chunk.make, chunk.model, chunk.model_year].filter(Boolean).join(" ") || "No vehicle filter metadata"}
                  {chunk.source_url ? (
                    <>
                      {" · "}
                      <a className="text-teal" href={chunk.source_url} target="_blank" rel="noreferrer">Open source</a>
                    </>
                  ) : null}
                </p>
                <p className="mt-3 text-sm leading-6">{highlight(chunk.text, chunk.highlights)}</p>
                <p className="mt-2 text-xs text-mist">
                  {Object.entries(chunk.score_detail).map(([key, value]) => `${key} ${value.toFixed(3)}`).join(" · ") || "Score detail unavailable"}
                </p>
              </article>
            ))}
          </div>
          {result.retrieved.length === 0 ? <Banner tone="warn">No passages matched the question and filters.</Banner> : null}
        </section>
      ) : null}
    </div>
  );
}
