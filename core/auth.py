import bcrypt
import streamlit as st
from core.database import get_session, User, WaterSystem
from sqlalchemy import text as sql_text


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(
        plain.encode(), bcrypt.gensalt()
    ).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain.encode(), hashed.encode()
        )
    except Exception:
        return False


def get_user_accessible_systems(user_id: int) -> list:
    """
    Get all systems a user can access
    from user_systems table.
    """
    session = get_session()
    try:
        rows = session.execute(sql_text("""
            SELECT ws.id, ws.name, ws.currency
            FROM user_systems us
            JOIN water_systems ws
                ON us.system_id = ws.id
            WHERE us.user_id = :uid
            AND ws.is_active = true
            ORDER BY ws.name
        """), {"uid": user_id}).fetchall()
        result = [
            {
                "id":       row[0],
                "name":     row[1],
                "currency": row[2]
            }
            for row in rows
        ]
    except Exception:
        result = []
    session.close()
    return result


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

    is_approved = getattr(user, 'is_approved', True)
    if not is_approved:
        session.close()
        return "pending"

    # Get accessible systems
    user_id  = user.id
    role     = user.role
    name     = user.name
    email_   = user.email
    sys_id   = user.system_id
    sys_name = user.system.name \
               if user.system else "All Systems"
    session.close()

    accessible = get_user_accessible_systems(user_id)

    result = {
        "id":          user_id,
        "name":        name,
        "email":       email_,
        "role":        role,
        "system_id":   sys_id,
        "system_name": sys_name,
        "systems":     accessible
    }
    return result


def register_viewer(name: str, email: str,
                    password: str,
                    system_id: int = None) -> dict:
    session  = get_session()
    existing = session.query(User).filter_by(
        email=email
    ).first()
    if existing:
        session.close()
        return {
            "success": False,
            "message": "An account with this email "
                       "already exists."
        }

    try:
        user = User(
            name        = name,
            email       = email,
            role        = "viewer",
            password    = hash_password(password),
            system_id   = system_id,
            is_active   = True,
            is_approved = False
        )
        session.add(user)
        session.commit()

        # Add to user_systems table
        if system_id:
            try:
                session.execute(sql_text("""
                    INSERT INTO user_systems
                        (user_id, system_id)
                    VALUES (:uid, :sid)
                    ON CONFLICT DO NOTHING
                """), {
                    "uid": user.id,
                    "sid": system_id
                })
                session.commit()
            except Exception:
                pass

        session.close()
        return {
            "success": True,
            "message": "Registration successful. "
                       "Your account is pending "
                       "approval by the administrator."
        }
    except Exception as e:
        session.close()
        return {
            "success": False,
            "message": f"Registration failed: {e}"
        }


def require_login():
    if "user" not in st.session_state:
        st.warning("Please log in to continue.")
        st.stop()


def is_super_admin() -> bool:
    return st.session_state.get(
        "user", {}
    ).get("role") == "super_admin"


def is_system_admin() -> bool:
    return st.session_state.get(
        "user", {}
    ).get("role") in [
        "super_admin", "system_admin"
    ]


def is_operator() -> bool:
    return st.session_state.get(
        "user", {}
    ).get("role") in [
        "super_admin", "system_admin", "operator"
    ]


def get_user_system_id():
    user = st.session_state.get("user", {})
    if user.get("role") == "super_admin":
        return st.session_state.get(
            "selected_system_id"
        )
    return user.get("system_id")


def get_accessible_systems() -> list:
    user    = st.session_state.get("user", {})
    session = get_session()
    if user.get("role") == "super_admin":
        systems = session.query(WaterSystem).filter_by(
            is_active=True
        ).all()
        result = [
            {
                "id":       s.id,
                "name":     s.name,
                "currency": s.currency
            }
            for s in systems
        ]
    else:
        result = get_user_accessible_systems(
            user.get("id")
        )
    session.close()
    return result
