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

    st.markdown("## ⚙️ Operations")
    st.markdown(
        f"<span style='color:#64748b;font-size:13px'>"
        f"{system_name} · Monthly Production & Consumption</span>",
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

    # ── Aggregate by month ─────────────────────────────
    monthly = defaultdict(lambda: {"pumped": 0.0,
                                    "consumed": 0.0,
                                    "pump_visits": 0,
                                    "tank_visits": 0})
    for r in readings:
        month = r.reading_date.strftime("%Y-%m")
        if r.water_produced_m3 and r.water_produced_m3 > 0:
            monthly[month]["pumped"]      += r.water_produced_m3
            monthly[month]["pump_visits"] += 1
        if r.water_consumed_m3 and r.water_consumed_m3 > 0:
            monthly[month]["consumed"]    += r.water_consumed_m3
            monthly[month]["tank_visits"] += 1

    months   = sorted(monthly.keys())
    pumped   = [round(monthly[m]["pumped"],   1) for m in months]
    consumed = [round(monthly[m]["consumed"], 1) for m in months]
    nrw      = [round(p - c, 1)
                for p, c in zip(pumped, consumed)]
    nrw_pct  = [round((n / p) * 100, 1) if p > 0 else 0
                for n, p in zip(nrw, pumped)]

    pump_visits = [monthly[m]["pump_visits"] for m in months]
    tank_visits = [monthly[m]["tank_visits"] for m in months]

    # ── KPI summary ────────────────────────────────────
    total_pumped   = sum(pumped)
    total_consumed = sum(consumed)
    total_nrw      = round(total_pumped - total_consumed, 1)
    overall_nrw    = round(
        (total_nrw / total_pumped) * 100, 1
    ) if total_pumped > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Total pumped",   f"{total_pumped:.0f} m³")
    with c2:
        st.metric("Total consumed", f"{total_consumed:.0f} m³")
    with c3:
        st.metric("Total NRW",      f"{total_nrw:.0f} m³")
    with c4:
        st.metric("Overall NRW %",  f"{overall_nrw}%")

    st.divider()

    # ── Chart 1: Monthly water produced ───────────────
    st.markdown("### Monthly water produced — pump house (m³)")
    st.caption(
        "Total volume pumped each month from all operator visits"
    )

    fig1 = go.Figure()
    fig1.add_trace(go.Bar(
        x            = months,
        y            = pumped,
        marker_color = "#3b82f6",
        text         = [f"{p:.0f}" for p in pumped],
        textposition = "outside",
        textfont     = dict(size=11),
        customdata   = pump_visits,
        hovertemplate = (
            "<b>%{x}</b><br>"
            "Pumped: %{y:.1f} m³<br>"
            "Operator visits: %{customdata}<br>"
            "<extra></extra>"
        )
    ))
    fig1.update_layout(
        height        = 320,
        margin        = dict(t=30, b=10, l=0, r=0),
        plot_bgcolor  = "white",
        paper_bgcolor = "white",
        yaxis         = dict(
            title     = "Volume (m³)",
            gridcolor = "#f1f5f9"
        ),
        xaxis = dict(gridcolor="#f1f5f9"),
        showlegend = False
    )
    st.plotly_chart(fig1, use_container_width=True)

    st.divider()

    # ── Chart 2: Monthly tank flow to consumers ────────
    st.markdown(
        "### Monthly tank flow to consumers — tank outlet (m³)"
    )
    st.caption(
        "Total volume flowing out to customers each month"
    )

    fig2 = go.Figure()
    fig2.add_trace(go.Bar(
        x            = months,
        y            = consumed,
        marker_color = "#22c55e",
        text         = [f"{c:.0f}" for c in consumed],
        textposition = "outside",
        textfont     = dict(size=11),
        customdata   = tank_visits,
        hovertemplate = (
            "<b>%{x}</b><br>"
            "Consumed: %{y:.1f} m³<br>"
            "Operator visits: %{customdata}<br>"
            "<extra></extra>"
        )
    ))
    fig2.update_layout(
        height        = 320,
        margin        = dict(t=30, b=10, l=0, r=0),
        plot_bgcolor  = "white",
        paper_bgcolor = "white",
        yaxis         = dict(
            title     = "Volume (m³)",
            gridcolor = "#f1f5f9"
        ),
        xaxis = dict(gridcolor="#f1f5f9"),
        showlegend = False
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    # ── Chart 3: Pump vs Tank grouped + NRW line ───────
    st.markdown("### Monthly pump vs tank — NRW gap")
    st.caption(
        "Blue = pumped, Green = to consumers, "
        "Red line = NRW %"
    )

    fig3 = go.Figure()
    fig3.add_trace(go.Bar(
        name         = "Pumped (m³)",
        x            = months,
        y            = pumped,
        marker_color = "#bfdbfe",
        opacity      = 0.8
    ))
    fig3.add_trace(go.Bar(
        name         = "To consumers (m³)",
        x            = months,
        y            = consumed,
        marker_color = "#22c55e",
        opacity      = 0.8
    ))
    fig3.add_trace(go.Scatter(
        name       = "NRW %",
        x          = months,
        y          = nrw_pct,
        mode       = "lines+markers",
        yaxis      = "y2",
        line       = dict(color="#ef4444", width=2.5),
        marker     = dict(
            size  = 8,
            color = ["#ef4444" if p >= 20 else
                     "#f59e0b" if p >= 15 else
                     "#22c55e" for p in nrw_pct],
            line  = dict(color="white", width=1.5)
        )
    ))
    fig3.add_hline(
        y                   = 20,
        line_dash           = "dash",
        line_color          = "#ef4444",
        opacity             = 0.4,
        annotation_text     = "20% NRW threshold",
        annotation_position = "top right",
        yref                = "y2"
    )
    fig3.update_layout(
        barmode       = "group",
        height        = 380,
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
            range      = [0, max(nrw_pct) * 1.3 + 10]
                         if nrw_pct else [0, 100],
            showgrid   = False
        ),
        xaxis  = dict(gridcolor="#f1f5f9"),
        legend = dict(
            orientation = "h",
            yanchor     = "bottom",
            y           = 1.02,
            xanchor     = "left",
            x           = 0
        )
    )
    st.plotly_chart(fig3, use_container_width=True)

    st.divider()

    # ── Monthly data table ─────────────────────────────
    st.markdown("### Monthly summary table")
    rows = []
    for i, month in enumerate(months):
        pct    = nrw_pct[i]
        status = ("🔴 ALERT" if pct >= 20 else
                  "🟡 WARN"  if pct >= 15 else "🟢 OK")
        rows.append({
            "Month":        month,
            "Pumped m³":    pumped[i],
            "Consumed m³":  consumed[i],
            "NRW m³":       nrw[i],
            "NRW %":        f"{pct}%",
            "Pump visits":  pump_visits[i],
            "Tank visits":  tank_visits[i],
            "Status":       status
        })

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True
    )

    st.markdown("""
    <div style='font-size:12px;color:#94a3b8;margin-top:8px'>
    ℹ️ Pump visits and tank visits show how many times
    the operator recorded readings each month.
    Consistent monthly readings improve NRW accuracy.
    </div>
    """, unsafe_allow_html=True)
