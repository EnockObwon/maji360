import streamlit as st
from core.auth import require_login, is_operator
from core.sync import sync_system
from core.database import get_session, DailyReading, Bill


def show():
    require_login()

    if not is_operator():
        st.error("Access denied. Operators only.")
        return

    system_id   = st.session_state.get("selected_system_id")
    system_name = st.session_state.get(
        "selected_system_name", ""
    )

    st.markdown("## 🔄 Data Sync")
    st.markdown(
        f"<span style='color:#64748b;font-size:13px'>"
        f"{system_name} · Sync from mWater</span>",
        unsafe_allow_html=True
    )
    st.divider()

    # ── Current data summary ───────────────────────────
    if system_id:
        session       = get_session()
        reading_count = session.query(
            DailyReading
        ).filter_by(system_id=system_id).count()
        bill_count    = session.query(Bill).filter_by(
            system_id=system_id
        ).count()
        last_reading  = session.query(
            DailyReading
        ).filter_by(
            system_id=system_id
        ).order_by(
            DailyReading.synced_at.desc()
        ).first()
        last_sync = last_reading.synced_at.strftime(
            "%d %b %Y %H:%M UTC"
        ) if last_reading and last_reading.synced_at \
          else "Never"
        session.close()

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Readings in database", reading_count)
        with col2:
            st.metric("Bills in database", bill_count)
        with col3:
            st.metric("Last sync", last_sync)

    st.divider()

    # ── Sync button ────────────────────────────────────
    st.markdown("### Manual sync")
    st.markdown(
        "Pull the latest readings, customers, billing "
        "and expense data from mWater into Maji360. "
        "This typically takes 30–60 seconds."
    )

    if st.button(
        "🔄 Sync now",
        use_container_width=True,
        type="primary"
    ):
        if not system_id:
            st.error("Please select a water system first.")
        else:
            log     = []
            results = {}

            with st.spinner("Syncing from mWater..."):
                try:
                    results = sync_system(system_id, log)
                except Exception as e:
                    st.error(f"Sync failed: {e}")
                    log.append(f"Error: {e}")

            if results and "error" not in results:
                st.success("✓ Sync completed successfully.")

                c1, c2, c3, c4, c5 = st.columns(5)
                with c1:
                    st.metric(
                        "New pump readings",
                        results.get("new_pump", 0)
                    )
                with c2:
                    st.metric(
                        "New tank readings",
                        results.get("new_tank", 0)
                    )
                with c3:
                    st.metric(
                        "New customers",
                        results.get("new_customers", 0)
                    )
                with c4:
                    st.metric(
                        "New bills",
                        results.get("new_bills", 0)
                    )
                with c5:
                    st.metric(
                        "New expenses",
                        results.get("new_expenses", 0)
                    )

            with st.expander("Sync log"):
                for line in log:
                    st.text(line)

    st.divider()

    # ── Auto sync info ─────────────────────────────────
    st.markdown("### Automatic sync schedule")
    st.markdown("""
    Maji360 is configured to sync automatically
    every day at **06:00 Uganda time** via
    GitHub Actions.

    The sync now covers:
    - 💧 Pump and tank readings from mWater form
    - 👥 New customers added in mWater
    - 💰 Billing transactions from mWater Accounts
    - 📊 Expense transactions from mWater Accounts

    The automatic sync runs even when no one is
    logged into the dashboard.
    """)

    st.info(
        "ℹ️ After a sync completes, refresh any "
        "open dashboard pages to see the latest data."
    )
