<div align="center">

<a href="https://caseforge-53w6bcjxtq-el.a.run.app/"><img src="assets/banner.png" alt="CaseForge AI: Agents Assemble the Case. Humans Close It." width="100%"></a>

# CaseForge AI
### Agents Assemble the Case. Humans Close It.

[![Live demo](https://img.shields.io/badge/%F0%9F%9A%80_Live_demo-Open_the_Agent_Desktop-2dd4bf?style=for-the-badge)](https://caseforge-53w6bcjxtq-el.a.run.app/)

![Gemini](https://img.shields.io/badge/Gemini-Vertex_AI-8E75B2?logo=googlegemini&logoColor=white) ![Cloud Run](https://img.shields.io/badge/Google_Cloud-Cloud_Run-4285F4?logo=googlecloud&logoColor=white) ![Firestore](https://img.shields.io/badge/Firestore-FFCA28?logo=firebase&logoColor=black) ![Twilio](https://img.shields.io/badge/Twilio-Voice-F22F46?logo=twilio&logoColor=white) ![Human in the loop](https://img.shields.io/badge/AI_safety-human_in_the_loop-F5A524)

</div>

> 🏦 **BFSI:** a multi-agent contact centre for banks, cards and lending, where every call can be a fraud case.

## 🔥 Problem → ✅ Solution
- 🔥 **Today:** human agents start from zero, juggling CRM, card and fraud tools. Industry estimates put **40–70% of handle time** on lookups, and fraud signals get missed.
- 🟦 **AI prepares:** while *Maya* talks, AI agents verify identity, understand the issue, investigate **in parallel** and score the risk.
- 🟧 **Human closes:** the agent gets a **cited case file**, a risk score and suggested actions before saying hello. Nothing fires without a human click.

## 🏗 Architecture

```mermaid
flowchart TD
    caller(["📞 Caller"]):::human --> twilio["☎️ Twilio voice"]:::ext --> stt["🎙️ Cloud Speech-to-Text"]:::gcp
    stt --> maya["🤖 Maya<br/>Gemini on Vertex AI"]:::ai
    maya -.->|voice reply| tts["🔊 Cloud Text-to-Speech"]:::gcp
    maya --> idn["🪪 Identity agent<br/>lookup_customer"]:::ai
    fs[("🗄️ Firestore")]:::gcp -.-> idn
    idn -->|verified| intent["🧭 Intent & Routing<br/>route_case"]:::ai
    intent --> orch{{"Specialist orchestrator<br/>💳 Credit · 🏧 Debit<br/>🏠 Loan · 👤 Account<br/><i>fans out in parallel</i>"}}:::ai
    orch --> e1["🔎 Profile"]:::ai & e2["🔎 Transactions"]:::ai & e3["🔎 Prior fraud"]:::ai & e4["🔎 ANI & auth"]:::ai
    e1 & e2 & e3 & e4 --> risk["📊 Risk engine<br/>deterministic rules<br/><i>JSON + evidence E1…En</i>"]:::ai
    risk --> asm["📋 Case Assembler<br/>cited summary"]:::ai
    asm -.-> log[("💾 Case log · Firestore")]:::gcp
    asm --> desk["🖥️ Agent Desktop<br/>live via WebSocket"]:::human --> human(["🧑‍💼 Human agent<br/>decides & acts"]):::human
    classDef ai fill:#0b3b3c,stroke:#2dd4bf,color:#e6fffb,stroke-width:2px
    classDef human fill:#3d2a05,stroke:#f5a524,color:#fff4dc,stroke-width:2px
    classDef gcp fill:#0b2540,stroke:#4285f4,color:#e8f0fe
    classDef ext fill:#1f2937,stroke:#9ca3af,color:#f3f4f6
```

<details><summary><sub>Implementation notes</sub></summary><sub>Agent-to-agent communication is in-process through structured JSON handoffs inside one FastAPI service; A2A/ADK are not used. Each agent has a clear tool contract, so it can be exposed over A2A later.</sub></details>

## ☁ Google Cloud tools
| Service | Role |
|---|---|
| **Gemini on Vertex AI** | Function calling for the identity, intent and enrichment agents; JSON for the Case Assembler |
| **Cloud Speech-to-Text** | Streams the caller's phone audio (telephony model, en-IN) |
| **Cloud Text-to-Speech** | Maya's voice, streamed back to the caller |
| **Cloud Run** | One FastAPI container: Twilio webhooks, WebSockets and the React desktop |
| **Firestore** | Customer, card, loan and transaction data, plus the post-call case log |
| **Secret Manager** | Twilio credentials |
| **Cloud Build · Artifact Registry** | `gcloud run deploy --source .` builds and stores the image |

## 🎬 How to demo
Open the **[live Agent Desktop](https://caseforge-53w6bcjxtq-el.a.run.app/)**, then pick either way:

- 📞 **Real call:** dial **+1 507 708 6987** and talk to Maya. Your call appears live on the desktop.
- 🖱️ **Simulated call:** click **Simulate call ▾** and pick a scenario.

Watch the panels fill in: identity → intent → parallel agents → risk → cited case → human handoff.

<table><tr>
<td width="50%"><img src="assets/desktop-fraud-case.png" alt="Credit card fraud case, 94 CRITICAL" width="100%"><br><sub>Credit card fraud: 94 CRITICAL → Card Fraud Desk</sub></td>
<td width="50%"><img src="assets/desktop-resolved-by-ai.png" alt="Account query resolved by AI" width="100%"><br><sub>Account query: resolved by AI</sub></td>
</tr></table>

**Example: credit card fraud.** Aarav Mehta gives his mobile's last 4 digits → verified (evidence E1) → "₹1,84,000 charge in Romania" → 4 agents run in parallel and find a SIM swap → impossible travel, an unusual amount, the SIM swap and 8 more signals → **93–94 CRITICAL** → cited case → Card Fraud Desk, P1.

| 🏧 Debit card stolen | 🏠 Loan hardship | 🧾 Balance query |
|---|---|---|
| 94 CRITICAL | 92 CRITICAL | 6 LOW · resolved by AI |

## 🎯 Risk indicators
`GEO_VELOCITY` +25 · `UNUSUAL_AMOUNT` +20 · `ATM_VELOCITY` +20 · `SIM_SWAP_RECENT` +15 · `NEW_COUNTRY` +10 · `CARD_TESTING` +10 → `score = 100·(1−e^(−raw/45))`, computed in code, not by the LLM.<br>
**Bands:** 🟢 LOW < 30 ≤ 🟡 MEDIUM < 60 ≤ 🟠 HIGH < 80 ≤ 🔴 CRITICAL

## 📈 Scalability
- ⟷ **Horizontal:** each new product (wealth, insurance…) gets its own specialist orchestrator.
- ↕ **Vertical:** each new enrichment agent joins the parallel fan-out and deepens the case.

## 🛡 AI safety
📎 **Full Citations** · 🔐 **Least-Privilege** · 🗂️ **Complete Logging** · ✋ **No Autonomous Actions** · 🧑‍⚖️ **Human-in-the-Loop**

## 📞 Environment & call flow
| Variable | Purpose |
|---|---|
| `LLM_MODE` · `GEMINI_MODEL` · `GOOGLE_CLOUD_PROJECT` | `vertex` / `mock` · the Gemini model · the GCP project |
| `DATA_BACKEND` · `VOICE_MODE` | `firestore` / `memory` · `media_stream` / `gather` |
| `TWILIO_ACCOUNT_SID` · `TWILIO_AUTH_TOKEN` · `PUBLIC_BASE_URL` | Twilio credentials · the public URL for the webhooks |
| `DEMO_TRUSTED_CALLER_NUMBERS` · `HANDOFF_NUMBER` | Caller numbers treated as registered · an E.164 number for the human agent |

A caller dials the Twilio number → Twilio posts to `/twilio/voice` on Cloud Run → Maya handles the call. At handoff, if `HANDOFF_NUMBER` is set, Twilio `<Dial>`s that real human agent while the desktop shows the full case; if it's empty, the AI keeps the line.

## 💻 Local setup
```bash
# Option A: Docker
cp .env.example .env
docker compose up --build
# open http://localhost:8080 → "Simulate call" → pick a scenario

# Option B: no Docker (Python 3.11+ and Node 18+)
./scripts/run_local.sh            # builds the UI and serves everything on :8080
./scripts/run_local.sh --dev      # backend :8080 + hot-reload UI on :5173
```

---
<p align="center"><b>For any further details, reach out to</b><br>
Team Name: <b>Jurassic Prompt</b><br>
<a href="mailto:priyadarshi.prakirn@gmail.com">Prakirn Priyadarshi</a> · <a href="mailto:pandeyaryaman187@gmail.com">Aryaman Pandey</a></p>
