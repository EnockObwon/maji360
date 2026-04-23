import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from core.database import (
    get_session, WaterSystem, Asset, Customer
)
from core.auth import require_login
import math


ASSET_TYPES = [
    "borehole", "pump", "pump_house",
    "power_supply", "generator", "pipeline",
    "pipe", "tank", "treatment", "meter",
    "valve", "civil", "other"
]

ASSET_TYPE_LABELS = {
    "borehole":     "Borehole / Water source",
    "pump":         "Pump (submersible or surface)",
    "pump_house":   "Pump house",
    "power_supply": "Power supply (solar/electric)",
    "generator":    "Generator (backup) — optional",
    "pipeline":     "Pipeline",
    "pipe":         "Pipe (overflow/other)",
    "tank":         "Storage tank",
    "treatment":    "Water treatment",
    "meter":        "Bulk or customer meter",
    "valve":        "Valve (gate/air release)",
    "civil":        "Civil structure",
    "other":        "Other"
}

RECOMMENDED_ASSETS = [
    ("Borehole / Water Source",              "borehole"),
    ("Submersible Pump",                     "pump"),
    ("Pump House",                           "pump_house"),
    ("Power Supply (Solar Panels)",          "power_supply"),
    ("Rising Main Pipeline",                 "pipeline"),
    ("Transmission Main (Pump to Tank)",     "pipeline"),
    ("Storage Tank",                         "tank"),
    ("Overflow Pipe",                        "pipe"),
    ("Treatment House",                      "treatment"),
    ("Inline Chlorinator",                   "treatment"),
    ("Tank Outlet Bulk Meter",               "meter"),
    ("Main Distribution Pipeline",           "pipeline"),
    ("Secondary Pipelines",                  "pipeline"),
    ("Air Release Valves",                   "valve"),
    ("Gate Valves",                          "valve"),
    ("Customer Meters",                      "meter"),
    ("Fence / Security",                     "civil"),
    ("Access Road",                          "civil"),
    ("Generator (backup)",                   "generator"),
]

CONNECTION_TYPES = [
    "PSP", "Private", "School", "Institution"
]

POPULATION_HELP = {
    "PSP":         "Total number of people "
                   "served by this PSP",
    "Private":     "Number of people in this "
                   "household connection. "
                   "Note: if switching from PSP "
                   "reduce PSP population accordingly",
    "School":      "Current school enrollment "
                   "(pupils + staff)",
    "Institution": "Total number of people "
                   "served by this connection"
}


def generate_account_no(system_name: str,
                         system_id: int) -> str:
    words  = system_name.strip().split()
    prefix = "".join(
        w[0] for w in words[:3]
    ).upper()[:3]

    session   = get_session()
    customers = session.query(Customer).filter(
        Customer.system_id  == system_id,
        Customer.account_no.like(f"{prefix}%")
    ).all()
    session.close()

    if not customers:
        next_num = 1
    else:
        existing_nums = []
        for c in customers:
            try:
                num = int(
                    c.account_no.replace(prefix, "")
                )
                existing_nums.append(num)
            except ValueError:
                continue
        next_num = max(existing_nums) + 1 \
                   if existing_nums else 1

    return f"{prefix}{next_num:04d}"


def show():
    require_login()

    system_id   = st.session_state.get(
        "selected_system_id"
    )
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
            "Customers are managed in mWater "
            "and synced automatically. "
            "You can still register assets here "
            "for maintenance tracking."
        )
        _show_assets_tab(
            system_id, system_name,
            currency, mwater_mode=True
        )
        return

    tab1, tab2, tab3 = st.tabs([
        "🏗️ Assets",
        "👥 Customers",
        "💰 Tariffs"
    ])

    with tab1:
        _show_assets_tab(
            system_id, system_name,
            currency, mwater_mode=False
        )
    with tab2:
        _show_customers_tab(
            system_id, system_name, currency
        )
    with tab3:
        _show_tariffs_tab(system_id, currency)


