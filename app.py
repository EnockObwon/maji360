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
    /* Hide streamlit default elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* Sidebar styling — desktop and mobile */
    [data-testid="stSidebar"] {
        background: #0a1628 !important;
        min-width: 240px !important;
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
        font-size: 15px;
        width: 100%;
        border-radius: 6px;
        margin: 2px 0;
    }
    [data-testid="stSidebar"] .stButton button:hover {
        background: rgba(14,165,233,0.15) !important;
        color: #0ea5e9 !important;
    }

    /* Hamburger button — large and always visible */
    [data-testid="collapsedControl"] {
        display: flex !important;
        visibility: visible !important;
        opacity: 1 !important;
        position: fixed !important;
        top: 10px !important;
        left: 10px !important;
        width: 48px !important;
        height: 48px !important;
        background: #0a1628 !important;
        border-radius: 10px !important;
        align-items: center !important;
        justify-content: center !important;
        z-index: 99999 !important;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3) !important;
        cursor: pointer !important;
    }
    [data-testid="collapsedControl"] svg {
        fill: #0ea5e9 !important;
        width: 26px !important;
        height: 26px !important;
    }

    /* Mobile specific */
    @media (max-width: 768px) {
        [data-testid="stSidebar"] {
            width: 85vw !important;
            min-width: 260px !important;
        }
        [data-testid="stSidebar"] .stButton button {
            font-size: 16px !important;
            padding: 12px 16px !important;
            margin: 3px 0 !important;
            min-height: 48px !important;
        }
        .main .block-container {
            padding-top: 4rem !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }
    }

    /* Alert banners */
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

<script>
    // Force sidebar to stay visible on mobile
    // by periodically checking and expanding it
    function forceSidebar() {
        try {
            const sidebar = window.parent.document
                .querySelector(
                    '[data-testid="stSidebar"]'
                );
            const collapsed = window.parent.document
                .querySelector(
                    '[data-testid="collapsedControl"]'
                );
            if (sidebar) {
                sidebar.style.display = 'flex';
                sidebar.style.visibility = 'visible';
                sidebar.style.opacity = '1';
                sidebar.style.transform = 'none';
                sidebar.style.width = '260px';
                sidebar.style.minWidth = '240px';
            }
            if (collapsed) {
                collapsed.style.display = 'flex';
                collapsed.style.visibility = 'visible';
                collapsed.style.opacity = '1';
            }
        } catch(e) {}
    }
    // Run immediately and every 500ms
    forceSidebar();
    setInterval(forceSidebar, 500);
</script>

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
                                "pending approval by "
                                "the administrator."
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
            st.markdown(
                "<span style='font-size:13px;"
                "color:#64748b'>Fill in your "
                "details. Your account will be "
                "reviewed and activated by the "
                "administrator.</span>",
                unsafe_allow_html=True
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
                    "Water system of interest *",
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

        # ── System selector ────────────────────────
        systems = get_accessible_systems()

        if not systems:
            st.warning("No systems assigned.")
            return None

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

        # ── Navigation ─────────────────────────────
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

        return current_page


# ── Main app ───────────────────────────────────────────
if "user" not in st.session_state:
    show_login()
else:
    page = show_sidebar()

    if page == "Home" or page is None:
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
