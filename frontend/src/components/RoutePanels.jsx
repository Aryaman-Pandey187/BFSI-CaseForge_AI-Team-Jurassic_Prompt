import { motion } from "framer-motion";
import clsx from "clsx";
import { Banknote, CheckCircle2, CreditCard, HeartPulse, Landmark, MessageSquareReply, Wallet } from "lucide-react";
import { compactInr, dateIST, inr, timeIST, titleCase } from "../lib/format";
import { Card, Cite, Stat } from "./ui";

/** Route-specific panel: appears once the orchestrator has finished, based on the route. */
export default function RoutePanel({ call }) {
  const p = call.case?.route_panel;
  if (!p) return null;
  if (p.type === "loan") return <LoanPanel p={p} />;
  if (p.type === "account") return <AccountPanel p={p} citations={call.case.citations} />;
  if (p.type === "debit_card") return <DebitPanel p={p} />;
  return <CreditPanel p={p} />;
}

const EMI_COLOR = { PAID: "bg-emerald-400", PAID_LATE: "bg-amber-400", BOUNCED: "bg-rose-500", OVERDUE: "bg-rose-400 animate-pulse", UPCOMING: "bg-white/15" };

function LoanPanel({ p }) {
  return (
    <Card title="Loan & hardship workspace" icon={Landmark} accent="from-transparent via-violet-400/60 to-transparent">
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-3 lg:col-span-2">
          {p.loans.map((ln) => {
            const rep = p.repayment.find((r) => r.loan_id === ln.loan_id);
            const row = [...ln.last_12, ...ln.next_3];
            return (
              <div key={ln.loan_id} className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-sm font-semibold text-white">{titleCase(ln.type)} <span className="font-mono text-xs text-slate-500">{ln.loan_id}</span></div>
                  <span className={clsx("chip", ln.dpd > 60 ? "border-rose-400/30 bg-rose-500/10 text-rose-200" : ln.dpd > 0 ? "border-amber-400/30 text-amber-200" : "border-emerald-400/30 text-emerald-200")}>{ln.bucket} · DPD {ln.dpd}</span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Stat label="EMI" value={inr(ln.emi_amount)} />
                  <Stat label="Outstanding" value={compactInr(ln.outstanding)} />
                  <Stat label="Rate" value={`${ln.interest_rate}%`} />
                  <Stat label="Remaining" value={`${ln.remaining_installments} EMIs`} />
                </div>
                <div className="mt-3 text-[10px] uppercase tracking-wider text-slate-500">EMI schedule · last 12 + next 3</div>
                <div className="mt-1.5 flex items-end gap-1">
                  {row.map((r, i) => (
                    <motion.div key={r.installment} title={`#${r.installment} · ${r.due_date} · ${r.status}${r.dpd ? ` · DPD ${r.dpd}` : ""}`}
                      initial={{ scaleY: 0 }} animate={{ scaleY: 1 }} transition={{ delay: i * 0.03 }}
                      className={clsx("h-8 flex-1 origin-bottom rounded-md", EMI_COLOR[r.status] || "bg-white/10")} />
                  ))}
                </div>
                <div className="mt-1.5 flex flex-wrap gap-3 text-[10px] text-slate-500">
                  {Object.entries({ PAID: "paid", PAID_LATE: "late", BOUNCED: "bounced", OVERDUE: "overdue", UPCOMING: "upcoming" }).map(([k, v]) => (
                    <span key={k} className="flex items-center gap-1"><span className={clsx("h-2 w-2 rounded-sm", EMI_COLOR[k].replace(" animate-pulse", ""))} />{v}</span>
                  ))}
                  {rep && <span className="ml-auto text-slate-400">{rep.on_time} on-time · {rep.bounced} bounced · {inr(rep.overdue_amount)} overdue</span>}
                </div>
              </div>
            );
          })}
        </div>
        <div className="space-y-3">
          <div className="rounded-xl border border-rose-400/15 bg-rose-500/[0.04] p-3">
            <div className="card-title text-rose-200/80"><HeartPulse className="h-3.5 w-3.5" /> Hardship signals</div>
            <ul className="mt-2 space-y-1.5">
              {p.hardship.signals.map((s) => (
                <li key={s.code} className="text-[11.5px] text-slate-300"><span className="font-mono text-[10px] text-rose-300">{s.code}</span><br />{s.detail}</li>
              ))}
            </ul>
          </div>
          <div className="rounded-xl border border-emerald-400/15 bg-emerald-500/[0.04] p-3">
            <div className="card-title text-emerald-200/80">Relief options (pre-computed)</div>
            {p.relief_options.map((o) => (
              <div key={o.loan_id} className="mt-2">
                <div className="text-[11px] font-semibold text-slate-200">{titleCase(o.type)} · current EMI {inr(o.current_emi)}</div>
                {o.options.map((x) => (
                  <div key={x.name} className="mt-1 rounded-lg bg-white/[0.03] px-2 py-1.5 text-[11px] text-slate-400">
                    <span className="font-medium text-emerald-200">{x.name}</span> — {x.detail}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}

function AccountPanel({ p, citations }) {
  const resolved = p.resolution === "RESOLVED_BY_AI";
  return (
    <Card title="Account services" icon={Wallet} accent="from-transparent via-emerald-400/60 to-transparent"
      right={<span className={clsx("chip", resolved ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-200" : "border-amber-400/30 text-amber-200")}>
        {resolved ? <><CheckCircle2 className="h-3 w-3" /> AI resolved</> : "Needs agent"}</span>}>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          <div className="card-title"><MessageSquareReply className="h-3.5 w-3.5" /> Answers given by AI</div>
          {p.answers.map((a) => (
            <motion.div key={a.query} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
              className="rounded-xl border border-emerald-400/15 bg-emerald-500/[0.05] px-3 py-2.5">
              <div className="flex items-center justify-between text-[10px] uppercase tracking-wider text-emerald-300/80">
                {titleCase(a.query)} <span className="flex gap-1">{a.evidence.map((e) => <Cite key={e} id={e} citations={citations} />)}</span>
              </div>
              <div className="mt-1 text-[13px] text-slate-100">{a.answer}</div>
            </motion.div>
          ))}
        </div>
        <div className="space-y-2">
          <div className="card-title">Accounts & service requests</div>
          {p.accounts.map((a) => (
            <div key={a.account_id} className="flex items-center justify-between rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2 text-xs">
              <span className="text-slate-300">{titleCase(a.type)} <span className="font-mono text-slate-500">{a.account_id}</span></span>
              <span className="font-semibold text-slate-100">{inr(a.balance, { decimals: 2 })}</span>
            </div>
          ))}
          {p.service_requests.map((s) => (
            <div key={s.sr_id} className="rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2 text-xs">
              <div className="flex justify-between"><span className="font-medium text-slate-200">{titleCase(s.type)}</span><span className="chip border-white/10 text-[10px] text-slate-400">{s.status.toLowerCase()}</span></div>
              <div className="mt-0.5 text-[11px] text-slate-500">{s.sr_id} · {dateIST(s.created)} · {s.detail}</div>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

function DebitPanel({ p }) {
  const { atm, linked_account: la } = p;
  const max = Math.max(...atm.withdrawals.map((w) => w.amount), 1);
  return (
    <Card title="Debit card · ATM & linked account" icon={Banknote} accent="from-transparent via-orange-400/60 to-transparent">
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat label="ATM attempts (24h)" value={atm.withdrawals.length} />
            <Stat label="Cash withdrawn" value={inr(atm.total_withdrawn)} />
            <Stat label="Distinct ATMs" value={atm.distinct_atms} />
            <Stat label="Peak / hour" value={<span className="text-rose-300">{atm.max_in_1h}</span>} sub={`baseline ${atm.baseline_atm_per_month}/month`} />
          </div>
          <div className="mt-3 space-y-1.5">
            {atm.withdrawals.map((w, i) => (
              <div key={w.txn_id} className="flex items-center gap-3 text-xs">
                <span className="w-16 shrink-0 font-mono text-slate-500">{timeIST(w.timestamp).slice(0, 5)}</span>
                <div className="relative h-6 flex-1 overflow-hidden rounded-md bg-white/[0.03]">
                  <motion.div initial={{ width: 0 }} animate={{ width: `${(w.amount / max) * 100}%` }} transition={{ delay: i * 0.08, duration: 0.6 }}
                    className={clsx("h-full rounded-md", w.status === "APPROVED" ? "bg-gradient-to-r from-orange-500/70 to-rose-500/70" : "bg-white/10")} />
                  <span className="absolute inset-0 flex items-center px-2 text-[11px] text-white/90">{w.merchant} · {w.city}</span>
                </div>
                <span className={clsx("w-20 shrink-0 text-right font-semibold", w.status === "APPROVED" ? "text-slate-100" : "text-slate-500 line-through")}>{inr(w.amount)}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-xl border border-rose-400/15 bg-rose-500/[0.04] p-3">
          <div className="card-title text-rose-200/80">Linked account {la.account_id}</div>
          <div className="mt-3 flex items-end justify-between">
            <div><div className="text-[10px] text-slate-500">Before</div><div className="text-lg font-semibold text-slate-200">{compactInr(la.balance_before)}</div></div>
            <div className="text-right"><div className="text-[10px] text-slate-500">Now</div><div className="text-lg font-semibold text-rose-300">{compactInr(la.current_balance)}</div></div>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/5">
            <motion.div initial={{ width: 0 }} animate={{ width: `${la.outflow_pct_of_balance}%` }} transition={{ duration: 1 }} className="h-full bg-gradient-to-r from-orange-400 to-rose-500" />
          </div>
          <div className="mt-1 text-[11px] text-rose-200">{la.outflow_pct_of_balance}% drained in 48h</div>
          <div className="mt-3 space-y-1.5">
            {la.transfers.map((t) => (
              <div key={t.txn_id} className="rounded-lg bg-white/[0.03] px-2 py-1.5 text-[11px]">
                <div className="flex justify-between text-slate-200"><span>{t.channel}</span><span className="font-semibold">{inr(t.amount)}</span></div>
                <div className="truncate text-slate-500">{t.merchant}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}

function CreditPanel({ p }) {
  const c = p.card || {};
  const used = c.credit_limit ? (c.outstanding / c.credit_limit) * 100 : 0;
  return (
    <Card title="Credit card" icon={CreditCard} accent="from-transparent via-rose-400/60 to-transparent">
      <div className="grid gap-3 sm:grid-cols-4">
        <div className="relative col-span-2 overflow-hidden rounded-2xl bg-gradient-to-br from-indigo-600 via-violet-600 to-fuchsia-600 p-4 text-white shadow-glow">
          <div className="absolute -right-8 -top-8 h-32 w-32 rounded-full bg-white/10" />
          <div className="text-xs opacity-80">{c.network} {c.variant}</div>
          <div className="mt-6 font-mono text-lg tracking-[0.2em]">•••• •••• •••• {c.last4}</div>
          <div className="mt-2 flex justify-between text-[11px] opacity-80"><span>{c.status}</span><span>{c.international_enabled ? "International ON" : "Domestic only"}</span></div>
        </div>
        <Stat label="Credit limit" value={inr(c.credit_limit)} />
        <Stat label="Outstanding" value={inr(c.outstanding)} sub={`${used.toFixed(0)}% utilised · avail ${compactInr(c.available_limit)}`} />
      </div>
    </Card>
  );
}
