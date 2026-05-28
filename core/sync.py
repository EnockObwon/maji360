# Maji360 · core/sync.py  v2.0  — Multi-System Sync Engine
# Key changes from v1.5:
#   • All hardcoded GROUP_ID / WATER_SYSTEM_ID / FIELD_IDS /
#     KR_TO_METER removed from module level.
#   • Values are now loaded per-system from water_systems table
#     (mwater_group_id, mwater_water_system_id, mwater_field_ids,
#     meter_code_map) with safe fallbacks for Karungu (system 1).
#   • accounts_base / accounts_key can be overridden per-system.
#   • Every sync run is recorded in sync_logs.
#   • sync_system() return dict is unchanged — all callers safe.

import time
import requests
import json
from datetime import datetime, timezone
from collections import defaultdict
from sqlalchemy import text as sql_text

from core.database import (
    get_session, WaterSystem, DailyReading,
    Bill, Customer, NRWRecord,
)

# Try importing SyncLog; graceful fallback if migration not ─
# yet applied (scheduler will still work, just no log rows) ─
try:
    from core.database import SyncLog
    _SYNCLOG_AVAILABLE = True
except ImportError:
    _SYNCLOG_AVAILABLE = False


# Karungu (system 1) fallback constants
# Used ONLY when the corresponding column on water_systems
# is NULL — i.e., before the migration is run or for legacy
# data. New systems must have their values set in the DB.

_DEFAULT_GROUP_ID        = "718ce61fbf4f4742bd1018cabf90d1e8"
_DEFAULT_WATER_SYSTEM_ID = "b0e76a15-7047-4c5e-a986-e2bba550a4ff"

_DEFAULT_FIELD_IDS = {
    "pump_start": "7411292765fa4fb7a0217bfb001ab167",
    "pump_end":   "3456b8d568fe46b49dd0843a58cdc143",
    "tank_start": "f1c488eb7ec248a8a6d1208ba8f4b06a",
    "tank_end":   "9cae2fe4ea6b4940bb800253123b7565",
}

_DEFAULT_METER_CODE_MAP = {
    "KR1":  "659279453",
    "KR2":  "659279460",
    "KR3":  "659279501",
    "KR4":  "659279518",
    "KR5":  "659279477",
    "KR6":  "659280956",
    "KR7":  "659281005",
    "KR8":  "659281036",
    "KR9":  "659281050",
    "KR10": "659280891",
}

CONN_TYPE_MAP = {
    "Piped into public tap or basin": "PSP",
    "Piped into yard/plot":           "Private",
    None:                             "PSP",
}


def _infer_connection_type(name: str, wp_type: str = None) -> str:
    """
    Determine connection type from mWater water point type field
    (preferred) or by keyword-matching the customer name.

    Returns one of: "PSP" | "Private" | "School" | "Institution"
    These match the DHIS2 Uganda Water Sector reporting categories
    and the values expected by reports.py.
    """
    # mWater water point type field takes priority
    if wp_type and wp_type in CONN_TYPE_MAP:
        return CONN_TYPE_MAP[wp_type]

    n = name.lower()

    # Schools — separate DHIS2 category
    if any(w in n for w in [
        "school", "p/s", "nursery", "kindergarten"
    ]):
        return "School"

    # Other institutional — churches, health, commercial
    if any(w in n for w in [
        "church", "cou", "catholic", "mosque",
        "hospital", "clinic", "health centre",
        "lodge", "market", "trading centre"
    ]):
        return "Institution"

    # PSP — shared/public taps
    if any(w in n for w in [
        "psp", "public stand", "stand post",
        "public tap", "main public", "tap stand",
        "pump house"
    ]):
        return "PSP"

    # Private — individual yard/household connections
    if any(w in n for w in [
        "private", "yard tap", "residence",
        "house", "home"
    ]):
        return "Private"

    # Default
    return "PSP"


# Helpers

def get_mwater_config(system: WaterSystem = None) -> dict:
    """
    Build the API config dict.
    If `system` has non-null accounts_base / accounts_key,
    those override the global secrets — useful when the
    second system belongs to a different mWater organisation.
    """
    try:
        import streamlit as st
        base_cfg = {
            "client_key":    st.secrets["MWATER_CLIENT_KEY"],
            "v3_base":       st.secrets["MWATER_V3_BASE"],
            "accounts_key":  st.secrets["ACCOUNTS_CLIENT_KEY"],
            "accounts_base": st.secrets["ACCOUNTS_BASE"],
        }
    except Exception:
        import os
        base_cfg = {
            "client_key":    os.environ.get(
                "MWATER_CLIENT_KEY", ""
            ),
            "v3_base":       os.environ.get(
                "MWATER_V3_BASE",
                "https://api.mwater.co/v3",
            ),
            "accounts_key":  os.environ.get(
                "ACCOUNTS_CLIENT_KEY", ""
            ),
            "accounts_base": os.environ.get(
                "ACCOUNTS_BASE", ""
            ),
        }

    # Per-system overrides (only when set)
    if system:
        if getattr(system, "accounts_base", None):
            base_cfg["accounts_base"] = system.accounts_base
        if getattr(system, "accounts_key", None):
            base_cfg["accounts_key"] = system.accounts_key

    return base_cfg


