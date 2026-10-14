import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api";
import type { Health, Status } from "../types";
import { Badge } from "./ui";

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/extract", label: "Text extraction" },
  { to: "/ask", label: "Diagnostic QA" },
  { to: "/sources", label: "Data sources" },
  { to: "/synthetic", label: "Synthetic studio" },
  { to: "/experiments", label: "Experiments" },
  { to: "/training", label: "Training" },
  { to: "/settings", label: "Model & settings" },
  { to: "/about", label: "Documentation" },
];

const TITLES: Record<string, string> = {
  "/": "Overview",
  "/extract": "Text extraction",
  "/ask": "Diagnostic QA",
  "/sources": "Data sources",
  "/synthetic": "Synthetic data studio",
  "/experiments": "Experiments",
  "/training": "Training",
  "/settings": "Model & settings",
  "/about": "Documentation",
};

export default function Shell() {
  const location = useLocation();
  const health = useQuery({ queryKey: ["health"], queryFn: () => api<Health>("/api/v1/health"), refetchInterval: 20000 });
  const status = useQuery({ queryKey: ["status"], queryFn: () => api<Status>("/api/v1/status"), refetchInterval: 20000 });
  const demo = health.data?.demo_provider || status.data?.demo_data;

  return (
    <div className="min-h-screen md:grid md:grid-cols-[240px_1fr]">
      <aside className="border-b border-line bg-panel md:min-h-screen md:border-b-0 md:border-r">
        <div className="flex items-center gap-3 px-4 py-4">
          <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden="true">
            <rect width="32" height="32" rx="6" fill="#071018" />
            <path d="M6 20h20M8 20a8 8 0 0 1 16 0" fill="none" stroke="#2ec4b6" strokeWidth="2" />
            <circle cx="16" cy="14" r="2" fill="#e2b340" />
          </svg>
          <div>
            <p className="text-sm font-semibold tracking-wide">AutoRO-LM</p>
            <p className="text-[11px] text-mist">Repair-text research</p>
          </div>
        </div>
        <nav aria-label="Primary" className="flex gap-1 overflow-x-auto px-2 pb-3 md:block md:px-2">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `block whitespace-nowrap rounded-md px-3 py-2 text-sm ${isActive ? "bg-ink text-teal" : "text-mist hover:bg-panel2 hover:text-foam"}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="min-w-0">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3 md:px-6">
          <div>
            <p className="text-[11px] uppercase tracking-[0.16em] text-mist">Auto Royal M</p>
            <h1 className="text-lg font-semibold">{TITLES[location.pathname] || "AutoRO-LM"}</h1>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {demo ? <Badge tone="demo">DEMO</Badge> : <Badge tone="ok">Live provider</Badge>}
            <span className="text-mist">
              API {health.isError ? "unreachable" : health.data?.status || "…"} · DB{" "}
              {health.data?.database.active_adapter || "…"}
              {health.data?.database.fallback ? " fallback" : ""}
            </span>
          </div>
        </header>
        {demo ? (
          <p className="border-b border-amber/30 bg-amber/10 px-4 py-2 text-xs text-amber-50 md:px-6">
            Demonstration mode. Fixture records and the deterministic provider are labeled DEMO and are not an LLM, NHTSA download, or measured production model.
          </p>
        ) : null}
        <main className="px-4 py-5 md:px-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
