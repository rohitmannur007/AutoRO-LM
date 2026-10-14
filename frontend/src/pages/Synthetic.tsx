import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { Badge, Banner, Button, Empty, Field, controlClass } from "../components/ui";
import type { Health, Job, SyntheticExample } from "../types";

const VARIATIONS = ["abbreviation", "capitalization", "typos", "terse", "ccc"] as const;

export default function Synthetic() {
  const queryClient = useQueryClient();
  const health = useQuery({ queryKey: ["health"], queryFn: () => api<Health>("/api/v1/health") });
  const examples = useQuery({
    queryKey: ["synthetic"],
    queryFn: () => api<{ items: SyntheticExample[] }>("/api/v1/synthetic/examples"),
  });
  const [teacher, setTeacher] = useState<"deterministic_demo" | "ollama">("deterministic_demo");
  const [count, setCount] = useState("3");
  const [selectedVars, setSelectedVars] = useState<string[]>(["terse", "ccc"]);
  const [seed, setSeed] = useState("demo-civic-catalyst");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState<SyntheticExample | null>(null);
  const teacherHealth = health.data?.providers.find((item) => item.role === "teacher");
  const ollamaBlocked = teacher === "ollama" && teacherHealth && !teacherHealth.available;

  function toggle(name: string) {
    setSelectedVars((current) => (current.includes(name) ? current.filter((item) => item !== name) : [...current, name]));
  }

  async function generate(event: React.FormEvent) {
    event.preventDefault();
    const requested = Number(count);
    if (!requested || requested < 1 || requested > 20) {
      setError("Count must be between 1 and 20.");
      return;
    }
    if (!selectedVars.length) {
      setError("Choose at least one variation.");
      return;
    }
    setError("");
    setBusy(true);
    try {
      const job = await api<Job>("/api/v1/synthetic/jobs", {
        method: "POST",
        body: JSON.stringify({
          seed_document_ids: seed ? [seed] : [],
          variations: selectedVars,
          count: requested,
          teacher,
        }),
      });
      if (job.status === "failed") {
        setError(job.errors.join(" ") || "Generation failed");
      }
      await queryClient.invalidateQueries({ queryKey: ["synthetic"] });
      await queryClient.invalidateQueries({ queryKey: ["status"] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generation failed");
    } finally {
      setBusy(false);
    }
  }

  async function review(example: SyntheticExample, status: "approved" | "rejected") {
    const reason = status === "rejected" ? "Reviewer rejected" : "Reviewer approved";
    await api(`/api/v1/synthetic/examples/${example.example_id}/review`, {
      method: "POST",
      body: JSON.stringify({ status, reason }),
    });
    await queryClient.invalidateQueries({ queryKey: ["synthetic"] });
  }

  async function exportJsonl() {
    const text = await api<string>("/api/v1/synthetic/examples/export");
    const blob = new Blob([text], { type: "application/x-ndjson" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "synthetic_examples.jsonl";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-4">
      <Banner tone="info">
        The deterministic teacher rewrites supported seed facts only. It is not an LLM. Ollama is used only when that teacher is selected and the local model is present. Gold and test documents cannot be seeds.
      </Banner>
      <form onSubmit={generate} className="space-y-3 rounded-lg border border-line bg-panel p-4">
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="Teacher">
            <select aria-label="Teacher" className={controlClass} value={teacher} onChange={(event) => setTeacher(event.target.value as "deterministic_demo" | "ollama")}>
              <option value="deterministic_demo">Deterministic demo paraphraser (not an LLM)</option>
              <option value="ollama">Ollama local model</option>
            </select>
          </Field>
          <Field label="Seed document id">
            <input className={controlClass} value={seed} onChange={(event) => setSeed(event.target.value)} />
          </Field>
          <Field label="Count">
            <input className={controlClass} value={count} onChange={(event) => setCount(event.target.value)} />
          </Field>
        </div>
        <fieldset>
          <legend className="mb-2 text-sm font-medium">Variations</legend>
          <div className="flex flex-wrap gap-3 text-sm">
            {VARIATIONS.map((name) => (
              <label key={name} className="flex items-center gap-2">
                <input type="checkbox" checked={selectedVars.includes(name)} onChange={() => toggle(name)} />
                {name}
              </label>
            ))}
          </div>
        </fieldset>
        {ollamaBlocked ? <Banner tone="error">Ollama teacher is unavailable. {teacherHealth?.detail} Generation stays disabled for that teacher.</Banner> : null}
        {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={busy || Boolean(ollamaBlocked)}>{busy ? "Generating…" : "Generate"}</Button>
          <Button type="button" tone="ghost" onClick={async () => { await api("/api/v1/synthetic/rule-filter", { method: "POST" }); await queryClient.invalidateQueries({ queryKey: ["synthetic"] }); }}>
            Apply rule filter
          </Button>
          <Button type="button" tone="ghost" onClick={async () => { await api("/api/v1/synthetic/dedupe", { method: "POST" }); await queryClient.invalidateQueries({ queryKey: ["synthetic"] }); }}>
            Deduplicate
          </Button>
          <Button type="button" tone="ghost" onClick={exportJsonl}>Export JSONL</Button>
        </div>
      </form>
      {examples.data && examples.data.items.length === 0 ? (
        <Empty title="No synthetic examples" body="Generate from a train-split DEMO seed such as demo-civic-catalyst. Counts stay at zero until a job actually stores rows." />
      ) : null}
      {examples.data && examples.data.items.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full text-left text-sm">
            <thead className="bg-panel text-xs uppercase text-mist">
              <tr>
                <th className="px-3 py-2">Example</th>
                <th className="px-3 py-2">Provider</th>
                <th className="px-3 py-2">Review</th>
                <th className="px-3 py-2">Flags</th>
              </tr>
            </thead>
            <tbody>
              {examples.data.items.map((item) => (
                <tr key={item.example_id} className="border-t border-line">
                  <td className="px-3 py-2">
                    <button className="text-left text-teal" onClick={() => setActive(item)}>{item.example_id}</button>
                    <div className="max-w-xl truncate text-mist">{item.input_text}</div>
                  </td>
                  <td className="px-3 py-2">
                    {item.demo ? <Badge tone="demo">DEMO</Badge> : <Badge tone="ok">{item.generation_provider}</Badge>}
                    <div className="text-xs text-mist">{item.is_llm ? "LLM" : "not an LLM"}</div>
                  </td>
                  <td className="px-3 py-2">{item.review_status}</td>
                  <td className="px-3 py-2 text-xs">{item.quality_flags.join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {active ? (
        <aside className="rounded-lg border border-line bg-panel p-4">
          <h2 className="text-sm font-semibold">Review {active.example_id}</h2>
          <p className="mt-2 text-sm leading-6">{active.input_text}</p>
          <p className="mt-2 text-xs text-mist">Seeds {active.seed_document_ids.join(", ")} · prompt {active.generation_prompt_version} · {active.provenance_label}</p>
          <pre className="mt-3 overflow-auto font-mono text-xs">{JSON.stringify(active.expected_json, null, 2)}</pre>
          <div className="mt-3 flex gap-2">
            <Button type="button" onClick={() => review(active, "approved")}>Approve</Button>
            <Button type="button" tone="danger" onClick={() => review(active, "rejected")}>Reject</Button>
          </div>
        </aside>
      ) : null}
    </div>
  );
}
