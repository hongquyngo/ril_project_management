# pages/IL_3_⏱️_Cost_Tracking.py
"""
Cost Tracking — Labor Logs / Expenses / Pre-sales Costs
UX: @st.dialog cho CRUD forms | @st.fragment cho tables | S3 cho chứng từ đính kèm
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
    update_expense_attachment, update_labor_attachment,
    fmt_vnd, PHASE_LABELS,
)
from utils.il_project.helpers import (
    EXPENSE_CATEGORIES, PRESALES_CATEGORIES_L1, PRESALES_CATEGORIES_L2,
    EMPLOYEE_LEVELS, DEFAULT_RATES_BY_LEVEL,
)
from utils.il_project.s3_il import ILProjectS3Manager

logger = logging.getLogger(__name__)
auth = AuthManager()

st.set_page_config(page_title="Cost Tracking", page_icon="⏱️", layout="wide")
auth.require_auth()
user_id    = str(auth.get_user_id())
emp_int_id = auth.get_user_id()
is_pm      = st.session_state.get('user_role') in ('admin', 'manager')


# ── Lookups (cached) ──────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load():
    return get_projects_df(), get_employees(), get_currencies()

proj_df, employees, currencies = _load()
emp_map = {e['id']: e['full_name'] for e in employees}
cur_map = {c['id']: c['code'] for c in currencies}


# ── S3 (cached per session, lazy init) ───────────────────────────────────────
@st.cache_resource
def _get_s3():
    try:
        return ILProjectS3Manager()
    except Exception as e:
        logger.warning(f"S3 not available: {e}")
        return None


# ── Page header ───────────────────────────────────────────────────────────────
st.title("⏱️ Cost Tracking")

if proj_df.empty:
    st.warning("No projects found.")
    st.stop()

proj_options = [f"{r.project_code} — {r.project_name}" for r in proj_df.itertuples()]
sel_label    = st.selectbox("Select Project", proj_options)
project_id   = int(proj_df.iloc[proj_options.index(sel_label)]['project_id'])
project      = get_project(project_id)
if not project:
    st.error("Project not found.")
    st.stop()

st.caption(
    f"**{project['project_code']}** | "
    f"{project.get('customer_name') or project.get('end_customer_name', '—')} | "
    f"Status: **{project['status']}**"
)


# ══════════════════════════════════════════════════════════════════════════════
# DIALOGS — Labor
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("👷 Log Labor Entry", width="large")
def _dialog_add_labor(project_id: int):
    with st.form("labor_add_form", clear_on_submit=True):
        is_subcon = st.checkbox("External / Subcontractor", value=False)
        la1, la2  = st.columns(2)

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
        uploaded_file = st.file_uploader(
            "📎 Đính kèm chứng từ (tùy chọn)",
            type=["pdf", "jpg", "jpeg", "png", "xlsx", "docx"],
            help="Timesheet, email xác nhận, hoặc chứng từ liên quan",
        )

        submitted = st.form_submit_button("✅ Lưu entry", type="primary", use_container_width=True)

    if submitted:
        if is_subcon and not subcon_name:
            st.error("Subcontractor name required.")
            return
        try:
            log_id = create_labor_log({
                'project_id':            project_id,
                'employee_id':           worker_id,
                'employee_level':        level_sel or None,
                'subcontractor_name':    subcon_name,
                'subcontractor_company': subcon_co,
                'work_date':             work_date,
                'man_days':              man_days_v,
                'daily_rate':            daily_rate_v,
                'phase':                 phase_sel,
                'description':           description_v or None,
                'is_on_site':            1 if is_on_site else 0,
                'presales_allocation':   presales_alloc,
            }, user_id)

            if uploaded_file and log_id:
                s3 = _get_s3()
                if s3:
                    ok, s3_key = s3.upload_labor_attachment(
                        uploaded_file.read(), uploaded_file.name, project_id, log_id
                    )
                    if ok:
                        update_labor_attachment(log_id, s3_key, uploaded_file.name, user_id)
                    else:
                        st.warning(f"Entry đã lưu nhưng upload file thất bại: {s3_key}")

            st.success("✅ Labor entry added!")
            st.rerun()
        except Exception as e:
            st.error(f"Lỗi: {e}")


@st.dialog("👷 Edit Labor Entry", width="large")
def _dialog_edit_labor(log: dict, project_id: int):
    log_id = log['id']
    with st.form("labor_edit_form"):
        lb1, lb2, lb3 = st.columns(3)
        work_date    = lb1.date_input(
            "Work Date",
            value=pd.to_datetime(log.get('work_date')).date() if log.get('work_date') else date.today(),
        )
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
            'work_date':           work_date,
            'man_days':            man_days_v,
            'daily_rate':          daily_rate_v,
            'phase':               phase_sel,
            'description':         description_v or None,
            'is_on_site':          1 if is_on_site else 0,
            'employee_level':      level_sel or None,
            'presales_allocation': presales_alloc,
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
def _dialog_add_expense(project_id: int):
    with st.form("expense_add_form", clear_on_submit=True):
        ea1, ea2, ea3 = st.columns(3)
        exp_date  = ea1.date_input("Date", value=date.today())
        exp_cat   = ea2.selectbox("Category", EXPENSE_CATEGORIES)
        exp_phase = ea3.selectbox(
            "Phase", list(PHASE_LABELS.keys()),
            index=list(PHASE_LABELS.keys()).index('IMPLEMENTATION'),
        )

        eb1, eb2, eb3, eb4 = st.columns(4)
        emp_opts   = [e['full_name'] for e in employees]
        exp_emp    = eb1.selectbox("Employee", emp_opts)
        exp_emp_id = employees[emp_opts.index(exp_emp)]['id']
        exp_amount = eb2.number_input("Amount", value=0.0, min_value=0.0, format="%.0f")
        cur_opts   = [c['code'] for c in currencies]
        exp_cur    = eb3.selectbox("Currency", cur_opts)
        exp_cur_id = currencies[cur_opts.index(exp_cur)]['id']
        is_vnd     = (exp_cur == 'VND')
        exp_rate   = eb4.number_input("Exchange Rate", value=1.0 if is_vnd else 25_000.0, format="%.2f")

        ec1, ec2 = st.columns(2)
        exp_vendor  = ec1.text_input("Vendor Name")
        exp_receipt = ec2.text_input("Receipt Number")
        exp_desc    = st.text_input("Description")

        st.divider()
        uploaded_file = st.file_uploader(
            "📎 Đính kèm chứng từ (hóa đơn, receipt...)",
            type=["pdf", "jpg", "jpeg", "png", "xlsx"],
            help="Khuyến nghị đính kèm đầy đủ để phục vụ quyết toán",
        )

        submitted = st.form_submit_button("✅ Lưu expense", type="primary", use_container_width=True)

    if submitted:
        if exp_amount <= 0:
            st.error("Amount must be > 0.")
            return
        try:
            expense_id = create_expense({
                'project_id':     project_id,
                'employee_id':    exp_emp_id,
                'expense_date':   exp_date,
                'category':       exp_cat,
                'phase':          exp_phase,
                'amount':         exp_amount,
                'currency_id':    exp_cur_id,
                'exchange_rate':  exp_rate,
                'description':    exp_desc or None,
                'vendor_name':    exp_vendor or None,
                'receipt_number': exp_receipt or None,
            }, user_id)

            if uploaded_file and expense_id:
                s3 = _get_s3()
                if s3:
                    ok, s3_key = s3.upload_expense_attachment(
                        uploaded_file.read(), uploaded_file.name, project_id, expense_id
                    )
                    if ok:
                        update_expense_attachment(expense_id, s3_key, uploaded_file.name, user_id)
                    else:
                        st.warning(f"Expense đã lưu nhưng upload file thất bại: {s3_key}")

            st.success("✅ Expense added!")
            st.rerun()
        except Exception as e:
            st.error(f"Lỗi: {e}")


@st.dialog("🧾 Edit Expense", width="large")
def _dialog_edit_expense(exp: dict, project_id: int):
    exp_id = exp['id']
    with st.form("expense_edit_form"):
        ea1, ea2, ea3 = st.columns(3)
        exp_date  = ea1.date_input(
            "Date",
            value=pd.to_datetime(exp.get('expense_date')).date() if exp.get('expense_date') else date.today(),
        )
        cat_idx   = EXPENSE_CATEGORIES.index(exp['category']) if exp.get('category') in EXPENSE_CATEGORIES else 0
        exp_cat   = ea2.selectbox("Category", EXPENSE_CATEGORIES, index=cat_idx)
        phase_keys = list(PHASE_LABELS.keys())
        phase_idx  = phase_keys.index(exp['phase']) if exp.get('phase') in phase_keys else 0
        exp_phase  = ea3.selectbox("Phase", phase_keys, index=phase_idx)

        eb1, eb2, eb3, eb4 = st.columns(4)
        emp_opts   = [e['full_name'] for e in employees]
        cur_emp_nm = exp.get('employee_name', emp_opts[0])
        cur_emp_i  = emp_opts.index(cur_emp_nm) if cur_emp_nm in emp_opts else 0
        exp_emp    = eb1.selectbox("Employee", emp_opts, index=cur_emp_i)
        exp_emp_id = employees[emp_opts.index(exp_emp)]['id']
        exp_amount = eb2.number_input("Amount", value=float(exp.get('amount', 0)), min_value=0.0, format="%.0f")
        cur_opts   = [c['code'] for c in currencies]
        cur_code   = exp.get('currency', 'VND')
        cur_idx    = cur_opts.index(cur_code) if cur_code in cur_opts else 0
        exp_cur    = eb3.selectbox("Currency", cur_opts, index=cur_idx)
        exp_cur_id = currencies[cur_opts.index(exp_cur)]['id']
        exp_rate   = eb4.number_input("Exchange Rate", value=float(exp.get('exchange_rate', 1)), format="%.2f")

        ec1, ec2 = st.columns(2)
        exp_vendor  = ec1.text_input("Vendor Name",    value=exp.get('vendor_name') or '')
        exp_receipt = ec2.text_input("Receipt Number", value=exp.get('receipt_number') or '')
        exp_desc    = st.text_input("Description",     value=exp.get('description') or '')

        st.divider()
        cur_attachment = exp.get('attachment_filename')
        if cur_attachment:
            st.info(f"📎 Chứng từ hiện tại: **{cur_attachment}**")
        new_file = st.file_uploader(
            "📎 Thay thế chứng từ (để trống = giữ nguyên)",
            type=["pdf", "jpg", "jpeg", "png", "xlsx"],
        )

        col_save, col_del = st.columns(2)
        save   = col_save.form_submit_button("💾 Update",  type="primary", use_container_width=True)
        delete = col_del.form_submit_button("🗑 Delete", use_container_width=True)

    if save:
        ok = update_expense(exp_id, {
            'expense_date':   exp_date,
            'category':       exp_cat,
            'phase':          exp_phase,
            'amount':         exp_amount,
            'currency_id':    exp_cur_id,
            'exchange_rate':  exp_rate,
            'description':    exp_desc or None,
            'vendor_name':    exp_vendor or None,
            'receipt_number': exp_receipt or None,
            'employee_id':    exp_emp_id,
        }, user_id)
        if ok:
            if new_file:
                s3 = _get_s3()
                if s3:
                    ok2, s3_key = s3.upload_expense_attachment(
                        new_file.read(), new_file.name, project_id, exp_id
                    )
                    if ok2:
                        update_expense_attachment(exp_id, s3_key, new_file.name, user_id)
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


@st.dialog("📎 Xem chứng từ", width="large")
def _dialog_view_attachment(s3_key: str, filename: str):
    s3 = _get_s3()
    if not s3:
        st.error("S3 không khả dụng.")
        return
    with st.spinner("Đang tạo link xem file..."):
        url = s3.get_presigned_url(s3_key, expiration=600)
    if not url:
        st.error("Không thể tạo URL — kiểm tra lại cấu hình S3.")
        return

    st.markdown(f"**File:** `{filename}`")
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext in ('jpg', 'jpeg', 'png'):
        st.image(url, use_container_width=True)
    elif ext == 'pdf':
        st.markdown(f"[📄 Mở PDF trong tab mới]({url})")
        st.components.v1.iframe(url, height=600, scrolling=True)
    else:
        st.markdown(f"[⬇️ Tải về `{filename}`]({url})")
    st.caption("Link hết hạn sau 10 phút.")


# ══════════════════════════════════════════════════════════════════════════════
# DIALOGS — Pre-sales
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("🔍 Add Pre-sales Cost", width="large")
def _dialog_add_presales(project_id: int):
    with st.form("presales_add_form", clear_on_submit=True):
        pa1, pa2    = st.columns(2)
        ps_layer_lb = pa1.radio(
            "Layer",
            ["STANDARD (Layer 1 → SGA)", "SPECIAL (Layer 2 → COGS if win)"],
            horizontal=True,
        )
        ps_layer_v  = "STANDARD" if "STANDARD" in ps_layer_lb else "SPECIAL"
        cat_list    = PRESALES_CATEGORIES_L1 if ps_layer_v == "STANDARD" else PRESALES_CATEGORIES_L2
        ps_cat      = pa2.selectbox("Category", cat_list)

        pb1, pb2      = st.columns(2)
        is_ps_subcon  = pb1.checkbox("External worker", value=False)
        if not is_ps_subcon:
            ps_emp_opts = [e['full_name'] for e in employees]
            ps_emp      = pb2.selectbox("Employee", ps_emp_opts)
            ps_emp_id   = employees[ps_emp_opts.index(ps_emp)]['id']
            ps_subcon   = None
        else:
            ps_emp_id   = None
            ps_subcon   = pb2.text_input("Subcontractor Name *")

        pc1, pc2, pc3, pc4 = st.columns(4)
        ps_amount   = pc1.number_input("Amount", value=0.0, min_value=0.0, format="%.0f")
        ps_cur_opts = [c['code'] for c in currencies]
        ps_cur      = pc2.selectbox("Currency", ps_cur_opts)
        ps_cur_id   = currencies[ps_cur_opts.index(ps_cur)]['id']
        is_vnd_ps   = (ps_cur == 'VND')
        ps_rate     = pc3.number_input("Exchange Rate", value=1.0 if is_vnd_ps else 25_000.0, format="%.2f")
        ps_days     = pc4.number_input("Man-Days (optional)", value=0.0, min_value=0.0, format="%.1f")

        alloc_opts    = ['PENDING', 'SGA', 'COGS']
        default_alloc = 'SGA' if ps_layer_v == 'STANDARD' else 'PENDING'
        ps_alloc      = st.selectbox("Allocation", alloc_opts, index=alloc_opts.index(default_alloc))
        ps_desc       = st.text_input("Description")

        submitted = st.form_submit_button("✅ Lưu", type="primary", use_container_width=True)

    if submitted:
        if ps_amount <= 0:
            st.error("Amount must be > 0.")
            return
        if is_ps_subcon and not ps_subcon:
            st.error("Subcontractor name required.")
            return
        try:
            create_presales_cost({
                'project_id':         project_id,
                'employee_id':        ps_emp_id,
                'subcontractor_name': ps_subcon,
                'cost_layer':         ps_layer_v,
                'category':           ps_cat,
                'amount':             ps_amount,
                'currency_id':        ps_cur_id,
                'exchange_rate':      ps_rate,
                'allocation':         ps_alloc,
                'man_days':           ps_days if ps_days > 0 else None,
                'description':        ps_desc or None,
            }, user_id)
            st.success("✅ Pre-sales cost added!")
            st.rerun()
        except Exception as e:
            st.error(f"Lỗi: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# FRAGMENT — Labor tab
# ══════════════════════════════════════════════════════════════════════════════

@st.fragment
def _labor_tab(project_id: int):
    fc1, fc2, fc3 = st.columns([2, 2, 1])
    lf_phase  = fc1.selectbox("Filter Phase",    ["All"] + list(PHASE_LABELS.keys()), key="lf_phase")
    lf_status = fc2.selectbox("Filter Approval", ["All", "PENDING", "APPROVED", "REJECTED"], key="lf_status")
    if fc3.button("➕ Log Labor", type="primary", use_container_width=True):
        _dialog_add_labor(project_id)

    labor_df = get_labor_logs_df(
        project_id,
        phase=None if lf_phase == "All" else lf_phase,
        approval_status=None if lf_status == "All" else lf_status,
    )

    approved_df = labor_df[labor_df['approval_status'] == 'APPROVED'] if not labor_df.empty else labor_df
    k1, k2, k3 = st.columns(3)
    k1.metric("Man-Days (Approved)", f"{approved_df['man_days'].sum():.1f}" if not approved_df.empty else "0")
    k2.metric("Labor Cost (Approved)", fmt_vnd(approved_df['amount'].sum() if not approved_df.empty else 0))
    k3.metric("Pending", int((labor_df['approval_status'] == 'PENDING').sum()) if not labor_df.empty else 0)

    if labor_df.empty:
        st.info("Chưa có labor log nào.")
        return

    has_att    = 'attachment_filename' in labor_df.columns
    display_df = labor_df.copy()
    col_config = {
        'id':                  st.column_config.NumberColumn('ID', width=55),
        'work_date':           st.column_config.DateColumn('Date'),
        'phase':               st.column_config.TextColumn('Phase'),
        'worker':              st.column_config.TextColumn('Worker'),
        'employee_level':      st.column_config.TextColumn('Level'),
        'man_days':            st.column_config.NumberColumn('Days', format="%.1f"),
        'daily_rate':          st.column_config.NumberColumn('Rate', format="%.0f"),
        'amount':              st.column_config.NumberColumn('Amount', format="%.0f"),
        'is_on_site':          st.column_config.CheckboxColumn('On-site'),
        'presales_allocation': st.column_config.TextColumn('Pre-sales'),
        'approval_status':     st.column_config.TextColumn('Status'),
        'description':         st.column_config.TextColumn('Description'),
    }
    if has_att:
        display_df.insert(0, '📎', display_df['attachment_filename'].apply(lambda x: '📎' if x else ''))
        col_config['📎'] = st.column_config.TextColumn('', width=30)

    event = st.dataframe(
        display_df, use_container_width=True, hide_index=True,
        on_select="rerun", selection_mode="single-row",
        column_config=col_config,
    )

    sel = event.selection.rows
    if sel:
        row = labor_df.iloc[sel[0]].to_dict()
        col_edit, col_att = st.columns(2)
        if row.get('approval_status') == 'PENDING':
            if col_edit.button("✏️ Edit selected", key="labor_edit_btn"):
                _dialog_edit_labor(row, project_id)
        if has_att and row.get('attachment_s3_key'):
            if col_att.button("📎 Xem chứng từ", key="labor_att_btn"):
                _dialog_view_attachment(row['attachment_s3_key'], row['attachment_filename'])

    if is_pm:
        pending_ids = labor_df[labor_df['approval_status'] == 'PENDING']['id'].tolist()
        if pending_ids:
            if st.button(f"✅ Approve All Pending ({len(pending_ids)})", key="bulk_approve_labor"):
                for lid in pending_ids:
                    approve_labor_log(lid, emp_int_id)
                st.success(f"Approved {len(pending_ids)} entries.")
                st.rerun(scope="fragment")


# ══════════════════════════════════════════════════════════════════════════════
# FRAGMENT — Expenses tab
# ══════════════════════════════════════════════════════════════════════════════

@st.fragment
def _expense_tab(project_id: int):
    ef1, ef2, ef3 = st.columns([2, 2, 1])
    ef_phase  = ef1.selectbox("Filter Phase",    ["All"] + list(PHASE_LABELS.keys()), key="ef_phase")
    ef_status = ef2.selectbox("Filter Approval", ["All", "PENDING", "APPROVED", "REJECTED"], key="ef_status")
    if ef3.button("➕ Add Expense", type="primary", use_container_width=True):
        _dialog_add_expense(project_id)

    exp_df = get_expenses_df(
        project_id,
        phase=None if ef_phase == "All" else ef_phase,
        approval_status=None if ef_status == "All" else ef_status,
    )

    approved_exp = exp_df[exp_df['approval_status'] == 'APPROVED'] if not exp_df.empty else exp_df
    ek1, ek2, ek3 = st.columns(3)
    ek1.metric("Total Expenses (Approved)", fmt_vnd(approved_exp['amount_vnd'].sum() if not approved_exp.empty else 0))
    ek2.metric("Transactions", len(approved_exp))
    ek3.metric("Pending", int((exp_df['approval_status'] == 'PENDING').sum()) if not exp_df.empty else 0)

    if exp_df.empty:
        st.info("Chưa có expense nào.")
        return

    has_att    = 'attachment_filename' in exp_df.columns
    display_df = exp_df.copy()
    col_config = {
        'id':              st.column_config.NumberColumn('ID', width=55),
        'expense_date':    st.column_config.DateColumn('Date'),
        'category':        st.column_config.TextColumn('Category'),
        'phase':           st.column_config.TextColumn('Phase'),
        'employee_name':   st.column_config.TextColumn('Employee'),
        'amount':          st.column_config.NumberColumn('Amount', format="%.0f"),
        'currency':        st.column_config.TextColumn('CCY', width=50),
        'amount_vnd':      st.column_config.NumberColumn('VND', format="%.0f"),
        'vendor_name':     st.column_config.TextColumn('Vendor'),
        'receipt_number':  st.column_config.TextColumn('Receipt#'),
        'approval_status': st.column_config.TextColumn('Status'),
        'description':     st.column_config.TextColumn('Description'),
    }
    if has_att:
        display_df.insert(0, '📎', display_df['attachment_filename'].apply(lambda x: '📎' if x else ''))
        col_config['📎'] = st.column_config.TextColumn('', width=30)

    event = st.dataframe(
        display_df, use_container_width=True, hide_index=True,
        on_select="rerun", selection_mode="single-row",
        column_config=col_config,
    )

    sel = event.selection.rows
    if sel:
        row = exp_df.iloc[sel[0]].to_dict()
        col_edit, col_att = st.columns(2)
        if row.get('approval_status') == 'PENDING':
            if col_edit.button("✏️ Edit selected", key="exp_edit_btn"):
                _dialog_edit_expense(row, project_id)
        if has_att and row.get('attachment_s3_key'):
            if col_att.button("📎 Xem chứng từ", key="exp_att_btn"):
                _dialog_view_attachment(row['attachment_s3_key'], row['attachment_filename'])

    if is_pm:
        pending_exp = exp_df[exp_df['approval_status'] == 'PENDING']['id'].tolist()
        if pending_exp:
            if st.button(f"✅ Approve All Pending ({len(pending_exp)})", key="bulk_approve_exp"):
                for eid in pending_exp:
                    approve_expense(eid, emp_int_id)
                st.success(f"Approved {len(pending_exp)} expenses.")
                st.rerun(scope="fragment")


# ══════════════════════════════════════════════════════════════════════════════
# FRAGMENT — Pre-sales tab
# ══════════════════════════════════════════════════════════════════════════════

@st.fragment
def _presales_tab(project_id: int):
    ps_h1, ps_h2 = st.columns([5, 1])
    if ps_h2.button("➕ Add", type="primary", use_container_width=True):
        _dialog_add_presales(project_id)

    ps_df = get_presales_costs_df(project_id)

    if not ps_df.empty:
        l1_total = ps_df[ps_df['cost_layer'] == 'STANDARD']['amount_vnd'].sum()
        l2_total = ps_df[ps_df['cost_layer'] == 'SPECIAL']['amount_vnd'].sum()
        l2_cogs  = ps_df[(ps_df['cost_layer'] == 'SPECIAL') & (ps_df['allocation'] == 'COGS')]['amount_vnd'].sum()
        pk1, pk2, pk3 = st.columns(3)
        pk1.metric("Layer 1 — SG&A",  fmt_vnd(l1_total))
        pk2.metric("Layer 2 — Total", fmt_vnd(l2_total))
        pk3.metric("Layer 2 → COGS",  fmt_vnd(l2_cogs))

        display_df = ps_df.copy()
        display_df.insert(0, '●', display_df['allocation'].map(
            lambda a: {'SGA': '🔵', 'COGS': '🟢', 'PENDING': '⚪'}.get(a, '⚪')
        ))
        st.dataframe(
            display_df, use_container_width=True, hide_index=True,
            column_config={
                '●':           st.column_config.TextColumn('', width=30),
                'cost_layer':  st.column_config.TextColumn('Layer'),
                'category':    st.column_config.TextColumn('Category'),
                'worker':      st.column_config.TextColumn('Worker'),
                'amount':      st.column_config.NumberColumn('Amount', format="%.0f"),
                'currency':    st.column_config.TextColumn('CCY', width=50),
                'amount_vnd':  st.column_config.NumberColumn('VND', format="%.0f"),
                'man_days':    st.column_config.NumberColumn('Man-Days', format="%.1f"),
                'allocation':  st.column_config.TextColumn('Allocation'),
                'description': st.column_config.TextColumn('Description'),
            },
        )
    else:
        st.info("Chưa có pre-sales cost nào.")

    if is_pm:
        st.divider()
        st.markdown("**Win/Lose Decision — Layer 2 allocation**")
        dc1, dc2, _ = st.columns(3)
        if dc1.button("🏆 WIN — Move Layer 2 → COGS", type="primary"):
            n = bulk_update_presales_allocation(project_id, 'COGS', user_id)
            st.success(f"Updated {n} Layer-2 costs → COGS.")
            st.rerun(scope="fragment")
        if dc2.button("❌ LOSE — Move Layer 2 → SGA"):
            n = bulk_update_presales_allocation(project_id, 'SGA', user_id)
            st.info(f"Updated {n} Layer-2 costs → SGA.")
            st.rerun(scope="fragment")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

tab_labor, tab_exp, tab_presales = st.tabs(["👷 Labor Logs", "🧾 Expenses", "🔍 Pre-sales Costs"])

with tab_labor:
    _labor_tab(project_id)

with tab_exp:
    _expense_tab(project_id)

with tab_presales:
    _presales_tab(project_id)