def safe_float(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, dict):
        val = val.get("value")
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _get_system_config(system: WaterSystem) -> dict:
    """
    Extract per-system mWater identifiers with safe fallbacks.
    Returns a dict consumed by sync sub-functions.
    """
    group_id = (
        getattr(system, "mwater_group_id", None)
        or _DEFAULT_GROUP_ID
    )
    water_system_id = (
        getattr(system, "mwater_water_system_id", None)
        or _DEFAULT_WATER_SYSTEM_ID
    )
    field_ids = (
        getattr(system, "mwater_field_ids", None)
        or _DEFAULT_FIELD_IDS
    )
    # Use `is None` — an empty dict {} is intentional for
    # accounts-based systems (NYAKABALE). Using `or` would
    # silently replace it with Karungu defaults and block
    # the accounts API customer sync path.
    _raw_map       = getattr(system, "meter_code_map", None)
    meter_code_map = _DEFAULT_METER_CODE_MAP if _raw_map is None else _raw_map
    return {
        "group_id":        group_id,
        "water_system_id": water_system_id,
        "field_ids":       field_ids,
        "meter_code_map":  meter_code_map,
    }


def get_last_end_readings(
    system_id: int, session
) -> tuple[float | None, float | None]:
    """
    Most recent pump_end_reading and tank_end_reading
    stored in daily_readings for this system.
    """
    try:
        pump_row = session.execute(sql_text(
            "SELECT pump_end_reading "
            "FROM daily_readings "
            "WHERE system_id = :sid "
            "  AND pump_end_reading IS NOT NULL "
            "ORDER BY reading_date DESC LIMIT 1"
        ), {"sid": system_id}).fetchone()
        last_pump_end = float(pump_row[0]) if pump_row else None
    except Exception:
        last_pump_end = None

    try:
        tank_row = session.execute(sql_text(
            "SELECT tank_end_reading "
            "FROM daily_readings "
            "WHERE system_id = :sid "
            "  AND tank_end_reading IS NOT NULL "
            "ORDER BY reading_date DESC LIMIT 1"
        ), {"sid": system_id}).fetchone()
        last_tank_end = float(tank_row[0]) if tank_row else None
    except Exception:
        last_tank_end = None

    return last_pump_end, last_tank_end


def _write_sync_log(
    session,
    system_id:        int,
    triggered_by:     str,
    status:           str,
    results:          dict,
    duration_seconds: float,
    log_lines:        list,
    error_message:    str | None = None,
) -> None:
    """
    Persist a SyncLog row and update water_systems.last_synced_at.
    Silent on failure so a log error never breaks a sync run.
    """
    try:
        if _SYNCLOG_AVAILABLE:
            log_row = SyncLog(
                system_id        = system_id,
                synced_at        = datetime.now(timezone.utc),
                triggered_by     = triggered_by,
                status           = status,
                new_readings     = results.get("new_pump", 0)
                                 + results.get("new_tank", 0),
                new_customers    = results.get("new_customers", 0),
                new_bills        = results.get("new_bills", 0),
                new_payments     = results.get("new_payments", 0),
                new_expenses     = results.get("new_expenses", 0),
                duplicates       = results.get("duplicates", 0),
                error_message    = error_message,
                duration_seconds = duration_seconds,
                log_lines        = log_lines,
            )
            session.add(log_row)

        # Always stamp the system row regardless of SyncLog
        session.execute(sql_text("""
            UPDATE water_systems
            SET last_synced_at = :ts,
                sync_status    = :status
            WHERE id = :sid
        """), {
            "ts":     datetime.now(timezone.utc),
            "status": status,
            "sid":    system_id,
        })
        session.commit()
    except Exception:
        pass   # never let logging crash a sync


# Main entry point

