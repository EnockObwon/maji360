# ── Maji360 · core/sync.py ─────────────────────────────
import requests
import json
from datetime import datetime, timezone
from collections import defaultdict
from core.database import (
    get_session, WaterSystem, DailyReading,
    Bill, Customer, NRWRecord
)


def get_mwater_config():
    try:
        import streamlit as st
        return {
            "client_key":    st.secrets["MWATER_CLIENT_KEY"],
            "v3_base":       st.secrets["MWATER_V3_BASE"],
            "accounts_key":  st.secrets["ACCOUNTS_CLIENT_KEY"],
            "accounts_base": st.secrets["ACCOUNTS_BASE"],
        }
    except Exception:
        import os
        return {
            "client_key":    os.environ.get(
                "MWATER_CLIENT_KEY", ""
            ),
            "v3_base":       os.environ.get(
                "MWATER_V3_BASE",
                "https://api.mwater.co/v3"
            ),
            "accounts_key":  os.environ.get(
                "ACCOUNTS_CLIENT_KEY", ""
            ),
            "accounts_base": os.environ.get(
                "ACCOUNTS_BASE", ""
            ),
        }


def safe_float(val):
    if val is None:
        return None
    if isinstance(val, dict):
        val = val.get("value")
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


FIELD_IDS = {
    "pump_start": "7411292765fa4fb7a0217bfb001ab167",
    "pump_end":   "3456b8d568fe46b49dd0843a58cdc143",
    "tank_start": "f1c488eb7ec248a8a6d1208ba8f4b06a",
    "tank_end":   "9cae2fe4ea6b4940bb800253123b7565",
}

WATER_SYSTEM_ID = "b0e76a15-7047-4c5e-a986-e2bba550a4ff"
GROUP_ID        = "718ce61fbf4f4742bd1018cabf90d1e8"

CONN_TYPE_MAP = {
    "Piped into public tap or basin": "PSP",
    "Piped into yard/plot":           "Private",
    None:                             "PSP"
}

