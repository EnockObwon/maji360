import streamlit as st
import pandas as pd
from core.database import get_session, DailyReading, Bill, NRWRecord, Customer
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
    latest_nrw   = session.query(NRWRecord).filter_by(system_id=system_id).order_by(NRWRecord.created_at.desc()).first()
    total_billed = session.query(func.sum(Bill.amount)).filter_by(system_id=system_id).scalar() or 0
    total_paid   = session.query(func.sum(Bill.amount)).filter(Bill.system_id==system_id, Bill.is_paid==True).scalar() or 0
    total_outstanding = total_billed - total_paid
    collection_rate   = round((total_paid/total_billed)*100,1) if total_billed>0 else 0
    total_customers   = session.query(Customer).filter_by(system_id=system_id,is_active=True).count()
    last_reading      = session.query(DailyReading).filter_by(system_id=system_id).order_by(DailyReading.synced_at.desc()).first()
    last_sync = last_reading.synced_at.strftime("%d %b %Y %H:%M") if last_reading and last_reading.synced_at else "Never"
    session.close()
    st.markdown(f"## {system_name}")
    st.markdown(f"<span style='font-size:13px;color:#64748b'>Last synced: {last_sync} UTC</span>", unsafe_allow_html=True)
    st.divider()
    if latest_nrw:
        nrw_pct = latest_nrw.nrw_percent or 0
        if nrw_pct >= 20:
            st.markdown(f'<div class="alert-banner">🔴 NRW ALERT — {latest_nrw.month}: {nrw_pct:.1f}% water unaccounted (threshold: 20%)</div>', unsafe_allow_html=True)
        elif nrw_pct >= 15:
            st.markdown(f'<div class="warn-banner">🟡 NRW WARNING — {latest_nrw.month}: {nrw_pct:.1f}% water unaccounted</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="ok-banner">🟢 NRW OK — {latest_nrw.month}: {nrw_pct:.1f}% within acceptable range</div>', unsafe_allow_html=True)
    st.markdown("### System overview")
    c1,c2,c3,c4,c5 = st.columns(5)
    with c1: st.metric("NRW rate", f"{latest_nrw.nrw_percent:.1f}%" if latest_nrw else "—")
    with c2: st.metric("Customers", total_customers)
    with c3: st.metric("Total billed", f"{currency} {total_billed:,.0f}")
    with c4: st.metric("Collected", f"{currency} {total_paid:,.0f}")
    with c5: st.metric("Collection rate", f"{collection_rate}%")
    st.divider()
    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("### Outstanding balances")
        session   = get_session()
        customers = session.query(Customer).filter_by(system_id=system_id,is_active=True).all()
        rows = []
        for c in customers:
            if not c.account_no or not c.account_no.startswith("4"): continue
            owed = sum(b.amount or 0 for b in c.bills if not b.is_paid)
            if owed > 0:
                rows.append({"Account": c.account_no, "Customer": c.name, "Outstanding": f"{currency} {owed:,.0f}"})
        session.close()
        if rows: st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else: st.success("All customers are up to date.")
    with col_right:
        st.markdown("### Recent readings")
        session = get_session()
        recent  = session.query(DailyReading).filter(DailyReading.system_id==system_id, DailyReading.water_produced_m3>0).order_by(DailyReading.reading_date.desc()).limit(8).all()
        session.close()
        if recent:
            data = [{"Date": r.reading_date.strftime("%d %b %Y"), "Pump (m³)": r.water_produced_m3, "Tank (m³)": r.water_consumed_m3, "NRW (m³)": round((r.water_produced_m3 or 0)-(r.water_consumed_m3 or 0),1)} for r in recent]
            st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
        else: st.info("No readings available.")
