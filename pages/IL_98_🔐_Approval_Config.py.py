# pages/Admin_🔐_Approval_Config.py
"""
Approval Authority Management — Admin Only

CRUD for approval_types + approval_authorities.
Controls who can approve what, at which level, up to what amount.

Access: admin role only.
"""

import streamlit as st
import pandas as pd
from datetime import date, datetime
import logging

from utils.auth import AuthManager
from utils.db import execute_query, execute_update, get_transaction
from sqlalchemy import text

logger = logging.getLogger(__name__)
auth = AuthManager()

st.set_page_config(page_title="Approval Config", page_icon="🔐", layout="wide")
auth.require_role(['admin'])
user_id = str(auth.get_user_id())


# ══════════════════════════════════════════════════════════════════════
# DATA LOADERS
# ══════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=120)
def _load_approval_types():
    return execute_query("""
        SELECT id, code, name, description, is_active,
               created_by, created_date, modified_date
        FROM approval_types
        WHERE delete_flag = 0
        ORDER BY code
    """)

@st.cache_data(ttl=120)
def _load_authorities():
    return execute_query("""
        SELECT
            aa.id,
            aa.employee_id,
            CONCAT(e.first_name, ' ', e.last_name) AS employee_name,
            e.email,
            p.name AS position,
            aa.approval_type_id,
            at2.code AS type_code,
            at2.name AS type_name,
            aa.company_id,
            c.english_name AS company_name,
            aa.approval_level,
            aa.max_amount,
            aa.is_active,
            aa.valid_from,
            aa.valid_to,
            aa.notes,
            aa.created_date,
            aa.modified_date
        FROM approval_authorities aa
        JOIN employees e ON aa.employee_id = e.id
        JOIN approval_types at2 ON aa.approval_type_id = at2.id
        LEFT JOIN companies c ON aa.company_id = c.id
        LEFT JOIN positions p ON e.position_id = p.id
        WHERE aa.delete_flag = 0
        ORDER BY at2.code, aa.approval_level, e.first_name
    """)

@st.cache_data(ttl=300)
def _load_employees():
    return execute_query("""
        SELECT e.id,
               CONCAT(e.first_name, ' ', e.last_name) AS full_name,
               e.email,
               p.name AS position
        FROM employees e
        LEFT JOIN positions p ON e.position_id = p.id
        WHERE e.delete_flag = 0 AND e.status = 'ACTIVE'
        ORDER BY e.first_name, e.last_name
    """)

@st.cache_data(ttl=300)
def _load_companies():
    return execute_query("""
        SELECT id, english_name AS name, company_code
        FROM companies
        WHERE delete_flag = 0
        ORDER BY english_name
    """)

@st.cache_data(ttl=60)
def _load_approval_history_recent(limit: int = 30):
    return execute_query("""
        SELECT
            ah.id,
            at2.code AS type_code,
            ah.entity_id,
            ah.entity_reference,
            CONCAT(e.first_name, ' ', e.last_name) AS approver_name,
            ah.approval_status,
            ah.approval_level,
            ah.approval_date,
            LEFT(ah.comments, 150) AS comments
        FROM approval_history ah
        JOIN approval_types at2 ON ah.approval_type_id = at2.id
        JOIN employees e ON ah.approver_id = e.id
        WHERE ah.delete_flag = 0
        ORDER BY ah.created_date DESC
        LIMIT :lim
    """, {'lim': limit})


# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════

def _fmt_amount(val) -> str:
    if val is None:
        return '∞ (unlimited)'
    try:
        v = float(val)
        if v >= 1_000_000_000:
            return f"{v/1_000_000_000:,.1f}B ₫"
        if v >= 1_000_000:
            return f"{v/1_000_000:,.0f}M ₫"
        return f"{v:,.0f} ₫"
    except (TypeError, ValueError):
        return str(val)

STATUS_MAP = {True: '🟢 Active', False: '🔴 Inactive', 1: '🟢 Active', 0: '🔴 Inactive'}


