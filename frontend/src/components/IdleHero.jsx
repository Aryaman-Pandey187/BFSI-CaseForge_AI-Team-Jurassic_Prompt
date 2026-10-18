import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { CreditCard, Keyboard, Landmark, PhoneIncoming, Wallet, Banknote, Sparkles } from "lucide-react";
import { api } from "../hooks/useDesktopSocket";

const SCENARIO_ICON = { credit_card_fraud: CreditCard, debit_card_fraud: Banknote, loan_hardship: Landmark, account_query: Wallet };
const SCENARIO_TONE = {
  credit_card_fraud: "from-rose-500/25 to-orange-500/5 border-rose-400/20",
  debit_card_fraud: "from-orange-500/25 to-amber-500/5 border-orange-400/20",
  loan_hardship: "from-violet-500/25 to-indigo-500/5 border-violet-400/20",
  account_query: "from-emerald-500/25 to-cyan-500/5 border-emerald-400/20",
};

export default function IdleHero({ config, onTextCall }) {
  const [customers, setCustomers] = useState([]);
  useEffect(() => { api("/api/customers").then(setCustomers).catch(() => {}); }, []);

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:py-16">
      <div className="flex flex-col items-center text-center">
        <div className="relative mb-8 grid h-28 w-28 place-items-center">
          <span className="absolute inset-0 animate-ring rounded-full border border-indigo-400/40" />
          <span className="absolute inset-0 animate-ring rounded-full border border-cyan-400/30 [animation-delay:0.7s]" />
          <span className="absolute inset-0 animate-ring rounded-full border border-indigo-400/20 [animation-delay:1.4s]" />
          <div className="grid h-20 w-20 place-items-center rounded-full bg-gradient-to-br from-indigo-500 to-cyan-400 shadow-glow">
            <PhoneIncoming className="h-8 w-8 text-white" />
          </div>
        </div>
        <motion.h1 initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
          className="text-3xl font-extrabold tracking-tight text-white sm:text-5xl">
          Every call arrives <span className="text-gradient">pre-investigated.</span>
        </motion.h1>
        <p className="mt-4 max-w-2xl text-sm text-slate-400 sm:text-base">
          {config?.persona || "Maya"} answers the phone, verifies the caller, and a swarm of Gemini agents builds a cited,
          risk-scored case before you say hello. Call your Twilio number, or simulate a call below.
        </p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-2 text-xs text-slate-500">
          <span className="chip border-white/10"><Sparkles className="h-3 w-3 text-indigo-300" /> Speech-to-Text → Gemini → Text-to-Speech</span>
          <span className="chip border-white/10">Parallel tool-calling agents</span>
          <span className="chip border-white/10">Explainable risk 0–100</span>
        </div>
      </div>

      <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {config?.scenarios?.map((s, i) => {
          const Icon = SCENARIO_ICON[s.id] || CreditCard;
          return (
            <motion.button key={s.id} onClick={() => api("/api/simulate", { scenario: s.id })}
              initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 * i }}
              whileHover={{ y: -4 }} whileTap={{ scale: 0.98 }}
              className={`group glass overflow-hidden border bg-gradient-to-br p-5 text-left ${SCENARIO_TONE[s.id]}`}>
              <Icon className="h-6 w-6 text-white/90" />
              <div className="mt-4 text-sm font-semibold text-white">{s.title}</div>
              <div className="mt-1 text-xs text-slate-400">{s.customer}</div>
              <div className="mt-4 text-[11px] font-semibold uppercase tracking-wider text-indigo-200 opacity-70 transition group-hover:opacity-100">
                Simulate call →
              </div>
            </motion.button>
          );
        })}
      </div>

      <div className="mt-6 flex justify-center">
        <button onClick={onTextCall}
          className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm text-slate-200 transition hover:border-indigo-400/40 hover:bg-indigo-500/10">
          <Keyboard className="h-4 w-4 text-indigo-300" /> Start a typed call (play the caller yourself)
        </button>
      </div>

      {customers.length > 0 && (
        <div className="glass mx-auto mt-10 max-w-4xl overflow-hidden">
          <div className="border-b border-white/5 px-5 py-3 card-title">Demo cheat-sheet · say the name + last 4 of mobile (or customer ID)</div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-slate-500">
                <tr>{["Customer", "ID", "Mobile last 4", "City", "Segment", "Risk"].map((h) => <th key={h} className="px-5 py-2 font-medium">{h}</th>)}</tr>
              </thead>
              <tbody>
                {customers.map((c) => (
                  <tr key={c.customer_id} className="border-t border-white/[0.04] text-slate-300">
                    <td className="px-5 py-2 font-medium text-slate-100">{c.full_name}</td>
                    <td className="px-5 py-2 font-mono">{c.customer_id}</td>
                    <td className="px-5 py-2 font-mono">{c.mobile_last4}</td>
                    <td className="px-5 py-2">{c.city}</td>
                    <td className="px-5 py-2">{c.segment}</td>
                    <td className={`px-5 py-2 font-semibold ${c.risk_rating === "HIGH" ? "text-rose-300" : c.risk_rating === "MEDIUM" ? "text-amber-300" : "text-emerald-300"}`}>{c.risk_rating}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
