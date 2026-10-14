import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { expect, vi } from "vitest";
import Ask from "../pages/Ask";
import Extract, { SAMPLE_NOTE } from "../pages/Extract";

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

test("extraction form keeps text and explains a short note", async () => {
  const user = userEvent.setup();
  wrap(<Extract />);
  const box = screen.getByLabelText("Repair note");
  await user.type(box, "short");
  await user.click(screen.getByRole("button", { name: "Run extraction" }));
  expect(screen.getByRole("alert")).toHaveTextContent(/at least a short repair note/i);
  expect(box).toHaveValue("short");
});

test("sample button fills the demo note", async () => {
  const user = userEvent.setup();
  wrap(<Extract />);
  await user.click(screen.getByRole("button", { name: "Load DEMO sample" }));
  expect(screen.getByLabelText("Repair note")).toHaveValue(SAMPLE_NOTE);
});

test("QA abstention state is visible", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => ({
        request_id: "qa_test",
        question: "torque",
        answer: "Evidence is not sufficient for a repair procedure or specification.",
        abstained: true,
        abstain_reason: "requested specification or procedure is not in the retrieved text",
        citations: [],
        retrieved_chunk_ids: [],
        retrieved: [],
        provider: { provider: "demo", is_llm: false, demo: true, caveats: [] },
        latency_ms: 3,
        demo: true,
        safety_notice: "Informational only.",
        conflicts: [],
      }),
    }),
  );
  wrap(<Ask />);
  await user.click(screen.getByRole("button", { name: "DEMO unanswerable question" }));
  await user.click(screen.getByRole("button", { name: "Ask" }));
  expect(await screen.findByText(/Evidence not sufficient/i)).toBeInTheDocument();
  vi.unstubAllGlobals();
});
