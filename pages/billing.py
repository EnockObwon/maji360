import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from core.database import get_session, Bill, Customer
from core.auth import require_login
from collections import defaultdict

def show():
    require_login()
    system_id   = st.session_state.get("selected_system_id")
    system_name = st.session_state.get("selected_system_name", "")
    currency    = st.session_state.get("currency", "UGX")
    if not system_id:
        st.warning("Please select a water system.")
        return
    st.markdown("## 💰 Billing & Revenue")
    st.markdown(f"<span style='color:#64748b;font-size:13px'>{system_name} · Financial Performance</span>", unsafe_allow_html=True)
    st.divider()
    session   = get_session()
    customers = session.query(Customer).filter_by(system_id=system_id,is_active=True).all()
    all_bills = session.query(Bill).filter_by(system_id=system_id).all()
    session.close()
    if not all_bills:
        st.info("No billing data available yet.")
        return
    monthly_billed = defaultdict(float)
    monthly_paid   = defaultdict(float)
    for b in all_bills:
        if b.amount and b.bill_month:
            monthly_billed[b.bill_month] += b.amount
            if b.is_paid: monthly_paid[b.bill_month] += b.amount
    months        = sorted(monthly_billed.keys())
    total_billed  = sum(b.amount or 0 for b in all_bills)
    total_paid    = sum(b.amount or 0 for b in all_bills if b.is_paid)
    total_owed    = total_billed - total_paid
    coll_rate     = round((total_paid/total_billed)*100,1) if total_billed>0 else 0
    c1,c2,c3,c4  = st.columns(4)
    with c1: st.metric("Total billed",     f"{currency} {total_billed:,.0f}")
    with c2: st.metric("Total collected",  f"{currency} {total_paid:,.0f}")
    with c3: st.metric("Outstanding",      f"{currency} {total_owed:,.0f}")
    with c4: st.metric("Collection rate",  f"{coll_rate}%")
    st.divider()
    billed_vals      = [monthly_billed[m] for m in months]
    paid_vals        = [monthly_paid.get(m,0) for m in months]
    outstanding_vals = [monthly_billed[m]-monthly_paid.get(m,0) for m in months]
    rates            = [round((monthly_paid.get(m,0)/monthly_billed[m])*100,1) if monthly_billed[m]>0 else 0 for m in months]
    st.markdown("### Collection rate by month")
    st.caption("Stacked bars — paid vs outstanding per month")
    fig1 = go.Figure()
    fig1.add_trace(go.Bar(name="Collected", x=months, y=paid_vals, marker_color="#22c55e", text=[f"{r}%" for r in rates], textposition="inside", textfont=dict(color="white",size=11)))
    fig1.add_trace(go.Bar(name="Outstanding", x=months, y=outstanding_vals, marker_color="#fca5a5"))
    fig1.update_layout(barmode="stack", height=340, margin=dict(t=10,b=10,l=0,r=0), plot_bgcolor="white", paper_bgcolor="white",
        yaxis=dict(title=f"Amount ({currency})",gridcolor="#f1f5f9"), xaxis=dict(gridcolor="#f1f5f9"),
        legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="left",x=0))
    st.plotly_chart(fig1, use_container_width=True)
    st.divider()
    st.markdown("### Customer consumption by month (m³)")
    st.caption("Grouped bars — each colour is one customer")
    cust_monthly = defaultdict(lambda: defaultdict(float))
    cust_names   = {}
    colours = ["#3b82f6","#22c55e","#f59e0b","#ef4444","#8b5cf6","#06b6d4","#f97316","#ec4899","#84cc16","#14b8a6"]
    for c in customers:
        if not c.account_no or not c.account_no.startswith("4"): continue
        cust_names[c.id] = c.name
        for b in c.bills:
            if b.bill_month and b.units_m3:
                cust_monthly[c.id][b.bill_month] += b.units_m3
    fig2 = go.Figure()
    for i,(cid,mc) in enumerate(cust_monthly.items()):
        fig2.add_trace(go.Bar(name=cust_names.get(cid,str(cid)), x=months, y=[mc.get(m,0) for m in months], marker_color=colours[i%len(colours)]))
    fig2.update_layout(barmode="group", height=380, margin=dict(t=10,b=10,l=0,r=0), plot_bgcolor="white", paper_bgcolor="white",
        yaxis=dict(title="Consumption (m³)",gridcolor="#f1f5f9"), xaxis=dict(gridcolor="#f1f5f9"),
        legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="left",x=0,font=dict(size=10)))
    st.plotly_chart(fig2, use_container_width=True)
    st.divider()
    st.markdown("### Monthly revenue trend")
    st.caption("Billed vs collected over time")
    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(name="Billed", x=months, y=billed_vals, mode="lines+markers", line=dict(color="#3b82f6",width=2.5), marker=dict(size=7), fill="tozeroy", fillcolor="rgba(59,130,246,0.08)"))
    fig3.add_trace(go.Scatter(name="Collected", x=months, y=paid_vals, mode="lines+markers", line=dict(color="#22c55e",width=2.5), marker=dict(size=7), fill="tozeroy", fillcolor="rgba(34,197,94,0.08)"))
    fig3.update_layout(height=300, margin=dict(t=10,b=10,l=0,r=0), plot_bgcolor="white", paper_bgcolor="white",
        yaxis=dict(title=f"Amount ({currency})",gridcolor="#f1f5f9"), xaxis=dict(gridcolor="#f1f5f9"),
        legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="left",x=0))
    st.plotly_chart(fig3, use_container_width=True)
    st.divider()
    st.markdown("### Customer account balances")
    rows = []
    for c in customers:
        if not c.account_no or not c.account_no.startswith("4"): continue
        billed = sum(b.amount or 0 for b in c.bills)
        paid   = sum(b.amount or 0 for b in c.bills if b.is_paid)
        owed   = billed - paid
        rate   = round((paid/billed)*100,0) if billed>0 else 0
        rows.append({"Account": c.account_no, "Customer": c.name, "Billed": f"{currency} {billed:,.0f}", "Paid": f"{currency} {paid:,.0f}", "Outstanding": f"{currency} {owed:,.0f}", "Rate": f"{rate:.0f}%"})
    if rows: st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
