import streamlit as st
import pandas as pd
from core.database import (
    get_session, DailyReading, Bill,
    NRWRecord, Customer
)
from core.auth import require_login
from sqlalchemy import func


def show():
    require_login()

    system_id   = st.session_state.get("selected_system_id")
    system_name = st.session_state.get("selected_system_name", "")
    currency    = st.session_state.get("currency", "UGX")

    if not system_id:
        st.warning("Please select a water system.")
        return

    session = get_session()

    # ── Latest NRW — most recent month with pump data ──
    latest_nrw = session.query(NRWRecord).filter(
        NRWRecord.system_id    == system_id,
        NRWRecord.water_produced > 0
    ).order_by(NRWRecord.month.desc()).first()

    # ── Billing — use amount_paid not is_paid ──────────
    all_bills    = session.query(Bill).filter_by(
        system_id=system_id
    ).all()

    total_billed      = sum(b.amount or 0 for b in all_bills)
    total_paid        = sum(
        b.amount_paid or 0 for b in all_bills
    )
    total_outstanding = total_billed - total_paid
    collection_rate   = round(
        (total_paid / total_billed) * 100, 1
    ) if total_billed > 0 else 0

    total_customers = session.query(Customer).filter_by(
        system_id=system_id, is_active=True
    ).count()

    last_reading = session.query(DailyReading).filter_by(
        system_id=system_id
    ).order_by(DailyReading.synced_at.desc()).first()
    last_sync = last_reading.synced_at.strftime(
        "%d %b %Y %H:%M"
    ) if last_reading and last_reading.synced_at else "Never"

    # ── Customer outstanding using amount_paid ─────────
    customers = session.query(Customer).filter_by(
        system_id=system_id, is_active=True
    ).all()

    outstanding_rows = []
    for c in customers:
        if not c.account_no or \
           not c.account_no.startswith("4"):
            continue
        c_bills  = session.query(Bill).filter_by(
            customer_id=c.id
        ).all()
        billed   = sum(b.amount or 0 for b in c_bills)
        paid     = sum(b.amount_paid or 0 for b in c_bills)
        owed     = billed - paid
        if owed > 0:
            outstanding_rows.append({
                "Account":     c.account_no,
                "Customer":    c.name,
                "Outstanding": f"{currency} {owed:,.0f}"
            })

    # ── Recent readings ────────────────────────────────
    pump_readings = session.query(DailyReading).filter(
        DailyReading.system_id         == system_id,
        DailyReading.water_produced_m3 > 0
    ).order_by(
        DailyReading.reading_date.desc()
    ).limit(5).all()

    tank_readings = session.query(DailyReading).filter(
        DailyReading.system_id         == system_id,
        DailyReading.water_consumed_m3 > 0
    ).order_by(
        DailyReading.reading_date.desc()
    ).limit(5).all()

    session.close()

    # ── Header ─────────────────────────────────────────
    st.markdown(f"## {system_name}")
    st.markdown(
        f"<span style='font-size:13px;color:#64748b'>"
        f"Last synced: {last_sync} UTC</span>",
        unsafe_allow_html=True
    )
    st.divider()

    # ── NRW status banner ──────────────────────────────
    if latest_nrw:
        nrw_pct = latest_nrw.nrw_percent or 0
        month   = latest_nrw.month
        if nrw_pct >= 20:
            st.markdown(
                f'<div class="alert-banner">🔴 '
                f'NRW ALERT — {month}: '
                f'{nrw_pct:.1f}% water unaccounted '
                f'(threshold: 20%)</div>',
                unsafe_allow_html=True
            )
        elif nrw_pct >= 15:
            st.markdown(
                f'<div class="warn-banner">🟡 '
                f'NRW WARNING — {month}: '
                f'{nrw_pct:.1f}% water unaccounted</div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f'<div class="ok-banner">🟢 '
                f'NRW OK — {month}: '
                f'{nrw_pct:.1f}% within acceptable range'
                f'</div>',
                unsafe_allow_html=True
            )

    # ── KPI cards ──────────────────────────────────────
    st.markdown("### System overview")
    c1, c2, c3, c4, c5 = st.columns(5)

    with c1:
        st.metric(
            "NRW rate",
            f"{latest_nrw.nrw_percent:.1f}%"
            if latest_nrw else "—"
        )
    with c2:
        st.metric("Customers", total_customers)
    with c3:
        st.metric(
            "Total billed",
            f"{currency} {total_billed:,.0f}"
        )
    with c4:
        st.metric(
            "Collected",
            f"{currency} {total_paid:,.0f}"
        )
    with c5:
        st.metric(
            "Collection rate",
            f"{collection_rate}%"
        )

    st.divider()

    # ── Two column layout ──────────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("### Outstanding balances")
        if outstanding_rows:
            st.dataframe(
                pd.DataFrame(outstanding_rows),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.success("All customers are up to date.")

    with col_right:
        st.markdown("### Recent readings")

        st.markdown(
            "<span style='font-size:13px;color:#64748b'>"
            "💧 Pump house — last 5 readings</span>",
            unsafe_allow_html=True
        )
        if pump_readings:
            pump_data = [{
                "Date":       r.reading_date.strftime(
                    "%d %b %Y"
                ),
                "Pumped m³":  r.water_produced_m3
            } for r in pump_readings]
            st.dataframe(
                pd.DataFrame(pump_data),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No pump readings available.")

        st.markdown(
            "<span style='font-size:13px;color:#64748b'>"
            "🏗️ Tank outlet — last 5 readings</span>",
            unsafe_allow_html=True
        )
        if tank_readings:
            tank_data = [{
                "Date":        r.reading_date.strftime(
                    "%d %b %Y"
                ),
                "Consumed m³": r.water_consumed_m3
            } for r in tank_readings]
            st.dataframe(
                pd.DataFrame(tank_data),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No tank readings available.")
