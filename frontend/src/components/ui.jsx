import { motion } from "framer-motion";
import clsx from "clsx";
import {
  Banknote, Bot, Calendar, FileText, Fingerprint, Gauge, HeartPulse, History, Inbox, Layers, Link2, Receipt,
  ShieldAlert, User,
} from "lucide-react";

export const ICONS = {
  user: User, receipt: Receipt, shield: ShieldAlert, fingerprint: Fingerprint, banknote: Banknote, link: Link2,
  calendar: Calendar, history: History, heart: HeartPulse, layers: Layers, inbox: Inbox, gauge: Gauge, file: FileText,
  bot: Bot,
};

export function Card({ title, icon: Icon, right, className, children, delay = 0, accent }) {
  return (
    <motion.section
      layout
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, delay, ease: [0.22, 1, 0.36, 1] }}
      className={clsx("glass p-4 sm:p-5", className)}
    >
      {accent && <div className={clsx("pointer-events-none absolute inset-x-6 -top-px h-px bg-gradient-to-r", accent)} />}
      {(title || right) && (
        <header className="mb-3 flex items-center justify-between gap-3">
          <h2 className="card-title">
            {Icon && <Icon className="h-3.5 w-3.5 text-indigo-300" />}
            {title}
          </h2>
          {right}
        </header>
      )}
      {children}
    </motion.section>
  );
}

export function Cite({ id, citations }) {
  const c = citations?.find((x) => x.id === id);
  return (
    <span className="cite" title={c ? `${c.tool} · ${c.agent}\n${c.source}\n${c.summary}` : id}>
      {id}
    </span>
  );
}

export function Empty({ icon: Icon = Bot, text, sub }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-8 text-center">
      <div className="rounded-2xl border border-white/5 bg-white/[0.03] p-3">
        <Icon className="h-5 w-5 text-slate-500" />
      </div>
      <p className="text-sm text-slate-400">{text}</p>
      {sub && <p className="max-w-xs text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

export function Skeleton({ className }) {
  return (
    <div className={clsx("relative overflow-hidden rounded-lg bg-white/[0.04]", className)}>
      <div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-white/[0.06] to-transparent" />
    </div>
  );
}

export function Stat({ label, value, sub, className }) {
  return (
    <div className={clsx("rounded-xl border border-white/[0.06] bg-white/[0.025] px-3 py-2.5", className)}>
      <div className="text-[10px] font-medium uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-0.5 truncate text-sm font-semibold text-slate-100">{value}</div>
      {sub && <div className="truncate text-[11px] text-slate-500">{sub}</div>}
    </div>
  );
}

export function Waveform({ active, color = "bg-indigo-400", bars = 5 }) {
  return (
    <div className="flex h-4 items-center gap-[3px]">
      {Array.from({ length: bars }).map((_, i) => (
        <span
          key={i}
          className={clsx("w-[3px] rounded-full", color, active ? "animate-wave" : "opacity-30")}
          style={{ height: "100%", animationDelay: `${i * 0.12}s`, transform: active ? undefined : "scaleY(0.3)" }}
        />
      ))}
    </div>
  );
}
