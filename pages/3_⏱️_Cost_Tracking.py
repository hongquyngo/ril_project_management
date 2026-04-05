# pages/3_⏱️_Cost_Tracking.py
"""
Cost Tracking — Labor Logs / Expenses / Pre-sales Costs

Redesigned:
  - Sidebar: Project (All default), date range, phase, approval filters
  - "All Projects" → Overview dashboard with cross-project KPIs + pending approvals
  - Specific project → 3 tabs (Labor / Expenses / Pre-sales)
  - No @st.fragment — action bar pattern for stability
  - Deselect button on every table
"""

import streamlit as st
import pandas as pd
from datetime import date
import logging

from utils.auth import AuthManager
from utils.il_project import (
    get_projects_df, get_project,
    get_labor_logs_df, create_labor_log, update_labor_log, approve_labor_log, soft_delete_labor_log,
    get_expenses_df, create_expense, update_expense, approve_expense, soft_delete_expense,
    get_presales_costs_df, create_presales_cost, bulk_update_presales_allocation,
    get_employees, get_currencies,
    create_expense_media, get_expense_medias,
    create_labor_media,
    fmt_vnd, PHASE_LABELS,
)
from utils.il_project.helpers import (
    EXPENSE_CATEGORIES, PRESALES_CATEGORIES_L1, PRESALES_CATEGORIES_L2,
    EMPLOYEE_LEVELS, DEFAULT_RATES_BY_LEVEL,
    get_vendor_companies,
)
from utils.il_project.s3_il import ILProjectS3Manager
from utils.il_project.currency import get_rate_to_vnd, rate_status, fmt_rate
from utils.il_project.permissions import PermissionContext, get_role_badge

logger = logging.getLogger(__name__)
auth = AuthManager()

st.set_page_config(page_title="Cost Tracking", page_icon="⏱️", layout="wide")
auth.require_auth()
user_id    = str(auth.get_user_id())
emp_int_id = st.session_state.get('employee_id')  # employees.id — for FK approved_by
user_role  = st.session_state.get('user_role', '')
is_admin   = auth.is_admin()

# Permission context — replaces the old global `is_pm` pattern
ctx = PermissionContext(employee_id=emp_int_id, is_admin=is_admin, user_role=user_role)

if not emp_int_id:
    st.error("⚠️ Employee ID not found in session. Please re-login.")
    st.stop()


# ── Lookups (cached) ──────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load():
    return get_projects_df(), get_employees(), get_currencies(), get_vendor_companies()

proj_df, employees, currencies, vendors = _load()
emp_map = {e['id']: e['full_name'] for e in employees}
cur_map = {c['id']: c['code'] for c in currencies}


# ── S3 (cached per session) ──────────────────────────────────────────────────
@st.cache_resource
def _get_s3():
    try:
        return ILProjectS3Manager()
    except Exception as e:
        logger.warning(f"S3 not available: {e}")
        return None


# ── Vendor selector helper ────────────────────────────────────────────────────
def _vendor_selector(col, current_name: str = "", key_suffix: str = "") -> str:
    vendor_names = [v['name'] for v in vendors]
    options = ["(None)"] + vendor_names + ["— Enter manually —"]
    if current_name in vendor_names:
        default_idx = options.index(current_name)
    elif current_name:
        default_idx = options.index("— Enter manually —")
    else:
        default_idx = 0
    sel = col.selectbox("Vendor", options, index=default_idx, key=f"vendor_sel_{key_suffix}",
                        help="Chọn từ danh sách Vendor, hoặc nhập thủ công")
    if sel == "— Enter manually —":
        return st.text_input("Vendor Name (manual)",
                             value=current_name if current_name not in vendor_names else "",
                             key=f"vendor_manual_{key_suffix}", placeholder="Tên vendor / cá nhân tự do")
    elif sel == "(None)":
        return ""
    return sel


# ══════════════════════════════════════════════════════════════════════════════
# PAGE HEADER + SIDEBAR FILTERS
# ══════════════════════════════════════════════════════════════════════════════

st.title("⏱️ Cost Tracking")

if proj_df.empty:
    st.warning("No projects found.")
    st.stop()

with st.sidebar:
    st.header("Filters")

    # ── Project selector (All Projects default) ──
    proj_options = ["All Projects"] + [f"{r.project_code} — {r.project_name}" for r in proj_df.itertuples()]
    sel_label = st.selectbox("Project", proj_options, key="ct_project")
    is_all_projects = sel_label == "All Projects"

    if not is_all_projects:
        sel_idx = proj_options.index(sel_label) - 1  # offset for "All Projects"
        project_id = int(proj_df.iloc[sel_idx]['project_id'])
        project = get_project(project_id)
    else:
        project_id = None
        project = None

    # ── Date range ──
    use_date = st.checkbox("Filter by date range", value=False)
    if use_date:
        d1, d2 = st.columns(2)
        date_from = d1.date_input("From", value=date.today().replace(day=1))
        date_to   = d2.date_input("To",   value=date.today())
    else:
        date_from = date_to = None

    # ── Phase & Approval ──
    f_phase  = st.selectbox("Phase",    ["All"] + list(PHASE_LABELS.keys()), key="ct_phase")
    f_status = st.selectbox("Approval", ["All", "PENDING", "APPROVED", "REJECTED"], key="ct_approval")

    # ── Action buttons (only when specific project selected) ──
    if not is_all_projects:
        st.divider()
        _can_add = ctx.can('cost.create_labor', project_id)
        if _can_add:
            bc1, bc2 = st.columns(2)
            if bc1.button("➕ Log Labor", type="primary", use_container_width=True):
                st.session_state["open_add_labor"] = True
            if bc2.button("➕ Add Expense", type="primary", use_container_width=True):
                st.session_state["open_add_expense"] = True
        st.divider()
        st.caption(f"Role: {get_role_badge(ctx.role(project_id))}")
    else:
        st.divider()
        st.caption(f"Role: {get_role_badge(ctx.role())}")

