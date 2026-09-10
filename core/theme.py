"""
core/theme.py — shared dark theme for Maji360.

Extends the existing sidebar dark navy (#0a1628) + sky blue accent
(#0ea5e9) — already established in app.py — across the whole app,
instead of only the sidebar. Nothing here invents a new palette;
it's the same two colors already in use, applied consistently.

Usage:
    from core.theme import apply_theme, metric_card, style_dark_chart

    apply_theme()                      # once, in app.py
    st.markdown(metric_card(...), unsafe_allow_html=True)   # per KPI
    fig = style_dark_chart(fig)        # before st.plotly_chart(fig)
"""

import streamlit as st

# Palette — matches app.py's existing sidebar exactly, extended with
# a couple of tints needed for cards/banners on a dark background.
BG_PAGE     = "#0a1628"   # matches existing sidebar bg
BG_CARD     = "#111c33"   # one step lighter — card/panel surfaces
BG_CARD_ALT = "#0f1e35"
BORDER      = "#1e293b"
ACCENT      = "#0ea5e9"   # existing brand sky blue — unchanged
TEXT_PRI    = "#f1f5f9"
TEXT_SEC    = "#94a3b8"
TEXT_MUTED  = "#64748b"
SUCCESS     = "#22c55e"
WARNING     = "#f59e0b"
DANGER      = "#ef4444"


def apply_theme():
    """Inject CSS for the parts Streamlit's own theme engine can't
    reach: the custom banner classes (alert/warn/ok) used by pages
    like Home, which are project-specific and unknown to Streamlit.

    Native widgets — selectboxes, buttons, inputs, tabs, sliders —
    are themed by .streamlit/config.toml instead of CSS overrides
    here. That file is what Streamlit's own rendering respects
    reliably; guessing at BaseWeb's internal DOM structure via
    injected CSS (an earlier version of this function did that) is
    fragile and is exactly what left the mobile nav's "System"/"Home"
    dropdowns and "Sign out" button rendering white against the dark
    background — Streamlit's internal markup for those controls
    didn't match the selectors being overridden. Trust config.toml
    for anything Streamlit renders itself; only add CSS here for
    things this project defines that Streamlit has no theme concept
    of at all.
    """
    st.markdown(f"""
    <style>
        h1, h2, h3, h4, h5, h6, .main p, .main label, .main span {{
            color: {TEXT_PRI} !important;
        }}
        .main .stCaption, [data-testid="stCaptionContainer"] {{
            color: {TEXT_MUTED} !important;
        }}
        hr {{
            border-color: {BORDER} !important;
        }}

        /* Banners — dark-tinted instead of light pastel. Custom
           classes with no Streamlit-native equivalent. */
        .alert-banner {{
            background    : #2a1414;
            border-left   : 4px solid {DANGER};
            padding       : 10px 16px;
            border-radius : 4px;
            margin-bottom : 12px;
            color         : #fca5a5;
            font-size     : 14px;
        }}
        .warn-banner {{
            background    : #2a230f;
            border-left   : 4px solid {WARNING};
            padding       : 10px 16px;
            border-radius : 4px;
            margin-bottom : 12px;
            color         : #fcd34d;
            font-size     : 14px;
        }}
        .ok-banner {{
            background    : #0d2b1f;
            border-left   : 4px solid {SUCCESS};
            padding       : 10px 16px;
            border-radius : 4px;
            margin-bottom : 12px;
            color         : #86efac;
            font-size     : 14px;
        }}

        /* Light, testid-based touches only — these attributes are
           stable Streamlit test hooks, not guessed internal markup,
           so they're safe to rely on unlike the form-control
           overrides removed above. */
        [data-testid="stMetric"] {{
            background    : {BG_CARD};
            border-radius : 8px;
            padding       : 14px 16px;
        }}
        [data-testid="stDataFrame"], [data-testid="stTable"] {{
            background : {BG_CARD};
        }}
    </style>
    """, unsafe_allow_html=True)


