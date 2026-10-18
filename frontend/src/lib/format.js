// Formatting helpers shared by the desktop components.

export function inr(v, opts = {}) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: opts.decimals ?? 0,
  }).format(n);
}

export function compactInr(v) {
  const n = Number(v || 0);
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  if (n >= 1e3) return `₹${(n / 1e3).toFixed(1)}k`;
  return `₹${n.toFixed(0)}`;
}

const IST = "Asia/Kolkata";

export function timeIST(iso, withDate = false) {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00+05:30` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  const opts = withDate
    ? { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: IST }
    : { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZone: IST };
  return d.toLocaleString("en-IN", opts);
}

export function dateIST(iso) {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00+05:30` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric", timeZone: IST });
}

export function duration(sec) {
  const s = Math.max(0, Math.floor(sec));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export function initials(name = "") {
  return name.split(" ").filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";
}

export const BAND = {
  LOW: { text: "text-emerald-300", ring: "#10b981", bg: "bg-emerald-500/10", border: "border-emerald-400/30", glow: "shadow-glow-emerald" },
  MEDIUM: { text: "text-amber-300", ring: "#f59e0b", bg: "bg-amber-500/10", border: "border-amber-400/30", glow: "" },
  HIGH: { text: "text-orange-300", ring: "#f97316", bg: "bg-orange-500/10", border: "border-orange-400/30", glow: "" },
  CRITICAL: { text: "text-rose-300", ring: "#f43f5e", bg: "bg-rose-500/10", border: "border-rose-400/40", glow: "shadow-glow-rose" },
};

export const titleCase = (s = "") => s.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
