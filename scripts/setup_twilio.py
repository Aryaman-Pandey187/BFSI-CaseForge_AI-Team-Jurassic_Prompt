#!/usr/bin/env python3
"""
Twilio setup for CaseForge AI: buy a voice number (optional) and point its
voice webhook + status callback at your Cloud Run / ngrok URL.

Examples
  # list a few available US numbers
  python3 scripts/setup_twilio.py --search --country US --area-code 415
  # buy the first available US local number and wire it up
  python3 scripts/setup_twilio.py --buy --country US --base-url https://caseforge-xyz.a.run.app
  # re-point an existing number (e.g. after redeploying or restarting ngrok)
  python3 scripts/setup_twilio.py --number +14155550123 --base-url https://abcd.ngrok-free.app

Credentials: TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN env vars (or a .env file in the repo root).

Notes
  * Indian (+91) Twilio numbers need a regulatory bundle (business docs) and take days to approve.
    For a hackathon demo use a US/UK/CA number; dial it from your phone (international rates apply)
    or from the Twilio console / a VoIP app. Trial accounts can only receive calls from verified caller IDs
    and play a short trial preamble before connecting.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def load_env():
    for f in (Path(__file__).resolve().parent.parent / ".env", Path(__file__).resolve().parent.parent / "backend" / ".env"):
        if f.exists():
            for line in f.read_text().splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    load_env()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", help="Public HTTPS base URL of the backend (Cloud Run or ngrok)")
    p.add_argument("--number", help="Existing Twilio number (E.164) to configure")
    p.add_argument("--buy", action="store_true", help="Buy a new local voice number")
    p.add_argument("--search", action="store_true", help="Only list available numbers")
    p.add_argument("--country", default="US")
    p.add_argument("--area-code", type=int)
    p.add_argument("--friendly-name", default="CaseForge AI Demo")
    a = p.parse_args()

    sid, token = os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN")
    if not sid or not token or token.startswith("sm://"):
        print("Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN (plain values) in your environment.", file=sys.stderr)
        return 2
    from twilio.rest import Client

    client = Client(sid, token)
    if a.search or a.buy:
        kw = {"voice_enabled": True, "limit": 5}
        if a.area_code:
            kw["area_code"] = a.area_code
        avail = client.available_phone_numbers(a.country).local.list(**kw)
        if not avail:
            print("No numbers available for that search; try another --area-code or --country.")
            return 1
        for n in avail:
            print(f"  {n.phone_number}  {n.locality or ''} {n.region or ''}")
        if a.search:
            return 0
        bought = client.incoming_phone_numbers.create(phone_number=avail[0].phone_number, friendly_name=a.friendly_name)
        print(f"Bought {bought.phone_number} (sid {bought.sid})")
        a.number = bought.phone_number

    if not a.number:
        print("Nothing to configure: pass --number or --buy.")
        return 1
    if not a.base_url:
        print("--base-url is required to configure the webhook.")
        return 1
    base = a.base_url.rstrip("/")
    matches = client.incoming_phone_numbers.list(phone_number=a.number)
    if not matches:
        print(f"{a.number} is not in this Twilio account.")
        return 1
    num = matches[0].update(voice_url=f"{base}/twilio/voice", voice_method="POST",
                            status_callback=f"{base}/twilio/status", status_callback_method="POST")
    print("Configured:")
    print(f"  number          {num.phone_number}")
    print(f"  voice webhook   {num.voice_url}")
    print(f"  status callback {num.status_callback}")
    print(f"\nCall {num.phone_number} and watch {base}/ light up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
