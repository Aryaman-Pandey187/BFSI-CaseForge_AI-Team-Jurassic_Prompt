import { motion } from "framer-motion";
import clsx from "clsx";
import { Globe2, ReceiptText } from "lucide-react";
import { inr, timeIST } from "../lib/format";
import { Card, Empty } from "./ui";

export default function FlaggedTransactions({ call }) {
  const txns = call.risk?.flagged_transactions || [];
  return (
    <Card title="Flagged transactions" icon={ReceiptText}
      right={txns.length > 0 && <span className="chip border-rose-400/30 bg-rose-500/10 text-rose-200">{txns.length} flagged · {inr(txns.filter((t) => t.status === "APPROVED").reduce((s, t) => s + t.amount, 0))} approved</span>}>
      {txns.length === 0 ? (
        <Empty icon={ReceiptText} text={call.risk ? "No suspicious transactions" : "Waiting for the Transaction Enricher…"} />
      ) : (
        <div className="-mx-4 overflow-x-auto sm:-mx-5">
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-slate-500">
                {["Time (IST)", "Merchant", "Amount", "Location", "Channel", "Status", "Why flagged"].map((h) => (
                  <th key={h} className="px-4 py-2 font-medium first:pl-5">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {txns.map((t, i) => {
                const severe = t.flags.length >= 2 || t.amount >= 40000;
                return (
                  <motion.tr key={t.txn_id} initial={{ opacity: 0, backgroundColor: "rgba(244,63,94,0.25)" }}
                    animate={{ opacity: 1, backgroundColor: severe ? "rgba(244,63,94,0.06)" : "rgba(0,0,0,0)" }}
                    transition={{ delay: i * 0.06, duration: 0.8 }}
                    className={clsx("border-t border-white/[0.04]", severe && "shadow-[inset_3px_0_0_0_rgba(244,63,94,0.7)]")}>
                    <td className="whitespace-nowrap px-4 py-2.5 pl-5 font-mono text-slate-400">{timeIST(t.timestamp, true)}</td>
                    <td className="px-4 py-2.5">
                      <div className="font-medium text-slate-100">{t.merchant}</div>
                      <div className="font-mono text-[10px] text-slate-500">MCC {t.mcc} · {t.mcc_description}</div>
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5">
                      <div className={clsx("font-semibold", severe ? "text-rose-200" : "text-slate-100")}>{inr(t.amount)}</div>
                      {t.original_currency && <div className="text-[10px] text-slate-500">{t.original_currency} {t.original_amount?.toLocaleString()}</div>}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-slate-300">
                      <span className="flex items-center gap-1">{t.country !== "IN" && <Globe2 className="h-3 w-3 text-rose-300" />}{t.city}, {t.country}</span>
                    </td>
                    <td className="px-4 py-2.5 text-slate-400">{t.channel}<div className="text-[10px] text-slate-500">{t.entry_mode?.replace(/_/g, " ").toLowerCase()}</div></td>
                    <td className="px-4 py-2.5">
                      <span className={clsx("chip", t.status === "APPROVED" ? "border-rose-400/30 text-rose-200" : "border-white/10 text-slate-400")}>{t.status.toLowerCase()}</span>
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex flex-wrap gap-1">
                        {t.flags.map((f) => <span key={f} className="chip border-amber-400/25 bg-amber-500/10 text-amber-200">{f}</span>)}
                      </div>
                    </td>
                  </motion.tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
