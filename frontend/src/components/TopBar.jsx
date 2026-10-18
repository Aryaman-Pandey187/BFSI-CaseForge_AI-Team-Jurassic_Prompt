import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import clsx from "clsx";
import { ChevronDown, Home, Cpu, Database, Headphones, PhoneCall, PhoneOff, Play, Radio, Square } from "lucide-react";
import { duration } from "../lib/format";
import { api } from "../hooks/useDesktopSocket";
import { Waveform } from "./ui";

const STAGES = ["IDENTITY", "INTENT", "ORCHESTRATING", "HANDOFF"];

export function useNow(active) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

export default function TopBar({ state, call, onSelect, onHome }) {
  const cfg = state.config;
  const live = call && !call.ended;
  const now = useNow(live);
  const secs = call ? ((call.ended ? new Date(call.ended.at) : now) - new Date(call.startedAt)) / 1000 : 0;
  const [open, setOpen] = useState(false);

  const simulate = async (id) => {
    setOpen(false);
    await api("/api/simulate", { scenario: id });
  };

  return (
    <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-ink-950/70 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1680px] flex-wrap items-center gap-3 px-4 py-3 sm:px-6">
        <button onClick={onHome} title="Back to home" className="flex items-center gap-3 text-left">
          <div className="relative grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-indigo-500 to-cyan-400 shadow-glow">
            <Headphones className="h-[18px] w-[18px] text-white" />
          </div>
          <div className="leading-tight">
            <div className="text-[15px] font-bold tracking-tight text-white">
              CaseForge <span className="text-gradient">AI</span>
            </div>
            <div className="text-[11px] text-slate-500">{cfg?.bank_name || "Horizon Bank"} · Agent Desktop</div>
          </div>
        </button>

        {/* live call pill */}
        <div className="order-3 flex w-full items-center justify-center lg:order-none lg:w-auto lg:flex-1">
          {call ? (
            <motion.div layout className={clsx("flex items-center gap-3 rounded-full border px-3 py-1.5 text-xs",
              live ? "border-emerald-400/30 bg-emerald-500/10" : "border-white/10 bg-white/[0.03]")}>
              {live ? (
                <span className="relative flex h-2.5 w-2.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-70" />
                  <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-400" />
                </span>
              ) : <PhoneOff className="h-3.5 w-3.5 text-slate-500" />}
              <span className={clsx("font-semibold", live ? "text-emerald-200" : "text-slate-400")}>
                {live ? "LIVE" : "ENDED"}
              </span>
              <span className="font-mono text-slate-300">{duration(secs)}</span>
              <span className="hidden h-4 w-px bg-white/10 sm:block" />
              <div className="hidden items-center gap-1 sm:flex">
                {STAGES.map((s) => {
                  const idx = STAGES.indexOf(call.stage === "RESOLVED" ? "HANDOFF" : call.stage);
                  const me = STAGES.indexOf(s);
                  const doneOrActive = call.stage === "ENDED" || me <= idx;
                  return <span key={s} className={clsx("h-1.5 w-6 rounded-full transition-colors duration-500",
                    doneOrActive ? (me === idx && live ? "bg-indigo-400 animate-pulse" : "bg-indigo-400/70") : "bg-white/10")} />;
                })}
              </div>
              <span className="text-slate-300">{call.stageLabel}</span>
              {live && (
                <span className="flex items-center gap-1.5 text-slate-400">
                  <Waveform active={call.voice === "speaking"} color="bg-cyan-300" bars={4} />
                  <span className="hidden capitalize md:inline">{call.voice === "speaking" ? "AI speaking" : call.voice === "thinking" ? "Thinking" : "Listening"}</span>
                </span>
              )}
            </motion.div>
          ) : (
            <div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs text-slate-400">
              <Radio className="h-3.5 w-3.5 text-indigo-300" /> Waiting for incoming call
            </div>
          )}
        </div>

        <div className="ml-auto flex items-center gap-2">
          {call && (
            <button onClick={onHome}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs font-semibold text-slate-200 transition hover:bg-white/5">
              <Home className="h-3.5 w-3.5" /> Home
            </button>
          )}
          {state.order.length > 1 && (
            <select
              value={state.selected || ""}
              onChange={(e) => onSelect(e.target.value || null)}
              className="hidden rounded-lg border border-white/10 bg-ink-900 px-2 py-1.5 text-xs text-slate-300 md:block"
            >
              <option value="">Follow latest call</option>
              {state.order.map((id) => (
                <option key={id} value={id}>{state.calls[id]?.customer?.full_name || id} · {id.slice(0, 12)}</option>
              ))}
            </select>
          )}
          <div className="hidden items-center gap-1.5 xl:flex">
            <Badge icon={Cpu} label={cfg?.llm_mode === "mock" ? "Offline agents" : cfg?.model || "Gemini"} tone={cfg?.llm_mode === "mock" ? "amber" : "indigo"} />
            <Badge icon={Database} label={cfg?.data_backend || "—"} />
            <Badge icon={PhoneCall} label={cfg?.voice_mode?.replace("_", " ") || "—"} />
          </div>
          <div className="relative">
            <button onClick={() => setOpen((o) => !o)}
              className="flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-indigo-500 to-cyan-500 px-3 py-1.5 text-xs font-semibold text-white shadow-glow transition hover:brightness-110">
              <Play className="h-3.5 w-3.5" /> Simulate call <ChevronDown className="h-3.5 w-3.5" />
            </button>
            {open && (
              <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
                className="absolute right-0 mt-2 w-72 overflow-hidden rounded-xl border border-white/10 bg-ink-900/95 p-1 shadow-2xl backdrop-blur-xl">
                {cfg?.scenarios?.map((s) => (
                  <button key={s.id} onClick={() => simulate(s.id)} className="w-full rounded-lg px-3 py-2 text-left hover:bg-white/5">
                    <div className="text-sm font-medium text-slate-100">{s.title}</div>
                    <div className="text-[11px] text-slate-500">{s.customer}</div>
                  </button>
                ))}
                <button onClick={() => { setOpen(false); api("/api/simulate/stop", {}); }}
                  className="mt-1 flex w-full items-center gap-2 rounded-lg border-t border-white/5 px-3 py-2 text-left text-xs text-rose-300 hover:bg-rose-500/10">
                  <Square className="h-3 w-3" /> Stop simulated calls
                </button>
              </motion.div>
            )}
          </div>
          <span title={state.connected ? "Real-time link connected" : "Reconnecting…"}
            className={clsx("h-2.5 w-2.5 rounded-full", state.connected ? "bg-emerald-400 shadow-[0_0_10px_#34d399]" : "animate-pulse bg-rose-500")} />
        </div>
      </div>
    </header>
  );
}

function Badge({ icon: Icon, label, tone = "slate" }) {
  const tones = { slate: "border-white/10 text-slate-400", indigo: "border-indigo-400/30 text-indigo-200", amber: "border-amber-400/30 text-amber-200" };
  return (
    <span className={clsx("chip bg-white/[0.02] capitalize", tones[tone])}>
      <Icon className="h-3 w-3" /> {label}
    </span>
  );
}
