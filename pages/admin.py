import streamlit as st
import pandas as pd
from core.database import (
    get_session, WaterSystem, User,
    Customer, Bill, DailyReading
)
from core.auth import (
    require_login, is_super_admin, hash_password
)
from sqlalchemy import func, text as sql_text


def show():
    require_login()

    if not is_super_admin():
        st.error("Access denied. Super admin only.")
        return

    st.markdown("## 🔧 Admin Panel")
    st.divider()

    tab1, tab2, tab3 = st.tabs([
        "📊 Platform overview",
        "💧 Water systems",
        "👥 Users"
    ])

    # ── Tab 1: Platform overview ───────────────────────
    with tab1:
        session         = get_session()
        systems         = session.query(WaterSystem).filter_by(
            is_active=True
        ).all()
        total_customers = session.query(Customer).filter_by(
            is_active=True
        ).count()
        total_billed    = session.query(
            func.sum(Bill.amount)
        ).scalar() or 0
        total_paid      = session.query(
            func.sum(Bill.amount_paid)
        ).scalar() or 0
        session.close()

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Water systems", len(systems))
        with c2:
            st.metric("Total customers", total_customers)
        with c3:
            st.metric(
                "Total billed",
                f"UGX {total_billed:,.0f}"
            )
        with c4:
            rate = round(
                (total_paid / total_billed) * 100, 1
            ) if total_billed > 0 else 0
            st.metric("Collection rate", f"{rate}%")

        st.divider()
        st.markdown("### All water systems")

        rows = []
        session = get_session()
        for s in systems:
            c_count = session.query(Customer).filter_by(
                system_id=s.id, is_active=True
            ).count()
            r_count = session.query(DailyReading).filter_by(
                system_id=s.id
            ).count()
            billed  = session.query(
                func.sum(Bill.amount)
            ).filter_by(system_id=s.id).scalar() or 0
            paid    = session.query(
                func.sum(Bill.amount_paid)
            ).filter_by(system_id=s.id).scalar() or 0
            rate    = round(
                (paid / billed) * 100, 0
            ) if billed > 0 else 0
            rows.append({
                "System":    s.name,
                "Country":   s.country,
                "Currency":  s.currency,
                "Customers": c_count,
                "Readings":  r_count,
                "Billed":    f"{s.currency} {billed:,.0f}",
                "Rate":      f"{rate:.0f}%"
            })
        session.close()

        if rows:
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True
            )

    # ── Tab 2: Water systems ───────────────────────────
    with tab2:
        st.markdown("### Register new water system")
        with st.form("new_system_form"):
            col1, col2 = st.columns(2)
            with col1:
                s_name     = st.text_input("System name *")
                s_district = st.text_input("District")
                s_country  = st.selectbox(
                    "Country",
                    ["Uganda", "Kenya", "Tanzania",
                     "Malawi", "Zambia", "Ghana",
                     "Nigeria", "Rwanda", "Ethiopia"]
                )
                s_currency = st.selectbox(
                    "Currency",
                    ["UGX", "KES", "TZS", "MWK",
                     "ZMW", "GHS", "NGN", "RWF", "ETB"]
                )
            with col2:
                s_tariff   = st.number_input(
                    "Tariff per m³",
                    min_value=0.0, value=2500.0
                )
                s_form_id  = st.text_input(
                    "mWater form ID"
                )
                s_uses_mwater = st.checkbox(
                    "This system uses mWater",
                    value=True
                )
                s_lat = st.number_input(
                    "Latitude", value=0.0,
                    format="%.6f"
                )
                s_lon = st.number_input(
                    "Longitude", value=0.0,
                    format="%.6f"
                )

            if st.form_submit_button(
                "Register system",
                use_container_width=True
            ) and s_name:
                session = get_session()
                session.add(WaterSystem(
                    name           = s_name,
                    district       = s_district,
                    country        = s_country,
                    currency       = s_currency,
                    tariff_per_m3  = s_tariff,
                    mwater_form_id = s_form_id,
                    latitude       = s_lat or None,
                    longitude      = s_lon or None
                ))
                session.commit()
                session.close()
                st.success(f"✓ {s_name} registered.")
                st.rerun()

    # ── Tab 3: Users ───────────────────────────────────
    with tab3:

        # ── Pending approvals ──────────────────────────
        session = get_session()
        try:
            pending = session.execute(sql_text(
                "SELECT id, name, email, system_id "
                "FROM users "
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
                u_role  = st.selectbox(
                    "Role",
                    ["viewer", "operator",
                     "system_admin", "super_admin"]
                )
                u_pass  = st.text_input(
                    "Password *", type="password"
                )
                u_pass2 = st.text_input(
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

        # ── All users with remove button ───────────────
        st.markdown("### All users")
        session      = get_session()
        users        = session.query(User).filter_by(
            is_active=True
        ).all()
        current_user = st.session_state.get("user", {})
        session.close()

        if users:
            for u in users:
                col1, col2, col3, col4 = st.columns(
                    [3, 2, 2, 1]
                )
                with col1:
                    approved = getattr(u, 'is_approved', True)
                    badge    = "" if approved else " ⏳"
                    st.markdown(
                        f"**{u.name}**{badge}  \n"
                        f"<span style='font-size:12px;"
                        f"color:#64748b'>{u.email}</span>",
                        unsafe_allow_html=True
                    )
                with col2:
                    st.markdown(
                        f"<span style='font-size:13px'>"
                        f"{u.role.replace('_',' ').title()}"
                        f"</span>",
                        unsafe_allow_html=True
                    )
                with col3:
                    session  = get_session()
                    sys_name = "All systems"
                    if u.system_id:
                        sys_obj = session.query(
                            WaterSystem
                        ).filter_by(id=u.system_id).first()
                        if sys_obj:
                            sys_name = sys_obj.name
                    session.close()
                    st.markdown(
                        f"<span style='font-size:13px'>"
                        f"{sys_name}</span>",
                        unsafe_allow_html=True
                    )
                with col4:
                    if u.email != current_user.get("email"):
                        if st.button(
                            "Remove",
                            key=f"remove_{u.id}",
                            type="secondary"
                        ):
                            session = get_session()
                            target  = session.query(
                                User
                            ).filter_by(id=u.id).first()
                            if target:
                                target.is_active = False
                                session.commit()
                            session.close()
                            st.success(
                                f"✓ {u.name} access removed."
                            )
                            st.rerun()
                    else:
                        st.markdown(
                            "<span style='font-size:11px;"
                            "color:#94a3b8'>You</span>",
                            unsafe_allow_html=True
                        )