# ══════════════════════════════════════════════════════════════════════
# DIALOGS — Approval Types
# ══════════════════════════════════════════════════════════════════════

@st.dialog("➕ New Approval Type", width="large")
def _dialog_create_type():
    with st.form("create_type_form"):
        c1, c2 = st.columns(2)
        code = c1.text_input("Code *", placeholder="e.g. IL_PURCHASE_REQUEST",
                              help="Unique identifier. Use UPPER_SNAKE_CASE.")
        name = c2.text_input("Name *", placeholder="e.g. IL Project — Purchase Request")
        description = st.text_area("Description", height=80)
        is_active = st.checkbox("Active", value=True)
        submitted = st.form_submit_button("💾 Create", type="primary", use_container_width=True)

    if submitted:
        if not code or not name:
            st.error("Code and Name are required."); return
        # Check unique
        existing = execute_query(
            "SELECT id FROM approval_types WHERE code = :c AND delete_flag = 0",
            {'c': code.strip().upper()}
        )
        if existing:
            st.error(f"Code '{code}' already exists."); return
        try:
            execute_update("""
                INSERT INTO approval_types (code, name, description, is_active, created_by, created_date)
                VALUES (:code, :name, :desc, :active, :by, NOW())
            """, {
                'code': code.strip().upper(), 'name': name.strip(),
                'desc': description.strip() or None,
                'active': 1 if is_active else 0, 'by': user_id,
            })
            st.success(f"✅ Approval type '{code}' created!")
            st.cache_data.clear(); st.rerun()
        except Exception as e:
            st.error(f"Create failed: {e}")


@st.dialog("✏️ Edit Approval Type", width="large")
def _dialog_edit_type(type_data: dict):
    with st.form("edit_type_form"):
        c1, c2 = st.columns(2)
        c1.text_input("Code", value=type_data['code'], disabled=True)
        name = c2.text_input("Name *", value=type_data['name'])
        description = st.text_area("Description", value=type_data.get('description') or '', height=80)
        is_active = st.checkbox("Active", value=bool(type_data['is_active']))

        col_save, col_del = st.columns(2)
        save = col_save.form_submit_button("💾 Save", type="primary", use_container_width=True)
        delete = col_del.form_submit_button("🗑 Delete", use_container_width=True)

    if save:
        if not name:
            st.error("Name is required."); return
        try:
            execute_update("""
                UPDATE approval_types SET
                    name = :name, description = :desc, is_active = :active,
                    modified_by = :by, modified_date = NOW()
                WHERE id = :id AND delete_flag = 0
            """, {
                'id': type_data['id'], 'name': name.strip(),
                'desc': description.strip() or None,
                'active': 1 if is_active else 0, 'by': user_id,
            })
            st.success("✅ Updated!")
            st.cache_data.clear(); st.rerun()
        except Exception as e:
            st.error(f"Update failed: {e}")

    if delete:
        # Check if any authorities reference this type
        refs = execute_query(
            "SELECT COUNT(*) AS cnt FROM approval_authorities WHERE approval_type_id = :id AND delete_flag = 0",
            {'id': type_data['id']}
        )
        if refs and refs[0]['cnt'] > 0:
            st.error(f"Cannot delete — {refs[0]['cnt']} authority record(s) reference this type. "
                     "Remove those first or set type to Inactive.")
            return
        execute_update(
            "UPDATE approval_types SET delete_flag = 1, modified_by = :by WHERE id = :id",
            {'id': type_data['id'], 'by': user_id}
        )
        st.success("Deleted.")
        st.cache_data.clear(); st.rerun()


# ══════════════════════════════════════════════════════════════════════
# DIALOGS — Approval Authorities
# ══════════════════════════════════════════════════════════════════════

