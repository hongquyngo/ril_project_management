# pages/Admin_🔐_Approval_Config.py
"""
Approval Authority Management — Admin Only

CRUD for approval_types + approval_authorities.
Controls who can approve what, at which level, up to what amount.

Phase 1: 📧 Notifications tab — on-demand summary email
Phase 2: Auto-notify stakeholders on config changes (inline after CRUD)
Phase 3: Saved recipient presets + notification audit log

Access: admin role only.
"""

import streamlit as st
import pandas as pd
from datetime import date, datetime
import logging

from utils.auth import AuthManager
from utils.db import execute_query, execute_update, get_transaction
from sqlalchemy import text
import streamlit.components.v1 as components

try:
    from utils.il_project.approval_guide import render_approval_guide
    _has_guide = True
except ImportError:
    _has_guide = False

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


def _get_admin_name() -> str:
    """Get current admin's display name."""
    try:
        emp_id = st.session_state.get('employee_id')
        if emp_id:
            rows = execute_query(
                "SELECT CONCAT(first_name, ' ', last_name) AS name FROM employees WHERE id = :id",
                {'id': emp_id}
            )
            if rows:
                return rows[0]['name']
    except Exception:
        pass
    return f"Admin (ID: {user_id})"


def _get_chain_for_type(type_code: str) -> list:
    """Get current approval chain for a specific type (for email visualization)."""
    all_auth = _load_authorities()
    return [a for a in all_auth if a.get('type_code') == type_code and a.get('is_active')]


# ══════════════════════════════════════════════════════════════════════
# PHASE 2: AUTO-NOTIFY AFTER CONFIG CHANGE
# ══════════════════════════════════════════════════════════════════════

def _get_admin_email() -> str:
    """Get current admin's email address."""
    try:
        emp_id = st.session_state.get('employee_id')
        if emp_id:
            rows = execute_query(
                "SELECT email FROM employees WHERE id = :id AND delete_flag = 0",
                {'id': emp_id}
            )
            if rows and rows[0].get('email'):
                return rows[0]['email']
    except Exception:
        pass
    return ""


def _auto_notify_change(
    change_type: str,
    authority_data: dict,
    old_data: dict = None,
):
    """
    Auto-send notification after CRUD. Non-blocking — CRUD succeeds
    regardless of email result. Stores result in session_state for
    display on next rerun.
    """
    try:
        from utils.il_project.approval_notify import auto_notify_crud
    except ImportError:
        logger.debug("auto_notify_crud not available — skipping notification.")
        return

    admin_name = _get_admin_name()
    admin_email = _get_admin_email()

    result = auto_notify_crud(
        change_type=change_type,
        authority_data=authority_data,
        old_data=old_data,
        changed_by_name=admin_name,
        sender_email=admin_email,
        sent_by=user_id,
        sent_by_employee_id=st.session_state.get('employee_id'),
    )

    # Store result for display after rerun
    st.session_state['_crud_notify_result'] = result