# ── Resolve filters ──
phase_filter    = None if f_phase == "All" else f_phase
approval_filter = None if f_status == "All" else f_status


# ══════════════════════════════════════════════════════════════════════════════
# DIALOGS — Labor
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("👷 Log Labor Entry", width="large")
def _dialog_add_labor(pid: int):
    with st.form("labor_add_form", clear_on_submit=True):
        is_subcon = st.checkbox("External / Subcontractor", value=False)
        la1, la2 = st.columns(2)
        if not is_subcon:
            emp_opts    = [e['full_name'] for e in employees]
            worker      = la1.selectbox("Employee", emp_opts)
            worker_id   = employees[emp_opts.index(worker)]['id']
            subcon_name = subcon_co = None
        else:
            worker_id   = None
            subcon_name = la1.text_input("Subcontractor Name *")
            subcon_co   = la2.text_input("Company")

        lb1, lb2, lb3, lb4 = st.columns(4)
        level_opts   = [""] + EMPLOYEE_LEVELS
        level_sel    = lb1.selectbox("Level", level_opts)
        work_date    = lb2.date_input("Work Date", value=date.today())
        man_days_v   = lb3.number_input("Man-Days", value=1.0, min_value=0.5, max_value=3.0, step=0.5, format="%.1f")
        is_on_site   = lb4.checkbox("On-site", value=True)

        lc1, lc2, lc3 = st.columns(3)
        hint_rate    = DEFAULT_RATES_BY_LEVEL.get(level_sel, 1_200_000) if level_sel else 1_200_000
        daily_rate_v = lc1.number_input("Day Rate (VND)", value=float(hint_rate), min_value=0.0, format="%.0f")
        phase_opts   = list(PHASE_LABELS.keys())
        phase_sel    = lc2.selectbox("Phase", phase_opts, index=phase_opts.index('IMPLEMENTATION'))
        presales_alloc = None
        if phase_sel == 'PRE_SALES':
            presales_alloc = lc3.selectbox("Pre-sales Allocation", ['PENDING', 'SGA', 'COGS'])

        description_v = st.text_input("Description")
        st.divider()
        uploaded_file = st.file_uploader("📎 Attach document (optional)",
                                         type=["pdf", "jpg", "jpeg", "png", "xlsx", "docx", "doc", "xls", "pptx", "csv", "zip"])
        submitted = st.form_submit_button("✅ Save entry", type="primary", use_container_width=True)

    if submitted:
        if is_subcon and not subcon_name:
            st.error("Subcontractor name required.")
            return
        try:
            log_id = create_labor_log({
                'project_id': pid, 'employee_id': worker_id,
                'employee_level': level_sel or None,
                'subcontractor_name': subcon_name, 'subcontractor_company': subcon_co,
                'work_date': work_date, 'man_days': man_days_v, 'daily_rate': daily_rate_v,
                'phase': phase_sel, 'description': description_v or None,
                'is_on_site': 1 if is_on_site else 0, 'presales_allocation': presales_alloc,
            }, user_id)
            if uploaded_file and log_id:
                s3 = _get_s3()
                if s3:
                    ok, s3_key = s3.upload_labor_attachment(uploaded_file.read(), uploaded_file.name, pid, log_id)
                    if ok:
                        create_labor_media(log_id, s3_key, uploaded_file.name, created_by=user_id)
                    else:
                        st.warning(f"Entry saved but file upload failed: {s3_key}")
            st.success("✅ Labor entry added!")
            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")


@st.dialog("👷 Edit Labor Entry", width="large")
def _dialog_edit_labor(log: dict, pid: int):
    log_id = log['id']
    with st.form("labor_edit_form"):
        lb1, lb2, lb3 = st.columns(3)
        work_date    = lb1.date_input("Work Date",
                        value=pd.to_datetime(log.get('work_date')).date() if log.get('work_date') else date.today())
        man_days_v   = lb2.number_input("Man-Days", value=float(log.get('man_days', 1)),
                                         min_value=0.5, max_value=3.0, step=0.5, format="%.1f")
        daily_rate_v = lb3.number_input("Day Rate (VND)", value=float(log.get('daily_rate', 0)),
                                         min_value=0.0, format="%.0f")

        lc1, lc2, lc3 = st.columns(3)
        level_opts  = [""] + EMPLOYEE_LEVELS
        level_idx   = level_opts.index(log.get('employee_level') or '') if log.get('employee_level') in level_opts else 0
        level_sel   = lc1.selectbox("Level", level_opts, index=level_idx)
        phase_opts  = list(PHASE_LABELS.keys())
        phase_idx   = phase_opts.index(log.get('phase', 'IMPLEMENTATION')) if log.get('phase') in phase_opts else 0
        phase_sel   = lc2.selectbox("Phase", phase_opts, index=phase_idx)
        is_on_site  = lc3.checkbox("On-site", value=bool(log.get('is_on_site')))

        presales_alloc = log.get('presales_allocation')
        if phase_sel == 'PRE_SALES':
            alloc_opts     = ['PENDING', 'SGA', 'COGS']
            alloc_idx      = alloc_opts.index(presales_alloc) if presales_alloc in alloc_opts else 0
            presales_alloc = st.selectbox("Pre-sales Allocation", alloc_opts, index=alloc_idx)

        description_v = st.text_input("Description", value=log.get('description') or '')
        col_save, col_del = st.columns(2)
        save   = col_save.form_submit_button("💾 Update",  type="primary", use_container_width=True)
        delete = col_del.form_submit_button("🗑 Delete", use_container_width=True)

    if save:
        ok = update_labor_log(log_id, {
            'work_date': work_date, 'man_days': man_days_v, 'daily_rate': daily_rate_v,
            'phase': phase_sel, 'description': description_v or None,
            'is_on_site': 1 if is_on_site else 0,
            'employee_level': level_sel or None, 'presales_allocation': presales_alloc,
        }, user_id)
        if ok:
            st.success("Updated!")
            st.rerun()
        else:
            st.error("Update failed — entry may already be approved.")
    if delete:
        ok = soft_delete_labor_log(log_id, user_id)
        if ok:
            st.success("Deleted!")
            st.rerun()
        else:
            st.error("Delete failed — entry may already be approved.")


