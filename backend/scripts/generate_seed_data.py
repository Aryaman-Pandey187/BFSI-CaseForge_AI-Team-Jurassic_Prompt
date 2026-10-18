#!/usr/bin/env python3
"""
Deterministically (re)generate ``app/data/seed_data.json``.

The JSON file is committed, so you never *need* to run this. It exists so the
dummy data is reproducible and easy to tweak. All timestamps are anchored to
``ANCHOR`` (the "demo day"); at seed time the data store shifts every date so
that the anchor maps to *today*, keeping "last 90 days" logic fresh forever.

Run:  python scripts/generate_seed_data.py
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
ANCHOR = datetime(2026, 10, 17, 9, 0, tzinfo=IST)  # the demo "now"
OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "seed_data.json"
rnd = random.Random(42)

CITIES = {
    "Mumbai": ("Maharashtra", "IN", 19.0760, 72.8777),
    "Bengaluru": ("Karnataka", "IN", 12.9716, 77.5946),
    "Gurugram": ("Haryana", "IN", 28.4595, 77.0266),
    "Chennai": ("Tamil Nadu", "IN", 13.0827, 80.2707),
    "Jaipur": ("Rajasthan", "IN", 26.9124, 75.7873),
    "Kolkata": ("West Bengal", "IN", 22.5726, 88.3639),
    "Hyderabad": ("Telangana", "IN", 17.3850, 78.4867),
    "Pune": ("Maharashtra", "IN", 18.5204, 73.8567),
    "Lucknow": ("Uttar Pradesh", "IN", 26.8467, 80.9462),
    "Panaji": ("Goa", "IN", 15.4909, 73.8278),
    "Hosur": ("Tamil Nadu", "IN", 12.7409, 77.8253),
    "Bucharest": ("Bucharest", "RO", 44.4268, 26.1025),
}

# (merchant, mcc, mcc description, channel, min, max)
MERCHANTS = [
    ("BigBasket", "5411", "Grocery Stores", "ECOM", 600, 4200),
    ("Reliance Smart", "5411", "Grocery Stores", "POS", 450, 3800),
    ("Indian Oil Fuel Station", "5541", "Service Stations", "POS", 1200, 4500),
    ("Swiggy", "5814", "Fast Food Restaurants", "ECOM", 180, 1400),
    ("Zomato", "5814", "Fast Food Restaurants", "ECOM", 220, 1600),
    ("Amazon India", "5399", "General Merchandise", "ECOM", 400, 9000),
    ("Uber India", "4121", "Taxicabs / Rideshare", "ECOM", 140, 900),
    ("Starbucks", "5814", "Fast Food Restaurants", "CONTACTLESS", 250, 900),
    ("Apollo Pharmacy", "5912", "Drug Stores", "POS", 150, 2600),
    ("Netflix", "4899", "Cable / Streaming", "ECOM", 649, 649),
    ("Myntra", "5651", "Family Clothing", "ECOM", 900, 6500),
    ("PVR Cinemas", "7832", "Motion Picture Theatres", "POS", 400, 1800),
    ("Croma Electronics", "5732", "Electronics Stores", "POS", 1500, 22000),
]

_counter = {"txn": 0, "evt": 0}


def ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def txn_id() -> str:
    _counter["txn"] += 1
    return f"TXN{_counter['txn']:06d}"


def evt_id() -> str:
    _counter["evt"] += 1
    return f"AUTH{_counter['evt']:05d}"


def jitter(city: str) -> tuple[float, float]:
    _, _, lat, lon = CITIES[city]
    return round(lat + rnd.uniform(-0.05, 0.05), 4), round(lon + rnd.uniform(-0.05, 0.05), 4)


def mk_txn(cust, instrument, card_id, account_id, dt, amount, merchant, mcc, mcc_desc,
           channel, city, device_id, status="APPROVED", direction="DEBIT", extra=None):
    state, country, *_ = CITIES[city]
    lat, lon = jitter(city)
    t = {
        "txn_id": txn_id(),
        "customer_id": cust,
        "instrument": instrument,  # credit_card | debit_card | account
        "card_id": card_id,
        "account_id": account_id,
        "timestamp": ts(dt),
        "amount": round(float(amount), 2),
        "currency": "INR",
        "direction": direction,
        "merchant": merchant,
        "mcc": mcc,
        "mcc_description": mcc_desc,
        "channel": channel,
        "city": city,
        "country": country,
        "lat": lat,
        "lon": lon,
        "device_id": device_id,
        "status": status,
        "entry_mode": {"POS": "CHIP", "CONTACTLESS": "NFC", "ECOM": "CNP", "ATM": "CHIP"}.get(channel, "NA"),
    }
    if extra:
        t.update(extra)
    return t


def background_card_txns(cust, instrument, card_id, account_id, city, device, n_days=90, every=(1, 4)):
    out = []
    day = n_days
    while day > 1:
        day -= rnd.randint(*every)
        if day < 1:
            break
        m = rnd.choice(MERCHANTS)
        hour = rnd.choice([9, 11, 13, 14, 18, 19, 20, 21])
        dt = (ANCHOR - timedelta(days=day)).replace(hour=hour, minute=rnd.randint(0, 59))
        amt = m[4] if m[4] == m[5] else rnd.uniform(m[4], m[5])
        out.append(mk_txn(cust, instrument, card_id, account_id, dt, amt, m[0], m[1], m[2], m[3], city,
                          device if m[3] == "ECOM" else f"POS-{city[:3].upper()}-{rnd.randint(100,999)}"))
    return out


def monthly_credits(cust, account_id, employer, amount, months, city, day_of_month=1):
    out = []
    for m in months:  # months back from anchor (e.g. [3,2,1])
        dt = (ANCHOR.replace(day=1) - timedelta(days=30 * m)).replace(day=day_of_month, hour=10, minute=5)
        out.append(mk_txn(cust, "account", None, account_id, dt, amount, f"SALARY {employer}", "0000",
                          "Salary Credit (NEFT)", "NEFT", city, "BANK", direction="CREDIT"))
    return out


customers, cards, accounts, loans, transactions, fraud_flags, auth_events, service_requests = (
    [], [], [], [], [], [], [], [])


def add_customer(cid, name, dob, mobile, city, segment, since, risk, email=None, **kw):
    first = name.split()[0]
    state, country, *_ = CITIES[city]
    c = {
        "customer_id": cid,
        "full_name": name,
        "first_name": first,
        "dob": dob,
        "registered_mobile": mobile,
        "mobile_last4": mobile[-4:],
        "email": email or f"{first.lower()}.{name.split()[-1].lower()}@example.in",
        "city": city,
        "state": state,
        "country": country,
        "address": kw.pop("address", f"{rnd.randint(4, 220)}, {rnd.choice(['MG Road', 'Park Street', 'Lake View', 'Sector 21', 'Anna Nagar', 'Banjara Hills'])}, {city}"),
        "segment": segment,
        "relationship_since": since,
        "kyc_status": kw.pop("kyc_status", "VERIFIED"),
        "risk_rating": risk,
        "preferred_language": kw.pop("preferred_language", "English"),
        "pep": False,
        "vulnerable_customer": kw.pop("vulnerable_customer", False),
        "nps_last": kw.pop("nps_last", rnd.randint(6, 10)),
        "products": [],
        "notes": kw.pop("notes", ""),
    }
    c.update(kw)
    customers.append(c)
    return c


def add_card(cust, card_id, ctype, network, variant, last4, home_city, limit=None, account_id=None):
    c = {
        "card_id": card_id, "customer_id": cust["customer_id"], "type": ctype, "network": network,
        "variant": variant, "last4": last4, "status": "ACTIVE", "home_city": home_city,
        "issued_on": "2023-04-12", "expiry": "08/29",
        "international_enabled": ctype == "credit", "contactless_enabled": True,
    }
    if ctype == "credit":
        c.update({"credit_limit": limit, "available_limit": limit, "outstanding": 0.0,
                  "min_due": 0.0, "statement_day": 12, "reward_points": rnd.randint(1200, 48000)})
    else:
        c.update({"linked_account_id": account_id, "daily_atm_limit": 50000, "daily_pos_limit": 200000})
    cards.append(c)
    cust["products"].append(f"{network} {variant} {ctype.title()} Card ••{last4}".replace("  ", " "))
    return c


def add_account(cust, account_id, atype, balance, **kw):
    a = {"account_id": account_id, "customer_id": cust["customer_id"], "type": atype,
         "balance": balance, "available_balance": balance, "currency": "INR", "status": "ACTIVE",
         "branch": f"{cust['city']} Main", "ifsc": "HRZN0001" + account_id[-3:],
         "opened_on": cust["relationship_since"], "nominee": True}
    a.update(kw)
    accounts.append(a)
    cust["products"].append(f"{atype.title()} Account ••{account_id[-4:]}")
    return a


def emi_schedule(start: datetime, n: int, emi: float, statuses: dict[int, dict]):
    """Build an EMI schedule; `statuses` overrides by installment number."""
    rows = []
    for i in range(1, n + 1):
        due = (start + timedelta(days=30.4 * (i - 1))).replace(hour=0, minute=0)
        row = {"installment": i, "due_date": due.date().isoformat(), "amount": emi,
               "status": "UPCOMING" if due > ANCHOR else "PAID",
               "paid_date": None if due > ANCHOR else (due + timedelta(days=0)).date().isoformat(),
               "dpd": 0}
        if i in statuses:
            row.update(statuses[i])
        rows.append(row)
    return rows


def add_auth(cust, etype, dt, channel, device, ip_city, risk, detail):
    auth_events.append({
        "event_id": evt_id(), "customer_id": cust, "type": etype, "timestamp": ts(dt), "channel": channel,
        "device_id": device, "ip_city": ip_city, "risk": risk, "detail": detail,
    })


def routine_logins(cust, device, city, n=6):
    for _ in range(n):
        d = ANCHOR - timedelta(days=rnd.randint(5, 88), hours=rnd.randint(0, 12))
        add_auth(cust, "LOGIN_SUCCESS", d, rnd.choice(["MOBILE_APP", "NET_BANKING"]), device, city, "LOW",
                 "Routine login from registered device")


# ---------------------------------------------------------------------------
# C1001 Aarav Mehta — CREDIT CARD FRAUD (account takeover after SIM swap)
# ---------------------------------------------------------------------------
c = add_customer("C1001", "Aarav Mehta", "1988-03-14", "+919820114821", "Mumbai", "Affluent", "2016-07-01",
                 "LOW", notes="Frequent domestic traveller; never used card outside India.")
cc = add_card(c, "CC-1001-01", "credit", "Visa", "Signature", "4417", "Mumbai", limit=500000)
sb = add_account(c, "SB-30010041", "savings", 412880.40)
dev = "DEV-A1-IPHONE15"
tx = background_card_txns("C1001", "credit_card", cc["card_id"], None, "Mumbai", dev, every=(1, 3))
tx += monthly_credits("C1001", sb["account_id"], "NOVA FINTECH PVT LTD", 245000, [3, 2, 1, 0], "Mumbai")
d0 = ANCHOR - timedelta(days=1)
tx += [
    mk_txn("C1001", "credit_card", cc["card_id"], None, d0.replace(hour=20, minute=41), 420, "Starbucks Bandra",
           "5814", "Fast Food Restaurants", "CONTACTLESS", "Mumbai", "POS-MUM-221"),
    mk_txn("C1001", "credit_card", cc["card_id"], None, d0.replace(hour=22, minute=4), 49, "DIGITALKEYS.RO",
           "5816", "Digital Goods - Games", "ECOM", "Bucharest", "DEV-UNKNOWN-7F3A"),
    mk_txn("C1001", "credit_card", cc["card_id"], None, d0.replace(hour=22, minute=9), 99, "DIGITALKEYS.RO",
           "5816", "Digital Goods - Games", "ECOM", "Bucharest", "DEV-UNKNOWN-7F3A"),
    mk_txn("C1001", "credit_card", cc["card_id"], None, d0.replace(hour=22, minute=58), 184500, "eMAG Electronics Bucharest",
           "5732", "Electronics Stores", "POS", "Bucharest", "POS-RO-88412",
           extra={"entry_mode": "MAGSTRIPE_FALLBACK", "original_amount": 1890.0, "original_currency": "EUR"}),
    mk_txn("C1001", "credit_card", cc["card_id"], None, d0.replace(hour=23, minute=21), 62300, "Bijuteria Aurora",
           "5944", "Jewelry Stores", "POS", "Bucharest", "POS-RO-10233", status="DECLINED",
           extra={"entry_mode": "MAGSTRIPE_FALLBACK", "decline_reason": "VELOCITY_LIMIT",
                  "original_amount": 638.0, "original_currency": "EUR"}),
]
transactions += tx
cc["outstanding"] = round(sum(t["amount"] for t in tx if t["card_id"] == cc["card_id"] and t["status"] == "APPROVED" and t["timestamp"] > ts(ANCHOR - timedelta(days=25))), 2)
cc["available_limit"] = round(cc["credit_limit"] - cc["outstanding"], 2)
routine_logins("C1001", dev, "Mumbai")
add_auth("C1001", "SIM_SWAP", (ANCHOR - timedelta(days=2)).replace(hour=11, minute=20), "TELECOM_API",
         "SIM-NEW-89914", "Mumbai", "HIGH", "Telecom operator reported SIM replacement on registered mobile")
add_auth("C1001", "PASSWORD_RESET", (ANCHOR - timedelta(days=2)).replace(hour=11, minute=46), "NET_BANKING",
         "DEV-UNKNOWN-7F3A", "Bucharest", "HIGH", "Password reset via OTP to registered mobile")
add_auth("C1001", "NEW_DEVICE_LOGIN", (ANCHOR - timedelta(days=2)).replace(hour=11, minute=52), "MOBILE_APP",
         "DEV-UNKNOWN-7F3A", "Bucharest", "HIGH", "First login from unrecognised Android device")
add_auth("C1001", "CARD_LIMIT_CHANGE", (ANCHOR - timedelta(days=2)).replace(hour=12, minute=3), "MOBILE_APP",
         "DEV-UNKNOWN-7F3A", "Bucharest", "HIGH", "International usage enabled & POS limit raised to max")

# ---------------------------------------------------------------------------
# C1002 Priya Nair — DEBIT CARD: stolen card, ATM cash-out + linked a/c drain
# ---------------------------------------------------------------------------
c = add_customer("C1002", "Priya Nair", "1992-11-02", "+919845207310", "Bengaluru", "Mass Affluent",
                 "2019-02-18", "LOW")
sb = add_account(c, "SB-30020087", "savings", 38500.00, balance_7d_ago=289400.00)
dc = add_card(c, "DC-1002-01", "debit", "RuPay", "Platinum", "9032", "Bengaluru", account_id=sb["account_id"])
dev = "DEV-P2-PIXEL8"
tx = background_card_txns("C1002", "debit_card", dc["card_id"], sb["account_id"], "Bengaluru", dev, every=(2, 4))
tx += monthly_credits("C1002", sb["account_id"], "ORBIT LABS INDIA", 132000, [3, 2, 1, 0], "Bengaluru")
for i, (h, m) in enumerate([(7, 15), (23, 50)]):
    tx.append(mk_txn("C1002", "debit_card", dc["card_id"], sb["account_id"],
                     (ANCHOR - timedelta(days=40 + i * 20)).replace(hour=h, minute=m), 5000,
                     "HORIZON ATM Koramangala", "6011", "ATM Cash Withdrawal", "ATM", "Bengaluru", "ATM-BLR-0041"))
d0 = ANCHOR
atms = [("HORIZON ATM Majestic", "ATM-BLR-0102"), ("SBI ATM Shivajinagar", "ATM-BLR-7731"),
        ("HDFC ATM Hebbal", "ATM-BLR-5520"), ("SBI ATM Shivajinagar", "ATM-BLR-7731"),
        ("AXIS ATM Electronic City", "ATM-BLR-3307")]
for i, (name, atm) in enumerate(atms):
    tx.append(mk_txn("C1002", "debit_card", dc["card_id"], sb["account_id"],
                     d0.replace(hour=1, minute=8) + timedelta(minutes=i * 9), 10000, name, "6011",
                     "ATM Cash Withdrawal", "ATM", "Bengaluru", atm))
tx.append(mk_txn("C1002", "debit_card", dc["card_id"], sb["account_id"], d0.replace(hour=2, minute=15), 10000,
                 "IOB ATM Hosur Bus Stand", "6011", "ATM Cash Withdrawal", "ATM", "Hosur", "ATM-HSR-1180",
                 status="DECLINED", extra={"decline_reason": "DAILY_ATM_LIMIT_EXCEEDED"}))
tx.append(mk_txn("C1002", "debit_card", dc["card_id"], sb["account_id"], d0.replace(hour=2, minute=41), 48000,
                 "Sri Lakshmi Jewellers", "5944", "Jewelry Stores", "POS", "Hosur", "POS-HSR-404"))
tx.append(mk_txn("C1002", "account", None, sb["account_id"], d0.replace(hour=3, minute=2), 95000,
                 "IMPS to R K TRADERS (new beneficiary)", "4829", "Money Transfer", "IMPS", "Hosur",
                 "DEV-UNKNOWN-22C9", extra={"beneficiary_added_minutes_before": 11}))
tx.append(mk_txn("C1002", "account", None, sb["account_id"], d0.replace(hour=3, minute=9), 45000,
                 "UPI to rktraders77@okaxis", "4829", "Money Transfer", "UPI", "Hosur", "DEV-UNKNOWN-22C9"))
transactions += tx
routine_logins("C1002", dev, "Bengaluru")
add_auth("C1002", "CARD_PIN_FAIL", d0.replace(hour=1, minute=2), "ATM", "ATM-BLR-0102", "Bengaluru", "MEDIUM",
         "2 incorrect PIN attempts before successful withdrawal")
add_auth("C1002", "NEW_DEVICE_LOGIN", d0.replace(hour=2, minute=46), "MOBILE_APP", "DEV-UNKNOWN-22C9", "Hosur",
         "HIGH", "Login from new device after MPIN reset using debit card details")
add_auth("C1002", "MPIN_RESET", d0.replace(hour=2, minute=44), "MOBILE_APP", "DEV-UNKNOWN-22C9", "Hosur", "HIGH",
         "MPIN reset authenticated with debit card number + PIN")
add_auth("C1002", "BENEFICIARY_ADDED", d0.replace(hour=2, minute=51), "MOBILE_APP", "DEV-UNKNOWN-22C9", "Hosur",
         "HIGH", "New payee 'R K TRADERS' added; cooling period bypassed (low first-transfer rule)")
fraud_flags.append({"flag_id": "FF-2024-0112", "customer_id": "C1002", "type": "PHISHING_ALERT",
                    "date": "2024-06-03", "severity": "LOW", "status": "CLOSED", "sar_filed": False,
                    "description": "Customer reported phishing SMS; no loss. Education provided."})

# ---------------------------------------------------------------------------
# C1003 Rohan Gupta — LOAN HARDSHIP (job loss, bounced EMIs)
# ---------------------------------------------------------------------------
c = add_customer("C1003", "Rohan Gupta", "1985-06-21", "+919811035562", "Gurugram", "Mass Affluent",
                 "2014-09-09", "MEDIUM", notes="Long-standing customer; first delinquency in 10 years.")
sb = add_account(c, "SB-30030192", "savings", 6240.75, balance_90d_ago=184300.00)
dc = add_card(c, "DC-1003-01", "debit", "Mastercard", "World", "2286", "Gurugram", account_id=sb["account_id"])
cc = add_card(c, "CC-1003-01", "credit", "Mastercard", "Titanium", "6630", "Gurugram", limit=180000)
cc.update({"outstanding": 164220.0, "available_limit": 15780.0, "min_due": 8211.0,
           "utilisation_trend": [22, 35, 58, 91], "payment_behaviour": "MIN_DUE_ONLY_LAST_2_CYCLES"})
dev = "DEV-R3-ONEPLUS"
tx = background_card_txns("C1003", "debit_card", dc["card_id"], sb["account_id"], "Gurugram", dev, every=(3, 6))
tx += monthly_credits("C1003", sb["account_id"], "ZENTRIX TECHNOLOGIES", 168000, [3], "Gurugram")
tx += [mk_txn("C1003", "account", None, sb["account_id"], (ANCHOR - timedelta(days=62)).replace(hour=10), 412000,
              "FULL & FINAL SETTLEMENT ZENTRIX TECHNOLOGIES", "0000", "Salary Credit (NEFT)", "NEFT", "Gurugram",
              "BANK", direction="CREDIT")]
transactions += tx
start = datetime(2023, 1, 5, tzinfo=IST)
n_paid = sum(1 for i in range(1, 241) if start + timedelta(days=30.4 * (i - 1)) <= ANCHOR)
over = {n_paid - 2: {"status": "BOUNCED", "paid_date": None, "dpd": 72, "bounce_reason": "INSUFFICIENT_FUNDS"},
        n_paid - 1: {"status": "BOUNCED", "paid_date": None, "dpd": 42, "bounce_reason": "INSUFFICIENT_FUNDS"},
        n_paid: {"status": "OVERDUE", "paid_date": None, "dpd": 12}}
loans.append({
    "loan_id": "HL-77120034", "customer_id": "C1003", "type": "HOME_LOAN", "principal": 6500000,
    "outstanding": 5734120.0, "interest_rate": 8.65, "tenure_months": 240, "emi_amount": 57055.0,
    "start_date": start.date().isoformat(), "collateral": "Flat 1204, Tower B, Sector 65, Gurugram",
    "emi_schedule": emi_schedule(start, 240, 57055.0, over),
    "bounce_history": [
        {"date": (ANCHOR - timedelta(days=72)).date().isoformat(), "amount": 57055.0, "reason": "INSUFFICIENT_FUNDS", "charge": 590},
        {"date": (ANCHOR - timedelta(days=42)).date().isoformat(), "amount": 57055.0, "reason": "INSUFFICIENT_FUNDS", "charge": 590},
    ],
    "dpd": 72, "bucket": "SMA-1", "restructure_eligible": True, "moratorium_history": [],
    "auto_debit_account": sb["account_id"],
})
start2 = datetime(2025, 3, 10, tzinfo=IST)
n2 = sum(1 for i in range(1, 37) if start2 + timedelta(days=30.4 * (i - 1)) <= ANCHOR)
loans.append({
    "loan_id": "PL-55290811", "customer_id": "C1003", "type": "PERSONAL_LOAN", "principal": 800000,
    "outstanding": 512400.0, "interest_rate": 12.4, "tenure_months": 36, "emi_amount": 26720.0,
    "start_date": start2.date().isoformat(), "collateral": None,
    "emi_schedule": emi_schedule(start2, 36, 26720.0, {
        n2 - 1: {"status": "BOUNCED", "paid_date": None, "dpd": 37, "bounce_reason": "INSUFFICIENT_FUNDS"},
        n2: {"status": "PAID_LATE", "paid_date": (ANCHOR - timedelta(days=3)).date().isoformat(), "dpd": 4}}),
    "bounce_history": [{"date": (ANCHOR - timedelta(days=37)).date().isoformat(), "amount": 26720.0,
                        "reason": "INSUFFICIENT_FUNDS", "charge": 500}],
    "dpd": 37, "bucket": "SMA-1", "restructure_eligible": True, "moratorium_history": [],
    "auto_debit_account": sb["account_id"],
})
c["products"] += ["Home Loan ••0034", "Personal Loan ••0811"]
routine_logins("C1003", dev, "Gurugram")
add_auth("C1003", "LOGIN_SUCCESS", ANCHOR - timedelta(hours=20), "MOBILE_APP", dev, "Gurugram", "LOW",
         "Viewed loan statement & 'EMI holiday' FAQ page 4 times this week")
service_requests.append({"sr_id": "SR-88410", "customer_id": "C1003", "type": "EMI_DATE_CHANGE",
                         "status": "CLOSED", "created": (ANCHOR - timedelta(days=50)).date().isoformat(),
                         "detail": "Requested EMI date change - not eligible while overdue"})

# ---------------------------------------------------------------------------
# C1004 Sneha Iyer — CLEAN, simple ACCOUNT QUERY (balance / cheque book / FD)
# ---------------------------------------------------------------------------
c = add_customer("C1004", "Sneha Iyer", "1994-01-30", "+919884019047", "Chennai", "Affluent", "2018-05-22", "LOW",
                 nps_last=10)
sb = add_account(c, "SB-30040311", "savings", 342118.50, interest_rate=3.0, last_statement="2026-09-30",
                 monthly_avg_balance=318400.0)
add_account(c, "FD-90040022", "fixed_deposit", 500000.00, interest_rate=7.1, maturity_date="2026-11-28",
            maturity_amount=535500.0, auto_renew=True)
dc = add_card(c, "DC-1004-01", "debit", "Visa", "Platinum", "5521", "Chennai", account_id=sb["account_id"])
dev = "DEV-S4-GALAXY"
transactions += background_card_txns("C1004", "debit_card", dc["card_id"], sb["account_id"], "Chennai", dev)
transactions += monthly_credits("C1004", sb["account_id"], "LUMEN HEALTHCARE", 154000, [3, 2, 1, 0], "Chennai")
routine_logins("C1004", dev, "Chennai", n=8)
service_requests += [
    {"sr_id": "SR-90112", "customer_id": "C1004", "type": "CHEQUE_BOOK_REQUEST", "status": "DISPATCHED",
     "created": (ANCHOR - timedelta(days=4)).date().isoformat(),
     "detail": "25-leaf cheque book dispatched via BlueDart AWB 81234567890, ETA 2 working days",
     "eta": (ANCHOR + timedelta(days=2)).date().isoformat()},
    {"sr_id": "SR-87001", "customer_id": "C1004", "type": "ADDRESS_UPDATE", "status": "CLOSED",
     "created": "2026-03-11", "detail": "Communication address updated"},
]

# ---------------------------------------------------------------------------
# C1005 Vikram Singh — RISKY: serial disputes, prior SAR (friendly-fraud risk)
# ---------------------------------------------------------------------------
c = add_customer("C1005", "Vikram Singh", "1979-09-08", "+919829056678", "Jaipur", "Mass", "2021-01-15", "HIGH",
                 notes="Under enhanced due diligence since 2025 SAR.")
cc = add_card(c, "CC-1005-01", "credit", "Visa", "Gold", "7781", "Jaipur", limit=250000)
add_account(c, "SB-30050078", "savings", 18420.00)
dev = "DEV-V5-REDMI"
transactions += background_card_txns("C1005", "credit_card", cc["card_id"], None, "Jaipur", dev, every=(1, 3))
transactions.append(mk_txn("C1005", "credit_card", cc["card_id"], None, ANCHOR - timedelta(days=3, hours=4), 74999,
                           "Apple Store Online", "5732", "Electronics Stores", "ECOM", "Jaipur", dev))
fraud_flags += [
    {"flag_id": "FF-2025-0441", "customer_id": "C1005", "type": "SAR", "date": "2025-08-19", "severity": "HIGH",
     "status": "FILED", "sar_filed": True, "description": "SAR filed: structured cash deposits below reporting threshold"},
    {"flag_id": "FF-2025-0502", "customer_id": "C1005", "type": "CHARGEBACK_ABUSE", "date": "2025-11-02",
     "severity": "MEDIUM", "status": "OPEN", "sar_filed": False,
     "description": "4 'item not received' disputes in 6 months; 3 merchants proved delivery"},
    {"flag_id": "FF-2026-0071", "customer_id": "C1005", "type": "DISPUTE_LOST", "date": "2026-04-22",
     "severity": "MEDIUM", "status": "CLOSED", "sar_filed": False,
     "description": "Dispute on Rs 54,000 electronics purchase rejected - signed POD from merchant"},
]
routine_logins("C1005", dev, "Jaipur")
add_auth("C1005", "OTP_FAIL", ANCHOR - timedelta(days=6), "NET_BANKING", "DEV-UNKNOWN-0B1E", "Delhi", "MEDIUM",
         "3 consecutive OTP failures")

# ---------------------------------------------------------------------------
# C1006 Ananya Das — CLEAN, merchant dispute (double charge)
# ---------------------------------------------------------------------------
c = add_customer("C1006", "Ananya Das", "1996-12-12", "+919830061234", "Kolkata", "Mass Affluent", "2020-10-03", "LOW")
cc = add_card(c, "CC-1006-01", "credit", "Mastercard", "Platinum", "3092", "Kolkata", limit=300000)
add_account(c, "SB-30060044", "savings", 96550.00)
dev = "DEV-A6-IPHONE13"
transactions += background_card_txns("C1006", "credit_card", cc["card_id"], None, "Kolkata", dev)
for mins in (0, 2):
    transactions.append(mk_txn("C1006", "credit_card", cc["card_id"], None,
                               (ANCHOR - timedelta(days=5)).replace(hour=16, minute=10 + mins), 18450,
                               "IndiGo Airlines", "3000", "Airlines", "ECOM", "Kolkata", dev,
                               extra={"booking_ref": "6E-QX7P2L"}))
routine_logins("C1006", dev, "Kolkata")

# ---------------------------------------------------------------------------
# C1007 Karthik Reddy — CLEAN home loan, prepayment enquiry
# ---------------------------------------------------------------------------
c = add_customer("C1007", "Karthik Reddy", "1983-04-04", "+919849077781", "Hyderabad", "Private", "2012-12-01", "LOW",
                 nps_last=9)
sb = add_account(c, "SB-30070009", "savings", 1824000.00)
dc = add_card(c, "DC-1007-01", "debit", "Visa", "Infinite", "1175", "Hyderabad", account_id=sb["account_id"])
dev = "DEV-K7-IPHONE16"
transactions += background_card_txns("C1007", "debit_card", dc["card_id"], sb["account_id"], "Hyderabad", dev, every=(2, 5))
transactions += monthly_credits("C1007", sb["account_id"], "AXIOM SEMICONDUCTORS", 410000, [3, 2, 1, 0], "Hyderabad")
start = datetime(2021, 6, 7, tzinfo=IST)
loans.append({"loan_id": "HL-77120981", "customer_id": "C1007", "type": "HOME_LOAN", "principal": 9500000,
              "outstanding": 7120400.0, "interest_rate": 8.4, "tenure_months": 240, "emi_amount": 81840.0,
              "start_date": start.date().isoformat(), "collateral": "Villa 22, Kokapet, Hyderabad",
              "emi_schedule": emi_schedule(start, 240, 81840.0, {}), "bounce_history": [], "dpd": 0,
              "bucket": "STANDARD", "restructure_eligible": False, "moratorium_history": [],
              "auto_debit_account": sb["account_id"], "prepayment_charges": "NIL (floating rate)"})
c["products"].append("Home Loan ••0981")
routine_logins("C1007", dev, "Hyderabad")

# ---------------------------------------------------------------------------
# C1008 Meera Kapoor — RISKY: money-mule pattern, SAR filed
# ---------------------------------------------------------------------------
c = add_customer("C1008", "Meera Kapoor", "2001-07-19", "+919822088890", "Pune", "Mass", "2025-12-02", "HIGH",
                 notes="Account on watchlist; inbound credits from many unrelated UPI handles.")
sb = add_account(c, "SB-30080126", "savings", 2210.00)
dc = add_card(c, "DC-1008-01", "debit", "RuPay", "Classic", "6404", "Pune", account_id=sb["account_id"])
for i in range(14):
    d = ANCHOR - timedelta(days=rnd.randint(1, 30), hours=rnd.randint(0, 20))
    amt = rnd.choice([24000, 31500, 18000, 45000, 27500])
    transactions.append(mk_txn("C1008", "account", None, sb["account_id"], d, amt,
                               f"UPI from user{rnd.randint(1000, 9999)}@ybl", "4829", "Money Transfer", "UPI",
                               "Pune", "BANK", direction="CREDIT"))
    transactions.append(mk_txn("C1008", "debit_card", dc["card_id"], sb["account_id"], d + timedelta(minutes=35),
                               min(amt, 10000), "Various ATM Pune", "6011", "ATM Cash Withdrawal", "ATM", "Pune",
                               f"ATM-PNQ-{rnd.randint(1000, 9999)}"))
fraud_flags += [
    {"flag_id": "FF-2026-0318", "customer_id": "C1008", "type": "MULE_ACCOUNT_SUSPECTED", "date": "2026-08-30",
     "severity": "HIGH", "status": "OPEN", "sar_filed": True,
     "description": "Rapid in-out pattern: 41 inbound UPI credits from 33 unrelated handles, cash-out within 1h"},
    {"flag_id": "FF-2026-0355", "customer_id": "C1008", "type": "NCRP_COMPLAINT", "date": "2026-09-21",
     "severity": "HIGH", "status": "OPEN", "sar_filed": False,
     "description": "National Cybercrime Reporting Portal complaint names this account as beneficiary"},
]
add_auth("C1008", "DEVICE_CHANGE", ANCHOR - timedelta(days=9), "MOBILE_APP", "DEV-UNKNOWN-55AA", "Mumbai", "HIGH",
         "Third device change in 30 days")

# ---------------------------------------------------------------------------
# C1009 Farhan Qureshi — CLEAN, salaried, credit card
# C1010 Isabella D'Souza — CLEAN, senior citizen (vulnerable flag)
# ---------------------------------------------------------------------------
c = add_customer("C1009", "Farhan Qureshi", "1990-02-25", "+919839012345", "Lucknow", "Mass Affluent", "2017-03-17", "LOW")
cc = add_card(c, "CC-1009-01", "credit", "RuPay", "Select", "8820", "Lucknow", limit=220000)
add_account(c, "SB-30090017", "savings", 158300.00)
transactions += background_card_txns("C1009", "credit_card", cc["card_id"], None, "Lucknow", "DEV-F9-VIVO")
routine_logins("C1009", "DEV-F9-VIVO", "Lucknow")

c = add_customer("C1010", "Isabella D'Souza", "1954-05-09", "+919823045566", "Panaji", "Private", "1998-08-08", "LOW",
                 vulnerable_customer=True, notes="Senior citizen; prefers slow, clear communication.")
sb = add_account(c, "SB-30100002", "savings", 2645000.00)
add_account(c, "FD-90100005", "fixed_deposit", 3000000.00, interest_rate=7.6, maturity_date="2027-02-14",
            maturity_amount=3228000.0, auto_renew=False)
dc = add_card(c, "DC-1010-01", "debit", "Visa", "Signature", "4090", "Panaji", account_id=sb["account_id"])
transactions += background_card_txns("C1010", "debit_card", dc["card_id"], sb["account_id"], "Panaji", "DEV-I10-IPAD", every=(4, 8))
routine_logins("C1010", "DEV-I10-IPAD", "Panaji", n=3)

transactions.sort(key=lambda t: t["timestamp"])
data = {
    "meta": {
        "anchor": ts(ANCHOR),
        "description": "CaseForge AI dummy BFSI data. All PII is fictitious.",
        "generated_by": "backend/scripts/generate_seed_data.py",
        "counts": {},
    },
    "customers": customers, "cards": cards, "accounts": accounts, "loans": loans,
    "transactions": transactions, "fraud_flags": fraud_flags, "auth_events": auth_events,
    "service_requests": service_requests,
}
data["meta"]["counts"] = {k: len(v) for k, v in data.items() if isinstance(v, list)}
OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False))
print(f"Wrote {OUT} :: {data['meta']['counts']}")
