import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone
from core.database import get_session, Asset, WaterSystem
from core.auth import require_login, is_operator
from sqlalchemy import text as sql_text


CATEGORIES = [
    "Pump repair",
    "Pump replacement",
    "Pipeline leak repair",
    "Tank repair",
    "Meter replacement",
    "Valve repair",
    "Electrical / solar repair",
    "Routine inspection",
    "Chlorination / water treatment",
    "Other"
]

STATUSES = ["Reported", "In progress", "Resolved"]


def get_maintenance(system_id: int) -> list:
    session = get_session()
    try:
        rows = session.execute(sql_text("""
            SELECT m.id, m.incident_date,
                   m.resolved_date, m.category,
                   m.problem, m.action_taken,
                   m.status, m.cost, m.done_by,
                   m.contractor_name,
                   m.contractor_phone,
                   a.name as asset_name
            FROM maintenance m
            LEFT JOIN assets a ON m.asset_id = a.id
            WHERE m.system_id = :sid
            ORDER BY m.incident_date DESC
        """), {"sid": system_id}).fetchall()
        result = [dict(r._mapping) for r in rows]
    except Exception as e:
        st.error(f"Error loading maintenance: {e}")
        result = []
    session.close()
    return result


def show():
    require_login()

    system_id   = st.session_state.get(
        "selected_system_id"
    )
    system_name = st.session_state.get(
        "selected_system_name", ""
    )
    currency    = st.session_state.get(
        "currency", "UGX"
    )

    if not system_id:
        st.warning("Please select a water system.")
        return

    st.markdown("## 🔧 Maintenance Tracking")
    st.markdown(
        f"<span style='color:#64748b;font-size:13px'>"
        f"{system_name} · Asset maintenance log"
        f"</span>",
        unsafe_allow_html=True
    )
    st.divider()

    # ── Fetch assets ───────────────────────────────────
    session = get_session()
    assets  = session.query(Asset).filter_by(
        system_id=system_id, is_active=True
    ).all()
    session.close()

    asset_options = {"— General / no specific asset —": None}
    for a in assets:
        asset_options[
            f"{a.name} ({a.asset_type})"
        ] = a.id

    tab1, tab2, tab3 = st.tabs([
        "📋 Log incident",
        "✏️ Update status",
        "📊 Maintenance report"
    ])

    # ── Tab 1: Log new incident ────────────────────────
    with tab1:
        st.markdown("### Log new maintenance incident")

        with st.form("maintenance_form"):
            col1, col2 = st.columns(2)
            with col1:
                m_asset    = st.selectbox(
                    "Affected asset",
                    options=list(asset_options.keys())
                )
                m_category = st.selectbox(
                    "Category *",
                    options=CATEGORIES
                )
                m_done_by  = st.selectbox(
                    "Work done by *",
                    options=["Staff", "Contractor"]
                )
                m_incident_date = st.date_input(
                    "Incident date *",
                    value=datetime.now().date()
                )
            with col2:
                m_status = st.selectbox(
                    "Status *",
                    options=STATUSES
                )
                m_cost   = st.number_input(
                    f"Cost ({currency})",
                    min_value=0.0,
                    value=0.0,
                    step=1000.0,
                    format="%.0f"
                )
                m_resolved_date = st.date_input(
                    "Resolved date (if resolved)",
                    value=None
                )

            m_problem = st.text_area(
                "Problem description *",
                placeholder="Describe the fault or "
                            "issue observed...",
                height=80
            )
            m_action  = st.text_area(
                "Action taken",
                placeholder="Describe what was done "
                            "to fix the problem...",
                height=80
            )

            # Contractor details
            m_contractor_name  = None
            m_contractor_phone = None
            if m_done_by == "Contractor":
                col3, col4 = st.columns(2)
                with col3:
                    m_contractor_name = st.text_input(
                        "Contractor name"
                    )
                with col4:
                    m_contractor_phone = st.text_input(
                        "Contractor phone"
                    )

            submitted = st.form_submit_button(
                "✓ Log incident",
                use_container_width=True,
                type="primary"
            )

            if submitted:
                if not m_problem:
                    st.error(
                        "Problem description is required."
                    )
                else:
                    asset_id = asset_options.get(m_asset)
                    current_user = st.session_state.get(
                        "user", {}
                    )

                    resolved_date_val = None
                    if m_status == "Resolved" and \
                       m_resolved_date:
                        resolved_date_val = str(
                            m_resolved_date
                        )

                    session = get_session()
                    try:
                        session.execute(sql_text("""
                            INSERT INTO maintenance (
                                system_id, asset_id,
                                incident_date,
                                resolved_date,
                                category, problem,
                                action_taken, status,
                                cost, done_by,
                                contractor_name,
                                contractor_phone,
                                recorded_by
                            ) VALUES (
                                :system_id, :asset_id,
                                :incident_date,
                                :resolved_date,
                                :category, :problem,
                                :action_taken, :status,
                                :cost, :done_by,
                                :contractor_name,
                                :contractor_phone,
                                :recorded_by
                            )
                        """), {
                            "system_id":       system_id,
                            "asset_id":        asset_id,
                            "incident_date":   str(
                                m_incident_date
                            ),
                            "resolved_date":   resolved_date_val,
                            "category":        m_category,
                            "problem":         m_problem,
                            "action_taken":    m_action or None,
                            "status":          m_status,
                            "cost":            m_cost,
                            "done_by":         m_done_by,
                            "contractor_name": m_contractor_name,
                            "contractor_phone": m_contractor_phone,
                            "recorded_by":     current_user.get("id")
                        })
                        session.commit()
                        st.success(
                            f"✓ Maintenance incident "
                            f"logged — {m_category}"
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
                    finally:
                        session.close()

    # ── Tab 2: Update status ───────────────────────────
    with tab2:
        st.markdown("### Update incident status")

        records = get_maintenance(system_id)
        open_records = [
            r for r in records
            if r["status"] != "Resolved"
        ]

        if not open_records:
            st.success(
                "✓ No open maintenance incidents."
            )
        else:
            st.markdown(
                f"**{len(open_records)} open "
                f"incident(s)**"
            )

            for rec in open_records:
                with st.expander(
                    f"🔧 {rec['category']} — "
                    f"{rec['incident_date']} — "
                    f"{rec['status']}"
                ):
                    st.markdown(
                        f"**Asset:** "
                        f"{rec['asset_name'] or '—'}"
                    )
                    st.markdown(
                        f"**Problem:** {rec['problem']}"
                    )
                    if rec['action_taken']:
                        st.markdown(
                            f"**Action:** "
                            f"{rec['action_taken']}"
                        )
                    st.markdown(
                        f"**Done by:** {rec['done_by']}"
                    )
                    if rec['contractor_name']:
                        st.markdown(
                            f"**Contractor:** "
                            f"{rec['contractor_name']} "
                            f"{rec['contractor_phone'] or ''}"
                        )

                    with st.form(
                        f"update_{rec['id']}"
                    ):
                        col1, col2 = st.columns(2)
                        with col1:
                            new_status = st.selectbox(
                                "Update status",
                                options=STATUSES,
                                index=STATUSES.index(
                                    rec["status"]
                                ) if rec["status"]
                                in STATUSES else 0
                            )
                        with col2:
                            new_cost = st.number_input(
                                f"Final cost "
                                f"({currency})",
                                min_value=0.0,
                                value=float(
                                    rec["cost"] or 0
                                ),
                                step=1000.0,
                                format="%.0f"
                            )

                        new_action = st.text_area(
                            "Action taken",
                            value=rec[
                                "action_taken"
                            ] or "",
                            height=60
                        )

                        resolved_date = None
                        if new_status == "Resolved":
                            resolved_date = st.date_input(
                                "Resolved date",
                                value=datetime.now().date(),
                                key=f"rd_{rec['id']}"
                            )

                        update_btn = st.form_submit_button(
                            "✓ Update",
                            use_container_width=True,
                            type="primary"
                        )

                        if update_btn:
                            session = get_session()
                            try:
                                session.execute(
                                    sql_text("""
                                    UPDATE maintenance
                                    SET status = :status,
                                        cost = :cost,
                                        action_taken = :action,
                                        resolved_date = :rdate
                                    WHERE id = :mid
                                """), {
                                    "status": new_status,
                                    "cost":   new_cost,
                                    "action": new_action or None,
                                    "rdate":  str(resolved_date)
                                             if resolved_date
                                             else None,
                                    "mid":    rec["id"]
                                })
                                session.commit()
                                st.success(
                                    "✓ Updated successfully"
                                )
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
                            finally:
                                session.close()

    # ── Tab 3: Maintenance report ──────────────────────
    with tab3:
        st.markdown("### Maintenance report")

        records = get_maintenance(system_id)

        if not records:
            st.info(
                "No maintenance records yet. "
                "Log your first incident above."
            )
            return

        # ── KPI summary ────────────────────────────────
        total_incidents = len(records)
        open_count      = sum(
            1 for r in records
            if r["status"] != "Resolved"
        )
        resolved_count  = sum(
            1 for r in records
            if r["status"] == "Resolved"
        )
        total_cost      = sum(
            r["cost"] or 0 for r in records
        )

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric(
                "Total incidents", total_incidents
            )
        with c2:
            st.metric("Open", open_count)
        with c3:
            st.metric("Resolved", resolved_count)
        with c4:
            st.metric(
                "Total cost",
                f"{currency} {total_cost:,.0f}"
            )

        st.divider()

        # ── Chart: Incidents by category ───────────────
        st.markdown("### Incidents by category")
        cat_counts = {}
        cat_costs  = {}
        for r in records:
            cat = r["category"]
            cat_counts[cat] = \
                cat_counts.get(cat, 0) + 1
            cat_costs[cat]  = \
                cat_costs.get(cat, 0) + \
                (r["cost"] or 0)

        fig1 = go.Figure()
        fig1.add_trace(go.Bar(
            x            = list(cat_counts.keys()),
            y            = list(cat_counts.values()),
            marker_color = "#3b82f6",
            text         = list(cat_counts.values()),
            textposition = "outside"
        ))
        fig1.update_layout(
            height        = 300,
            margin        = dict(
                t=20, b=80, l=0, r=0
            ),
            plot_bgcolor  = "white",
            paper_bgcolor = "white",
            yaxis         = dict(
                title     = "Number of incidents",
                gridcolor = "#f1f5f9"
            ),
            xaxis = dict(
                tickangle = -30,
                gridcolor = "#f1f5f9"
            ),
            showlegend = False
        )
        st.plotly_chart(fig1, use_container_width=True)

        st.divider()

        # ── Timeline chart ─────────────────────────────
        st.markdown("### Maintenance timeline")
        st.caption(
            "Each bar shows incident date to "
            "resolution date"
        )

        timeline_records = [
            r for r in records
            if r["incident_date"]
        ]

        if timeline_records:
            colours = {
                "Reported":    "#f59e0b",
                "In progress": "#3b82f6",
                "Resolved":    "#22c55e"
            }
            fig2 = go.Figure()
            for r in timeline_records:
                start = str(r["incident_date"])
                end   = str(
                    r["resolved_date"]
                ) if r["resolved_date"] else \
                    datetime.now().strftime("%Y-%m-%d")
                fig2.add_trace(go.Bar(
                    name             = r["status"],
                    x                = [end],
                    y                = [r["category"]],
                    orientation      = "h",
                    marker_color     = colours.get(
                        r["status"], "#94a3b8"
                    ),
                    base             = [start],
                    hovertemplate    = (
                        f"<b>{r['category']}</b><br>"
                        f"Asset: "
                        f"{r['asset_name'] or '—'}<br>"
                        f"Status: {r['status']}<br>"
                        f"Cost: {currency} "
                        f"{r['cost'] or 0:,.0f}<br>"
                        f"<extra></extra>"
                    ),
                    showlegend=False
                ))
            fig2.update_layout(
                barmode       = "overlay",
                height        = max(
                    250,
                    len(timeline_records) * 40
                ),
                margin        = dict(
                    t=10, b=10, l=0, r=0
                ),
                plot_bgcolor  = "white",
                paper_bgcolor = "white",
                xaxis         = dict(
                    type      = "date",
                    gridcolor = "#f1f5f9"
                ),
                yaxis = dict(gridcolor="#f1f5f9")
            )
            st.plotly_chart(
                fig2, use_container_width=True
            )

        st.divider()

        # ── Full maintenance log table ─────────────────
        st.markdown("### Full maintenance log")
        rows = []
        for r in records:
            rows.append({
                "Date":       str(r["incident_date"]),
                "Resolved":   str(
                    r["resolved_date"]
                ) if r["resolved_date"] else "—",
                "Asset":      r["asset_name"] or "—",
                "Category":   r["category"],
                "Problem":    r["problem"][:50] + "..."
                              if len(
                                  r["problem"]
                              ) > 50 else r["problem"],
                "Status":     r["status"],
                "Done by":    r["done_by"],
                "Contractor": r["contractor_name"] or "—",
                "Cost":       f"{currency} "
                              f"{r['cost']:,.0f}"
                              if r["cost"] else "—"
            })

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True
        )

        # Cost by month
        st.divider()
        st.markdown("### Maintenance cost by month")
        monthly_cost = {}
        for r in records:
            if r["incident_date"] and r["cost"]:
                month = str(
                    r["incident_date"]
                )[:7]
                monthly_cost[month] = \
                    monthly_cost.get(month, 0) + \
                    r["cost"]

        if monthly_cost:
            months_sorted = sorted(
                monthly_cost.keys()
            )
            fig3 = go.Figure()
            fig3.add_trace(go.Bar(
                x            = months_sorted,
                y            = [
                    monthly_cost[m]
                    for m in months_sorted
                ],
                marker_color = "#8b5cf6",
                text         = [
                    f"{currency} "
                    f"{monthly_cost[m]:,.0f}"
                    for m in months_sorted
                ],
                textposition = "outside"
            ))
            fig3.update_layout(
                height        = 280,
                margin        = dict(
                    t=30, b=10, l=0, r=0
                ),
                plot_bgcolor  = "white",
                paper_bgcolor = "white",
                yaxis         = dict(
                    title     = f"Cost ({currency})",
                    gridcolor = "#f1f5f9"
                ),
                xaxis  = dict(
                    gridcolor = "#f1f5f9",
                    type      = "category"
                ),
                showlegend = False
            )
            st.plotly_chart(
                fig3, use_container_width=True
            )
