import { useMemo } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { PhoneOff } from "lucide-react";
import { api, useDesktopSocket } from "./hooks/useDesktopSocket";
import TopBar from "./components/TopBar";
import IdleHero from "./components/IdleHero";
import IdentityCard from "./components/IdentityCard";
import Customer360 from "./components/Customer360";
import Transcript from "./components/Transcript";
import RiskPanel from "./components/RiskPanel";
import AgentActivity from "./components/AgentActivity";
import CaseSummary from "./components/CaseSummary";
import ActionsPanel, { SuggestedQuestions } from "./components/ActionsPanel";
import FlaggedTransactions from "./components/FlaggedTransactions";
import FraudTimeline from "./components/FraudTimeline";
import RoutePanel from "./components/RoutePanels";
import { CaseLog, EvidencePanel } from "./components/CaseLog";

export default function App() {
  const [state, dispatch] = useDesktopSocket();
  const callId = state.selected || state.order[0];
  const call = callId && !state.home ? state.calls[callId] : null;
  const loggedKey = useMemo(() => Object.values(state.calls).filter((c) => c.logged).length, [state.calls]);
  const showTxns = call && (call.case?.route === "credit_card" || call.case?.route === "debit_card" || (!call.case && call.intent?.route?.includes("card")));

  const startTextCall = async () => { await api("/api/text-call", {}); };

  return (
    <div className="min-h-screen">
      <TopBar state={state} call={call} onSelect={(id) => dispatch({ type: "select", id })} onHome={() => dispatch({ type: "home" })} />
      <AnimatePresence mode="wait">
        {!call ? (
          <motion.main key="idle" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <IdleHero config={state.config} onTextCall={startTextCall} />
          </motion.main>
        ) : (
          <motion.main key={call.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="mx-auto max-w-[1680px] space-y-4 px-4 py-4 sm:px-6 sm:py-6">
            {call.ended && (
              <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}
                className="flex flex-wrap items-center gap-3 rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-2.5 text-xs text-slate-300">
                <PhoneOff className="h-4 w-4 text-slate-400" />
                Call ended · {call.ended.disposition?.replace(/_/g, " ").toLowerCase()} · {call.ended.duration_s}s
                {call.logged && <span className="text-emerald-300">· case {call.logged.case_id} logged to {call.logged.store}</span>}
                <button onClick={() => dispatch({ type: "home" })} className="ml-auto rounded-lg border border-white/10 px-2.5 py-1 hover:bg-white/5">Back to home</button>
                <button onClick={startTextCall} className="rounded-lg border border-white/10 px-2.5 py-1 hover:bg-white/5">New typed call</button>
              </motion.div>
            )}
            <AgentActivity call={call} />
            <div className="grid gap-4 lg:grid-cols-12">
              <div className="space-y-4 lg:col-span-3">
                <IdentityCard call={call} />
                <Customer360 call={call} />
              </div>
              <div className="space-y-4 lg:col-span-6">
                <CaseSummary call={call} />
                <Transcript call={call} />
              </div>
              <div className="space-y-4 lg:col-span-3">
                <RiskPanel call={call} />
                <ActionsPanel call={call} />
                <SuggestedQuestions call={call} />
              </div>
            </div>
            <RoutePanel call={call} />
            <div className="grid gap-4 lg:grid-cols-12">
              <div className="space-y-4 lg:col-span-8">
                {showTxns && <FlaggedTransactions call={call} />}
                <EvidencePanel call={call} />
              </div>
              <div className="space-y-4 lg:col-span-4">
                <FraudTimeline call={call} />
                <CaseLog refreshKey={loggedKey} />
              </div>
            </div>
            <footer className="pb-6 pt-2 text-center text-[11px] text-slate-600">
              CaseForge AI · Gemini on Vertex AI · Cloud Speech-to-Text · Cloud Text-to-Speech · Firestore · Cloud Run · Twilio
            </footer>
          </motion.main>
        )}
      </AnimatePresence>
    </div>
  );
}
