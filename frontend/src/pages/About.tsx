export default function About() {
  return (
    <article className="max-w-3xl space-y-4 text-sm leading-6 text-mist">
      <section className="rounded-lg border border-line bg-panel p-4">
        <h2 className="text-base font-semibold text-foam">Architecture</h2>
        <p className="mt-2">
          The React client talks to a versioned FastAPI service. Extraction and QA go through a provider interface with a deterministic demo implementation, an optional Ollama client, and an optional OpenAI-compatible extension that reads its key only from the environment.
          Retrieval is BM25 plus a local TF-IDF index, fused with reciprocal rank fusion. Persistence is SQLite unless a MongoDB URL connects successfully.
        </p>
      </section>
      <section className="rounded-lg border border-line bg-panel p-4">
        <h2 className="text-base font-semibold text-foam">Safety</h2>
        <p className="mt-2">
          Outputs are informational. They are not repair instructions. A stored diagnostic trouble code is not evidence that a part has failed. Confirm safety-critical work with the manufacturer’s service information and a qualified technician.
        </p>
      </section>
      <section className="rounded-lg border border-line bg-panel p-4">
        <h2 className="text-base font-semibold text-foam">Provenance and limits</h2>
        <p className="mt-2">
          Shipped records in <code>backend/data/demo</code> are hand-authored fixtures. NHTSA complaints and recalls can be ingested from the public API, and manufacturer communications from the official flat files. Those downloads are opt-in and are not bundled here.
          This project does not claim access to any private automotive platform, customer, or model.
        </p>
        <ul className="mt-2 list-disc pl-5">
          <li>docs/ARCHITECTURE.md</li>
          <li>docs/DATA_SOURCES.md</li>
          <li>docs/ANNOTATION_GUIDELINES.md</li>
          <li>docs/EXPERIMENT_PROTOCOL.md</li>
          <li>docs/MAC_M2_SETUP.md</li>
          <li>docs/SECURITY_AND_PRIVACY.md</li>
          <li>docs/DEMO_WALKTHROUGH.md</li>
        </ul>
      </section>
    </article>
  );
}
