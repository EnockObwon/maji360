import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from sqlalchemy import text as sql_text
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
    st.markdown(
        f"<span style='color:#64748b;font-size:13px'>"
        f"{system_name} · Financial Performance</span>",
        unsafe_allow_html=True
    )
    st.divider()

    session   = get_session()
    customers = session.query(Customer).filter_by(system_id=system_id, is_active=True).all()
    all_bills = session.query(Bill).filter_by(system_id=system_id).all()

    cust_bill_map = {}
    for c in customers:
        if not c.account_no:
            continue
        c_bills = session.query(Bill).filter_by(customer_id=c.id).all()
        cust_bill_map[c.id] = {
            "account_no": c.account_no,
            "name":       c.name,
            "bills": [{
                "bill_month":  b.bill_month,
                "units_m3":    b.units_m3    or 0,
                "amount":      b.amount      or 0,
                "amount_paid": b.amount_paid or 0,
                "is_paid":     b.is_paid,
            } for b in c_bills]
        }

    # Cash received by payment date — this is now the primary
    # "Collected" figure throughout the page (Option A).
    # It matches what mWater shows and what the Board expects.
    try:
        cash_rows = session.execute(sql_text(
            "SELECT TO_CHAR(paid_at, 'YYYY-MM') AS pm, SUM(amount) "
            "FROM payments "
            "WHERE system_id = :sid AND status = 'completed' "
            "AND paid_at IS NOT NULL "
            "GROUP BY pm"
        ), {"sid": system_id}).fetchall()
        cash_by_month = {r[0]: float(r[1] or 0) for r in cash_rows if r[0]}
    except Exception:
        cash_by_month = {}

    session.close()

    if not all_bills:
        st.info("No billing data available yet.")
        return

    # Period selector 
    bill_months_all   = {b.bill_month for b in all_bills if b.bill_month}
    payment_months    = set(cash_by_month.keys())
    all_period_months = bill_months_all | payment_months

    available_years = sorted(
        {m[:4] for m in all_period_months}, reverse=True
    )
    month_names = {
        "01":"January","02":"February","03":"March","04":"April",
        "05":"May","06":"June","07":"July","08":"August",
        "09":"September","10":"October","11":"November","12":"December",
    }
    col_p1, col_p2, _ = st.columns([2, 2, 3])
    with col_p1:
        sel_year = st.selectbox(
            "Year", ["All time"] + available_years, index=0, key="billing_year"
        )
    with col_p2:
        if sel_year == "All time":
            st.selectbox("Month", ["—"], key="billing_month", disabled=True)
            sel_period   = "All time"
            period_label = "All time"
        else:
            year_months = sorted(
                {m[5:7] for m in all_period_months
                 if m[:4] == sel_year}, reverse=True
            )
            month_opts = ["All months"] + [month_names[m] for m in year_months]
            sel_month  = st.selectbox("Month", month_opts, index=0, key="billing_month")
            if sel_month == "All months":
                sel_period   = sel_year
                period_label = sel_year
            else:
                month_num    = {v: k for k, v in month_names.items()}.get(sel_month, "")
                sel_period   = f"{sel_year}-{month_num}"
                period_label = f"{sel_month} {sel_year}"

    def _subset(period):
        if period == "All time":  return all_bills
        if len(period) == 4:      return [b for b in all_bills if b.bill_month and b.bill_month.startswith(period)]
        return [b for b in all_bills if b.bill_month == period]

    period_bills = _subset(sel_period)

    def _cash_received(period):
        """Cash received in this period by payment date."""
        if period == "All time":
            return sum(cash_by_month.values())
        if len(period) == 4:
            return sum(v for m, v in cash_by_month.items() if m.startswith(period))
        return cash_by_month.get(period, 0.0)

    cash_received = _cash_received(sel_period)

    # KPI totals 
    # "Collected" and "Collection rate" now use actual cash
    # received by payment date (Option A — matches mWater).
    # "Outstanding" = billed − cash received.
    # The FIFO allocation on bills (amount_paid) is still used
    # for the per-customer balances table and outstanding bar
    # chart — those need the debt position, not cash flow.
    total_billed      = sum(b.amount or 0 for b in period_bills)
    total_outstanding = total_billed - cash_received
    coll_rate         = round((cash_received / total_billed) * 100, 1) if total_billed > 0 else 0

    # Previous period for delta arrows
    sorted_months = sorted(all_period_months)

    def _prev(period):
        if period == "All time" or not sorted_months: return None
        if len(period) == 4: return str(int(period) - 1)
        idx = sorted_months.index(period) if period in sorted_months else -1
        return sorted_months[idx - 1] if idx > 0 else None

    prev_p = _prev(sel_period)
    if prev_p:
        prev_bills        = _subset(prev_p)
        prev_b            = sum(b.amount or 0 for b in prev_bills)
        prev_cash         = _cash_received(prev_p)
        prev_outstanding  = prev_b - prev_cash
        prev_rate         = round((prev_cash / prev_b) * 100, 1) if prev_b > 0 else 0
        d_billed          = total_billed      - prev_b
        d_collected       = cash_received     - prev_cash
        d_outstanding     = total_outstanding - prev_outstanding
        d_rate            = round(coll_rate   - prev_rate, 1)
        def _dfmt(v):
            if abs(v) >= 1_000_000: return f"{v/1_000_000:+.2f}M"
            if abs(v) >=    10_000: return f"{v/1_000:+.0f}K"
            return f"{v:+,.0f}"
    else:
        d_billed = d_collected = d_outstanding = d_rate = None

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Total billed",
                  f"{currency} {total_billed:,.0f}",
                  delta=_dfmt(d_billed) if d_billed is not None else None,
                  delta_color="off")
    with c2:
        st.metric("Total collected",
                  f"{currency} {cash_received:,.0f}",
                  delta=_dfmt(d_collected) if d_collected is not None else None)
    with c3:
        st.metric("Outstanding",
                  f"{currency} {total_outstanding:,.0f}",
                  delta=_dfmt(d_outstanding) if d_outstanding is not None else None,
                  delta_color="inverse")
    with c4:
        st.metric("Collection rate",
                  f"{coll_rate}%",
                  delta=f"{d_rate:+.1f}pp" if d_rate is not None else None)

    st.caption(
        f"Showing: **{period_label}**"
        + (f" · ↑↓ vs {prev_p}" if prev_p else "")
        + " · Collected = cash received by payment date, matching mWater"
    )
    st.divider()

    # Monthly aggregates 
    monthly_billed = defaultdict(float)
    for b in all_bills:
        if b.bill_month:
            monthly_billed[b.bill_month] += b.amount or 0

    if sel_period != "All time":
        all_months = [sel_period] if sel_period in monthly_billed or sel_period in cash_by_month else []
    else:
        all_months = sorted(set(monthly_billed.keys()) | set(cash_by_month.keys()))

    billed_vals      = [monthly_billed.get(m, 0)  for m in all_months]
    collected_vals   = [cash_by_month.get(m, 0)   for m in all_months]  # Option A: payment date
    outstanding_vals = [max(0, b - c) for b, c in zip(billed_vals, collected_vals)]
    rates            = [
        round((c / b) * 100, 1) if b > 0 else 0
        for b, c in zip(billed_vals, collected_vals)
    ]

    # Chart 1: Cash collected by month 
    st.markdown("### Cash collected by month")
    st.caption(
        "Green = cash received in that month · "
        "Pink = billed but not yet received · % = collection rate"
    )
    fig1 = go.Figure()
    fig1.add_trace(go.Bar(
        name="Cash collected", x=all_months, y=collected_vals,
        marker_color="#22c55e",
        text=[f"{r}%" for r in rates],
        textposition="inside", textfont=dict(color="white", size=11)
    ))
    fig1.add_trace(go.Bar(
        name="Outstanding", x=all_months, y=outstanding_vals,
        marker_color="#fca5a5"
    ))
    fig1.update_layout(
        barmode="stack", height=340,
        margin=dict(t=10, b=10, l=0, r=0),
        plot_bgcolor="white", paper_bgcolor="white",
        yaxis=dict(title=f"Amount ({currency})", gridcolor="#f1f5f9"),
        xaxis=dict(gridcolor="#f1f5f9"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)
    )
    st.plotly_chart(fig1, use_container_width=True)
    st.divider()

    # Chart 2: Customer consumption by month 
    st.markdown("### Customer consumption by month (m³)")
    st.caption("Grouped bars — each colour is one customer")
    colours     = ["#3b82f6","#22c55e","#f59e0b","#ef4444","#8b5cf6",
                   "#06b6d4","#f97316","#ec4899","#84cc16","#14b8a6"]
    bill_months = sorted(monthly_billed.keys())
    fig2 = go.Figure()
    for i, (cid, info) in enumerate(cust_bill_map.items()):
        monthly_cons = defaultdict(float)
        for b in info["bills"]:
            if b["bill_month"] and b["units_m3"]:
                monthly_cons[b["bill_month"]] += b["units_m3"]
        fig2.add_trace(go.Bar(
            name=info["name"], x=bill_months,
            y=[monthly_cons.get(m, 0) for m in bill_months],
            marker_color=colours[i % len(colours)]
        ))
    fig2.update_layout(
        barmode="group", height=380,
        margin=dict(t=10, b=10, l=0, r=0),
        plot_bgcolor="white", paper_bgcolor="white",
        yaxis=dict(title="Consumption (m³)", gridcolor="#f1f5f9"),
        xaxis=dict(gridcolor="#f1f5f9"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="left", x=0, font=dict(size=10))
    )
    st.plotly_chart(fig2, use_container_width=True)
    st.divider()

    # Chart 3: Monthly revenue trend 
    st.markdown("### Monthly revenue trend")
    st.caption("Blue = bills issued · Green = cash received in that month")
    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(
        name="Billed", x=all_months, y=billed_vals,
        mode="lines+markers", line=dict(color="#3b82f6", width=2.5),
        marker=dict(size=7), fill="tozeroy", fillcolor="rgba(59,130,246,0.08)"
    ))
    fig3.add_trace(go.Scatter(
        name="Cash collected", x=all_months, y=collected_vals,
        mode="lines+markers", line=dict(color="#22c55e", width=2.5),
        marker=dict(size=7), fill="tozeroy", fillcolor="rgba(34,197,94,0.08)"
    ))
    fig3.update_layout(
        height=300, margin=dict(t=10, b=10, l=0, r=0),
        plot_bgcolor="white", paper_bgcolor="white",
        yaxis=dict(title=f"Amount ({currency})", gridcolor="#f1f5f9"),
        xaxis=dict(gridcolor="#f1f5f9", tickmode="array",
                   tickvals=all_months, ticktext=all_months),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)
    )
    st.plotly_chart(fig3, use_container_width=True)
    st.divider()

    # Customer account balances table 
    # Uses FIFO allocation (amount_paid) for the per-customer
    # outstanding position — this is correct for debt tracking.
    st.markdown("### Customer account balances")
    rows = []
    for cid, info in cust_bill_map.items():
        billed = sum(b["amount"]      for b in info["bills"])
        paid   = sum(b["amount_paid"] for b in info["bills"])
        owed   = billed - paid
        rate   = round((paid / billed) * 100, 0) if billed > 0 else 0
        rows.append({
            "Account":     info["account_no"],
            "Customer":    info["name"],
            "Billed":      f"{currency} {billed:,.0f}",
            "Paid":        f"{currency} {paid:,.0f}",
            "Outstanding": f"{currency} {owed:,.0f}",
            "Rate":        f"{rate:.0f}%",
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.divider()

    # Monthly cash flow summary table 
    st.markdown("### Monthly cash flow summary")
    st.caption(
        "Billed = bills issued that month. "
        "Collected = cash received by payment date (matches mWater). "
        "Rate = cash received ÷ billed."
    )

    if sel_period == "All time":
        flow_months = sorted(set(monthly_billed.keys()) | set(cash_by_month.keys()))
    elif len(sel_period) == 4:
        flow_months = sorted({
            m for m in (set(monthly_billed.keys()) | set(cash_by_month.keys()))
            if m.startswith(sel_period)
        })
    else:
        flow_months = [sel_period]

    flow_rows = []
    for m in flow_months:
        b    = monthly_billed.get(m, 0)
        cash = cash_by_month.get(m, 0)
        rate = round((cash / b) * 100, 1) if b > 0 else 0
        flow_rows.append({
            "Month":     m,
            "Billed":    f"{currency} {b:,.0f}"    if b    > 0 else "—",
            "Collected": f"{currency} {cash:,.0f}" if cash > 0 else "—",
            "Rate":      f"{rate}%"                if b    > 0 else "—",
        })
    if flow_rows:
        st.dataframe(pd.DataFrame(flow_rows), use_container_width=True, hide_index=True)
