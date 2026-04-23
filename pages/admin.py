import streamlit as st
import pandas as pd
from core.database import (
    get_session, WaterSystem, User,
    Customer, Bill, DailyReading, Asset
)
from core.auth import (
    require_login, is_super_admin,
    is_system_admin, hash_password
)
from sqlalchemy import func, text as sql_text


def show():
    require_login()

    if not is_super_admin():
        st.error("Access denied. Super admin only.")
        return

    st.markdown("## 🔧 Admin Panel")
    st.divider()

    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Platform overview",
        "💧 Water systems",
        "👥 Users",
        "🏗️ Assets"
    ])

    # ── Tab 1: Platform overview ───────────────────────
    with tab1:
        session         = get_session()
        systems         = session.query(
            WaterSystem
        ).filter_by(is_active=True).all()
        total_customers = session.query(
            Customer
        ).filter_by(is_active=True).count()
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
            st.metric("Total customers",
                      total_customers)
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

        session = get_session()
        rows    = []
        for s in systems:
            c_count = session.query(Customer).filter_by(
                system_id=s.id, is_active=True
            ).count()
            r_count = session.query(
                DailyReading
            ).filter_by(system_id=s.id).count()
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
                "mWater":    "✓" if getattr(
                    s, 'uses_mwater', True
                ) else "✗",
                "Customers": c_count,
                "Readings":  r_count,
                "Billed":    f"{s.currency} "
                             f"{billed:,.0f}",
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
                s_name     = st.text_input(
                    "System name *"
                )
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
                     "ZMW", "GHS", "NGN", "RWF",
                     "ETB"]
                )
            with col2:
                s_tariff      = st.number_input(
                    "Tariff per m³",
                    min_value=0.0, value=2500.0
                )
                s_form_id     = st.text_input(
                    "mWater form ID"
                )
                s_uses_mwater = st.checkbox(
                    "This system uses mWater",
                    value=True
                )
                s_lat = st.number_input(
                    "Latitude",
                    value=0.0, format="%.6f"
                )
                s_lon = st.number_input(
                    "Longitude",
                    value=0.0, format="%.6f"
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
                    tariff_psp     = s_tariff,
                    tariff_private = s_tariff + 500,
                    mwater_form_id = s_form_id,
                    uses_mwater    = s_uses_mwater,
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
            st.markdown(
                "### ⏳ Pending approval requests"
            )
            st.markdown(
                f"**{len(pending)} request(s) "
                f"waiting for approval**"
            )
            for p in pending:
                col1, col2, col3 = st.columns(
                    [3, 2, 1]
                )
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
                        st.success(
                            f"✓ {p[1]} approved."
                        )
                        st.rerun()
            st.divider()
        else:
            st.success(
                "✓ No pending approval requests."
            )
            st.divider()

        session.close()

        # ── Create new user ────────────────────────────
        st.markdown("### Create new user")
        session = get_session()
        systems = session.query(WaterSystem).filter_by(
            is_active=True
        ).all()
        system_options = {
            "All systems (super admin)": None
        }
        for s in systems:
            system_options[s.name] = s.id
        session.close()

        with st.form("new_user_form"):
            col1, col2 = st.columns(2)
            with col1:
                u_name   = st.text_input(
                    "Full name *"
                )
                u_email  = st.text_input("Email *")
                u_system = st.selectbox(
                    "Primary system",
                    options=list(
                        system_options.keys()
                    )
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
                    "Confirm password *",
                    type="password"
                )

            if st.form_submit_button(
                "Create user",
                use_container_width=True
            ):
                if not u_name or not u_email \
                   or not u_pass:
                    st.error(
                        "Please fill in all fields."
                    )
                elif u_pass != u_pass2:
                    st.error("Passwords do not match.")
                else:
                    session  = get_session()
                    existing = session.query(
                        User
                    ).filter_by(email=u_email).first()
                    if existing:
                        st.error(
                            "Email already exists."
                        )
                        session.close()
                    else:
                        sys_id = system_options[
                            u_system
                        ]
                        new_user = User(
                            name        = u_name,
                            email       = u_email,
                            role        = u_role,
                            password    = hash_password(
                                u_pass
                            ),
                            system_id   = sys_id,
                            is_approved = True
                        )
                        session.add(new_user)
                        session.commit()

                        # Add to user_systems
                        if sys_id:
                            try:
                                session.execute(
                                    sql_text("""
                                    INSERT INTO
                                    user_systems
                                    (user_id, system_id)
                                    VALUES (:uid, :sid)
                                    ON CONFLICT
                                    DO NOTHING
                                """), {
                                    "uid": new_user.id,
                                    "sid": sys_id
                                })
                                session.commit()
                            except Exception:
                                pass

                        session.close()
                        st.success(
                            f"✓ {u_name} created."
                        )
                        st.rerun()

        st.divider()

        # ── All users with system access control ───────
        st.markdown("### All users")
        session      = get_session()
        users        = session.query(User).filter_by(
            is_active=True
        ).all()
        all_systems  = session.query(
            WaterSystem
        ).filter_by(is_active=True).all()
        current_user = st.session_state.get(
            "user", {}
        )

        for u in users:
            with st.expander(
                f"**{u.name}** — "
                f"{u.role.replace('_', ' ').title()} "
                f"· {u.email}"
            ):
                # Current system access
                try:
                    access_rows = session.execute(
                        sql_text("""
                        SELECT ws.id, ws.name
                        FROM user_systems us
                        JOIN water_systems ws
                            ON us.system_id = ws.id
                        WHERE us.user_id = :uid
                        ORDER BY ws.name
                    """), {"uid": u.id}
                    ).fetchall()
                    current_access = [
                        {"id": r[0], "name": r[1]}
                        for r in access_rows
                    ]
                except Exception:
                    current_access = []

                st.markdown(
                    "**Current system access:**"
                )
                if current_access:
                    for acc in current_access:
                        col1, col2 = st.columns([4, 1])
                        with col1:
                            st.markdown(
                                f"• {acc['name']}"
                            )
                        with col2:
                            if u.email != \
                               current_user.get(
                                   "email"
                               ):
                                if st.button(
                                    "Remove",
                                    key=f"rm_{u.id}_{acc['id']}",
                                    type="secondary"
                                ):
                                    session.execute(
                                        sql_text("""
                                        DELETE FROM
                                        user_systems
                                        WHERE
                                        user_id=:uid
                                        AND
                                        system_id=:sid
                                    """), {
                                        "uid": u.id,
                                        "sid": acc["id"]
                                    })
                                    session.commit()
                                    st.success(
                                        "✓ Access removed"
                                    )
                                    st.rerun()
                else:
                    st.markdown(
                        "*No system access assigned*"
                    )

                # Add system access
                st.markdown("**Grant access to:**")
                accessible_ids = {
                    a["id"] for a in current_access
                }
                available = [
                    s for s in all_systems
                    if s.id not in accessible_ids
                ]
                if available:
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        add_sys = st.selectbox(
                            "Select system",
                            options=[
                                s.name
                                for s in available
                            ],
                            key=f"add_sys_{u.id}",
                            label_visibility="collapsed"
                        )
                    with col2:
                        if st.button(
                            "Grant",
                            key=f"grant_{u.id}",
                            type="primary"
                        ):
                            sys_obj = next(
                                (s for s in available
                                 if s.name == add_sys),
                                None
                            )
                            if sys_obj:
                                session.execute(
                                    sql_text("""
                                    INSERT INTO
                                    user_systems
                                    (user_id, system_id)
                                    VALUES (:uid, :sid)
                                    ON CONFLICT
                                    DO NOTHING
                                """), {
                                    "uid": u.id,
                                    "sid": sys_obj.id
                                })
                                session.commit()
                                st.success(
                                    f"✓ Access granted "
                                    f"to {add_sys}"
                                )
                                st.rerun()
                else:
                    st.markdown(
                        "*Has access to all systems*"
                    )

                st.divider()

                # Remove user
                if u.email != current_user.get("email"):
                    if st.button(
                        f"🗑️ Remove {u.name} "
                        f"from platform",
                        key=f"remove_{u.id}",
                        type="secondary"
                    ):
                        target = session.query(
                            User
                        ).filter_by(id=u.id).first()
                        if target:
                            target.is_active = False
                            session.commit()
                        st.success(
                            f"✓ {u.name} removed."
                        )
                        st.rerun()

        session.close()

    # ── Tab 4: Assets ──────────────────────────────────
    with tab4:
        st.markdown("### Edit assets")
        st.caption(
            "Super admin and system admins can edit "
            "asset details or deactivate assets "
            "entered in error."
        )

        session     = get_session()
        all_systems = session.query(
            WaterSystem
        ).filter_by(is_active=True).all()
        session.close()

        sys_select = st.selectbox(
            "Select water system",
            options=[s.name for s in all_systems],
            key="asset_edit_system"
        )

        selected_sys = next(
            (s for s in all_systems
             if s.name == sys_select), None
        )

        if selected_sys:
            session = get_session()
            assets  = session.query(Asset).filter_by(
                system_id=selected_sys.id
            ).order_by(Asset.name).all()
            session.close()

            if not assets:
                st.info(
                    "No assets registered for "
                    "this system."
                )
            else:
                st.markdown(
                    f"**{len(assets)} assets** "
                    f"for {selected_sys.name}"
                )

                for asset in assets:
                    status_icon = "✓" \
                        if asset.is_active else "✗"
                    with st.expander(
                        f"{status_icon} {asset.name} "
                        f"— {asset.asset_type}"
                    ):
                        with st.form(
                            f"edit_asset_{asset.id}"
                        ):
                            col1, col2 = st.columns(2)
                            with col1:
                                new_name = st.text_input(
                                    "Name *",
                                    value=asset.name
                                )
                                new_type = st.selectbox(
                                    "Type *",
                                    options=[
                                        "borehole",
                                        "pump",
                                        "pump_house",
                                        "power_supply",
                                        "generator",
                                        "pipeline",
                                        "pipe",
                                        "tank",
                                        "treatment",
                                        "meter",
                                        "valve",
                                        "civil",
                                        "other"
                                    ],
                                    index=[
                                        "borehole",
                                        "pump",
                                        "pump_house",
                                        "power_supply",
                                        "generator",
                                        "pipeline",
                                        "pipe",
                                        "tank",
                                        "treatment",
                                        "meter",
                                        "valve",
                                        "civil",
                                        "other"
                                    ].index(
                                        asset.asset_type
                                    ) if asset.asset_type
                                    in [
                                        "borehole",
                                        "pump",
                                        "pump_house",
                                        "power_supply",
                                        "generator",
                                        "pipeline",
                                        "pipe",
                                        "tank",
                                        "treatment",
                                        "meter",
                                        "valve",
                                        "civil",
                                        "other"
                                    ] else 12
                                )
                                new_active = st.checkbox(
                                    "Active",
                                    value=asset.is_active
                                )
                            with col2:
                                new_lat = st.number_input(
                                    "Latitude",
                                    value=float(
                                        asset.latitude
                                        or 0.0
                                    ),
                                    format="%.6f",
                                    key=f"lat_{asset.id}"
                                )
                                new_lon = st.number_input(
                                    "Longitude",
                                    value=float(
                                        asset.longitude
                                        or 0.0
                                    ),
                                    format="%.6f",
                                    key=f"lon_{asset.id}"
                                )
                                # Tank dimensions
                                if new_type == "tank":
                                    new_height = \
                                        st.number_input(
                                        "Height (m)",
                                        value=float(
                                            asset.height_m
                                            or 0.0
                                        ),
                                        format="%.1f",
                                        key=f"h_{asset.id}"
                                    )
                                    new_length = \
                                        st.number_input(
                                        "Length (m)",
                                        value=float(
                                            asset.length_m
                                            or 0.0
                                        ),
                                        format="%.1f",
                                        key=f"l_{asset.id}"
                                    )
                                    new_width = \
                                        st.number_input(
                                        "Width (m)",
                                        value=float(
                                            asset.width_m
                                            or 0.0
                                        ),
                                        format="%.1f",
                                        key=f"w_{asset.id}"
                                    )
                                else:
                                    new_height = \
                                        asset.height_m
                                    new_length = \
                                        asset.length_m
                                    new_width  = \
                                        asset.width_m

                            save = st.form_submit_button(
                                "✓ Save changes",
                                use_container_width=True,
                                type="primary"
                            )

                            if save:
                                session = get_session()
                                a = session.query(
                                    Asset
                                ).filter_by(
                                    id=asset.id
                                ).first()
                                if a:
                                    a.name       = new_name
                                    a.asset_type = new_type
                                    a.is_active  = new_active
                                    a.latitude   = new_lat \
                                        or None
                                    a.longitude  = new_lon \
                                        or None
                                    if new_type == "tank":
                                        a.height_m = \
                                            new_height
                                        a.length_m = \
                                            new_length
                                        a.width_m  = \
                                            new_width
                                        if new_length \
                                           and new_width \
                                           and new_height:
                                            a.capacity_m3 = \
                                                round(
                                                new_length *
                                                new_width *
                                                new_height,
                                                1
                                            )
                                    session.commit()
                                session.close()
                                st.success(
                                    f"✓ {new_name} updated"
                                )
                                st.rerun()
