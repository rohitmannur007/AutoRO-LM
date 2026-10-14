import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Badge, Banner, Empty, Skeleton } from "../components/ui";
import type { Health, Status } from "../types";

export default function Overview() {
  const health = useQuery({ queryKey: ["health"], queryFn: () => api<Health>("/api/v1/health") });
  const status = useQuery({ queryKey: ["status"], queryFn: () => api<Status>("/api/v1/status") });
  const runs = useQuery({
    queryKey: ["experiments"],
    queryFn: () => api<{ items: { run_id: string; task: string; status: string }[] }>("/api/v1/experiments"),
  });

  if (health.isLoading || status.isLoading) {
    return (
      <div className="grid gap-3 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-24" />
        ))}
      </div>
    );
  }
  if (health.isError || status.isError) {
    return (
      <Banner tone="error">
        The API did not respond. Start the backend on port 8000, then retry.{" "}
        <button className="underline" onClick={() => { health.refetch(); status.refetch(); }}>
          Retry
        </button>
      </Banner>
    );
  }
  const counts = status.data!.counts;
  const cards = [
    ["Documents", counts.documents],
    ["Chunks", counts.chunks],
    ["Gold examples", counts.gold_examples],
    ["Synthetic approved", counts.synthetic_approved],
  ];
  return (
    <div className="space-y-5">
      <Banner tone="warn">{status.data!.safety_notice}</Banner>
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map(([label, value]) => (
          <article key={String(label)} className="rounded-lg border border-line bg-panel px-4 py-3 shadow-inset">
            <p className="text-xs uppercase tracking-wide text-mist">{label}</p>
            <p className="mt-1 font-mono text-2xl">{value ?? 0}</p>
            {status.data!.demo_data ? <Badge tone="demo">DEMO fixtures</Badge> : null}
          </article>
        ))}
      </section>
      <section className="grid gap-4 lg:grid-cols-2">
        <article className="rounded-lg border border-line bg-panel p-4">
          <h2 className="text-sm font-semibold">What this prototype does</h2>
          <p className="mt-2 text-sm leading-6 text-mist">
            AutoRO-LM turns noisy automotive notes into schema-checked JSON and answers questions only from retrieved passages.
            It is a public-data research prototype. It does not connect to any private repair network, customer system, or proprietary model.
          </p>
          <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
            <dt className="text-mist">Schema</dt>
            <dd className="font-mono">{health.data!.schema_version}</dd>
            <dt className="text-mist">Retrieval</dt>
            <dd className="font-mono">{String(health.data!.retrieval.lexical)} / {String(health.data!.retrieval.vector)}</dd>
            <dt className="text-mist">Database</dt>
            <dd>{health.data!.database.detail}</dd>
          </dl>
        </article>
        <article className="rounded-lg border border-line bg-panel p-4">
          <h2 className="text-sm font-semibold">Providers</h2>
          <ul className="mt-3 space-y-2">
            {health.data!.providers.map((provider) => (
              <li key={provider.role} className="rounded-md border border-line px-3 py-2 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{provider.role}</span>
                  <Badge tone={provider.available ? (provider.demo ? "demo" : "ok") : "bad"}>
                    {provider.available ? provider.name : "unavailable"}
                  </Badge>
                </div>
                <p className="mt-1 text-mist">{provider.detail}</p>
              </li>
            ))}
          </ul>
        </article>
      </section>
      <section className="rounded-lg border border-line bg-panel p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Recent jobs</h2>
          <Link className="text-sm text-teal" to="/sources">Ingestion</Link>
        </div>
        {status.data!.recent_jobs.length === 0 ? (
          <Empty title="No jobs yet" body="Load fixtures again from Data sources, or run an evaluation from Experiments. Counts above come from the local database, not from placeholder telemetry." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-mist">
                <tr>
                  <th className="py-2 pr-3">Job</th>
                  <th className="py-2 pr-3">Type</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2">Counts</th>
                </tr>
              </thead>
              <tbody>
                {status.data!.recent_jobs.map((job) => (
                  <tr key={job.job_id} className="border-t border-line">
                    <td className="py-2 pr-3 font-mono text-xs">{job.job_id}</td>
                    <td className="py-2 pr-3">{job.action}</td>
                    <td className="py-2 pr-3">{job.status}</td>
                    <td className="py-2 font-mono text-xs">{JSON.stringify(job.counts)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="rounded-lg border border-line bg-panel p-4">
        <h2 className="text-sm font-semibold">Evaluations</h2>
        {runs.data && runs.data.items.length > 0 ? (
          <p className="mt-2 text-sm text-mist">{runs.data.items.length} stored run{runs.data.items.length === 1 ? "" : "s"}. Open Experiments to inspect measured metrics.</p>
        ) : (
          <Empty title="No measured evaluation results" body="Run extraction, retrieval, or classifier evaluations from the Experiments page. This screen will not draw a chart until those runs exist in the database." />
        )}
      </section>
    </div>
  );
}
