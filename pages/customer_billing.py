import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from core.database import (
    get_session, WaterSystem, Customer,
    Bill, MeterReading, Payment
)
from core.auth import require_login


def show():
    require_login()

    system_id   = st.session_state.get("selected_system_id")
    system_name = st.session_state.get(
        "selected_system_name", ""
    )
    currency    = st.session_state.get("currency", "UGX")

    if not system_id:
        st.warning("Please select a water system.")
        return

    session     = get_session()
    system      = session.query(WaterSystem).filter_by(
        id=system_id
    ).first()
    uses_mwater    = getattr(system, 'uses_mwater', True)
    tariff_psp     = getattr(system, 'tariff_psp', 2500.0) or 2500.0
    tariff_private = getattr(system, 'tariff_private', 3000.0) or 3000.0
    customers      = session.query(Customer).filter_by(
        system_id=system_id, is_active=True
    ).order_by(Customer.name).all()
    session.close()

    st.markdown("## 💵 Customer Billing")
    st.markdown(
        f"<span style='color:#64748b;font-size:13px'>"
        f"{system_name} · Bill customers and "
        f"record payments</span>",
        unsafe_allow_html=True
    )
    st.divider()

    if not customers:
        st.warning(
            "No customers registered. "
            "Please add customers first in "
            "the System Setup page."
        )
        return

    tab1, tab2, tab3 = st.tabs([
        "📋 Generate bill",
        "💰 Record payment",
        "📊 Customer balances"
    ])

    # ── Tab 1: Generate bill ───────────────────────────
    with tab1:
        st.markdown("### Generate customer bill")

        cust_options = {
            f"{c.account_no} — {c.name}": c
            for c in customers
        }
        selected_name = st.selectbox(
            "Select customer *",
            options=list(cust_options.keys()),
            key="bill_customer"
        )
        customer = cust_options[selected_name]

        conn_type = getattr(
            customer, 'connection_type', 'PSP'
        ) or 'PSP'
        tariff    = tariff_private \
                    if conn_type == "Private" \
                    else tariff_psp
        last_rdg  = getattr(
            customer, 'last_reading', 0
        ) or 0

        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"**Connection:** {conn_type}")
        with col2:
            st.markdown(
                f"**Tariff:** {currency} "
                f"{tariff:,.0f}/m³"
            )
        with col3:
            st.markdown(
                f"**Last reading:** {last_rdg:.1f} m³"
            )

        st.divider()

        with st.form("bill_form"):
            col1, col2 = st.columns(2)
            with col1:
                prev_reading = st.number_input(
                    "Previous meter reading (m³) *",
                    min_value=0.0,
                    value=float(last_rdg),
                    step=0.1,
                    format="%.1f"
                )
            with col2:
                curr_reading = st.number_input(
                    "Current meter reading (m³) *",
                    min_value=0.0,
                    value=float(last_rdg),
                    step=0.1,
                    format="%.1f"
                )

            bill_date = st.date_input(
                "Billing date *",
                value=datetime.now().date()
            )

            if curr_reading > prev_reading:
                consumption = round(
                    curr_reading - prev_reading, 2
                )
                bill_amount = round(
                    consumption * tariff, 0
                )
                st.markdown(
                    f"<div style='background:#f0fdf4;"
                    f"border-radius:8px;"
                    f"padding:12px 16px;margin:8px 0'>"
                    f"<b>Bill preview</b><br>"
                    f"Consumption: {consumption:.1f} m³"
                    f"<br>Amount: {currency} "
                    f"{bill_amount:,.0f}</div>",
                    unsafe_allow_html=True
                )
            else:
                consumption = 0
                bill_amount = 0

            submitted = st.form_submit_button(
                "✓ Generate bill & send SMS",
                use_container_width=True,
                type="primary"
            )

            if submitted:
                if curr_reading <= prev_reading:
                    st.error(
                        "Current reading must be "
                        "greater than previous reading."
                    )
                else:
                    bill_month = bill_date.strftime(
                        "%Y-%m"
                    )
                    session  = get_session()
                    existing = session.query(Bill).filter_by(
                        system_id   = system_id,
                        customer_id = customer.id,
                        bill_month  = bill_month
                    ).first()

                    if existing:
                        st.warning(
                            f"Bill already exists for "
                            f"{customer.name} in "
                            f"{bill_month}."
                        )
                        session.close()
                    else:
                        session.add(Bill(
                            system_id   = system_id,
                            customer_id = customer.id,
                            bill_month  = bill_month,
                            units_m3    = consumption,
                            amount      = bill_amount,
                            amount_paid = 0.0,
                            is_paid     = False
                        ))
                        session.add(MeterReading(
                            system_id     = system_id,
                            customer_id   = customer.id,
                            reading_type  = "customer",
                            reading_date  = datetime.combine(
                                bill_date,
                                datetime.min.time()
                            ).replace(tzinfo=timezone.utc),
                            start_reading = prev_reading,
                            end_reading   = curr_reading,
                            volume        = consumption
                        ))
                        cust_obj = session.query(
                            Customer
                        ).filter_by(id=customer.id).first()
                        if cust_obj:
                            cust_obj.last_reading = \
                                curr_reading
                            cust_obj.last_reading_date = \
                                datetime.now(timezone.utc)
                        session.commit()
                        session.close()

                        # Send SMS
                        if customer.phone:
                            try:
                                import africastalking
                                at_user = st.secrets.get(
                                    "AT_USERNAME", ""
                                )
                                at_key = st.secrets.get(
                                    "AT_API_KEY", ""
                                )
                                sender = st.secrets.get(
                                    "AT_SENDER_ID",
                                    "Maji360"
                                )
                                if at_user and at_key:
                                    africastalking.initialize(
                                        at_user, at_key
                                    )
                                    sms = africastalking.SMS
                                    msg = (
                                        f"Maji360 | "
                                        f"{system_name}\n"
                                        f"Dear Caretaker,\n"
                                        f"Acc: "
                                        f"{customer.account_no}"
                                        f"\nBill: {bill_month}"
                                        f"\nUnits: "
                                        f"{consumption:.1f} m³"
                                        f"\nAmount: {currency}"
                                        f" {bill_amount:,.0f}"
                                        f"\nPay promptly."
                                        f" Thank you."
                                    )
                                    sms.send(
                                        msg,
                                        [customer.phone],
                                        sender_id=sender
                                    )
                            except Exception:
                                pass

                        st.success(
                            f"✓ Bill generated — "
                            f"{customer.name} "
                            f"{currency} "
                            f"{bill_amount:,.0f}"
                        )
                        st.rerun()

    # ── Tab 2: Record payment ──────────────────────────
    with tab2:
        st.markdown("### Record payment")

        cust_options2 = {
            f"{c.account_no} — {c.name}": c
            for c in customers
        }
        selected_name2 = st.selectbox(
            "Select customer *",
            options=list(cust_options2.keys()),
            key="pay_customer"
        )
        customer2 = cust_options2[selected_name2]

        session   = get_session()
        all_bills = session.query(Bill).filter_by(
            customer_id=customer2.id
        ).all()
        session.close()

        total_billed = sum(
            b.amount or 0 for b in all_bills
        )
        total_paid   = sum(
            b.amount_paid or 0 for b in all_bills
        )
        outstanding  = total_billed - total_paid

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric(
                "Total billed",
                f"{currency} {total_billed:,.0f}"
            )
        with col2:
            st.metric(
                "Total paid",
                f"{currency} {total_paid:,.0f}"
            )
        with col3:
            st.metric(
                "Outstanding",
                f"{currency} {outstanding:,.0f}"
            )

        if outstanding <= 0:
            st.success(
                "✓ No outstanding balance."
            )
        else:
            with st.form("payment_form"):
                col1, col2 = st.columns(2)
                with col1:
                    pay_amount = st.number_input(
                        f"Amount paid ({currency}) *",
                        min_value=0.0,
                        max_value=float(outstanding),
                        value=float(outstanding),
                        step=500.0,
                        format="%.0f"
                    )
                with col2:
                    pay_method = st.selectbox(
                        "Payment method *",
                        ["Cash", "MTN Mobile Money",
                         "Airtel Money",
                         "Bank transfer", "Other"]
                    )

                pay_ref   = st.text_input(
                    "Reference / receipt number"
                )
                pay_notes = st.text_input(
                    "Notes (optional)"
                )
                pay_date  = st.date_input(
                    "Payment date *",
                    value=datetime.now().date()
                )

                pay_submit = st.form_submit_button(
                    "✓ Record payment",
                    use_container_width=True,
                    type="primary"
                )

                if pay_submit and pay_amount > 0:
                    session = get_session()
                    unpaid  = session.query(Bill).filter(
                        Bill.customer_id == customer2.id,
                        Bill.is_paid     == False
                    ).order_by(Bill.bill_month).all()

                    remaining = pay_amount
                    for bill in unpaid:
                        if remaining <= 0:
                            break
                        owed = (bill.amount or 0) - \
                               (bill.amount_paid or 0)
                        if owed <= 0:
                            continue
                        if remaining >= owed:
                            bill.amount_paid = bill.amount
                            bill.is_paid     = True
                            remaining       -= owed
                        else:
                            bill.amount_paid = \
                                (bill.amount_paid or 0) + \
                                remaining
                            remaining = 0

                    current_user = st.session_state.get(
                        "user", {}
                    )
                    session.add(Payment(
                        system_id      = system_id,
                        customer_id    = customer2.id,
                        amount         = pay_amount,
                        payment_method = pay_method,
                        reference      = pay_ref or None,
                        notes          = pay_notes or None,
                        recorded_by    = current_user.get(
                            "id"
                        ),
                        paid_at        = datetime.combine(
                            pay_date,
                            datetime.min.time()
                        ).replace(tzinfo=timezone.utc)
                    ))
                    session.commit()
                    session.close()

                    # SMS confirmation
                    if customer2.phone:
                        try:
                            import africastalking
                            at_user = st.secrets.get(
                                "AT_USERNAME", ""
                            )
                            at_key = st.secrets.get(
                                "AT_API_KEY", ""
                            )
                            sender = st.secrets.get(
                                "AT_SENDER_ID", "Maji360"
                            )
                            if at_user and at_key:
                                africastalking.initialize(
                                    at_user, at_key
                                )
                                sms = africastalking.SMS
                                new_bal = max(
                                    0,
                                    outstanding - pay_amount
                                )
                                msg = (
                                    f"Maji360 | "
                                    f"{system_name}\n"
                                    f"Payment received: "
                                    f"{currency} "
                                    f"{pay_amount:,.0f}\n"
                                    f"Acc: "
                                    f"{customer2.account_no}"
                                    f"\nBalance: {currency}"
                                    f" {new_bal:,.0f}"
                                    f"\nThank you."
                                )
                                sms.send(
                                    msg,
                                    [customer2.phone],
                                    sender_id=sender
                                )
                        except Exception:
                            pass

                    st.success(
                        f"✓ Payment of {currency} "
                        f"{pay_amount:,.0f} recorded."
                    )
                    st.rerun()

    # ── Tab 3: Customer balances ───────────────────────
    with tab3:
        st.markdown("### All customer balances")

        session = get_session()
        rows    = []
        for c in customers:
            c_bills  = session.query(Bill).filter_by(
                customer_id=c.id
            ).all()
            billed   = sum(b.amount or 0 for b in c_bills)
            paid     = sum(
                b.amount_paid or 0 for b in c_bills
            )
            owed     = billed - paid
            rate     = round(
                (paid / billed) * 100, 0
            ) if billed > 0 else 0
            conn     = getattr(
                c, 'connection_type', 'PSP'
            ) or 'PSP'
            rows.append({
                "Account":     c.account_no,
                "Customer":    c.name,
                "Type":        conn,
                "Billed":      f"{currency} {billed:,.0f}",
                "Paid":        f"{currency} {paid:,.0f}",
                "Outstanding": f"{currency} {owed:,.0f}",
                "Rate":        f"{rate:.0f}%",
                "Phone":       c.phone or "—"
            })
        session.close()

        if rows:
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No billing data yet.")