@st.dialog("➕ New Approval Authority", width="large")
def _dialog_create_authority():
    types = _load_approval_types()
    emps = _load_employees()
    comps = _load_companies()

    if not types:
        st.warning("No approval types defined. Create one first."); return
    if not emps:
        st.warning("No active employees found."); return

    with st.form("create_auth_form"):
        # Type
        type_opts = [f"[{t['code']}] {t['name']}" for t in types]
        type_sel = st.selectbox("Approval Type *", type_opts)
        type_id = types[type_opts.index(type_sel)]['id']

        # Employee
        a1, a2 = st.columns(2)
        emp_opts = [f"{e['full_name']} ({e.get('position', '—')})" for e in emps]
        emp_sel = a1.selectbox("Approver *", emp_opts)
        emp_id = emps[emp_opts.index(emp_sel)]['id']
        a2.caption(f"📧 {emps[emp_opts.index(emp_sel)]['email']}")

        # Level & Amount
        b1, b2 = st.columns(2)
        level = b1.number_input("Approval Level *", min_value=1, max_value=10, value=1,
                                 help="1 = first approver, 2 = second, etc. Lower level approves first.")
        has_limit = b2.checkbox("Set amount limit", value=True,
                                 help="Uncheck = unlimited (approves any amount)")
        max_amount = None
        if has_limit:
            max_amount = st.number_input("Max Amount (VND)", min_value=0.0, value=500_000_000.0,
                                          format="%.0f",
                                          help="Maximum total PR amount this approver can approve at this level")
            st.caption(f"= {_fmt_amount(max_amount)}")

        # Company scope
        comp_opts = ["All companies (no restriction)"] + [c['name'] for c in comps]
        comp_sel = st.selectbox("Company Scope", comp_opts,
                                 help="Restrict this authority to a specific company. Usually leave as 'All'.")
        company_id = None
        if comp_sel != "All companies (no restriction)":
            company_id = comps[comp_opts.index(comp_sel) - 1]['id']

        # Validity
        c1, c2 = st.columns(2)
        valid_from = c1.date_input("Valid From", value=date.today())
        has_expiry = c2.checkbox("Set expiry date", value=False)
        valid_to = None
        if has_expiry:
            valid_to = st.date_input("Valid To")

        is_active = st.checkbox("Active", value=True)
        notes = st.text_input("Notes", placeholder="e.g. IL PR Level 1: GM approves up to 500M VND")

        submitted = st.form_submit_button("💾 Create", type="primary", use_container_width=True)

    if submitted:
        # Check duplicate: same employee + type + level
        dup = execute_query("""
            SELECT id FROM approval_authorities
            WHERE employee_id = :eid AND approval_type_id = :tid AND approval_level = :lvl
              AND delete_flag = 0
        """, {'eid': emp_id, 'tid': type_id, 'lvl': level})
        if dup:
            st.error(f"Duplicate: this employee already has level {level} for this approval type. "
                     "Edit the existing record instead."); return

        try:
            execute_update("""
                INSERT INTO approval_authorities
                    (employee_id, approval_type_id, company_id, is_active,
                     valid_from, valid_to, approval_level, max_amount,
                     created_by, created_date, notes)
                VALUES
                    (:eid, :tid, :cid, :active,
                     :vfrom, :vto, :lvl, :amt,
                     :by, NOW(), :notes)
            """, {
                'eid': emp_id, 'tid': type_id, 'cid': company_id,
                'active': 1 if is_active else 0,
                'vfrom': valid_from,
                'vto': valid_to,
                'lvl': level, 'amt': max_amount,
                'by': user_id, 'notes': notes.strip() or None,
            })
            st.success(f"✅ Authority created: {emps[emp_opts.index(emp_sel)]['full_name']} — Level {level}")
            st.cache_data.clear(); st.rerun()
        except Exception as e:
            st.error(f"Create failed: {e}")


