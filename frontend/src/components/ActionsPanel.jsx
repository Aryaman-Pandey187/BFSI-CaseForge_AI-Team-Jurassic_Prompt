import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import clsx from "clsx";
import {
  ArrowUpRight, Ban, Gavel, HandCoins, Lightbulb, Lock, MessageCircleQuestion, MessageSquare, PhoneForwarded, ShieldCheck, Snowflake, Sparkles,
} from "lucide-react";
import { Card } from "./ui";

const ROUTE_ACTIONS = {
  credit_card: ["BLOCK_CARD", "RAISE_DISPUTE", "RESET_CREDENTIALS", "OFFER_RESOLUTION", "ESCALATE"],
  debit_card: ["BLOCK_CARD", "FREEZE_ACCOUNT", "RECALL_FUNDS", "RAISE_DISPUTE", "ESCALATE"],
  loan: ["OFFER_RESOLUTION", "WAIVE_CHARGES", "PAUSE_COLLECTIONS", "ESCALATE"],
  account: ["SEND_SMS", "OFFER_RESOLUTION", "ESCALATE"],
};
const META = {
  BLOCK_CARD: { label: "Block Card", icon: Ban, tone: "from-rose-500 to-red-600" },
  RAISE_DISPUTE: { label: "Raise Dispute", icon: Gavel, tone: "from-orange-500 to-amber-500" },
  OFFER_RESOLUTION: { label: "Offer Resolution", icon: HandCoins, tone: "from-emerald-500 to-teal-500" },
  ESCALATE: { label: "Escalate", icon: ArrowUpRight, tone: "from-fuchsia-500 to-purple-600" },
  FREEZE_ACCOUNT: { label: "Freeze Account", icon: Snowflake, tone: "from-sky-500 to-blue-600" },
  RECALL_FUNDS: { label: "Recall Funds", icon: ShieldCheck, tone: "from-indigo-500 to-violet-600" },
  RESET_CREDENTIALS: { label: "Lock Digital Banking", icon: Lock, tone: "from-slate-500 to-slate-700" },
  WAIVE_CHARGES: { label: "Waive Charges", icon: Sparkles, tone: "from-cyan-500 to-sky-600" },
  PAUSE_COLLECTIONS: { label: "Pause Collections", icon: PhoneForwarded, tone: "from-violet-500 to-indigo-600" },
  SEND_SMS: { label: "Send SMS", icon: MessageSquare, tone: "from-sky-500 to-cyan-500" },
};

export default function ActionsPanel({ call }) {
  const [toast, setToast] = useState(null);
  const route = call.case?.route || call.intent?.route || "credit_card";
  const recommended = new Map((call.case?.recommended_actions || []).map((a) => [a.action, a]));
  const keys = [...new Set([...(ROUTE_ACTIONS[route] || []), ...recommended.keys()])].filter((k) => META[k]);

  const click = (k) => {
    setToast(`${META[k].label} — demo mode, no backend action taken`);
    setTimeout(() => setToast(null), 2600);
  };

  return (
    <>
      <Card title="Agent actions" icon={ShieldCheck} right={<span className="text-[10px] text-slate-500">demo · non-functional</span>}>
        <div className="grid grid-cols-2 gap-2">
          {keys.map((k, i) => {
            const m = META[k];
            const rec = recommended.get(k);
            return (
              <motion.button key={k} onClick={() => click(k)} title={rec?.rationale || m.label}
                initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * 0.04 }}
                whileHover={{ y: -2 }} whileTap={{ scale: 0.97 }}
                className={clsx("group relative flex items-center gap-2 overflow-hidden rounded-xl px-3 py-2.5 text-left text-xs font-semibold text-white shadow-lg transition",
                  "bg-gradient-to-br", m.tone, rec ? "ring-2 ring-white/30" : "opacity-80 hover:opacity-100")}>
                <m.icon className="h-4 w-4 shrink-0" />
                <span className="truncate">{m.label}</span>
                {rec && <span className="absolute right-1.5 top-1 rounded bg-black/25 px-1 text-[8px] font-bold uppercase tracking-wider">AI pick</span>}
              </motion.button>
            );
          })}
        </div>
        {recommended.size > 0 && (
          <ul className="mt-3 space-y-1.5">
            {[...recommended.values()].slice(0, 4).map((a) => (
              <li key={a.action} className="flex gap-2 text-[11px] text-slate-400">
                <Lightbulb className="mt-0.5 h-3 w-3 shrink-0 text-amber-300" />
                <span><span className="font-medium text-slate-200">{a.label}</span>{a.rationale ? ` — ${a.rationale}` : ""}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <AnimatePresence>
        {toast && (
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 20 }}
            className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-xl border border-white/10 bg-ink-900/95 px-4 py-2.5 text-sm text-slate-200 shadow-2xl backdrop-blur-xl">
            {toast}
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

export function SuggestedQuestions({ call }) {
  const qs = call.case?.suggested_questions || [];
  return (
    <Card title="Suggested questions" icon={MessageCircleQuestion}>
      {qs.length === 0 ? <p className="text-xs text-slate-500">AI-suggested probing questions appear once the case is assembled.</p> : (
        <ol className="space-y-2">
          {qs.map((q, i) => (
            <motion.li key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.07 }}
              className="flex gap-2.5 rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2 text-[12.5px] text-slate-200">
              <span className="grid h-5 w-5 shrink-0 place-items-center rounded-md bg-indigo-500/20 font-mono text-[10px] text-indigo-200">{i + 1}</span>
              {q}
            </motion.li>
          ))}
        </ol>
      )}
    </Card>
  );
}