def sync_system(
    system_id:    int,
    log:          list = None,
    triggered_by: str  = "manual",
) -> dict:
    """
    Sync one water system from mWater.

    Parameters
    ----------
    system_id    : row id in water_systems table
    log          : list to append progress strings to
    triggered_by : 'manual' | 'scheduler' | 'admin'

    Returns
    -------
    dict with keys: system, new_pump, new_tank,
                    new_customers, new_bills,
                    new_payments, new_expenses,
                    duplicates, synced_at, error (opt)
    """
    t_start = time.time()

    def log_msg(msg: str):
        if log is not None:
            log.append(msg)

    session = get_session()
    results = {}
    status  = "success"
    err_msg = None

    try:
        system = session.query(WaterSystem).filter_by(
            id=system_id
        ).first()

        if not system:
            session.close()
            return {"error": f"System id={system_id} not found"}

        system_name = system.name
        form_id     = system.mwater_form_id
        sys_cfg     = _get_system_config(system)
        cfg         = get_mwater_config(system)

        log_msg(f"{'─'*44}")
        log_msg(f"Syncing  : {system_name}  (id={system_id})")
        log_msg(f"Form ID  : {form_id}")
        log_msg(f"Group ID : {sys_cfg['group_id']}")
        log_msg(f"WS UUID  : {sys_cfg['water_system_id']}")
        log_msg(f"{'─'*44}")

        if not form_id:
            err_msg = "mwater_form_id is not set for this system"
            log_msg(f"✗ {err_msg}")
            _write_sync_log(
                session, system_id, triggered_by,
                "error", {}, 0.0, log or [], err_msg
            )
            session.close()
            return {"error": err_msg, "system": system_name}

        # Fetch all mWater responses 
        log_msg("Fetching mWater responses...")
        all_responses = []
        skip = 0

        while True:
            try:
                resp = requests.get(
                    f"{cfg['v3_base']}/responses",
                    params={
                        "client":   cfg["client_key"],
                        "selector": json.dumps(
                            {"form": form_id}
                        ),
                        "limit": 100,
                        "skip":  skip,
                    },
                    timeout=60,
                )
                if resp.status_code != 200:
                    log_msg(
                        f"  mWater API error: "
                        f"{resp.status_code} — "
                        f"{resp.text[:120]}"
                    )
                    break

                batch = [
                    r for r in resp.json()
                    if r.get("form") == form_id
                ]
                if not batch:
                    break

                all_responses.extend(batch)
                log_msg(
                    f"  Fetched {len(all_responses)} "
                    f"responses..."
                )
                if len(batch) < 100:
                    break
                skip += 100

            except Exception as e:
                log_msg(f"  Fetch error: {e}")
                break

        log_msg(f"Total responses : {len(all_responses)}")

        # ── Sort oldest-first (cumulative calc depends on order)
        def _submitted_dt(r):
            s = r.get("submittedOn", "")
            try:
                return datetime.fromisoformat(
                    s.replace("Z", "+00:00")
                ) if s else datetime.min.replace(
                    tzinfo=timezone.utc
                )
            except Exception:
                return datetime.min.replace(
                    tzinfo=timezone.utc
                )

        all_responses.sort(key=_submitted_dt)

        # Existing response IDs (skip duplicates) 
        # Check GLOBALLY across all systems, not just the
        # current one. When two systems share the same form,
        # each response belongs to exactly one system.
        # Filtering by system_id misses responses already
        # stored under a different system_id and causes a
        # unique constraint violation on mwater_response_id.
        existing_ids = set(
            row[0]
            for row in session.execute(sql_text(
                "SELECT mwater_response_id "
                "FROM daily_readings "
                "WHERE mwater_response_id IS NOT NULL"
            )).fetchall()
            if row[0]
        )

        # Cumulative baseline readings 
        last_pump_end, last_tank_end = \
            get_last_end_readings(system_id, session)
        log_msg(f"Last pump end   : {last_pump_end}")
        log_msg(f"Last tank end   : {last_tank_end}")

        # Field IDs for this system
        fids     = sys_cfg["field_ids"]
        pump_end_fid = fids.get(
            "pump_end", _DEFAULT_FIELD_IDS["pump_end"]
        )
        tank_end_fid = fids.get(
            "tank_end", _DEFAULT_FIELD_IDS["tank_end"]
        )

        # Parse and save new readings 
        new_pump   = 0
        new_tank   = 0
        duplicates = 0

        for r in all_responses:
            resp_id = r.get("_id", r.get("id", ""))
            if resp_id in existing_ids:
                duplicates += 1
                continue

            data = r.get("data", {})
            pe   = safe_float(data.get(pump_end_fid))
            te   = safe_float(data.get(tank_end_fid))

            submitted = r.get("submittedOn", "")
            try:
                reading_date = datetime.fromisoformat(
                    submitted.replace("Z", "+00:00")
                ) if submitted else datetime.now(timezone.utc)
            except Exception:
                reading_date = datetime.now(timezone.utc)

            # Cumulative pump volume 
            pumped = 0.0
            if pe is not None:
                if last_pump_end is not None:
                    diff = round(pe - last_pump_end, 2)
                    if diff > 0:
                        pumped = diff
                    elif diff < 0:
                        log_msg(
                            f"  ⚠ Pump meter went backwards "
                            f"({last_pump_end} → {pe}) — "
                            f"skipping volume."
                        )
                else:
                    log_msg(
                        f"  First pump baseline: {pe}"
                    )
                last_pump_end = pe

            # Cumulative tank volume 
            consumed = 0.0
            if te is not None:
                if last_tank_end is not None:
                    diff = round(te - last_tank_end, 2)
                    if diff > 0:
                        consumed = diff
                    elif diff < 0:
                        log_msg(
                            f"  ⚠ Tank meter went backwards "
                            f"({last_tank_end} → {te}) — "
                            f"skipping volume."
                        )
                else:
                    log_msg(
                        f"  First tank baseline: {te}"
                    )
                last_tank_end = te

            if pe is None and te is None:
                continue

            session.add(DailyReading(
                system_id          = system_id,
                reading_date       = reading_date,
                water_produced_m3  = pumped,
                water_consumed_m3  = consumed,
                water_sold_m3      = 0.0,
                pump_end_reading   = pe,
                tank_end_reading   = te,
                mwater_response_id = resp_id,
                synced_at          = datetime.now(timezone.utc),
            ))
            existing_ids.add(resp_id)

            if pumped   > 0: new_pump += 1
            if consumed > 0: new_tank += 1

        session.commit()
        log_msg(f"New pump readings : {new_pump}")
        log_msg(f"New tank readings : {new_tank}")
        log_msg(f"Duplicates skipped: {duplicates}")

        # Customers 
        log_msg("Syncing customers from mWater...")
        new_customers = sync_customers(
            system_id, system_name, form_id,
            session, cfg, sys_cfg, log,
        )
        log_msg(f"New customers     : {new_customers}")

        # Billing 
        log_msg("Syncing billing...")
        new_bills = sync_billing(
            system_id, session, cfg, sys_cfg, log
        )
        log_msg(f"New bills         : {new_bills}")

        # Payments
        log_msg("Syncing payments...")
        new_payments = sync_payments(
            system_id, session, cfg, sys_cfg, log
        )
        log_msg(f"New payments      : {new_payments}")

        # Expenses 
        log_msg("Syncing expenses...")
        new_expenses = sync_expenses(
            system_id, session, cfg, log
        )
        log_msg(f"New expenses      : {new_expenses}")

        # NRW recalculation 
        log_msg("Recalculating NRW...")
        recalculate_nrw(system_id, session)

        duration = round(time.time() - t_start, 1)
        log_msg(f"✓ Sync complete in {duration}s")

        results = {
            "system":        system_name,
            "new_pump":      new_pump,
            "new_tank":      new_tank,
            "new_customers": new_customers,
            "new_bills":     new_bills,
            "new_payments":  new_payments,
            "new_expenses":  new_expenses,
            "duplicates":    duplicates,
            "synced_at":     datetime.now(timezone.utc).isoformat(),
        }

        _write_sync_log(
            session, system_id, triggered_by,
            status, results, duration, log or [],
        )

    except Exception as e:
        duration = round(time.time() - t_start, 1)
        err_msg  = str(e)
        status   = "error"
        log_msg(f"✗ Sync error: {e}")
        results  = {
            "system":   getattr(system, "name", f"id={system_id}"),
            "error":    err_msg,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            _write_sync_log(
                session, system_id, triggered_by,
                status, results, duration, log or [], err_msg
            )
        except Exception:
            pass

    finally:
        try:
            session.close()
        except Exception:
            pass

    return results


# sync_customers

def sync_customers(
    system_id:   int,
    system_name: str,
    form_id:     str,
    session,
    cfg:         dict,
    sys_cfg:     dict,   # ← new: per-system identifiers
    log:         list,
) -> int:

    def log_msg(msg):
        if log is not None:
            log.append(msg)

    if not cfg.get("client_key") or not form_id:
        log_msg("  No mWater config — skipping customers")
        return 0

    # Per-system values (no module-level constants)
    group_id        = sys_cfg["group_id"]
    water_system_id = sys_cfg["water_system_id"]

    try:
        # Fetch water points for this group 
        all_wps = []
        skip    = 0
        while True:
            r = requests.get(
                f"{cfg['v3_base']}/entities/water_point",
                params={
                    "client":   cfg["client_key"],
                    "selector": json.dumps({
                        "_managed_by": f"group:{group_id}"
                    }),
                    "limit": 50,
                    "skip":  skip,
                },
                timeout=30,
            )
            if r.status_code != 200 or not r.text.strip():
                break
            batch = r.json()
            if not batch:
                break
            all_wps.extend(batch)
            if len(batch) < 50:
                break
            skip += 50

        # Filter to this specific water system
        wps_for_system = [
            wp for wp in all_wps
            if wp.get("water_system") == water_system_id
        ]

        log_msg(
            f"  Water points in group  : {len(all_wps)}"
        )
        log_msg(
            f"  Matching this system   : {len(wps_for_system)}"
        )

        existing_meters = set(
            row[0]
            for row in session.query(Customer.meter_no)
                              .filter_by(system_id=system_id).all()
            if row[0]
        )
        log_msg(
            f"  Already in Maji360     : {len(existing_meters)}"
        )

        # Build meter → account-number map
        meter_code_map   = sys_cfg["meter_code_map"]  # code → meter_no
        meter_to_account = {}  # meter_no → account_no (meter_code_map path)
        acc_name_to_code = {}  # name.lower() → accounts code (name-match path)

        if cfg.get("accounts_key") and cfg.get("accounts_base"):
            try:
                r2 = requests.get(
                    f"{cfg['accounts_base']}/customer_accounts",
                    params={"client": cfg["accounts_key"], "limit": 200},
                    timeout=15,
                )
                r3 = requests.get(
                    f"{cfg['accounts_base']}/customers",
                    params={"client": cfg["accounts_key"], "limit": 200},
                    timeout=15,
                )
                if r2.status_code == 200 and r3.status_code == 200:
                    mw_customers = {
                        c["_id"]: c.get("code", "")
                        for c in r3.json()
                    }
                    for ca in r2.json():
                        cust_id  = ca.get("customer", "")
                        kr_code  = mw_customers.get(cust_id, "")
                        acc_code = ca.get("code", "")
                        meter_no = meter_code_map.get(kr_code, "")
                        if meter_no and acc_code:
                            meter_to_account[meter_no] = acc_code

                    # Build name → accounts code map so water points
                    # without a meter_code_map entry can still be linked
                    # to billing transactions via customer name matching.
                    for c in r3.json():
                        name = (c.get("name") or "").lower().strip()
                        code = c.get("code", "")
                        if name and code:
                            acc_name_to_code[name] = code

                    log_msg(
                        f"  Accounts name index: "
                        f"{len(acc_name_to_code)} entries"
                    )
            except Exception as e:
                log_msg(f"  Accounts lookup error: {e}")

        new_count = 0
        for wp in wps_for_system:
            code = str(wp.get("code", ""))
            if not code or code in existing_meters:
                continue

            name = wp.get("name", f"Customer {code}")
            if isinstance(name, dict):
                name = name.get("en", str(name))

            coords = (
                wp.get("location", {})
                  .get("coordinates", [])
            )
            lon = coords[0] if len(coords) > 0 else None
            lat = coords[1] if len(coords) > 1 else None
            desc = wp.get("desc", "")

            # Priority for account_no:
            # 1. meter_to_account (meter_code_map path — Karungu)
            # 2. Name match with accounts API customer (NYAKABALE)
            #    Stores the accounts customer code so billing
            #    transactions can be matched via account_no lookup.
            # 3. Auto-generated fallback
            name_key   = name.lower().strip()
            matched_acc = (
                meter_to_account.get(code)
                or acc_name_to_code.get(name_key)
            )

            # When accounts API is configured (system has its own
            # accounting URL), skip water points that have no name
            # match. They will be inserted correctly by the accounts
            # API sync below with their proper account codes.
            # This prevents NYA-... placeholder accounts being created.
            if not matched_acc and                cfg.get("accounts_key") and cfg.get("accounts_base"):
                continue

            account_no = matched_acc or                 f"{system_name[:3].upper()}-{code}"

            wp_type         = wp.get("type_improved") or wp.get("type_")
            connection_type = _infer_connection_type(name, wp_type)

            session.add(Customer(
                system_id       = system_id,
                name            = name,
                account_no      = account_no,
                meter_no        = code,
                address         = desc,
                latitude        = lat,
                longitude       = lon,
                connection_type = connection_type,
                is_active       = True,
            ))
            existing_meters.add(code)
            new_count += 1
            log_msg(
                f"  ✓ {name} "
                f"(meter={code}, acc={account_no})"
            )

        session.commit()

        # Accounts API customer sync 
        # Used when meter_code_map is empty (e.g. NYAKABALE).
        # Pulls customers directly from the mWater accounts
        # system using their numeric IDs (10001, 10002...).
        # New connections added in mWater are picked up
        # automatically on the next sync — no map update needed.
        if not meter_code_map and \
           cfg.get("accounts_key") and cfg.get("accounts_base"):
            log_msg("  No meter_code_map — syncing from accounts API...")
            new_count += _sync_customers_from_accounts(
                system_id, session, cfg, log,
                water_system_id=sys_cfg["water_system_id"]
            )

        return new_count

    except Exception as e:
        log_msg(f"  Customer sync error: {e}")
        return 0


def _sync_customers_from_accounts(
    system_id:       int,
    session,
    cfg:             dict,
    log:             list,
    water_system_id: str = None,
) -> int:
    """
    Sync customers directly from the mWater accounts API.
    Used for systems like NYAKABALE where customers are
    managed in the accounts system with numeric IDs
    (10001, 10002...) rather than a meter_code_map.

    Filters to water_system_id so customers from other
    systems in the same organisation are excluded.
    """
    def log_msg(msg):
        if log is not None:
            log.append(msg)

    try:
        # No water_system filter — the accounts_base URL is
        # already system-specific (e.g. accounting:528 for NYAKABALE).
        # All customers returned belong to this system.
        r = requests.get(
            f"{cfg['accounts_base']}/customers",
            params={"client": cfg["accounts_key"], "limit": 200},
            timeout=15,
        )
        if r.status_code != 200:
            log_msg(f"  Accounts customers error: {r.status_code}")
            return 0

        acc_customers = r.json()
        log_msg(f"  Accounts API customers: {len(acc_customers)}")
        log_msg(f"  Customers to process  : {len(acc_customers)}")

        # Existing customers for this system (by account_no)
        existing_accounts = set(
            row[0]
            for row in session.query(Customer.account_no)
                              .filter_by(system_id=system_id).all()
            if row[0]
        )

        new_count = 0
        for c in acc_customers:
            code = str(c.get("code", "")).strip()
            name = (c.get("name") or f"Customer {code}").strip()
            if not code or code in existing_accounts:
                continue

            # account_no = accounts API code (e.g. "10001")
            # meter_no   = same, used for billing lookup
            connection_type = _infer_connection_type(name)

            session.add(Customer(
                system_id       = system_id,
                name            = name,
                account_no      = code,
                meter_no        = code,
                connection_type = connection_type,
                is_active       = True,
            ))
            existing_accounts.add(code)
            new_count += 1
            log_msg(f"  ✓ {name} (acc={code})")

        session.commit()
        log_msg(f"  New accounts customers: {new_count}")
        return new_count

    except Exception as e:
        log_msg(f"  Accounts customer sync error: {e}")
        return 0


# sync_billing

def sync_billing(
    system_id: int,
    session,
    cfg:       dict,
    sys_cfg:   dict,   # ← new
    log:       list,
) -> int:

    def log_msg(msg):
        if log is not None:
            log.append(msg)

    if not cfg.get("accounts_key") or not cfg.get("accounts_base"):
        log_msg("  Accounts API not configured — skipping")
        return 0

    meter_code_map = sys_cfg["meter_code_map"]

    try:
        all_txns = _fetch_all_transactions(
            cfg["accounts_base"], cfg["accounts_key"]
        )

        r2 = requests.get(
            f"{cfg['accounts_base']}/customer_accounts",
            params={"client": cfg["accounts_key"], "limit": 50},
            timeout=15,
        )
        r3 = requests.get(
            f"{cfg['accounts_base']}/customers",
            params={"client": cfg["accounts_key"], "limit": 50},
            timeout=15,
        )
        mw_customers = {
            c["_id"]: c.get("code")
            for c in (r3.json() if r3.status_code == 200 else [])
        }
        acc_to_kr = {
            ca["_id"]: mw_customers.get(ca.get("customer", ""), "")
            for ca in (r2.json() if r2.status_code == 200 else [])
        }

        billing_txns = [
            t for t in all_txns
            if t.get("meter_volume") is not None
        ]
        payment_txns = [
            t for t in all_txns
            if t.get("meter_volume") is None
            and t.get("customer_account")
        ]

        # Build total-paid-per-meter for payment allocation.
        # For systems with meter_code_map (Karungu): use the
        # mapped meter serial number as the key.
        # For systems without (NYAKABALE): use the accounts
        # customer code directly — it matches meter_no/account_no.
        cust_paid: dict[str, float] = defaultdict(float)
        for t in payment_txns:
            acc     = t.get("customer_account", "")
            kr_code = acc_to_kr.get(acc, "")
            meter   = meter_code_map.get(kr_code) or kr_code
            if meter:
                cust_paid[meter] += t.get("amount", 0)

        new_bills = 0
        for t in billing_txns:
            cust_acc_id = t.get("customer_account", "")
            kr_code     = acc_to_kr.get(cust_acc_id, "")

            # Look up customer — meter_code_map path first
            # (Karungu), then direct account_no fallback (NYAKABALE)
            meter_no = meter_code_map.get(kr_code)
            customer = None
            if meter_no:
                customer = session.query(Customer).filter_by(
                    system_id=system_id, meter_no=meter_no
                ).first()
            if not customer and kr_code:
                customer = session.query(Customer).filter_by(
                    system_id=system_id, account_no=kr_code
                ).first()
            if not customer:
                log_msg(
                    f"  ⚠ Unmatched billing txn: "
                    f"acc={cust_acc_id} "
                    f"code={kr_code} "
                    f"amount={t.get('amount',0)}"
                )
                continue

            date_str   = t.get("date", "")
            bill_month = date_str[:7] if date_str else ""
            units_m3   = float(t.get("meter_volume", 0))
            amount     = float(t.get("amount", 0))

            existing = session.query(Bill).filter_by(
                system_id   = system_id,
                customer_id = customer.id,
                bill_month  = bill_month,
            ).first()

            if not existing:
                session.add(Bill(
                    system_id   = system_id,
                    customer_id = customer.id,
                    bill_month  = bill_month,
                    units_m3    = units_m3,
                    amount      = amount,
                    amount_paid = 0.0,
                    is_paid     = False,
                    sms_sent    = False,
                ))
                new_bills += 1
            else:
                # Update if mWater has a different amount —
                # catches corrections made in the accounts portal.
                # Reset amount_paid proportionally if billed changed.
                if existing.amount != amount or                    existing.units_m3 != units_m3:
                    old_amount = existing.amount or 0
                    old_paid   = existing.amount_paid or 0
                    # Scale paid amount to new bill amount
                    if old_amount > 0 and old_paid > 0:
                        ratio = min(old_paid / old_amount, 1.0)
                        existing.amount_paid = round(
                            amount * ratio, 0
                        )
                    existing.amount   = amount
                    existing.units_m3 = units_m3
                    existing.is_paid  = (
                        existing.amount_paid >= amount
                    )
                    log_msg(
                        f"  ↻ Updated bill {bill_month} "
                        f"for {customer.account_no}: "
                        f"{old_amount} → {amount}"
                    )

        session.commit()
        log_msg(f"  New bills added: {new_bills}")

        # Allocate payments across bills
        # Uses the payments TABLE (all sources: mWater-synced
        # AND manually recorded in the app). This prevents
        # manual payments being overwritten on the next sync.
        log_msg("  Recalculating payment allocation...")

        try:
            pay_rows = session.execute(sql_text(
                "SELECT customer_id, SUM(amount) "
                "FROM payments "
                "WHERE system_id = :sid "
                "GROUP BY customer_id"
            ), {"sid": system_id}).fetchall()
            db_paid = {row[0]: float(row[1] or 0) for row in pay_rows}
        except Exception:
            db_paid = {}

        updated   = 0
        all_custs = session.query(Customer).filter_by(
            system_id=system_id
        ).all()

        for customer in all_custs:
            total_paid = db_paid.get(customer.id, 0.0)
            if total_paid == 0:
                continue

            cust_bills = session.query(Bill).filter_by(
                system_id=system_id, customer_id=customer.id
            ).order_by(Bill.bill_month).all()

            remaining = total_paid
            for bill in cust_bills:
                bill_amount = bill.amount or 0
                if remaining >= bill_amount:
                    new_paid, new_flag = bill_amount, True
                    remaining -= bill_amount
                elif remaining > 0:
                    new_paid, new_flag = remaining, False
                    remaining = 0
                else:
                    new_paid, new_flag = 0.0, False

                if bill.amount_paid != new_paid \
                   or bill.is_paid != new_flag:
                    bill.amount_paid = new_paid
                    bill.is_paid     = new_flag
                    updated += 1

        session.commit()
        log_msg(f"  Payment records updated: {updated}")
        return new_bills

    except Exception as e:
        log_msg(f"  Billing sync error: {e}")
        return 0


# sync_payments

def sync_payments(
    system_id: int,
    session,
    cfg:       dict,
    sys_cfg:   dict,   # ← new
    log:       list,
) -> int:

    def log_msg(msg):
        if log is not None:
            log.append(msg)

    if not cfg.get("accounts_key") or not cfg.get("accounts_base"):
        return 0

    meter_code_map = sys_cfg["meter_code_map"]

    try:
        all_txns = _fetch_all_transactions(
            cfg["accounts_base"], cfg["accounts_key"]
        )

        r2 = requests.get(
            f"{cfg['accounts_base']}/customer_accounts",
            params={"client": cfg["accounts_key"], "limit": 50},
            timeout=15,
        )
        r3 = requests.get(
            f"{cfg['accounts_base']}/customers",
            params={"client": cfg["accounts_key"], "limit": 50},
            timeout=15,
        )
        mw_customers = {
            c["_id"]: c.get("code")
            for c in (r3.json() if r3.status_code == 200 else [])
        }
        acc_to_kr = {
            ca["_id"]: mw_customers.get(ca.get("customer", ""), "")
            for ca in (r2.json() if r2.status_code == 200 else [])
        }

        payment_txns = [
            t for t in all_txns
            if t.get("meter_volume") is None
            and t.get("customer_account")
        ]

        existing_payments: set[tuple] = set()
        try:
            result = session.execute(sql_text(
                "SELECT customer_id, amount, "
                "DATE(paid_at) FROM payments "
                "WHERE system_id = :sid"
            ), {"sid": system_id})
            existing_payments = {
                (row[0], float(row[1]), str(row[2])[:10])
                for row in result
            }
        except Exception:
            pass

        new_payments = 0
        for t in payment_txns:
            acc     = t.get("customer_account", "")
            kr_code = acc_to_kr.get(acc, "")
            meter   = meter_code_map.get(kr_code) or kr_code
            if not meter:
                continue

            customer = (
                session.query(Customer).filter_by(
                    system_id=system_id, meter_no=meter
                ).first()
                or session.query(Customer).filter_by(
                    system_id=system_id, account_no=meter
                ).first()
            )
            if not customer:
                continue

            date_str = t.get("date", "")
            amount   = float(t.get("amount", 0))
            notes    = t.get("notes", "") or ""

            if not date_str or amount <= 0:
                continue

            date_only = date_str[:10]
            key       = (customer.id, amount, date_only)
            if key in existing_payments:
                continue

            try:
                session.execute(sql_text("""
                    INSERT INTO payments
                        (system_id, customer_id, amount,
                         payment_method, notes, paid_at, status)
                    VALUES
                        (:system_id, :customer_id, :amount,
                         :method, :notes,
                         :paid_at, 'completed')
                """), {
                    "system_id":   system_id,
                    "customer_id": customer.id,
                    "amount":      amount,
                    "method":      "Cash",
                    "notes":       notes,
                    "paid_at":     f"{date_only}T00:00:00+00:00",
                })
                existing_payments.add(key)
                new_payments += 1
            except Exception as e:
                log_msg(f"  Payment insert error: {e}")

        session.commit()
        log_msg(f"  New payments synced: {new_payments}")
        return new_payments

    except Exception as e:
        log_msg(f"  Payment sync error: {e}")
        return 0


# sync_expenses  (no per-system changes needed here yet)

def sync_expenses(
    system_id: int,
    session,
    cfg:       dict,
    log:       list,
) -> int:

    def log_msg(msg):
        if log is not None:
            log.append(msg)

    if not cfg.get("accounts_key") or not cfg.get("accounts_base"):
        log_msg("  Accounts API not configured — skipping expenses")
        return 0

    CASH_ACCOUNT  = "302bafeccb9d4cb0ae442cffb833a64c"
    ACCOUNT_NAMES = {
        "998ebd77689a4bd388af840c4ca860b4": "Office Expenses",
        "eca51b9feeab4cb79c77c9445585044d": "Operating Expenses",
        "11fe4eb898c749fe9e1dadae10933f30": "Salaries and Wages",
    }

    try:
        all_txns = _fetch_all_transactions(
            cfg["accounts_base"], cfg["accounts_key"]
        )
        expense_txns = [
            t for t in all_txns
            if t.get("from_account") == CASH_ACCOUNT
            and not t.get("customer_account")
            and not t.get("meter_volume")
        ]
        log_msg(
            f"  Expense transactions: {len(expense_txns)}"
        )

        existing: set[str] = set()
        try:
            result = session.execute(sql_text(
                "SELECT mwater_id FROM expenses "
                "WHERE system_id = :sid "
                "  AND mwater_id IS NOT NULL"
            ), {"sid": system_id})
            existing = {row[0] for row in result}
        except Exception:
            pass

        new_expenses = 0
        for t in expense_txns:
            mwater_id = t.get("_id", "")
            if mwater_id in existing:
                continue
            to_acc   = t.get("to_account", "")
            category = ACCOUNT_NAMES.get(to_acc, "Other")
            date_str = t.get("date", "")
            month    = date_str[:7] if date_str else ""
            try:
                session.execute(sql_text("""
                    INSERT INTO expenses
                        (system_id, date, month, amount,
                         category, notes, mwater_id)
                    VALUES
                        (:system_id, :date, :month, :amount,
                         :category, :notes, :mwater_id)
                    ON CONFLICT (mwater_id) DO NOTHING
                """), {
                    "system_id": system_id,
                    "date":      date_str,
                    "month":     month,
                    "amount":    float(t.get("amount", 0)),
                    "category":  category,
                    "notes":     t.get("notes", ""),
                    "mwater_id": mwater_id,
                })
                new_expenses += 1
                existing.add(mwater_id)
            except Exception as e:
                log_msg(f"  Expense insert error: {e}")

        session.commit()
        log_msg(f"  New expenses: {new_expenses}")
        return new_expenses

    except Exception as e:
        log_msg(f"  Expense sync error: {e}")
        return 0


# recalculate_nrw  (unchanged logic, kept here for completeness)

def recalculate_nrw(system_id: int, session) -> None:
    readings = session.query(DailyReading).filter_by(
        system_id=system_id
    ).all()

    monthly: dict[str, dict] = defaultdict(
        lambda: {"pumped": 0.0, "consumed": 0.0}
    )
    for r in readings:
        month = r.reading_date.strftime("%Y-%m")
        if r.water_produced_m3 and r.water_produced_m3 > 0:
            monthly[month]["pumped"]   += r.water_produced_m3
        if r.water_consumed_m3 and r.water_consumed_m3 > 0:
            monthly[month]["consumed"] += r.water_consumed_m3

    for month, data in monthly.items():
        pumped   = round(data["pumped"],   2)
        consumed = round(data["consumed"], 2)
        nrw_m3   = round(pumped - consumed, 2)
        nrw_pct  = round(
            (nrw_m3 / pumped) * 100, 1
        ) if pumped > 0 else 0.0

        existing = session.query(NRWRecord).filter_by(
            system_id=system_id, month=month
        ).first()

        if existing:
            existing.water_produced = pumped
            existing.water_billed   = consumed
            existing.nrw_m3         = nrw_m3
            existing.nrw_percent    = nrw_pct
        else:
            session.add(NRWRecord(
                system_id      = system_id,
                month          = month,
                water_produced = pumped,
                water_billed   = consumed,
                nrw_m3         = nrw_m3,
                nrw_percent    = nrw_pct,
            ))

    session.commit()


# Private helper: paginated transaction fetch
# (de-duplicates the identical loop in billing/payments/expenses)

def _fetch_all_transactions(
    accounts_base: str, accounts_key: str
) -> list[dict]:
    """
    Fetch all transactions with pagination.
    Uses limit=200 (mWater max) to minimise
    round-trips and reduce risk of partial fetches.
    """
    all_txns: list[dict] = []
    skip  = 0
    limit = 200
    while True:
        r = requests.get(
            f"{accounts_base}/transactions",
            params={
                "client": accounts_key,
                "limit":  limit,
                "skip":   skip,
            },
            timeout=60,
        )
        if r.status_code != 200 or not r.text.strip():
            break
        batch = r.json()
        if not batch:
            break
        all_txns.extend(batch)
        if len(batch) < limit:
            break
        skip += limit
    return all_txns
