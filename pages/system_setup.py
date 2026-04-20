import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from core.database import (
    get_session, WaterSystem, Asset, Customer
)
from core.auth import require_login, is_operator


def show():
    require_login()

    system_id   = st.session_state.get("selected_system_id")
    system_name = st.session_state.get(
        "selected_system_name", ""
    )

    if not system_id:
        st.warning("Please select a water system.")
        return

    session     = get_session()
    system      = session.query(WaterSystem).filter_by(
        id=system_id
    ).first()
    uses_mwater = getattr(system, 'uses_mwater', True)
    currency    = system.currency or "UGX"
    session.close()

    st.markdown("## ⚙️ System Setup")
    st.markdown(
        f"<span style='color:#64748b;font-size:13px'>"
        f"{system_name} · One-time system configuration"
        f"</span>",
        unsafe_allow_html=True
    )
    st.divider()

    if uses_mwater:
        st.info(
            "ℹ️ This system uses mWater. "
            "Assets and customers are managed "
            "in mWater and synced automatically."
        )
        return

    tab1, tab2, tab3 = st.tabs([
        "🏗️ Assets",
        "👥 Customers",
        "💰 Tariffs"
    ])

    # ── Tab 1: Assets ──────────────────────────────────
    with tab1:
        st.markdown("### Register assets")
        st.caption(
            "Add pump houses, tanks, pipes and "
            "other infrastructure components. "
            "GPS is captured automatically."
        )

        with st.form("asset_form"):
            col1, col2 = st.columns(2)
            with col1:
                a_name = st.text_input(
                    "Asset name *",
                    placeholder="e.g. Main Pump House"
                )
                a_type = st.selectbox(
                    "Asset type *",
                    ["pump_house", "tank",
                     "pipe", "valve",
                     "meter", "other"]
                )
            with col2:
                a_lat = st.number_input(
                    "Latitude",
                    value=0.0, format="%.6f"
                )
                a_lon = st.number_input(
                    "Longitude",
                    value=0.0, format="%.6f"
                )

            a_submit = st.form_submit_button(
                "✓ Add asset",
                use_container_width=True,
                type="primary"
            )

            if a_submit and a_name:
                session = get_session()
                session.add(Asset(
                    system_id  = system_id,
                    name       = a_name,
                    asset_type = a_type,
                    latitude   = a_lat or None,
                    longitude  = a_lon or None,
                    is_active  = True
                ))
                session.commit()
                session.close()
                st.success(f"✓ {a_name} added.")
                st.rerun()

        st.divider()
        st.markdown("### Registered assets")
        session = get_session()
        assets  = session.query(Asset).filter_by(
            system_id=system_id, is_active=True
        ).all()
        session.close()

        if assets:
            rows = [{
                "Name":      a.name,
                "Type":      a.asset_type,
                "Latitude":  a.latitude or "—",
                "Longitude": a.longitude or "—"
            } for a in assets]
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No assets registered yet.")

    # ── Tab 2: Customers ───────────────────────────────
    with tab2:
        st.markdown("### Register customers")
        st.caption(
            "Add customers once. Maji360 stores "
            "all details — just select from list "
            "when billing."
        )

        with st.form("customer_form"):
            col1, col2 = st.columns(2)
            with col1:
                c_name    = st.text_input(
                    "Customer name *",
                    placeholder="e.g. Karungu I PSP"
                )
                c_acc     = st.text_input(
                    "Account number *",
                    placeholder="e.g. 433001"
                )
                c_meter   = st.text_input(
                    "Meter number *",
                    placeholder="e.g. 659279453"
                )
                c_phone   = st.text_input(
                    "Phone number",
                    placeholder="+256700000000"
                )
            with col2:
                c_type    = st.selectbox(
                    "Connection type *",
                    ["PSP", "Private",
                     "School", "Institution"]
                )
                c_opening = st.number_input(
                    "Opening meter reading (m³) *",
                    min_value=0.0,
                    value=0.0,
                    step=0.1,
                    format="%.1f",
                    help="Meter reading on day "
                         "of installation"
                )
                c_lat     = st.number_input(
                    "Latitude",
                    value=0.0, format="%.6f"
                )
                c_lon     = st.number_input(
                    "Longitude",
                    value=0.0, format="%.6f"
                )
                c_address = st.text_input(
                    "Address / location description"
                )

            c_submit = st.form_submit_button(
                "✓ Add customer",
                use_container_width=True,
                type="primary"
            )

            if c_submit and c_name and c_acc and c_meter:
                session  = get_session()
                existing = session.query(Customer).filter_by(
                    system_id  = system_id,
                    account_no = c_acc
                ).first()
                if existing:
                    st.error(
                        f"Account {c_acc} already exists."
                    )
                    session.close()
                else:
                    session.add(Customer(
                        system_id       = system_id,
                        name            = c_name,
                        account_no      = c_acc,
                        meter_no        = c_meter,
                        phone           = c_phone or None,
                        connection_type = c_type,
                        opening_reading = c_opening,
                        last_reading    = c_opening,
                        address         = c_address,
                        latitude        = c_lat or None,
                        longitude       = c_lon or None,
                        is_active       = True
                    ))
                    session.commit()
                    session.close()
                    st.success(f"✓ {c_name} added.")
                    st.rerun()

        st.divider()
        st.markdown("### Registered customers")
        session   = get_session()
        customers = session.query(Customer).filter_by(
            system_id=system_id, is_active=True
        ).all()
        session.close()

        if customers:
            rows = [{
                "Account":  c.account_no,
                "Name":     c.name,
                "Type":     getattr(
                    c, 'connection_type', 'PSP'
                ),
                "Meter":    c.meter_no,
                "Opening":  getattr(
                    c, 'opening_reading', 0
                ),
                "Phone":    c.phone or "—"
            } for c in customers]
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True
            )

            # Deactivate customer
            st.divider()
            st.markdown("### Deactivate customer")
            deact_opts = {
                f"{c.account_no} — {c.name}": c.id
                for c in customers
            }
            deact_sel = st.selectbox(
                "Select customer to deactivate",
                options=list(deact_opts.keys())
            )
            if st.button(
                "Deactivate selected customer",
                type="secondary"
            ):
                session  = get_session()
                target   = session.query(Customer).filter_by(
                    id=deact_opts[deact_sel]
                ).first()
                if target:
                    target.is_active = False
                    session.commit()
                st.success(
                    f"✓ {deact_sel} deactivated."
                )
                session.close()
                st.rerun()
        else:
            st.info("No customers registered yet.")

    # ── Tab 3: Tariffs ─────────────────────────────────
    with tab3:
        st.markdown("### Tariff settings")
        st.caption(
            "Set tariffs per connection type. "
            "Changes apply to all new bills generated."
        )

        session = get_session()
        system  = session.query(WaterSystem).filter_by(
            id=system_id
        ).first()
        current_psp     = getattr(
            system, 'tariff_psp', 2500.0
        ) or 2500.0
        current_private = getattr(
            system, 'tariff_private', 3000.0
        ) or 3000.0
        session.close()

        with st.form("tariff_form"):
            col1, col2 = st.columns(2)
            with col1:
                new_psp = st.number_input(
                    f"PSP tariff ({currency}/m³) *",
                    min_value=0.0,
                    value=float(current_psp),
                    step=100.0,
                    format="%.0f"
                )
            with col2:
                new_private = st.number_input(
                    f"Private connection tariff "
                    f"({currency}/m³) *",
                    min_value=0.0,
                    value=float(current_private),
                    step=100.0,
                    format="%.0f"
                )

            t_submit = st.form_submit_button(
                "✓ Update tariffs",
                use_container_width=True,
                type="primary"
            )

            if t_submit:
                session = get_session()
                sys_obj = session.query(
                    WaterSystem
                ).filter_by(id=system_id).first()
                if sys_obj:
                    sys_obj.tariff_psp     = new_psp
                    sys_obj.tariff_private = new_private
                    sys_obj.tariff_per_m3  = new_psp
                    session.commit()
                session.close()
                st.success(
                    f"✓ Tariffs updated — "
                    f"PSP: {currency} {new_psp:,.0f}/m³, "
                    f"Private: {currency} "
                    f"{new_private:,.0f}/m³"
                )
                st.rerun()

        st.divider()
        st.markdown("### Current tariff summary")
        st.markdown(f"""
        | Connection type | Tariff per m³ |
        |---|---|
        | PSP | {currency} {current_psp:,.0f} |
        | Private connection | {currency} {current_private:,.0f} |
        """)
