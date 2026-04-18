import bcrypt
import streamlit as st
from core.database import get_session, User, WaterSystem

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False

def login(email: str, password: str):
    session = get_session()
    user    = session.query(User).filter_by(
        email=email, is_active=True
    ).first()
    if not user:
        session.close()
        return None
    if not verify_password(password, user.password):
        session.close()
        return None
    result = {
        "id":          user.id,
        "name":        user.name,
        "email":       user.email,
        "role":        user.role,
        "system_id":   user.system_id,
        "system_name": user.system.name if user.system else "All Systems"
    }
    session.close()
    return result

def require_login():
    if "user" not in st.session_state:
        st.warning("Please log in to continue.")
        st.stop()

def is_super_admin() -> bool:
    return st.session_state.get("user", {}).get("role") == "super_admin"

def is_operator() -> bool:
    return st.session_state.get("user", {}).get("role") in [
        "super_admin", "system_admin", "operator"
    ]

def get_user_system_id():
    user = st.session_state.get("user", {})
    if user.get("role") == "super_admin":
        return st.session_state.get("selected_system_id")
    return user.get("system_id")

def get_accessible_systems() -> list:
    user    = st.session_state.get("user", {})
    session = get_session()
    if user.get("role") == "super_admin":
        systems = session.query(WaterSystem).filter_by(
            is_active=True
        ).all()
    else:
        systems = session.query(WaterSystem).filter_by(
            id=user.get("system_id"), is_active=True
        ).all()
    result = [{"id": s.id, "name": s.name,
               "currency": s.currency} for s in systems]
    session.close()
    return result