@st.dialog("✏️ Edit Approval Authority", width="large")
def _dialog_edit_authority(auth_data: dict):
    emps = _load_employees()
    comps = _load_companies()

    st.markdown(f"**{auth_data['type_code']}** — {auth_data['type_name']}")
    st.caption(f"Current: {auth_data['employee_name']} | Level {auth_data['approval_level']} | "
               f"Max: {_fmt_amount(auth_data.get('max_amount'))}")

    with st.form("edit_auth_form"):
        # Employee (can change)
        emp_opts = [f"{e['full_name']} ({e.get('position', '—')})" for e in emps]
        cur_emp_idx = next(
            (i for i, e in enumerate(emps) if e['id'] == auth_data['employee_id']),
            0
        )
        emp_sel = st.selectbox("Approver", emp_opts, index=cur_emp_idx)
        emp_id = emps[emp_opts.index(emp_sel)]['id']

        # Level & Amount
        b1, b2 = st.columns(2)
        level = b1.number_input("Approval Level", min_value=1, max_value=10,
                                 value=int(auth_data['approval_level']))
        cur_amount = auth_data.get('max_amount')
        has_limit = b2.checkbox("Amount limit", value=(cur_amount is not None))
        max_amount = None
        if has_limit:
            max_amount = st.number_input("Max Amount (VND)", min_value=0.0,
                                          value=float(cur_amount or 500_000_000),
                                          format="%.0f")
            st.caption(f"= {_fmt_amount(max_amount)}")

        # Company scope
        comp_opts = ["All companies"] + [c['name'] for c in comps]
        cur_comp_idx = 0
        if auth_data.get('company_id'):
            for i, c in enumerate(comps):
                if c['id'] == auth_data['company_id']:
                    cur_comp_idx = i + 1; break
        comp_sel = st.selectbox("Company Scope", comp_opts, index=cur_comp_idx)
        company_id = None
        if comp_sel != "All companies":
            company_id = comps[comp_opts.index(comp_sel) - 1]['id']

        # Validity
        c1, c2 = st.columns(2)
        vf = auth_data.get('valid_from')
        if isinstance(vf, datetime):
            vf = vf.date()
        elif isinstance(vf, str):
            vf = datetime.strptime(vf[:10], '%Y-%m-%d').date()
        valid_from = c1.date_input("Valid From", value=vf or date.today())

        vt = auth_data.get('valid_to')
        has_expiry = c2.checkbox("Has expiry", value=(vt is not None))
        valid_to = None
        if has_expiry:
            if isinstance(vt, datetime):
                vt = vt.date()
            elif isinstance(vt, str):
                vt = datetime.strptime(vt[:10], '%Y-%m-%d').date()
            valid_to = st.date_input("Valid To", value=vt or date.today())

        is_active = st.checkbox("Active", value=bool(auth_data['is_active']))
        notes = st.text_input("Notes", value=auth_data.get('notes') or '')

        col_save, col_del = st.columns(2)
        save = col_save.form_submit_button("💾 Save", type="primary", use_container_width=True)
        delete = col_del.form_submit_button("🗑 Delete", use_container_width=True)

    if save:
        try:
            execute_update("""
                UPDATE approval_authorities SET
                    employee_id = :eid,
                    approval_level = :lvl,
                    max_amount = :amt,
                    company_id = :cid,
                    valid_from = :vfrom,
                    valid_to = :vto,
                    is_active = :active,
                    notes = :notes,
                    modified_by = :by,
                    modified_date = NOW()
                WHERE id = :id AND delete_flag = 0
            """, {
                'id': auth_data['id'], 'eid': emp_id, 'lvl': level,
                'amt': max_amount, 'cid': company_id,
                'vfrom': valid_from, 'vto': valid_to,
                'active': 1 if is_active else 0,
                'notes': notes.strip() or None, 'by': user_id,
            })
            st.success("✅ Updated!")
            st.cache_data.clear(); st.rerun()
        except Exception as e:
            st.error(f"Update failed: {e}")

    if delete:
        execute_update(
            "UPDATE approval_authorities SET delete_flag = 1, modified_by = :by WHERE id = :id",
            {'id': auth_data['id'], 'by': user_id}
        )
        st.success("Deleted.")
        st.cache_data.clear(); st.rerun()