KR_TO_METER = {
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


def sync_system(system_id: int, log: list = None) -> dict:
    def log_msg(msg: str):
        if log is not None:
            log.append(msg)

    cfg     = get_mwater_config()
    session = get_session()
    system  = session.query(WaterSystem).filter_by(
        id=system_id
    ).first()

    if not system:
        session.close()
        return {"error": "System not found"}

    system_name = system.name
    form_id     = system.mwater_form_id

    log_msg(f"Syncing {system_name}...")
    log_msg(f"Form ID: {form_id}")

    # ── Fetch all mWater responses ─────────────────────
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
                    "limit":    100,
                    "skip":     skip
                },
                timeout=60
            )
            if resp.status_code != 200:
                log_msg(
                    f"mWater error: {resp.status_code}"
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
            log_msg(f"Fetch error: {e}")
            break

    log_msg(f"Total responses: {len(all_responses)}")

    # ── Get existing response IDs ──────────────────────
    existing_ids = set(
        row[0] for row in session.query(
            DailyReading.mwater_response_id
        ).filter_by(system_id=system_id).all()
        if row[0]
    )

    # ── Parse and save new readings ────────────────────
    new_pump   = 0
    new_tank   = 0
    duplicates = 0

    for r in all_responses:
        resp_id = r.get("_id", r.get("id", ""))

        if resp_id in existing_ids:
            duplicates += 1
            continue

        data = r.get("data", {})
        ps   = safe_float(data.get(FIELD_IDS["pump_start"]))
        pe   = safe_float(data.get(FIELD_IDS["pump_end"]))
        ts   = safe_float(data.get(FIELD_IDS["tank_start"]))
        te   = safe_float(data.get(FIELD_IDS["tank_end"]))

        submitted = r.get("submittedOn", "")
        try:
            reading_date = datetime.fromisoformat(
                submitted.replace("Z", "+00:00")
            ) if submitted else datetime.now(timezone.utc)
        except Exception:
            reading_date = datetime.now(timezone.utc)

        pumped   = round(pe - ps, 2) \
                   if ps is not None and pe is not None \
                   and pe > ps else 0.0
        consumed = round(te - ts, 2) \
                   if ts is not None and te is not None \
                   and te > ts else 0.0

        if pumped == 0 and consumed == 0:
            continue

        reading = DailyReading(
            system_id          = system_id,
            reading_date       = reading_date,
            water_produced_m3  = pumped,
            water_consumed_m3  = consumed,
            water_sold_m3      = 0.0,
            mwater_response_id = resp_id,
            synced_at          = datetime.now(timezone.utc)
        )
        session.add(reading)
        existing_ids.add(resp_id)

        if pumped > 0:
            new_pump += 1
        if consumed > 0:
            new_tank += 1

    session.commit()
    log_msg(f"New pump readings : {new_pump}")
    log_msg(f"New tank readings : {new_tank}")
    log_msg(f"Duplicates skipped: {duplicates}")

    # ── Sync customers ─────────────────────────────────
    log_msg("Syncing customers from mWater...")
    new_customers = sync_customers(
        system_id, system_name, form_id,
        session, cfg, log
    )
    log_msg(f"New customers synced: {new_customers}")

    # ── Sync billing ───────────────────────────────────
    log_msg("Syncing billing transactions...")
    new_bills = sync_billing(
        system_id, session, cfg, log
    )
    log_msg(f"New bills synced  : {new_bills}")

    # ── Sync expenses ──────────────────────────────────
    log_msg("Syncing expenses...")
    new_expenses = sync_expenses(
        system_id, session, cfg, log
    )
    log_msg(f"New expenses synced: {new_expenses}")

    # ── Recalculate NRW ────────────────────────────────
    log_msg("Recalculating NRW...")
    recalculate_nrw(system_id, session)

    session.close()

    log_msg("✓ Sync complete.")
    return {
        "system":        system_name,
        "new_pump":      new_pump,
        "new_tank":      new_tank,
        "new_customers": new_customers,
        "new_bills":     new_bills,
        "new_expenses":  new_expenses,
        "duplicates":    duplicates,
        "synced_at":     datetime.now(
            timezone.utc
        ).isoformat()
    }


def sync_customers(system_id: int, system_name: str,
                   form_id: str, session,
                   cfg: dict, log: list) -> int:
    def log_msg(msg):
        if log is not None:
            log.append(msg)

    if not cfg.get("client_key") or not form_id:
        log_msg(
            "  No mWater config — skipping customer sync"
        )
        return 0

    try:
        # Fetch all water points from mWater group
        all_wps = []
        skip    = 0
        while True:
            r = requests.get(
                f"{cfg['v3_base']}/entities/water_point",
                params={
                    "client":   cfg["client_key"],
                    "selector": json.dumps({
                        "_managed_by": f"group:{GROUP_ID}"
                    }),
                    "limit": 50,
                    "skip":  skip
                },
                timeout=30
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

        log_msg(
            f"  mWater water points found: {len(all_wps)}"
        )

        # Get existing meter numbers in Maji360
        existing_meters = set(
            row[0] for row in session.query(
                Customer.meter_no
            ).filter_by(system_id=system_id).all()
            if row[0]
        )
        log_msg(
            f"  Existing in Maji360: {len(existing_meters)}"
        )

        # Fetch account numbers from mWater Accounts
        meter_to_account = {}
        if cfg.get("accounts_key") and \
           cfg.get("accounts_base"):
            try:
                r2 = requests.get(
                    f"{cfg['accounts_base']}"
                    f"/customer_accounts",
                    params={
                        "client": cfg["accounts_key"],
                        "limit":  50
                    },
                    timeout=15
                )
                r3 = requests.get(
                    f"{cfg['accounts_base']}/customers",
                    params={
                        "client": cfg["accounts_key"],
                        "limit":  50
                    },
                    timeout=15
                )
                if r2.status_code == 200 and \
                   r3.status_code == 200:
                    mw_customers = {
                        c["_id"]: c.get("code", "")
                        for c in r3.json()
                    }
                    for ca in r2.json():
                        cust_id  = ca.get("customer", "")
                        kr_code  = mw_customers.get(
                            cust_id, ""
                        )
                        acc_code = ca.get("code", "")
                        meter_no = KR_TO_METER.get(
                            kr_code, ""
                        )
                        if meter_no and acc_code:
                            meter_to_account[meter_no] = \
                                acc_code
            except Exception as e:
                log_msg(f"  Accounts lookup error: {e}")

        # Add new water points to Maji360
        new_count = 0
        for wp in all_wps:
            code = str(wp.get("code", ""))
            if not code or code in existing_meters:
                continue

            # Only add water points for this system
            if wp.get("water_system") != WATER_SYSTEM_ID:
                continue

            name = wp.get("name", f"Customer {code}")
            if isinstance(name, dict):
                name = name.get("en", str(name))

            conn_raw  = wp.get("type")
            coords    = wp.get(
                "location", {}
            ).get("coordinates", [])
            lon       = coords[0] \
                        if len(coords) > 0 else None
            lat       = coords[1] \
                        if len(coords) > 1 else None
            desc      = wp.get("desc", "")
            account_no = meter_to_account.get(
                code, f"KAR-{code}"
            )

            session.add(Customer(
                system_id  = system_id,
                name       = name,
                account_no = account_no,
                meter_no   = code,
                address    = desc,
                latitude   = lat,
                longitude  = lon,
                is_active  = True
            ))
            existing_meters.add(code)
            new_count += 1
            log_msg(f"  ✓ New customer: {name} "
                    f"(meter={code} acc={account_no})")

        session.commit()
        return new_count

    except Exception as e:
        log_msg(f"  Customer sync error: {e}")
        return 0


def sync_billing(system_id: int, session,
                  cfg: dict, log: list) -> int:
    def log_msg(msg):
        if log is not None:
            log.append(msg)

    if not cfg.get("accounts_key") or \
       not cfg.get("accounts_base"):
        log_msg(
            "  Accounts API not configured — skipping"
        )
        return 0

    try:
        all_txns = []
        skip     = 0
        while True:
            r = requests.get(
                f"{cfg['accounts_base']}/transactions",
                params={
                    "client": cfg["accounts_key"],
                    "limit":  50,
                    "skip":   skip
                },
                timeout=30
            )
            if r.status_code != 200 or not r.text.strip():
                break
            batch = r.json()
            if not batch:
                break
            all_txns.extend(batch)
            if len(batch) < 50:
                break
            skip += 50

        r2 = requests.get(
            f"{cfg['accounts_base']}/customer_accounts",
            params={
                "client": cfg["accounts_key"],
                "limit":  50
            },
            timeout=15
        )
        r3 = requests.get(
            f"{cfg['accounts_base']}/customers",
            params={
                "client": cfg["accounts_key"],
                "limit":  50
            },
            timeout=15
        )
        mw_customers = {
            c["_id"]: c.get("code")
            for c in (
                r3.json() if r3.status_code == 200 else []
            )
        }
        acc_to_kr = {
            ca["_id"]: mw_customers.get(
                ca.get("customer", ""), ""
            )
            for ca in (
                r2.json() if r2.status_code == 200 else []
            )
        }

        payment_txns  = [
            t for t in all_txns
            if t.get("meter_volume") is None
            and t.get("customer_account_bill")
        ]
        paid_bill_ids = {
            t.get("customer_account_bill")
            for t in payment_txns
        }
        billing_txns  = [
            t for t in all_txns
            if t.get("meter_volume") is not None
        ]

        new_bills = 0
        for t in billing_txns:
            cust_acc_id = t.get("customer_account", "")
            kr_code     = acc_to_kr.get(cust_acc_id, "")
            meter_no    = KR_TO_METER.get(kr_code)

            if not meter_no:
                continue

            customer = session.query(Customer).filter_by(
                system_id=system_id,
                meter_no=meter_no
            ).first()

            if not customer:
                continue

            date_str   = t.get("date", "")
            bill_month = date_str[:7] if date_str else ""
            units_m3   = float(t.get("meter_volume", 0))
            amount     = float(t.get("amount", 0))
            bill_id    = t.get(
                "customer_account_bill", ""
            )
            is_paid    = bill_id in paid_bill_ids

            existing = session.query(Bill).filter_by(
                system_id   = system_id,
                customer_id = customer.id,
                bill_month  = bill_month
            ).first()

            if existing:
                if existing.is_paid != is_paid:
                    existing.is_paid = is_paid
                continue

            session.add(Bill(
                system_id   = system_id,
                customer_id = customer.id,
                bill_month  = bill_month,
                units_m3    = units_m3,
                amount      = amount,
                is_paid     = is_paid,
                sms_sent    = False
            ))
            new_bills += 1

        session.commit()
        return new_bills

    except Exception as e:
        log_msg(f"  Billing sync error: {e}")
        return 0


def sync_expenses(system_id: int, session,
                   cfg: dict, log: list) -> int:
    def log_msg(msg):
        if log is not None:
            log.append(msg)

    if not cfg.get("accounts_key") or \
       not cfg.get("accounts_base"):
        log_msg(
            "  Accounts API not configured — skipping"
        )
        return 0

    CASH_ACCOUNT  = "302bafeccb9d4cb0ae442cffb833a64c"
    ACCOUNT_NAMES = {
        "998ebd77689a4bd388af840c4ca860b4":
            "Office Expenses",
        "eca51b9feeab4cb79c77c9445585044d":
            "Operating Expenses",
        "11fe4eb898c749fe9e1dadae10933f30":
            "Salaries and Wages",
    }

    try:
        all_txns = []
        skip     = 0
        while True:
            r = requests.get(
                f"{cfg['accounts_base']}/transactions",
                params={
                    "client": cfg["accounts_key"],
                    "limit":  50,
                    "skip":   skip
                },
                timeout=30
            )
            if r.status_code != 200 or not r.text.strip():
                break
            batch = r.json()
            if not batch:
                break
            all_txns.extend(batch)
            if len(batch) < 50:
                break
            skip += 50

        expense_txns = [
            t for t in all_txns
            if t.get("from_account") == CASH_ACCOUNT
            and not t.get("customer_account")
            and not t.get("meter_volume")
        ]

        log_msg(
            f"  Expense transactions found: "
            f"{len(expense_txns)}"
        )

        from sqlalchemy import text as sql_text
        existing = set()
        try:
            result = session.execute(sql_text(
                "SELECT mwater_id FROM expenses "
                "WHERE system_id = :sid "
                "AND mwater_id IS NOT NULL"
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
            category = ACCOUNT_NAMES.get(
                to_acc, "Other"
            )
            date_str = t.get("date", "")
            month    = date_str[:7] if date_str else ""

            try:
                session.execute(sql_text("""
                    INSERT INTO expenses
                        (system_id, date, month,
                         amount, category,
                         notes, mwater_id)
                    VALUES
                        (:system_id, :date, :month,
                         :amount, :category,
                         :notes, :mwater_id)
                    ON CONFLICT (mwater_id) DO NOTHING
                """), {
                    "system_id": system_id,
                    "date":      date_str,
                    "month":     month,
                    "amount":    float(
                        t.get("amount", 0)
                    ),
                    "category":  category,
                    "notes":     t.get("notes", ""),
                    "mwater_id": mwater_id
                })
                new_expenses += 1
                existing.add(mwater_id)
            except Exception as e:
                log_msg(f"  Expense insert error: {e}")

        session.commit()
        log_msg(f"  New expenses synced: {new_expenses}")
        return new_expenses

    except Exception as e:
        log_msg(f"  Expense sync error: {e}")
        return 0


def recalculate_nrw(system_id: int, session) -> None:
    readings = session.query(DailyReading).filter_by(
        system_id=system_id
    ).all()

    monthly = defaultdict(
        lambda: {"pumped": 0.0, "consumed": 0.0}
    )
    for r in readings:
        month = r.reading_date.strftime("%Y-%m")
        if r.water_produced_m3 and \
           r.water_produced_m3 > 0:
            monthly[month]["pumped"] += \
                r.water_produced_m3
        if r.water_consumed_m3 and \
           r.water_consumed_m3 > 0:
            monthly[month]["consumed"] += \
                r.water_consumed_m3

    for month, data in monthly.items():
        pumped   = round(data["pumped"],   2)
        consumed = round(data["consumed"], 2)
        nrw_m3   = round(pumped - consumed, 2)
        nrw_pct  = round(
            (nrw_m3 / pumped) * 100, 1
        ) if pumped > 0 else 0

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
                nrw_percent    = nrw_pct
            ))

    session.commit()
