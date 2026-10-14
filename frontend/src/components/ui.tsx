import type { ReactNode } from "react";

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "demo" | "ok" | "warn" | "bad" }) {
  const tones = {
    neutral: "border-line text-mist",
    demo: "border-amber/50 text-amber",
    ok: "border-teal/50 text-teal",
    warn: "border-amber/50 text-amber",
    bad: "border-red-400/50 text-red-300",
  };
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold tracking-wide ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function Button({
  children,
  tone = "primary",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { tone?: "primary" | "ghost" | "danger" }) {
  const tones = {
    primary: "bg-teal text-ink hover:bg-teal/90 disabled:bg-teal/40",
    ghost: "border border-line bg-panel2 text-foam hover:border-teal/60 disabled:opacity-50",
    danger: "border border-red-400/40 text-red-200 hover:bg-red-400/10",
  };
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed ${tones[tone]} ${props.className || ""}`}
    >
      {children}
    </button>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-foam">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-xs text-mist">{hint}</span> : null}
    </label>
  );
}

export const controlClass =
  "w-full rounded-md border border-line bg-ink px-3 py-2 text-sm text-foam placeholder:text-mist/70";

export function Banner({ tone, children }: { tone: "info" | "error" | "warn"; children: ReactNode }) {
  const tones = {
    info: "border-teal/40 bg-teal/10 text-foam",
    error: "border-red-400/40 bg-red-400/10 text-red-100",
    warn: "border-amber/40 bg-amber/10 text-amber-50",
  };
  return <div className={`rounded-md border px-3 py-2 text-sm ${tones[tone]}`}>{children}</div>;
}

export function Empty({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border border-dashed border-line px-4 py-8 text-center">
      <p className="font-semibold text-foam">{title}</p>
      <p className="mx-auto mt-1 max-w-xl text-sm text-mist">{body}</p>
    </div>
  );
}

export function Skeleton({ className = "h-16" }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-panel2 ${className}`} />;
}

export function highlight(text: string, spans: { start: number; end: number }[]) {
  if (!spans.length) return text;
  const nodes: ReactNode[] = [];
  let cursor = 0;
  spans.forEach((span, index) => {
    if (span.start > cursor) nodes.push(text.slice(cursor, span.start));
    nodes.push(<mark key={index}>{text.slice(span.start, span.end)}</mark>);
    cursor = span.end;
  });
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}