# ══════════════════════════════════════════════════════════════════════
# PAGE LAYOUT
# ══════════════════════════════════════════════════════════════════════

st.title("🔐 Approval Configuration")
st.caption("Manage approval types, authorities, and view approval history. Admin only.")

tab_authorities, tab_types, tab_history = st.tabs([
    "👥 Approval Authorities",
    "📋 Approval Types",
    "📜 Approval History",
])


# ══════════════════════════════════════════════════════════════════════
# TAB 1 — Authorities (main table)
# ══════════════════════════════════════════════════════════════════════

with tab_authorities:
    # Toolbar
    th1, th2, th3 = st.columns([3, 2, 1])
    types_for_filter = _load_approval_types()
    type_filter_opts = ["All Types"] + [f"[{t['code']}] {t['name']}" for t in types_for_filter]
    type_filter = th1.selectbox("Filter by Type", type_filter_opts, key="auth_type_filter")
    active_filter = th2.selectbox("Status", ["All", "Active Only", "Inactive Only"], key="auth_status_filter")
    if th3.button("➕ New Authority", type="primary", use_container_width=True):
        _dialog_create_authority()

    # Load & filter
    authorities = _load_authorities()

    if type_filter != "All Types":
        filter_code = type_filter.split("]")[0][1:]
        authorities = [a for a in authorities if a['type_code'] == filter_code]
    if active_filter == "Active Only":
        authorities = [a for a in authorities if a['is_active']]
    elif active_filter == "Inactive Only":
        authorities = [a for a in authorities if not a['is_active']]

    # KPIs
    k1, k2, k3 = st.columns(3)
    k1.metric("Total Authorities", len(authorities))
    active_count = sum(1 for a in authorities if a['is_active'])
    k2.metric("Active", active_count)
    unique_types = len(set(a['type_code'] for a in authorities))
    k3.metric("Types Configured", unique_types)

    if not authorities:
        st.info("No approval authorities configured. Click ➕ to create one.")
    else:
        # Group by type for clarity
        auth_df = pd.DataFrame(authorities)
        auth_df['status'] = auth_df['is_active'].map(lambda v: '🟢' if v else '🔴')
        auth_df['max_amount_fmt'] = auth_df['max_amount'].apply(_fmt_amount)
        auth_df['valid_range'] = auth_df.apply(
            lambda r: f"{str(r['valid_from'])[:10]} → {str(r['valid_to'])[:10] if r['valid_to'] else '∞'}",
            axis=1
        )

        tbl_key = f"auth_tbl_{st.session_state.get('_auth_key', 0)}"
        event = st.dataframe(
            auth_df, key=tbl_key, width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            column_config={
                'status':          st.column_config.TextColumn('', width=30),
                'type_code':       st.column_config.TextColumn('Type', width=160),
                'employee_name':   st.column_config.TextColumn('Approver'),
                'position':        st.column_config.TextColumn('Position', width=120),
                'email':           st.column_config.TextColumn('Email'),
                'approval_level':  st.column_config.NumberColumn('Level', width=60),
                'max_amount_fmt':  st.column_config.TextColumn('Max Amount'),
                'company_name':    st.column_config.TextColumn('Company Scope'),
                'valid_range':     st.column_config.TextColumn('Valid Period'),
                'notes':           st.column_config.TextColumn('Notes'),
                # Hide raw columns
                'id': None, 'employee_id': None, 'approval_type_id': None,
                'type_name': None, 'company_id': None, 'max_amount': None,
                'is_active': None, 'valid_from': None, 'valid_to': None,
                'created_date': None, 'modified_date': None,
            },
        )

        sel = event.selection.rows
        if sel:
            row = authorities[sel[0]]
            st.markdown(f"**Selected:** {row['employee_name']} — Level {row['approval_level']} "
                        f"— {row['type_code']} — Max: {_fmt_amount(row.get('max_amount'))}")
            ab1, ab2, ab3 = st.columns([1, 1, 2])
            if ab1.button("✏️ Edit", type="primary", use_container_width=True, key="auth_edit"):
                _dialog_edit_authority(row)
            if ab2.button("✖ Deselect", use_container_width=True, key="auth_desel"):
                st.session_state['_auth_key'] = st.session_state.get('_auth_key', 0) + 1
                st.rerun()