def _show_assets_tab(system_id, system_name,
                      currency, mwater_mode=False):
    st.markdown("### Register assets")
    st.caption(
        "Register all physical assets. "
        "This enables maintenance tracking "
        "and field operations."
    )

    session        = get_session()
    existing       = session.query(Asset).filter_by(
        system_id=system_id, is_active=True
    ).all()
    existing_names = {a.name.lower() for a in existing}
    session.close()

    missing = [
        (name, atype)
        for name, atype in RECOMMENDED_ASSETS
        if name.lower() not in existing_names
    ]

    if missing and not mwater_mode:
        st.markdown("#### Quick setup")
        st.caption(
            "Recommended assets for a typical "
            "rural water system. Generator is "
            "optional — uncheck if not available."
        )

        with st.expander(
            f"➕ Add {len(missing)} recommended assets",
            expanded=len(existing) == 0
        ):
            selected = []
            for name, atype in missing:
                label      = ASSET_TYPE_LABELS.get(
                    atype, atype
                )
                is_optional = "optional" in label.lower()
                checked     = st.checkbox(
                    f"{name} ({label})",
                    value=not is_optional,
                    key=f"quick_{name}"
                )
                if checked:
                    selected.append((name, atype))

            if st.button(
                f"✓ Add {len(selected)} selected",
                type="primary",
                disabled=len(selected) == 0
            ):
                session = get_session()
                added   = 0
                for name, atype in selected:
                    if name.lower() not in \
                       existing_names:
                        session.add(Asset(
                            system_id  = system_id,
                            name       = name,
                            asset_type = atype,
                            is_active  = True
                        ))
                        added += 1
                session.commit()
                session.close()
                st.success(
                    f"✓ {added} assets added."
                )
                st.rerun()

    st.divider()
    st.markdown("#### Add individual asset")

    with st.form("asset_form"):
        col1, col2 = st.columns(2)
        with col1:
            a_name = st.text_input(
                "Asset name *",
                placeholder="e.g. Main Pump House"
            )
            a_type = st.selectbox(
                "Asset type *",
                options=ASSET_TYPES,
                format_func=lambda x:
                    ASSET_TYPE_LABELS.get(x, x)
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

        a_shape = a_length = a_width = None
        a_diameter = a_height = a_capacity = None

        if a_type == "tank":
            st.markdown("**Tank dimensions**")
            col3, col4 = st.columns(2)
            with col3:
                a_shape  = st.selectbox(
                    "Shape *",
                    ["rectangular", "cylindrical"]
                )
                a_height = st.number_input(
                    "Height (m) *",
                    min_value=0.0,
                    value=3.0, step=0.1,
                    format="%.1f"
                )
            with col4:
                if a_shape == "rectangular":
                    a_length = st.number_input(
                        "Length (m) *",
                        min_value=0.0,
                        value=4.0, step=0.1,
                        format="%.1f"
                    )
                    a_width = st.number_input(
                        "Width (m) *",
                        min_value=0.0,
                        value=4.0, step=0.1,
                        format="%.1f"
                    )
                    if a_length and a_width \
                       and a_height:
                        a_capacity = round(
                            a_length * a_width *
                            a_height, 1
                        )
                        st.markdown(
                            f"**Capacity:** "
                            f"{a_capacity} m³"
                        )
                else:
                    a_diameter = st.number_input(
                        "Diameter (m) *",
                        min_value=0.0,
                        value=2.0, step=0.1,
                        format="%.1f"
                    )
                    if a_diameter and a_height:
                        a_capacity = round(
                            math.pi *
                            (a_diameter / 2) ** 2 *
                            a_height, 1
                        )
                        st.markdown(
                            f"**Capacity:** "
                            f"{a_capacity} m³"
                        )

        if st.form_submit_button(
            "✓ Add asset",
            use_container_width=True,
            type="primary"
        ) and a_name:
            session = get_session()
            session.add(Asset(
                system_id   = system_id,
                name        = a_name,
                asset_type  = a_type,
                shape       = a_shape,
                length_m    = a_length,
                width_m     = a_width,
                diameter_m  = a_diameter,
                height_m    = a_height,
                capacity_m3 = a_capacity,
                latitude    = a_lat or None,
                longitude   = a_lon or None,
                is_active   = True
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
            "Type":      ASSET_TYPE_LABELS.get(
                a.asset_type, a.asset_type
            ),
            "Capacity":  f"{a.capacity_m3:.0f} m³"
                         if a.capacity_m3 else "—",
        } for a in assets]
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True
        )
        st.markdown(
            f"**{len(assets)} assets registered**"
        )
    else:
        st.info("No assets registered yet.")


