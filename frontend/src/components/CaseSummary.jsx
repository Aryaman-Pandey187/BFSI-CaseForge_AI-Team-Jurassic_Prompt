import { motion } from "framer-motion";
import clsx from "clsx";
import { AlertTriangle, CheckCircle2, ClipboardList, Info, Sparkles } from "lucide-react";
import { BAND, titleCase } from "../lib/format";
import { Card, Cite, Skeleton } from "./ui";

const SEV = {
  critical: { icon: AlertTriangle, cls: "text-rose-300" },
  warning: { icon: AlertTriangle, cls: "text-amber-300" },
  info: { icon: Info, cls: "text-sky-300" },
};

export default function CaseSummary({ call }) {
  const c = call.case;
  if (!c) {
    const working = call.stage === "ORCHESTRATING";
    return (
      <Card title="Case summary" icon={ClipboardList}>
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <Sparkles className={clsx("h-3.5 w-3.5 text-indigo-300", working && "animate-pulse")} />
            {working ? "Agents are assembling the case…" : call.intent ? "Routing…" : "The case file will appear here once the caller explains their issue."}
          </div>
          {call.intent && (
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 text-xs">
              <div className="font-semibold text-slate-200">{titleCase(call.intent.intent)} <span className="font-normal text-slate-500">· {Math.round(call.intent.confidence * 100)}% · {call.intent.engine}</span></div>
              <div className="mt-1 text-slate-400">{call.intent.summary}</div>
              <Entities entities={call.intent.entities} />
            </div>
          )}
          <Skeleton className="h-5 w-3/4" /><Skeleton className="h-16" /><Skeleton className="h-9" /><Skeleton className="h-9" />
        </div>
      </Card>
    );
  }
  const band = BAND[c.risk.band];
  const resolved = c.status === "RESOLVED_BY_AI";
  return (
    <Card title="Case summary" icon={ClipboardList} accent={resolved ? "from-transparent via-emerald-400/70 to-transparent" : "from-transparent via-rose-400/60 to-transparent"}
      right={<div className="flex items-center gap-1.5">
        <span className="chip border-white/10 font-mono text-slate-300">{c.case_id}</span>
        <span className={clsx("chip", band.border, band.bg, band.text)}>{c.priority}</span>
      </div>}>
      <motion.h3 initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-lg font-semibold leading-snug text-white sm:text-xl">
        {c.summary.headline}
      </motion.h3>
      <div className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
        <span className="chip border-indigo-400/30 bg-indigo-500/10 text-indigo-200">{titleCase(c.intent.intent)}</span>
        <span className="chip border-white/10 text-slate-300">→ {c.queue}</span>
        {resolved ? <span className="chip border-emerald-400/30 bg-emerald-500/10 text-emerald-200"><CheckCircle2 className="h-3 w-3" /> Resolved by AI</span>
          : <span className="chip border-amber-400/30 bg-amber-500/10 text-amber-200">Awaiting human agent</span>}
        <span className="chip border-white/10 text-slate-500">summary: {c.assembler_engine === "gemini" ? "Gemini" : "templates"}</span>
      </div>
      <p className="mt-3 text-[13px] leading-relaxed text-slate-300">{c.summary.narrative}</p>
      <Entities entities={c.intent.entities} />
      <ul className="mt-4 space-y-2">
        {c.summary.key_findings.map((f, i) => {
          const s = SEV[f.severity] || SEV.info;
          return (
            <motion.li key={i} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.05 * i }}
              className="flex gap-2.5 rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2 text-[12.5px] text-slate-200">
              <s.icon className={clsx("mt-0.5 h-3.5 w-3.5 shrink-0", s.cls)} />
              <span className="flex-1">{f.text}</span>
              <span className="flex shrink-0 gap-1">{f.citations.map((id) => <Cite key={id} id={id} citations={c.citations} />)}</span>
            </motion.li>
          );
        })}
      </ul>
      <div className="mt-4 rounded-xl border border-cyan-400/15 bg-cyan-500/[0.05] p-3">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-cyan-300/80">What the AI told the caller</div>
        <p className="mt-1 text-[12.5px] italic text-slate-300">“{c.caller_message}”</p>
      </div>
    </Card>
  );
}

function Entities({ entities }) {
  const e = Object.entries(entities || {});
  if (!e.length) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-1.5">
      {e.map(([k, v]) => (
        <span key={k} className="kbd">
          <span className="text-slate-500">{k.replace(/_/g, " ")}:</span>{" "}
          {Array.isArray(v) ? v.join(", ") : typeof v === "boolean" ? (v ? "yes" : "no") : typeof v === "number" && k === "amount" ? `₹${v.toLocaleString("en-IN")}` : String(v)}
        </span>
      ))}
    </div>
  );
}
