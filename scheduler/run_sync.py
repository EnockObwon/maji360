#!/usr/bin/env python3
# ══════════════════════════════════════════════════════════════
# Maji360 · scheduler/run_sync.py  v2.0
#
# Runs daily at 06:00 EAT (03:00 UTC) via GitHub Actions /
# cron / Render cron job.
#
# Changes from v1.5:
#   • Per-system error isolation: one system failing does not
#     abort the others.
#   • Passes triggered_by="scheduler" for SyncLog tracking.
#   • Exit code 1 only when ALL systems failed (not partial).
#   • Cleaner summary table at the end.
# ══════════════════════════════════════════════════════════════

import os
import sys
import time

sys.path.insert(0, ".")

# ── Read config from environment ──────────────────────────────
DATABASE_URL        = os.environ.get("DATABASE_URL",        "")
MWATER_CLIENT_KEY   = os.environ.get("MWATER_CLIENT_KEY",   "")
MWATER_V3_BASE      = os.environ.get(
    "MWATER_V3_BASE", "https://api.mwater.co/v3"
)
ACCOUNTS_CLIENT_KEY = os.environ.get("ACCOUNTS_CLIENT_KEY", "")
ACCOUNTS_BASE       = os.environ.get("ACCOUNTS_BASE",       "")

print("=" * 56)
print("  Maji360 — Scheduled Daily Sync")
print(f"  DB      : {DATABASE_URL[:45]}...")
print(f"  mWater  : {MWATER_V3_BASE}")
print("=" * 56)

if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set.")
    sys.exit(1)

# ── Minimal Streamlit mock so core/* imports cleanly ─────────
import types

st_mock                = types.ModuleType("streamlit")
st_mock.cache_resource = lambda f: f


class _EnvSecrets:
    _data = {
        "DATABASE_URL":        DATABASE_URL,
        "MWATER_CLIENT_KEY":   MWATER_CLIENT_KEY,
        "MWATER_V3_BASE":      MWATER_V3_BASE,
        "ACCOUNTS_CLIENT_KEY": ACCOUNTS_CLIENT_KEY,
        "ACCOUNTS_BASE":       ACCOUNTS_BASE,
    }

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __getitem__(self, key):
        val = self._data.get(key)
        if val is None:
            raise KeyError(key)
        return val

    def __contains__(self, key):
        return key in self._data


st_mock.secrets      = _EnvSecrets()
sys.modules["streamlit"] = st_mock

# ── Now safe to import project modules ────────────────────────
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base, WaterSystem
from core.sync     import sync_system

# ── Bootstrap DB ─────────────────────────────────────────────
engine  = create_engine(DATABASE_URL, echo=False)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# ── Load active systems ───────────────────────────────────────
session = Session()
systems = session.query(WaterSystem).filter_by(
    is_active=True
).order_by(WaterSystem.id).all()
session.close()

print(f"\nActive systems found: {len(systems)}")

if not systems:
    print("Nothing to sync.")
    sys.exit(0)

# ── Sync each system independently ───────────────────────────
summary       = []
failed_count  = 0
total_start   = time.time()

for system in systems:
    print(f"\n{'─' * 56}")
    print(f"  System : {system.name}  (id={system.id})")
    print(f"  Form   : {system.mwater_form_id or '⚠ NOT SET'}")
    print(f"  Group  : {getattr(system, 'mwater_group_id', None) or '⚠ NOT SET'}")
    print(f"{'─' * 56}")

    log     = []
    t_start = time.time()

    try:
        result = sync_system(
            system.id,
            log          = log,
            triggered_by = "scheduler",
        )
    except Exception as exc:
        result = {
            "system": system.name,
            "error":  str(exc),
        }

    duration = round(time.time() - t_start, 1)

    for line in log:
        print(f"  {line}")

    if "error" in result:
        status = "ERROR"
        failed_count += 1
    else:
        status = "OK"

    summary.append({
        "id":       system.id,
        "name":     system.name,
        "status":   status,
        "duration": duration,
        "result":   result,
    })

    print(f"\n  → {status} in {duration}s")

# ── Final summary ─────────────────────────────────────────────
total_duration = round(time.time() - total_start, 1)
print(f"\n{'=' * 56}")
print(f"  SYNC SUMMARY — {len(systems)} system(s) in {total_duration}s")
print(f"{'=' * 56}")
print(f"  {'System':<30} {'Status':<8} {'Time':>6}")
print(f"  {'─'*30} {'─'*8} {'─'*6}")

for s in summary:
    r   = s["result"]
    tme = f"{s['duration']}s"
    print(f"  {s['name']:<30} {s['status']:<8} {tme:>6}")
    if s["status"] == "OK":
        print(
            f"    readings+{r.get('new_pump',0)}"
            f"  customers+{r.get('new_customers',0)}"
            f"  bills+{r.get('new_bills',0)}"
            f"  payments+{r.get('new_payments',0)}"
        )
    else:
        print(f"    ✗ {r.get('error','unknown error')}")

print(f"{'=' * 56}")

# Exit non-zero only when ALL systems errored
if failed_count == len(systems):
    print(f"\nAll {len(systems)} system(s) failed.")
    sys.exit(1)
elif failed_count > 0:
    print(f"\n{failed_count}/{len(systems)} system(s) failed (partial sync).")
    sys.exit(0)   # partial success — don't trigger alert noise
else:
    print(f"\nAll systems synced successfully.")
    sys.exit(0)