def _render_crud_notify_result():
    """
    Display auto-notify result banner at the top of Authorities tab.
    Called once per rerun, pops the result from session_state.
    """
    result = st.session_state.pop('_crud_notify_result', None)
    if not result:
        return

    if result.get('success'):
        to_list = result.get('to', [])
        cc_list = result.get('cc', [])
        total = len(to_list) + len(cc_list)
        st.success(
            f"📧 Notification sent to {total} recipient(s)  \n"
            f"**TO:** {', '.join(to_list)}  \n"
            f"**CC:** {', '.join(cc_list) if cc_list else '—'}"
        )
    else:
        msg = result.get('message', 'Unknown error')
        # Don't show error for non-configured email — just info
        if 'not configured' in msg.lower():
            st.info(f"ℹ️ Email notification skipped: {msg}")
        else:
            st.warning(f"⚠️ Notification failed: {msg}  \n(The changes were saved successfully.)")


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
# DIALOGS — Approval Authorities (with Phase 2 auto-notify)
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
        type_opts = [f"[{t['code']}] {t['name']}" for t in types]
        type_sel = st.selectbox("Approval Type *", type_opts)
        type_idx = type_opts.index(type_sel)
        type_id = types[type_idx]['id']
        type_code = types[type_idx]['code']
        type_name = types[type_idx]['name']

        a1, a2 = st.columns(2)
        emp_opts = [f"{e['full_name']} ({e.get('position', '—')})" for e in emps]
        emp_sel = a1.selectbox("Approver *", emp_opts)
        emp_idx = emp_opts.index(emp_sel)
        emp_id = emps[emp_idx]['id']
        a2.caption(f"📧 {emps[emp_idx]['email']}")

        b1, b2 = st.columns(2)
        level = b1.number_input("Approval Level *", min_value=1, max_value=10, value=1,
                                 help="1 = first approver, 2 = second, etc.")
        has_limit = b2.checkbox("Set amount limit", value=True)
        max_amount = None
        if has_limit:
            max_amount = st.number_input("Max Amount (VND)", min_value=0.0, value=500_000_000.0,
                                          format="%.0f")
            st.caption(f"= {_fmt_amount(max_amount)}")

        comp_opts = ["All companies (no restriction)"] + [c['name'] for c in comps]
        comp_sel = st.selectbox("Company Scope", comp_opts)
        company_id = None
        if comp_sel != "All companies (no restriction)":
            company_id = comps[comp_opts.index(comp_sel) - 1]['id']

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
        dup = execute_query("""
            SELECT id FROM approval_authorities
            WHERE employee_id = :eid AND approval_type_id = :tid AND approval_level = :lvl
              AND delete_flag = 0
        """, {'eid': emp_id, 'tid': type_id, 'lvl': level})
        if dup:
            st.error(f"Duplicate: this employee already has level {level} for this approval type."); return

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
                'vfrom': valid_from, 'vto': valid_to,
                'lvl': level, 'amt': max_amount,
                'by': user_id, 'notes': notes.strip() or None,
            })
            st.success(f"✅ Authority created: {emps[emp_idx]['full_name']} — Level {level}")

            # Auto-notify all relevant parties
            _auto_notify_change(
                change_type='CREATED',
                authority_data={
                    'employee_name': emps[emp_idx]['full_name'],
                    'email': emps[emp_idx]['email'],
                    'position': emps[emp_idx].get('position'),
                    'type_code': type_code, 'type_name': type_name,
                    'approval_level': level, 'max_amount': max_amount,
                    'is_active': is_active,
                },
            )
            st.cache_data.clear(); st.rerun()
        except Exception as e:
            st.error(f"Create failed: {e}")


@st.dialog("✏️ Edit Approval Authority", width="large")
def _dialog_edit_authority(auth_data: dict):
    emps = _load_employees()
    comps = _load_companies()

    # Capture old data for diff (Phase 2)
    old_data = dict(auth_data)

    st.markdown(f"**{auth_data['type_code']}** — {auth_data['type_name']}")
    st.caption(f"Current: {auth_data['employee_name']} | Level {auth_data['approval_level']} | "
               f"Max: {_fmt_amount(auth_data.get('max_amount'))}")

    with st.form("edit_auth_form"):
        emp_opts = [f"{e['full_name']} ({e.get('position', '—')})" for e in emps]
        cur_emp_idx = next(
            (i for i, e in enumerate(emps) if e['id'] == auth_data['employee_id']),
            0
        )
        emp_sel = st.selectbox("Approver", emp_opts, index=cur_emp_idx)
        emp_idx = emp_opts.index(emp_sel)
        emp_id = emps[emp_idx]['id']

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

            # Auto-notify all relevant parties
            new_data = {
                'employee_name': emps[emp_idx]['full_name'],
                'email': emps[emp_idx]['email'],
                'position': emps[emp_idx].get('position'),
                'type_code': auth_data['type_code'],
                'type_name': auth_data['type_name'],
                'approval_level': level,
                'max_amount': max_amount,
                'is_active': is_active,
            }
            _auto_notify_change(
                change_type='UPDATED',
                authority_data=new_data,
                old_data=old_data,
            )
            st.cache_data.clear(); st.rerun()
        except Exception as e:
            st.error(f"Update failed: {e}")

    if delete:
        execute_update(
            "UPDATE approval_authorities SET delete_flag = 1, modified_by = :by WHERE id = :id",
            {'id': auth_data['id'], 'by': user_id}
        )
        st.success("Deleted.")
        # Auto-notify all relevant parties
        _auto_notify_change(
            change_type='DELETED',
            authority_data=auth_data,
        )
        st.cache_data.clear(); st.rerun()


