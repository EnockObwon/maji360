import streamlit as st
from core.database import get_session, WaterSystem, DailyReading, Bill
from core.auth import require_login
from core.sync import sync_system
from sqlalchemy import text as sql_text
from datetime import datetime, timezone


def get_sync_status(system_id: int) -> dict:
    """
    Read sync status directly from water_systems.
    Falls back to daily_readings for legacy systems
    that haven't synced since sync_logs was added.
    """
    session = get_session()
    try:
        row = session.execute(sql_text("""
            SELECT last_synced_at, sync_status
            FROM water_systems
            WHERE id = :sid
        """), {"sid": system_id}).fetchone()

        if row and row[0]:
            return {
                "last_synced_at": row[0],
                "sync_status":    row[1] or "success"
            }

        # Legacy fallback — daily_readings
        row2 = session.execute(sql_text("""
            SELECT MAX(synced_at)
            FROM daily_readings
            WHERE system_id = :sid
              AND synced_at IS NOT NULL
        """), {"sid": system_id}).fetchone()

        return {
            "last_synced_at": row2[0] if row2 else None,
            "sync_status":    "success" if (row2 and row2[0]) else None
        }
    except Exception:
        return {"last_synced_at": None, "sync_status": None}
    finally:
        session.close()


def format_ts(ts) -> str:
    if not ts:
        return "Awaiting first sync"
    try:
        if hasattr(ts, "strftime"):
            return ts.strftime("%d %b %Y at %H:%M UTC")
        return str(ts)[:16]
    except Exception:
        return str(ts)


def show():
    require_login()

    system_id   = st.session_state.get("selected_system_id")
    system_name = st.session_state.get("selected_system_name", "")

    if not system_id:
        st.warning("Please select a water system.")
        return

    session     = get_session()
    system      = session.query(WaterSystem).filter_by(id=system_id).first()
    uses_mwater = getattr(system, "uses_mwater", True)
    session.close()

    st.markdown("## 🔄 Data Sync")
    st.markdown(
        f"<span style='color:#64748b;font-size:13px'>"
        f"{system_name} · "
        f"{'Sync from mWater' if uses_mwater else 'Manual data entry system'}"
        f"</span>",
        unsafe_allow_html=True
    )
    st.divider()

    if not uses_mwater:
        st.info(
            "This system does not use mWater. "
            "Data is entered manually in Field Ops and Customer Billing."
        )
        return

    # ── Stats ─────────────────────────────────────────────
    session       = get_session()
    reading_count = session.query(DailyReading).filter_by(system_id=system_id).count()
    bill_count    = session.query(Bill).filter_by(system_id=system_id).count()
    session.close()

    sync_info = get_sync_status(system_id)
    last_sync = format_ts(sync_info["last_synced_at"])

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Readings in database", reading_count)
    with c2:
        st.metric("Bills in database", bill_count)
    with c3:
        st.metric("Last sync", last_sync)

    st.divider()

    # ── Show previous sync results (persisted across rerun) ──
    prev = st.session_state.get(f"sync_result_{system_id}")
    if prev:
        if prev.get("status") == "success":
            st.success(f"✓ Last sync completed — {prev.get('time', '')}")
            r = prev.get("results", {})
            st.markdown(
                f"<div style='background:#f0fdf4;border-radius:8px;"
                f"padding:12px 16px;font-size:14px;margin-bottom:8px'>"
                f"<b>Sync summary</b><br>"
                f"New pump readings : <b>{r.get('new_pump', 0)}</b><br>"
                f"New tank readings : <b>{r.get('new_tank', 0)}</b><br>"
                f"New customers     : <b>{r.get('new_customers', 0)}</b><br>"
                f"New bills         : <b>{r.get('new_bills', 0)}</b><br>"
                f"New payments      : <b>{r.get('new_payments', 0)}</b><br>"
                f"New expenses      : <b>{r.get('new_expenses', 0)}</b><br>"
                f"Duplicates skipped: <b>{r.get('duplicates', 0)}</b>"
                f"</div>",
                unsafe_allow_html=True
            )
        else:
            st.error(f"✗ Last sync failed — {prev.get('error', 'unknown error')}")

        if prev.get("log"):
            with st.expander("View sync log", expanded=prev.get("status") != "success"):
                st.code("\n".join(prev["log"]), language="text")

        st.divider()

    # ── Automatic daily sync info ──────────────────────────
    st.markdown("### Automatic daily sync")
    st.markdown(
        "<div style='background:#eff6ff;border-radius:8px;"
        "padding:12px 16px;font-size:14px;margin-bottom:16px'>"
        "⏰ Maji360 syncs automatically every day at <b>06:00 EAT</b> "
        "(03:00 UTC) via GitHub Actions. This pulls the latest pump "
        "readings, billing transactions, payments and expenses from mWater."
        "</div>",
        unsafe_allow_html=True
    )

    # ── Manual sync ────────────────────────────────────────
    st.markdown("### Manual sync")
    st.caption(
        "Run a manual sync if you need the latest data "
        "immediately without waiting for the scheduled sync."
    )

    if st.button("▶ Run sync now", type="primary", use_container_width=True):
        log     = []
        results = {}

        with st.spinner("Syncing from mWater — please wait..."):
            try:
                results = sync_system(
                    system_id, log=log, triggered_by="manual"
                )
            except Exception as e:
                results = {"error": str(e)}
                log.append(f"EXCEPTION: {e}")

        now_str = datetime.now(timezone.utc).strftime(
            "%d %b %Y at %H:%M UTC"
        )

        if "error" not in results:
            st.session_state[f"sync_result_{system_id}"] = {
                "status":  "success",
                "time":    now_str,
                "results": results,
                "log":     log,
            }
        else:
            st.session_state[f"sync_result_{system_id}"] = {
                "status": "error",
                "error":  results.get("error", "Unknown error"),
                "log":    log,
                "time":   now_str,
            }

        # Rerun to refresh stats and show persisted results
        st.rerun()

    st.divider()

    # ── What gets synced ───────────────────────────────────
    st.markdown("### What gets synced")
    items = [
        ("📊", "Pump readings",
         "Daily pump start and end meter readings from mWater monitoring form"),
        ("🚰", "Tank readings",
         "Daily tank outlet start and end meter readings from mWater monitoring form"),
        ("👥", "Customers",
         "New water points or accounts customers registered in mWater are automatically added"),
        ("💰", "Bills",
         "Billing transactions from mWater Accounts with payment redistribution"),
        ("💵", "Payments",
         "Individual payment records with actual payment dates for cash flow reporting"),
        ("📋", "Expenses",
         "Operational expense transactions from mWater Accounts"),
        ("📉", "NRW",
         "Non-revenue water recalculated automatically after each sync"),
    ]
    for icon, title, desc in items:
        st.markdown(
            f"<div style='display:flex;align-items:flex-start;"
            f"padding:8px 0;border-bottom:1px solid #f1f5f9'>"
            f"<span style='font-size:20px;margin-right:12px'>{icon}</span>"
            f"<div><b>{title}</b><br>"
            f"<span style='font-size:13px;color:#64748b'>{desc}</span>"
            f"</div></div>",
            unsafe_allow_html=True
        )
