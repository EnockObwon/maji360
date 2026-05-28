import streamlit as st
import pandas as pd
import io
from datetime import datetime, timezone
from collections import defaultdict
from sqlalchemy import text as sql_text
from core.database import (
    get_session, WaterSystem, Customer,
    Bill, MeterReading, Payment
)
from core.auth import require_login


# Excel export helper
def _generate_reconciliation_excel(
    system_id: int,
    system_name: str,
    currency: str,
    customers: list,
    all_bills: list,
    all_payments: list,
) -> bytes:
    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine="xlsxwriter")
    wb     = writer.book

    fmt_title  = wb.add_format({"bold": True, "font_size": 13, "font_color": "#0ea5e9", "align": "center"})
    fmt_header = wb.add_format({"bold": True, "bg_color": "#0a1628", "font_color": "white", "border": 1, "align": "center"})
    fmt_cell   = wb.add_format({"border": 1})
    fmt_num    = wb.add_format({"border": 1, "num_format": "#,##0", "align": "right"})
    fmt_red    = wb.add_format({"border": 1, "num_format": "#,##0", "align": "right", "font_color": "#dc2626"})
    fmt_green  = wb.add_format({"border": 1, "num_format": "#,##0", "align": "right", "font_color": "#16a34a"})
    fmt_gen    = wb.add_format({"align": "center", "font_color": "#64748b", "font_size": 10})

    cust_map = {c.id: c for c in customers}

    # Sheet 1: Bills Register
    ws1 = wb.add_worksheet("Bills Register")
    ws1.set_column("A:A", 14)
    ws1.set_column("B:B", 32)
    ws1.set_column("C:C", 14)
    ws1.set_column("D:D", 12)
    ws1.set_column("E:H", 16)
    ws1.set_column("I:I", 12)

    ws1.merge_range("A1:I1", f"Bills Register — {system_name}", fmt_title)
    ws1.merge_range("A2:I2", f"Generated: {datetime.now().strftime('%d %b %Y %H:%M')}", fmt_gen)
    for i, h in enumerate(["Account","Customer","Type","Bill Month",
                            f"Billed ({currency})",f"Paid ({currency})",
                            f"Outstanding ({currency})","Status"]):
        ws1.write(2, i, h, fmt_header)

    for row, b in enumerate(sorted(all_bills, key=lambda x: (x.bill_month or "", x.customer_id))):
        c        = cust_map.get(b.customer_id)
        billed   = b.amount      or 0
        paid     = b.amount_paid or 0
        owed     = billed - paid
        status   = "Paid" if b.is_paid else ("Partial" if paid > 0 else "Unpaid")
        r = row + 3
        ws1.write(r, 0, c.account_no          if c else "", fmt_cell)
        ws1.write(r, 1, c.name                if c else "", fmt_cell)
        ws1.write(r, 2, c.connection_type     if c else "", fmt_cell)
        ws1.write(r, 3, b.bill_month or "",   fmt_cell)
        ws1.write(r, 4, billed,               fmt_num)
        ws1.write(r, 5, paid,                 fmt_green)
        ws1.write(r, 6, owed,                 fmt_red if owed > 0 else fmt_num)
        ws1.write(r, 7, status,               fmt_cell)

    # Sheet 2: Payments Register
    ws2 = wb.add_worksheet("Payments Register")
    ws2.set_column("A:A", 14)
    ws2.set_column("B:B", 32)
    ws2.set_column("C:C", 14)
    ws2.set_column("D:D", 16)
    ws2.set_column("E:F", 18)
    ws2.set_column("G:H", 22)

    ws2.merge_range("A1:H1", f"Payments Register — {system_name}", fmt_title)
    ws2.merge_range("A2:H2", f"Generated: {datetime.now().strftime('%d %b %Y %H:%M')}", fmt_gen)
    for i, h in enumerate(["Account","Customer","Payment Date",
                            f"Amount ({currency})","Method","Reference","Notes"]):
        ws2.write(2, i, h, fmt_header)

    for row, p in enumerate(sorted(all_payments, key=lambda x: str(x.get("paid_at","")))):
        c   = cust_map.get(p.get("customer_id"))
        r   = row + 3
        dt  = p.get("paid_at")
        dt_str = dt.strftime("%d %b %Y") if hasattr(dt, "strftime") else str(dt)[:10]
        ws2.write(r, 0, c.account_no       if c else "", fmt_cell)
        ws2.write(r, 1, c.name             if c else "", fmt_cell)
        ws2.write(r, 2, dt_str,            fmt_cell)
        ws2.write(r, 3, p.get("amount",0), fmt_green)
        ws2.write(r, 4, p.get("payment_method","") or "", fmt_cell)
        ws2.write(r, 5, p.get("reference","")  or "", fmt_cell)
        ws2.write(r, 6, p.get("notes","")     or "", fmt_cell)

    # Sheet 3: Customer Statements 
    ws3 = wb.add_worksheet("Customer Statements")
    ws3.set_column("A:A", 14)
    ws3.set_column("B:B", 32)
    ws3.set_column("C:C", 16)
    ws3.set_column("D:D", 22)
    ws3.set_column("E:G", 16)
    ws3.set_column("H:H", 16)

    ws3.merge_range("A1:H1", f"Customer Statements — {system_name}", fmt_title)
    ws3.merge_range("A2:H2", f"Generated: {datetime.now().strftime('%d %b %Y %H:%M')}", fmt_gen)
    for i, h in enumerate(["Account","Customer","Date","Description",
                            f"Debit ({currency})", f"Credit ({currency})",
                            f"Balance ({currency})","Type"]):
        ws3.write(2, i, h, fmt_header)

    # Build per-customer statement
    bills_by_cust    = defaultdict(list)
    payments_by_cust = defaultdict(list)
    for b in all_bills:
        bills_by_cust[b.customer_id].append(b)
    for p in all_payments:
        if p.get("customer_id"):
            payments_by_cust[p["customer_id"]].append(p)

    excel_row = 3
    for c in customers:
        # Merge all transactions for this customer
        txns = []
        for b in bills_by_cust.get(c.id, []):
            txns.append({
                "date":    b.bill_month or "",
                "desc":    f"Bill — {b.bill_month}",
                "debit":   b.amount or 0,
                "credit":  0,
                "type":    "Bill",
            })
        for p in payments_by_cust.get(c.id, []):
            dt = p.get("paid_at")
            txns.append({
                "date":   dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10],
                "desc":   f"Payment — {p.get('payment_method','Cash')}",
                "debit":  0,
                "credit": p.get("amount", 0),
                "type":   "Payment",
            })

        txns.sort(key=lambda x: x["date"])
        balance = 0
        for t in txns:
            balance += t["debit"] - t["credit"]
            ws3.write(excel_row, 0, c.account_no, fmt_cell)
            ws3.write(excel_row, 1, c.name,       fmt_cell)
            ws3.write(excel_row, 2, t["date"],    fmt_cell)
            ws3.write(excel_row, 3, t["desc"],    fmt_cell)
            ws3.write(excel_row, 4, t["debit"]  if t["debit"]  > 0 else "", fmt_red   if t["debit"]  > 0 else fmt_cell)
            ws3.write(excel_row, 5, t["credit"] if t["credit"] > 0 else "", fmt_green if t["credit"] > 0 else fmt_cell)
            ws3.write(excel_row, 6, balance,      fmt_red if balance > 0 else fmt_green)
            ws3.write(excel_row, 7, t["type"],    fmt_cell)
            excel_row += 1

        # Closing balance row
        tot_billed = sum(b.amount      or 0 for b in bills_by_cust.get(c.id, []))
        tot_paid   = sum(p.get("amount",0)  for p in payments_by_cust.get(c.id, []))
        fmt_bal    = wb.add_format({"bold": True, "border": 1, "bg_color": "#fef2f2" if tot_billed > tot_paid else "#f0fdf4"})
        ws3.write(excel_row, 0, c.account_no,            fmt_bal)
        ws3.write(excel_row, 1, f"BALANCE — {c.name}",  fmt_bal)
        ws3.write(excel_row, 2, "",                      fmt_bal)
        ws3.write(excel_row, 3, "",                      fmt_bal)
        ws3.write(excel_row, 4, tot_billed, wb.add_format({"bold":True,"border":1,"num_format":"#,##0","align":"right","bg_color":"#fef2f2"}))
        ws3.write(excel_row, 5, tot_paid,   wb.add_format({"bold":True,"border":1,"num_format":"#,##0","align":"right","bg_color":"#f0fdf4"}))
        ws3.write(excel_row, 6, tot_billed - tot_paid, wb.add_format({"bold":True,"border":1,"num_format":"#,##0","align":"right","bg_color":"#fef2f2" if tot_billed > tot_paid else "#f0fdf4"}))
        ws3.write(excel_row, 7, "",                      fmt_bal)
        excel_row += 2  # blank row between customers

    writer.close()
    output.seek(0)
    return output.getvalue()