# ══════════════════════════════════════════════════════════════════════
# DIALOGS — Preset Management (Phase 3)
# ══════════════════════════════════════════════════════════════════════

@st.dialog("➕ New Notification Preset", width="large")
def _dialog_create_preset():
    emps = _load_employees()
    types = _load_approval_types()

    with st.form("create_preset_form"):
        preset_name = st.text_input("Preset Name *", placeholder="e.g. Finance Team")

        preset_type = st.selectbox("Type", [
            "MANUAL — Pick employees + enter emails",
            "AUTO_APPROVERS — All active approvers (auto-resolved)",
            "AUTO_PMS — All active project managers (auto-resolved)",
        ])
        preset_type_code = preset_type.split(" —")[0]

        # Scope
        type_opts = ["All Types"] + [t['code'] for t in types]
        scope_sel = st.selectbox("Approval Type Scope", type_opts,
                                  help="Filter: only show this preset when working with this type")
        scope_code = None if scope_sel == "All Types" else scope_sel

        selected_emp_ids = []
        manual_emails = []
        if 'MANUAL' in preset_type_code:
            # Employee multiselect
            emp_opts = [f"{e['full_name']} ({e.get('email', '—')})" for e in emps]
            emp_sel = st.multiselect("Select Employees", emp_opts,
                                      help="Pick from employee list")
            selected_emp_ids = [emps[emp_opts.index(s)]['id'] for s in emp_sel]

            # Manual emails
            email_input = st.text_area(
                "Additional Emails (one per line)",
                placeholder="finance-group@prostech.vn\naccounting@prostech.vn",
                height=80,
            )
            if email_input:
                manual_emails = [
                    e.strip() for e in email_input.strip().split('\n')
                    if e.strip() and '@' in e
                ]

        submitted = st.form_submit_button("💾 Save Preset", type="primary", use_container_width=True)

    if submitted:
        if not preset_name:
            st.error("Preset name is required."); return

        try:
            from utils.il_project.approval_notify import save_preset
            result = save_preset(
                preset_name=preset_name,
                preset_type=preset_type_code,
                email_list=manual_emails,
                employee_ids=selected_emp_ids,
                approval_type_code=scope_code,
                created_by=user_id,
            )
            if result['success']:
                st.success(f"✅ {result['message']}")
                st.cache_data.clear(); st.rerun()
            else:
                st.error(result['message'])
        except ImportError:
            st.error("approval_notify module not available.")


