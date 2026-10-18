import { motion } from "framer-motion";
import { CreditCard, Landmark, LayoutGrid, PiggyBank, Wallet } from "lucide-react";
import { compactInr, dateIST, inr, titleCase } from "../lib/format";
import { Card, Empty, Skeleton, Stat } from "./ui";

export default function Customer360({ call }) {
  const c = call.customer;
  if (!c) {
    return (
      <Card title="Customer 360" icon={LayoutGrid}>
        {call.identity?.status === "failed" ? <Empty text="Caller not verified" /> : (
          <div className="space-y-2"><Skeleton className="h-14" /><Skeleton className="h-10" /><Skeleton className="h-10" /></div>
        )}
      </Card>
    );
  }
  const years = new Date().getFullYear() - Number(c.relationship_since.slice(0, 4));
  return (
    <Card title="Customer 360" icon={LayoutGrid} right={<span className="text-[11px] text-slate-500">{c.city}</span>}>
      <div className="grid grid-cols-3 gap-2">
        <Stat label="Segment" value={c.segment} />
        <Stat label="Tenure" value={`${years} yrs`} sub={`since ${c.relationship_since.slice(0, 4)}`} />
        <Stat label="Bank risk" value={<span className={c.risk_rating === "HIGH" ? "text-rose-300" : c.risk_rating === "MEDIUM" ? "text-amber-300" : "text-emerald-300"}>{c.risk_rating}</span>} />
        <Stat label="Balances" value={compactInr(c.total_balance)} />
        <Stat label="Deposits" value={compactInr(c.total_deposits)} />
        <Stat label="KYC · NPS" value={`${c.kyc_status === "VERIFIED" ? "✓" : "!"} · ${c.nps_last}/10`} />
      </div>
      <div className="mt-3 space-y-1.5">
        {c.accounts.map((a, i) => (
          <Row key={a.account_id} i={i} icon={a.type === "fixed_deposit" ? PiggyBank : Wallet}
            title={`${titleCase(a.type)} ••${a.account_id.slice(-4)}`} sub={a.maturity_date ? `matures ${dateIST(a.maturity_date)}` : a.status}
            value={inr(a.balance)} />
        ))}
        {c.cards.map((x, i) => (
          <Row key={x.card_id} i={i + 3} icon={CreditCard}
            title={`${x.network} ${x.variant} ${titleCase(x.type)} ••${x.last4}`}
            sub={x.type === "credit" ? `limit ${compactInr(x.credit_limit)} · avail ${compactInr(x.available_limit)}` : x.status}
            value={x.type === "credit" ? inr(x.outstanding) : <span className="text-emerald-300">{x.status}</span>} />
        ))}
        {c.loans.map((l, i) => (
          <Row key={l.loan_id} i={i + 6} icon={Landmark} title={`${titleCase(l.type)} ••${l.loan_id.slice(-4)}`}
            sub={`EMI ${inr(l.emi_amount)} · ${l.bucket}`}
            value={<span className={l.dpd > 0 ? "text-rose-300" : ""}>{compactInr(l.outstanding)}</span>} />
        ))}
      </div>
    </Card>
  );
}

function Row({ icon: Icon, title, sub, value, i }) {
  return (
    <motion.div initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.04 * i }}
      className="flex items-center gap-3 rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2">
      <Icon className="h-4 w-4 shrink-0 text-slate-400" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs font-medium text-slate-200">{title}</div>
        <div className="truncate text-[11px] text-slate-500">{sub}</div>
      </div>
      <div className="text-right text-xs font-semibold text-slate-100">{value}</div>
    </motion.div>
  );
}