def show():
    require_login()

    system_id   = st.session_state.get("selected_system_id")
    system_name = st.session_state.get("selected_system_name", "")
    currency    = st.session_state.get("currency", "UGX")

    if not system_id:
        st.warning("Please select a water system.")
        return

    session        = get_session()
    system         = session.query(WaterSystem).filter_by(id=system_id).first()
    uses_mwater    = getattr(system, "uses_mwater", True)
    tariff_psp     = getattr(system, "tariff_psp",     2500.0) or 2500.0
    tariff_private = getattr(system, "tariff_private", 3000.0) or 3000.0
    customers      = session.query(Customer).filter_by(
        system_id=system_id, is_active=True
    ).order_by(Customer.name).all()
    session.close()

    st.markdown("## 💵 Customer Billing")
    st.markdown(
        f"<span style='color:#64748b;font-size:13px'>"
        f"{system_name} · Bill customers and record payments</span>",
        unsafe_allow_html=True
    )
    st.divider()

    if not customers:
        st.warning("No customers registered. Please add customers first in System Setup.")
        return

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📋 Generate bill",
        "💰 Record payment",
        "📊 Customer balances",
        "🧾 Bills register",
        "💳 Payments register",
        "📒 Customer statements",
    ])

    # Tab 1: Generate bill (unchanged) 
    with tab1:
        st.markdown("### Generate customer bill")
        cust_options  = {f"{c.account_no} — {c.name}": c for c in customers}
        selected_name = st.selectbox("Select customer *", options=list(cust_options.keys()), key="bill_customer")
        customer      = cust_options[selected_name]
        conn_type     = getattr(customer, "connection_type", "PSP") or "PSP"
        tariff        = tariff_private if conn_type == "Private" else tariff_psp
        last_rdg      = getattr(customer, "last_reading", 0) or 0

        col1, col2, col3 = st.columns(3)
        with col1: st.markdown(f"**Connection:** {conn_type}")
        with col2: st.markdown(f"**Tariff:** {currency} {tariff:,.0f}/m³")
        with col3: st.markdown(f"**Last reading:** {last_rdg:.1f} m³")
        st.divider()

        with st.form("bill_form"):
            col1, col2 = st.columns(2)
            with col1:
                prev_reading = st.number_input("Previous meter reading (m³) *", min_value=0.0, value=float(last_rdg), step=0.1, format="%.1f")
            with col2:
                curr_reading = st.number_input("Current meter reading (m³) *",  min_value=0.0, value=float(last_rdg), step=0.1, format="%.1f")
            bill_date = st.date_input("Billing date *", value=datetime.now().date())

            if curr_reading > prev_reading:
                consumption = round(curr_reading - prev_reading, 2)
                bill_amount = round(consumption * tariff, 0)
                st.markdown(
                    f"<div style='background:#f0fdf4;border-radius:8px;padding:12px 16px;margin:8px 0'>"
                    f"<b>Bill preview</b><br>Consumption: {consumption:.1f} m³<br>"
                    f"Amount: {currency} {bill_amount:,.0f}</div>",
                    unsafe_allow_html=True
                )
            else:
                consumption = bill_amount = 0

            if st.form_submit_button("✓ Generate bill & send SMS", use_container_width=True, type="primary"):
                if curr_reading <= prev_reading:
                    st.error("Current reading must be greater than previous reading.")
                else:
                    bill_month = bill_date.strftime("%Y-%m")
                    session    = get_session()
                    existing   = session.query(Bill).filter_by(
                        system_id=system_id, customer_id=customer.id, bill_month=bill_month
                    ).first()
                    if existing:
                        st.warning(f"Bill already exists for {customer.name} in {bill_month}.")
                        session.close()
                    else:
                        session.add(Bill(
                            system_id=system_id, customer_id=customer.id,
                            bill_month=bill_month, units_m3=consumption,
                            amount=bill_amount, amount_paid=0.0, is_paid=False
                        ))
                        session.add(MeterReading(
                            system_id=system_id, customer_id=customer.id,
                            reading_type="customer",
                            reading_date=datetime.combine(bill_date, datetime.min.time()).replace(tzinfo=timezone.utc),
                            start_reading=prev_reading, end_reading=curr_reading, volume=consumption
                        ))
                        cust_obj = session.query(Customer).filter_by(id=customer.id).first()
                        if cust_obj:
                            cust_obj.last_reading      = curr_reading
                            cust_obj.last_reading_date = datetime.now(timezone.utc)
                        session.commit()
                        session.close()
                        if customer.phone:
                            try:
                                import africastalking
                                at_user = st.secrets.get("AT_USERNAME", "")
                                at_key  = st.secrets.get("AT_API_KEY", "")
                                sender  = st.secrets.get("AT_SENDER_ID", "Maji360")
                                if at_user and at_key:
                                    africastalking.initialize(at_user, at_key)
                                    africastalking.SMS.send(
                                        f"Maji360 | {system_name}\nDear Caretaker,\n"
                                        f"Acc: {customer.account_no}\nBill: {bill_month}\n"
                                        f"Units: {consumption:.1f} m³\n"
                                        f"Amount: {currency} {bill_amount:,.0f}\nPay promptly. Thank you.",
                                        [customer.phone], sender_id=sender
                                    )
                            except Exception:
                                pass
                        st.success(f"✓ Bill generated — {customer.name} {currency} {bill_amount:,.0f}")
                        st.rerun()

    # Tab 2: Record payment (unchanged) 
    with tab2:
        st.markdown("### Record payment")
        cust_options2  = {f"{c.account_no} — {c.name}": c for c in customers}
        selected_name2 = st.selectbox("Select customer *", options=list(cust_options2.keys()), key="pay_customer")
        customer2      = cust_options2[selected_name2]

        session   = get_session()
        all_bills2 = session.query(Bill).filter_by(customer_id=customer2.id).all()
        session.close()

        total_billed = sum(b.amount      or 0 for b in all_bills2)
        total_paid   = sum(b.amount_paid or 0 for b in all_bills2)
        outstanding  = total_billed - total_paid

        col1, col2, col3 = st.columns(3)
        with col1: st.metric("Total billed",  f"{currency} {total_billed:,.0f}")
        with col2: st.metric("Total paid",    f"{currency} {total_paid:,.0f}")
        with col3: st.metric("Outstanding",   f"{currency} {outstanding:,.0f}")

        if outstanding <= 0:
            st.success("✓ No outstanding balance.")
        else:
            with st.form("payment_form"):
                col1, col2 = st.columns(2)
                with col1:
                    pay_amount = st.number_input(f"Amount paid ({currency}) *", min_value=0.0, max_value=float(outstanding), value=float(outstanding), step=500.0, format="%.0f")
                with col2:
                    pay_method = st.selectbox("Payment method *", ["Cash","MTN Mobile Money","Airtel Money","Bank transfer","Other"])
                pay_ref   = st.text_input("Reference / receipt number")
                pay_notes = st.text_input("Notes (optional)")
                pay_date  = st.date_input("Payment date *", value=datetime.now().date())

                if st.form_submit_button("✓ Record payment", use_container_width=True, type="primary") and pay_amount > 0:
                    session = get_session()
                    unpaid  = session.query(Bill).filter(
                        Bill.customer_id == customer2.id, Bill.is_paid == False
                    ).order_by(Bill.bill_month).all()
                    remaining = pay_amount
                    for bill in unpaid:
                        if remaining <= 0: break
                        owed = (bill.amount or 0) - (bill.amount_paid or 0)
                        if owed <= 0: continue
                        if remaining >= owed:
                            bill.amount_paid = bill.amount
                            bill.is_paid     = True
                            remaining       -= owed
                        else:
                            bill.amount_paid = (bill.amount_paid or 0) + remaining
                            remaining = 0
                    current_user = st.session_state.get("user", {})
                    session.add(Payment(
                        system_id=system_id, customer_id=customer2.id,
                        amount=pay_amount, payment_method=pay_method,
                        reference=pay_ref or None, notes=pay_notes or None,
                        recorded_by=current_user.get("id"),
                        paid_at=datetime.combine(pay_date, datetime.min.time()).replace(tzinfo=timezone.utc)
                    ))
                    session.commit()
                    session.close()
                    if customer2.phone:
                        try:
                            import africastalking
                            at_user = st.secrets.get("AT_USERNAME","")
                            at_key  = st.secrets.get("AT_API_KEY","")
                            sender  = st.secrets.get("AT_SENDER_ID","Maji360")
                            if at_user and at_key:
                                africastalking.initialize(at_user, at_key)
                                africastalking.SMS.send(
                                    f"Maji360 | {system_name}\nPayment received: {currency} {pay_amount:,.0f}\n"
                                    f"Acc: {customer2.account_no}\nBalance: {currency} {max(0, outstanding-pay_amount):,.0f}\nThank you.",
                                    [customer2.phone], sender_id=sender
                                )
                        except Exception:
                            pass
                    st.success(f"✓ Payment of {currency} {pay_amount:,.0f} recorded.")
                    st.rerun()

    # Tab 3: Customer balances (unchanged) 
    with tab3:
        st.markdown("### All customer balances")
        session = get_session()
        rows    = []
        for c in customers:
            c_bills = session.query(Bill).filter_by(customer_id=c.id).all()
            billed  = sum(b.amount      or 0 for b in c_bills)
            paid    = sum(b.amount_paid or 0 for b in c_bills)
            owed    = billed - paid
            rate    = round((paid / billed) * 100, 0) if billed > 0 else 0
            rows.append({
                "Account":     c.account_no,
                "Customer":    c.name,
                "Type":        c.connection_type or "PSP",
                "Billed":      f"{currency} {billed:,.0f}",
                "Paid":        f"{currency} {paid:,.0f}",
                "Outstanding": f"{currency} {owed:,.0f}",
                "Rate":        f"{rate:.0f}%",
                "Phone":       c.phone or "—",
            })
        session.close()
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No billing data yet.")

    # Shared data load for tabs 4-6 
    # Load once and reuse across tabs
    @st.cache_data(ttl=120, show_spinner=False)
    def _load_reconciliation_data(sid: int):
        sess  = get_session()
        bills = sess.query(Bill).filter_by(system_id=sid).all()
        try:
            pay_rows = sess.execute(sql_text(
                "SELECT id, customer_id, amount, payment_method, "
                "reference, notes, paid_at, status "
                "FROM payments WHERE system_id = :sid "
                "ORDER BY paid_at"
            ), {"sid": sid}).fetchall()
            payments = [
                {
                    "id":             r[0],
                    "customer_id":    r[1],
                    "amount":         float(r[2] or 0),
                    "payment_method": r[3] or "Cash",
                    "reference":      r[4] or "",
                    "notes":          r[5] or "",
                    "paid_at":        r[6],
                    "status":         r[7] or "",
                }
                for r in pay_rows
            ]
        except Exception:
            payments = []
        sess.close()
        return bills, payments

    all_bills, all_payments = _load_reconciliation_data(system_id)
    cust_map = {c.id: c for c in customers}

    # Tab 4: Bills register 
    with tab4:
        st.markdown("### Bills register")
        st.caption(
            "Every individual bill issued. "
            "Amount Paid reflects the current allocation — "
            "it updates as new payments are received."
        )

        # Filters
        col1, col2, col3 = st.columns(3)
        with col1:
            months = sorted({b.bill_month for b in all_bills if b.bill_month}, reverse=True)
            month_filter = st.selectbox("Filter by month", ["All months"] + months, key="br_month")
        with col2:
            status_filter = st.selectbox("Filter by status", ["All", "Unpaid", "Partial", "Paid"], key="br_status")
        with col3:
            cust_names = ["All customers"] + [f"{c.account_no} — {c.name}" for c in customers]
            cust_filter = st.selectbox("Filter by customer", cust_names, key="br_cust")

        rows = []
        for b in sorted(all_bills, key=lambda x: (x.bill_month or "", x.customer_id)):
            c      = cust_map.get(b.customer_id)
            billed = b.amount      or 0
            paid   = b.amount_paid or 0
            owed   = billed - paid
            status = "Paid" if b.is_paid else ("Partial" if paid > 0 else "Unpaid")

            if month_filter != "All months" and b.bill_month != month_filter:
                continue
            if status_filter != "All" and status != status_filter:
                continue
            if cust_filter != "All customers":
                acc_name = f"{c.account_no} — {c.name}" if c else ""
                if acc_name != cust_filter:
                    continue

            rows.append({
                "Account":          c.account_no        if c else "—",
                "Customer":         c.name              if c else "—",
                "Type":             c.connection_type   if c else "—",
                "Bill month":       b.bill_month or "—",
                "Units (m³)":       f"{b.units_m3:.1f}" if b.units_m3 else "—",
                f"Billed ({currency})":      f"{billed:,.0f}",
                f"Paid ({currency})":        f"{paid:,.0f}",
                f"Outstanding ({currency})": f"{owed:,.0f}",
                "Status":           status,
            })

        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption(f"{len(rows)} bills shown · "
                       f"Total billed: {currency} "
                       f"{sum(b.amount or 0 for b in all_bills if (month_filter=='All months' or b.bill_month==month_filter)):,.0f}")
        else:
            st.info("No bills match the selected filters.")

    # Tab 5: Payments register 
    with tab5:
        st.markdown("### Payments register")
        st.caption(
            "Every individual payment received, with the actual date "
            "cash was received. This is what the Board's cash book "
            "should reflect. Use this to reconcile against mWater records."
        )

        col1, col2 = st.columns(2)
        with col1:
            pay_months  = sorted({
                str(p["paid_at"])[:7]
                for p in all_payments if p.get("paid_at")
            }, reverse=True)
            pay_month_f = st.selectbox("Filter by month", ["All months"] + pay_months, key="pr_month")
        with col2:
            pay_cust_f  = st.selectbox("Filter by customer",
                ["All customers"] + [f"{c.account_no} — {c.name}" for c in customers],
                key="pr_cust"
            )

        pay_rows = []
        for p in all_payments:
            c  = cust_map.get(p.get("customer_id"))
            dt = p.get("paid_at")
            dt_str  = dt.strftime("%d %b %Y") if hasattr(dt, "strftime") else str(dt)[:10]
            dt_month = str(dt)[:7] if dt else ""

            if pay_month_f != "All months" and dt_month != pay_month_f:
                continue
            if pay_cust_f != "All customers":
                acc_name = f"{c.account_no} — {c.name}" if c else ""
                if acc_name != pay_cust_f:
                    continue

            pay_rows.append({
                "Account":        c.account_no        if c else "—",
                "Customer":       c.name              if c else "—",
                "Payment date":   dt_str,
                f"Amount ({currency})": f"{p['amount']:,.0f}",
                "Method":         p.get("payment_method", "Cash"),
                "Reference":      p.get("reference", "") or "—",
                "Notes":          p.get("notes", "")     or "—",
            })

        if pay_rows:
            df2 = pd.DataFrame(pay_rows)
            st.dataframe(df2, use_container_width=True, hide_index=True)
            visible_total = sum(
                p["amount"] for p in all_payments
                if (pay_month_f == "All months" or str(p.get("paid_at",""))[:7] == pay_month_f)
            )
            st.caption(f"{len(pay_rows)} payments shown · "
                       f"Total: {currency} {visible_total:,.0f}")
        else:
            st.info("No payments match the selected filters.")

    # Tab 6: Customer statements 
    with tab6:
        st.markdown("### Customer statement")
        st.caption(
            "Chronological ledger of bills (debits) and payments (credits) "
            "with running balance. Use to reconcile individual customer accounts."
        )

        col1, col2 = st.columns([2, 1])
        with col1:
            stmt_cust_opts = {f"{c.account_no} — {c.name}": c for c in customers}
            stmt_selected  = st.selectbox("Select customer", list(stmt_cust_opts.keys()), key="stmt_cust")
            stmt_customer  = stmt_cust_opts[stmt_selected]
        with col2:
            st.markdown("<br>", unsafe_allow_html=True)

        # Bills for this customer
        cust_bills = [b for b in all_bills if b.customer_id == stmt_customer.id]
        cust_pays  = [p for p in all_payments if p.get("customer_id") == stmt_customer.id]

        # Build chronological ledger
        ledger = []
        for b in cust_bills:
            ledger.append({
                "sort_key": b.bill_month or "",
                "Date":     b.bill_month or "—",
                "Type":     "🧾 Bill",
                "Description": f"Bill — {b.bill_month}  ({b.units_m3:.1f} m³)" if b.units_m3 else f"Bill — {b.bill_month}",
                "Debit":    b.amount or 0,
                "Credit":   0,
            })
        for p in cust_pays:
            dt = p.get("paid_at")
            dt_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
            ledger.append({
                "sort_key": dt_str,
                "Date":     dt.strftime("%d %b %Y") if hasattr(dt, "strftime") else dt_str,
                "Type":     "💳 Payment",
                "Description": f"Payment — {p.get('payment_method','Cash')}"
                               + (f" / {p['reference']}" if p.get("reference") else ""),
                "Debit":    0,
                "Credit":   p["amount"],
            })

        ledger.sort(key=lambda x: x["sort_key"])

        # Running balance
        balance = 0
        display_rows = []
        for t in ledger:
            balance += t["Debit"] - t["Credit"]
            display_rows.append({
                "Date":        t["Date"],
                "Type":        t["Type"],
                "Description": t["Description"],
                f"Debit ({currency})":   f"{t['Debit']:,.0f}"   if t["Debit"]  > 0 else "—",
                f"Credit ({currency})":  f"{t['Credit']:,.0f}"  if t["Credit"] > 0 else "—",
                f"Balance ({currency})": f"{balance:,.0f}",
            })

        if display_rows:
            # Summary metrics
            tot_billed = sum(b.amount      or 0 for b in cust_bills)
            tot_paid   = sum(p["amount"]       for p in cust_pays)
            tot_alloc  = sum(b.amount_paid or 0 for b in cust_bills)
            c1, c2, c3, c4 = st.columns(4)
            with c1: st.metric("Total billed",      f"{currency} {tot_billed:,.0f}")
            with c2: st.metric("Cash received",      f"{currency} {tot_paid:,.0f}")
            with c3: st.metric("Allocated to bills", f"{currency} {tot_alloc:,.0f}")
            with c4:
                closing = tot_billed - tot_paid
                st.metric("Closing balance",  f"{currency} {closing:,.0f}")

            st.markdown("---")
            st.dataframe(
                pd.DataFrame(display_rows),
                use_container_width=True,
                hide_index=True
            )

            # Reconciliation note if cash ≠ allocation
            if abs(tot_paid - tot_alloc) > 1:
                st.warning(
                    f"⚠ Cash received ({currency} {tot_paid:,.0f}) differs from "
                    f"amount allocated to bills ({currency} {tot_alloc:,.0f}). "
                    f"Difference: {currency} {tot_paid - tot_alloc:,.0f}. "
                    f"This may indicate unallocated payments or rounding."
                )
        else:
            st.info("No transactions found for this customer.")

        st.divider()

        # Excel export (all customers) 
        st.markdown("### Export reconciliation report")
        st.caption(
            "Downloads Bills Register, Payments Register and "
            "Customer Statements for all customers in one Excel workbook."
        )
        with st.spinner("Building Excel..."):
            excel_bytes = _generate_reconciliation_excel(
                system_id, system_name, currency,
                customers, all_bills, all_payments
            )
        fname = f"Maji360_Reconciliation_{system_name.replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        st.download_button(
            label="⬇️ Download reconciliation workbook",
            data=excel_bytes,
            file_name=fname,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            type="primary"
        )