@st.dialog("✏️ Edit Preset", width="large")
def _dialog_edit_preset(preset: dict):
    emps = _load_employees()
    types = _load_approval_types()

    with st.form("edit_preset_form"):
        preset_name = st.text_input("Preset Name *", value=preset.get('preset_name', ''))

        type_opts_map = {
            'MANUAL': "MANUAL — Pick employees + enter emails",
            'AUTO_APPROVERS': "AUTO_APPROVERS — All active approvers (auto-resolved)",
            'AUTO_PMS': "AUTO_PMS — All active project managers (auto-resolved)",
        }
        type_display = list(type_opts_map.values())
        cur_type_idx = list(type_opts_map.keys()).index(preset.get('preset_type', 'MANUAL'))
        preset_type = st.selectbox("Type", type_display, index=cur_type_idx)
        preset_type_code = preset_type.split(" —")[0]

        scope_opts = ["All Types"] + [t['code'] for t in types]
        cur_scope = preset.get('approval_type_code') or 'All Types'
        scope_idx = scope_opts.index(cur_scope) if cur_scope in scope_opts else 0
        scope_sel = st.selectbox("Scope", scope_opts, index=scope_idx)
        scope_code = None if scope_sel == "All Types" else scope_sel

        selected_emp_ids = preset.get('employee_ids', []) or []
        manual_emails = preset.get('email_list', []) or []

        if 'MANUAL' in preset_type_code:
            emp_opts = [f"{e['full_name']} ({e.get('email', '—')})" for e in emps]
            pre_sel = [
                emp_opts[i] for i, e in enumerate(emps) if e['id'] in selected_emp_ids
            ]
            emp_sel = st.multiselect("Select Employees", emp_opts, default=pre_sel)
            selected_emp_ids = [emps[emp_opts.index(s)]['id'] for s in emp_sel]

            email_input = st.text_area(
                "Additional Emails (one per line)",
                value='\n'.join(manual_emails),
                height=80,
            )
            manual_emails = [
                e.strip() for e in email_input.strip().split('\n')
                if e.strip() and '@' in e
            ] if email_input else []

        col_save, col_del = st.columns(2)
        save = col_save.form_submit_button("💾 Save", type="primary", use_container_width=True)
        delete = col_del.form_submit_button("🗑 Delete", use_container_width=True)

    if save:
        if not preset_name:
            st.error("Preset name is required."); return
        try:
            from utils.il_project.approval_notify import save_preset
            result = save_preset(
                preset_name=preset_name,
                preset_type=preset_type_code,
                email_list=manual_emails,
                employee_ids=selected_emp_ids,
                approval_type_code=scope_code,
                created_by=user_id,
                preset_id=preset['id'],
            )
            if result['success']:
                st.success(f"✅ {result['message']}")
                st.cache_data.clear(); st.rerun()
            else:
                st.error(result['message'])
        except ImportError:
            st.error("approval_notify module not available.")

    if delete:
        try:
            from utils.il_project.approval_notify import delete_preset
            delete_preset(preset['id'])
            st.success("Deleted.")
            st.cache_data.clear(); st.rerun()
        except ImportError:
            st.error("approval_notify module not available.")


# ══════════════════════════════════════════════════════════════════════
# PAGE LAYOUT
# ══════════════════════════════════════════════════════════════════════

st.title("🔐 Approval Configuration")
st.caption("Manage approval types, authorities, notifications, and view history. Admin only.")

# Floating user guide popover
if _has_guide:
    render_approval_guide()

tab_authorities, tab_types, tab_notifications, tab_history = st.tabs([
    "👥 Approval Authorities",
    "📋 Approval Types",
    "📧 Notifications",
    "📜 Approval History",
])


# ══════════════════════════════════════════════════════════════════════
# TAB 1 — Authorities (main table)
# ══════════════════════════════════════════════════════════════════════

with tab_authorities:
    # Show auto-notify result banner (if a CRUD just happened)
    _render_crud_notify_result()

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
# TAB 3 — 📧 Notifications (Phase 1 + Phase 3)
# ══════════════════════════════════════════════════════════════════════

