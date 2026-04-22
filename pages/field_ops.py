import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone
from core.database import (
    get_session, WaterSystem, Asset,
    MeterReading, DailyReading, NRWRecord
)
from core.auth import require_login
from collections import defaultdict
from sqlalchemy import text as sql_text
import math


def calculate_volume(asset, level_m: float) -> tuple:
    """
    Calculate volume and percentage full from
    tank level reading.
    Returns (volume_m3, pct_full)
    """
    shape      = getattr(asset, 'shape', 'rectangular') \
                 or 'rectangular'
    height_m   = getattr(asset, 'height_m', None)
    capacity   = getattr(asset, 'capacity_m3', None)

    if not height_m or height_m <= 0:
        return 0.0, 0.0

    # Clamp level to valid range
    level_m = max(0.0, min(level_m, height_m))

    if shape == 'cylindrical':
        diameter_m = getattr(asset, 'diameter_m', None)
        if not diameter_m:
            return 0.0, 0.0
        radius   = diameter_m / 2
        volume   = math.pi * radius ** 2 * level_m
    else:
        # Rectangular
        length_m = getattr(asset, 'length_m', None)
        width_m  = getattr(asset, 'width_m', None)
        if not length_m or not width_m:
            return 0.0, 0.0
        volume = length_m * width_m * level_m

    pct_full = round((level_m / height_m) * 100, 1)
    volume   = round(volume, 2)

    return volume, pct_full


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

        # Update daily_readings for dashboard charts
        for r in readings:
            if r.reading_type in ["pump", "tank"]:
                existing_dr = session.query(
                    DailyReading
                ).filter_by(
                    system_id    = system_id,
                    reading_date = r.reading_date
                ).first()

                if not existing_dr:
                    session.add(DailyReading(
                        system_id         = system_id,
                        reading_date      = r.reading_date,
                        water_produced_m3 = r.volume
                            if r.reading_type == "pump"
                            else 0.0,
                        water_consumed_m3 = r.volume
                            if r.reading_type == "tank"
                            else 0.0,
                        water_sold_m3     = 0.0,
                        synced_at         = datetime.now(
                            timezone.utc
                        )
                    ))

    session.commit()
    session.close()


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
            "collection. Use the Sync page to pull "
            "latest data from mWater."
        )

        # Still show tank level entry for mWater systems
        st.markdown("### 📊 Tank level readings")
        st.caption(
            "Record weekly tank level dip readings "
            "for adjusted NRW calculation."
        )
        _show_tank_level_section(system_id, system_name)
        return

    # ── Non-mWater system ──────────────────────────────
    session = get_session()
    assets  = session.query(Asset).filter_by(
        system_id=system_id, is_active=True
    ).all()
    session.close()

    if not assets:
        st.warning(
            "No assets registered. Please add pump "
            "houses and tanks in System Setup first."
        )
        return

    tab1, tab2, tab3 = st.tabs([
        "📥 Pump / Tank outlet reading",
        "📊 Tank level dip",
        "📈 Recent readings"
    ])

    # ── Tab 1: Pump and tank outlet readings ───────────
    with tab1:
        st.markdown("### Record asset reading")

        asset_options = {
            f"{a.name} ({a.asset_type})": a
            for a in assets
            if a.asset_type in ["pump_house", "tank",
                                 "other"]
        }

        if not asset_options:
            st.info("No pump house or tank assets found.")
        else:
            selected_asset_name = st.selectbox(
                "Select asset *",
                options=list(asset_options.keys()),
                key="asset_select"
            )
            selected_asset = asset_options[
                selected_asset_name
            ]

            asset_type = selected_asset.asset_type or ""
            if "pump" in asset_type.lower():
                reading_type  = "pump"
                reading_label = "pump house bulk meter"
            elif "tank" in asset_type.lower():
                reading_type  = "tank"
                reading_label = "tank outlet bulk meter"
            else:
                reading_type  = "other"
                reading_label = "meter"

            st.markdown(
                f"<span style='font-size:13px;"
                f"color:#64748b'>Reading from: "
                f"{reading_label}</span>",
                unsafe_allow_html=True
            )

            session      = get_session()
            last_reading = session.query(
                MeterReading
            ).filter_by(
                system_id=system_id,
                asset_id=selected_asset.id
            ).order_by(
                MeterReading.reading_date.desc()
            ).first()
            session.close()

            if last_reading:
                st.info(
                    f"Last reading — "
                    f"End: **{last_reading.end_reading}**"
                    f" on "
                    f"{last_reading.reading_date.strftime('%d %b %Y')}"
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
                    "Notes (optional)"
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
                        volume  = round(
                            end_val - start_val, 2
                        )
                        session = get_session()
                        session.add(MeterReading(
                            system_id     = system_id,
                            asset_id      = selected_asset.id,
                            reading_type  = reading_type,
                            reading_date  = datetime.combine(
                                reading_date,
                                datetime.min.time()
                            ).replace(tzinfo=timezone.utc),
                            start_reading = start_val,
                            end_reading   = end_val,
                            volume        = volume
                        ))
                        session.commit()
                        session.close()
                        recalculate_nrw_native(system_id)
                        st.success(
                            f"✓ Reading saved — "
                            f"{volume:.1f} m³ recorded"
                        )
                        st.rerun()

    # ── Tab 2: Tank level dip ──────────────────────────
    with tab2:
        _show_tank_level_section(system_id, system_name)

    # ── Tab 3: Recent readings ─────────────────────────
    with tab3:
        st.markdown("### Recent readings")

        session     = get_session()
        recent      = session.query(MeterReading).filter_by(
            system_id=system_id
        ).order_by(
            MeterReading.reading_date.desc()
        ).limit(20).all()
        asset_names = {a.id: a.name for a in assets}
        session.close()

        if recent:
            rows = [{
                "Date":   r.reading_date.strftime(
                    "%d %b %Y"
                ),
                "Asset":  asset_names.get(
                    r.asset_id, "—"
                ),
                "Type":   r.reading_type.title()
                          if r.reading_type else "—",
                "Start":  r.start_reading,
                "End":    r.end_reading,
                "Volume": f"{r.volume:.1f} m³"
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
        st.markdown("### Monthly NRW summary")
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
                if r.reading_type == "pump" \
                   and r.volume:
                    monthly[month]["pumped"] += r.volume
                elif r.reading_type == "tank" \
                   and r.volume:
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


def _show_tank_level_section(system_id: int,
                               system_name: str):
    """
    Tank level dip recording section.
    Works for both mWater and non-mWater systems.
    """
    # Get tank assets with dimensions
    session     = get_session()
    tank_assets = session.query(Asset).filter_by(
        system_id=system_id,
        asset_type="tank",
        is_active=True
    ).all()
    session.close()

    if not tank_assets:
        st.info(
            "No tank assets registered. "
            "Please add tanks in System Setup first."
        )
        return

    tank_options = {
        a.name: a for a in tank_assets
    }

    selected_tank_name = st.selectbox(
        "Select tank *",
        options=list(tank_options.keys()),
        key="tank_level_select"
    )
    selected_tank = tank_options[selected_tank_name]

    # Show tank info
    shape    = getattr(
        selected_tank, 'shape', 'rectangular'
    ) or 'rectangular'
    height_m = getattr(selected_tank, 'height_m', None)
    cap      = getattr(
        selected_tank, 'capacity_m3', None
    )

    if height_m and cap:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"**Shape:** {shape.title()}")
        with col2:
            st.markdown(
                f"**Max height:** {height_m} m"
            )
        with col3:
            st.markdown(
                f"**Capacity:** {cap:.0f} m³"
            )
    else:
        st.warning(
            "Tank dimensions not set. "
            "Please update in System Setup."
        )
        return

    # Show last tank level reading
    session    = get_session()
    last_level = session.execute(sql_text(
        "SELECT level_m, volume_m3, pct_full, "
        "reading_date FROM tank_levels "
        "WHERE system_id = :sid "
        "AND asset_id = :aid "
        "ORDER BY reading_date DESC LIMIT 1"
    ), {"sid": system_id,
        "aid": selected_tank.id}).fetchone()
    session.close()

    if last_level:
        st.info(
            f"Last dip — "
            f"Level: **{last_level[0]} m** | "
            f"Volume: **{last_level[1]} m³** | "
            f"Full: **{last_level[2]}%** | "
            f"Date: **{str(last_level[3])[:10]}**"
        )

    with st.form("tank_level_form"):
        level_input = st.number_input(
            f"Current water level (metres) * "
            f"[0 – {height_m} m]",
            min_value=0.0,
            max_value=float(height_m),
            value=float(height_m) / 2,
            step=0.05,
            format="%.2f",
            help="Read directly from the level gauge "
                 "on the tank wall"
        )

        level_date = st.date_input(
            "Reading date *",
            value=datetime.now().date()
        )

        # Live preview
        volume, pct = calculate_volume(
            selected_tank, level_input
        )
        st.markdown(
            f"<div style='background:#eff6ff;"
            f"border-radius:8px;padding:10px 16px;"
            f"margin:8px 0;font-size:13px'>"
            f"<b>Preview:</b> "
            f"{level_input:.2f} m → "
            f"<b>{volume:.1f} m³</b> "
            f"({pct:.1f}% full)</div>",
            unsafe_allow_html=True
        )

        submitted = st.form_submit_button(
            "✓ Save tank level",
            use_container_width=True,
            type="primary"
        )

        if submitted:
            if level_input < 0:
                st.error("Level cannot be negative.")
            else:
                vol, pct_full = calculate_volume(
                    selected_tank, level_input
                )
                session = get_session()
                session.execute(sql_text("""
                    INSERT INTO tank_levels
                        (system_id, asset_id,
                         reading_date, level_m,
                         volume_m3, pct_full)
                    VALUES
                        (:sid, :aid, :rdate,
                         :level, :volume, :pct)
                """), {
                    "sid":    system_id,
                    "aid":    selected_tank.id,
                    "rdate":  datetime.combine(
                        level_date,
                        datetime.min.time()
                    ).replace(tzinfo=timezone.utc),
                    "level":  level_input,
                    "volume": vol,
                    "pct":    pct_full
                })
                session.commit()
                session.close()

                st.success(
                    f"✓ Tank level saved — "
                    f"{level_input:.2f} m = "
                    f"{vol:.1f} m³ "
                    f"({pct_full:.1f}% full)"
                )
                st.rerun()

    # ── Tank level history chart ───────────────────────
    st.divider()
    st.markdown("### Tank level history")

    session = get_session()
    levels  = session.execute(sql_text(
        "SELECT reading_date, level_m, "
        "volume_m3, pct_full "
        "FROM tank_levels "
        "WHERE system_id = :sid "
        "AND asset_id = :aid "
        "ORDER BY reading_date"
    ), {"sid": system_id,
        "aid": selected_tank.id}).fetchall()
    session.close()

    if levels:
        dates    = [str(l[0])[:10] for l in levels]
        volumes  = [l[2] for l in levels]
        pcts     = [l[3] for l in levels]
        capacity = cap or 48

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            name      = "Volume (m³)",
            x         = dates,
            y         = volumes,
            mode      = "lines+markers",
            line      = dict(color="#3b82f6",
                             width=2.5),
            marker    = dict(size=8),
            fill      = "tozeroy",
            fillcolor = "rgba(59,130,246,0.1)"
        ))
        fig.add_hline(
            y                   = capacity,
            line_dash           = "dash",
            line_color          = "#22c55e",
            annotation_text     = f"Full ({capacity} m³)",
            annotation_position = "top right"
        )
        fig.add_hline(
            y                   = capacity * 0.2,
            line_dash           = "dash",
            line_color          = "#ef4444",
            annotation_text     = "20% warning",
            annotation_position = "bottom right"
        )
        fig.update_layout(
            height        = 300,
            margin        = dict(t=20, b=10,
                                  l=0, r=0),
            plot_bgcolor  = "white",
            paper_bgcolor = "white",
            yaxis         = dict(
                title     = "Volume (m³)",
                range     = [0, capacity * 1.1],
                gridcolor = "#f1f5f9"
            ),
            xaxis = dict(gridcolor="#f1f5f9")
        )
        st.plotly_chart(fig, use_container_width=True)

        # History table
        rows = [{
            "Date":     d,
            "Level m":  f"{l[1]:.2f}",
            "Volume m³": f"{l[2]:.1f}",
            "% Full":   f"{l[3]:.1f}%"
        } for d, l in zip(dates, levels)]
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info(
            "No tank level readings yet. "
            "Record the first reading above."
        )
