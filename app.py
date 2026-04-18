import streamlit as st
from core.auth import login, get_accessible_systems
from core.database import get_session, User, WaterSystem
from core.auth import hash_password

st.set_page_config(
    page_title="Maji360",
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=Space+Mono:wght@400;700&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
section[data-testid="stSidebar"] { background: #0a1628; border-right: 1px solid #1e3a5f; }
section[data-testid="stSidebar"] * { color: #e2e8f0 !important; }
div[data-testid="metric-container"] { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 1rem 1.25rem; }
div[data-testid="metric-container"] label { font-size: 12px !important; color: #64748b !important; text-transform: uppercase; letter-spacing: 0.06em; }
div[data-testid="metric-container"] [data-testid="stMetricValue"] { font-family: 'Space Mono', monospace !important; font-size: 24px !important; color: #0f172a !important; }
h1 { font-weight: 600; color: #0f172a; }
h2 { font-weight: 500; color: #1e293b; }
.alert-banner { background: #fef2f2; border-left: 4px solid #ef4444; border-radius: 0 8px 8px 0; padding: 12px 16px; margin: 8px 0; font-size: 14px; color: #991b1b; }
.warn-banner { background: #fffbeb; border-left: 4px solid #f59e0b; border-radius: 0 8px 8px 0; padding: 12px 16px; margin: 8px 0; font-size: 14px; color: #92400e; }
.ok-banner { background: #f0fdf4; border-left: 4px solid #22c55e; border-radius: 0 8px 8px 0; padding: 12px 16px; margin: 8px 0; font-size: 14px; color: #166534; }
.maji-logo { font-family: 'Space Mono', monospace; font-size: 22px; font-weight: 700; color: #38bdf8 !important; letter-spacing: -0.5px; padding: 8px 0 4px; }
.maji-tagline { font-size: 11px; color: #64748b !important; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 24px; }
</style>
""", unsafe_allow_html=True)

def seed_admin():
    """Create super admin on first run if not exists."""
    try:
        session = get_session()
        admin_email = st.secrets.get("ADMIN_EMAIL", "admin@maji360.co")
        existing = session.query(User).filter_by(email=admin_email).first()
        if not existing:
            admin_pass = st.secrets.get("ADMIN_PASSWORD", "maji360admin")
            system = WaterSystem(
                name="Karungu Water Supply System",
                district="Kiryandongo",
                country="Uganda",
                currency="UGX",
                tariff_per_m3=2500.0,
                mwater_form_id="8436611dd18844a89c000e175dabc299",
                latitude=2.004673,
                longitude=32.120436,
                is_active=True
            )
            session.add(system)
            session.flush()
            admin = User(
                name="Super Admin",
                email=admin_email,
                role="super_admin",
                password=hash_password(admin_pass),
                system_id=None,
                is_active=True
            )
            session.add(admin)
            session.commit()
        session.close()
    except Exception as e:
        pass

def show_login():
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("""
        <div style='text-align:center; padding: 3rem 0 2rem;'>
            <div style='font-family:"Space Mono",monospace; font-size:36px; font-weight:700; color:#0ea5e9; letter-spacing:-1px;'>Maji360</div>
            <div style='font-size:13px; color:#64748b; text-transform:uppercase; letter-spacing:0.1em; margin-top:4px;'>Rural Water Management Platform</div>
        </div>
        """, unsafe_allow_html=True)
        with st.form("login_form"):
            st.markdown("#### Sign in to your account")
            email    = st.text_input("Email address")
            password = st.text_input("Password", type="password")
            submit   = st.form_submit_button("Sign in →", use_container_width=True)
            if submit:
                if not email or not password:
                    st.error("Please enter your email and password.")
                else:
                    user = login(email.strip(), password)
                    if user:
                        st.session_state["user"] = user
                        st.rerun()
                    else:
                        st.error("Invalid email or password.")
        st.markdown("<div style='text-align:center; margin-top:2rem; font-size:12px; color:#94a3b8;'>Maji360 v1.0 · Sub-Saharan Africa</div>", unsafe_allow_html=True)

def show_sidebar():
    user = st.session_state.get("user", {})
    with st.sidebar:
        st.markdown('<div class="maji-logo">Maji360</div>', unsafe_allow_html=True)
        st.markdown('<div class="maji-tagline">Water Management Platform</div>', unsafe_allow_html=True)
        if user.get("role") == "super_admin":
            systems = get_accessible_systems()
            system_names = {s["name"]: s["id"] for s in systems}
            selected = st.selectbox("Active system", options=list(system_names.keys()), key="system_selector")
            st.session_state["selected_system_id"]   = system_names.get(selected)
            st.session_state["selected_system_name"] = selected
            currency = next((s["currency"] for s in systems if s["name"] == selected), "UGX")
            st.session_state["currency"] = currency
        else:
            session = get_session()
            system  = session.query(WaterSystem).filter_by(id=user.get("system_id")).first()
            session.close()
            if system:
                st.markdown(f"**{system.name}**")
                st.session_state["selected_system_id"]   = system.id
                st.session_state["selected_system_name"] = system.name
                st.session_state["currency"]             = system.currency
        st.divider()
        st.markdown("**Navigation**")
        pages = {"🏠  Home": "Home", "📉  NRW Report": "NRW", "💰  Billing": "Billing", "⚙️  Operations": "Operations", "🗺️  Map": "Map", "🔄  Sync": "Sync"}
        if user.get("role") == "super_admin":
            pages["🔧  Admin"] = "Admin"
        for label in pages:
            if st.button(label, use_container_width=True, key=f"nav_{label}"):
                st.session_state["page"] = pages[label]
                st.rerun()
        st.divider()
        st.markdown(f"**{user.get('name', 'User')}**  \n<span style='font-size:12px;color:#94a3b8'>{user.get('role','').replace('_',' ').title()}</span>", unsafe_allow_html=True)
        if st.button("Sign out", use_container_width=True):
            st.session_state.clear()
            st.rerun()

seed_admin()

if "user" not in st.session_state:
    show_login()
else:
    show_sidebar()
    page = st.session_state.get("page", "Home")
    if page == "Home":
        from pages.home import show
        show()
    elif page == "NRW":
        from pages.nrw_report import show
        show()
    elif page == "Billing":
        from pages.billing import show
        show()
    elif page == "Operations":
        from pages.operations import show
        show()
    elif page == "Map":
        from pages.map_view import show
        show()
    elif page == "Admin":
        from pages.admin import show
        show()
    elif page == "Sync":
        from pages.sync import show
        show()
