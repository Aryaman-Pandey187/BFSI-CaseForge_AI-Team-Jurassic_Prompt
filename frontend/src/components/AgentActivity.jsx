import { AnimatePresence, motion } from "framer-motion";
import clsx from "clsx";
import { Activity, BadgeCheck, CheckCircle2, ChevronRight, FileText, Gauge, GitBranch, Loader2, Mic, Network, XCircle } from "lucide-react";
import { titleCase } from "../lib/format";
import { Card, ICONS } from "./ui";

/** Live Agent Activity: the pipeline header + one card per (parallel) sub-agent. */
export default function AgentActivity({ call }) {
  const agents = call.agentOrder.map((id) => call.agents[id]).filter(Boolean);
  const enrichers = agents.filter((a) => !["risk_scoring", "case_assembler", "identity"].includes(a.id) && a.title);
  const risk = call.agents.risk_scoring;
  const asm = call.agents.case_assembler;
  const running = agents.filter((a) => a.status === "running").length;
  const doneCount = enrichers.filter((a) => a.status === "done").length;

  const steps = [
    { key: "stt", label: "Voice loop", sub: call.channel === "phone" ? "STT ⇄ TTS" : titleCase(call.channel), icon: Mic, state: "done" },
    { key: "id", label: "Identity Agent", sub: call.identity?.status === "verified" ? "verified" : call.identity?.status === "failed" ? "failed" : "lookup_customer", icon: BadgeCheck,
      state: call.identity?.status === "verified" ? "done" : call.identity?.status === "failed" ? "error" : "running" },
    { key: "intent", label: "Intent & Routing", sub: call.intent ? `${titleCase(call.intent.intent)} · ${Math.round(call.intent.confidence * 100)}%` : "route_case",
      icon: GitBranch, state: call.intent ? "done" : call.identity?.status === "verified" ? "running" : "idle" },
    { key: "orch", label: call.orchestrator?.title?.replace(" Orchestrator", "") || "Orchestrator", sub: call.orchestrator ? `${doneCount}/${enrichers.length} agents` : "fan-out",
      icon: Network, state: call.orchestrator ? (doneCount === enrichers.length && enrichers.length ? "done" : "running") : "idle" },
    { key: "risk", label: "Risk Scoring", sub: call.risk ? `${call.risk.score}/100` : "deterministic", icon: Gauge, state: risk?.status || "idle" },
    { key: "asm", label: "Case Assembler", sub: call.case ? call.case.priority + " · cited" : "summary + citations", icon: FileText, state: asm?.status || "idle" },
  ];

  return (
    <Card title="Live agent activity" icon={Activity}
      right={<span className="flex items-center gap-2 text-[11px] text-slate-500">
        {running > 0 && <span className="chip border-indigo-400/30 bg-indigo-500/10 text-indigo-200"><Loader2 className="h-3 w-3 animate-spin" />{running} running in parallel</span>}
        {call.case && <span className="chip border-emerald-400/30 bg-emerald-500/10 text-emerald-200"><CheckCircle2 className="h-3 w-3" /> case ready in {(call.case.timings?.orchestration_ms / 1000).toFixed(1)}s</span>}
      </span>}>
      {/* pipeline */}
      <div className="-mx-1 flex items-stretch gap-1 overflow-x-auto px-1 pb-2">
        {steps.map((s, i) => (
          <div key={s.key} className="flex min-w-[150px] flex-1 items-center gap-1">
            <Step step={s} />
            {i < steps.length - 1 && <ChevronRight className={clsx("h-4 w-4 shrink-0", s.state === "done" ? "text-indigo-300" : "text-slate-700")} />}
          </div>
        ))}
      </div>

      {/* parallel sub-agents */}
      {enrichers.length > 0 ? (
        <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
          <AnimatePresence>
            {enrichers.map((a, i) => <AgentCard key={a.id} a={a} i={i} />)}
          </AnimatePresence>
        </div>
      ) : (
        <p className="mt-2 text-xs text-slate-500">
          Specialist agents fan out in parallel as soon as the caller is verified and the intent is known.
        </p>
      )}
    </Card>
  );
}

