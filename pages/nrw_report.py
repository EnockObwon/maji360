import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from core.database import get_session, DailyReading
from core.auth import require_login
from collections import defaultdict

def show():
    require_login()
    system_id   = st.session_state.get("selected_system_id")
    system_name = st.session_state.get("selected_system_name", "")
    if not system_id:
        st.warning("Please select a water system.")
        return
    st.markdown("## 📉 NRW Report")
    st.markdown(f"<span style='color:#64748b;font-size:13px'>{system_name} · Non-Revenue Water Analysis</span>", unsafe_allow_html=True)
    st.divider()
    session  = get_session()
    readings = session.query(DailyReading).filter(DailyReading.system_id==system_id, DailyReading.water_produced_m3>0).order_by(DailyReading.reading_date).all()
    session.close()
    if not readings:
        st.info("No readings available yet.")
        return
    monthly = defaultdict(lambda: {"pumped": 0.0, "consumed": 0.0})
    for r in readings:
        month = r.reading_date.strftime("%Y-%m")
        monthly[month]["pumped"]   += r.water_produced_m3 or 0
        monthly[month]["consumed"] += r.water_consumed_m3 or 0
    months   = sorted(monthly.keys())
    pumped   = [round(monthly[m]["pumped"],1)   for m in months]
    consumed = [round(monthly[m]["consumed"],1) for m in months]
    nrw_m3   = [round(p-c,1) for p,c in zip(pumped,consumed)]
    nrw_pct  = [round((n/p)*100,1) if p>0 else 0 for n,p in zip(nrw_m3,pumped)]
    bar_colors = ["#ef4444" if p>=20 else "#f59e0b" if p>=15 else "#22c55e" for p in nrw_pct]
    st.markdown("### Monthly NRW rate")
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Pumped (m³)", x=months, y=pumped, marker_color="#bfdbfe", opacity=0.7))
    fig.add_trace(go.Bar(name="To consumers (m³)", x=months, y=consumed, marker_color="#3b82f6"))
    fig.add_trace(go.Scatter(name="NRW %", x=months, y=nrw_pct, mode="lines+markers", yaxis="y2", line=dict(color="#ef4444",width=2.5), marker=dict(size=8,color=bar_colors,line=dict(color="white",width=1.5))))
    fig.add_hline(y=20, line_dash="dash", line_color="#ef4444", opacity=0.5, annotation_text="20% threshold", annotation_position="top right", yref="y2")
    fig.update_layout(barmode="group", height=380, margin=dict(t=20,b=20,l=0,r=0), plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="left",x=0),
        yaxis=dict(title="Volume (m³)",gridcolor="#f1f5f9"),
        yaxis2=dict(title="NRW %",overlaying="y",side="right",range=[0,max(nrw_pct)*1.3+5],gridcolor="#f1f5f9",showgrid=False),
        xaxis=dict(gridcolor="#f1f5f9"))
    st.plotly_chart(fig, use_container_width=True)
    st.markdown("### Monthly breakdown")
    rows = []
    for i,month in enumerate(months):
        pct = nrw_pct[i]
        status = "🔴 ALERT" if pct>=20 else "🟡 WARN" if pct>=15 else "🟢 OK"
        rows.append({"Month": month, "Pumped m³": pumped[i], "Consumed m³": consumed[i], "NRW m³": nrw_m3[i], "NRW %": f"{pct}%", "Status": status})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.divider()
    st.markdown("### Annual water balance")
    years = sorted(set(m[:4] for m in months))
    for year in years:
        ym  = [m for m in months if m.startswith(year)]
        yp  = sum(monthly[m]["pumped"]   for m in ym)
        yc  = sum(monthly[m]["consumed"] for m in ym)
        yn  = yp - yc
        ypc = round((yn/yp)*100,1) if yp>0 else 0
        st = "🔴 ALERT" if ypc>=20 else "🟡 WARN" if ypc>=15 else "🟢 OK"
        c1,c2,c3,c4 = globals()["st"].columns(4)
        with c1: globals()["st"].metric(f"{year} pumped",   f"{yp:.0f} m³")
        with c2: globals()["st"].metric(f"{year} consumed", f"{yc:.0f} m³")
        with c3: globals()["st"].metric(f"{year} NRW",      f"{yn:.0f} m³")
        with c4: globals()["st"].metric(f"{year} NRW %",    f"{ypc}% {st}")
