import streamlit as st
import folium
from streamlit_folium import st_folium
import pandas as pd
from core.database import get_session, Customer, WaterSystem
from core.auth import require_login

def show():
    require_login()
    system_id   = st.session_state.get("selected_system_id")
    system_name = st.session_state.get("selected_system_name", "")
    currency    = st.session_state.get("currency", "UGX")
    if not system_id:
        st.warning("Please select a water system.")
        return
    st.markdown("## 🗺️ GIS Map")
    st.markdown(f"<span style='color:#64748b;font-size:13px'>{system_name} · Water Point Locations</span>", unsafe_allow_html=True)
    st.divider()
    session   = get_session()
    system    = session.query(WaterSystem).filter_by(id=system_id).first()
    customers = session.query(Customer).filter_by(system_id=system_id,is_active=True).all()
    cust_data = []
    for c in customers:
        if not c.latitude or not c.longitude: continue
        if not c.account_no or not c.account_no.startswith("4"): continue
        unpaid      = [b for b in c.bills if not b.is_paid]
        outstanding = sum(b.amount or 0 for b in unpaid)
        total_billed = sum(b.amount or 0 for b in c.bills)
        paid         = total_billed - outstanding
        rate         = round((paid/total_billed)*100,0) if total_billed>0 else 0
        if outstanding==0 and total_billed>0: color,status = "green","Fully paid"
        elif outstanding>0 and paid>0:        color,status = "orange",f"Partial — {rate:.0f}% paid"
        elif outstanding>0 and paid==0:       color,status = "red","No payments recorded"
        else:                                  color,status = "gray","No billing data"
        cust_data.append({"name": c.name, "account_no": c.account_no, "lat": c.latitude, "lon": c.longitude, "outstanding": outstanding, "billed": total_billed, "color": color, "status": status, "phone": c.phone or "—"})
    session.close()
    if not cust_data:
        st.info("No customer locations available.")
        return
    c1,c2,c3,c4 = st.columns(4)
    with c1: st.markdown("🟢 **Fully paid**")
    with c2: st.markdown("🟠 **Partially paid**")
    with c3: st.markdown("🔴 **No payments**")
    with c4: st.markdown("⚫ **No billing data**")
    centre = [system.latitude, system.longitude] if system and system.latitude else [sum(c["lat"] for c in cust_data)/len(cust_data), sum(c["lon"] for c in cust_data)/len(cust_data)]
    m = folium.Map(location=centre, zoom_start=14, tiles="OpenStreetMap")
    if system and system.latitude:
        folium.Marker(location=[system.latitude,system.longitude], tooltip=f"💧 {system.name}", icon=folium.Icon(color="blue",icon="tint",prefix="fa")).add_to(m)
    for c in cust_data:
        popup_html = f"<div style='font-family:sans-serif;min-width:180px'><b>{c['name']}</b><br><span style='color:#64748b'>Acc: {c['account_no']}</span><hr style='margin:6px 0'><b>Status:</b> {c['status']}<br><b>Billed:</b> {currency} {c['billed']:,.0f}<br><b>Outstanding:</b> {currency} {c['outstanding']:,.0f}<br><b>Phone:</b> {c['phone']}</div>"
        folium.CircleMarker(location=[c["lat"],c["lon"]], radius=10, color="white", weight=2, fill=True, fill_color=c["color"], fill_opacity=0.85, tooltip=f"{c['name']} · {c['status']} · Owed: {currency} {c['outstanding']:,.0f}", popup=folium.Popup(popup_html,max_width=220)).add_to(m)
    st_folium(m, use_container_width=True, height=520)
    st.divider()
    st.markdown("### Water point summary")
    rows = [{"Account": c["account_no"], "Name": c["name"], "Status": c["status"], "Outstanding": f"{currency} {c['outstanding']:,.0f}", "Phone": c["phone"]} for c in cust_data]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