# ══════════════════════════════════════════════════════════════════════════════
# DIALOGS — Expenses
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("🧾 Add Expense", width="large")
def _dialog_add_expense(pid: int):
    cur_opts    = [c['code'] for c in currencies]
    _r1, _r2, _ = st.columns([2, 2, 2])
    _vnd_idx    = cur_opts.index('VND') if 'VND' in cur_opts else 0
    exp_cur     = _r1.selectbox("Currency", cur_opts, index=_vnd_idx, key="dlg_add_exp_cur")
    exp_cur_id  = currencies[cur_opts.index(exp_cur)]['id']

    _rate_result = get_rate_to_vnd(exp_cur)
    fetched_rate = _rate_result.rate
    _icon, _msg  = rate_status(_rate_result)
    if _rate_result.ok:
        _r2.success(f"{_icon} {_msg}")
    else:
        _r2.warning(f"{_icon} {_msg}")
    st.divider()

    with st.form("expense_add_form", clear_on_submit=True):
        ea1, ea2, ea3 = st.columns(3)
        exp_date  = ea1.date_input("Date", value=date.today())
        exp_cat   = ea2.selectbox("Category", EXPENSE_CATEGORIES)
        exp_phase = ea3.selectbox("Phase", list(PHASE_LABELS.keys()),
                                   index=list(PHASE_LABELS.keys()).index('IMPLEMENTATION'))

        eb1, eb2 = st.columns(2)
        emp_opts   = [e['full_name'] for e in employees]
        exp_emp    = eb1.selectbox("Employee", emp_opts)
        exp_emp_id = employees[emp_opts.index(exp_emp)]['id']
        exp_amount = eb2.number_input("Amount", value=0.0, min_value=0.0, format="%.0f")

        exp_rate = st.number_input(f"Exchange Rate (1 {exp_cur} = ? VND)",
                                    value=fetched_rate, min_value=0.0, format="%.2f",
                                    help="Rate auto-fetched from API. Override if needed.")
        if exp_amount > 0 and exp_rate > 0:
            st.caption(f"💱 Converted: {exp_amount:,.0f} {exp_cur} × {exp_rate:,.2f} = **{exp_amount * exp_rate:,.0f} VND**")

        ec1, ec2 = st.columns(2)
        exp_vendor  = _vendor_selector(ec1, key_suffix="add")
        exp_receipt = ec2.text_input("Receipt Number")
        exp_desc    = st.text_input("Description")

        st.divider()
        uploaded_file = st.file_uploader("📎 Attach document (invoice, receipt...)",
                                          type=["pdf", "jpg", "jpeg", "png", "xlsx", "docx", "doc", "xls", "pptx", "csv", "zip"])
        submitted = st.form_submit_button("✅ Save expense", type="primary", use_container_width=True)

    if submitted:
        if exp_amount <= 0:
            st.error("Amount must be > 0.")
            return
        try:
            expense_id = create_expense({
                'project_id': pid, 'employee_id': exp_emp_id,
                'expense_date': exp_date, 'category': exp_cat, 'phase': exp_phase,
                'amount': exp_amount, 'currency_id': exp_cur_id, 'exchange_rate': exp_rate,
                'description': exp_desc or None, 'vendor_name': exp_vendor or None,
                'receipt_number': exp_receipt or None,
            }, user_id)
            if uploaded_file and expense_id:
                s3 = _get_s3()
                if s3:
                    ok, s3_key = s3.upload_expense_attachment(uploaded_file.read(), uploaded_file.name, pid, expense_id)
                    if ok:
                        create_expense_media(expense_id, s3_key, uploaded_file.name, created_by=user_id)
                    else:
                        st.warning(f"Expense saved but file upload failed: {s3_key}")
            st.success("✅ Expense added!")
            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")


