"""
Data access layer.

Two interchangeable back-ends implement :class:`DataStore`:

* :class:`MemoryDataStore`   - loads ``app/data/seed_data.json`` into memory.
  Zero dependencies; used for local demos and tests.
* :class:`FirestoreDataStore` - Google Cloud Firestore (Native mode). Seeds
  itself from the same JSON on first run (guarded by a ``_meta/seed`` doc).

All seed timestamps are anchored to a fixed "demo day". When
``TIME_SHIFT_DATA=true`` every date is shifted so the anchor becomes *today*,
which keeps "last 90 days" windows and "SIM swap 2 days ago" stories true no
matter when you run the demo.
"""
from __future__ import annotations

import abc
import asyncio
import copy
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings

log = logging.getLogger("caseforge.datastore")

SEED_FILE = Path(__file__).resolve().parent.parent / "data" / "seed_data.json"
COLLECTIONS = ["customers", "cards", "accounts", "loans", "transactions", "fraud_flags",
               "auth_events", "service_requests"]
ID_FIELDS = {"customers": "customer_id", "cards": "card_id", "accounts": "account_id", "loans": "loan_id",
             "transactions": "txn_id", "fraud_flags": "flag_id", "auth_events": "event_id",
             "service_requests": "sr_id"}
# Keys whose values are event dates that should move with the demo clock.
SHIFT_KEYS = {"timestamp", "date", "due_date", "paid_date", "created", "eta", "maturity_date", "anchor",
              "last_statement"}


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _shift_value(v: str, delta: timedelta) -> str:
    try:
        if "T" in v:
            return (parse_ts(v) + delta).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return (date.fromisoformat(v) + delta).isoformat()
    except (ValueError, TypeError):
        return v


def _shift(obj: Any, delta: timedelta) -> Any:
    if isinstance(obj, dict):
        return {k: (_shift_value(v, delta) if k in SHIFT_KEYS and isinstance(v, str) else _shift(v, delta))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_shift(x, delta) for x in obj]
    return obj


def load_seed(time_shift: bool = True) -> dict[str, Any]:
    """Load the seed JSON, optionally time-shifting it so anchor == today."""
    data = json.loads(SEED_FILE.read_text())
    if time_shift:
        anchor = parse_ts(data["meta"]["anchor"])
        now = datetime.now(timezone.utc)
        # Shift by whole days (keeps times-of-day intact for the story), and
        # keep the anchor at least slightly in the past.
        delta = timedelta(days=(now.date() - anchor.date()).days)
        if anchor + delta > now:
            delta -= timedelta(days=1) if (anchor + delta - now) > timedelta(hours=6) else timedelta(0)
        data = _shift(data, delta)
        data["meta"]["time_shift_days"] = delta.days
    return data


def _norm(s: str | None) -> str:
    return " ".join((s or "").lower().replace(".", " ").split())


def name_score(spoken: str, actual: str) -> float:
    """Very small fuzzy matcher tolerant of STT errors ("arav mehta")."""
    a, b = _norm(spoken), _norm(actual)
    if not a:
        return 0.0
    if a == b:
        return 1.0
    sa, sb = set(a.split()), set(b.split())
    overlap = len(sa & sb) / max(len(sb), 1)
    # character-level similarity
    from difflib import SequenceMatcher

    ratio = SequenceMatcher(None, a, b).ratio()
    first_ratio = SequenceMatcher(None, a.split()[0], b.split()[0]).ratio()
    return max(overlap, ratio, first_ratio * 0.85)


class DataStore(abc.ABC):
    """Async interface used by every agent tool."""

    @abc.abstractmethod
    async def init(self) -> None: ...

    @abc.abstractmethod
    async def _all(self, collection: str, customer_id: str | None = None) -> list[dict]: ...

    @abc.abstractmethod
    async def get_customer(self, customer_id: str) -> dict | None: ...

    @abc.abstractmethod
    async def save_case(self, case: dict) -> None: ...

    @abc.abstractmethod
    async def list_cases(self, limit: int = 25) -> list[dict]: ...

    # ---- shared helpers built on the primitives -------------------------
    async def find_customer(self, name: str | None = None, mobile_last4: str | None = None,
                            customer_id: str | None = None) -> dict:
        """Identity lookup. Returns {match, confidence, customer?, reason}."""
        if customer_id:
            cid = customer_id.upper().replace(" ", "")
            if not cid.startswith("C"):
                cid = "C" + cid
            cust = await self.get_customer(cid)
            if cust:
                score = name_score(name, cust["full_name"]) if name else 0.75
                ok = score >= 0.6
                return {"match": ok, "confidence": round(score, 2), "customer": cust if ok else None,
                        "reason": "customer_id matched" + ("" if ok else " but name mismatch")}
        customers = await self._all("customers")
        best, best_score = None, 0.0
        for c in customers:
            if mobile_last4 and c["mobile_last4"] != str(mobile_last4)[-4:]:
                continue
            sc = name_score(name or "", c["full_name"]) if name else 0.5
            if sc > best_score:
                best, best_score = c, sc
        if best and mobile_last4 and best_score >= 0.55:
            return {"match": True, "confidence": round(min(1.0, best_score + 0.1), 2), "customer": best,
                    "reason": "name + mobile last 4 matched"}
        return {"match": False, "confidence": round(best_score, 2), "customer": None,
                "reason": "no customer matched the details provided"}

    async def cards(self, customer_id: str) -> list[dict]:
        return await self._all("cards", customer_id)

    async def accounts(self, customer_id: str) -> list[dict]:
        return await self._all("accounts", customer_id)

    async def loans(self, customer_id: str) -> list[dict]:
        return await self._all("loans", customer_id)

    async def fraud_flags(self, customer_id: str) -> list[dict]:
        return sorted(await self._all("fraud_flags", customer_id), key=lambda f: f["date"], reverse=True)

    async def service_requests(self, customer_id: str) -> list[dict]:
        return await self._all("service_requests", customer_id)

    async def auth_events(self, customer_id: str, days: int = 30) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        evts = [e for e in await self._all("auth_events", customer_id) if parse_ts(e["timestamp"]) >= since]
        return sorted(evts, key=lambda e: e["timestamp"], reverse=True)

    async def transactions(self, customer_id: str, days: int = 90, instrument: str | None = None) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        txns = [t for t in await self._all("transactions", customer_id)
                if parse_ts(t["timestamp"]) >= since and (instrument is None or t["instrument"] == instrument)]
        return sorted(txns, key=lambda t: t["timestamp"], reverse=True)


