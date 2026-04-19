import streamlit as st
import pandas as pd
from core.database import get_session, WaterSystem, User, Customer, Bill, DailyReading
from core.auth import require_login, is_super_admin, hash_password
from sqlalchemy import func

def show():
    require_login()
    if not is_super_admin():
        st.error("Access denied. Super admin only.")
        return
    st.markdown("## 🔧 Admin Panel")
    st.divider()
    tab1, tab2, tab3 = st.tabs(["📊 Platform overview", "💧 Water systems", "👥 Users"])
    with tab1:
        session = get_session()
        systems = session.query(WaterSystem).filter_by(is_active=True).all()
        total_customers = session.query(Customer).filter_by(is_active=True).count()
        total_billed    = session.query(func.sum(Bill.amount)).scalar() or 0
        total_paid      = session.query(func.sum(Bill.amount_paid)).scalar() or 0
        session.close()
        c1,c2,c3,c4 = st.columns(4)
        with c1: st.metric("Water systems", len(systems))
        with c2: st.metric("Total customers", total_customers)
        with c3: st.metric("Total billed", f"UGX {total_billed:,.0f}")
        with c4: st.metric("Collection rate", f"{round((total_paid/total_billed)*100,1) if total_billed>0 else 0}%")
    with tab2:
        st.markdown("### Register new water system")
        with st.form("new_system_form"):
            col1,col2 = st.columns(2)
            with col1:
                s_name    = st.text_input("System name *")
                s_district= st.text_input("District")
                s_country = st.selectbox("Country", ["Uganda","Kenya","Tanzania","Malawi","Zambia","Ghana","Nigeria","Rwanda","Ethiopia"])
                s_currency= st.selectbox("Currency", ["UGX","KES","TZS","MWK","ZMW","GHS","NGN","RWF","ETB"])
            with col2:
                s_tariff  = st.number_input("Tariff per m³", min_value=0.0, value=2500.0)
                s_form_id = st.text_input("mWater form ID")
                s_lat     = st.number_input("Latitude",  value=0.0, format="%.6f")
                s_lon     = st.number_input("Longitude", value=0.0, format="%.6f")
            if st.form_submit_button("Register system", use_container_width=True) and s_name:
                session = get_session()
                session.add(WaterSystem(name=s_name, district=s_district, country=s_country, currency=s_currency, tariff_per_m3=s_tariff, mwater_form_id=s_form_id, latitude=s_lat or None, longitude=s_lon or None))
                session.commit(); session.close()
                st.success(f"✓ {s_name} registered."); st.rerun()
    with tab3:
        # ── Pending approvals ──────────────────────────
        session = get_session()
        try:
            from sqlalchemy import text as sql_text
            pending = session.execute(sql_text(
                "SELECT id, name, email, system_id, "
                "requested_at FROM users "
                "WHERE is_approved = false "
                "AND is_active = true "
                "ORDER BY requested_at DESC"
            )).fetchall()
        except Exception:
            pending = []

        if pending:
            st.markdown("### ⏳ Pending approval requests")
            st.markdown(
                f"**{len(pending)} request(s) "
                f"waiting for approval**"
            )
            for p in pending:
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    st.markdown(
                        f"**{p[1]}**  \n"
                        f"<span style='font-size:12px;"
                        f"color:#64748b'>{p[2]}</span>",
                        unsafe_allow_html=True
                    )
                with col2:
                    sys_name = "Unknown"
                    if p[3]:
                        sys_obj = session.query(
                            WaterSystem
                        ).filter_by(id=p[3]).first()
                        if sys_obj:
                            sys_name = sys_obj.name
                    st.markdown(
                        f"<span style='font-size:13px'>"
                        f"{sys_name}</span>",
                        unsafe_allow_html=True
                    )
                with col3:
                    if st.button(
                        "✓ Approve",
                        key=f"approve_{p[0]}",
                        type="primary"
                    ):
                        session.execute(sql_text(
                            "UPDATE users SET "
                            "is_approved = true "
                            "WHERE id = :uid"
                        ), {"uid": p[0]})
                        session.commit()
                        st.success(f"✓ {p[1]} approved.")
                        st.rerun()
            st.divider()
        else:
            st.success("✓ No pending approval requests.")
            st.divider()

        session.close()

        # ── Create new user ────────────────────────────
        st.markdown("### Create new user")
        session = get_session()
        systems = session.query(WaterSystem).filter_by(
            is_active=True
        ).all()
        system_options = {"All systems (super admin)": None}
        for s in systems:
            system_options[s.name] = s.id
        session.close()

        with st.form("new_user_form"):
            col1, col2 = st.columns(2)
            with col1:
                u_name   = st.text_input("Full name *")
                u_email  = st.text_input("Email *")
                u_system = st.selectbox(
                    "Assigned system",
                    options=list(system_options.keys())
                )
            with col2:
                u_role   = st.selectbox(
                    "Role",
                    ["viewer", "operator",
                     "system_admin", "super_admin"]
                )
                u_pass   = st.text_input(
                    "Password *", type="password"
                )
                u_pass2  = st.text_input(
                    "Confirm password *", type="password"
                )

            if st.form_submit_button(
                "Create user", use_container_width=True
            ):
                if not u_name or not u_email or not u_pass:
                    st.error("Please fill in all fields.")
                elif u_pass != u_pass2:
                    st.error("Passwords do not match.")
                else:
                    session  = get_session()
                    existing = session.query(User).filter_by(
                        email=u_email
                    ).first()
                    if existing:
                        st.error("Email already exists.")
                    else:
                        session.add(User(
                            name        = u_name,
                            email       = u_email,
                            role        = u_role,
                            password    = hash_password(u_pass),
                            system_id   = system_options[u_system],
                            is_approved = True
                        ))
                        session.commit()
                        session.close()
                        st.success(
                            f"✓ {u_name} created successfully."
                        )
                        st.rerun()

        st.divider()

        # ── All users ──────────────────────────────────
        st.markdown("### All users")
        session = get_session()
        users   = session.query(User).filter_by(
            is_active=True
        ).all()
        rows = [{
            "Name":     u.name,
            "Email":    u.email,
            "Role":     u.role.replace("_", " ").title(),
            "System":   u.system.name
                        if u.system else "All systems",
            "Approved": "✓" if getattr(
                u, 'is_approved', True
            ) else "⏳ Pending"
        } for u in users]
        session.close()

        if rows:
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True
            )
