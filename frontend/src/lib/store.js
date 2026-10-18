// Event-sourced call state. The backend streams small events over a websocket;
// this reducer folds them into one object per call that the UI renders.

export const initialState = {
  connected: false,
  config: null,
  calls: {}, // call_id -> call state
  order: [], // call ids, newest first
  selected: null, // pinned call id (null = follow newest)
  home: false, // true = show the landing page until a new call starts
};

function newCall(evt) {
  return {
    id: evt.call_id,
    channel: evt.data.channel,
    scenario: evt.data.scenario,
    callerNumber: evt.data.caller_number,
    startedAt: evt.data.started_at || evt.ts,
    llmMode: evt.data.llm_mode,
    voiceMode: evt.data.voice_mode,
    stage: "GREETING",
    stageLabel: "Greeting",
    voice: "listening",
    transcript: [],
    interim: null,
    identity: { status: "pending", attempts: 0 },
    customer: null,
    intent: null,
    orchestrator: null,
    agents: {},
    agentOrder: [],
    risk: null,
    case: null,
    handoff: null,
    ended: null,
    logged: null,
    errors: [],
  };
}

function upsertAgent(call, id, patch) {
  const agents = { ...call.agents, [id]: { ...(call.agents[id] || { id, tools: [] }), ...patch } };
  const agentOrder = call.agentOrder.includes(id) ? call.agentOrder : [...call.agentOrder, id];
  return { ...call, agents, agentOrder };
}

export function applyEvent(call, evt) {
  const d = evt.data || {};
  switch (evt.type) {
    case "call.stage":
      return { ...call, stage: d.stage, stageLabel: d.label };
    case "voice.state":
      return { ...call, voice: d.state };
    case "transcript":
      if (d.interim) return { ...call, interim: d };
      if (call.transcript.some((l) => l.id === d.id)) return call;
      return { ...call, transcript: [...call.transcript, d], interim: d.role === "caller" ? null : call.interim };
    case "identity.update":
      return { ...call, identity: d };
    case "customer.snapshot":
      return { ...call, customer: d };
    case "intent.classified":
      return { ...call, intent: d };
    case "orchestrator.started": {
      let next = { ...call, orchestrator: d };
      for (const a of d.agents) next = upsertAgent(next, a.agent_id, { title: a.title, icon: a.icon, toolNames: a.tools, status: "queued", group: d.route });
      return next;
    }
    case "agent.started":
      return upsertAgent(call, d.agent_id, { title: d.title, icon: d.icon, toolNames: d.tools, group: d.group, status: "running", startedAt: evt.ts, parallel: d.parallel });
    case "agent.tool_call": {
      const a = call.agents[d.agent_id] || { tools: [] };
      return upsertAgent(call, d.agent_id, { tools: [...(a.tools || []), { tool: d.tool, args: d.args, status: "running" }] });
    }
    case "agent.tool_result": {
      const a = call.agents[d.agent_id] || { tools: [] };
      const tools = [...(a.tools || [])];
      const i = tools.map((t) => t.tool).lastIndexOf(d.tool);
      const done = { tool: d.tool, status: d.error ? "error" : "done", evidence: d.evidence_id, summary: d.summary || d.error, ms: d.ms, source: d.source };
      if (i >= 0) tools[i] = { ...tools[i], ...done };
      else tools.push(done);
      return upsertAgent(call, d.agent_id, { tools });
    }
    case "agent.completed":
      return upsertAgent(call, d.agent_id, { status: d.status === "error" ? "error" : "done", headline: d.headline, findings: d.findings, durationMs: d.duration_ms, engine: d.engine, title: d.title || call.agents[d.agent_id]?.title, group: d.group || call.agents[d.agent_id]?.group });
    case "risk.scored":
      return { ...call, risk: d };
    case "case.assembled":
      return { ...call, case: d };
    case "handoff":
      return { ...call, handoff: d };
    case "call.ended":
      return { ...call, ended: { ...d, at: evt.ts }, voice: "idle", interim: null };
    case "case.logged":
      return { ...call, logged: d };
    case "error":
      return { ...call, errors: [...call.errors, d] };
    default:
      return call;
  }
}

export function reducer(state, action) {
  switch (action.type) {
    case "ws.open":
      return { ...state, connected: true };
    case "ws.close":
      return { ...state, connected: false };
    case "hello":
      return { ...state, config: action.data };
    case "select":
      return { ...state, selected: action.id, home: false };
    case "home":
      // Back to the landing page; a new incoming or simulated call brings the desktop back.
      return { ...state, selected: null, home: true };
    case "events": {
      let { calls, order, home } = state;
      calls = { ...calls };
      for (const evt of action.events) {
        if (!evt.call_id) continue;
        if (evt.type === "call.started" || !calls[evt.call_id]) {
          if (!calls[evt.call_id]) {
            home = false;
            calls[evt.call_id] = newCall(evt.type === "call.started" ? evt : { ...evt, data: {} });
            order = [evt.call_id, ...order.filter((x) => x !== evt.call_id)].slice(0, 8);
          }
          if (evt.type === "call.started") continue;
        }
        calls[evt.call_id] = applyEvent(calls[evt.call_id], evt);
      }
      return { ...state, calls, order, home };
    }
    case "replay": {
      const next = reducer(state, { type: "events", events: action.events });
      const anyLive = next.order.some((id) => next.calls[id] && !next.calls[id].ended);
      // Only the first replay (page load) decides; a later reconnect keeps whatever the agent is viewing.
      if (state.replayed) return next;
      return { ...next, home: !anyLive, replayed: true };
    }
    default:
      return state;
  }
}
