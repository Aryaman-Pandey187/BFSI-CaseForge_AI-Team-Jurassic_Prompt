"""
Helpers for turning *spoken* text into structured values and back again.

STT output for phone calls looks like "four eight two one", "C one zero zero
one", "one lakh eighty four thousand" or "1.84 lakh". These helpers are used by
the mock agents and as a safety net for Gemini's entity extraction.
"""
from __future__ import annotations

import re

UNITS = {"zero": 0, "oh": 0, "o": 0, "one": 1, "two": 2, "three": 3, "four": 4, "for": 4, "five": 5, "six": 6,
         "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
         "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
SCALES = {"hundred": 100, "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000,
          "crore": 10_000_000, "k": 1_000}
DIGIT_WORDS = {k: str(v) for k, v in UNITS.items() if v < 10}
DIGIT_WORDS.update({"double": "", "triple": ""})


def spoken_digits(text: str) -> str:
    """'four eight two one' / 'double five six two' -> '4821' / '5562' (keeps existing digits)."""
    out, rep = [], 1
    for w in re.findall(r"[a-zA-Z]+|\d", text.lower()):
        if w == "double":
            rep = 2
            continue
        if w == "triple":
            rep = 3
            continue
        if w.isdigit():
            out.append(w * rep)
        elif w in DIGIT_WORDS and DIGIT_WORDS[w]:
            out.append(DIGIT_WORDS[w] * rep)
        else:
            rep = 1
            continue
        rep = 1
    return "".join(out)


def words_to_number(text: str) -> float | None:
    """
    Extract the most likely money amount from speech, e.g. 'one lakh eighty four thousand five hundred',
    '1.84 lakh', '₹1,84,500', 'Rs 50000', '50k'. Bare digit strings without a currency or scale word
    (like '4 8 2 1' or '9047') are ignored so identity digits are never mistaken for amounts.
    """
    t = text.lower().replace(",", "").replace("₹", " rs ").replace("rs.", " rs ")
    cands: list[float] = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(lakhs?|lac|crore|thousand|k)\b", t):
        cands.append(float(m.group(1)) * SCALES[m.group(2)])
    for m in re.finditer(r"\brs\s*(\d{2,}(?:\.\d+)?)|(\d{2,}(?:\.\d+)?)\s*(?:rupees|rs|inr)\b", t):
        cands.append(float(m.group(1) or m.group(2)))
    # spans of number words: "one lakh eighty four thousand"
    total = cur = 0
    has_scale = False
    for w in re.findall(r"[a-z]+|\d+", t) + ["."]:
        if w in UNITS:
            cur += UNITS[w]
        elif w in TENS:
            cur += TENS[w]
        elif w.isdigit() and has_scale is not None and len(w) <= 3 and (cur or total):
            cur += int(w)
        elif w == "hundred":
            cur = max(cur, 1) * 100
            has_scale = True
        elif w in SCALES and w != "k":
            total += max(cur, 1) * SCALES[w]
            cur, has_scale = 0, True
        elif w == "and" and (cur or total):
            continue
        else:
            if has_scale and (total + cur) >= 100:
                cands.append(float(total + cur))
            total = cur = 0
            has_scale = False
    return max(cands) if cands else None


def spoken_inr(amount: float) -> str:
    """184500 -> '1 lakh 84 thousand 500 rupees' (reads naturally in en-IN TTS)."""
    a = int(round(amount))
    parts = []
    for div, name in ((10_000_000, "crore"), (100_000, "lakh"), (1_000, "thousand")):
        if a >= div:
            parts.append(f"{a // div} {name}")
            a %= div
    if a:
        parts.append(str(a))
    return (" ".join(parts) or "0") + " rupees"


def spoken_date(iso: str) -> str:
    """'2026-10-19' -> '19 October' (TTS-friendly)."""
    from datetime import date

    try:
        d = date.fromisoformat(iso[:10])
        return f"{d.day} {d.strftime('%B')}"
    except ValueError:
        return iso
