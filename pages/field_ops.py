import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from core.database import (
    get_session, WaterSystem, Asset,
    MeterReading, DailyReading, NRWRecord
)
from core.auth import require_login, is_operator
from collections import defaultdict


def get_gps():
    """
    Returns GPS coordinates from browser if available.
    Falls back to system coordinates.
    """
    session  = get_session()
    system   = session.query(WaterSystem).filter_by(
        id=st.session_state.get("selected_system_id")
    ).first()
    fallback = (
        system.latitude,
        system.longitude
    ) if system else (None, None)
    session.close()
    return fallback


def recalculate_nrw_native(system_id: int):
    """Recalculate NRW from meter_readings table."""
    session  = get_session()
    readings = session.query(MeterReading).filter_by(
        system_id=system_id
    ).all()

    monthly = defaultdict(
        lambda: {"pumped": 0.0, "consumed": 0.0}
    )
    for r in readings:
        month = r.reading_date.strftime("%Y-%m")
        if r.reading_type == "pump" and r.volume:
            monthly[month]["pumped"]   += r.volume
        elif r.reading_type == "tank" and r.volume:
            monthly[month]["consumed"] += r.volume

    for month, data in monthly.items():
        pumped   = round(data["pumped"],   2)
        consumed = round(data["consumed"], 2)
        nrw_m3   = round(pumped - consumed, 2)
        nrw_pct  = round(
            (nrw_m3 / pumped) * 100, 1
        ) if pumped > 0 else 0

        existing = session.query(NRWRecord).filter_by(
            system_id=system_id, month=month
        ).first()

        if existing:
            existing.water_produced = pumped
            existing.water_billed   = consumed
            existing.nrw_m3         = nrw_m3
            existing.nrw_percent    = nrw_pct
        else:
            session.add(NRWRecord(
                system_id      = system_id,
                month          = month,
                water_produced = pumped,
                water_billed   = consumed,
                nrw_m3         = nrw_m3,
                nrw_percent    = nrw_pct
            ))

    # Also update daily_readings for dashboard charts
    for r in readings:
        if r.reading_type in ["pump", "tank"]:
            existing_dr = session.query(
                DailyReading
            ).filter_by(
                system_id=system_id,
                reading_date=r.reading_date
            ).first()

            if not existing_dr:
                dr = DailyReading(
                    system_id         = system_id,
                    reading_date      = r.reading_date,
                    water_produced_m3 = r.volume
                    if r.reading_type == "pump" else 0.0,
                    water_consumed_m3 = r.volume
                    if r.reading_type == "tank" else 0.0,
                    water_sold_m3     = 0.0,
                    synced_at         = datetime.now(
                        timezone.utc
                    )
                )
                session.add(dr)

    session.commit()
    session.close()


