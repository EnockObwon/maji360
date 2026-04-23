import streamlit as st
import pandas as pd
import io
from datetime import datetime
from core.database import (
    get_session, DailyReading, Bill,
    Customer, WaterSystem
)
from core.auth import require_login
from collections import defaultdict
from sqlalchemy import text as sql_text


def get_total_population(system_id: int) -> int:
    """
    Get total population served from customer
    population field — actual figures not estimates.
    """
    session = get_session()
    customers = session.query(Customer).filter_by(
        system_id=system_id, is_active=True
    ).all()
    session.close()
    return sum(
        getattr(c, 'population', 0) or 0
        for c in customers
    )


def get_report_data(system_id: int,
                    year: int,
                    month: int = None) -> dict:
    session = get_session()

    system = session.query(WaterSystem).filter_by(
        id=system_id
    ).first()

    if month:
        period       = f"{year}-{month:02d}"
        periods      = [period]
        period_label = datetime(
            year, month, 1
        ).strftime("%B %Y")
    else:
        periods      = [
            f"{year}-{m:02d}" for m in range(1, 13)
        ]
        period_label = str(year)

    # Production
    readings = session.query(DailyReading).filter(
        DailyReading.system_id == system_id
    ).all()

    monthly_production = defaultdict(
        lambda: {"pumped": 0.0, "consumed": 0.0}
    )
    for r in readings:
        m = r.reading_date.strftime("%Y-%m")
        if r.water_produced_m3 and \
           r.water_produced_m3 > 0:
            monthly_production[m]["pumped"] += \
                r.water_produced_m3
        if r.water_consumed_m3 and \
           r.water_consumed_m3 > 0:
            monthly_production[m]["consumed"] += \
                r.water_consumed_m3

    total_pumped   = sum(
        monthly_production[p]["pumped"]
        for p in periods
    )
    total_consumed = sum(
        monthly_production[p]["consumed"]
        for p in periods
    )
    total_nrw_m3   = round(
        total_pumped - total_consumed, 1
    )
    nrw_pct        = round(
        (total_nrw_m3 / total_pumped) * 100, 1
    ) if total_pumped > 0 else 0

    # Customers and population
    customers       = session.query(Customer).filter_by(
        system_id=system_id, is_active=True
    ).all()
    total_customers = len(customers)
    psp_count       = sum(
        1 for c in customers
        if getattr(c, 'connection_type', 'PSP')
        == 'PSP'
    )
    private_count   = sum(
        1 for c in customers
        if getattr(c, 'connection_type', 'PSP')
        == 'Private'
    )
    school_count    = sum(
        1 for c in customers
        if getattr(c, 'connection_type', 'PSP')
        == 'School'
    )

    # Use actual population from database
    pop_estimate = sum(
        getattr(c, 'population', 0) or 0
        for c in customers
    )

    # Per capita litres per person per day
    days = 30 * len(periods)
    per_capita = round(
        (total_consumed * 1000) /
        (pop_estimate * days), 1
    ) if pop_estimate > 0 and days > 0 else 0

    # Billing
    all_bills    = session.query(Bill).filter_by(
        system_id=system_id
    ).all()
    period_bills = [
        b for b in all_bills
        if b.bill_month in periods
    ]
    total_billed    = sum(
        b.amount or 0 for b in period_bills
    )
    total_collected = sum(
        b.amount_paid or 0 for b in period_bills
    )
    collection_rate = round(
        (total_collected / total_billed) * 100, 1
    ) if total_billed > 0 else 0

    # Expenses
    try:
        if month:
            exp_rows = session.execute(sql_text(
                "SELECT SUM(amount) FROM expenses "
                "WHERE system_id = :sid "
                "AND month = :month"
            ), {"sid": system_id,
                "month": period}).fetchone()
        else:
            exp_rows = session.execute(sql_text(
                "SELECT SUM(amount) FROM expenses "
                "WHERE system_id = :sid "
                "AND month LIKE :year"
            ), {"sid":  system_id,
                "year": f"{year}%"}).fetchone()
        total_expenses = float(exp_rows[0] or 0)
    except Exception:
        total_expenses = 0.0

    net_surplus = round(
        total_collected - total_expenses, 0
    )

    # Maintenance
    try:
        if month:
            maint_rows = session.execute(sql_text(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN status='Resolved' "
                "THEN 1 ELSE 0 END), SUM(cost) "
                "FROM maintenance "
                "WHERE system_id = :sid "
                "AND EXTRACT(YEAR FROM "
                "incident_date) = :year "
                "AND EXTRACT(MONTH FROM "
                "incident_date) = :month"
            ), {"sid":   system_id,
                "year":  year,
                "month": month}).fetchone()
        else:
            maint_rows = session.execute(sql_text(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN status='Resolved' "
                "THEN 1 ELSE 0 END), SUM(cost) "
                "FROM maintenance "
                "WHERE system_id = :sid "
                "AND EXTRACT(YEAR FROM "
                "incident_date) = :year"
            ), {"sid":  system_id,
                "year": year}).fetchone()
        total_incidents    = int(maint_rows[0] or 0)
        resolved_incidents = int(maint_rows[1] or 0)
        total_maint_cost   = float(maint_rows[2] or 0)
    except Exception:
        total_incidents    = 0
        resolved_incidents = 0
        total_maint_cost   = 0.0

    # Tank level
    try:
        tank_rows = session.execute(sql_text(
            "SELECT AVG(pct_full) "
            "FROM tank_levels "
            "WHERE system_id = :sid"
        ), {"sid": system_id}).fetchone()
        avg_tank_pct = round(
            float(tank_rows[0] or 0), 1
        )
    except Exception:
        avg_tank_pct = 0.0

    session.close()

    return {
        "system_name":       system.name
                             if system else "",
        "district":          system.district
                             if system else "",
        "country":           system.country
                             if system else "",
        "currency":          system.currency
                             if system else "UGX",
        "period_label":      period_label,
        "periods":           periods,
        "year":              year,
        "month":             month,
        "total_pumped":      round(total_pumped, 1),
        "total_consumed":    round(total_consumed, 1),
        "total_nrw_m3":      total_nrw_m3,
        "nrw_pct":           nrw_pct,
        "total_customers":   total_customers,
        "psp_count":         psp_count,
        "private_count":     private_count,
        "school_count":      school_count,
        "pop_estimate":      pop_estimate,
        "per_capita":        per_capita,
        "total_billed":      round(total_billed, 0),
        "total_collected":   round(total_collected, 0),
        "collection_rate":   collection_rate,
        "total_expenses":    round(total_expenses, 0),
        "net_surplus":       net_surplus,
        "total_incidents":   total_incidents,
        "resolved_incidents": resolved_incidents,
        "total_maint_cost":  round(total_maint_cost, 0),
        "avg_tank_pct":      avg_tank_pct
    }


