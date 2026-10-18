import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import clsx from "clsx";
import { Bot, MessageSquareText, Send, User } from "lucide-react";
import { timeIST } from "../lib/format";
import { api } from "../hooks/useDesktopSocket";
import { Card, Waveform } from "./ui";

export default function Transcript({ call }) {
  const scroller = useRef(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const lines = call.transcript;

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [lines.length, call.interim?.text]);

  const send = async (e) => {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    const t = text;
    setText("");
    try { await api(`/api/text-call/${call.id}/say`, { text: t }); } finally { setBusy(false); }
  };

  return (
    <Card title="Live transcript" icon={MessageSquareText}
      right={<span className="flex items-center gap-2 text-[11px] text-slate-500">
        {!call.ended && <Waveform active={call.voice === "speaking" || !!call.interim} color={call.interim ? "bg-indigo-300" : "bg-cyan-300"} bars={5} />}
        {lines.length} turns
      </span>}>
      <div ref={scroller} className="h-[360px] space-y-3 overflow-y-auto pr-1 sm:h-[420px]">
        <AnimatePresence initial={false}>
          {lines.map((l) => <Bubble key={l.id} line={l} />)}
          {call.interim && !call.ended && (
            <motion.div key="interim" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <Bubble line={{ ...call.interim, ts: null }} interim />
            </motion.div>
          )}
          {call.voice === "thinking" && !call.ended && (
            <motion.div key="thinking" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="flex items-center gap-2 pl-10 text-xs text-slate-500">
              <span className="flex gap-1">{[0, 1, 2].map((i) => <span key={i} className="h-1.5 w-1.5 animate-bounce rounded-full bg-indigo-300" style={{ animationDelay: `${i * 0.15}s` }} />)}</span>
              AI is thinking…
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      {call.channel === "text" && !call.ended && (
        <form onSubmit={send} className="mt-3 flex gap-2">
          <input value={text} onChange={(e) => setText(e.target.value)} disabled={busy} autoFocus
            placeholder="Type as the caller, e.g. “Hi, I'm Aarav Mehta”"
            className="flex-1 rounded-xl border border-white/10 bg-ink-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-indigo-400/50 focus:outline-none" />
          <button disabled={busy} className="flex items-center gap-1.5 rounded-xl bg-indigo-500 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-400 disabled:opacity-50">
            <Send className="h-4 w-4" />
          </button>
        </form>
      )}
    </Card>
  );
}

function Bubble({ line, interim }) {
  const ai = line.role === "ai";
  return (
    <motion.div layout initial={{ opacity: 0, y: 8, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.3 }} className={clsx("flex gap-2.5", !ai && "flex-row-reverse")}>
      <div className={clsx("mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg",
        ai ? "bg-gradient-to-br from-indigo-500/80 to-cyan-500/80" : "bg-white/10")}>
        {ai ? <Bot className="h-3.5 w-3.5 text-white" /> : <User className="h-3.5 w-3.5 text-slate-300" />}
      </div>
      <div className={clsx("max-w-[82%] rounded-2xl px-3.5 py-2.5 text-[13px] leading-relaxed",
        ai ? "rounded-tl-sm border border-indigo-400/15 bg-indigo-500/[0.08] text-slate-100"
          : "rounded-tr-sm border border-white/[0.07] bg-white/[0.05] text-slate-200",
        interim && "border-dashed italic text-slate-400")}>
        {line.text}
        <div className={clsx("mt-1 text-[10px] text-slate-500", !ai && "text-right")}>
          {ai ? "Maya · AI" : "Caller"}{line.ts ? ` · ${timeIST(line.ts)}` : interim ? " · speaking…" : ""}
        </div>
      </div>
    </motion.div>
  );
}
