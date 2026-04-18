# ── Maji360 · scheduler/run_sync.py ───────────────────
import os
import sys
sys.path.insert(0, ".")

# ── Read all config from environment ──────────────────
DATABASE_URL        = os.environ.get("DATABASE_URL", "")
MWATER_CLIENT_KEY   = os.environ.get("MWATER_CLIENT_KEY", "")
MWATER_V3_BASE      = os.environ.get("MWATER_V3_BASE",
                      "https://api.mwater.co/v3")
ACCOUNTS_CLIENT_KEY = os.environ.get("ACCOUNTS_CLIENT_KEY", "")
ACCOUNTS_BASE       = os.environ.get("ACCOUNTS_BASE", "")

print("=" * 50)
print("  Maji360 — Scheduled Daily Sync")
print(f"  Database : {DATABASE_URL[:40]}...")
print(f"  mWater   : {MWATER_V3_BASE}")
print("=" * 50)

if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set in secrets.")
    sys.exit(1)

# ── Mock streamlit before any imports ─────────────────
import types

st_mock           = types.ModuleType("streamlit")
st_mock.cache_resource = lambda f: f

class EnvSecrets:
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

st_mock.secrets = EnvSecrets()
sys.modules["streamlit"] = st_mock

# ── Now import database and sync ───────────────────────
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.database import Base, WaterSystem
from core.sync import sync_system

# Create engine directly — bypass st.secrets
engine  = create_engine(DATABASE_URL, echo=False)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

systems = session.query(WaterSystem).filter_by(
    is_active=True
).all()
session.close()

print(f"\nActive systems found: {len(systems)}")

if not systems:
    print("No active systems to sync.")
    sys.exit(0)

for system in systems:
    print(f"\n{'─'*40}")
    print(f"Syncing: {system.name}")
    print(f"{'─'*40}")

    log     = []
    results = sync_system(system.id, log)

    for line in log:
        print(f"  {line}")

    print(f"\nResult: {results}")

print(f"\n{'='*50}")
print(f"  Sync complete — {len(systems)} system(s)")
print(f"{'='*50}")
