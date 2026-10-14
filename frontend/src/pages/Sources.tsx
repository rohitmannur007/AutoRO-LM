import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { Badge, Banner, Button, Empty, Field, Skeleton, controlClass } from "../components/ui";
import type { Job, Profile, SourceDocument } from "../types";

export default function Sources() {
  const queryClient = useQueryClient();
  const [source, setSource] = useState("demo_fixtures");
  const [make, setMake] = useState("honda");
  const [model, setModel] = useState("civic");
  const [year, setYear] = useState("2018");
  const [maxRecords, setMaxRecords] = useState("25");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["sources"],
    queryFn: () => api<{ items: SourceDocument[] }>("/api/v1/sources?limit=50"),
  });
  const profile = useQuery({ queryKey: ["profile"], queryFn: () => api<Profile>("/api/v1/sources/profile") });
  const detail = useQuery({
    queryKey: ["source", selected],
    enabled: Boolean(selected),
    queryFn: () => api<{ document: SourceDocument; chunks: { chunk_id: string; text: string }[] }>(`/api/v1/sources/${selected}`),
  });

  async function ingest(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const created = await api<Job>("/api/v1/ingestion/jobs", {
        method: "POST",
        body: JSON.stringify({
          source,
          make: source === "demo_fixtures" ? null : make,
          model: source === "demo_fixtures" ? null : model,
          model_year: source === "demo_fixtures" ? null : Number(year),
          max_records: Number(maxRecords) || 25,
        }),
      });
      let current = created;
      if (current.status === "queued" || current.status === "running") {
        for (let attempt = 0; attempt < 20; attempt += 1) {
          await new Promise((resolve) => setTimeout(resolve, 500));
          current = await api<Job>(`/api/v1/jobs/${created.job_id}`);
          if (current.status === "completed" || current.status === "failed") break;
        }
      }
      setJob(current);
      await queryClient.invalidateQueries({ queryKey: ["sources"] });
      await queryClient.invalidateQueries({ queryKey: ["profile"] });
      await queryClient.invalidateQueries({ queryKey: ["status"] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ingestion failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={ingest} className="grid gap-3 rounded-lg border border-line bg-panel p-4 md:grid-cols-5">
        <Field label="Source">
          <select aria-label="Source" className={controlClass} value={source} onChange={(event) => setSource(event.target.value)}>
            <option value="demo_fixtures">Reload DEMO fixtures</option>
            <option value="nhtsa_complaints">NHTSA complaints API</option>
            <option value="nhtsa_recalls">NHTSA recalls API</option>
            <option value="nhtsa_mfr_comms">NHTSA manufacturer communications file</option>
          </select>
        </Field>
        <Field label="Make"><input className={controlClass} value={make} onChange={(event) => setMake(event.target.value)} disabled={source === "demo_fixtures"} /></Field>
        <Field label="Model"><input className={controlClass} value={model} onChange={(event) => setModel(event.target.value)} disabled={source === "demo_fixtures"} /></Field>
        <Field label="Year"><input className={controlClass} value={year} onChange={(event) => setYear(event.target.value)} disabled={source === "demo_fixtures"} /></Field>
        <Field label="Max records"><input className={controlClass} value={maxRecords} onChange={(event) => setMaxRecords(event.target.value)} /></Field>
        <div className="md:col-span-5">
          <Button type="submit" disabled={busy}>{busy ? "Running job…" : "Start ingestion"}</Button>
          <p className="mt-2 text-xs text-mist">
            Real NHTSA calls are opt-in, rate-limited, and stored with provenance. Complaints drop VINs. A failed external call marks the job failed and does not invent records.
          </p>
        </div>
      </form>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          tone="ghost"
          onClick={async () => {
            setError("");
            try {
              const manifest = await api<{ complaint_documents: number; counts: Record<string, number> }>("/api/v1/sources/assign-splits", {
                method: "POST",
                body: JSON.stringify({ seed: 42 }),
              });
              setJob({
                job_id: "splits",
                job_type: "splits",
                action: "assign",
                status: "completed",
                created_at: "",
                counts: manifest.counts,
                errors: [],
                logs: [],
                metadata: { complaints: manifest.complaint_documents },
              });
              await queryClient.invalidateQueries({ queryKey: ["sources"] });
            } catch (err) {
              setError(err instanceof Error ? err.message : "Split assignment failed");
            }
          }}
        >
          Assign complaint splits
        </Button>
        <Button
          type="button"
          tone="ghost"
          onClick={async () => {
            setError("");
            try {
              const result = await api<{ enabled_count: number; refused: { document_id: string; reason: string }[] }>("/api/v1/sources/eligibility", {
                method: "POST",
                body: JSON.stringify({ confirm: "ENABLE_TRAIN_SEEDS" }),
              });
              setError("");
              setJob({
                job_id: "seeds",
                job_type: "eligibility",
                action: "enable",
                status: "completed",
                created_at: "",
                counts: { enabled: result.enabled_count, refused: result.refused.length },
                errors: result.refused.map((item) => `${item.document_id}: ${item.reason}`),
                logs: [],
                metadata: {},
              });
            } catch (err) {
              setError(err instanceof Error ? err.message : "Eligibility update failed");
            }
          }}
        >
          Enable train-only seeds
        </Button>
      </div>
      <p className="text-xs text-mist">
        Split assignment covers stored non-demo NHTSA complaints and clears their synthetic-seed flag. Enabling seeds then marks only the train split. Test, validation, and reference records stay ineligible.
      </p>
      {error ? <Banner tone="error">{error}</Banner> : null}
      {job ? (
        <Banner tone={job.status === "failed" ? "error" : "info"}>
          Job {job.job_id} is {job.status}. Counts {JSON.stringify(job.counts)}. {job.errors.join(" ")}
        </Banner>
      ) : null}
      {profile.isLoading ? <Skeleton /> : null}
      {profile.data ? (
        <section className="rounded-lg border border-line bg-panel p-4 text-sm">
          <h2 className="font-semibold">Profile from stored records</h2>
          <p className="mt-2 text-mist">
            {profile.data.record_count} records · {profile.data.demo_count} DEMO · missing make {profile.data.missing_make} · duplicate checksums {profile.data.duplicate_checksums}
          </p>
          <ul className="mt-2 list-disc pl-5 text-mist">
            {profile.data.warnings.map((warning) => <li key={warning}>{warning}</li>)}
          </ul>
        </section>
      ) : null}
      {list.isLoading ? <Skeleton className="h-40" /> : null}
      {list.data && list.data.items.length === 0 ? <Empty title="No documents" body="Reload DEMO fixtures or run an opt-in NHTSA ingestion job." /> : null}
      {list.data && list.data.items.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full text-left text-sm">
            <thead className="bg-panel text-xs uppercase text-mist">
              <tr>
                <th className="px-3 py-2">Document</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2">Vehicle</th>
                <th className="px-3 py-2">Split</th>
                <th className="px-3 py-2">Label</th>
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((item) => (
                <tr key={item.document_id} className="border-t border-line">
                  <td className="px-3 py-2">
                    <button className="text-left text-teal" onClick={() => setSelected(item.document_id)}>{item.source_name}</button>
                    <div className="font-mono text-[11px] text-mist">{item.document_id}</div>
                  </td>
                  <td className="px-3 py-2">{item.narrative_kind}</td>
                  <td className="px-3 py-2">{[item.model_year, item.make, item.model].filter(Boolean).join(" ") || "—"}</td>
                  <td className="px-3 py-2">{item.split}</td>
                  <td className="px-3 py-2">{item.demo ? <Badge tone="demo">DEMO</Badge> : <Badge tone="ok">External</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {detail.data ? (
        <article className="rounded-lg border border-line bg-panel p-4">
          <h2 className="text-sm font-semibold">{detail.data.document.source_name}</h2>
          <p className="mt-1 text-xs text-mist">Retrieved {detail.data.document.retrieved_at || "unknown"} · checksum {detail.data.document.checksum.slice(0, 12)}</p>
          {detail.data.document.source_url ? <a className="text-sm text-teal" href={detail.data.document.source_url}>Source URL</a> : <p className="text-xs text-mist">No external URL. This fixture was authored for the demo.</p>}
          <pre className="mt-3 whitespace-pre-wrap text-sm leading-6">{detail.data.document.text}</pre>
          <h3 className="mt-3 text-sm font-semibold">Provenance</h3>
          <pre className="mt-1 overflow-auto font-mono text-xs text-mist">{JSON.stringify(detail.data.document.provenance, null, 2)}</pre>
        </article>
      ) : null}
    </div>
  );
}
