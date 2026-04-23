import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from core.database import get_session, DailyReading
from core.auth import require_login
from collections import defaultdict
from sqlalchemy import text as sql_text


def get_monthly_storage_changes(system_id: int) -> dict:
    session = get_session()
    try:
        levels = session.execute(sql_text(
            "SELECT DATE(reading_date) as rdate, "
            "volume_m3 "
            "FROM tank_levels "
            "WHERE system_id = :sid "
            "ORDER BY reading_date"
        ), {"sid": system_id}).fetchall()
    except Exception:
        levels = []
    session.close()

    if not levels:
        return {}

    monthly_readings = defaultdict(list)
    for l in levels:
        date_str = str(l[0])[:10]
        month    = date_str[:7]
        monthly_readings[month].append(float(l[1]))

    storage_changes = {}
    for month, vols in monthly_readings.items():
        if len(vols) >= 2:
            change = round(vols[-1] - vols[0], 2)
            storage_changes[month] = change

    return storage_changes


def get_maintenance_events(system_id: int) -> dict:
    session = get_session()
    try:
        rows = session.execute(sql_text(
            "SELECT incident_date, category "
            "FROM maintenance "
            "WHERE system_id = :sid "
            "ORDER BY incident_date"
        ), {"sid": system_id}).fetchall()
        result = [
            {"incident_date": str(r[0])[:7],
             "category":      r[1]}
            for r in rows
        ]
    except Exception:
        result = []
    session.close()

    events_by_month = defaultdict(list)
    for r in result:
        events_by_month[
            r["incident_date"]
        ].append(r["category"])

    return dict(events_by_month)


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

    st.markdown("## 📉 NRW Report")
    st.markdown(
        f"<span style='color:#64748b;font-size:13px'>"
        f"{system_name} · Non-Revenue Water Analysis"
        f"</span>",
        unsafe_allow_html=True
    )
    st.divider()

    # ── Fetch all readings ─────────────────────────────
    session  = get_session()
    readings = session.query(DailyReading).filter(
        DailyReading.system_id == system_id
    ).order_by(DailyReading.reading_date).all()
    session.close()

    if not readings:
        st.info("No readings available yet.")
        return

    # ── Monthly aggregates ─────────────────────────────
    monthly = defaultdict(
        lambda: {"pumped": 0.0, "consumed": 0.0}
    )
    for r in readings:
        month = r.reading_date.strftime("%Y-%m")
        if r.water_produced_m3 and \
           r.water_produced_m3 > 0:
            monthly[month]["pumped"]   += \
                r.water_produced_m3
        if r.water_consumed_m3 and \
           r.water_consumed_m3 > 0:
            monthly[month]["consumed"] += \
                r.water_consumed_m3

    months = sorted(
        m for m in monthly.keys()
        if monthly[m]["pumped"] > 0
    )

    if not months:
        st.info("No pump readings available yet.")
        return

    pumped   = [
        round(monthly[m]["pumped"],   1)
        for m in months
    ]
    consumed = [
        round(monthly[m]["consumed"], 1)
        for m in months
    ]
    nrw_m3  = [
        round(p - c, 1)
        for p, c in zip(pumped, consumed)
    ]
    nrw_pct = [
        round((n / p) * 100, 1)
        if p > 0 else 0
        for n, p in zip(nrw_m3, pumped)
    ]

    # ── Storage changes and maintenance ───────────────
    storage_changes     = get_monthly_storage_changes(
        system_id
    )
    maintenance_events  = get_maintenance_events(
        system_id
    )
    has_adjusted        = len(storage_changes) > 0

    # ── Adjusted NRW ───────────────────────────────────
    adj_nrw_pct = []
    adj_nrw_m3  = []

    for i, month in enumerate(months):
        if month in storage_changes:
            change  = storage_changes[month]
            adj     = round(nrw_m3[i] - change, 1)
            adj_pct = round(
                (adj / pumped[i]) * 100, 1
            ) if pumped[i] > 0 else 0
            adj_nrw_m3.append(adj)
            adj_nrw_pct.append(adj_pct)
        else:
            adj_nrw_m3.append(None)
            adj_nrw_pct.append(None)

    adj_months = [
        m for m, v in zip(months, adj_nrw_pct)
        if v is not None
    ]
    adj_vals = [
        v for v in adj_nrw_pct if v is not None
    ]

    # ── KPI cards ──────────────────────────────────────
    total_pumped   = sum(pumped)
    total_consumed = sum(consumed)
    total_nrw      = round(
        total_pumped - total_consumed, 1
    )
    overall_nrw    = round(
        (total_nrw / total_pumped) * 100, 1
    ) if total_pumped > 0 else 0

    latest_nrw = nrw_pct[-1] if nrw_pct else 0
    latest_adj = next(
        (v for v in reversed(adj_nrw_pct)
         if v is not None), None
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(
            "Total pumped",
            f"{total_pumped:.0f} m³"
        )
    with c2:
        st.metric(
            "Total consumed",
            f"{total_consumed:.0f} m³"
        )
    with c3:
        st.metric("Overall NRW", f"{overall_nrw}%")
    with c4:
        if latest_adj is not None:
            st.metric(
                "Latest adj NRW",
                f"{latest_adj}%",
                delta=f"{round(latest_adj - latest_nrw, 1)}% vs operational"
            )
        else:
            st.metric("Latest NRW", f"{latest_nrw}%")

    if has_adjusted:
        st.success(
            "✓ Adjusted NRW available for months "
            "with daily tank level readings."
        )
    else:
        st.info(
            "ℹ️ Record 2+ tank level dips per month "
            "in Field Ops to enable adjusted NRW."
        )

    st.divider()

    # ── Chart 1: Pump vs Tank grouped bar ─────────────
    st.markdown("### Pump vs tank — NRW gap")
    st.caption(
        "Blue = pumped · Green = to consumers · "
        "Red line = operational NRW % · "
        "Orange dotted = adjusted NRW %"
    )

    fig1 = go.Figure()
    fig1.add_trace(go.Bar(
        name         = "Pumped (m³)",
        x            = months,
        y            = pumped,
        marker_color = "#bfdbfe",
        opacity      = 0.8
    ))
    fig1.add_trace(go.Bar(
        name         = "To consumers (m³)",
        x            = months,
        y            = consumed,
        marker_color = "#22c55e",
        opacity      = 0.8
    ))
    fig1.add_trace(go.Scatter(
        name   = "Operational NRW %",
        x      = months,
        y      = nrw_pct,
        mode   = "lines+markers",
        yaxis  = "y2",
        line   = dict(color="#ef4444", width=2.5),
        marker = dict(
            size  = 8,
            color = [
                "#ef4444" if p >= 20 else
                "#f59e0b" if p >= 15 else
                "#22c55e"
                for p in nrw_pct
            ],
            line  = dict(color="white", width=1.5)
        )
    ))

    if has_adjusted and adj_months:
        fig1.add_trace(go.Scatter(
            name   = "Adjusted NRW %",
            x      = adj_months,
            y      = adj_vals,
            mode   = "lines+markers",
            yaxis  = "y2",
            line   = dict(
                color="#f97316",
                width=2.5,
                dash="dot"
            ),
            marker = dict(size=8)
        ))

    max_nrw = max(nrw_pct) if nrw_pct else 100
    fig1.add_hline(
        y                   = 20,
        line_dash           = "dash",
        line_color          = "#ef4444",
        opacity             = 0.4,
        annotation_text     = "20% threshold",
        annotation_position = "top right",
        yref                = "y2"
    )
    fig1.update_layout(
        barmode       = "group",
        height        = 400,
        margin        = dict(t=20, b=10, l=0, r=0),
        plot_bgcolor  = "white",
        paper_bgcolor = "white",
        yaxis         = dict(
            title     = "Volume (m³)",
            gridcolor = "#f1f5f9"
        ),
        yaxis2 = dict(
            title      = "NRW %",
            overlaying = "y",
            side       = "right",
            range      = [0, max_nrw * 1.3 + 10],
            showgrid   = False
        ),
        xaxis  = dict(
            gridcolor = "#f1f5f9",
            type      = "category"
        ),
        legend = dict(
            orientation = "h",
            yanchor     = "bottom",
            y           = 1.02,
            xanchor     = "left",
            x           = 0
        )
    )
    st.plotly_chart(fig1, use_container_width=True)

    st.divider()

    # ── Chart 2: NRW trend with maintenance ───────────
    st.markdown("### NRW trend over time")
    st.caption(
        "Red = operational NRW · "
        "Orange dotted = adjusted NRW · "
        "Purple markers = maintenance events"
    )

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        name      = "Operational NRW %",
        x         = months,
        y         = nrw_pct,
        mode      = "lines+markers",
        line      = dict(color="#ef4444", width=2.5),
        marker    = dict(size=8),
        fill      = "tozeroy",
        fillcolor = "rgba(239,68,68,0.08)"
    ))

    if has_adjusted and adj_months:
        fig2.add_trace(go.Scatter(
            name      = "Adjusted NRW %",
            x         = adj_months,
            y         = adj_vals,
            mode      = "lines+markers",
            line      = dict(
                color="#f97316",
                width=2.5,
                dash="dot"
            ),
            marker    = dict(size=8),
            fill      = "tozeroy",
            fillcolor = "rgba(249,115,22,0.05)"
        ))

    # Add maintenance event markers as scatter points
    if maintenance_events:
        maint_x = []
        maint_y = []
        maint_text = []
        for month in months:
            if month in maintenance_events:
                idx    = months.index(month)
                events = maintenance_events[month]
                maint_x.append(month)
                maint_y.append(nrw_pct[idx])
                maint_text.append(
                    f"🔧 {len(events)} maintenance: "
                    + ", ".join(events[:2])
                )

        if maint_x:
            fig2.add_trace(go.Scatter(
                name         = "Maintenance event",
                x            = maint_x,
                y            = maint_y,
                mode         = "markers",
                marker       = dict(
                    symbol = "diamond",
                    size   = 14,
                    color  = "#8b5cf6",
                    line   = dict(
                        color="white", width=2
                    )
                ),
                text         = maint_text,
                hovertemplate = "%{text}<extra></extra>"
            ))

    fig2.add_hline(
        y                   = 20,
        line_dash           = "dash",
        line_color          = "#ef4444",
        opacity             = 0.5,
        annotation_text     = "20% threshold",
        annotation_position = "top right"
    )
    fig2.update_layout(
        height        = 320,
        margin        = dict(t=20, b=10, l=0, r=0),
        plot_bgcolor  = "white",
        paper_bgcolor = "white",
        yaxis         = dict(
            title     = "NRW %",
            gridcolor = "#f1f5f9"
        ),
        xaxis  = dict(
            gridcolor = "#f1f5f9",
            type      = "category"
        ),
        legend = dict(
            orientation = "h",
            yanchor     = "bottom",
            y           = 1.02,
            xanchor     = "left",
            x           = 0
        )
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    # ── Monthly breakdown table ────────────────────────
    st.markdown("### Monthly breakdown")

    rows = []
    for i, month in enumerate(months):
        storage  = storage_changes.get(month)
        adj_pct  = adj_nrw_pct[i]
        m_events = maintenance_events.get(month, [])
        status   = (
            "🔴 ALERT" if nrw_pct[i] >= 20 else
            "🟡 WARN"  if nrw_pct[i] >= 15 else
            "🟢 OK"
        )
        rows.append({
            "Month":        month,
            "Pumped m³":    pumped[i],
            "Consumed m³":  consumed[i],
            "NRW m³":       nrw_m3[i],
            "NRW %":        f"{nrw_pct[i]}%",
            "Storage Δ m³": f"{storage:+.1f}"
                            if storage is not None
                            else "—",
            "Adj NRW %":    f"{adj_pct}%"
                            if adj_pct is not None
                            else "—",
            "Maintenance":  f"🔧 {len(m_events)}"
                            if m_events else "—",
            "Status":       status
        })

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True
    )

    st.markdown("""
    <div style='font-size:12px;color:#94a3b8;
    margin-top:8px'>
    ℹ️ Storage Δ = change in tank volume within
    that month. Requires 2+ tank level readings
    per month. 🔧 = maintenance events recorded
    that month — hover on purple diamonds in chart
    for details.
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # ── Annual water balance ───────────────────────────
    st.markdown("### Annual water balance")

    years = sorted(set(m[:4] for m in months))
    cols  = st.columns(len(years))

    for i, year in enumerate(years):
        year_months = [
            m for m in months if m[:4] == year
        ]
        yr_pumped   = sum(
            monthly[m]["pumped"]
            for m in year_months
        )
        yr_consumed = sum(
            monthly[m]["consumed"]
            for m in year_months
        )
        yr_nrw  = round(yr_pumped - yr_consumed, 1)
        yr_pct  = round(
            (yr_nrw / yr_pumped) * 100, 1
        ) if yr_pumped > 0 else 0
        status  = (
            "🔴 ALERT" if yr_pct >= 20 else
            "🟡 WARN"  if yr_pct >= 15 else
            "🟢 OK"
        )
        with cols[i]:
            st.metric(
                f"{year} pumped",
                f"{yr_pumped:.0f} m³"
            )
            st.metric(
                f"{year} consumed",
                f"{yr_consumed:.0f} m³"
            )
            st.metric(
                f"{year} NRW",
                f"{yr_nrw:.0f} m³"
            )
            st.metric(
                f"{year} NRW %",
                f"{yr_pct}%",
                delta=status
            )

    st.caption(
        "Annual figures are most reliable as tank "
        "storage changes cancel out over 12 months. "
        "Adj NRW requires 2+ tank level readings "
        "per month in Field Ops."
    )
