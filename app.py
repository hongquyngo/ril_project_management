# app.py
"""
Rozitek Intralogistic Management App - Main Entry Point

Version: 2.0.0
"""

import streamlit as st
from utils.auth import AuthManager
from utils.db import check_db_connection
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== PAGE CONFIGURATION ====================

APP_NAME = "Rozitek Intralogistic Management"
APP_ICON = "🏭"
APP_VERSION = "2.0.0"

st.set_page_config(
    page_title=f"{APP_NAME}",
    page_icon=APP_ICON,
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== CUSTOM CSS ====================

st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        margin-bottom: 0.5rem;
        color: #1f77b4;
    }
    
    .sub-header {
        font-size: 1.1rem;
        color: #666;
        margin-bottom: 2rem;
    }
    
    .welcome-box {
        background: linear-gradient(135deg, #1f77b4 0%, #2196f3 100%);
        color: white;
        padding: 2rem;
        border-radius: 0.75rem;
        margin-bottom: 2rem;
    }
    
    .welcome-title {
        font-size: 1.75rem;
        font-weight: 600;
        margin-bottom: 0.5rem;
    }
    
    .welcome-subtitle {
        opacity: 0.9;
        font-size: 1rem;
    }
    
    .info-card {
        background: #f8f9fa;
        padding: 1.5rem;
        border-radius: 0.5rem;
        border-left: 4px solid #1f77b4;
        margin-bottom: 1rem;
    }
    
    .footer {
        text-align: center;
        color: #888;
        padding: 1rem;
        margin-top: 3rem;
        border-top: 1px solid #eee;
        font-size: 0.9rem;
    }
</style>
""", unsafe_allow_html=True)

# ==================== INITIALIZATION ====================

auth = AuthManager()

# ==================== HELPER FUNCTIONS ====================

def show_login_page():
    """Display the login page"""
    st.markdown(f'<p class="main-header">{APP_ICON} {APP_NAME}</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Intralogistic & Warehouse Operations Platform</p>', unsafe_allow_html=True)
    
    # Check database connection
    db_ok, db_error = check_db_connection()
    if not db_ok:
        st.error(f"⚠️ {db_error}")
        st.info("Please check your network connection or contact IT support.")
        return
    
    # Center the login form
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        with st.form("login_form", clear_on_submit=False):
            st.markdown("#### 🔐 Login")
            
            username = st.text_input(
                "Username",
                placeholder="Enter your username",
                key="login_username"
            )
            password = st.text_input(
                "Password",
                type="password",
                placeholder="Enter your password",
                key="login_password"
            )
            
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                submit = st.form_submit_button(
                    "🔑 Login",
                    type="primary",
                    use_container_width=True
                )
            with col_btn2:
                st.form_submit_button(
                    "🔄 Clear",
                    use_container_width=True
                )
            
            if submit:
                if not username or not password:
                    st.warning("Please enter both username and password")
                else:
                    with st.spinner("Authenticating..."):
                        success, result = auth.authenticate(username, password)
                    
                    if success:
                        auth.login(result)
                        st.success("✅ Login successful!")
                        st.balloons()
                        st.rerun()
                    else:
                        st.error(result.get("error", "Authentication failed"))
        
        with st.expander("ℹ️ Need Help?"):
            st.info("""
            - Use your BI credentials to login
            - Contact IT support if you forgot your password
            - Session expires after 8 hours of inactivity
            """)


def show_main_app():
    """Display the main application after login"""

    # ── Sidebar ──────────────────────────────────────────────
    with st.sidebar:
        st.markdown(f"### 👤 {auth.get_user_display_name()}")

        access_level = st.session_state.get('user_role', 'viewer')

        FULL_ACCESS_ROLES    = {'admin', 'GM', 'MD'}
        MANAGER_ROLES        = {'sales_manager', 'supply_chain_manager', 'inbound_manager',
                                'outbound_manager', 'warehouse_manager', 'fa_manager'}
        STAFF_ROLES          = {'sales', 'supply_chain', 'buyer', 'allocator', 'accountant'}
        LIMITED_ROLES        = {'viewer', 'customer', 'vendor'}

        if access_level in FULL_ACCESS_ROLES:
            st.success("🔓 Full Access")
        elif access_level in MANAGER_ROLES:
            st.info("👥 Manager Access")
        elif access_level in STAFF_ROLES:
            st.info("🧑‍💼 Staff Access")
        else:   # viewer / customer / vendor / unknown
            st.warning("👤 Limited Access")

        st.caption(f"Role: {access_level}")
        st.markdown("---")

        if st.button("🚪 Logout", use_container_width=True):
            auth.logout()
            st.rerun()

    # ── Welcome banner ────────────────────────────────────────
    st.markdown(f"""
    <div class="welcome-box">
        <div class="welcome-title">Welcome, {auth.get_user_display_name()}! 👋</div>
        <div class="welcome-subtitle">
            Rozitek Intralogistic Management — warehouse operations, logistics workflows, and inventory control.
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Quick-info cards ──────────────────────────────────────
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        <div class="info-card">
            <strong>📦 Inbound & Outbound</strong><br>
            Manage receiving, put-away, picking, packing, and shipment workflows across all warehouse zones.
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div class="info-card">
            <strong>🗂️ Inventory & Logistics</strong><br>
            Track stock movements, manage storage locations, and monitor logistics KPIs in real time.
        </div>
        """, unsafe_allow_html=True)

    st.info("👈 Use the **sidebar menu** to navigate to the desired section.", icon="ℹ️")

    # ── Footer ────────────────────────────────────────────────
    st.markdown(f"""
    <div class="footer">
        <strong>{APP_NAME}</strong> v{APP_VERSION} | © 2025 Rozitek Intralogistic Solution Co., Ltd
    </div>
    """, unsafe_allow_html=True)


# ==================== MAIN ====================

def main():
    """Main application entry point"""
    if not auth.check_session():
        show_login_page()
    else:
        show_main_app()


if __name__ == "__main__":
    main()