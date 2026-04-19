"""
Closing-Date Validator — Nova Scotia
=====================================

Enforces Estevan's rule: closing can never land on a weekend or
Canadian/Nova Scotia statutory holiday.

Public API:

    validate_closing(date) -> dict
        {
          "ok":       bool,
          "reason":   "weekend" | "holiday:<name>" | None,
          "date":     iso string,
          "alternatives": [iso_prior_business_day, iso_next_business_day],
        }

    next_business_day(date) -> date
    prior_business_day(date) -> date
    is_business_day(date)    -> bool
    holiday_name(date)       -> str | None

Usage:

    from datetime import date
    from closing_date_validator import validate_closing
    v = validate_closing(date(2026, 7, 1))
    if not v["ok"]:
        print(f"{v['date']} is {v['reason']} — try {v['alternatives']}")
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional


# ---------------------------------------------------------------------------
# Holiday computations
# ---------------------------------------------------------------------------

def _easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm (Meeus/Jones/Butcher)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """nth occurrence of weekday (0=Mon) in year/month."""
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _monday_on_or_before(year: int, month: int, day: int) -> date:
    """Monday on or before the given date (for Victoria Day: Mon before May 25)."""
    target = date(year, month, day)
    return target - timedelta(days=target.weekday())


def ns_holidays(year: int) -> dict[date, str]:
    """Every NS / federal statutory holiday that closes banks + lawyers."""
    easter = _easter_sunday(year)
    good_friday = easter - timedelta(days=2)
    easter_monday = easter + timedelta(days=1)

    holidays: dict[date, str] = {
        date(year, 1, 1):   "New Year's Day",
        _nth_weekday_of_month(year, 2, 0, 3): "Nova Scotia Heritage Day",  # 3rd Mon Feb
        good_friday:        "Good Friday",
        easter_monday:      "Easter Monday",
        _monday_on_or_before(year, 5, 24): "Victoria Day",  # Mon on or before May 24
        date(year, 7, 1):   "Canada Day",
        _nth_weekday_of_month(year, 8, 0, 1): "Natal Day",  # 1st Mon Aug (NS Civic)
        _nth_weekday_of_month(year, 9, 0, 1): "Labour Day",  # 1st Mon Sep
        date(year, 9, 30):  "National Day for Truth and Reconciliation",
        _nth_weekday_of_month(year, 10, 0, 2): "Thanksgiving",  # 2nd Mon Oct
        date(year, 11, 11): "Remembrance Day",
        date(year, 12, 25): "Christmas Day",
        date(year, 12, 26): "Boxing Day",
    }

    # Observed-day shifting: if Canada Day, Remembrance Day, Christmas, Boxing, or
    # New Year's falls on a weekend, the bank/closing observance shifts to Monday
    # (and in the case of Christmas+Boxing both on weekend, to Mon+Tue).
    observed: dict[date, str] = dict(holidays)
    for d, name in list(holidays.items()):
        if d.weekday() == 5:  # Saturday
            observed[d + timedelta(days=2)] = f"{name} (observed)"
        elif d.weekday() == 6:  # Sunday
            observed[d + timedelta(days=1)] = f"{name} (observed)"
    return observed


# ---------------------------------------------------------------------------
# Core checks
# ---------------------------------------------------------------------------

def holiday_name(d: date) -> Optional[str]:
    return ns_holidays(d.year).get(d)


def is_business_day(d: date) -> bool:
    if d.weekday() >= 5:  # Sat/Sun
        return False
    if holiday_name(d) is not None:
        return False
    return True


def next_business_day(d: date) -> date:
    out = d + timedelta(days=1)
    while not is_business_day(out):
        out += timedelta(days=1)
    return out


def prior_business_day(d: date) -> date:
    out = d - timedelta(days=1)
    while not is_business_day(out):
        out -= timedelta(days=1)
    return out


def validate_closing(d: date) -> dict:
    """Main entry point used by the voice agent."""
    if d.weekday() == 5:
        reason = "weekend (Saturday)"
    elif d.weekday() == 6:
        reason = "weekend (Sunday)"
    else:
        hname = holiday_name(d)
        reason = f"holiday: {hname}" if hname else None

    ok = reason is None
    result = {
        "ok": ok,
        "reason": reason,
        "date": d.isoformat(),
        "weekday": d.strftime("%A"),
        "alternatives": [],
    }
    if not ok:
        result["alternatives"] = [
            prior_business_day(d).isoformat(),
            next_business_day(d).isoformat(),
        ]
    return result


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        # Format: (date, expected_ok, label)
        (date(2026, 6, 20), False, "Saturday"),
        (date(2026, 6, 21), False, "Sunday"),
        (date(2026, 6, 22), True,  "Monday — good"),
        (date(2026, 7, 1),  False, "Canada Day (Wed)"),
        (date(2026, 7, 2),  True,  "Day after Canada Day"),
        (date(2026, 12, 25), False, "Christmas Day (Fri)"),
        (date(2026, 12, 28), False, "Boxing Day observed (Mon after weekend)"),
        (date(2026, 2, 16), False, "NS Heritage Day (3rd Mon Feb)"),
        (date(2026, 4, 3),  False, "Good Friday 2026"),
        (date(2026, 4, 6),  False, "Easter Monday 2026"),
        (date(2026, 5, 18), False, "Victoria Day 2026 (Mon before May 25)"),
        (date(2026, 8, 3),  False, "Natal Day (1st Mon Aug)"),
        (date(2026, 9, 7),  False, "Labour Day"),
        (date(2026, 9, 30), False, "Truth and Reconciliation"),
        (date(2026, 10, 12), False, "Thanksgiving"),
        (date(2026, 11, 11), False, "Remembrance Day"),
        (date(2026, 4, 17), True,  "Random Friday April 17"),
    ]
    print(f"{'Date':<12}  {'Expected':<8}  {'OK':<5}  {'Reason':<40}  {'Alts'}")
    print("-" * 110)
    fails = 0
    for d, expected, label in tests:
        r = validate_closing(d)
        ok = (r["ok"] == expected)
        if not ok:
            fails += 1
        flag = "PASS" if ok else "FAIL"
        alts = ", ".join(r["alternatives"]) if r["alternatives"] else "-"
        print(f"{d}  {str(expected):<8}  {str(r['ok']):<5}  {str(r['reason']):<40}  {alts}   [{flag}] {label}")
    print(f"\n{len(tests) - fails}/{len(tests)} passed")