# ══════════════════════════════════════════════════════════════════════
# TAB 2 — Approval Types
# ══════════════════════════════════════════════════════════════════════

with tab_types:
    tc1, _, tc2 = st.columns([3, 2, 1])
    if tc2.button("➕ New Type", type="primary", use_container_width=True):
        _dialog_create_type()

    types = _load_approval_types()

    if not types:
        st.info("No approval types defined.")
    else:
        types_df = pd.DataFrame(types)
        types_df['status'] = types_df['is_active'].map(lambda v: '🟢' if v else '🔴')
        # Count authorities per type
        all_auth = _load_authorities()
        type_auth_count = {}
        for a in all_auth:
            type_auth_count[a['approval_type_id']] = type_auth_count.get(a['approval_type_id'], 0) + 1
        types_df['authorities'] = types_df['id'].map(lambda tid: type_auth_count.get(tid, 0))

        tbl_key = f"types_tbl_{st.session_state.get('_types_key', 0)}"
        event = st.dataframe(
            types_df, key=tbl_key, width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            column_config={
                'status':       st.column_config.TextColumn('', width=30),
                'code':         st.column_config.TextColumn('Code', width=200),
                'name':         st.column_config.TextColumn('Name'),
                'description':  st.column_config.TextColumn('Description'),
                'authorities':  st.column_config.NumberColumn('Authorities', width=100),
                'created_date': st.column_config.DatetimeColumn('Created'),
                'id': None, 'is_active': None, 'created_by': None, 'modified_date': None,
            },
        )

        sel = event.selection.rows
        if sel:
            row = types[sel[0]]
            st.markdown(f"**Selected:** `{row['code']}` — {row['name']}")
            ab1, ab2 = st.columns([1, 3])
            if ab1.button("✏️ Edit", type="primary", use_container_width=True, key="type_edit"):
                _dialog_edit_type(row)
            if ab2.button("✖ Deselect", use_container_width=True, key="type_desel"):
                st.session_state['_types_key'] = st.session_state.get('_types_key', 0) + 1
                st.rerun()


# ══════════════════════════════════════════════════════════════════════
# TAB 3 — Approval History (read-only log)
# ══════════════════════════════════════════════════════════════════════

with tab_history:
    st.caption("Recent approval decisions across all modules. Read-only.")

    history = _load_approval_history_recent(50)

    if not history:
        st.info("No approval history yet.")
    else:
        hist_df = pd.DataFrame(history)
        hist_df.insert(0, '●', hist_df['approval_status'].map({
            'APPROVED': '✅', 'REJECTED': '❌', 'SUBMITTED': '📤',
            'REVISION_REQUESTED': '🔄', 'PENDING': '🔵',
        }).fillna('⚪'))

        st.dataframe(
            hist_df, width="stretch", hide_index=True,
            column_config={
                '●':                st.column_config.TextColumn('', width=30),
                'type_code':        st.column_config.TextColumn('Type', width=180),
                'entity_reference': st.column_config.TextColumn('Reference'),
                'approver_name':    st.column_config.TextColumn('Approver'),
                'approval_status':  st.column_config.TextColumn('Decision'),
                'approval_level':   st.column_config.NumberColumn('Level', width=60),
                'approval_date':    st.column_config.DatetimeColumn('Date'),
                'comments':         st.column_config.TextColumn('Comments'),
                'id': None, 'entity_id': None,
            },
        )