def generate_excel(system_id: int,
                   year: int) -> bytes:
    session  = get_session()
    system   = session.query(WaterSystem).filter_by(
        id=system_id
    ).first()
    currency = system.currency if system else "UGX"
    sys_name = system.name if system else ""
    customers = session.query(Customer).filter_by(
        system_id=system_id, is_active=True
    ).all()
    all_bills = session.query(Bill).filter_by(
        system_id=system_id
    ).all()
    session.close()

    output = io.BytesIO()
    writer = pd.ExcelWriter(
        output, engine="xlsxwriter"
    )
    wb = writer.book

    fmt_title = wb.add_format({
        "bold": True, "font_size": 14,
        "font_color": "#0ea5e9",
        "align": "center"
    })
    fmt_header = wb.add_format({
        "bold": True, "bg_color": "#0a1628",
        "font_color": "white",
        "border": 1, "align": "center"
    })
    fmt_subheader = wb.add_format({
        "bold": True, "bg_color": "#e0f2fe",
        "font_color": "#0369a1", "border": 1
    })
    fmt_number  = wb.add_format({
        "num_format": "#,##0",
        "border": 1, "align": "right"
    })
    fmt_decimal = wb.add_format({
        "num_format": "#,##0.0",
        "border": 1, "align": "right"
    })
    fmt_cell  = wb.add_format({"border": 1})
    fmt_alert = wb.add_format({
        "bg_color": "#fef2f2",
        "font_color": "#991b1b",
        "bold": True, "border": 1,
        "align": "right",
        "num_format": "0.0"
    })

    months_labels = [
        "Jan", "Feb", "Mar", "Apr",
        "May", "Jun", "Jul", "Aug",
        "Sep", "Oct", "Nov", "Dec"
    ]

    # ── Sheet 1: Monthly Summary ───────────────────────
    ws1 = wb.add_worksheet("Monthly Summary")
    ws1.set_column("A:A", 30)
    ws1.set_column("B:M", 14)

    ws1.merge_range(
        "A1:M1",
        f"Maji360 — {sys_name} — {year} Report",
        fmt_title
    )
    ws1.merge_range(
        "A2:M2",
        f"Generated: {datetime.now().strftime('%d %b %Y %H:%M')}",
        wb.add_format({
            "align": "center",
            "font_color": "#64748b",
            "font_size": 10
        })
    )

    ws1.write(3, 0, "Indicator", fmt_header)
    for i, m in enumerate(months_labels):
        ws1.write(3, i + 1, m, fmt_header)

    row = 4

    sections = [
        ("WATER PRODUCTION", [
            ("Pumped (m³)", "total_pumped",
             fmt_decimal),
            ("Consumed (m³)", "total_consumed",
             fmt_decimal),
            ("NRW (m³)", "total_nrw_m3",
             fmt_decimal),
            ("NRW (%)", "nrw_pct", fmt_decimal),
        ]),
        ("SERVICE COVERAGE", [
            ("Active connections",
             "total_customers", fmt_number),
            ("PSP connections",
             "psp_count", fmt_number),
            ("Private connections",
             "private_count", fmt_number),
            ("School connections",
             "school_count", fmt_number),
            ("Population served",
             "pop_estimate", fmt_number),
            ("Per capita (L/p/day)",
             "per_capita", fmt_decimal),
        ]),
        ("FINANCIAL PERFORMANCE", [
            (f"Billed ({currency})",
             "total_billed", fmt_number),
            (f"Collected ({currency})",
             "total_collected", fmt_number),
            ("Collection rate (%)",
             "collection_rate", fmt_decimal),
            (f"Expenses ({currency})",
             "total_expenses", fmt_number),
            (f"Net surplus ({currency})",
             "net_surplus", fmt_number),
        ]),
        ("MAINTENANCE", [
            ("Total incidents",
             "total_incidents", fmt_number),
            ("Resolved incidents",
             "resolved_incidents", fmt_number),
            (f"Maintenance cost ({currency})",
             "total_maint_cost", fmt_number),
        ]),
    ]

    for section_name, indicators in sections:
        ws1.write(row, 0, section_name,
                  fmt_subheader)
        for i in range(12):
            ws1.write(row, i + 1, "",
                      fmt_subheader)
        row += 1

        for label, key, fmt in indicators:
            ws1.write(row, 0, label, fmt_cell)
            for i in range(1, 13):
                data = get_report_data(
                    system_id, year, i
                )
                val = data.get(key, 0)
                if key == "nrw_pct" and val >= 20:
                    ws1.write(row, i, val, fmt_alert)
                else:
                    ws1.write(row, i, val, fmt)
            row += 1

    # ── Sheet 2: DHIS2 Data Entry ──────────────────────
    ws2 = wb.add_worksheet("DHIS2 Data Entry")
    ws2.set_column("A:A", 38)
    ws2.set_column("B:B", 18)
    ws2.set_column("C:C", 15)
    ws2.set_column("D:D", 42)

    ws2.merge_range(
        "A1:D1",
        "DHIS2 Monthly Data Entry Sheet",
        fmt_title
    )
    ws2.merge_range(
        "A2:D2",
        f"{sys_name} — Uganda Water Sector Reporting",
        wb.add_format({
            "align": "center",
            "font_color": "#64748b"
        })
    )

    ws2.write(3, 0, "Data Element", fmt_header)
    ws2.write(3, 1, "Value", fmt_header)
    ws2.write(3, 2, "Unit", fmt_header)
    ws2.write(3, 3, "Notes", fmt_header)

    now        = datetime.now()
    dhis2_data = get_report_data(
        system_id, now.year, now.month
    )
    curr = dhis2_data.get("currency", "UGX")

    dhis2_elements = [
        ("", "", "", ""),
        ("WATER PRODUCTION", "", "",
         f"Period: {dhis2_data['period_label']}"),
        ("Volume of water produced",
         dhis2_data["total_pumped"], "m³",
         "From pump house bulk meter"),
        ("Volume of water consumed",
         dhis2_data["total_consumed"], "m³",
         "From tank outlet bulk meter"),
        ("Non-revenue water volume",
         dhis2_data["total_nrw_m3"], "m³",
         "Produced minus consumed"),
        ("Non-revenue water rate",
         dhis2_data["nrw_pct"], "%",
         "Target: below 20%"),
        ("", "", "", ""),
        ("SERVICE COVERAGE", "", "", ""),
        ("Active water connections",
         dhis2_data["total_customers"],
         "connections", "Active customers"),
        ("PSP connections",
         dhis2_data["psp_count"],
         "connections", "Public stand posts"),
        ("Private connections",
         dhis2_data["private_count"],
         "connections", "Household connections"),
        ("School connections",
         dhis2_data["school_count"],
         "connections", "School taps"),
        ("Population served",
         dhis2_data["pop_estimate"],
         "persons",
         "Actual figures from customer register"),
        ("Per capita water consumption",
         dhis2_data["per_capita"],
         "L/person/day", "Target: 20L/person/day"),
        ("", "", "", ""),
        ("FINANCIAL PERFORMANCE", "", "", ""),
        (f"Revenue billed ({curr})",
         dhis2_data["total_billed"], curr,
         "Total bills issued"),
        (f"Revenue collected ({curr})",
         dhis2_data["total_collected"], curr,
         "Actual cash received"),
        ("Revenue collection efficiency",
         dhis2_data["collection_rate"], "%",
         "Target: above 80%"),
        (f"Operational expenditure ({curr})",
         dhis2_data["total_expenses"], curr,
         "All operational costs"),
        (f"Revenue surplus/deficit ({curr})",
         dhis2_data["net_surplus"], curr,
         "Collected minus expenditure"),
        ("", "", "", ""),
        ("ASSET MANAGEMENT", "", "", ""),
        ("Maintenance incidents",
         dhis2_data["total_incidents"],
         "incidents", "All reported"),
        ("Resolved incidents",
         dhis2_data["resolved_incidents"],
         "incidents", "Successfully resolved"),
        (f"Maintenance cost ({curr})",
         dhis2_data["total_maint_cost"], curr,
         "Labour and materials"),
        ("Average tank level",
         dhis2_data["avg_tank_pct"], "%",
         "Average % full from dip readings"),
    ]

    section_keys = [
        "WATER PRODUCTION", "SERVICE COVERAGE",
        "FINANCIAL PERFORMANCE", "ASSET MANAGEMENT"
    ]

    for i, (element, value, unit, notes) in \
            enumerate(dhis2_elements):
        r = i + 4
        if element in section_keys:
            ws2.write(r, 0, element, fmt_subheader)
            ws2.write(r, 1, "", fmt_subheader)
            ws2.write(r, 2, "", fmt_subheader)
            ws2.write(r, 3, notes, fmt_subheader)
        elif element == "":
            for col in range(4):
                ws2.write(r, col, "")
        else:
            ws2.write(r, 0, element, fmt_cell)
            if isinstance(value, (int, float)):
                ws2.write(r, 1, value, fmt_decimal)
            else:
                ws2.write(r, 1, value or "", fmt_cell)
            ws2.write(r, 2, unit, fmt_cell)
            ws2.write(r, 3, notes, fmt_cell)

    # ── Sheet 3: Customer Ledger ───────────────────────
    ws3 = wb.add_worksheet("Customer Ledger")
    ws3.set_column("A:A", 12)
    ws3.set_column("B:B", 28)
    ws3.set_column("C:D", 14)
    ws3.set_column("E:G", 16)
    ws3.set_column("H:H", 12)

    ws3.merge_range(
        "A1:H1",
        f"Customer Ledger — {sys_name} — {year}",
        fmt_title
    )

    headers = [
        "Account", "Customer", "Type",
        "Population",
        f"Billed ({currency})",
        f"Paid ({currency})",
        f"Outstanding ({currency})",
        "Rate (%)"
    ]
    for i, h in enumerate(headers):
        ws3.write(2, i, h, fmt_header)

    total_b = total_p = total_pop_ws3 = 0
    for idx, c in enumerate(customers):
        c_bills  = [
            b for b in all_bills
            if b.customer_id == c.id
        ]
        billed   = sum(b.amount or 0
                       for b in c_bills)
        paid     = sum(b.amount_paid or 0
                       for b in c_bills)
        owed     = billed - paid
        rate     = round(
            (paid / billed) * 100, 1
        ) if billed > 0 else 0
        conn     = getattr(
            c, 'connection_type', 'PSP'
        ) or 'PSP'
        pop      = getattr(c, 'population', 0) or 0

        total_b       += billed
        total_p       += paid
        total_pop_ws3 += pop

        ws3.write(idx + 3, 0,
                  c.account_no, fmt_cell)
        ws3.write(idx + 3, 1, c.name, fmt_cell)
        ws3.write(idx + 3, 2, conn, fmt_cell)
        ws3.write(idx + 3, 3, pop, fmt_number)
        ws3.write(idx + 3, 4, billed, fmt_number)
        ws3.write(idx + 3, 5, paid, fmt_number)
        ws3.write(idx + 3, 6, owed, fmt_number)
        ws3.write(idx + 3, 7, rate, fmt_decimal)

    tot_row = len(customers) + 3
    tot_fmt = wb.add_format({
        "bold": True, "border": 1,
        "bg_color": "#0a1628",
        "font_color": "white"
    })
    ws3.write(tot_row, 0, "TOTAL", tot_fmt)
    ws3.write(tot_row, 1, "", tot_fmt)
    ws3.write(tot_row, 2, "", tot_fmt)
    ws3.write(tot_row, 3,
              total_pop_ws3, fmt_number)
    ws3.write(tot_row, 4, total_b, fmt_number)
    ws3.write(tot_row, 5, total_p, fmt_number)
    ws3.write(tot_row, 6,
              total_b - total_p, fmt_number)
    ws3.write(
        tot_row, 7,
        round(
            (total_p / total_b) * 100, 1
        ) if total_b > 0 else 0,
        fmt_decimal
    )

    writer.close()
    output.seek(0)
    return output.getvalue()


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

    st.markdown("## 📄 Reports & DHIS2 Export")
    st.markdown(
        f"<span style='color:#64748b;font-size:13px'>"
        f"{system_name} · Uganda Water Sector "
        f"Reporting</span>",
        unsafe_allow_html=True
    )
    st.divider()

    # ── Period selector ────────────────────────────────
    col1, col2, col3 = st.columns([2, 2, 3])
    with col1:
        current_year = datetime.now().year
        year = st.selectbox(
            "Year",
            options=list(range(
                current_year - 2,
                current_year + 1
            )),
            index=2
        )
    with col2:
        report_type = st.selectbox(
            "Report type",
            ["Monthly", "Annual"]
        )
    with col3:
        if report_type == "Monthly":
            month_names = [
                "January", "February", "March",
                "April", "May", "June", "July",
                "August", "September", "October",
                "November", "December"
            ]
            current_month = datetime.now().month
            month_name    = st.selectbox(
                "Month",
                options=month_names,
                index=current_month - 1
            )
            month = month_names.index(month_name) + 1
        else:
            month = None

    st.divider()

    with st.spinner("Compiling report data..."):
        data = get_report_data(
            system_id, year, month
        )

    period_label = data["period_label"]

    # ── DHIS2 Summary ──────────────────────────────────
    st.markdown(
        f"### DHIS2 Monthly Summary — {period_label}"
    )
    st.caption(
        "Uganda Water Sector standard indicators. "
        "Share with Water Office for DHIS2 submission."
    )

    st.markdown("#### 💧 Water Production")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(
            "Pumped",
            f"{data['total_pumped']:.1f} m³"
        )
    with c2:
        st.metric(
            "Consumed",
            f"{data['total_consumed']:.1f} m³"
        )
    with c3:
        st.metric(
            "NRW volume",
            f"{data['total_nrw_m3']:.1f} m³"
        )
    with c4:
        nrw_icon = "🔴" \
            if data["nrw_pct"] >= 20 else "🟢"
        st.metric(
            "NRW rate",
            f"{data['nrw_pct']}%",
            delta=f"{nrw_icon} "
                  f"{'ALERT' if data['nrw_pct'] >= 20 else 'OK'}"
        )

    st.markdown("#### 👥 Service Coverage")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(
            "Active connections",
            data["total_customers"]
        )
    with c2:
        st.metric(
            "Population served",
            f"{data['pop_estimate']:,}",
        )
    with c3:
        st.metric(
            "Per capita",
            f"{data['per_capita']} L/p/day"
        )
    with c4:
        st.metric(
            "Avg tank level",
            f"{data['avg_tank_pct']}%"
        )

    st.markdown("#### 💰 Financial Performance")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(
            f"Billed ({currency})",
            f"{data['total_billed']:,.0f}"
        )
    with c2:
        st.metric(
            f"Collected ({currency})",
            f"{data['total_collected']:,.0f}"
        )
    with c3:
        rate_icon = "🟢" \
            if data["collection_rate"] >= 80 \
            else "🔴"
        st.metric(
            "Collection rate",
            f"{data['collection_rate']}%",
            delta=f"{rate_icon} "
                  f"{'Good' if data['collection_rate'] >= 80 else 'Below target'}"
        )
    with c4:
        surplus = data["net_surplus"]
        st.metric(
            f"Net surplus ({currency})",
            f"{surplus:,.0f}",
            delta="Surplus" if surplus >= 0
            else "Deficit"
        )

    st.markdown("#### 🔧 Asset Management")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric(
            "Incidents reported",
            data["total_incidents"]
        )
    with c2:
        st.metric(
            "Incidents resolved",
            data["resolved_incidents"]
        )
    with c3:
        st.metric(
            f"Maintenance cost ({currency})",
            f"{data['total_maint_cost']:,.0f}"
        )

    st.divider()

    # ── DHIS2 table ────────────────────────────────────
    st.markdown("### DHIS2 Data Entry Table")
    st.caption(
        "Copy these values into your DHIS2 "
        "data entry form."
    )

    dhis2_rows = [
        {"Data Element": "Volume of water produced",
         "Value": f"{data['total_pumped']:.1f}",
         "Unit": "m³", "Status": "✓"},
        {"Data Element": "Volume of water consumed",
         "Value": f"{data['total_consumed']:.1f}",
         "Unit": "m³", "Status": "✓"},
        {"Data Element": "Non-revenue water volume",
         "Value": f"{data['total_nrw_m3']:.1f}",
         "Unit": "m³", "Status": "✓"},
        {"Data Element": "Non-revenue water rate",
         "Value": f"{data['nrw_pct']}",
         "Unit": "%",
         "Status": "🔴 ALERT"
                   if data["nrw_pct"] >= 20
                   else "🟢 OK"},
        {"Data Element": "Active connections",
         "Value": str(data["total_customers"]),
         "Unit": "connections", "Status": "✓"},
        {"Data Element": "PSP connections",
         "Value": str(data["psp_count"]),
         "Unit": "connections", "Status": "✓"},
        {"Data Element": "Private connections",
         "Value": str(data["private_count"]),
         "Unit": "connections", "Status": "✓"},
        {"Data Element": "School connections",
         "Value": str(data["school_count"]),
         "Unit": "connections", "Status": "✓"},
        {"Data Element": "Population served",
         "Value": f"{data['pop_estimate']:,}",
         "Unit": "persons",
         "Status": "✓ Actual figures"},
        {"Data Element": "Per capita consumption",
         "Value": f"{data['per_capita']}",
         "Unit": "L/person/day", "Status": "✓"},
        {"Data Element": f"Revenue billed ({currency})",
         "Value": f"{data['total_billed']:,.0f}",
         "Unit": currency, "Status": "✓"},
        {"Data Element": f"Revenue collected ({currency})",
         "Value": f"{data['total_collected']:,.0f}",
         "Unit": currency, "Status": "✓"},
        {"Data Element": "Collection efficiency",
         "Value": f"{data['collection_rate']}",
         "Unit": "%",
         "Status": "🟢 Good"
                   if data["collection_rate"] >= 80
                   else "🔴 Below target"},
        {"Data Element": f"Expenditure ({currency})",
         "Value": f"{data['total_expenses']:,.0f}",
         "Unit": currency, "Status": "✓"},
        {"Data Element": f"Net surplus ({currency})",
         "Value": f"{data['net_surplus']:,.0f}",
         "Unit": currency,
         "Status": "Surplus"
                   if data["net_surplus"] >= 0
                   else "Deficit"},
        {"Data Element": "Maintenance incidents",
         "Value": str(data["total_incidents"]),
         "Unit": "incidents", "Status": "✓"},
        {"Data Element": "Resolved incidents",
         "Value": str(data["resolved_incidents"]),
         "Unit": "incidents", "Status": "✓"},
        {"Data Element": f"Maintenance cost ({currency})",
         "Value": f"{data['total_maint_cost']:,.0f}",
         "Unit": currency, "Status": "✓"},
        {"Data Element": "Average tank level",
         "Value": f"{data['avg_tank_pct']}",
         "Unit": "%",
         "Status": "✓"
                   if data["avg_tank_pct"] > 20
                   else "🔴 Low"},
    ]

    st.dataframe(
        pd.DataFrame(dhis2_rows),
        use_container_width=True,
        hide_index=True
    )

    st.divider()

    # ── Export buttons ─────────────────────────────────
    st.markdown("### Export")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**📊 Excel export**")
        st.caption(
            "Full annual report with monthly "
            "breakdown, DHIS2 data entry sheet "
            "and customer ledger with population."
        )
        with st.spinner("Generating Excel..."):
            excel_data = generate_excel(
                system_id, year
            )
        fname = (
            f"Maji360_"
            f"{system_name.replace(' ', '_')}"
            f"_{year}.xlsx"
        )
        st.download_button(
            label    = "⬇️ Download Excel report",
            data     = excel_data,
            file_name = fname,
            mime     = "application/vnd.openxmlformats-"
                       "officedocument.spreadsheetml.sheet",
            use_container_width=True,
            type     = "primary"
        )

    with col2:
        st.markdown("**📋 CSV export**")
        st.caption(
            "Simple CSV of all DHIS2 indicators "
            "for the selected period."
        )
        csv_rows = []
        for r in dhis2_rows:
            csv_rows.append({
                "System":       system_name,
                "Period":       period_label,
                "Data Element": r["Data Element"],
                "Value":        r["Value"],
                "Unit":         r["Unit"]
            })
        csv_data = pd.DataFrame(
            csv_rows
        ).to_csv(index=False)
        fname_csv = (
            f"Maji360_DHIS2_"
            f"{system_name.replace(' ', '_')}_"
            f"{period_label.replace(' ', '_')}.csv"
        )
        st.download_button(
            label    = "⬇️ Download CSV",
            data     = csv_data,
            file_name = fname_csv,
            mime     = "text/csv",
            use_container_width=True
        )
