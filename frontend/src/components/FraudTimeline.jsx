import { motion } from "framer-motion";
import clsx from "clsx";
import { AlertOctagon, CreditCard, KeyRound, ShieldAlert, Clock3 } from "lucide-react";
import { timeIST, dateIST } from "../lib/format";
import { Card, Empty } from "./ui";

const KIND = {
  fraud_flag: { icon: ShieldAlert, dot: "bg-fuchsia-400" },
  auth_event: { icon: KeyRound, dot: "bg-amber-400" },
  transaction: { icon: CreditCard, dot: "bg-rose-400" },
};

export default function FraudTimeline({ call }) {
  const items = call.case?.timeline || [];
  return (
    <Card title="Fraud & alert timeline" icon={Clock3}>
      {items.length === 0 ? (
        <Empty icon={AlertOctagon} text={call.case ? "No prior alerts, SARs or risky events" : "Timeline builds as agents report"} />
      ) : (
        <ol className="relative max-h-[460px] space-y-3 overflow-y-auto pl-5 pr-1">
          <span className="absolute bottom-2 left-[7px] top-2 w-px bg-gradient-to-b from-rose-400/50 via-white/10 to-transparent" />
          {items.map((it, i) => {
            const k = KIND[it.kind] || KIND.auth_event;
            return (
              <motion.li key={i} initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }} className="relative">
                <span className={clsx("absolute -left-[17px] top-1.5 h-2.5 w-2.5 rounded-full ring-4 ring-ink-950", k.dot)} />
                <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-100"><k.icon className="h-3.5 w-3.5 text-slate-400" />{it.title}</span>
                    <span className="whitespace-nowrap font-mono text-[10px] text-slate-500">{it.ts.length === 10 ? dateIST(it.ts) : timeIST(it.ts, true)}</span>
                  </div>
                  <div className="mt-0.5 text-[11.5px] text-slate-400">{it.detail}</div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {it.severity && <span className={clsx("chip text-[10px]", it.severity === "HIGH" ? "border-rose-400/30 text-rose-200" : it.severity === "MEDIUM" ? "border-amber-400/30 text-amber-200" : "border-white/10 text-slate-400")}>{it.severity}</span>}
                    {it.status && <span className="chip border-white/10 text-[10px] text-slate-400">{it.status.toLowerCase()}</span>}
                    {it.sar && <span className="chip border-fuchsia-400/30 bg-fuchsia-500/10 text-[10px] text-fuchsia-200">SAR filed</span>}
                  </div>
                </div>
              </motion.li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}
