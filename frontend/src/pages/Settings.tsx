import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Banner, Button, Field, controlClass } from "../components/ui";
import type { SettingsView } from "../types";

export default function Settings() {
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsView>("/api/v1/settings") });
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState(false);

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    try {
      await api("/api/v1/settings", {
        method: "PUT",
        body: JSON.stringify({
          provider: form.get("provider"),
          teacher_provider: form.get("teacher_provider"),
          retrieval_mode: form.get("retrieval_mode"),
        }),
      });
      await queryClient.invalidateQueries({ queryKey: ["settings"] });
      await queryClient.invalidateQueries({ queryKey: ["health"] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  }

  async function reset() {
    setError("");
    try {
      await api("/api/v1/settings/reset-demo", { method: "POST", body: JSON.stringify({ confirm: "RESET_DEMO_DATA" }) });
      setConfirm(false);
      await queryClient.invalidateQueries();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset failed");
    }
  }

  if (settings.isLoading || !settings.data) return <p className="text-sm text-mist">Loading configuration…</p>;
  if (settings.isError) return <Banner tone="error">Settings could not be loaded.</Banner>;
  const data = settings.data;
  return (
    <div className="max-w-3xl space-y-4">
      <Banner tone="info">{data.privacy_note}</Banner>
      <form key={`${data.provider}-${data.teacher_provider}-${data.retrieval_mode}`} onSubmit={save} className="space-y-3 rounded-lg border border-line bg-panel p-4">
        <Field label="Active provider">
          <select name="provider" aria-label="Active provider" className={controlClass} defaultValue={data.provider}>
            <option value="demo">Deterministic demo</option>
            <option value="ollama">Ollama</option>
            <option value="openai_compatible">OpenAI-compatible endpoint</option>
            <option value="mlx">Local MLX adapter</option>
          </select>
        </Field>
        <Field label="Teacher">
          <select name="teacher_provider" aria-label="Teacher" className={controlClass} defaultValue={data.teacher_provider}>
            <option value="deterministic_demo">Deterministic demo paraphraser</option>
            <option value="ollama">Ollama</option>
            <option value="none">Disabled</option>
          </select>
        </Field>
        <Field label="Retrieval">
          <select name="retrieval_mode" aria-label="Retrieval" className={controlClass} defaultValue={data.retrieval_mode}>
            <option value="hybrid">Hybrid reciprocal rank fusion</option>
            <option value="lexical">BM25 lexical</option>
            <option value="vector">TF-IDF cosine</option>
          </select>
        </Field>
        <Button type="submit">Save non-secret settings</Button>
      </form>
      <dl className="grid gap-2 rounded-lg border border-line bg-panel p-4 text-sm sm:grid-cols-2">
        <dt className="text-mist">Environment</dt><dd>{data.environment}</dd>
        <dt className="text-mist">Data directory</dt><dd className="font-mono text-xs">{data.data_dir}</dd>
        <dt className="text-mist">Database</dt><dd>{data.database.active_adapter}{data.database.fallback ? " (fallback)" : ""} — {data.database.detail}</dd>
        <dt className="text-mist">Ollama URL</dt><dd className="font-mono text-xs">{data.ollama_base_url}</dd>
        <dt className="text-mist">Ollama model name</dt><dd>{data.ollama_model}</dd>
        <dt className="text-mist">Hosted endpoint configured</dt><dd>{data.hosted_provider_configured ? "yes" : "no"}</dd>
        <dt className="text-mist">Hosted key present</dt><dd>{data.hosted_key_present ? "yes, hidden" : "no"}</dd>
        <dt className="text-mist">Jobs inline</dt><dd>{data.jobs_inline ? "yes (tests)" : "background"}</dd>
        <dt className="text-mist">MLX base model</dt><dd className="font-mono text-xs">{data.mlx_model}</dd>
        <dt className="text-mist">MLX adapter</dt><dd>{data.mlx_adapter_trained ? "trained" : "not trained"} — {data.mlx_detail}</dd>
      </dl>
      {error ? <Banner tone="error">{error}</Banner> : null}
      <section className="rounded-lg border border-line bg-panel p-4">
        <h2 className="text-sm font-semibold">Clear local demo data</h2>
        <p className="mt-1 text-sm text-mist">This deletes local documents, synthetic examples, and experiment rows, then reloads the DEMO fixtures. It does not call an external provider.</p>
        {confirm ? (
          <div className="mt-3 flex gap-2">
            <Button type="button" tone="danger" onClick={reset}>Confirm reset</Button>
            <Button type="button" tone="ghost" onClick={() => setConfirm(false)}>Cancel</Button>
          </div>
        ) : (
          <Button type="button" tone="danger" className="mt-3" onClick={() => setConfirm(true)}>Reset demo data</Button>
        )}
      </section>
      <p className="text-sm text-mist">
        Setup notes live in the repository: <Link className="text-teal" to="/about">Documentation</Link>.
      </p>
    </div>
  );
}
