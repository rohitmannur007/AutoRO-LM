import { useState } from "react";
import { api, downloadText } from "../api";
import { Badge, Banner, Button, Field, controlClass } from "../components/ui";
import type { Extraction } from "../types";

export const SAMPLE_NOTE =
  "2018 Honda Civic. Check engine light on. Stored DTC P0420. Customer reports a rotten egg smell at idle. Replaced the catalytic converter.";

export default function Extract() {
  const [text, setText] = useState("");
  const [make, setMake] = useState("");
  const [model, setModel] = useState("");
  const [year, setYear] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Extraction | null>(null);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (text.trim().length < 8) {
      setError("Enter at least a short repair note. Your text is kept on the page.");
      return;
    }
    const yearNumber = year ? Number(year) : undefined;
    if (year && (!yearNumber || yearNumber < 1980 || yearNumber > 2035)) {
      setError("Model year must be between 1980 and 2035.");
      return;
    }
    setError("");
    setBusy(true);
    try {
      const body = await api<Extraction>("/api/v1/extract", {
        method: "POST",
        body: JSON.stringify({
          text,
          vehicle: {
            make: make || null,
            model: model || null,
            model_year: yearNumber ?? null,
          },
        }),
      });
      setResult(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Extraction failed");
    } finally {
      setBusy(false);
    }
  }

  async function copyJson() {
    if (!result) return;
    await navigator.clipboard.writeText(JSON.stringify(result, null, 2));
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <form onSubmit={onSubmit} className="space-y-3 rounded-lg border border-line bg-panel p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">Repair note</h2>
          <Button type="button" tone="ghost" onClick={() => setText(SAMPLE_NOTE)}>
            Load DEMO sample
          </Button>
        </div>
        <Field label="Narrative" hint="Missing facts stay null. A DTC alone will not be treated as a failed part.">
          <textarea
            aria-label="Repair note"
            className={`${controlClass} min-h-48 font-mono`}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Make (optional)">
            <input className={controlClass} value={make} onChange={(event) => setMake(event.target.value)} />
          </Field>
          <Field label="Model (optional)">
            <input className={controlClass} value={model} onChange={(event) => setModel(event.target.value)} />
          </Field>
          <Field label="Model year (optional)">
            <input className={controlClass} inputMode="numeric" value={year} onChange={(event) => setYear(event.target.value)} />
          </Field>
        </div>
        {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
        <Button type="submit" disabled={busy} aria-busy={busy}>
          {busy ? "Extracting…" : "Run extraction"}
        </Button>
      </form>
      <section className="space-y-3 rounded-lg border border-line bg-panel p-4" aria-live="polite">
        {!result ? <p className="text-sm text-mist">JSON, evidence spans, and schema status appear here. Confidence is omitted unless a provider returns a calibrated score.</p> : null}
        {result ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={result.schema_valid ? "ok" : "bad"}>{result.schema_valid ? "Schema valid" : "Schema invalid"}</Badge>
              {result.demo ? <Badge tone="demo">DEMO provider</Badge> : <Badge tone="ok">{result.provider.provider}</Badge>}
              <Badge tone="neutral">{result.provider.is_llm ? "LLM" : "Not an LLM"}</Badge>
            </div>
            {result.provider.caveats.map((caveat) => (
              <Banner key={caveat} tone="warn">{caveat}</Banner>
            ))}
            {result.validation_errors.length ? <Banner tone="error">{result.validation_errors.join(" ")}</Banner> : null}
            <div className="flex gap-2">
              <Button type="button" tone="ghost" onClick={copyJson}>Copy JSON</Button>
              <Button type="button" tone="ghost" onClick={() => downloadText(`${result.extraction_id}.json`, JSON.stringify(result, null, 2))}>
                Download JSON
              </Button>
            </div>
            <pre className="max-h-80 overflow-auto rounded-md bg-ink p-3 font-mono text-xs leading-5 text-teal">{JSON.stringify(result, null, 2)}</pre>
            <h3 className="text-sm font-semibold">Evidence</h3>
            <ul className="space-y-2">
              {result.evidence.map((span, index) => (
                <li key={`${span.field_name}-${index}`} className="rounded-md border border-line px-3 py-2 text-sm">
                  <span className="font-mono text-xs text-teal">{span.field_name}</span>
                  <p className="mt-1">“{span.quoted_text}”</p>
                  <p className="text-xs text-mist">
                    {span.support_status}
                    {span.start != null ? ` · offsets ${span.start}–${span.end}` : ""}
                  </p>
                </li>
              ))}
            </ul>
            <p className="text-xs text-mist">Unknown fields: {result.unknown_fields.join(", ") || "none"}</p>
          </>
        ) : null}
      </section>
    </div>
  );
}
