import { useEffect, useState } from "react";
import clsx from "clsx";
import { Archive, Database, Quote } from "lucide-react";
import { BAND, timeIST } from "../lib/format";
import { api } from "../hooks/useDesktopSocket";
import { Card } from "./ui";

export function CaseLog({ refreshKey }) {
  const [rows, setRows] = useState([]);
  useEffect(() => { api("/api/cases").then(setRows).catch(() => {}); }, [refreshKey]);
  return (
    <Card title="Post-call case log" icon={Archive} right={<span className="text-[10px] text-slate-500">persisted after every call</span>}>
      {rows.length === 0 ? <p className="text-xs text-slate-500">Cases are written to the data store when a call ends.</p> : (
        <div className="space-y-1.5">
          {rows.slice(0, 8).map((r) => (
            <div key={r.case_id} className="flex items-center gap-3 rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2 text-xs">
              <span className={clsx("w-9 shrink-0 text-center font-mono font-bold", r.band ? BAND[r.band].text : "text-slate-500")}>{r.score ?? "—"}</span>
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium text-slate-200">{r.headline || "No case (caller not verified)"}</div>
                <div className="truncate text-[10px] text-slate-500">{r.case_id} · {r.customer?.full_name || "unknown"} · {r.post_call?.disposition?.replace(/_/g, " ").toLowerCase()} · {r.post_call?.duration_s}s</div>
              </div>
              <span className="hidden font-mono text-[10px] text-slate-500 sm:block">{timeIST(r.post_call?.ended_at || r.created_at)}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export function EvidencePanel({ call }) {
  const cites = call.case?.citations || [];
  return (
    <Card title="Evidence & citations" icon={Quote} right={<span className="text-[10px] text-slate-500">{cites.length} tool outputs</span>}>
      {cites.length === 0 ? <p className="text-xs text-slate-500">Every statement in the case cites a tool output (E1, E2…). They are listed here.</p> : (
        <div className="max-h-[300px] space-y-1.5 overflow-y-auto pr-1">
          {cites.map((c) => (
            <div key={c.id} className="flex gap-2.5 rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2 text-[11px]">
              <span className="cite h-fit">{c.id}</span>
              <div className="min-w-0">
                <div className="font-mono text-slate-200">{c.tool}<span className="text-slate-500"> · {c.agent}</span></div>
                <div className="text-slate-400">{c.summary}</div>
                <div className="flex items-center gap-1 truncate font-mono text-[10px] text-slate-600"><Database className="h-2.5 w-2.5" />{c.source}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
