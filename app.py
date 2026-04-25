import streamlit as st
from core.database import get_session, WaterSystem
from core.auth import (
    login, get_accessible_systems,
    is_super_admin, is_system_admin
)


# ── Page config ────────────────────────────────────────
st.set_page_config(
    page_title            = "Maji360",
    page_icon             = "💧",
    layout                = "wide",
    initial_sidebar_state = "expanded"
)

# ── Global CSS ─────────────────────────────────────────
st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    [data-testid="stSidebar"] {
        background: #0a1628;
        min-width: 240px;
    }
    [data-testid="stSidebar"] * {
        color: #e2e8f0 !important;
    }
    [data-testid="stSidebar"] .stButton button {
        background: transparent;
        border: none;
        color: #94a3b8 !important;
        text-align: left;
        padding: 8px 12px;
        font-size: 14px;
        width: 100%;
        border-radius: 6px;
        margin: 1px 0;
    }
    [data-testid="stSidebar"] .stButton button:hover {
        background: rgba(14,165,233,0.15) !important;
        color: #0ea5e9 !important;
    }
    [data-testid="stSidebar"] .stSelectbox label {
        color: #94a3b8 !important;
        font-size: 12px;
    }

    /* Mobile top nav bar */
    .mobile-topnav {
        display: none;
    }
    @media (max-width: 768px) {
        .mobile-topnav {
            display: block;
            background: #0a1628;
            padding: 10px 12px;
            border-radius: 10px;
            margin-bottom: 16px;
        }
        .mobile-topnav .nav-title {
            color: #0ea5e9;
            font-size: 18px;
            font-weight: 700;
            margin-bottom: 4px;
        }
        .mobile-topnav .nav-user {
            color: #94a3b8;
            font-size: 12px;
            margin-bottom: 8px;
        }
        .main .block-container {
            padding-top: 1rem !important;
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
        }
    }

    .alert-banner {
        background: #fef2f2;
        border-left: 4px solid #ef4444;
        padding: 10px 16px;
        border-radius: 4px;
        margin-bottom: 12px;
        color: #991b1b;
        font-size: 14px;
    }
    .warn-banner {
        background: #fffbeb;
        border-left: 4px solid #f59e0b;
        padding: 10px 16px;
        border-radius: 4px;
        margin-bottom: 12px;
        color: #92400e;
        font-size: 14px;
    }
    .ok-banner {
        background: #f0fdf4;
        border-left: 4px solid #22c55e;
        padding: 10px 16px;
        border-radius: 4px;
        margin-bottom: 12px;
        color: #166534;
        font-size: 14px;
    }