@st.dialog("🧾 Edit Expense", width="large")
def _dialog_edit_expense(exp: dict, pid: int):
    exp_id = exp['id']
    cur_opts   = [c['code'] for c in currencies]
    cur_code   = exp.get('currency', 'VND')
    cur_idx    = cur_opts.index(cur_code) if cur_code in cur_opts else 0
    _r1, _r2   = st.columns(2)
    exp_cur    = _r1.selectbox("Currency", cur_opts, index=cur_idx, key="dlg_edit_exp_cur")
    exp_cur_id = currencies[cur_opts.index(exp_cur)]['id']

    _rate_result  = get_rate_to_vnd(exp_cur)
    fetched_rate  = _rate_result.rate
    saved_rate    = float(exp.get('exchange_rate') or fetched_rate)
    default_rate  = saved_rate if exp_cur == cur_code else fetched_rate

    _icon, _msg = rate_status(_rate_result)
    if _rate_result.ok:
        _r2.success(f"{_icon} {_msg}")
    else:
        _r2.warning(f"{_icon} {_msg}")
    st.divider()

    with st.form("expense_edit_form"):
        ea1, ea2, ea3 = st.columns(3)
        exp_date  = ea1.date_input("Date",
                     value=pd.to_datetime(exp.get('expense_date')).date() if exp.get('expense_date') else date.today())
        cat_idx   = EXPENSE_CATEGORIES.index(exp['category']) if exp.get('category') in EXPENSE_CATEGORIES else 0
        exp_cat   = ea2.selectbox("Category", EXPENSE_CATEGORIES, index=cat_idx)
        phase_keys = list(PHASE_LABELS.keys())
        phase_idx  = phase_keys.index(exp['phase']) if exp.get('phase') in phase_keys else 0
        exp_phase  = ea3.selectbox("Phase", phase_keys, index=phase_idx)

        eb1, eb2 = st.columns(2)
        emp_opts   = [e['full_name'] for e in employees]
        cur_emp_nm = exp.get('employee_name', emp_opts[0])
        cur_emp_i  = emp_opts.index(cur_emp_nm) if cur_emp_nm in emp_opts else 0
        exp_emp    = eb1.selectbox("Employee", emp_opts, index=cur_emp_i)
        exp_emp_id = employees[emp_opts.index(exp_emp)]['id']
        exp_amount = eb2.number_input("Amount", value=float(exp.get('amount', 0)), min_value=0.0, format="%.0f")

        exp_rate = st.number_input(f"Exchange Rate (1 {exp_cur} = ? VND)",
                                    value=default_rate, min_value=0.0, format="%.2f")
        if exp_amount > 0 and exp_rate > 0:
            st.caption(f"💱 Converted: {exp_amount:,.0f} {exp_cur} × {exp_rate:,.2f} = **{exp_amount * exp_rate:,.0f} VND**")

        ec1, ec2 = st.columns(2)
        exp_vendor  = _vendor_selector(ec1, current_name=exp.get('vendor_name') or '', key_suffix="edit")
        exp_receipt = ec2.text_input("Receipt Number", value=exp.get('receipt_number') or '')
        exp_desc    = st.text_input("Description", value=exp.get('description') or '')

        st.divider()
        cur_medias = get_expense_medias(exp_id)
        if cur_medias:
            st.info(f"📎 Current: **{cur_medias[0]['filename']}**" +
                    (f" (+{len(cur_medias)-1} more)" if len(cur_medias) > 1 else ""))
        new_file = st.file_uploader("📎 Add attachment (existing files kept)",
                                     type=["pdf", "jpg", "jpeg", "png", "xlsx", "docx", "doc", "xls", "pptx", "csv", "zip"])

        col_save, col_del = st.columns(2)
        save   = col_save.form_submit_button("💾 Update",  type="primary", use_container_width=True)
        delete = col_del.form_submit_button("🗑 Delete", use_container_width=True)

    if save:
        ok = update_expense(exp_id, {
            'expense_date': exp_date, 'category': exp_cat, 'phase': exp_phase,
            'amount': exp_amount, 'currency_id': exp_cur_id, 'exchange_rate': exp_rate,
            'description': exp_desc or None, 'vendor_name': exp_vendor or None,
            'receipt_number': exp_receipt or None, 'employee_id': exp_emp_id,
        }, user_id)
        if ok:
            if new_file:
                s3 = _get_s3()
                if s3:
                    ok2, s3_key = s3.upload_expense_attachment(new_file.read(), new_file.name, pid, exp_id)
                    if ok2:
                        create_expense_media(exp_id, s3_key, new_file.name, created_by=user_id)
            st.success("Updated!")
            st.rerun()
        else:
            st.error("Update failed — expense may already be approved.")
    if delete:
        ok = soft_delete_expense(exp_id, user_id)
        if ok:
            st.success("Deleted!")
            st.rerun()
        else:
            st.error("Delete failed.")


@st.dialog("📎 View Attachment", width="large")
def _dialog_view_attachment(s3_key: str, filename: str):
    s3 = _get_s3()
    if not s3:
        st.error("S3 is not available.")
        return
    with st.spinner("Generating download link..."):
        url = s3.get_presigned_url(s3_key, expiration=600)
    if not url:
        st.error("Could not generate URL — check S3 configuration.")
        return
    st.markdown(f"**File:** `{filename}`")
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext in ('jpg', 'jpeg', 'png'):
        st.image(url, use_container_width=True)
    elif ext == 'pdf':
        st.markdown(f"[📄 Open PDF in new tab]({url})")
        st.components.v1.iframe(url, height=600, scrolling=True)
    else:
        st.markdown(f"[⬇️ Download `{filename}`]({url})")
    st.caption("Link expires after 10 minutes.")


