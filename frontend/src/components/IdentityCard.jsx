import { motion } from "framer-motion";
import clsx from "clsx";
import { BadgeCheck, Loader2, Phone, ShieldQuestion, ShieldX, Smartphone } from "lucide-react";
import { initials, titleCase } from "../lib/format";
import { Card } from "./ui";

export default function IdentityCard({ call }) {
  const id = call.identity || {};
  const c = call.customer;
  const verified = id.status === "verified";
  const failed = id.status === "failed";
  const ani = call.agents?.identity_channel?.tools?.find((t) => t.tool === "check_ani_match");
  const status = verified
    ? { icon: BadgeCheck, text: "Identity verified", cls: "text-emerald-300 border-emerald-400/30 bg-emerald-500/10" }
    : failed
      ? { icon: ShieldX, text: "Not verified", cls: "text-rose-300 border-rose-400/30 bg-rose-500/10" }
      : { icon: id.attempts ? ShieldQuestion : Loader2, text: id.attempts ? `Retrying (${id.attempts}/3)` : "Verifying…", cls: "text-amber-200 border-amber-400/30 bg-amber-500/10", spin: !id.attempts };

  return (
    <Card title="Caller" icon={Phone} accent="from-transparent via-indigo-400/60 to-transparent">
      <div className="flex items-center gap-4">
        <div className="relative">
          <motion.div layout className={clsx("grid h-14 w-14 place-items-center rounded-2xl text-lg font-bold",
            verified ? "bg-gradient-to-br from-indigo-500 to-cyan-400 text-white" : "bg-white/5 text-slate-400")}>
            {c ? initials(c.full_name) : <Smartphone className="h-6 w-6" />}
          </motion.div>
          {verified && (
            <motion.span initial={{ scale: 0 }} animate={{ scale: 1 }} className="absolute -bottom-1 -right-1 rounded-full bg-ink-950 p-0.5">
              <BadgeCheck className="h-5 w-5 text-emerald-400" />
            </motion.span>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-lg font-semibold text-white">{c?.full_name || "Unknown caller"}</div>
          <div className="font-mono text-xs text-slate-400">{call.callerNumber || "No caller ID"}</div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <span className={clsx("chip", status.cls)}>
              <status.icon className={clsx("h-3 w-3", status.spin && "animate-spin")} /> {status.text}
            </span>
            {c && <span className="chip border-white/10 text-slate-300">{c.customer_id}</span>}
            {c?.vulnerable_customer && <span className="chip border-fuchsia-400/30 bg-fuchsia-500/10 text-fuchsia-200">Vulnerable</span>}
          </div>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
        <Field label="Method" value={id.method ? titleCase(id.method) : "—"} />
        <Field label="Match confidence" value={id.confidence != null ? `${Math.round(id.confidence * 100)}%` : "—"} />
        <Field label="Channel" value={titleCase(call.channel || "")} />
        <Field label="ANI check" plain value={ani?.summary ? ani.summary.replace("ANI check: ", "").replace("sim swapped", "SIM swapped").replace(/^./, (c) => c.toUpperCase()) : "—"}
          tone={ani?.summary?.includes("swapped") || ani?.summary?.includes("mismatch") ? "text-rose-300" : ani ? "text-emerald-300" : ""} />
      </div>
    </Card>
  );
}

function Field({ label, value, tone, plain }) {
  return (
    <div className="rounded-lg border border-white/[0.05] bg-white/[0.02] px-2.5 py-2">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={clsx("mt-0.5 truncate font-medium text-slate-200", !plain && "capitalize", tone)}>{value}</div>
    </div>
  );
}
