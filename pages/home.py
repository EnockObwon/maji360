import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from collections import defaultdict
from core.database import get_session, DailyReading, Bill, NRWRecord, Customer
from core.auth import require_login


def show():
    require_login()

    system_id   = st.session_state.get("selected_system_id")
    system_name = st.session_state.get("selected_system_name", "")
    currency    = st.session_state.get("currency", "UGX")

    if not system_id:
        st.warning("Please select a water system.")
        return

    session = get_session()

    all_bills = session.query(Bill).filter_by(system_id=system_id).all()

    last_reading = session.query(DailyReading).filter_by(
        system_id=system_id
    ).order_by(DailyReading.synced_at.desc()).first()
    last_sync = (
        last_reading.synced_at.strftime("%d %b %Y %H:%M")
        if last_reading and last_reading.synced_at else "Never"
    )

    total_customers = session.query(Customer).filter_by(
        system_id=system_id, is_active=True
    ).count()

    # Header
    st.markdown(f"## {system_name}")
    st.markdown(
        f"<span style='font-size:13px; color:#64748b'>"
        f"Last synced: {last_sync} UTC</span>",
        unsafe_allow_html=True
    )
    st.divider()

    # Period selector 
    available_years = sorted(
        {b.bill_month[:4] for b in all_bills if b.bill_month},
        reverse=True
    )
    month_names = {
        "01": "January",  "02": "February",
        "03": "March",    "04": "April",
        "05": "May",      "06": "June",
        "07": "July",     "08": "August",
        "09": "September","10": "October",
        "11": "November", "12": "December",
    }

    col_p1, col_p2, col_p3 = st.columns([2, 2, 3])
    with col_p1:
        sel_year = st.selectbox(
            "Year",
            options = ["All time"] + available_years,
            index   = 0,
            key     = "home_year"
        )
    with col_p2:
        if sel_year == "All time":
            st.selectbox("Month", ["—"], key="home_month", disabled=True)
            selected_period = "All time"
            period_label    = "All time"
        else:
            year_months = sorted(
                {b.bill_month[5:7] for b in all_bills
                 if b.bill_month and b.bill_month[:4] == sel_year},
                reverse=True
            )
            month_opts = ["All months"] + [month_names[m] for m in year_months]
            sel_month  = st.selectbox("Month", month_opts, index=0, key="home_month")
            if sel_month == "All months":
                selected_period = sel_year
                period_label    = sel_year
            else:
                month_num       = {v: k for k, v in month_names.items()}.get(sel_month, "")
                selected_period = f"{sel_year}-{month_num}"
                period_label    = f"{sel_month} {sel_year}"

    # Filter bills 
    if selected_period == "All time":
        period_bills = all_bills
    elif len(selected_period) == 4:
        period_bills = [b for b in all_bills if b.bill_month and b.bill_month.startswith(selected_period)]
    else:
        period_bills = [b for b in all_bills if b.bill_month == selected_period]

    total_billed    = sum(b.amount      or 0 for b in period_bills)
    total_paid      = sum(b.amount_paid or 0 for b in period_bills)
    collection_rate = round((total_paid / total_billed) * 100, 1) if total_billed > 0 else 0

    # Previous period for deltas 
    sorted_months = sorted({b.bill_month for b in all_bills if b.bill_month})
    if selected_period not in (None, "All time") and len(selected_period) == 7:
        idx = sorted_months.index(selected_period) if selected_period in sorted_months else -1
        if idx > 0:
            prev_month = sorted_months[idx - 1]
            prev_bills = [b for b in all_bills if b.bill_month == prev_month]
            prev_billed = sum(b.amount      or 0 for b in prev_bills)
            prev_paid   = sum(b.amount_paid or 0 for b in prev_bills)
            prev_rate   = round((prev_paid / prev_billed) * 100, 1) if prev_billed > 0 else 0
        else:
            prev_billed = prev_paid = prev_rate = None
    else:
        prev_billed = prev_paid = prev_rate = None

    def _delta(curr, prev):
        if prev is None or prev == 0:
            return None
        diff = curr - prev
        if isinstance(curr, float) and curr < 200:
            return f"{diff:+.1f}%"
        return f"{diff:+,.0f}"

    # NRW 
    nrw_q = session.query(NRWRecord).filter(NRWRecord.system_id == system_id, NRWRecord.water_produced > 0)
    if selected_period == "All time":
        nrw_q = nrw_q.filter(NRWRecord.nrw_percent > 0).order_by(NRWRecord.month.desc())
    elif len(selected_period) == 4:
        nrw_q = nrw_q.filter(NRWRecord.month.like(f"{selected_period}%")).order_by(NRWRecord.month.desc())
    else:
        nrw_q = nrw_q.filter(NRWRecord.month == selected_period)
    latest_nrw = nrw_q.first()

    # Previous NRW for delta
    prev_nrw = None
    if latest_nrw and len(selected_period) == 7:
        idx = sorted_months.index(selected_period) if selected_period in sorted_months else -1
        if idx > 0:
            prev_nrw = session.query(NRWRecord).filter(
                NRWRecord.system_id == system_id,
                NRWRecord.month     == sorted_months[idx - 1]
            ).first()

    # Outstanding balances 
    customers = session.query(Customer).filter_by(system_id=system_id, is_active=True).all()
    outstanding_data = []
    for c in customers:
        c_bills = session.query(Bill).filter_by(customer_id=c.id).all()
        billed  = sum(b.amount      or 0 for b in c_bills)
        paid    = sum(b.amount_paid or 0 for b in c_bills)
        owed    = billed - paid
        if owed > 0:
            outstanding_data.append({"name": c.name, "owed": owed})
    outstanding_data.sort(key=lambda x: x["owed"], reverse=True)

    # Recent readings 
    recent_readings = session.query(DailyReading).filter(
        DailyReading.system_id == system_id
    ).order_by(DailyReading.reading_date.desc()).limit(14).all()

    session.close()

    # NRW banner 
    if latest_nrw:
        nrw_pct = latest_nrw.nrw_percent or 0
        if nrw_pct >= 20:
            st.markdown(
                f'<div class="alert-banner">🔴 NRW ALERT — {latest_nrw.month}: '
                f'{nrw_pct:.1f}% water unaccounted (threshold: 20%)</div>',
                unsafe_allow_html=True
            )
        elif nrw_pct >= 15:
            st.markdown(
                f'<div class="warn-banner">🟡 NRW WARNING — {latest_nrw.month}: '
                f'{nrw_pct:.1f}% water unaccounted</div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f'<div class="ok-banner">🟢 NRW OK — {latest_nrw.month}: '
                f'{nrw_pct:.1f}% within acceptable range</div>',
                unsafe_allow_html=True
            )
    else:
        st.info("No readings synced yet for this system.")

    # KPI cards with delta arrows 
    st.markdown(
        f"### System overview "
        f"<span style='font-size:14px;font-weight:400;color:#64748b'>"
        f"— {period_label}</span>",
        unsafe_allow_html=True
    )

    def _fmt(val):
        if val >= 1_000_000: return f"{currency} {val/1_000_000:.2f}M"
        if val >= 10_000:    return f"{currency} {val/1_000:.0f}K"
        return f"{currency} {val:,.0f}"

    nrw_pct     = latest_nrw.nrw_percent if latest_nrw else None
    prev_nrw_pct = prev_nrw.nrw_percent  if prev_nrw  else None

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        nrw_delta = _delta(nrw_pct, prev_nrw_pct) if nrw_pct and prev_nrw_pct else None
        st.metric("NRW rate",        f"{nrw_pct:.1f}%" if nrw_pct else "—", delta=nrw_delta,
                  delta_color="inverse")
    with c2:
        st.metric("Customers",       total_customers)
    with c3:
        st.metric("Total billed",    _fmt(total_billed),
                  delta=_delta(total_billed, prev_billed) if prev_billed else None)
    with c4:
        st.metric("Collected",       _fmt(total_paid),
                  delta=_delta(total_paid, prev_paid) if prev_paid else None)
    with c5:
        st.metric("Collection rate", f"{collection_rate}%",
                  delta=_delta(collection_rate, prev_rate) if prev_rate else None)

    st.divider()

    # Two-column layout 
    col_left, col_right = st.columns(2)

    # Outstanding balances — horizontal bar chart
    with col_left:
        st.markdown("### Outstanding balances")
        st.caption("All-time net balance per customer")

        if outstanding_data:
            names  = [d["name"]  for d in outstanding_data]
            values = [d["owed"]  for d in outstanding_data]
            max_v  = max(values) if values else 1

            # Colour by severity: green < 50K, amber < 200K, red >= 200K
            colours = []
            for v in values:
                if v >= 200_000:   colours.append("#ef4444")
                elif v >= 50_000:  colours.append("#f59e0b")
                else:              colours.append("#22c55e")

            fig_bar = go.Figure(go.Bar(
                x            = values,
                y            = names,
                orientation  = "h",
                marker_color = colours,
                text         = [f"{currency} {v:,.0f}" for v in values],
                textposition = "outside",
                textfont     = dict(size=11),
            ))
            fig_bar.update_layout(
                height        = max(220, len(names) * 42),
                margin        = dict(t=4, b=4, l=4, r=80),
                plot_bgcolor  = "white",
                paper_bgcolor = "white",
                xaxis         = dict(
                    showticklabels=False,
                    showgrid=False,
                    range=[0, max_v * 1.35]
                ),
                yaxis         = dict(autorange="reversed", showgrid=False),
            )
            st.plotly_chart(fig_bar, use_container_width=True)

            # Severity legend
            st.markdown(
                "<span style='font-size:11px;color:#64748b'>"
                "🟢 &lt;50K &nbsp; 🟡 50K–200K &nbsp; 🔴 &gt;200K</span>",
                unsafe_allow_html=True
            )
        else:
            if total_customers > 0:
                st.success("✓ All customers are up to date.")
            else:
                st.info("No customers registered yet.")

    # Recent readings — bars (pumped) + dots (tank)
    with col_right:
        st.markdown("### Daily water readings")
        st.caption(
            "🟢 Bars = daily tank outlet readings  · "
            "🔵 Dots = pump house (only triggered when tank level drops)"
        )

        if recent_readings:
            # Separate pumped (daily) from consumed (irregular)
            pump_dates = []
            pump_vals  = []
            tank_dates = []
            tank_vals  = []

            for r in sorted(recent_readings,
                            key=lambda x: x.reading_date):
                d = r.reading_date.strftime("%d %b")
                if r.water_produced_m3 and r.water_produced_m3 > 0:
                    pump_dates.append(d)
                    pump_vals.append(r.water_produced_m3)
                if r.water_consumed_m3 and r.water_consumed_m3 > 0:
                    tank_dates.append(d)
                    tank_vals.append(r.water_consumed_m3)

            fig_flow = go.Figure()

            # Tank outlet — daily bars (regular, every day)
            if tank_dates:
                fig_flow.add_trace(go.Bar(
                    name         = "Tank outlet (m³)",
                    x            = tank_dates,
                    y            = tank_vals,
                    marker_color = "rgba(34,197,94,0.75)",
                    marker_line  = dict(color="#16a34a", width=1),
                ))

            # Pump house — dots only (irregular, only when tank level drops)
            if pump_dates:
                fig_flow.add_trace(go.Scatter(
                    name      = "Pump house (m³)",
                    x         = pump_dates,
                    y         = pump_vals,
                    mode      = "markers",
                    marker    = dict(
                        color  = "#3b82f6",
                        size   = 10,
                        symbol = "circle",
                        line   = dict(color="white", width=2)
                    ),
                    connectgaps = False,
                ))

            fig_flow.update_layout(
                height        = 260,
                margin        = dict(t=4, b=4, l=0, r=0),
                plot_bgcolor  = "white",
                paper_bgcolor = "white",
                barmode       = "overlay",
                yaxis         = dict(
                    title     = "m³",
                    gridcolor = "#f1f5f9"
                ),
                xaxis         = dict(
                    gridcolor = "#f1f5f9",
                    tickangle = -35,
                ),
                legend        = dict(
                    orientation = "h",
                    yanchor     = "bottom",
                    y           = 1.02,
                    xanchor     = "left",
                    x           = 0,
                    font        = dict(size=11)
                ),
            )
            st.plotly_chart(fig_flow, use_container_width=True)
        else:
            st.info("No readings synced yet.")

    st.divider()

    # NRW gauge 
    if latest_nrw:
        st.markdown("### NRW gauge")
        st.caption(f"Non-revenue water — {latest_nrw.month} · Target: below 20%")

        nrw_val = latest_nrw.nrw_percent or 0

        fig_gauge = go.Figure(go.Indicator(
            mode  = "gauge+number+delta",
            value = nrw_val,
            delta = {
                "reference": prev_nrw_pct,
                "increasing": {"color": "#ef4444"},
                "decreasing": {"color": "#22c55e"},
            } if prev_nrw_pct else {},
            number = {"suffix": "%", "font": {"size": 36}},
            gauge  = {
                "axis": {
                    "range": [0, 60],
                    "tickwidth": 1,
                    "tickcolor": "#94a3b8",
                    "tickvals": [0, 10, 20, 30, 40, 50, 60],
                },
                "bar": {"color": "#ef4444" if nrw_val >= 20 else "#22c55e", "thickness": 0.25},
                "bgcolor": "white",
                "borderwidth": 0,
                "steps": [
                    {"range": [0,  20], "color": "#f0fdf4"},
                    {"range": [20, 35], "color": "#fef9c3"},
                    {"range": [35, 60], "color": "#fef2f2"},
                ],
                "threshold": {
                    "line":  {"color": "#f59e0b", "width": 3},
                    "thickness": 0.8,
                    "value": 20,
                },
            },
            title = {"text": "NRW %", "font": {"size": 14, "color": "#64748b"}},
        ))
        fig_gauge.update_layout(
            height        = 260,
            margin        = dict(t=20, b=10, l=40, r=40),
            paper_bgcolor = "white",
        )
        st.plotly_chart(fig_gauge, use_container_width=True)