class MemoryDataStore(DataStore):
    def __init__(self) -> None:
        self.data: dict[str, list[dict]] = {}
        self.cases: list[dict] = []

    async def init(self) -> None:
        seed = load_seed(get_settings().time_shift_data)
        self.data = {c: seed.get(c, []) for c in COLLECTIONS}
        self.meta = seed["meta"]
        log.info("MemoryDataStore loaded %s", {k: len(v) for k, v in self.data.items()})

    async def _all(self, collection: str, customer_id: str | None = None) -> list[dict]:
        rows = self.data.get(collection, [])
        if customer_id:
            rows = [r for r in rows if r.get("customer_id") == customer_id]
        return copy.deepcopy(rows)

    async def get_customer(self, customer_id: str) -> dict | None:
        for c in self.data["customers"]:
            if c["customer_id"] == customer_id:
                return copy.deepcopy(c)
        return None

    async def save_case(self, case: dict) -> None:
        self.cases = [c for c in self.cases if c.get("case_id") != case.get("case_id")]
        self.cases.insert(0, copy.deepcopy(case))

    async def list_cases(self, limit: int = 25) -> list[dict]:
        return copy.deepcopy(self.cases[:limit])


class FirestoreDataStore(DataStore):
    """Firestore back-end. Small reads are cached for the life of the process."""

    def __init__(self) -> None:
        from google.cloud import firestore  # imported lazily

        s = get_settings()
        self.db = firestore.AsyncClient(project=s.gcp_project, database=s.firestore_database)
        self._cache: dict[str, list[dict]] = {}

    async def init(self) -> None:
        if get_settings().auto_seed:
            await seed_firestore(self.db, force=False)

    async def _all(self, collection: str, customer_id: str | None = None) -> list[dict]:
        key = f"{collection}:{customer_id}"
        if key in self._cache:
            return copy.deepcopy(self._cache[key])
        q = self.db.collection(collection)
        if customer_id:
            q = q.where("customer_id", "==", customer_id)
        rows = [d.to_dict() async for d in q.stream()]
        self._cache[key] = rows
        return copy.deepcopy(rows)

    async def get_customer(self, customer_id: str) -> dict | None:
        snap = await self.db.collection("customers").document(customer_id).get()
        return snap.to_dict() if snap.exists else None

    async def save_case(self, case: dict) -> None:
        await self.db.collection("cases").document(case["case_id"]).set(case)

    async def list_cases(self, limit: int = 25) -> list[dict]:
        from google.cloud import firestore

        q = self.db.collection("cases").order_by("created_at", direction=firestore.Query.DESCENDING).limit(limit)
        return [d.to_dict() async for d in q.stream()]


async def seed_firestore(db, force: bool = False) -> dict[str, int]:
    """Write the seed JSON into Firestore (batched). Idempotent unless force."""
    meta_ref = db.collection("_meta").document("seed")
    snap = await meta_ref.get()
    if snap.exists and not force:
        log.info("Firestore already seeded at %s - skipping", snap.to_dict().get("seeded_at"))
        return {}
    seed = load_seed(get_settings().time_shift_data)
    counts: dict[str, int] = {}
    for coll in COLLECTIONS:
        rows = seed.get(coll, [])
        for i in range(0, len(rows), 400):  # Firestore batch limit is 500
            batch = db.batch()
            for row in rows[i:i + 400]:
                batch.set(db.collection(coll).document(row[ID_FIELDS[coll]]), row)
            await batch.commit()
        counts[coll] = len(rows)
    await meta_ref.set({"seeded_at": datetime.now(timezone.utc).isoformat(), "counts": counts,
                        "anchor": seed["meta"]["anchor"]})
    log.info("Seeded Firestore: %s", counts)
    return counts


_store: DataStore | None = None
_lock = asyncio.Lock()


async def get_store() -> DataStore:
    """Singleton accessor; falls back to memory if Firestore is unavailable."""
    global _store
    async with _lock:
        if _store is None:
            backend = get_settings().data_backend
            if backend == "firestore":
                try:
                    store: DataStore = FirestoreDataStore()
                    await store.init()
                    _store = store
                except Exception as exc:
                    log.error("Firestore unavailable (%s) - falling back to in-memory data", exc)
                    _store = MemoryDataStore()
                    await _store.init()
            else:
                _store = MemoryDataStore()
                await _store.init()
    return _store