def metric_card(label: str, value: str, delta: str | None = None,
                 delta_positive: bool = True, accent: str = ACCENT,
                 delta_neutral: bool = False) -> str:
    """Return HTML for one KPI tile — pass to st.markdown(..., unsafe_allow_html=True).

    Replaces st.metric() with a card matching the rest of the theme:
    thin colored top-accent, muted label, bold value, optional
    up/down delta. `accent` lets each KPI carry its own category
    color (e.g. green for Collected, blue for Total billed) the way
    st.metric never could.

    `delta_neutral=True` shows the delta in plain muted text with no
    arrow or color judgment — matches st.metric(delta_color="off"),
    for values where a change isn't inherently good or bad (e.g.
    "Total billed" going up isn't automatically positive or negative).
    """
    delta_html = ""
    if delta:
        if delta_neutral:
            delta_html = (
                f'<div style="font-size:12px; color:{TEXT_SEC}; margin-top:6px;">'
                f'{delta}</div>'
            )
        else:
            color = SUCCESS if delta_positive else DANGER
            arrow = "&#9650;" if delta_positive else "&#9660;"  # ▲ / ▼
            delta_html = (
                f'<div style="font-size:12px; color:{color}; margin-top:6px;">'
                f'{arrow} {delta}</div>'
            )
    return f"""
    <div style="background:{BG_CARD}; border-radius:8px;
                border-top:3px solid {accent}; padding:14px 16px;
                margin-bottom:12px;">
        <div style="font-size:12px; color:{TEXT_SEC}; margin-bottom:6px;">{label}</div>
        <div style="font-size:26px; font-weight:500; color:{TEXT_PRI};">{value}</div>
        {delta_html}
    </div>
    """


# Shared Plotly layout overrides — apply to every chart so they're
# visually consistent across pages, e.g.:
#   fig.update_layout(**PLOTLY_DARK_LAYOUT)
PLOTLY_DARK_LAYOUT = dict(
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    font=dict(color=TEXT_SEC, size=12),
    xaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER, color=TEXT_SEC),
    yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER, color=TEXT_SEC),
    legend=dict(font=dict(color=TEXT_SEC)),
)


def style_dark_chart(fig):
    """Apply the shared dark layout to a Plotly figure, preserving
    any axis config the figure already set (merges rather than
    overwrites xaxis/yaxis so existing per-chart settings like
    showgrid=False or a custom range survive).

    Also reaches a secondary y-axis (yaxis2) if the figure has one —
    e.g. a dual-axis combo chart with volume bars on the left axis
    and a %-based line on the right. fig.update_yaxes() alone only
    touches the primary axis; secondary_y=True is required for the
    second one, and calling it on a figure that has no secondary
    axis is a harmless no-op, so this is safe on every chart.
    """
    fig.update_layout(
        plot_bgcolor=PLOTLY_DARK_LAYOUT["plot_bgcolor"],
        paper_bgcolor=PLOTLY_DARK_LAYOUT["paper_bgcolor"],
        font=PLOTLY_DARK_LAYOUT["font"],
        legend=dict(font=dict(color=TEXT_SEC)),
    )
    fig.update_xaxes(gridcolor=BORDER, zerolinecolor=BORDER, color=TEXT_SEC)
    fig.update_yaxes(gridcolor=BORDER, zerolinecolor=BORDER, color=TEXT_SEC)
    try:
        fig.update_yaxes(gridcolor=BORDER, zerolinecolor=BORDER, color=TEXT_SEC, secondary_y=True)
    except Exception:
        pass  # figure has no secondary axis — nothing to do
    return fig


def nrw_gauge(value: float, target: float = 20.0, prev_value: float | None = None):
    """Build a real Plotly gauge for NRW%, styled for the dark theme.

    Returns a go.Figure — call st.plotly_chart(fig, use_container_width=True).
    """
    import plotly.graph_objects as go

    bar_color = DANGER if value >= target else SUCCESS
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=value,
        delta={
            "reference": prev_value,
            "increasing": {"color": DANGER},
            "decreasing": {"color": SUCCESS},
        } if prev_value is not None else {},
        number={"suffix": "%", "font": {"size": 34, "color": TEXT_PRI}},
        gauge={
            "axis": {
                "range": [0, 60], "tickwidth": 1,
                "tickcolor": TEXT_MUTED, "tickfont": {"color": TEXT_SEC},
                "tickvals": [0, 10, 20, 30, 40, 50, 60],
            },
            "bar": {"color": bar_color, "thickness": 0.25},
            "bgcolor": BG_CARD, "borderwidth": 0,
            "steps": [
                {"range": [0, 20],  "color": "#0d2b1f"},
                {"range": [20, 35], "color": "#2a230f"},
                {"range": [35, 60], "color": "#2a1414"},
            ],
            "threshold": {
                "line": {"color": WARNING, "width": 3},
                "thickness": 0.8, "value": target,
            },
        },
        title={"text": "NRW %", "font": {"size": 14, "color": TEXT_SEC}},
    ))
    fig.update_layout(
        height=260,
        margin=dict(t=20, b=10, l=40, r=40),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT_SEC),
    )
    return fig