</style>
<link rel="manifest" href="https://raw.githubusercontent.com/EnockObwon/maji360/main/manifest.json">
<meta name="theme-color" content="#0ea5e9">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Maji360">
<link rel="apple-touch-icon" href="https://raw.githubusercontent.com/EnockObwon/maji360/main/static/icon-192.png">
""", unsafe_allow_html=True)


def show_login():
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("""
        <div style='text-align:center;
                    padding:3rem 0 2rem'>
            <div style='font-family:"Space Mono",
                        monospace;font-size:36px;
                        font-weight:700;
                        color:#0ea5e9;
                        letter-spacing:-1px'>
                Maji360
            </div>
            <div style='font-size:13px;
                        color:#64748b;
                        text-transform:uppercase;
                        letter-spacing:0.1em;
                        margin-top:4px'>
                Rural Water Management Platform
            </div>
        </div>
        """, unsafe_allow_html=True)

        tab_login, tab_register = st.tabs([
            "Sign in", "Request access"
        ])

        with tab_login:
            with st.form("login_form"):
                st.markdown(
                    "#### Sign in to your account"
                )
                email    = st.text_input(
                    "Email address"
                )
                password = st.text_input(
                    "Password", type="password"
                )
                submit   = st.form_submit_button(
                    "Sign in →",
                    use_container_width=True
                )

                if submit:
                    if not email or not password:
                        st.error(
                            "Please enter your "
                            "email and password."
                        )
                    else:
                        result = login(
                            email.strip(), password
                        )
                        if result == "pending":
                            st.warning(
                                "Your account is "
                                "pending approval."
                            )
                        elif result:
                            st.session_state[
                                "user"
                            ] = result
                            st.session_state[
                                "page"
                            ] = "Home"
                            st.rerun()
                        else:
                            st.error(
                                "Invalid email "
                                "or password."
                            )

        with tab_register:
            st.markdown(
                "#### Request viewer access"
            )
            with st.form("register_form"):
                reg_name  = st.text_input(
                    "Full name *"
                )
                reg_email = st.text_input(
                    "Email address *"
                )
                reg_pass  = st.text_input(
                    "Password *", type="password"
                )
                reg_pass2 = st.text_input(
                    "Confirm password *",
                    type="password"
                )

                session  = get_session()
                systems  = session.query(
                    WaterSystem
                ).filter_by(is_active=True).all()
                sys_opts = {
                    "Select a water system": None
                }
                for s in systems:
                    sys_opts[s.name] = s.id
                session.close()

                reg_system = st.selectbox(
                    "Water system *",
                    options=list(sys_opts.keys())
                )
                reg_reason = st.text_area(
                    "Why do you need access?",
                    placeholder=(
                        "e.g. Water Board member, "
                        "donor, government monitor..."
                    ),
                    height=80
                )

                reg_submit = st.form_submit_button(
                    "Request access →",
                    use_container_width=True
                )

                if reg_submit:
                    if not reg_name or \
                       not reg_email or \
                       not reg_pass:
                        st.error(
                            "Please fill in all "
                            "required fields."
                        )
                    elif reg_pass != reg_pass2:
                        st.error(
                            "Passwords do not match."
                        )
                    elif sys_opts.get(
                        reg_system
                    ) is None:
                        st.error(
                            "Please select a "
                            "water system."
                        )
                    else:
                        from core.auth import \
                            register_viewer
                        result = register_viewer(
                            name      = reg_name,
                            email     = reg_email,
                            password  = reg_pass,
                            system_id = sys_opts[
                                reg_system
                            ]
                        )
                        if result["success"]:
                            st.success(
                                result["message"]
                            )
                        else:
                            st.error(
                                result["message"]
                            )

        st.markdown(
            "<div style='text-align:center;"
            "margin-top:2rem;font-size:12px;"
            "color:#94a3b8'>"
            "Maji360 v1.5.0 · Sub-Saharan Africa"
            "</div>",
            unsafe_allow_html=True
        )


def show_mobile_nav(current_page: str,
                     user: dict,
                     systems: list):
    """
    Mobile navigation rendered inside main
    content area — always visible regardless
    of sidebar state.
    """
    role = user.get("role", "viewer")

    pages = {
        "🏠 Home":              "Home",
        "📉 NRW Report":        "NRW",
        "💰 Billing":           "Billing",
        "📊 Financial":         "Financial",
        "📄 Reports":           "Reports",
        "⚙️ Operations":        "Operations",
        "📋 Field Ops":         "FieldOps",
        "💵 Customer Billing":  "CustomerBilling",
        "🔧 Maintenance":       "Maintenance",
        "🗺️ Map":               "Map",
        "🔄 Sync":              "Sync",
    }
    if role in ["super_admin", "system_admin"]:
        pages["🔩 System Setup"] = "SystemSetup"
    if role == "super_admin":
        pages["👑 Admin"] = "Admin"

    st.markdown(
        f"<div class='mobile-topnav'>"
        f"<div class='nav-title'>💧 Maji360</div>"
        f"<div class='nav-user'>"
        f"{user.get('name','')} · "
        f"{role.replace('_',' ').title()}"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True
    )

    # System selector on mobile
    if len(systems) > 1:
        sys_names = [s["name"] for s in systems]
        current   = st.session_state.get(
            "selected_system_name", sys_names[0]
        )
        idx = sys_names.index(current) \
              if current in sys_names else 0
        chosen = st.selectbox(
            "System",
            options=sys_names,
            index=idx,
            key="mobile_sys_select"
        )
        selected = next(
            s for s in systems
            if s["name"] == chosen
        )
        st.session_state[
            "selected_system_id"
        ]   = selected["id"]
        st.session_state[
            "selected_system_name"
        ] = selected["name"]
        st.session_state[
            "currency"
        ] = selected.get("currency", "UGX")

    # Page selector as dropdown
    page_labels  = list(pages.keys())
    page_keys    = list(pages.values())
    current_idx  = page_keys.index(current_page) \
                   if current_page in page_keys \
                   else 0

    selected_label = st.selectbox(
        "Navigate to",
        options=page_labels,
        index=current_idx,
        key="mobile_page_select"
    )
    selected_page = pages[selected_label]

    if selected_page != current_page:
        st.session_state["page"] = selected_page
        st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(
            f"<div style='font-size:12px;"
            f"color:#64748b;padding:4px 0'>"
            f"📍 {st.session_state.get('selected_system_name','')}"
            f"</div>",
            unsafe_allow_html=True
        )
    with col2:
        if st.button(
            "Sign out",
            key="mobile_signout",
            use_container_width=True
        ):
            st.session_state.clear()
            st.rerun()

    st.divider()


def show_sidebar():
    user = st.session_state.get("user", {})
    if not user:
        return None

    with st.sidebar:
        st.markdown(
            f"<div style='padding:12px 0 8px'>"
            f"<span style='font-size:20px;"
            f"font-weight:700;color:#0ea5e9'>"
            f"Maji360</span><br>"
            f"<span style='font-size:12px;"
            f"color:#94a3b8'>"
            f"{user.get('name', '')}</span><br>"
            f"<span style='font-size:11px;"
            f"color:#64748b'>"
            f"{user.get('role','').replace('_',' ').title()}"
            f"</span></div>",
            unsafe_allow_html=True
        )
        st.divider()

        systems = get_accessible_systems()

        if not systems:
            st.warning("No systems assigned.")
            return None, []

        if len(systems) == 1:
            selected = systems[0]
            st.markdown(
                f"<span style='font-size:12px;"
                f"color:#94a3b8'>System</span><br>"
                f"<span style='font-size:13px;"
                f"font-weight:600'>"
                f"{selected['name']}</span>",
                unsafe_allow_html=True
            )
        else:
            sys_names = [s["name"] for s in systems]
            current   = st.session_state.get(
                "selected_system_name", sys_names[0]
            )
            idx = sys_names.index(current) \
                  if current in sys_names else 0
            chosen = st.selectbox(
                "Water system",
                options=sys_names,
                index=idx
            )
            selected = next(
                s for s in systems
                if s["name"] == chosen
            )

        st.session_state["selected_system_id"]   = \
            selected["id"]
        st.session_state["selected_system_name"] = \
            selected["name"]
        st.session_state["currency"]             = \
            selected.get("currency", "UGX")

        st.divider()

        pages = {
            "🏠  Home":             "Home",
            "📉  NRW Report":       "NRW",
            "💰  Billing":          "Billing",
            "📊  Financial":        "Financial",
            "📄  Reports":          "Reports",
            "⚙️  Operations":       "Operations",
            "📋  Field Ops":        "FieldOps",
            "💵  Customer Billing": "CustomerBilling",
            "🔧  Maintenance":      "Maintenance",
            "🗺️  Map":              "Map",
            "🔄  Sync":             "Sync",
        }

        if user.get("role") in [
            "super_admin", "system_admin"
        ]:
            pages["🔩  System Setup"] = "SystemSetup"

        if user.get("role") == "super_admin":
            pages["👑  Admin"] = "Admin"

        current_page = st.session_state.get(
            "page", "Home"
        )

        for label, page_key in pages.items():
            if st.button(
                label,
                key=f"nav_{page_key}",
                use_container_width=True
            ):
                st.session_state["page"] = page_key
                st.rerun()

        st.divider()
        if st.button(
            "Sign out",
            use_container_width=True
        ):
            st.session_state.clear()
            st.rerun()

        return current_page, systems


# ── Main app ───────────────────────────────────────────
if "user" not in st.session_state:
    show_login()
else:
    user           = st.session_state.get("user", {})
    sidebar_result = show_sidebar()

    if sidebar_result is None:
        st.stop()

    page, systems = sidebar_result

    if not page:
        page = "Home"

    # Mobile navigation — always rendered in
    # main content, visible when sidebar is hidden
    show_mobile_nav(page, user, systems)

    if page == "Home":
        from pages.home import show
        show()
    elif page == "NRW":
        from pages.nrw_report import show
        show()
    elif page == "Billing":
        from pages.billing import show
        show()
    elif page == "Financial":
        from pages.financial import show
        show()
    elif page == "Reports":
        from pages.reports import show
        show()
    elif page == "Operations":
        from pages.operations import show
        show()
    elif page == "FieldOps":
        from pages.field_ops import show
        show()
    elif page == "CustomerBilling":
        from pages.customer_billing import show
        show()
    elif page == "Maintenance":
        from pages.maintenance import show
        show()
    elif page == "Map":
        from pages.map_view import show
        show()
    elif page == "Sync":
        from pages.sync import show
        show()
    elif page == "SystemSetup":
        from pages.system_setup import show
        show()
    elif page == "Admin":
        from pages.admin import show
        show()
