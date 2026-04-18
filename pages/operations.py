import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from core.database import get_session, DailyReading
from core.auth import require_login

def show():
    require_login()
    system_id   = st.session_state.get("selected_system_id")
    system_name = st.session_state.get("selected_system_name", "")
    if not system_id:
        st.warning("Please select a water system.")
        return
    st.markdown("## ⚙️ Operations")
    st.markdown(f"<span style='color:#64748b;font-size:13px'>{system_name} · Daily Production & Consumption</span>", unsafe_allow_html=True)
    st.divider()
    session  = get_session()
    readings = session.query(DailyReading).filter(DailyReading.system_id==system_id).order_by(DailyReading.reading_date).all()
    session.close()
    if not readings:
        st.info("No readings available yet.")
        return
    data = [{"date": r.reading_date, "pumped": r.water_produced_m3 or 0, "consumed": r.water_consumed_m3 or 0} for r in readings]
    df      = pd.DataFrame(data)
    df_pump = df[df["pumped"]   > 0]
    df_tank = df[df["consumed"] > 0]
    months_options = sorted(set(r["date"].strftime("%Y-%m") for r in data))
    selected_month = st.selectbox("Filter by month", ["All months"] + months_options)
    if selected_month != "All months":
        df_pump = df_pump[df_pump["date"].apply(lambda d: d.strftime("%Y-%m")) == selected_month]
        df_tank = df_tank[df_tank["date"].apply(lambda d: d.strftime("%Y-%m")) == selected_month]
    st.markdown("### Daily water produced — pump house (m³)")
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(x=df_pump["date"], y=df_pump["pumped"], mode="lines+markers", line=dict(color="#3b82f6",width=2), marker=dict(size=7,color="#3b82f6",line=dict(color="white",width=1.5)), fill="tozeroy", fillcolor="rgba(59,130,246,0.1)"))
    fig1.update_layout(height=300, margin=dict(t=10,b=10,l=0,r=0), plot_bgcolor="white", paper_bgcolor="white", yaxis=dict(title="Volume (m³)",gridcolor="#f1f5f9"), xaxis=dict(gridcolor="#f1f5f9"), showlegend=False)
    st.plotly_chart(fig1, use_container_width=True)
    st.divider()
    st.markdown("### Daily tank flow to consumers — tank outlet (m³)")
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=df_tank["date"], y=df_tank["consumed"], mode="lines+markers", line=dict(color="#22c55e",width=2), marker=dict(size=7,color="#22c55e",line=dict(color="white",width=1.5)), fill="tozeroy", fillcolor="rgba(34,197,94,0.1)"))
    fig2.update_layout(height=300, margin=dict(t=10,b=10,l=0,r=0), plot_bgcolor="white", paper_bgcolor="white", yaxis=dict(title="Volume (m³)",gridcolor="#f1f5f9"), xaxis=dict(gridcolor="#f1f5f9"), showlegend=False)
    st.plotly_chart(fig2, use_container_width=True)
    st.divider()
    st.markdown("### Pump vs Tank — NRW gap visualised")
    st.caption("Red shaded area between lines = operational NRW")
    df_merged = pd.merge(df_pump[["date","pumped"]], df_tank[["date","consumed"]], on="date", how="outer").fillna(0).sort_values("date")
    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(x=df_merged["date"], y=df_merged["pumped"], mode="lines+markers", name="Pumped (pump house)", line=dict(color="#3b82f6",width=2.5), marker=dict(size=6)))
    fig3.add_trace(go.Scatter(x=df_merged["date"], y=df_merged["consumed"], mode="lines+markers", name="To consumers (tank outlet)", line=dict(color="#22c55e",width=2.5), marker=dict(size=6), fill="tonexty", fillcolor="rgba(239,68,68,0.08)"))
    fig3.update_layout(height=340, margin=dict(t=10,b=10,l=0,r=0), plot_bgcolor="white", paper_bgcolor="white",
        yaxis=dict(title="Volume (m³)",gridcolor="#f1f5f9"), xaxis=dict(gridcolor="#f1f5f9"),
        legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="left",x=0))
    st.plotly_chart(fig3, use_container_width=True)
