# Maji360 · core/sync.py  v2.3  — Multi-System Sync Engine
# Changes from v2.2:
#   • Auto-update meter_code_map: when a new water point is
#     found that isn't in the map, its KR code and meter serial
#     are added to water_systems.meter_code_map automatically.
#     No more manual SQL updates when new customers are added.

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

try:
    from core.database import SyncLog
    _SYNCLOG_AVAILABLE = True
except ImportError:
    _SYNCLOG_AVAILABLE = False


# Karungu (system 1) fallback constants 

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
    "KR11": "659281139",  # Komakech Comas
    "KR12": "659281153",  # Daniel Abetegeka
    "KR13": "659281160",  # Segawa Williams
    "KR14": "659281218",  # Kimono Lois
}

CONN_TYPE_MAP = {
    "Piped into public tap or basin": "PSP",
    "Piped into yard/plot":           "Private",
    None:                             "PSP",
}


def _infer_connection_type(name: str, wp_type: str = None) -> str:
    if wp_type and wp_type in CONN_TYPE_MAP:
        return CONN_TYPE_MAP[wp_type]
    n = name.lower()
    if any(w in n for w in ["school", "p/s", "nursery", "kindergarten"]):
        return "School"
    if any(w in n for w in [
        "church", "cou", "catholic", "mosque", "hospital",
        "clinic", "health centre", "lodge", "market", "trading centre"
    ]):
        return "Institution"
    if any(w in n for w in [
        "psp", "public stand", "stand post", "public tap",
        "main public", "tap stand", "pump house"
    ]):
        return "PSP"
    if any(w in n for w in ["private", "yard tap", "residence", "house", "home"]):
        return "Private"
    return "PSP"


# Config helpers 

def get_mwater_config(system: WaterSystem = None) -> dict:
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
            "client_key":    os.environ.get("MWATER_CLIENT_KEY", ""),
            "v3_base":       os.environ.get("MWATER_V3_BASE", "https://api.mwater.co/v3"),
            "accounts_key":  os.environ.get("ACCOUNTS_CLIENT_KEY", ""),
            "accounts_base": os.environ.get("ACCOUNTS_BASE", ""),
        }
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
    group_id        = getattr(system, "mwater_group_id", None)        or _DEFAULT_GROUP_ID
    water_system_id = getattr(system, "mwater_water_system_id", None) or _DEFAULT_WATER_SYSTEM_ID
    field_ids       = getattr(system, "mwater_field_ids", None)        or _DEFAULT_FIELD_IDS
    _raw_map        = getattr(system, "meter_code_map", None)
    meter_code_map  = _DEFAULT_METER_CODE_MAP if _raw_map is None else _raw_map
    return {
        "group_id":        group_id,
        "water_system_id": water_system_id,
        "field_ids":       field_ids,
        "meter_code_map":  meter_code_map,
    }


def get_last_end_readings(system_id: int, session) -> tuple[float | None, float | None]:
    try:
        pump_row = session.execute(sql_text(
            "SELECT pump_end_reading FROM daily_readings "
            "WHERE system_id = :sid AND pump_end_reading IS NOT NULL "
            "ORDER BY reading_date DESC LIMIT 1"
        ), {"sid": system_id}).fetchone()
        last_pump_end = float(pump_row[0]) if pump_row else None
    except Exception:
        last_pump_end = None
    try:
        tank_row = session.execute(sql_text(
            "SELECT tank_end_reading FROM daily_readings "
            "WHERE system_id = :sid AND tank_end_reading IS NOT NULL "
            "ORDER BY reading_date DESC LIMIT 1"
        ), {"sid": system_id}).fetchone()
        last_tank_end = float(tank_row[0]) if tank_row else None
    except Exception:
        last_tank_end = None
    return last_pump_end, last_tank_end


