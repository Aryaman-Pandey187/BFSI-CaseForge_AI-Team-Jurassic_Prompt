import { useEffect, useState } from "react";
import { animate, motion, useMotionValue, useTransform } from "framer-motion";
import clsx from "clsx";
import { Gauge } from "lucide-react";
import { BAND } from "../lib/format";
import { Card, Cite, Skeleton } from "./ui";

const R = 62;
const C = 2 * Math.PI * R;

export default function RiskPanel({ call }) {
  const risk = call.risk;
  const citations = call.case?.citations;
  const running = call.stage === "ORCHESTRATING";
  const [all, setAll] = useState(false);
  const reasons = risk ? (all ? risk.reasons : risk.reasons.slice(0, 6)) : [];
  return (
    <Card title={risk?.risk_type === "CREDIT_DELINQUENCY" ? "Delinquency risk" : risk?.risk_type === "AUTHENTICATION" ? "Authentication risk" : "Fraud risk"}
      icon={Gauge} className={clsx(risk && BAND[risk.band].glow)}
      right={risk && <span className={clsx("chip", BAND[risk.band].border, BAND[risk.band].bg, BAND[risk.band].text)}>{risk.band}</span>}>
      <div className="flex flex-col items-center">
        <RiskGauge score={risk?.score} band={risk?.band} pending={!risk} running={running} />
        {risk && <p className="mt-1 text-center text-[11px] text-slate-500">{risk.reasons.length} reason codes · raw {risk.raw_points} pts</p>}
      </div>
      <div className="mt-4 space-y-2">
        {!risk && [0, 1, 2].map((i) => <Skeleton key={i} className="h-10" />)}
        {reasons.map((r, i) => (
          <motion.div key={r.code} initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.25 + i * 0.06 }}
            className="rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-xs font-semibold text-slate-100">{r.label}</div>
                <div className="font-mono text-[10px] text-slate-500">{r.code}</div>
              </div>
              <div className="flex items-center gap-1.5">
                {r.evidence.slice(0, 2).map((e) => <Cite key={e} id={e} citations={citations} />)}
                <span className={clsx("font-mono text-xs font-bold", r.points >= 15 ? "text-rose-300" : r.points >= 10 ? "text-orange-300" : "text-amber-200")}>+{r.points}</span>
              </div>
            </div>
            <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-white/5">
              <motion.div initial={{ width: 0 }} animate={{ width: `${Math.min(100, r.points * 4)}%` }} transition={{ delay: 0.35 + i * 0.06, duration: 0.6 }}
                className={clsx("h-full rounded-full", r.points >= 15 ? "bg-rose-400" : r.points >= 10 ? "bg-orange-400" : "bg-amber-300")} />
            </div>
            <div className="mt-1 text-[11px] leading-snug text-slate-400">{r.detail}</div>
          </motion.div>
        ))}
        {risk && risk.reasons.length > 6 && (
          <button onClick={() => setAll((v) => !v)} className="w-full rounded-lg border border-white/[0.06] py-1.5 text-[11px] text-slate-400 hover:bg-white/[0.04]">
            {all ? "Show top 6" : `Show all ${risk.reasons.length} reason codes`}
          </button>
        )}
        {risk && risk.reasons.length === 0 && <p className="text-center text-xs text-emerald-300">No risk signals detected.</p>}
      </div>
    </Card>
  );
}

function RiskGauge({ score, band, pending, running }) {
  const mv = useMotionValue(0);
  const rounded = useTransform(mv, (v) => Math.round(v));
  const dash = useTransform(mv, (v) => C - (C * v) / 100);
  useEffect(() => {
    if (score != null) {
      const ctl = animate(mv, score, { duration: 1.6, ease: [0.16, 1, 0.3, 1] });
      return () => ctl.stop();
    }
  }, [score, mv]);
  const color = band ? BAND[band].ring : "#6366f1";
  return (
    <div className="relative h-[160px] w-[160px]">
      {band === "CRITICAL" && <span className="absolute inset-3 animate-ping rounded-full bg-rose-500/10" />}
      <svg viewBox="0 0 160 160" className="h-full w-full -rotate-90">
        <defs>
          <linearGradient id="rg" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0" stopColor={color} stopOpacity="0.6" />
            <stop offset="1" stopColor={color} />
          </linearGradient>
        </defs>
        <circle cx="80" cy="80" r={R} stroke="rgba(255,255,255,0.06)" strokeWidth="12" fill="none" />
        {pending ? (
          <circle cx="80" cy="80" r={R} stroke="url(#rg)" strokeWidth="12" fill="none" strokeLinecap="round"
            strokeDasharray={`${C * 0.18} ${C}`} className={running ? "animate-spin [animation-duration:1.4s]" : "opacity-20"} style={{ transformOrigin: "80px 80px" }} />
        ) : (
          <motion.circle cx="80" cy="80" r={R} stroke="url(#rg)" strokeWidth="12" fill="none" strokeLinecap="round"
            strokeDasharray={C} style={{ strokeDashoffset: dash, filter: `drop-shadow(0 0 8px ${color})` }} />
        )}
      </svg>
      <div className="absolute inset-0 grid place-items-center">
        <div className="text-center">
          {pending ? (
            <div className="text-xs text-slate-500">{running ? "Scoring…" : "Awaiting"}</div>
          ) : (
            <>
              <motion.div className="text-5xl font-extrabold tabular-nums tracking-tight" style={{ color }}>{rounded}</motion.div>
              <div className="text-[10px] font-medium uppercase tracking-[0.2em] text-slate-500">/ 100</div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
