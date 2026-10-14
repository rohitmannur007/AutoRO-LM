import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { Banner, Button, Empty, Field, controlClass } from "../components/ui";
import type { Job } from "../types";

type Adapter = { model: string; adapter_dir: string; trained: boolean; detail: string };
type Dataset = {
  train_count: number;
  real_train_count: number;
  synthetic_train_count: number;
  validation_count: number;
  mixture_share: number;
  mixture_reason?: string | null;
  gold_test_included: boolean;
  train_sha256: string;
};

export default function Training() {
  const queryClient = useQueryClient();
  const adapter = useQuery({ queryKey: ["adapter"], queryFn: () => api<Adapter>("/api/v1/training/adapter") });
  const [share, setShare] = useState("0");
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [confirm, setConfirm] = useState("");
  const [goldText, setGoldText] = useState("");
  const [goldSplit, setGoldSplit] = useState("train");
  const [goldGroup, setGoldGroup] = useState("");
  const [symptom, setSymptom] = useState("");
  const [dtc, setDtc] = useState("");
  const [component, setComponent] = useState("");

  async function prepare() {
    setBusy("data");
    setError("");
    try {
      const body = await api<Dataset>("/api/v1/training/datasets", {
        method: "POST",
        body: JSON.stringify({ dry_run: true, mixture_share: Number(share) }),
      });
      setDataset(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Dataset build failed");
    } finally {
      setBusy("");
    }
  }

  async function launch(dryRun: boolean) {
    setBusy(dryRun ? "dry" : "train");
    setError("");
    try {
      const created = await api<Job>("/api/v1/training/jobs", {
        method: "POST",
        body: JSON.stringify({
          dry_run: dryRun,
          mixture_share: Number(share),
          confirm: dryRun ? "" : confirm,
        }),
      });
      setJob(created);
      await queryClient.invalidateQueries({ queryKey: ["adapter"] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Training request failed");
    } finally {
      setBusy("");
    }
  }

  async function saveGold(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setBusy("gold");
    try {
      await api("/api/v1/gold", {
        method: "POST",
        body: JSON.stringify({
          example_id: `gold-${Date.now()}`,
          source_group: goldGroup,
          input_text: goldText,
          split: goldSplit,
          reviewer_id: "local-reviewer",
          demo: false,
          target: {
            symptom: symptom.trim() || null,
            dtc_codes: dtc.trim() ? dtc.split(/[\s,]+/).filter(Boolean) : [],
            component: component.trim() || null,
            suspected_component: null,
            repair_action: null,
            complaint: null,
            cause: null,
            correction: null,
            vehicle: { make: null, model: null, model_year: null },
          },
        }),
      });
      setGoldText("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gold example was rejected");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-4">
      <Banner tone="info">
        A dry run writes train JSONL from the train split and does not start MLX. A real fine-tune requires mlx-lm, a model download, and the confirmation text TRAIN_MLX. Until an adapter exists, extraction stays on the demo or another configured provider.
      </Banner>
      {adapter.data ? (
        <section className="rounded-lg border border-line bg-panel p-4 text-sm">
          <h2 className="font-semibold">Adapter</h2>
          <p className="mt-2 text-mist">{adapter.data.detail}</p>
          <p className="mt-1 font-mono text-xs text-mist">{adapter.data.model}</p>
          <p className="font-mono text-xs text-mist">{adapter.data.adapter_dir}</p>
          <p className="mt-2">{adapter.data.trained ? "A completed adapter is stored." : "No completed adapter is stored."}</p>
        </section>
      ) : null}
      <section className="space-y-3 rounded-lg border border-line bg-panel p-4">
        <Field label="Synthetic share">
          <select aria-label="Synthetic share" className={controlClass} value={share} onChange={(event) => setShare(event.target.value)}>
            <option value="0">0% synthetic</option>
            <option value="0.25">25% synthetic</option>
            <option value="0.5">50% synthetic</option>
            <option value="0.75">75% synthetic</option>
            <option value="1">100% synthetic</option>
          </select>
        </Field>
        <div className="flex flex-wrap gap-2">
          <Button type="button" tone="ghost" disabled={busy === "data"} onClick={prepare}>{busy === "data" ? "Preparing…" : "Build train JSONL"}</Button>
          <Button type="button" tone="ghost" disabled={busy === "dry"} onClick={() => launch(true)}>{busy === "dry" ? "Checking…" : "Dry run"}</Button>
        </div>
        <Field label="Confirmation for a real MLX run">
          <input aria-label="Training confirmation" className={controlClass} value={confirm} onChange={(event) => setConfirm(event.target.value)} placeholder="TRAIN_MLX" />
        </Field>
        <Button type="button" disabled={busy === "train" || confirm !== "TRAIN_MLX"} onClick={() => launch(false)}>
          {busy === "train" ? "Starting…" : "Launch MLX LoRA"}
        </Button>
        <p className="text-xs text-mist">The launch button stays disabled until the confirmation matches. A missing mlx-lm install fails the job.</p>
      </section>
      {dataset ? (
        <section className="rounded-lg border border-line bg-panel p-4 text-sm">
          <h2 className="font-semibold">Dataset manifest</h2>
          <p className="mt-2 text-mist">
            {dataset.train_count} train rows ({dataset.real_train_count} real, {dataset.synthetic_train_count} synthetic) · validation {dataset.validation_count} · test included {dataset.gold_test_included ? "yes" : "no"}
          </p>
          {dataset.mixture_reason ? <p className="mt-1 text-mist">{dataset.mixture_reason}</p> : null}
          <p className="mt-1 font-mono text-xs text-mist">sha256 {dataset.train_sha256}</p>
        </section>
      ) : (
        <Empty title="No dataset built in this session" body="Build train JSONL to see counts. Test-split gold is excluded." />
      )}
      {job ? (
        <Banner tone={job.status === "failed" ? "error" : "info"}>
          Job {job.job_id} is {job.status}. Trained {String(job.metadata.trained)}. {job.errors.join(" ")}
        </Banner>
      ) : null}
      {error ? <Banner tone="error">{error}</Banner> : null}
      <form onSubmit={saveGold} className="space-y-3 rounded-lg border border-line bg-panel p-4">
        <h2 className="text-sm font-semibold">Gold label</h2>
        <p className="text-xs text-mist">
          Leave a field blank when the text does not support it. A saved test example cannot share a source group with a train example. This is a local annotation record, not a generated label.
        </p>
        <Field label="Source group">
          <input aria-label="Source group" className={controlClass} value={goldGroup} onChange={(event) => setGoldGroup(event.target.value)} required />
        </Field>
        <Field label="Source text">
          <textarea aria-label="Gold source text" className={`${controlClass} min-h-28`} value={goldText} onChange={(event) => setGoldText(event.target.value)} required />
        </Field>
        <Field label="Symptom">
          <input aria-label="Gold symptom" className={controlClass} value={symptom} onChange={(event) => setSymptom(event.target.value)} />
        </Field>
        <Field label="DTC codes">
          <input aria-label="Gold DTC codes" className={controlClass} value={dtc} onChange={(event) => setDtc(event.target.value)} placeholder="P0420" />
        </Field>
        <Field label="Confirmed component">
          <input aria-label="Gold component" className={controlClass} value={component} onChange={(event) => setComponent(event.target.value)} />
        </Field>
        <Field label="Split">
          <select aria-label="Gold split" className={controlClass} value={goldSplit} onChange={(event) => setGoldSplit(event.target.value)}>
            <option value="train">train</option>
            <option value="validation">validation</option>
            <option value="test">test</option>
          </select>
        </Field>
        <Button type="submit" disabled={busy === "gold"}>{busy === "gold" ? "Saving…" : "Save gold example"}</Button>
      </form>
    </div>
  );
}