def _write_sync_log(session, system_id, triggered_by, status,
                    results, duration_seconds, log_lines, error_message=None):
    try:
        if _SYNCLOG_AVAILABLE:
            session.add(SyncLog(
                system_id        = system_id,
                synced_at        = datetime.now(timezone.utc),
                triggered_by     = triggered_by,
                status           = status,
                new_readings     = results.get("new_pump", 0) + results.get("new_tank", 0),
                new_customers    = results.get("new_customers", 0),
                new_bills        = results.get("new_bills", 0),
                new_payments     = results.get("new_payments", 0),
                new_expenses     = results.get("new_expenses", 0),
                duplicates       = results.get("duplicates", 0),
                error_message    = error_message,
                duration_seconds = duration_seconds,
                log_lines        = log_lines,
            ))
        session.execute(sql_text("""
            UPDATE water_systems
            SET last_synced_at = :ts, sync_status = :status
            WHERE id = :sid
        """), {"ts": datetime.now(timezone.utc), "status": status, "sid": system_id})
        session.commit()
    except Exception:
        pass


# Main entry point 

def sync_system(system_id: int, log: list = None, triggered_by: str = "manual") -> dict:
    t_start = time.time()

    def log_msg(msg: str):
        if log is not None:
            log.append(msg)

    session = get_session()
    results = {}
    status  = "success"
    err_msg = None

    try:
        system = session.query(WaterSystem).filter_by(id=system_id).first()
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
            _write_sync_log(session, system_id, triggered_by, "error", {}, 0.0, log or [], err_msg)
            session.close()
            return {"error": err_msg, "system": system_name}

        # Fetch mWater responses 
        log_msg("Fetching mWater responses...")
        all_responses = []
        skip = 0
        while True:
            try:
                resp = requests.get(
                    f"{cfg['v3_base']}/responses",
                    params={
                        "client":   cfg["client_key"],
                        "selector": json.dumps({"form": form_id}),
                        "limit": 100, "skip": skip,
                    },
                    timeout=60,
                )
                if resp.status_code != 200:
                    log_msg(f"  mWater API error: {resp.status_code} — {resp.text[:120]}")
                    break
                batch = [r for r in resp.json() if r.get("form") == form_id]
                if not batch:
                    break
                all_responses.extend(batch)
                log_msg(f"  Fetched {len(all_responses)} responses...")
                if len(batch) < 100:
                    break
                skip += 100
            except Exception as e:
                log_msg(f"  Fetch error: {e}")
                break

        log_msg(f"Total responses : {len(all_responses)}")

        def _submitted_dt(r):
            s = r.get("submittedOn", "")
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00")) if s \
                    else datetime.min.replace(tzinfo=timezone.utc)
            except Exception:
                return datetime.min.replace(tzinfo=timezone.utc)

        all_responses.sort(key=_submitted_dt)

        existing_ids = set(
            row[0]
            for row in session.execute(sql_text(
                "SELECT mwater_response_id FROM daily_readings "
                "WHERE mwater_response_id IS NOT NULL"
            )).fetchall()
            if row[0]
        )

        last_pump_end, last_tank_end = get_last_end_readings(system_id, session)
        log_msg(f"Last pump end   : {last_pump_end}")
        log_msg(f"Last tank end   : {last_tank_end}")

        fids         = sys_cfg["field_ids"]
        pump_end_fid = fids.get("pump_end", _DEFAULT_FIELD_IDS["pump_end"])
        tank_end_fid = fids.get("tank_end", _DEFAULT_FIELD_IDS["tank_end"])

        new_pump = new_tank = duplicates = 0

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

            pumped = 0.0
            if pe is not None:
                if last_pump_end is not None:
                    diff = round(pe - last_pump_end, 2)
                    if diff > 0:
                        pumped = diff
                    elif diff < 0:
                        log_msg(f"  ⚠ Pump meter went backwards ({last_pump_end} → {pe}) — skipping.")
                else:
                    log_msg(f"  First pump baseline: {pe}")
                last_pump_end = pe

            consumed = 0.0
            if te is not None:
                if last_tank_end is not None:
                    diff = round(te - last_tank_end, 2)
                    if diff > 0:
                        consumed = diff
                    elif diff < 0:
                        log_msg(f"  ⚠ Tank meter went backwards ({last_tank_end} → {te}) — skipping.")
                else:
                    log_msg(f"  First tank baseline: {te}")
                last_tank_end = te

            if pe is None and te is None:
                continue

            session.add(DailyReading(
                system_id=system_id, reading_date=reading_date,
                water_produced_m3=pumped, water_consumed_m3=consumed,
                water_sold_m3=0.0, pump_end_reading=pe, tank_end_reading=te,
                mwater_response_id=resp_id, synced_at=datetime.now(timezone.utc),
            ))
            existing_ids.add(resp_id)
            if pumped   > 0: new_pump += 1
            if consumed > 0: new_tank += 1

        session.commit()
        log_msg(f"New pump readings : {new_pump}")
        log_msg(f"New tank readings : {new_tank}")
        log_msg(f"Duplicates skipped: {duplicates}")

        log_msg("Syncing customers from mWater...")
        new_customers = sync_customers(system_id, system_name, form_id, session, cfg, sys_cfg, log)
        log_msg(f"New customers     : {new_customers}")

        log_msg("Syncing billing...")
        new_bills = sync_billing(system_id, session, cfg, sys_cfg, log)
        log_msg(f"New bills         : {new_bills}")

        log_msg("Syncing payments...")
        new_payments = sync_payments(system_id, session, cfg, sys_cfg, log)
        log_msg(f"New payments      : {new_payments}")

        # Re-run allocation after payments so bills created in this
        # same run are correctly allocated without needing a second sync.
        if new_payments > 0:
            log_msg("Re-allocating after new payments...")
            updated = reallocate_payments(system_id, session, log, commit=True)
            log_msg(f"  Payment records updated: {updated}")

        log_msg("Syncing expenses...")
        new_expenses = sync_expenses(system_id, session, cfg, log)
        log_msg(f"New expenses      : {new_expenses}")

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
        _write_sync_log(session, system_id, triggered_by, status, results, duration, log or [])

    except Exception as e:
        duration = round(time.time() - t_start, 1)
        err_msg  = str(e)
        status   = "error"
        log_msg(f"✗ Sync error: {e}")
        results  = {
            "system":    getattr(system, "name", f"id={system_id}"),
            "error":     err_msg,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            _write_sync_log(session, system_id, triggered_by, status, results, duration, log or [], err_msg)
        except Exception:
            pass

    finally:
        try:
            session.close()
        except Exception:
            pass

    return results


# sync_customers 

def sync_customers(system_id, system_name, form_id, session, cfg, sys_cfg, log) -> int:

    def log_msg(msg):
        if log is not None:
            log.append(msg)

    if not cfg.get("client_key") or not form_id:
        log_msg("  No mWater config — skipping customers")
        return 0

    group_id        = sys_cfg["group_id"]
    water_system_id = sys_cfg["water_system_id"]

    try:
        all_wps = []
        skip    = 0
        while True:
            r = requests.get(
                f"{cfg['v3_base']}/entities/water_point",
                params={
                    "client":   cfg["client_key"],
                    "selector": json.dumps({"_managed_by": f"group:{group_id}"}),
                    "limit": 50, "skip": skip,
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

        wps_for_system = [wp for wp in all_wps if wp.get("water_system") == water_system_id]
        log_msg(f"  Water points in group  : {len(all_wps)}")
        log_msg(f"  Matching this system   : {len(wps_for_system)}")

        existing_meters = set(
            row[0] for row in session.query(Customer.meter_no)
                                     .filter_by(system_id=system_id).all()
            if row[0]
        )
        log_msg(f"  Already in Maji360     : {len(existing_meters)}")

        meter_code_map   = sys_cfg["meter_code_map"]
        meter_to_account = {}
        acc_name_to_code = {}
        r2_data = []
        r3_data = []

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
                    r3_data = r3.json()
                    r2_data = r2.json()

                    mw_customers = {c["_id"]: c.get("code", "") for c in r3_data}

                    for ca in r2_data:
                        cust_id  = ca.get("customer", "")
                        kr_code  = mw_customers.get(cust_id, "")
                        acc_code = ca.get("code", "")
                        meter_no = meter_code_map.get(kr_code, "")
                        if meter_no and acc_code:
                            meter_to_account[meter_no] = acc_code

                    # Build name → 433xxx account code (not KR code)
                    cust_id_to_name = {
                        c["_id"]: (c.get("name") or "").lower().strip()
                        for c in r3_data
                    }
                    for ca in r2_data:
                        cust_id  = ca.get("customer", "")
                        acc_code = ca.get("code", "")
                        name     = cust_id_to_name.get(cust_id, "")
                        if name and acc_code:
                            acc_name_to_code[name] = acc_code

                    log_msg(f"  Accounts name index: {len(acc_name_to_code)} entries")

                    # Auto-update meter_code_map 
                    # If a water point's KR code is not yet in
                    # meter_code_map, detect it via name match and add
                    # it to water_systems.meter_code_map automatically.
                    # No manual SQL needed when new customers are added.
                    new_map_entries = {}
                    existing_meter_serials = set(meter_code_map.values())

                    for wp in wps_for_system:
                        wp_code     = str(wp.get("code", ""))
                        wp_name     = wp.get("name", "")
                        if isinstance(wp_name, dict):
                            wp_name = wp_name.get("en", "")
                        wp_name_key = (wp_name or "").lower().strip()

                        # Skip if already in the map
                        if wp_code in existing_meter_serials:
                            continue

                        # Find matching KR code via name in accounts
                        for c in r3_data:
                            c_name = (c.get("name") or "").lower().strip()
                            kr     = c.get("code", "")
                            if c_name == wp_name_key and kr and kr not in meter_code_map:
                                new_map_entries[kr] = wp_code
                                log_msg(f"  📍 Auto-mapping {kr} → {wp_code} ({wp_name})")
                                break

                    if new_map_entries:
                        try:
                            merged = {**meter_code_map, **new_map_entries}
                            session.execute(sql_text(
                                "UPDATE water_systems "
                                "SET meter_code_map = :m::jsonb "
                                "WHERE id = :sid"
                            ), {"m": json.dumps(merged), "sid": system_id})
                            session.commit()
                            # Update local copies so billing sync
                            # uses the new map in the same run
                            meter_code_map.update(new_map_entries)
                            sys_cfg["meter_code_map"] = meter_code_map
                            existing_meter_serials    = set(meter_code_map.values())
                            log_msg(
                                f"  ✓ meter_code_map updated with "
                                f"{len(new_map_entries)} new entry(ies)"
                            )
                            # Rebuild meter_to_account with new entries
                            for kr, meter_no in new_map_entries.items():
                                for ca in r2_data:
                                    cust_id  = ca.get("customer", "")
                                    kr_code  = mw_customers.get(cust_id, "")
                                    acc_code = ca.get("code", "")
                                    if kr_code == kr and meter_no and acc_code:
                                        meter_to_account[meter_no] = acc_code
                        except Exception as e:
                            log_msg(f"  ⚠ Could not update meter_code_map: {e}")

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

            coords = wp.get("location", {}).get("coordinates", [])
            lon = coords[0] if len(coords) > 0 else None
            lat = coords[1] if len(coords) > 1 else None
            desc = wp.get("desc", "")

            name_key    = name.lower().strip()
            matched_acc = meter_to_account.get(code) or acc_name_to_code.get(name_key)

            if not matched_acc and cfg.get("accounts_key") and cfg.get("accounts_base"):
                continue

            account_no      = matched_acc or f"{system_name[:3].upper()}-{code}"
            wp_type         = wp.get("type_improved") or wp.get("type_")
            connection_type = _infer_connection_type(name, wp_type)

            session.add(Customer(
                system_id=system_id, name=name, account_no=account_no,
                meter_no=code, address=desc, latitude=lat, longitude=lon,
                connection_type=connection_type, is_active=True,
            ))
            existing_meters.add(code)
            new_count += 1
            log_msg(f"  ✓ {name} (meter={code}, acc={account_no})")

        session.commit()

        if not meter_code_map and cfg.get("accounts_key") and cfg.get("accounts_base"):
            log_msg("  No meter_code_map — syncing from accounts API...")
            new_count += _sync_customers_from_accounts(
                system_id, session, cfg, log,
                water_system_id=sys_cfg["water_system_id"]
            )

        return new_count

    except Exception as e:
        log_msg(f"  Customer sync error: {e}")
        return 0


def _sync_customers_from_accounts(system_id, session, cfg, log, water_system_id=None) -> int:

    def log_msg(msg):
        if log is not None:
            log.append(msg)

    try:
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

        existing_accounts = set(
            row[0] for row in session.query(Customer.account_no)
                                     .filter_by(system_id=system_id).all()
            if row[0]
        )

        new_count = 0
        for c in acc_customers:
            code = str(c.get("code", "")).strip()
            name = (c.get("name") or f"Customer {code}").strip()
            if not code or code in existing_accounts:
                continue
            session.add(Customer(
                system_id=system_id, name=name, account_no=code,
                meter_no=code, connection_type=_infer_connection_type(name),
                is_active=True,
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


# reallocate_payments 

def reallocate_payments(system_id: int, session, log: list = None, commit: bool = True) -> int:

    def log_msg(msg):
        if log is not None:
            log.append(msg)

    try:
        pay_rows = session.execute(sql_text(
            "SELECT customer_id, SUM(amount) FROM payments "
            "WHERE system_id = :sid GROUP BY customer_id"
        ), {"sid": system_id}).fetchall()
        db_paid = {row[0]: float(row[1] or 0) for row in pay_rows}
    except Exception as e:
        log_msg(f"  Reallocation error: {e}")
        return 0

    updated   = 0
    all_custs = session.query(Customer).filter_by(system_id=system_id).all()

    for customer in all_custs:
        total_paid = db_paid.get(customer.id, 0.0)
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

            if bill.amount_paid != new_paid or bill.is_paid != new_flag:
                bill.amount_paid = new_paid
                bill.is_paid     = new_flag
                updated += 1

    if commit:
        session.commit()
    return updated


# sync_billing

def sync_billing(system_id, session, cfg, sys_cfg, log) -> int:

    def log_msg(msg):
        if log is not None:
            log.append(msg)

    if not cfg.get("accounts_key") or not cfg.get("accounts_base"):
        log_msg("  Accounts API not configured — skipping")
        return 0

    meter_code_map = sys_cfg["meter_code_map"]

    try:
        all_txns = _fetch_all_transactions(cfg["accounts_base"], cfg["accounts_key"])

        r2 = requests.get(f"{cfg['accounts_base']}/customer_accounts",
                          params={"client": cfg["accounts_key"], "limit": 50}, timeout=15)
        r3 = requests.get(f"{cfg['accounts_base']}/customers",
                          params={"client": cfg["accounts_key"], "limit": 50}, timeout=15)

        mw_customers = {c["_id"]: c.get("code") for c in (r3.json() if r3.status_code == 200 else [])}
        acc_to_kr    = {
            ca["_id"]: mw_customers.get(ca.get("customer", ""), "")
            for ca in (r2.json() if r2.status_code == 200 else [])
        }

        billing_txns = [t for t in all_txns if t.get("meter_volume") is not None]
        payment_txns = [t for t in all_txns if t.get("meter_volume") is None and t.get("customer_account")]

        new_bills = 0
        for t in billing_txns:
            cust_acc_id = t.get("customer_account", "")
            kr_code     = acc_to_kr.get(cust_acc_id, "")
            mwater_id   = t.get("_id") or t.get("id") or ""

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
                log_msg(f"  ⚠ Unmatched billing txn: acc={cust_acc_id} code={kr_code} amount={t.get('amount',0)}")
                continue

            date_str   = t.get("date", "")
            bill_month = date_str[:7] if date_str else ""
            units_m3   = float(t.get("meter_volume", 0))
            amount     = float(t.get("amount", 0))

            existing = session.query(Bill).filter_by(
                system_id=system_id, customer_id=customer.id, bill_month=bill_month
            ).first()

            if not existing:
                session.add(Bill(
                    system_id=system_id, customer_id=customer.id,
                    bill_month=bill_month, units_m3=units_m3, amount=amount,
                    amount_paid=0.0, is_paid=False, sms_sent=False,
                    mwater_id=mwater_id or None, is_orphaned=False,
                ))
                new_bills += 1
            else:
                if mwater_id and existing.mwater_id != mwater_id:
                    existing.mwater_id = mwater_id
                if existing.is_orphaned:
                    existing.is_orphaned = False
                    log_msg(f"  ✓ Bill {bill_month} for {customer.account_no} no longer orphaned")

                if existing.amount != amount or existing.units_m3 != units_m3:
                    old_amount = existing.amount or 0
                    old_paid   = existing.amount_paid or 0
                    if old_amount > 0 and old_paid > 0:
                        existing.amount_paid = round(min(old_paid / old_amount, 1.0) * amount, 0)
                    existing.amount   = amount
                    existing.units_m3 = units_m3
                    existing.is_paid  = (existing.amount_paid >= amount)
                    log_msg(f"  ↻ Updated bill {bill_month} for {customer.account_no}: {old_amount} → {amount}")

        session.commit()
        log_msg(f"  New bills added: {new_bills}")

        # Orphan detection 
        if all_txns:
            current_billing_ids = {
                t.get("_id") or t.get("id")
                for t in billing_txns
                if t.get("_id") or t.get("id")
            }
            tracked_bills = session.query(Bill).filter(
                Bill.system_id == system_id,
                Bill.mwater_id.isnot(None),
                Bill.mwater_id != "",
            ).all()

            newly_orphaned = 0
            for b in tracked_bills:
                if b.mwater_id not in current_billing_ids:
                    if not b.is_orphaned:
                        cust = session.query(Customer).filter_by(id=b.customer_id).first()
                        log_msg(
                            f"  🚩 Possible deletion: Bill {b.bill_month} for "
                            f"{cust.account_no if cust else '?'} "
                            f"(amount {b.amount:,.0f}) — flagged for review."
                        )
                        newly_orphaned += 1
                    b.is_orphaned = True

            if newly_orphaned:
                log_msg(f"  🚩 {newly_orphaned} bill(s) newly flagged — review in Data Quality")
            session.commit()
        else:
            log_msg("  (skipping orphan check — no transactions returned from mWater)")

        # Payment allocation 
        log_msg("  Recalculating payment allocation...")
        updated = reallocate_payments(system_id, session, log, commit=True)
        log_msg(f"  Payment records updated: {updated}")
        return new_bills

    except Exception as e:
        log_msg(f"  Billing sync error: {e}")
        return 0


# sync_payments 

def sync_payments(system_id, session, cfg, sys_cfg, log) -> int:

    def log_msg(msg):
        if log is not None:
            log.append(msg)

    if not cfg.get("accounts_key") or not cfg.get("accounts_base"):
        return 0

    meter_code_map = sys_cfg["meter_code_map"]

    try:
        all_txns = _fetch_all_transactions(cfg["accounts_base"], cfg["accounts_key"])

        r2 = requests.get(f"{cfg['accounts_base']}/customer_accounts",
                          params={"client": cfg["accounts_key"], "limit": 50}, timeout=15)
        r3 = requests.get(f"{cfg['accounts_base']}/customers",
                          params={"client": cfg["accounts_key"], "limit": 50}, timeout=15)

        mw_customers = {c["_id"]: c.get("code") for c in (r3.json() if r3.status_code == 200 else [])}
        acc_to_kr    = {
            ca["_id"]: mw_customers.get(ca.get("customer", ""), "")
            for ca in (r2.json() if r2.status_code == 200 else [])
        }

        payment_txns = [t for t in all_txns if t.get("meter_volume") is None and t.get("customer_account")]

        existing_payments: set[tuple] = set()
        try:
            result = session.execute(sql_text(
                "SELECT customer_id, amount, DATE(paid_at) FROM payments WHERE system_id = :sid"
            ), {"sid": system_id})
            existing_payments = {(row[0], float(row[1]), str(row[2])[:10]) for row in result}
        except Exception:
            pass

        new_payments = 0
        for t in payment_txns:
            acc       = t.get("customer_account", "")
            kr_code   = acc_to_kr.get(acc, "")
            meter     = meter_code_map.get(kr_code) or kr_code
            if not meter:
                continue

            customer = (
                session.query(Customer).filter_by(system_id=system_id, meter_no=meter).first()
                or session.query(Customer).filter_by(system_id=system_id, account_no=meter).first()
            )
            if not customer:
                continue

            date_str  = t.get("date", "")
            amount    = float(t.get("amount", 0))
            notes     = t.get("notes", "") or ""
            mwater_id = t.get("_id") or t.get("id") or ""

            if not date_str or amount <= 0:
                continue

            date_only = date_str[:10]
            key       = (customer.id, amount, date_only)
            if key in existing_payments:
                continue

            try:
                session.execute(sql_text("""
                    INSERT INTO payments
                        (system_id, customer_id, amount, payment_method,
                         notes, paid_at, status, transaction_id, is_orphaned)
                    VALUES
                        (:system_id, :customer_id, :amount, :method,
                         :notes, :paid_at, 'completed', :transaction_id, false)
                """), {
                    "system_id":      system_id,
                    "customer_id":    customer.id,
                    "amount":         amount,
                    "method":         "Cash",
                    "notes":          notes,
                    "paid_at":        f"{date_only}T00:00:00+00:00",
                    "transaction_id": mwater_id or None,
                })
                existing_payments.add(key)
                new_payments += 1
            except Exception as e:
                log_msg(f"  Payment insert error: {e}")

        session.commit()
        log_msg(f"  New payments synced: {new_payments}")

        # Backfill transaction_id for pre-existing payments
        if payment_txns:
            backfilled = 0
            for t in payment_txns:
                acc2       = t.get("customer_account", "")
                kr_code2   = acc_to_kr.get(acc2, "")
                meter2     = meter_code_map.get(kr_code2) or kr_code2
                mwater_id2 = t.get("_id") or t.get("id") or ""
                date_str2  = t.get("date", "")
                amount2    = float(t.get("amount", 0))
                date_only2 = date_str2[:10] if date_str2 else ""

                if not meter2 or not mwater_id2 or not date_only2 or amount2 <= 0:
                    continue

                cust2 = (
                    session.query(Customer).filter_by(system_id=system_id, meter_no=meter2).first()
                    or session.query(Customer).filter_by(system_id=system_id, account_no=meter2).first()
                )
                if not cust2:
                    continue

                try:
                    res2 = session.execute(sql_text("""
                        UPDATE payments SET transaction_id = :txn_id
                        WHERE system_id   = :sid
                          AND customer_id = :cid
                          AND amount      = :amount
                          AND DATE(paid_at) = :date
                          AND (transaction_id IS NULL OR transaction_id = '')
                    """), {
                        "txn_id": mwater_id2, "sid": system_id,
                        "cid": cust2.id, "amount": amount2, "date": date_only2,
                    })
                    backfilled += res2.rowcount
                except Exception:
                    pass

            if backfilled:
                session.commit()
                log_msg(f"  ↻ Backfilled transaction_id on {backfilled} pre-existing payment(s)")

        # Orphan detection 
        if all_txns:
            current_payment_ids = {
                t.get("_id") or t.get("id")
                for t in payment_txns
                if t.get("_id") or t.get("id")
            }
            try:
                tracked_rows = session.execute(sql_text(
                    "SELECT id, transaction_id, customer_id, amount, is_orphaned "
                    "FROM payments WHERE system_id = :sid "
                    "AND transaction_id IS NOT NULL AND transaction_id != ''"
                ), {"sid": system_id}).fetchall()
            except Exception:
                tracked_rows = []

            newly_orphaned = 0
            for row in tracked_rows:
                pay_id, txn_id, cust_id, amount, was_orphaned = row
                now_missing = txn_id not in current_payment_ids

                if now_missing and not was_orphaned:
                    cust = session.query(Customer).filter_by(id=cust_id).first()
                    log_msg(
                        f"  🚩 Possible deletion: Payment of {amount:,.0f} for "
                        f"{cust.account_no if cust else '?'} — flagged for review."
                    )
                    newly_orphaned += 1

                if now_missing != bool(was_orphaned):
                    session.execute(sql_text(
                        "UPDATE payments SET is_orphaned = :v WHERE id = :id"
                    ), {"v": now_missing, "id": pay_id})
                    if was_orphaned and not now_missing:
                        log_msg(f"  ✓ Payment {pay_id} no longer orphaned")

            if newly_orphaned:
                log_msg(f"  🚩 {newly_orphaned} payment(s) newly flagged — review in Data Quality")
            session.commit()
        else:
            log_msg("  (skipping orphan check — no transactions returned from mWater)")

        return new_payments

    except Exception as e:
        log_msg(f"  Payment sync error: {e}")
        return 0


# sync_expenses 

def sync_expenses(system_id, session, cfg, log) -> int:

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
        all_txns     = _fetch_all_transactions(cfg["accounts_base"], cfg["accounts_key"])
        expense_txns = [
            t for t in all_txns
            if t.get("from_account") == CASH_ACCOUNT
            and not t.get("customer_account")
            and not t.get("meter_volume")
        ]
        log_msg(f"  Expense transactions: {len(expense_txns)}")

        existing: set[str] = set()
        try:
            result = session.execute(sql_text(
                "SELECT mwater_id FROM expenses WHERE system_id = :sid AND mwater_id IS NOT NULL"
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
                    INSERT INTO expenses (system_id, date, month, amount, category, notes, mwater_id)
                    VALUES (:system_id, :date, :month, :amount, :category, :notes, :mwater_id)
                    ON CONFLICT (mwater_id) DO NOTHING
                """), {
                    "system_id": system_id, "date": date_str, "month": month,
                    "amount": float(t.get("amount", 0)), "category": category,
                    "notes": t.get("notes", ""), "mwater_id": mwater_id,
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


# recalculate_nrw 

def recalculate_nrw(system_id: int, session) -> None:
    readings = session.query(DailyReading).filter_by(system_id=system_id).all()
    monthly: dict[str, dict] = defaultdict(lambda: {"pumped": 0.0, "consumed": 0.0})

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
        nrw_pct  = round((nrw_m3 / pumped) * 100, 1) if pumped > 0 else 0.0

        existing = session.query(NRWRecord).filter_by(system_id=system_id, month=month).first()
        if existing:
            existing.water_produced = pumped
            existing.water_billed   = consumed
            existing.nrw_m3         = nrw_m3
            existing.nrw_percent    = nrw_pct
        else:
            session.add(NRWRecord(
                system_id=system_id, month=month,
                water_produced=pumped, water_billed=consumed,
                nrw_m3=nrw_m3, nrw_percent=nrw_pct,
            ))

    session.commit()


# _fetch_all_transactions 

def _fetch_all_transactions(accounts_base: str, accounts_key: str) -> list[dict]:
    all_txns: list[dict] = []
    skip  = 0
    limit = 200
    while True:
        r = requests.get(
            f"{accounts_base}/transactions",
            params={"client": accounts_key, "limit": limit, "skip": skip},
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
