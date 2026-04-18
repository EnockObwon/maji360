# ── Maji360 · scheduler/run_sync.py ───────────────────
# Runs daily via GitHub Actions
# Syncs all active water systems from mWater to Supabase

import os
import sys
sys.path.insert(0, ".")

# ── Mock streamlit secrets using environment variables ─
class EnvSecrets:
    def get(self, key, default=None):
        return os.environ.get(key, default)
    def __getitem__(self, key):
        val = os.environ.get(key)
        if val is None:
            raise KeyError(key)
        return val
    def __contains__(self, key):
        return key in os.environ

# Patch before any streamlit imports
import types
import unittest.mock as mock

# Create a minimal streamlit mock
st_mock = types.ModuleType("streamlit")
st_mock.secrets = EnvSecrets()
st_mock.cache_resource = lambda f: f
sys.modules["streamlit"] = st_mock

# Now import our modules
from core.database import get_session, WaterSystem
from core.sync import sync_system

print("=" * 50)
print("  Maji360 — Scheduled Daily Sync")
print(f"  Database: {os.environ.get('DATABASE_URL','')[:40]}...")
print("=" * 50)

session = get_session()
systems = session.query(WaterSystem).filter_by(
    is_active=True
).all()
session.close()

print(f"\nActive systems found: {len(systems)}")

if not systems:
    print("No active systems to sync.")
    sys.exit(0)

all_results = []
for system in systems:
    print(f"\n{'─'*40}")
    print(f"Syncing: {system.name}")
    print(f"{'─'*40}")

    log     = []
    results = sync_system(system.id, log)

    for line in log:
        print(f"  {line}")

    all_results.append(results)
    print(f"\nResult: {results}")

print(f"\n{'='*50}")
print(f"  Sync complete — {len(systems)} system(s) synced")
print(f"{'='*50}")