def _show_customers_tab(system_id, system_name,
                          currency):
    st.markdown("### Register customers")
    st.caption(
        "Population served is mandatory for all "
        "connection types — this is used for "
        "official DHIS2 reporting. "
        "If a household switches from PSP to "
        "private connection, reduce the PSP "
        "population accordingly."
    )

    # Show current total population
    session   = get_session()
    customers = session.query(Customer).filter_by(
        system_id=system_id, is_active=True
    ).all()
    session.close()

    total_pop = sum(
        getattr(c, 'population', 0) or 0
        for c in customers
    )
    if total_pop > 0:
        st.info(
            f"Current total population served: "
            f"**{total_pop:,} people**"
        )

    next_acc = generate_account_no(
        system_name, system_id
    )
    st.markdown(
        f"<div style='background:#eff6ff;"
        f"border-radius:8px;padding:10px 16px;"
        f"margin-bottom:12px;font-size:13px'>"
        f"Next account number: <b>{next_acc}</b>"
        f"</div>",
        unsafe_allow_html=True
    )

    with st.form("customer_form"):
        col1, col2 = st.columns(2)
        with col1:
            c_name    = st.text_input(
                "Customer name *",
                placeholder="e.g. Nyakabale I PSP"
            )
            c_meter   = st.text_input(
                "Meter number *"
            )
            c_phone   = st.text_input(
                "Phone number",
                placeholder="+256700000000"
            )
            c_address = st.text_input(
                "Address / location"
            )
        with col2:
            c_type = st.selectbox(
                "Connection type *",
                CONNECTION_TYPES
            )
            c_population = st.number_input(
                "Population served *",
                min_value=0,
                value=0,
                step=1,
                help=POPULATION_HELP.get(
                    c_type, "Number of people served"
                )
            )
            c_opening = st.number_input(
                "Opening meter reading (m³) *",
                min_value=0.0,
                value=0.0, step=0.1,
                format="%.1f",
                help="Meter reading on installation day"
            )
            c_lat = st.number_input(
                "Latitude",
                value=0.0, format="%.6f"
            )
            c_lon = st.number_input(
                "Longitude",
                value=0.0, format="%.6f"
            )

        # Population warning for private connections
        if c_type == "Private" and c_population > 0:
            st.warning(
                f"⚠️ Remember to reduce the "
                f"population of the PSP this "
                f"household was previously served by "
                f"by {c_population} people."
            )

        c_submit = st.form_submit_button(
            "✓ Add customer",
            use_container_width=True,
            type="primary"
        )

        if c_submit:
            if not c_name or not c_meter:
                st.error(
                    "Customer name and meter "
                    "number are required."
                )
            elif c_population == 0:
                st.error(
                    "Population served is required. "
                    "Enter the number of people "
                    "this connection serves."
                )
            else:
                acc_no   = generate_account_no(
                    system_name, system_id
                )
                session  = get_session()
                existing = session.query(
                    Customer
                ).filter_by(
                    system_id=system_id,
                    meter_no=c_meter
                ).first()

                if existing:
                    st.error(
                        f"Meter {c_meter} already "
                        f"registered."
                    )
                    session.close()
                else:
                    session.add(Customer(
                        system_id       = system_id,
                        name            = c_name,
                        account_no      = acc_no,
                        meter_no        = c_meter,
                        phone           = c_phone
                                          or None,
                        connection_type = c_type,
                        population      = c_population,
                        opening_reading = c_opening,
                        last_reading    = c_opening,
                        address         = c_address,
                        latitude        = c_lat or None,
                        longitude       = c_lon or None,
                        is_active       = True
                    ))
                    session.commit()
                    session.close()
                    new_total = total_pop + c_population
                    st.success(
                        f"✓ {c_name} added — "
                        f"account {acc_no} · "
                        f"population +{c_population} "
                        f"→ total {new_total:,}"
                    )
                    st.rerun()

    st.divider()
    st.markdown("### Registered customers")

    if customers:
        rows = []
        for c in customers:
            pop  = getattr(c, 'population', 0) or 0
            rows.append({
                "Account":    c.account_no,
                "Name":       c.name,
                "Type":       getattr(
                    c, 'connection_type', 'PSP'
                ) or 'PSP',
                "Population": pop,
                "Meter":      c.meter_no,
                "Phone":      c.phone or "—"
            })

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True
        )
        st.markdown(
            f"**Total population served: "
            f"{total_pop:,} people**"
        )

        st.divider()
        st.markdown("### Edit customer population")
        st.caption(
            "Use this to correct population figures "
            "or adjust when a household switches "
            "from PSP to private connection."
        )

        edit_opts = {
            f"{c.account_no} — {c.name}": c
            for c in customers
        }
        edit_sel = st.selectbox(
            "Select customer to edit",
            options=list(edit_opts.keys()),
            key="edit_pop_sel"
        )
        edit_cust = edit_opts[edit_sel]
        current_pop = getattr(
            edit_cust, 'population', 0
        ) or 0

        col1, col2 = st.columns(2)
        with col1:
            new_pop = st.number_input(
                f"Population served "
                f"(current: {current_pop})",
                min_value=0,
                value=current_pop,
                step=1,
                key="edit_pop_val"
            )
        with col2:
            st.markdown("")
            st.markdown("")
            if st.button(
                "✓ Update population",
                type="primary"
            ):
                session = get_session()
                target  = session.query(
                    Customer
                ).filter_by(
                    id=edit_cust.id
                ).first()
                if target:
                    target.population = new_pop
                    session.commit()
                session.close()
                st.success(
                    f"✓ Population updated to "
                    f"{new_pop:,}"
                )
                st.rerun()

        st.divider()
        st.markdown("### Deactivate customer")
        deact_opts = {
            f"{c.account_no} — {c.name}": c.id
            for c in customers
        }
        deact_sel = st.selectbox(
            "Select customer to deactivate",
            options=list(deact_opts.keys()),
            key="deact_sel"
        )
        if st.button(
            "Deactivate selected customer",
            type="secondary"
        ):
            session = get_session()
            target  = session.query(
                Customer
            ).filter_by(
                id=deact_opts[deact_sel]
            ).first()
            if target:
                target.is_active = False
                session.commit()
            session.close()
            st.success(
                f"✓ {deact_sel} deactivated."
            )
            st.rerun()
    else:
        st.info("No customers registered yet.")


def _show_tariffs_tab(system_id, currency):
    st.markdown("### Tariff settings")

    session         = get_session()
    system          = session.query(
        WaterSystem
    ).filter_by(id=system_id).first()
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
                step=100.0, format="%.0f"
            )
        with col2:
            new_private = st.number_input(
                f"Private tariff ({currency}/m³) *",
                min_value=0.0,
                value=float(current_private),
                step=100.0, format="%.0f"
            )

        if st.form_submit_button(
            "✓ Update tariffs",
            use_container_width=True,
            type="primary"
        ):
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
                f"PSP: {currency} {new_psp:,.0f}/m³ "
                f"· Private: {currency} "
                f"{new_private:,.0f}/m³"
            )
            st.rerun()

    st.divider()
    st.markdown("### Current tariff summary")
    st.markdown(f"""
    | Connection type | Tariff per m³ |
    |---|---|
    | PSP | {currency} {current_psp:,.0f} |
    | Private | {currency} {current_private:,.0f} |
    """)
