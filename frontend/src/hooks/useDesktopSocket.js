import { useEffect, useReducer, useRef } from "react";
import { initialState, reducer } from "../lib/store";

// Resolve the backend websocket URL (same origin in prod, Vite proxy in dev,
// or an explicit VITE_BACKEND_URL).
function wsUrl() {
  const explicit = import.meta.env.VITE_BACKEND_URL;
  if (explicit) return explicit.replace(/^http/, "ws") + "/ws/desktop";
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws/desktop`;
}

export const apiBase = import.meta.env.VITE_BACKEND_URL || "";

export function useDesktopSocket() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const buf = useRef([]);
  const flushTimer = useRef(null);

  useEffect(() => {
    let ws;
    let retry = 0;
    let stop = false;
    let pingTimer;

    const flush = () => {
      flushTimer.current = null;
      if (buf.current.length) {
        dispatch({ type: "events", events: buf.current });
        buf.current = [];
      }
    };

    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onopen = () => {
        retry = 0;
        dispatch({ type: "ws.open" });
        pingTimer = setInterval(() => ws.readyState === 1 && ws.send("ping"), 20000);
      };
      ws.onmessage = (m) => {
        const msg = JSON.parse(m.data);
        if (msg.type === "hello") return dispatch({ type: "hello", data: msg.data });
        if (msg.type === "replay") return dispatch({ type: "events", events: msg.data });
        // batch bursts of events into one render per animation frame
        buf.current.push(msg);
        if (!flushTimer.current) flushTimer.current = requestAnimationFrame(flush);
      };
      ws.onclose = () => {
        clearInterval(pingTimer);
        dispatch({ type: "ws.close" });
        if (!stop) setTimeout(connect, Math.min(8000, 500 * 2 ** retry++));
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => {
      stop = true;
      clearInterval(pingTimer);
      ws && ws.close();
    };
  }, []);

  return [state, dispatch];
}

export async function api(path, body) {
  const res = await fetch(apiBase + path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}