# ══════════════════════════════════════════════════════════════════════════════
# DIALOGS — Pre-sales
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("🔍 Add Pre-sales Cost", width="large")
def _dialog_add_presales(pid: int):
    pa1, pa2 = st.columns(2)
    ps_layer_lb = pa1.radio("Layer",
        ["STANDARD (Layer 1 → SGA)", "SPECIAL (Layer 2 → COGS if win)"],
        horizontal=True, key="dlg_ps_layer")
    ps_layer_v  = "STANDARD" if "STANDARD" in ps_layer_lb else "SPECIAL"
    cat_list    = PRESALES_CATEGORIES_L1 if ps_layer_v == "STANDARD" else PRESALES_CATEGORIES_L2
    ps_cat      = pa2.selectbox("Category", cat_list, key="dlg_ps_cat")

    ps_cur_opts = [c['code'] for c in currencies]
    _pc1, _pc2  = st.columns(2)
    ps_cur      = _pc1.selectbox("Currency", ps_cur_opts, key="dlg_ps_cur")
    ps_cur_id   = currencies[ps_cur_opts.index(ps_cur)]['id']
    _ps_rate_result = get_rate_to_vnd(ps_cur)
    fetched_rate    = _ps_rate_result.rate
    _icon, _msg     = rate_status(_ps_rate_result)
    if _ps_rate_result.ok:
        _pc2.success(f"{_icon} {_msg}")
    else:
        _pc2.warning(f"{_icon} {_msg}")
    st.divider()

    with st.form("presales_add_form", clear_on_submit=True):
        pb1, pb2 = st.columns(2)
        is_ps_subcon = pb1.checkbox("External worker", value=False)
        if not is_ps_subcon:
            ps_emp_opts = [e['full_name'] for e in employees]
            ps_emp      = pb2.selectbox("Employee", ps_emp_opts)
            ps_emp_id   = employees[ps_emp_opts.index(ps_emp)]['id']
            ps_subcon   = None
        else:
            ps_emp_id = None
            ps_subcon = pb2.text_input("Subcontractor Name *")

        pc1, pc2, pc3 = st.columns(3)
        ps_amount = pc1.number_input("Amount", value=0.0, min_value=0.0, format="%.0f")
        ps_rate   = pc2.number_input(f"Exchange Rate (1 {ps_cur} = ? VND)",
                                      value=fetched_rate, min_value=0.0, format="%.2f")
        ps_days   = pc3.number_input("Man-Days (optional)", value=0.0, min_value=0.0, format="%.1f")
        if ps_amount > 0 and ps_rate > 0:
            st.caption(f"💱 Converted: {ps_amount:,.0f} {ps_cur} × {ps_rate:,.2f} = **{ps_amount * ps_rate:,.0f} VND**")

        alloc_opts    = ['PENDING', 'SGA', 'COGS']
        default_alloc = 'SGA' if ps_layer_v == 'STANDARD' else 'PENDING'
        ps_alloc      = st.selectbox("Allocation", alloc_opts, index=alloc_opts.index(default_alloc))
        ps_desc       = st.text_input("Description")
        submitted = st.form_submit_button("✅ Save", type="primary", use_container_width=True)

    if submitted:
        if ps_amount <= 0:
            st.error("Amount must be > 0.")
            return
        if is_ps_subcon and not ps_subcon:
            st.error("Subcontractor name required.")
            return
        try:
            create_presales_cost({
                'project_id': pid, 'employee_id': ps_emp_id,
                'subcontractor_name': ps_subcon, 'cost_layer': ps_layer_v,
                'category': ps_cat, 'amount': ps_amount, 'currency_id': ps_cur_id,
                'exchange_rate': ps_rate, 'allocation': ps_alloc,
                'man_days': ps_days if ps_days > 0 else None,
                'description': ps_desc or None,
            }, user_id)
            st.success("✅ Pre-sales cost added!")
            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# OVERVIEW — All Projects Dashboard
# ══════════════════════════════════════════════════════════════════════════════

