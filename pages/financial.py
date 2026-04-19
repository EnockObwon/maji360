import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from core.database import get_session, get_engine
from core.auth import require_login
from collections import defaultdict
from sqlalchemy import text


def get_expenses(system_id: int) -> list:
    """Fetch expenses from Supabase."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT date, month, amount, category, notes
                FROM expenses
                WHERE system_id = :sid
                ORDER BY date
            """), {"sid": system_id})
            return [dict(row._mapping) for row in result]
    except Exception as e:
        st.error(f"Could not load expenses: {e}")
        return []


def show():
    require_login()

    system_id   = st.session_state.get("selected_system_id")
    system_name = st.session_state.get("selected_system_name", "")
    currency    = st.session_state.get("currency", "UGX")

    if not system_id:
        st.warning("Please select a water system.")
        return

    st.markdown("## 📊 Financial Report")
    st.markdown(
        f"<span style='color:#64748b;font-size:13px'>"
        f"{system_name} · Income & Expenditure</span>",
        unsafe_allow_html=True
    )
    st.divider()

    # ── Fetch data ─────────────────────────────────────
    from core.database import Bill
    session   = get_session()
    all_bills = session.query(Bill).filter_by(
        system_id=system_id
    ).all()
    session.close()

    expenses = get_expenses(system_id)

    # ── Revenue aggregates ─────────────────────────────
    total_billed = sum(b.amount or 0 for b in all_bills)
    total_collected = sum(
        b.amount_paid or 0 for b in all_bills
    )
    total_outstanding = total_billed - total_collected

    monthly_billed    = defaultdict(float)
    monthly_collected = defaultdict(float)
    for b in all_bills:
        if b.bill_month:
            monthly_billed[b.bill_month]    += b.amount or 0
            monthly_collected[b.bill_month] += b.amount_paid or 0

    # ── Expense aggregates ─────────────────────────────
    total_expenses   = sum(e["amount"] for e in expenses)
    net_surplus      = total_collected - total_expenses

    monthly_expenses = defaultdict(float)
    expenses_by_cat  = defaultdict(float)
    for e in expenses:
        if e["month"]:
            monthly_expenses[e["month"]] += e["amount"]
        if e["category"]:
            expenses_by_cat[e["category"]] += e["amount"]

    # ── KPI cards ──────────────────────────────────────
    st.markdown("### Financial summary")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(
            "Revenue collected",
            f"{currency} {total_collected/1000000:.2f}M"
            if total_collected >= 1000000
            else f"{currency} {total_collected:,.0f}"
        )
    with c2:
        st.metric(
            "Total expenses",
            f"{currency} {total_expenses:,.0f}"
        )
    with c3:
        st.metric(
            "Net surplus",
            f"{currency} {net_surplus/1000000:.2f}M"
            if net_surplus >= 1000000
            else f"{currency} {net_surplus:,.0f}"
        )
    with c4:
        expense_ratio = round(
            (total_expenses / total_collected) * 100, 1
        ) if total_collected > 0 else 0
        st.metric(
            "Expense ratio",
            f"{expense_ratio}%",
        )

    st.divider()

    # ── Chart 1: Income vs Expenses by month ───────────
    st.markdown("### Monthly income vs expenses")
    st.caption(
        "Green = revenue collected · "
        "Red = expenses · "
        "Blue line = net surplus"
    )

    all_months = sorted(set(
        list(monthly_collected.keys()) +
        list(monthly_expenses.keys())
    ))

    rev_vals     = [monthly_collected.get(m, 0)
                    for m in all_months]
    exp_vals     = [monthly_expenses.get(m, 0)
                    for m in all_months]
    surplus_vals = [r - e for r, e in
                    zip(rev_vals, exp_vals)]

    fig1 = go.Figure()
    fig1.add_trace(go.Bar(
        name         = "Revenue collected",
        x            = all_months,
        y            = rev_vals,
        marker_color = "#22c55e",
        opacity      = 0.85
    ))
    fig1.add_trace(go.Bar(
        name         = "Expenses",
        x            = all_months,
        y            = exp_vals,
        marker_color = "#ef4444",
        opacity      = 0.85
    ))
    fig1.add_trace(go.Scatter(
        name       = "Net surplus",
        x          = all_months,
        y          = surplus_vals,
        mode       = "lines+markers",
        yaxis      = "y",
        line       = dict(color="#3b82f6", width=2.5),
        marker     = dict(size=8)
    ))
    fig1.update_layout(
        barmode       = "group",
        height        = 380,
        margin        = dict(t=20, b=10, l=0, r=0),
        plot_bgcolor  = "white",
        paper_bgcolor = "white",
        yaxis         = dict(
            title     = f"Amount ({currency})",
            gridcolor = "#f1f5f9"
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
    st.plotly_chart(fig1, use_container_width=True)

    st.divider()

    # ── Chart 2: Expenses by category pie chart ────────
    st.markdown("### Expenses by category")
    col_left, col_right = st.columns(2)

    with col_left:
        fig2 = go.Figure(go.Pie(
            labels    = list(expenses_by_cat.keys()),
            values    = list(expenses_by_cat.values()),
            hole      = 0.4,
            marker    = dict(colors=[
                "#ef4444", "#f59e0b", "#3b82f6",
                "#8b5cf6", "#22c55e"
            ])
        ))
        fig2.update_layout(
            height        = 300,
            margin        = dict(t=20, b=10, l=0, r=0),
            paper_bgcolor = "white",
            showlegend    = True,
            legend        = dict(
                orientation = "v",
                x           = 0.7
            )
        )
        st.plotly_chart(fig2, use_container_width=True)

    with col_right:
        cat_rows = []
        for cat, amt in sorted(
            expenses_by_cat.items(), key=lambda x: -x[1]
        ):
            pct = round(
                (amt / total_expenses) * 100, 1
            ) if total_expenses > 0 else 0
            cat_rows.append({
                "Category": cat,
                "Amount":   f"{currency} {amt:,.0f}",
                "Share":    f"{pct}%"
            })
        st.dataframe(
            pd.DataFrame(cat_rows),
            use_container_width=True,
            hide_index=True
        )

        st.markdown(f"""
        <div style='background:#f0fdf4;border-radius:8px;
                    padding:12px 16px;margin-top:8px'>
            <div style='font-size:12px;color:#64748b;
                        text-transform:uppercase;
                        letter-spacing:0.06em'>
                Net surplus
            </div>
            <div style='font-size:24px;font-weight:600;
                        color:#166534;font-family:monospace'>
                {currency} {net_surplus:,.0f}
            </div>
            <div style='font-size:12px;color:#64748b;
                        margin-top:4px'>
                Revenue collected minus total expenses
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.divider()

    # ── Full expense ledger ────────────────────────────
    st.markdown("### Expense transactions")
    if expenses:
        exp_rows = [{
            "Date":     e["date"],
            "Month":    e["month"],
            "Category": e["category"],
            "Amount":   f"{currency} {e['amount']:,.0f}",
            "Notes":    e["notes"] or "—"
        } for e in expenses]

        st.dataframe(
            pd.DataFrame(exp_rows),
            use_container_width=True,
            hide_index=True
        )

        st.markdown(
            f"**Total: {currency} {total_expenses:,.0f}** "
            f"across {len(expenses)} transactions"
        )
    else:
        st.info("No expense transactions recorded yet.")

    st.divider()

    # ── Income statement summary ───────────────────────
    st.markdown("### Income statement")
    st.markdown(f"""
    | Item | Amount ({currency}) |
    |---|---|
    | **Revenue** | |
    | Total billed | {total_billed:,.0f} |
    | Total collected | {total_collected:,.0f} |
    | Outstanding | {total_outstanding:,.0f} |
    | **Expenses** | |
    | Office Expenses | {expenses_by_cat.get('Office Expenses', 0):,.0f} |
    | Operating Expenses | {expenses_by_cat.get('Operating Expenses', 0):,.0f} |
    | Salaries and Wages | {expenses_by_cat.get('Salaries and Wages', 0):,.0f} |
    | **Total Expenses** | **{total_expenses:,.0f}** |
    | **Net Surplus** | **{net_surplus:,.0f}** |
    """)