with tab_notifications:
    st.markdown("#### 📧 Approval Config Notifications")
    st.caption(
        "Send approval authority configuration to Finance, approvers, and other stakeholders. "
        "Especially important for Finance team to verify payment authorization."
    )

    # ── Section 1: Send Mode ──────────────────────────────────────
    send_mode = st.radio(
        "Send Mode", ["📊 Current Config Summary", "⚡ Config Change Alert"],
        horizontal=True, key="notify_send_mode",
        help="Summary = full config snapshot. Change Alert = notify about a specific change.",
    )

    st.divider()

    # ── Section 2: Scope Filter ───────────────────────────────────
    types_list = _load_approval_types()
    scope_opts = ["All Types"] + [f"{t['code']} — {t['name']}" for t in types_list]
    scope_sel = st.selectbox("Approval Type Scope", scope_opts, key="notify_scope")
    scope_code = None
    if scope_sel != "All Types":
        scope_code = scope_sel.split(" — ")[0]

    # ── Section 3: Recipients ─────────────────────────────────────
    st.markdown("##### 📬 Recipients")

    # Import notify module
    try:
        from utils.il_project.approval_notify import (
            get_presets, resolve_preset_emails,
            build_summary_html, send_config_summary,
            get_notification_log, get_mandatory_cc,
        )
        _has_notify_module = True
    except ImportError:
        _has_notify_module = False
        st.warning("⚠️ `approval_notify` module not found. Place `approval_notify.py` in `utils/il_project/`.")

    # ── 3a: Mandatory CC (locked — sender + all approvers in scope) ──
    mandatory_cc_emails = []
    mandatory_cc_labels = []
    sender_email = _get_admin_email()

    if _has_notify_module:
        authorities_for_cc = _load_authorities()
        mandatory_cc_emails, mandatory_cc_labels = get_mandatory_cc(
            type_filter=scope_code,
            sender_email=sender_email,
            authorities=authorities_for_cc,
        )

    if mandatory_cc_emails:
        with st.container(border=True):
            st.markdown("**🔒 Required CC** — automatically included, cannot be removed")
            for lbl in mandatory_cc_labels:
                st.caption(f"  • {lbl}")
            st.caption(f"Total: {len(mandatory_cc_emails)} required recipient(s)")

    # ── 3b: Quick Presets for additional TO ──
    preset_to_emails = []

    if _has_notify_module:
        presets = get_presets(scope_code)

        if presets:
            st.markdown("**Quick Presets:**")
            preset_cols = st.columns(min(len(presets) + 1, 5))
            for i, p in enumerate(presets):
                pname = p.get('preset_name', '—')
                ptype_icon = {'MANUAL': '📋', 'AUTO_APPROVERS': '👥', 'AUTO_PMS': '📊'}.get(
                    p.get('preset_type', ''), '📋'
                )
                col_idx = i % len(preset_cols)
                if preset_cols[col_idx].button(
                    f"{ptype_icon} {pname}", key=f"preset_btn_{p['id']}",
                    use_container_width=True,
                ):
                    emails, labels = resolve_preset_emails(p)
                    st.session_state['_preset_resolved_to'] = emails
                    st.session_state['_preset_resolved_labels'] = labels
                    st.rerun()

            # Show resolved preset
            if '_preset_resolved_to' in st.session_state:
                resolved = st.session_state['_preset_resolved_to']
                labels = st.session_state.get('_preset_resolved_labels', resolved)
                if resolved:
                    st.info(f"Preset resolved: **{len(resolved)}** recipient(s) — {', '.join(labels[:5])}"
                            + (f" +{len(labels) - 5} more" if len(labels) > 5 else ""))
                    preset_to_emails = resolved

    # ── 3c: Additional TO (manual selection) ──
    st.markdown("**Additional Recipients**")
    emps = _load_employees()
    emp_with_email = [e for e in emps if e.get('email')]
    emp_opts_to = [f"{e['full_name']} — {e.get('position', '')} ({e['email']})" for e in emp_with_email]

    to_sel = st.multiselect("TO: Select from employees", emp_opts_to, key="notify_to_emps",
                             help="Primary recipients (in addition to required CC)")
    to_emp_emails = [emp_with_email[emp_opts_to.index(s)]['email'] for s in to_sel]

    # Additional CC
    cc_sel = st.multiselect("Additional CC: Select from employees", emp_opts_to, key="notify_cc_emps",
                             help="Extra CC recipients beyond the required list")
    cc_emp_emails = [emp_with_email[emp_opts_to.index(s)]['email'] for s in cc_sel]

    # Manual email input
    manual_to = st.text_input(
        "Additional TO emails (comma-separated)", key="notify_manual_to",
        placeholder="finance@prostech.vn, accounting@prostech.vn",
    )
    manual_to_list = [
        e.strip() for e in (manual_to or '').split(',')
        if e.strip() and '@' in e
    ]

    manual_cc = st.text_input(
        "Additional CC emails (comma-separated)", key="notify_manual_cc",
        placeholder="ceo@prostech.vn",
    )
    manual_cc_list = [
        e.strip() for e in (manual_cc or '').split(',')
        if e.strip() and '@' in e
    ]

    # Merge all recipients (mandatory CC is handled server-side by send_config_summary)
    all_to = list(dict.fromkeys(preset_to_emails + to_emp_emails + manual_to_list))
    user_cc = list(dict.fromkeys(cc_emp_emails + manual_cc_list))
    # Remove TO from user CC
    user_cc = [e for e in user_cc if e not in all_to]
    # Final CC = mandatory + user-selected (deduped, mandatory handled server-side)
    all_cc = list(dict.fromkeys(mandatory_cc_emails + user_cc))
    # Remove any that are already in TO
    all_cc = [e for e in all_cc if e not in all_to]

    # Summary
    total_recipients = len(all_to) + len(all_cc)
    if total_recipients:
        st.caption(
            f"📧 TO: {len(all_to)} | "
            f"CC: {len(all_cc)} (incl. {len(mandatory_cc_emails)} required) | "
            f"Total: {total_recipients}"
        )

    # ── Section 4: Options ────────────────────────────────────────
    st.markdown("##### ⚙️ Options")
    oc1, oc2 = st.columns(2)
    include_validity = oc1.checkbox("Include valid period (from/to)", value=True, key="notify_opt_validity")
    include_history = oc2.checkbox("Include recent changes (30 days)", value=False, key="notify_opt_history")

    admin_note = st.text_area(
        "Note to recipients (optional)", key="notify_admin_note", height=80,
        placeholder="e.g. Cập nhật quyền approve PR cho Q2 2026. Finance team vui lòng kiểm tra lại checklist thanh toán."
    )

    # ── Section 5: Preview & Send ─────────────────────────────────
    st.divider()

    pv_col, send_col, _ = st.columns([1, 1, 2])

    if pv_col.button("👁 Preview Email", use_container_width=True, key="notify_preview"):
        st.session_state['_show_preview'] = True

    if send_col.button("📧 Send Notification", type="primary", use_container_width=True, key="notify_send"):
        if not all_to:
            st.error("No TO recipients. Select employees or enter emails.")
        elif not _has_notify_module:
            st.error("approval_notify module not available.")
        else:
            with st.spinner("Sending..."):
                authorities = _load_authorities()
                result = send_config_summary(
                    to_emails=all_to,
                    cc_emails=all_cc or None,
                    authorities=authorities,
                    type_filter=scope_code,
                    admin_note=admin_note,
                    include_validity=include_validity,
                    include_history=include_history,
                    sent_by=user_id,
                    sent_by_employee_id=st.session_state.get('employee_id'),
                    sender_email=sender_email,
                )
            if result.get('success'):
                st.success(f"✅ {result['message']}")
                # Clear preset state
                st.session_state.pop('_preset_resolved_to', None)
                st.session_state.pop('_preset_resolved_labels', None)
            else:
                st.error(f"❌ {result.get('message', 'Send failed')}")

    # Preview panel
    if st.session_state.get('_show_preview') and _has_notify_module:
        st.session_state['_show_preview'] = False
        authorities = _load_authorities()
        preview_body = build_summary_html(
            authorities=authorities,
            type_filter=scope_code,
            admin_note=admin_note,
            include_validity=include_validity,
            include_history=include_history,
        )
        # Wrap with the full email template so preview matches what recipients see
        from utils.il_project.approval_notify import _base_template
        full_preview_html = _base_template("Approval Authority Notification", preview_body)

        with st.expander("📧 Email Preview", expanded=True):
            # ── Recipient bar ──
            _to_str = ', '.join(all_to) if all_to else '(none)'
            _mcc_str = ', '.join(mandatory_cc_emails) if mandatory_cc_emails else ''
            _extra_cc = [e for e in all_cc if e not in mandatory_cc_emails]
            _extra_cc_str = ', '.join(_extra_cc) if _extra_cc else ''
            _cc_parts = []
            if _mcc_str:
                _cc_parts.append(f'<span style="color:#1e40af;">{_mcc_str}</span> <span style="color:#9ca3af;">(required)</span>')
            if _extra_cc_str:
                _cc_parts.append(f'<span style="color:#6b7280;">{_extra_cc_str}</span>')
            _cc_display = ', '.join(_cc_parts) if _cc_parts else '(none)'
            st.markdown(
                f'<div style="padding:10px 14px;background:#f0f4f8;border-radius:6px;'
                f'font-size:13px;line-height:1.6;margin-bottom:12px;">'
                f'<strong style="color:#374151;">TO:</strong> '
                f'<span style="color:#1e40af;">{_to_str}</span><br>'
                f'<strong style="color:#374151;">CC:</strong> '
                f'{_cc_display}'
                f'</div>',
                unsafe_allow_html=True,
            )
            # ── Rendered email preview (iframe) ──
            # Wrap in a minimal HTML doc so it renders cleanly inside the iframe
            iframe_html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>body{{margin:0;padding:16px;background:#f9fafb;font-family:'Segoe UI',Arial,sans-serif;}}</style>
</head><body>{full_preview_html}</body></html>'''
            components.html(iframe_html, height=620, scrolling=True)

    # ── Section 6: Preset Management (Phase 3) ───────────────────
    st.divider()
    with st.expander("🔧 Manage Notification Presets", expanded=False):
        st.caption(
            "Saved recipient groups for quick selection. "
            "AUTO presets resolve dynamically at send time."
        )

        if _has_notify_module:
            all_presets = get_presets()

            if all_presets:
                for p in all_presets:
                    ptype_icon = {'MANUAL': '📋', 'AUTO_APPROVERS': '👥', 'AUTO_PMS': '📊'}.get(
                        p.get('preset_type', ''), '📋'
                    )
                    pname = p.get('preset_name', '—')
                    ptype = p.get('preset_type', '—')
                    scope = p.get('approval_type_code') or 'All Types'

                    # Resolve count
                    emails, _ = resolve_preset_emails(p)

                    pc1, pc2, pc3, pc4 = st.columns([3, 2, 1, 1])
                    pc1.markdown(f"**{ptype_icon} {pname}**")
                    pc2.caption(f"{ptype} | Scope: {scope} | {len(emails)} recipient(s)")
                    if pc3.button("✏️", key=f"preset_edit_{p['id']}"):
                        _dialog_edit_preset(p)
                    if pc4.button("🗑", key=f"preset_del_{p['id']}"):
                        from utils.il_project.approval_notify import delete_preset
                        delete_preset(p['id'])
                        st.cache_data.clear(); st.rerun()
            else:
                st.info("No presets configured yet.")

            if st.button("➕ New Preset", key="preset_create_btn"):
                _dialog_create_preset()

    # ── Section 7: Notification Log (Phase 3) ─────────────────────
    if _has_notify_module:
        with st.expander("📜 Notification Send Log", expanded=False):
            st.caption("Audit trail: who sent what, when, to whom.")
            log = get_notification_log(30)
            if log:
                log_df = pd.DataFrame(log)
                st.dataframe(
                    log_df, width="stretch", hide_index=True,
                    column_config={
                        'entity_reference': st.column_config.TextColumn('Type', width=120),
                        'comments':         st.column_config.TextColumn('Details'),
                        'sent_by_name':     st.column_config.TextColumn('Sent by', width=140),
                        'created_date':     st.column_config.DatetimeColumn('Date', width=140),
                        'id': None, 'created_by': None,
                    },
                )
            else:
                st.info("No notifications sent yet.")
                st.caption(
                    "💡 Tip: Create an approval type `APPROVAL_CONFIG_NOTIFY` "
                    "in the Approval Types tab to enable notification logging."
                )


# ══════════════════════════════════════════════════════════════════════
# TAB 4 — Approval History (read-only log)
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
            'REVISION_REQUESTED': '🔄', 'PENDING': '🔵', 'SENT': '📧',
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