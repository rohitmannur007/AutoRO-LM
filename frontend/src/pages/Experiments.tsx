import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, downloadText } from "../api";
import { Banner, Button, Empty, Skeleton } from "../components/ui";
import type { ExperimentRun, Job } from "../types";

const TASKS = [
  ["extraction_rules", "Rules extraction"],
  ["component_classifier", "TF-IDF classifier"],
  ["retrieval_comparison", "Retrieval comparison"],
  ["qa_rag", "QA with selected provider"],
  ["extraction_provider", "Selected provider extraction"],
  ["synthetic_share", "Classifier synthetic share"],
  ["synthetic_share_llm", "LLM synthetic share"],
  ["filtered_vs_unfiltered", "Filtered vs unfiltered"],
] as const;

export default function Experiments() {
  const queryClient = useQueryClient();
  const runs = useQuery({
    queryKey: ["experiments"],
    queryFn: () => api<{ items: ExperimentRun[] }>("/api/v1/experiments"),
  });
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const detail = useQuery({
    queryKey: ["experiment", selected],
    enabled: Boolean(selected),
    queryFn: () => api<ExperimentRun>(`/api/v1/experiments/${selected}`),
  });

  async function launch(task: string) {
    setBusy(task);
    setError("");
    try {
      const job = await api<Job>("/api/v1/evaluations", { method: "POST", body: JSON.stringify({ task }) });
      if (job.status === "failed") setError(job.errors.join(" ") || "Evaluation failed");
      if (job.metadata.run_id) setSelected(String(job.metadata.run_id));
      await queryClient.invalidateQueries({ queryKey: ["experiments"] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Evaluation failed");
    } finally {
      setBusy("");
    }
  }

  const shareArms = Array.isArray((detail.data?.metrics as { arms?: unknown[] } | undefined)?.arms)
    ? ((detail.data!.metrics as { arms: { synthetic_share: number; macro_f1: number | null; status: string }[] }).arms)
    : [];
  const chartRows = shareArms.filter((arm) => typeof arm.macro_f1 === "number");

  return (
    <div className="space-y-4">
      <p className="text-sm text-mist">
        Every number on this page comes from a stored run. The synthetic-share chart is the TF-IDF classifier. The LLM share study stays failed until separate fine-tuned adapters exist, and it does not reuse the classifier score.
      </p>
      <div className="flex flex-wrap gap-2">
        {TASKS.map(([task, label]) => (
          <Button key={task} type="button" tone="ghost" disabled={busy === task} onClick={() => launch(task)}>
            {busy === task ? "Running…" : label}
          </Button>
        ))}
      </div>
      {error ? <Banner tone="error">{error}</Banner> : null}
      {runs.isLoading ? <Skeleton className="h-24" /> : null}
      {runs.data && runs.data.items.length === 0 ? (
        <Empty title="No experiment results" body="Choose a study above. The rules extraction and retrieval comparisons can run entirely on the DEMO gold set and fixture questions." />
      ) : null}
      {runs.data && runs.data.items.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full text-left text-sm">
            <thead className="bg-panel text-xs uppercase text-mist">
              <tr>
                <th className="px-3 py-2">Run</th>
                <th className="px-3 py-2">Task</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Runtime</th>
              </tr>
            </thead>
            <tbody>
              {runs.data.items.map((run) => (
                <tr key={run.run_id} className="border-t border-line">
                  <td className="px-3 py-2">
                    <button className="font-mono text-xs text-teal" onClick={() => setSelected(run.run_id)}>{run.run_id}</button>
                  </td>
                  <td className="px-3 py-2">{run.task}</td>
                  <td className="px-3 py-2">{run.status}</td>
                  <td className="px-3 py-2">{run.runtime_seconds ?? "—"}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {detail.data ? (
        <section className="space-y-3 rounded-lg border border-line bg-panel p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">{detail.data.task} · {detail.data.status}</h2>
            <div className="flex gap-2">
              <Button type="button" tone="ghost" onClick={() => downloadText(`${detail.data!.run_id}.json`, JSON.stringify(detail.data, null, 2))}>Export JSON</Button>
              <Button
                type="button"
                tone="ghost"
                onClick={async () => {
                  const csv = await api<string>(`/api/v1/evaluations/${detail.data!.run_id}/export?format=csv`);
                  downloadText(`${detail.data!.run_id}.csv`, csv, "text/csv");
                }}
              >
                Export CSV
              </Button>
            </div>
          </div>
          {detail.data.caveats.map((caveat) => <Banner key={caveat} tone="warn">{caveat}</Banner>)}
          <p className="text-xs text-mist">
            Provider {detail.data.model_provider} · dataset {detail.data.dataset_version} · seed {detail.data.seed} · {String(detail.data.hardware.machine || "")} {String(detail.data.hardware.python || "")}
          </p>
          {chartRows.length >= 2 ? (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartRows.map((arm) => ({ share: arm.synthetic_share, f1: arm.macro_f1 }))}>
                  <CartesianGrid stroke="#234056" />
                  <XAxis dataKey="share" stroke="#9eb2c6" />
                  <YAxis stroke="#9eb2c6" domain={[0, 1]} />
                  <Tooltip />
                  <Line type="monotone" dataKey="f1" stroke="#2ec4b6" dot />
                </LineChart>
              </ResponsiveContainer>
              <p className="text-xs text-mist">Macro F1 of the component classifier versus synthetic share. This chart is not a fine-tuned LLM result. Only measured arms are plotted.</p>
            </div>
          ) : (
            <Empty title="No chart for this run" body="A synthetic-share chart appears only after at least two arms record a real macro F1. Skipped proportions are listed in the JSON instead of being filled in." />
          )}
          <pre className="max-h-96 overflow-auto rounded-md bg-ink p-3 font-mono text-xs leading-5">{JSON.stringify(detail.data.metrics, null, 2)}</pre>
        </section>
      ) : null}
    </div>
  );
}
