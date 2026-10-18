#!/usr/bin/env python3
"""
Live smoke test: connects to /ws/desktop like the agent desktop does, triggers
each simulated scenario over HTTP and asserts the expected websocket events
arrive. Run against a running server:

    python scripts/verify_ws.py --base http://localhost:8080
"""
import argparse
import asyncio
import json
import sys
from collections import Counter

import httpx
import websockets

REQUIRED = ["call.started", "transcript", "identity.update", "customer.snapshot", "intent.classified",
            "orchestrator.started", "agent.started", "agent.tool_call", "agent.tool_result", "agent.completed",
            "risk.scored", "case.assembled", "call.ended", "case.logged"]


async def run(base: str, scenarios: list[str], timeout: float) -> bool:
    ws_url = base.replace("http", "ws", 1) + "/ws/desktop"
    ok = True
    async with httpx.AsyncClient(base_url=base, timeout=10) as http:
        if not scenarios:
            scenarios = [s["id"] for s in (await http.get("/api/config")).json()["scenarios"]]
        for sc in scenarios:
            async with websockets.connect(ws_url, max_size=2**24) as ws:
                hello = json.loads(await ws.recv())
                assert hello["type"] == "hello"
                await ws.recv()  # replay
                call_id = (await http.post("/api/simulate", json={"scenario": sc})).json()["call_id"]
                counts, case = Counter(), None
                try:
                    while True:
                        evt = json.loads(await asyncio.wait_for(ws.recv(), timeout))
                        if evt.get("call_id") != call_id:
                            continue
                        counts[evt["type"]] += 1
                        if evt["type"] == "case.assembled":
                            case = evt["data"]
                        if evt["type"] == "case.logged":
                            break
                except asyncio.TimeoutError:
                    print(f"  timeout waiting for events on {sc}")
                missing = [t for t in REQUIRED if not counts[t]]
                status = "PASS" if not missing and case else "FAIL"
                ok &= status == "PASS"
                print(f"[{status}] {sc:18} call={call_id} events={sum(counts.values())} "
                      f"agents={counts['agent.completed']} tools={counts['agent.tool_result']} "
                      f"risk={case['risk']['score'] if case else '-'} {case['risk']['band'] if case else ''} "
                      f"status={case['status'] if case else '-'}" + (f" MISSING={missing}" if missing else ""))
        cases = (await http.get("/api/cases")).json()
        print(f"post-call log: {len(cases)} cases stored")
    return ok


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8080")
    p.add_argument("--timeout", type=float, default=60)
    p.add_argument("scenarios", nargs="*")
    a = p.parse_args()
    sys.exit(0 if asyncio.run(run(a.base.rstrip("/"), a.scenarios, a.timeout)) else 1)
