import streamlit as st
import pandas as pd
from sqlalchemy import text as sql_text
from core.database import get_session, Bill, Customer, Payment
from core.sync import reallocate_payments
from core.auth import require_login


def show():
    require_login()

    system_id   = st.session_state.get("selected_system_id")
    system_name = st.session_state.get("selected_system_name", "")
    currency    = st.session_state.get("currency", "UGX")

    if not system_id:
        st.warning("Please select a water system.")
        return

    st.markdown("## 🩺 Data Quality")
    st.markdown(
        f"<span style='color:#64748b;font-size:13px'>"
        f"{system_name} · Review records flagged by sync</span>",
        unsafe_allow_html=True
    )
    st.divider()

    st.caption(
        "When the operator corrects or deletes an entry in mWater "
        "after it has already been synced into Maji360, the sync "
        "can't tell the difference between 'mWater is down' and "
        "'this was deleted on purpose' — so it never deletes "
        "anything automatically. Instead, records whose source "
        "transaction has disappeared from mWater are flagged here "
        "for you to review and confirm."
    )

    session = get_session()

    orphaned_bills = session.query(Bill).filter_by(
        system_id=system_id, is_orphaned=True
    ).order_by(Bill.bill_month).all()

    try:
        orphaned_payment_rows = session.execute(sql_text(
            "SELECT p.id, p.customer_id, p.amount, p.paid_at, "
            "p.payment_method, p.notes, p.transaction_id, "
            "c.account_no, c.name "
            "FROM payments p "
            "JOIN customers c ON c.id = p.customer_id "
            "WHERE p.system_id = :sid AND p.is_orphaned = true "
            "ORDER BY p.paid_at"
        ), {"sid": system_id}).fetchall()
    except Exception:
        orphaned_payment_rows = []

    cust_map = {
        c.id: c for c in session.query(Customer).filter_by(
            system_id=system_id
        ).all()
    }

    # Summary 
    total_flagged = len(orphaned_bills) + len(orphaned_payment_rows)
    if total_flagged == 0:
        session.close()
        st.success(
            "✓ Nothing flagged. All synced bills and payments "
            "still have a matching transaction in mWater."
        )
        return

    st.warning(
        f"⚠ {total_flagged} record(s) flagged — their source "
        f"transaction in mWater could no longer be found on the "
        f"most recent sync."
    )
    st.divider()

    # Orphaned bills 
    if orphaned_bills:
        st.markdown(f"### 🧾 Bills ({len(orphaned_bills)})")

        for b in orphaned_bills:
            cust = cust_map.get(b.customer_id)
            col1, col2, col3 = st.columns([4, 2, 2])
            with col1:
                st.markdown(
                    f"**{cust.account_no if cust else '—'} — "
                    f"{cust.name if cust else '—'}**  \n"
                    f"<span style='color:#64748b;font-size:13px'>"
                    f"Bill month: {b.bill_month} · "
                    f"{b.units_m3:.1f} m³ · "
                    f"{currency} {b.amount:,.0f} "
                    f"(paid: {currency} {b.amount_paid:,.0f})"
                    f"</span>",
                    unsafe_allow_html=True
                )
            with col2:
                if st.button(
                    "🗑 Confirm deleted",
                    key=f"del_bill_{b.id}",
                    help="Permanently remove this bill — confirms "
                         "it was a mistaken entry that was deleted "
                         "in mWater. Payment allocation will be "
                         "recalculated for this customer."
                ):
                    cust_id = b.customer_id
                    session.delete(b)
                    session.commit()
                    reallocate_payments(system_id, session, commit=True)
                    st.success(
                        f"Deleted bill {b.bill_month} for "
                        f"{cust.name if cust else 'customer'}. "
                        f"Allocation recalculated."
                    )
                    st.rerun()
            with col3:
                if st.button(
                    "✓ Keep — not deleted",
                    key=f"keep_bill_{b.id}",
                    help="This bill is correct. Stop tracking it "
                         "against mWater (it will be treated like "
                         "a manually entered bill and won't be "
                         "flagged again)."
                ):
                    b.mwater_id   = None
                    b.is_orphaned = False
                    session.commit()
                    st.success(
                        f"Kept bill {b.bill_month} — no longer "
                        f"tracked against mWater."
                    )
                    st.rerun()
            st.divider()

    # Orphaned payments 
    if orphaned_payment_rows:
        st.markdown(f"### 💳 Payments ({len(orphaned_payment_rows)})")

        for row in orphaned_payment_rows:
            (pay_id, cust_id, amount, paid_at, method,
             notes, txn_id, acc_no, cust_name) = row

            date_str = paid_at.strftime("%d %b %Y") \
                if hasattr(paid_at, "strftime") else str(paid_at)[:10]

            col1, col2, col3 = st.columns([4, 2, 2])
            with col1:
                st.markdown(
                    f"**{acc_no} — {cust_name}**  \n"
                    f"<span style='color:#64748b;font-size:13px'>"
                    f"{date_str} · {currency} {amount:,.0f} · "
                    f"{method or 'Cash'}"
                    + (f" · {notes}" if notes else "")
                    + f"</span>",
                    unsafe_allow_html=True
                )
            with col2:
                if st.button(
                    "🗑 Confirm deleted",
                    key=f"del_pay_{pay_id}",
                    help="Permanently remove this payment — confirms "
                         "it was a mistaken entry that was deleted "
                         "in mWater. Payment allocation will be "
                         "recalculated for this customer."
                ):
                    session.execute(sql_text(
                        "DELETE FROM payments WHERE id = :id"
                    ), {"id": pay_id})
                    session.commit()
                    reallocate_payments(system_id, session, commit=True)
                    st.success(
                        f"Deleted payment of {currency} "
                        f"{amount:,.0f} for {cust_name}. "
                        f"Allocation recalculated."
                    )
                    st.rerun()
            with col3:
                if st.button(
                    "✓ Keep — not deleted",
                    key=f"keep_pay_{pay_id}",
                    help="This payment is correct. Stop tracking it "
                         "against mWater (it will be treated like a "
                         "manually entered payment and won't be "
                         "flagged again)."
                ):
                    session.execute(sql_text(
                        "UPDATE payments SET transaction_id = NULL, "
                        "is_orphaned = false WHERE id = :id"
                    ), {"id": pay_id})
                    session.commit()
                    st.success(
                        f"Kept payment of {currency} {amount:,.0f} — "
                        f"no longer tracked against mWater."
                    )
                    st.rerun()
            st.divider()

    session.close()