def _render_overview(labor_df: pd.DataFrame, exp_df: pd.DataFrame):
    """Cross-project dashboard: KPIs + per-project summary + pending approvals."""

    approved_labor = labor_df[labor_df['approval_status'] == 'APPROVED'] if not labor_df.empty else labor_df
    approved_exp   = exp_df[exp_df['approval_status'] == 'APPROVED'] if not exp_df.empty else exp_df
    pending_labor  = labor_df[labor_df['approval_status'] == 'PENDING'] if not labor_df.empty else labor_df
    pending_exp    = exp_df[exp_df['approval_status'] == 'PENDING'] if not exp_df.empty else exp_df

    # ── KPIs ─────────────────────────────────────────────────────────────────
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Man-Days (Approved)", f"{approved_labor['man_days'].sum():.1f}" if not approved_labor.empty else "0")
    k2.metric("Labor Cost (Approved)", fmt_vnd(approved_labor['amount'].sum() if not approved_labor.empty else 0))
    k3.metric("Expenses (Approved)", fmt_vnd(approved_exp['amount_vnd'].sum() if not approved_exp.empty else 0))
    k4.metric("Pending Items", len(pending_labor) + len(pending_exp))

    st.divider()

    # ── Per-project summary ──────────────────────────────────────────────────
    st.subheader("📊 Per-Project Cost Summary")

    summary_rows = []
    for _, row in proj_df.iterrows():
        pid = row['project_id']
        p_labor = approved_labor[approved_labor['project_id'] == pid] if not approved_labor.empty else pd.DataFrame()
        p_exp   = approved_exp[approved_exp['project_id'] == pid] if not approved_exp.empty else pd.DataFrame()
        p_pend_l = pending_labor[pending_labor['project_id'] == pid] if not pending_labor.empty else pd.DataFrame()
        p_pend_e = pending_exp[pending_exp['project_id'] == pid] if not pending_exp.empty else pd.DataFrame()

        labor_cost = float(p_labor['amount'].sum()) if not p_labor.empty else 0
        exp_cost   = float(p_exp['amount_vnd'].sum()) if not p_exp.empty else 0

        if labor_cost == 0 and exp_cost == 0 and len(p_pend_l) == 0 and len(p_pend_e) == 0:
            continue

        summary_rows.append({
            'Project':    row['project_code'],
            'Name':       row['project_name'],
            'Status':     row['status'],
            'Man-Days':   f"{p_labor['man_days'].sum():.1f}" if not p_labor.empty else "0",
            'Labor Cost': f"{labor_cost:,.0f}" if labor_cost > 0 else '—',
            'Expenses':   f"{exp_cost:,.0f}" if exp_cost > 0 else '—',
            'Total':      f"{labor_cost + exp_cost:,.0f}" if (labor_cost + exp_cost) > 0 else '—',
            'Pending':    len(p_pend_l) + len(p_pend_e),
        })

    if summary_rows:
        st.dataframe(
            pd.DataFrame(summary_rows), width="stretch", hide_index=True,
            column_config={
                'Project':    st.column_config.TextColumn('Project', width=150),
                'Name':       st.column_config.TextColumn('Name'),
                'Status':     st.column_config.TextColumn('Status', width=120),
                'Man-Days':   st.column_config.TextColumn('Man-Days', width=90),
                'Labor Cost': st.column_config.TextColumn('Labor (VND)'),
                'Expenses':   st.column_config.TextColumn('Expenses (VND)'),
                'Total':      st.column_config.TextColumn('Total (VND)'),
                'Pending':    st.column_config.NumberColumn('Pending', width=80),
            },
        )
    else:
        st.info("No cost data found for the selected filters.")

    # ── Pending Approvals (PM only) ──────────────────────────────────────────
    if is_admin and (len(pending_labor) > 0 or len(pending_exp) > 0):
        st.divider()
        st.subheader("⏳ Pending Approvals")

        ptab_labor, ptab_exp = st.tabs([
            f"👷 Labor ({len(pending_labor)})",
            f"🧾 Expenses ({len(pending_exp)})",
        ])

        with ptab_labor:
            if not pending_labor.empty:
                display_pl = pending_labor[['project_code', 'work_date', 'phase', 'worker',
                                             'man_days', 'amount', 'description']].copy()
                display_pl['amount_fmt'] = display_pl['amount'].apply(
                    lambda v: f"{v:,.0f}" if v is not None and str(v) not in ('', 'nan', 'None') else '—')
                st.dataframe(display_pl, width="stretch", hide_index=True,
                             column_config={
                                 'project_code': st.column_config.TextColumn('Project', width=150),
                                 'work_date':    st.column_config.DateColumn('Date'),
                                 'phase':        st.column_config.TextColumn('Phase'),
                                 'worker':       st.column_config.TextColumn('Worker'),
                                 'man_days':     st.column_config.NumberColumn('Days', format="%.1f"),
                                 'amount_fmt':   st.column_config.TextColumn('Amount'),
                                 'description':  st.column_config.TextColumn('Description'),
                                 'amount':       None,
                             })
                if st.button(f"✅ Approve All Pending Labor ({len(pending_labor)})", key="bulk_approve_labor_all"):
                    for lid in pending_labor['id'].tolist():
                        approve_labor_log(lid, emp_int_id)
                    st.success(f"Approved {len(pending_labor)} labor entries.")
                    st.rerun()
            else:
                st.info("No pending labor entries.")

        with ptab_exp:
            if not pending_exp.empty:
                display_pe = pending_exp[['project_code', 'expense_date', 'category', 'phase',
                                           'employee_name', 'amount', 'currency', 'amount_vnd']].copy()
                display_pe['amount_fmt']     = display_pe['amount'].apply(
                    lambda v: f"{v:,.0f}" if v is not None and str(v) not in ('', 'nan', 'None') else '—')
                display_pe['amount_vnd_fmt'] = display_pe['amount_vnd'].apply(
                    lambda v: f"{v:,.0f}" if v is not None and str(v) not in ('', 'nan', 'None') else '—')
                st.dataframe(display_pe, width="stretch", hide_index=True,
                             column_config={
                                 'project_code':  st.column_config.TextColumn('Project', width=150),
                                 'expense_date':  st.column_config.DateColumn('Date'),
                                 'category':      st.column_config.TextColumn('Category'),
                                 'phase':         st.column_config.TextColumn('Phase'),
                                 'employee_name': st.column_config.TextColumn('Employee'),
                                 'amount_fmt':    st.column_config.TextColumn('Amount'),
                                 'currency':      st.column_config.TextColumn('CCY', width=50),
                                 'amount_vnd_fmt':st.column_config.TextColumn('VND'),
                                 'amount':        None,
                                 'amount_vnd':    None,
                             })
                if st.button(f"✅ Approve All Pending Expenses ({len(pending_exp)})", key="bulk_approve_exp_all"):
                    for eid in pending_exp['id'].tolist():
                        approve_expense(eid, emp_int_id)
                    st.success(f"Approved {len(pending_exp)} expenses.")
                    st.rerun()
            else:
                st.info("No pending expenses.")


# ══════════════════════════════════════════════════════════════════════════════
# LABOR TABLE — Per-project
# ══════════════════════════════════════════════════════════════════════════════