def show():
    require_login()

    system_id   = st.session_state.get("selected_system_id")
    system_name = st.session_state.get(
        "selected_system_name", ""
    )

    if not system_id:
        st.warning("Please select a water system.")
        return

    # Check if this is a non-mWater system
    session = get_session()
    system  = session.query(WaterSystem).filter_by(
        id=system_id
    ).first()
    uses_mwater = getattr(system, 'uses_mwater', True)
    currency    = system.currency or "UGX"
    session.close()

    st.markdown("## 📋 Field Operations")
    st.markdown(
        f"<span style='color:#64748b;font-size:13px'>"
        f"{system_name} · Record readings in the field"
        f"</span>",
        unsafe_allow_html=True
    )
    st.divider()

    if uses_mwater:
        st.info(
            "ℹ️ This system uses mWater for data "
            "collection. Readings are synced "
            "automatically from mWater. Use the "
            "Sync page to pull latest data."
        )
        return

    # ── Fetch assets ───────────────────────────────────
    session = get_session()
    assets  = session.query(Asset).filter_by(
        system_id=system_id, is_active=True
    ).all()
    session.close()

    if not assets:
        st.warning(
            "No assets registered for this system. "
            "Please add pump houses and tanks first "
            "in the System Setup page."
        )
        return

    # ── Tab layout ─────────────────────────────────────
    tab1, tab2 = st.tabs([
        "📥 Record reading",
        "📊 Recent readings"
    ])

    # ── Tab 1: Record reading ──────────────────────────
    with tab1:
        st.markdown("### Record asset reading")

        asset_options = {
            f"{a.name} ({a.asset_type})": a
            for a in assets
        }

        selected_asset_name = st.selectbox(
            "Select asset *",
            options=list(asset_options.keys())
        )
        selected_asset = asset_options[selected_asset_name]

        # Determine reading type from asset type
        asset_type = selected_asset.asset_type or ""
        if "pump" in asset_type.lower():
            reading_type = "pump"
            reading_label = "pump house bulk meter"
        elif "tank" in asset_type.lower():
            reading_type = "tank"
            reading_label = "tank outlet bulk meter"
        else:
            reading_type = "other"
            reading_label = "meter"

        st.markdown(
            f"<span style='font-size:13px;"
            f"color:#64748b'>Reading from: "
            f"{reading_label}</span>",
            unsafe_allow_html=True
        )

        # Show last reading for reference
        session       = get_session()
        last_reading  = session.query(MeterReading).filter_by(
            system_id=system_id,
            asset_id=selected_asset.id
        ).order_by(
            MeterReading.reading_date.desc()
        ).first()
        session.close()

        if last_reading:
            st.info(
                f"Last reading — "
                f"End: **{last_reading.end_reading}** "
                f"on {last_reading.reading_date.strftime('%d %b %Y')}"
            )

        with st.form("reading_form"):
            col1, col2 = st.columns(2)
            with col1:
                start_val = st.number_input(
                    "Start reading (m³) *",
                    min_value=0.0,
                    value=float(
                        last_reading.end_reading
                        if last_reading else 0.0
                    ),
                    step=0.1,
                    format="%.1f"
                )
            with col2:
                end_val = st.number_input(
                    "End reading (m³) *",
                    min_value=0.0,
                    value=float(
                        last_reading.end_reading
                        if last_reading else 0.0
                    ),
                    step=0.1,
                    format="%.1f"
                )

            reading_date = st.date_input(
                "Reading date *",
                value=datetime.now().date()
            )

            notes = st.text_input(
                "Notes (optional)",
                placeholder="e.g. pump serviced, "
                            "unusual noise observed"
            )

            submitted = st.form_submit_button(
                "✓ Save reading",
                use_container_width=True,
                type="primary"
            )

            if submitted:
                if end_val <= start_val:
                    st.error(
                        "End reading must be greater "
                        "than start reading."
                    )
                else:
                    volume = round(end_val - start_val, 2)

                    # Get system GPS as fallback
                    lat, lon = get_gps()

                    session = get_session()
                    session.add(MeterReading(
                        system_id    = system_id,
                        asset_id     = selected_asset.id,
                        reading_type = reading_type,
                        reading_date = datetime.combine(
                            reading_date,
                            datetime.min.time()
                        ).replace(tzinfo=timezone.utc),
                        start_reading = start_val,
                        end_reading   = end_val,
                        volume        = volume,
                        latitude      = lat,
                        longitude     = lon
                    ))
                    session.commit()
                    session.close()

                    # Recalculate NRW
                    recalculate_nrw_native(system_id)

                    st.success(
                        f"✓ Reading saved — "
                        f"{volume:.1f} m³ recorded "
                        f"for {selected_asset.name}"
                    )
                    st.rerun()

    # ── Tab 2: Recent readings ─────────────────────────
    with tab2:
        st.markdown("### Recent readings")

        session  = get_session()
        recent   = session.query(MeterReading).filter_by(
            system_id=system_id
        ).order_by(
            MeterReading.reading_date.desc()
        ).limit(20).all()

        asset_names = {
            a.id: a.name for a in assets
        }
        session.close()

        if recent:
            rows = [{
                "Date":    r.reading_date.strftime(
                    "%d %b %Y"
                ),
                "Asset":   asset_names.get(
                    r.asset_id, "—"
                ),
                "Type":    r.reading_type.title()
                           if r.reading_type else "—",
                "Start":   r.start_reading,
                "End":     r.end_reading,
                "Volume":  f"{r.volume:.1f} m³"
                           if r.volume else "—"
            } for r in recent]

            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No readings recorded yet.")

        # Monthly summary
        st.divider()
        st.markdown("### Monthly summary")

        session  = get_session()
        all_rdgs = session.query(MeterReading).filter_by(
            system_id=system_id
        ).all()
        session.close()

        if all_rdgs:
            monthly = defaultdict(
                lambda: {"pumped": 0.0, "consumed": 0.0}
            )
            for r in all_rdgs:
                month = r.reading_date.strftime("%Y-%m")
                if r.reading_type == "pump" and r.volume:
                    monthly[month]["pumped"] += r.volume
                elif r.reading_type == "tank" and r.volume:
                    monthly[month]["consumed"] += r.volume

            rows = []
            for month in sorted(monthly.keys()):
                pumped   = monthly[month]["pumped"]
                consumed = monthly[month]["consumed"]
                nrw      = round(pumped - consumed, 1)
                nrw_pct  = round(
                    (nrw / pumped) * 100, 1
                ) if pumped > 0 else 0
                status   = (
                    "🔴 ALERT" if nrw_pct >= 20 else
                    "🟡 WARN"  if nrw_pct >= 15 else
                    "🟢 OK"
                )
                rows.append({
                    "Month":       month,
                    "Pumped m³":   pumped,
                    "Consumed m³": consumed,
                    "NRW m³":      nrw,
                    "NRW %":       f"{nrw_pct}%",
                    "Status":      status
                })

            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True
            )