function Step({ step }) {
  const Icon = step.icon;
  const st = step.state;
  return (
    <motion.div layout className={clsx("relative flex flex-1 items-center gap-2.5 overflow-hidden rounded-xl border px-3 py-2 transition-colors duration-500",
      st === "done" ? "border-indigo-400/25 bg-indigo-500/[0.08]" : st === "running" ? "border-cyan-400/30 bg-cyan-500/[0.06]" : st === "error" ? "border-rose-400/30 bg-rose-500/10" : "border-white/[0.05] bg-white/[0.015]")}>
      {st === "running" && <div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-cyan-300/10 to-transparent" />}
      <div className={clsx("grid h-7 w-7 shrink-0 place-items-center rounded-lg",
        st === "done" ? "bg-indigo-500/30 text-indigo-100" : st === "running" ? "bg-cyan-500/20 text-cyan-200" : "bg-white/5 text-slate-500")}>
        {st === "running" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Icon className="h-3.5 w-3.5" />}
      </div>
      <div className="min-w-0">
        <div className={clsx("truncate text-xs font-semibold", st === "idle" ? "text-slate-500" : "text-slate-100")}>{step.label}</div>
        <div className="truncate text-[10px] text-slate-500">{step.sub}</div>
      </div>
    </motion.div>
  );
}

function AgentCard({ a, i }) {
  const Icon = ICONS[a.icon] || ICONS.bot;
  const st = a.status || "queued";
  return (
    <motion.div layout initial={{ opacity: 0, y: 12, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ delay: i * 0.05 }}
      className={clsx("relative overflow-hidden rounded-xl border p-3",
        st === "done" ? "border-emerald-400/20 bg-emerald-500/[0.04]" : st === "running" ? "border-cyan-400/30 bg-cyan-500/[0.05]" : st === "error" ? "border-rose-400/30" : "border-white/[0.06] bg-white/[0.02]")}>
      {st === "running" && <div className="absolute inset-x-0 top-0 h-0.5 overflow-hidden"><div className="h-full w-1/2 animate-shimmer bg-gradient-to-r from-transparent via-cyan-300 to-transparent" /></div>}
      <div className="flex items-center gap-2">
        <div className={clsx("grid h-8 w-8 place-items-center rounded-lg", st === "done" ? "bg-emerald-500/15 text-emerald-200" : "bg-white/5 text-cyan-200")}>
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-semibold text-slate-100">{a.title}</div>
          <div className="flex items-center gap-1 text-[10px] text-slate-500">
            {st === "running" && <><Loader2 className="h-3 w-3 animate-spin text-cyan-300" /> running</>}
            {st === "done" && <><CheckCircle2 className="h-3 w-3 text-emerald-400" /> {a.durationMs ? `${(a.durationMs / 1000).toFixed(2)}s` : "done"} · {a.engine === "gemini" ? "Gemini" : "rules"}</>}
            {st === "queued" && "queued"}
            {st === "error" && <><XCircle className="h-3 w-3 text-rose-400" /> error</>}
          </div>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {(a.tools?.length ? a.tools : (a.toolNames || []).map((t) => ({ tool: t, status: "queued" }))).map((t, j) => (
          <span key={j} title={t.summary || ""} className={clsx("chip font-mono text-[10px]",
            t.status === "done" ? "border-emerald-400/20 text-emerald-200" : t.status === "running" ? "border-cyan-400/30 text-cyan-200" : "border-white/10 text-slate-500")}>
            {t.status === "running" && <Loader2 className="h-2.5 w-2.5 animate-spin" />}
            {t.tool}{t.evidence ? ` · ${t.evidence}` : ""}
          </span>
        ))}
      </div>
      <AnimatePresence>
        {a.headline && (
          <motion.p initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} className="mt-2 text-[11.5px] leading-snug text-slate-300">
            {a.headline}
          </motion.p>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