def _render_labor_tab(pid: int, labor_df: pd.DataFrame):
    approved_df = labor_df[labor_df['approval_status'] == 'APPROVED'] if not labor_df.empty else labor_df
    k1, k2, k3 = st.columns(3)
    k1.metric("Man-Days (Approved)", f"{approved_df['man_days'].sum():.1f}" if not approved_df.empty else "0")
    k2.metric("Labor Cost (Approved)", fmt_vnd(approved_df['amount'].sum() if not approved_df.empty else 0))
    k3.metric("Pending", int((labor_df['approval_status'] == 'PENDING').sum()) if not labor_df.empty else 0)

    if labor_df.empty:
        st.info("No labor entries yet.")
        return

    display_df = labor_df.copy()
    display_df['daily_rate_fmt'] = display_df['daily_rate'].apply(
        lambda v: f"{v:,.0f}" if v is not None and str(v) not in ('', 'nan', 'None') else '—')
    display_df['amount_fmt'] = display_df['amount'].apply(
        lambda v: f"{v:,.0f}" if v is not None and str(v) not in ('', 'nan', 'None') else '—')

    col_config = {
        'id':                  st.column_config.NumberColumn('ID', width=55),
        'work_date':           st.column_config.DateColumn('Date'),
        'phase':               st.column_config.TextColumn('Phase'),
        'worker':              st.column_config.TextColumn('Worker'),
        'employee_level':      st.column_config.TextColumn('Level'),
        'man_days':            st.column_config.NumberColumn('Days', format="%.1f"),
        'daily_rate_fmt':      st.column_config.TextColumn('Rate'),
        'amount_fmt':          st.column_config.TextColumn('Amount'),
        'is_on_site':          st.column_config.CheckboxColumn('On-site'),
        'presales_allocation': st.column_config.TextColumn('Pre-sales'),
        'approval_status':     st.column_config.TextColumn('Status'),
        'description':         st.column_config.TextColumn('Description'),
        'daily_rate': None, 'amount': None,
        'project_id': None, 'project_code': None,
        'approved_by_name': None, 'approved_date': None,
    }

    tbl_key = f"labor_tbl_{st.session_state.get('_labor_key', 0)}"
    event = st.dataframe(display_df, key=tbl_key, width="stretch", hide_index=True,
                         on_select="rerun", selection_mode="single-row", column_config=col_config)

    sel = event.selection.rows
    if sel:
        row = labor_df.iloc[sel[0]].to_dict()
        st.markdown(f"**Selected:** ID {row['id']} — {row['worker']} ({row['phase']}, {row['approval_status']})")
        ab1, ab2, ab3, ab4 = st.columns(4)
        if row.get('approval_status') == 'PENDING':
            # Edit: PM can edit any, others can edit own entry only
            _can_edit = (
                ctx.can('cost.edit_any', pid)
                or (ctx.can('cost.edit_own', pid) and str(row.get('created_by', '')) == user_id)
            )
            if _can_edit:
                if ab1.button("✏️ Edit", key="labor_edit_btn", use_container_width=True):
                    _dialog_edit_labor(row, pid)
            # Approve: PM of THIS project only (not global manager)
            if ctx.can('cost.approve', pid):
                if ab2.button("✅ Approve", key="labor_approve_btn", use_container_width=True):
                    approve_labor_log(row['id'], emp_int_id)
                    st.success("Approved!")
                    st.rerun()
        if ab3.button("✖ Deselect", key="labor_desel_btn", use_container_width=True):
            st.session_state["_labor_key"] = st.session_state.get("_labor_key", 0) + 1
            st.rerun()

    # Bulk approve — PM of THIS project only
    if ctx.can('cost.bulk_approve', pid):
        pending_ids = labor_df[labor_df['approval_status'] == 'PENDING']['id'].tolist()
        if pending_ids:
            if st.button(f"✅ Approve All Pending ({len(pending_ids)})", key="bulk_approve_labor"):
                for lid in pending_ids:
                    approve_labor_log(lid, emp_int_id)
                st.success(f"Approved {len(pending_ids)} entries.")
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# EXPENSE TABLE — Per-project
# ══════════════════════════════════════════════════════════════════════════════

def _render_expense_tab(pid: int, exp_df: pd.DataFrame):
    approved_exp = exp_df[exp_df['approval_status'] == 'APPROVED'] if not exp_df.empty else exp_df
    ek1, ek2, ek3 = st.columns(3)
    ek1.metric("Total Expenses (Approved)", fmt_vnd(approved_exp['amount_vnd'].sum() if not approved_exp.empty else 0))
    ek2.metric("Transactions", len(approved_exp))
    ek3.metric("Pending", int((exp_df['approval_status'] == 'PENDING').sum()) if not exp_df.empty else 0)

    if exp_df.empty:
        st.info("No expenses yet.")
        return

    display_df = exp_df.copy()
    display_df['amount_fmt'] = display_df['amount'].apply(
        lambda v: f"{v:,.0f}" if v is not None and str(v) not in ('', 'nan', 'None') else '—')
    display_df['amount_vnd_fmt'] = display_df['amount_vnd'].apply(
        lambda v: f"{v:,.0f}" if v is not None and str(v) not in ('', 'nan', 'None') else '—')

    col_config = {
        'id':              st.column_config.NumberColumn('ID', width=55),
        'expense_date':    st.column_config.DateColumn('Date'),
        'category':        st.column_config.TextColumn('Category'),
        'phase':           st.column_config.TextColumn('Phase'),
        'employee_name':   st.column_config.TextColumn('Employee'),
        'amount_fmt':      st.column_config.TextColumn('Amount'),
        'currency':        st.column_config.TextColumn('CCY', width=50),
        'amount_vnd_fmt':  st.column_config.TextColumn('VND'),
        'vendor_name':     st.column_config.TextColumn('Vendor'),
        'receipt_number':  st.column_config.TextColumn('Receipt#'),
        'approval_status': st.column_config.TextColumn('Status'),
        'description':     st.column_config.TextColumn('Description'),
        'amount': None, 'amount_vnd': None, 'exchange_rate': None,
        'project_id': None, 'project_code': None,
        'approved_by_name': None,
    }

    tbl_key = f"exp_tbl_{st.session_state.get('_exp_key', 0)}"
    event = st.dataframe(display_df, key=tbl_key, width="stretch", hide_index=True,
                         on_select="rerun", selection_mode="single-row", column_config=col_config)

    sel = event.selection.rows
    if sel:
        row = exp_df.iloc[sel[0]].to_dict()
        st.markdown(f"**Selected:** ID {row['id']} — {row.get('employee_name', '—')} ({row['category']}, {row['approval_status']})")
        ab1, ab2, ab3, ab4 = st.columns(4)
        if row.get('approval_status') == 'PENDING':
            # Edit: PM can edit any, others can edit own entry only
            _can_edit = (
                ctx.can('cost.edit_any', pid)
                or (ctx.can('cost.edit_own', pid) and str(row.get('created_by', '')) == user_id)
            )
            if _can_edit:
                if ab1.button("✏️ Edit", key="exp_edit_btn", use_container_width=True):
                    _dialog_edit_expense(row, pid)
            # Approve: PM of THIS project only
            if ctx.can('cost.approve', pid):
                if ab2.button("✅ Approve", key="exp_approve_btn", use_container_width=True):
                    approve_expense(row['id'], emp_int_id)
                    st.success("Approved!")
                    st.rerun()
        if ab3.button("✖ Deselect", key="exp_desel_btn", use_container_width=True):
            st.session_state["_exp_key"] = st.session_state.get("_exp_key", 0) + 1
            st.rerun()

    # Bulk approve — PM of THIS project only
    if ctx.can('cost.bulk_approve', pid):
        pending_exp = exp_df[exp_df['approval_status'] == 'PENDING']['id'].tolist()
        if pending_exp:
            if st.button(f"✅ Approve All Pending ({len(pending_exp)})", key="bulk_approve_exp"):
                for eid in pending_exp:
                    approve_expense(eid, emp_int_id)
                st.success(f"Approved {len(pending_exp)} expenses.")
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PRE-SALES TABLE — Per-project
# ══════════════════════════════════════════════════════════════════════════════

