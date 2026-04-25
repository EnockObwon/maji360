import streamlit as st
from core.database import get_session, WaterSystem, DailyReading, Bill
from core.auth import require_login
from core.sync import sync_system
from sqlalchemy import text as sql_text
from datetime import datetime, timezone


def get_last_sync_time(system_id: int):
    """
    Get the most recent synced_at timestamp
    from daily_readings as a proxy for last sync.
    """
    session = get_session()
    try:
        result = session.execute(sql_text(
            "SELECT MAX(synced_at) "
            "FROM daily_readings "
            "WHERE system_id = :sid "
            "AND synced_at IS NOT NULL"
        ), {"sid": system_id}).fetchone()
        last_sync = result[0] if result else None
    except Exception:
        last_sync = None
    session.close()
    return last_sync


def format_sync_time(ts) -> str:
    """
    Format sync timestamp in a friendly way.
    """
    if not ts:
        return None
    try:
        if hasattr(ts, 'strftime'):
            return ts.strftime(
                "%d %b %Y at %H:%M UTC"
            )
        return str(ts)[:16]
    except Exception:
        return None


def show():
    require_login()

    system_id   = st.session_state.get(
        "selected_system_id"
    )
    system_name = st.session_state.get(
        "selected_system_name", ""
    )

    if not system_id:
        st.warning("Please select a water system.")
        return

    session     = get_session()
    system      = session.query(WaterSystem).filter_by(
        id=system_id
    ).first()
    uses_mwater = getattr(
        system, 'uses_mwater', True
    )
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
            "Data is entered manually in "
            "Field Ops and Customer Billing."
        )
        return

    # ── Database stats ─────────────────────────────────
    session       = get_session()
    reading_count = session.query(
        DailyReading
    ).filter_by(system_id=system_id).count()
    bill_count    = session.query(
        Bill
    ).filter_by(system_id=system_id).count()
    session.close()

    last_sync    = get_last_sync_time(system_id)
    sync_display = format_sync_time(last_sync)

    # ── Stats row ──────────────────────────────────────
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric(
            "Readings in database",
            reading_count
        )
    with c2:
        st.metric(
            "Bills in database",
            bill_count
        )
    with c3:
        if sync_display:
            st.metric(
                "Last sync",
                sync_display
            )
        else:
            st.metric(
                "Last sync",
                "Awaiting first sync"
            )

    st.divider()

    # ── Sync info ──────────────────────────────────────
    st.markdown("### Automatic daily sync")
    st.markdown(
        "<div style='background:#eff6ff;"
        "border-radius:8px;padding:12px 16px;"
        "font-size:14px;margin-bottom:16px'>"
        "⏰ Maji360 syncs automatically every day "
        "at <b>06:00 EAT</b> (03:00 UTC) via "
        "GitHub Actions. This pulls the latest "
        "pump readings, billing transactions, "
        "payments and expenses from mWater."
        "</div>",
        unsafe_allow_html=True
    )

    st.markdown("### Manual sync")
    st.caption(
        "Run a manual sync if you need the latest "
        "data immediately without waiting for the "
        "scheduled sync."
    )

    # ── Sync button ────────────────────────────────────
    if st.button(
        "▶ Run sync now",
        type="primary",
        use_container_width=True
    ):
        log     = []
        results = {}

        with st.spinner(
            "Syncing from mWater — please wait..."
        ):
            try:
                results = sync_system(
                    system_id, log=log
                )
            except Exception as e:
                st.error(f"Sync error: {e}")
                results = {"error": str(e)}

        if "error" not in results:
            # Show success with timestamp
            now_str = datetime.now(
                timezone.utc
            ).strftime("%d %b %Y at %H:%M UTC")

            st.success(
                f"✓ Sync completed — {now_str}"
            )

            # Results summary
            st.markdown(
                f"<div style='background:#f0fdf4;"
                f"border-radius:8px;"
                f"padding:12px 16px;"
                f"font-size:14px;margin-top:8px'>"
                f"<b>Sync summary</b><br>"
                f"New pump readings: "
                f"<b>{results.get('new_pump', 0)}</b><br>"
                f"New tank readings: "
                f"<b>{results.get('new_tank', 0)}</b><br>"
                f"New customers: "
                f"<b>{results.get('new_customers', 0)}</b><br>"
                f"New bills: "
                f"<b>{results.get('new_bills', 0)}</b><br>"
                f"New payments: "
                f"<b>{results.get('new_payments', 0)}</b><br>"
                f"New expenses: "
                f"<b>{results.get('new_expenses', 0)}</b><br>"
                f"Duplicates skipped: "
                f"<b>{results.get('duplicates', 0)}</b>"
                f"</div>",
                unsafe_allow_html=True
            )

            # Update the last sync display
            st.session_state[
                "last_sync_time"
            ] = now_str

        else:
            st.error(
                f"Sync failed: {results['error']}"
            )

        # Show log
        if log:
            with st.expander(
                "View sync log", expanded=False
            ):
                st.code(
                    "\n".join(log),
                    language="text"
                )

        st.rerun()

    st.divider()

    # ── What gets synced ───────────────────────────────
    st.markdown("### What gets synced")
    sync_items = [
        ("📊", "Pump readings",
         "Daily pump start and end meter readings "
         "from mWater monitoring form"),
        ("🚰", "Tank readings",
         "Daily tank outlet start and end meter "
         "readings from mWater monitoring form"),
        ("👥", "Customers",
         "New water points registered in mWater "
         "are automatically added"),
        ("💰", "Bills",
         "Billing transactions from mWater "
         "Accounts with payment redistribution"),
        ("💵", "Payments",
         "Individual payment records with actual "
         "payment dates for cash flow reporting"),
        ("📋", "Expenses",
         "Operational expense transactions "
         "from mWater Accounts"),
        ("📉", "NRW",
         "Non-revenue water recalculated "
         "automatically after each sync"),
    ]

    for icon, title, desc in sync_items:
        st.markdown(
            f"<div style='display:flex;"
            f"align-items:flex-start;"
            f"padding:8px 0;border-bottom:"
            f"1px solid #f1f5f9'>"
            f"<span style='font-size:20px;"
            f"margin-right:12px'>{icon}</span>"
            f"<div><b>{title}</b><br>"
            f"<span style='font-size:13px;"
            f"color:#64748b'>{desc}</span>"
            f"</div></div>",
            unsafe_allow_html=True
        )