def _render_presales_tab(pid: int):
    ph1, ph2 = st.columns([5, 1])
    if ph2.button("➕ Add", type="primary", use_container_width=True, key="btn_add_presales"):
        _dialog_add_presales(pid)

    ps_df = get_presales_costs_df(pid)

    if not ps_df.empty:
        l1_total = ps_df[ps_df['cost_layer'] == 'STANDARD']['amount_vnd'].sum()
        l2_total = ps_df[ps_df['cost_layer'] == 'SPECIAL']['amount_vnd'].sum()
        l2_cogs  = ps_df[(ps_df['cost_layer'] == 'SPECIAL') & (ps_df['allocation'] == 'COGS')]['amount_vnd'].sum()
        pk1, pk2, pk3 = st.columns(3)
        pk1.metric("Layer 1 — SG&A",  fmt_vnd(l1_total))
        pk2.metric("Layer 2 — Total", fmt_vnd(l2_total))
        pk3.metric("Layer 2 → COGS",  fmt_vnd(l2_cogs))

        display_df = ps_df.copy()
        display_df['amount_fmt']     = display_df['amount'].apply(
            lambda v: f"{v:,.0f}" if v is not None and str(v) not in ('', 'nan', 'None') else '—')
        display_df['amount_vnd_fmt'] = display_df['amount_vnd'].apply(
            lambda v: f"{v:,.0f}" if v is not None and str(v) not in ('', 'nan', 'None') else '—')
        display_df.insert(0, '●', display_df['allocation'].map(
            lambda a: {'SGA': '🔵', 'COGS': '🟢', 'PENDING': '⚪'}.get(a, '⚪')))
        st.dataframe(display_df, width="stretch", hide_index=True,
                     column_config={
                         '●':              st.column_config.TextColumn('', width=30),
                         'cost_layer':     st.column_config.TextColumn('Layer'),
                         'category':       st.column_config.TextColumn('Category'),
                         'worker':         st.column_config.TextColumn('Worker'),
                         'amount_fmt':     st.column_config.TextColumn('Amount'),
                         'currency':       st.column_config.TextColumn('CCY', width=50),
                         'amount_vnd_fmt': st.column_config.TextColumn('VND'),
                         'man_days':       st.column_config.NumberColumn('Man-Days', format="%.1f"),
                         'allocation':     st.column_config.TextColumn('Allocation'),
                         'description':    st.column_config.TextColumn('Description'),
                         'amount': None, 'amount_vnd': None,
                     })
    else:
        st.info("No pre-sales costs yet.")

    if ctx.can('cost.presales_decide', pid):
        st.divider()
        st.markdown("**Win/Lose Decision — Layer 2 allocation**")
        dc1, dc2, _ = st.columns(3)
        if dc1.button("🏆 WIN — Move Layer 2 → COGS", type="primary"):
            n = bulk_update_presales_allocation(pid, 'COGS', user_id)
            st.success(f"Updated {n} Layer-2 costs → COGS.")
            st.rerun()
        if dc2.button("❌ LOSE — Move Layer 2 → SGA"):
            n = bulk_update_presales_allocation(pid, 'SGA', user_id)
            st.info(f"Updated {n} Layer-2 costs → SGA.")
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN CONTENT
# ══════════════════════════════════════════════════════════════════════════════

if is_all_projects:
    # ── Overview mode ─────────────────────────────────────────────────────────
    if not ctx.can('cost.view_overview'):
        st.warning("⛔ Bạn không có quyền xem tổng quan cross-project. Vui lòng chọn một dự án cụ thể.")
        st.stop()
    all_labor = get_labor_logs_df(
        phase=phase_filter,
        approval_status=approval_filter,
        date_from=date_from,
        date_to=date_to,
    )
    all_exp = get_expenses_df(
        phase=phase_filter,
        approval_status=approval_filter,
        date_from=date_from,
        date_to=date_to,
    )
    _render_overview(all_labor, all_exp)

else:
    # ── Per-project mode ──────────────────────────────────────────────────────
    if not project:
        st.error("Project not found.")
        st.stop()

    st.caption(
        f"**{project['project_code']}** | "
        f"{project.get('customer_name') or project.get('end_customer_name', '—')} | "
        f"Status: **{project['status']}**"
    )

    # Fetch data with sidebar filters
    labor_df = get_labor_logs_df(
        project_id=project_id,
        phase=phase_filter,
        approval_status=approval_filter,
        date_from=date_from,
        date_to=date_to,
    )
    exp_df = get_expenses_df(
        project_id=project_id,
        phase=phase_filter,
        approval_status=approval_filter,
        date_from=date_from,
        date_to=date_to,
    )

    tab_labor, tab_exp, tab_presales = st.tabs(["👷 Labor Logs", "🧾 Expenses", "🔍 Pre-sales Costs"])

    with tab_labor:
        _render_labor_tab(project_id, labor_df)

    with tab_exp:
        _render_expense_tab(project_id, exp_df)

    with tab_presales:
        _render_presales_tab(project_id)


# ── Dialog triggers (from sidebar buttons) ────────────────────────────────────
if st.session_state.pop("open_add_labor", False) and project_id:
    _dialog_add_labor(project_id)

if st.session_state.pop("open_add_expense", False) and project_id:
    _dialog_add_expense(project_id)