# pages/1_🏗️_Projects.py
"""
IL Projects — Master list + Create / Edit
Enhanced Phase 1: 2-row KPI dashboard, Health indicator, Budget%, Days Left, Quick Jump
"""

import streamlit as st
import pandas as pd
from datetime import date
import logging

from utils.auth import AuthManager
from utils.il_project import (
    get_projects_df, get_project, create_project, update_project, soft_delete_project,
    get_project_types, get_employees, get_companies, get_currencies, get_milestones_df,
    create_milestone, update_milestone, generate_project_code,
    fmt_vnd, fmt_percent, STATUS_COLORS,
    get_rate_to_vnd, rate_status, fmt_rate,
)

from utils.il_project.permissions import PermissionContext, get_role_badge

logger = logging.getLogger(__name__)
auth = AuthManager()

st.set_page_config(page_title="IL Projects", page_icon="🏗️", layout="wide")
auth.require_auth()
user_id   = str(auth.get_user_id())
user_role = st.session_state.get('user_role', '')
is_admin  = auth.is_admin()
emp_int_id = st.session_state.get('employee_id')

# ── Permission context (used throughout page) ────────────────────────────────
ctx = PermissionContext(
    employee_id=emp_int_id,
    is_admin=is_admin,
    user_role=user_role,
)


# ── Lookups (cached) ──────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load_lookups():
    types      = get_project_types()
    employees  = get_employees()
    companies  = get_companies()
    currencies = get_currencies()
    return types, employees, companies, currencies

proj_types, employees, companies, currencies = _load_lookups()

type_map     = {t['id']: f"[{t['code']}] {t['name']}" for t in proj_types}
emp_map      = {e['id']: e['full_name'] for e in employees}
company_map  = {c['id']: c['name'] for c in companies}
currency_map = {c['id']: c['code'] for c in currencies}


# ── Pending counts (cached, lightweight cross-query) ─────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def _load_pending_counts() -> dict:
    """
    Return {project_id: {'prs': N, 'labor': N, 'expenses': N}} for all projects.
    Single query — no N+1.
    """
    try:
        from utils.db import execute_query
        rows = execute_query("""
            SELECT
                p.id AS project_id,
                COALESCE(pr_cnt.cnt, 0) AS pending_prs,
                COALESCE(lb_cnt.cnt, 0) AS pending_labor,
                COALESCE(ex_cnt.cnt, 0) AS pending_expenses
            FROM il_projects p
            LEFT JOIN (
                SELECT project_id, COUNT(*) AS cnt
                FROM il_purchase_requests
                WHERE status IN ('SUBMITTED', 'PENDING_APPROVAL') AND delete_flag = 0
                GROUP BY project_id
            ) pr_cnt ON pr_cnt.project_id = p.id
            LEFT JOIN (
                SELECT project_id, COUNT(*) AS cnt
                FROM il_project_labor_logs
                WHERE approval_status = 'PENDING' AND delete_flag = 0
                GROUP BY project_id
            ) lb_cnt ON lb_cnt.project_id = p.id
            LEFT JOIN (
                SELECT project_id, COUNT(*) AS cnt
                FROM il_project_expenses
                WHERE approval_status = 'PENDING' AND delete_flag = 0
                GROUP BY project_id
            ) ex_cnt ON ex_cnt.project_id = p.id
            WHERE p.delete_flag = 0
        """, {})
        return {
            r['project_id']: {
                'prs':      int(r['pending_prs']),
                'labor':    int(r['pending_labor']),
                'expenses': int(r['pending_expenses']),
                'total':    int(r['pending_prs']) + int(r['pending_labor']) + int(r['pending_expenses']),
            }
            for r in rows
        }
    except Exception as e:
        logger.warning(f"_load_pending_counts failed: {e}")
        return {}


@st.cache_data(ttl=120, show_spinner=False)
def _load_completion_map() -> dict:
    """
    Return {project_id: completion_pct} from il_projects.overall_completion_percent.
    This column is auto-calculated from phase weights by sync_project_completion().
    Falls back to AVG(task completion) if overall is null.
    """
    try:
        from utils.db import execute_query
        rows = execute_query("""
            SELECT
                p.id AS project_id,
                COALESCE(
                    p.overall_completion_percent,
                    (SELECT ROUND(AVG(t.completion_percent), 0)
                     FROM il_project_tasks t
                     WHERE t.project_id = p.id AND t.delete_flag = 0)
                ) AS completion
            FROM il_projects p
            WHERE p.delete_flag = 0
        """, {})
        return {
            r['project_id']: int(r['completion'] or 0)
            for r in rows
            if r['completion'] is not None and float(r['completion'] or 0) > 0
        }
    except Exception as e:
        logger.debug(f"_load_completion_map: {e}")
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH INDICATOR — composite project health score
# ══════════════════════════════════════════════════════════════════════════════

_ACTIVE_STATUSES = {'CONTRACTED', 'IN_PROGRESS', 'COMMISSIONING', 'WARRANTY'}


def _compute_health(row) -> str:
    """
    Composite health indicator based on GP deviation + budget + schedule.

    Returns: 🟢 🟡 🔴 ⚪ (⚪ = not active / no data)

    Logic (additive score):
      GP deviation (est-actual):  >8pp → +2,  3–8pp → +1
      Budget consumption:         >100% → +2,  85–100% → +1
      Schedule overdue:           >14d → +2,   1–14d → +1

      Score 0 → 🟢   Score 1 → 🟡   Score 2+ → 🔴
    """
    status = row.get('status', '')
    if status not in _ACTIVE_STATUSES:
        return '⚪'

    score = 0

    # ── GP deviation ─────────────────────────────────
    est_gp = row.get('estimated_gp_percent')
    act_gp = row.get('actual_gp_percent')
    if _is_num(est_gp) and _is_num(act_gp):
        deviation = float(est_gp) - float(act_gp)
        if deviation > 8:
            score += 2
        elif deviation > 3:
            score += 1

    # ── Budget consumption ───────────────────────────
    est_cogs = _safe_float(row.get('estimated_cogs'))
    act_cogs = _safe_float(row.get('actual_cogs'))
    if est_cogs > 0 and act_cogs > 0:
        budget_pct = act_cogs / est_cogs
        if budget_pct > 1.0:
            score += 2
        elif budget_pct > 0.85:
            score += 1

    # ── Schedule overdue ─────────────────────────────
    end_date = row.get('estimated_end_date')
    if end_date is not None:
        try:
            end_dt = pd.to_datetime(end_date).date()
            overdue_days = (date.today() - end_dt).days
            if overdue_days > 14:
                score += 2
            elif overdue_days > 0:
                score += 1
        except Exception:
            pass

    if score >= 2:
        return '🔴'
    if score >= 1:
        return '🟡'
    return '🟢'


def _compute_days_left(row) -> str:
    """Days until estimated_end_date. Returns readable string."""
    status = row.get('status', '')
    if status in ('COMPLETED', 'CLOSED', 'CANCELLED'):
        return '—'

    end_date = row.get('estimated_end_date')
    if end_date is None or str(end_date) in ('', 'NaT', 'None', 'nan'):
        return '—'
    try:
        end_dt = pd.to_datetime(end_date).date()
        delta = (end_dt - date.today()).days
        if delta < 0:
            return f"⚠️ {abs(delta)}d over"
        if delta == 0:
            return "📍 Today"
        if delta <= 14:
            return f"⏰ {delta}d"
        return f"{delta}d"
    except Exception:
        return '—'


def _compute_budget_pct(row) -> str:
    """Budget consumption: actual_cogs / estimated_cogs."""
    est = _safe_float(row.get('estimated_cogs'))
    act = _safe_float(row.get('actual_cogs'))
    if est <= 0:
        return '—'
    if act <= 0:
        return '0%'
    pct = act / est * 100
    if pct > 100:
        return f"🔴 {pct:.0f}%"
    if pct > 85:
        return f"🟡 {pct:.0f}%"
    return f"{pct:.0f}%"


def _is_num(v) -> bool:
    """Check if value is a real number (not None/NaN)."""
    if v is None:
        return False
    try:
        f = float(v)
        return not pd.isna(f)
    except (TypeError, ValueError):
        return False


def _safe_float(v, default: float = 0.0) -> float:
    """Safe float conversion."""
    if v is None:
        return default
    try:
        f = float(v)
        return default if pd.isna(f) else f
    except (TypeError, ValueError):
        return default


# ══════════════════════════════════════════════════════════════════════════════
# PROJECT FORM (shared between Create and Edit dialogs)
# ══════════════════════════════════════════════════════════════════════════════

def _project_form_fields(proj: dict, is_create: bool):
    """Render project form fields inside a tab layout. Returns field values as dict."""

    tab_basic, tab_financial, tab_timeline, tab_team = st.tabs(
        ["📋 Basic", "💰 Financial", "📅 Timeline", "👥 Team & Warranty"]
    )

    # ── Basic tab ─────────────────────────────────────────────────────────────
    with tab_basic:
        fc1, fc2, fc3 = st.columns(3)
        if is_create:
            auto_code    = generate_project_code(auth.get_user_id())
            fc1.text_input("Project Code", value=auto_code, disabled=True,
                            help="Auto-generated: IL-YYYY-{user_id}-NNN")
            project_code = auto_code
        else:
            fc1.text_input("Project Code", value=proj.get('project_code', ''), disabled=True)
            project_code = proj.get('project_code', '')

        contract_num = fc2.text_input("Contract Number", value=proj.get('contract_number') or '')
        project_name = fc3.text_input("Project Name *", value=proj.get('project_name', ''))

        ft1, ft2, ft3 = st.columns(3)
        type_options = [f"[{t['code']}] {t['name']}" for t in proj_types]
        current_type = type_map.get(proj.get('project_type_id', ''))
        type_idx     = type_options.index(current_type) if current_type in type_options else 0
        type_sel     = ft1.selectbox("Project Type", type_options, index=type_idx)
        _type_code   = type_sel.split("]")[0][1:]
        type_id_sel  = next((t for t in proj_types if t['code'] == _type_code), proj_types[0])['id']

        billing_types = ['LUMP_SUM', 'MILESTONE', 'TIME_MATERIAL', 'MIXED']
        billing_idx   = billing_types.index(proj['billing_type']) if proj.get('billing_type') in billing_types else 0
        billing_sel   = ft2.selectbox("Billing Type", billing_types, index=billing_idx)

        statuses   = ['DRAFT', 'ESTIMATING', 'PROPOSAL_SENT', 'GO', 'CONDITIONAL', 'NO_GO',
                      'CONTRACTED', 'IN_PROGRESS', 'COMMISSIONING', 'COMPLETED',
                      'WARRANTY', 'CLOSED', 'CANCELLED']
        status_idx = statuses.index(proj['status']) if proj.get('status') in statuses else 0
        status_sel = ft3.selectbox("Status", statuses, index=status_idx)

        cc1, cc2 = st.columns(2)
        company_opts = ["(Not in system)"] + [c['name'] for c in companies]
        company_idx  = next((i + 1 for i, c in enumerate(companies) if c['id'] == proj.get('customer_id')), 0)
        company_sel  = cc1.selectbox("Customer (Companies)", company_opts, index=company_idx)
        customer_id  = companies[company_opts.index(company_sel) - 1]['id'] if company_sel != "(Not in system)" else None
        end_cust     = cc2.text_input("Customer Name (free text)", value=proj.get('end_customer_name') or '')

        fl1, fl2, fl3, fl4 = st.columns(4)
        location   = fl1.text_input("Location", value=proj.get('location') or '')
        dist_opts  = ['LOCAL', 'NEARBY', 'FAR', 'OVERSEAS']
        dist_idx   = dist_opts.index(proj['site_distance_category']) if proj.get('site_distance_category') in dist_opts else 1
        dist_sel   = fl2.selectbox("Distance", dist_opts, index=dist_idx)
        env_opts   = ['CLEAN', 'NORMAL', 'HARSH']
        env_idx    = env_opts.index(proj['environment_category']) if proj.get('environment_category') in env_opts else 1
        env_sel    = fl3.selectbox("Environment", env_opts, index=env_idx)
        imp_opts   = ['DOMESTIC', 'IMPORTED', 'MIXED']
        imp_idx    = imp_opts.index(proj['import_category']) if proj.get('import_category') in imp_opts else 1
        imp_sel    = fl4.selectbox("Import Category", imp_opts, index=imp_idx)

        decision_notes = st.text_area("Decision Notes", value=proj.get('decision_notes') or '', height=70)

    # ── Financial tab ─────────────────────────────────────────────────────────
    with tab_financial:
        fm1, fm2 = st.columns(2)
        contract_val = fm1.number_input("Contract Value",
                                         value=float(proj.get('contract_value') or 0),
                                         min_value=0.0, format="%.0f")
        amended_val  = fm2.number_input("Amended Value (0=none)",
                                         value=float(proj.get('amended_contract_value') or 0),
                                         min_value=0.0, format="%.0f")

        cur_opts    = [c['code'] for c in currencies]
        cur_idx     = next((i for i, c in enumerate(currencies) if c['id'] == proj.get('currency_id')), 0)
        cur_sel     = st.selectbox("Contract Currency", cur_opts, index=cur_idx,
                                    help="Contract currency with customer.")
        currency_id = currencies[cur_opts.index(cur_sel)]['id']

        # Auto-fetch rate (runs at form render time; inside form so no per-keystroke rerun)
        _rate_res   = get_rate_to_vnd(cur_sel)
        _icon, _msg = rate_status(_rate_res)
        saved_rate  = float(proj.get('exchange_rate') or 0)

        if cur_sel == 'VND':
            st.info("ℹ️ VND — rate = 1")
        elif _rate_res.ok:
            # Show info banner if saved rate differs from live rate by >1%
            if saved_rate > 0 and abs(_rate_res.rate - saved_rate) / saved_rate > 0.01:
                st.info(
                    f"💡 Live market rate: **{fmt_rate(_rate_res.rate)}** VND (saved: {fmt_rate(saved_rate)})"
                )
            else:
                st.success(f"{_icon} {_msg}")
        else:
            st.warning(f"{_icon} {_msg}")

        default_rate = saved_rate if saved_rate > 0 else _rate_res.rate
        exc_rate = st.number_input(
            f"Exchange Rate (1 {cur_sel} = ? VND)",
            value=default_rate if default_rate > 0 else 1.0,
            min_value=0.0, format="%.4f",
            help="Exchange rate to VND at contract signing date. Auto-fetched from API when available.",
        )

    # ── Timeline tab ──────────────────────────────────────────────────────────
    with tab_timeline:
        fd1, fd2, fd3, fd4 = st.columns(4)
        est_start = fd1.date_input("Est. Start", value=proj.get('estimated_start_date') or None)
        est_end   = fd2.date_input("Est. End",   value=proj.get('estimated_end_date') or None)
        act_start = fd3.date_input("Act. Start", value=proj.get('actual_start_date') or None)
        act_end   = fd4.date_input("Act. End",   value=proj.get('actual_end_date') or None)

    # ── Team & Warranty tab ───────────────────────────────────────────────────
    with tab_team:
        fw1, fw2, fw3, fw4 = st.columns(4)
        emp_opts   = [e['full_name'] for e in employees]
        pm_idx     = next((i for i, e in enumerate(employees) if e['id'] == proj.get('pm_employee_id')), 0)
        pm_sel     = fw1.selectbox("Project Manager", emp_opts, index=pm_idx)
        sales_idx  = next((i for i, e in enumerate(employees) if e['id'] == proj.get('sales_employee_id')), 0)
        sales_sel  = fw2.selectbox("Sales", emp_opts, index=sales_idx)
        war_months = fw3.number_input("Warranty (months)", value=int(proj.get('warranty_months') or 12), min_value=0)
        war_types  = ['PARTS_ONLY', 'LABOR_INCLUDED', 'FULL_SERVICE']
        war_t_idx  = war_types.index(proj['warranty_type']) if proj.get('warranty_type') in war_types else 0
        war_type   = fw4.selectbox("Warranty Type", war_types, index=war_t_idx)

    return {
        'project_code':        project_code,
        'contract_number':     contract_num.strip() or None,
        'project_name':        project_name.strip(),
        'project_type_id':     type_id_sel,
        'customer_id':         customer_id,
        'end_customer_name':   end_cust.strip() or None,
        'contract_value':      contract_val or None,
        'amended_contract_value': amended_val if amended_val > 0 else None,
        'currency_id':         currency_id,
        'exchange_rate':       exc_rate,
        'billing_type':        billing_sel,
        'status':              status_sel,
        'go_no_go_decision':   None,
        'decision_date':       None,
        'decision_notes':      decision_notes.strip() or None,
        'location':            location.strip() or None,
        'site_distance_category': dist_sel,
        'environment_category':   env_sel,
        'import_category':        imp_sel,
        'estimated_start_date':   est_start,
        'estimated_end_date':     est_end,
        'actual_start_date':      act_start,
        'actual_end_date':        act_end,
        'warranty_months':        war_months,
        'warranty_end_date':      None,
        'warranty_type':          war_type,
        'pm_employee_id':         employees[emp_opts.index(pm_sel)]['id'],
        'sales_employee_id':      employees[emp_opts.index(sales_sel)]['id'],
    }


# ══════════════════════════════════════════════════════════════════════════════
# DIALOGS
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("➕ New Project", width="large")
def _dialog_create_project():
    if not ctx.can('project.create'):
        st.warning("⛔ Bạn không có quyền tạo dự án mới.")
        return
    with st.form("create_project_form"):
        data = _project_form_fields({}, is_create=True)
        col_save, col_cancel = st.columns(2)
        submitted = col_save.form_submit_button("💾 Create", type="primary", width="stretch")
        cancelled = col_cancel.form_submit_button("✖ Cancel", width="stretch")

    if cancelled:
        st.rerun()
    if submitted:
        if not data['project_name']:
            st.error("Project Name is required.")
            return
        try:
            new_id = create_project(data, user_id)
            st.success(f"✅ Project created! ID: {new_id}")
            _load_lookups.clear()  # Targeted: only projects/employees/companies
            st.session_state["open_view_pid"] = new_id
            st.rerun()
        except Exception as e:
            st.error(f"Save failed: {e}")


@st.dialog("✏️ Edit Project", width="large")
def _dialog_edit_project(project_id: int):
    if not ctx.can('project.edit', project_id):
        st.warning("⛔ Bạn không có quyền chỉnh sửa dự án này. Chỉ PM hoặc Admin mới có thể sửa.")
        return
    proj = get_project(project_id) or {}
    with st.form("edit_project_form"):
        data = _project_form_fields(proj, is_create=False)
        col_save, col_cancel = st.columns(2)
        submitted = col_save.form_submit_button("💾 Save", type="primary", width="stretch")
        cancelled = col_cancel.form_submit_button("✖ Cancel", width="stretch")

    if cancelled:
        st.rerun()
    if submitted:
        if not data['project_name']:
            st.error("Project Name is required.")
            return
        try:
            update_project(project_id, data, user_id)
            st.success("✅ Project updated!")
            _load_lookups.clear()  # Targeted: refresh project list
            st.rerun()
        except Exception as e:
            st.error(f"Save failed: {e}")


@st.dialog("🏗️ Project Details", width="large")
def _dialog_view_project(project_id: int):
    proj = get_project(project_id)
    if not proj:
        st.warning("Project not found.")
        return

    # Header
    hcol1, hcol2 = st.columns([5, 1])
    hcol1.subheader(f"{STATUS_COLORS.get(proj['status'], '⚪')} {proj['project_code']} — {proj['project_name']}")

    if ctx.can('project.edit', project_id):
        if hcol2.button("✏️ Edit", use_container_width=True, type="primary"):
            st.session_state["open_edit_pid"] = project_id
            st.rerun()

    # KPIs
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Status",      proj['status'])
    m2.metric("Contract",    fmt_vnd(proj.get('contract_value')))
    m3.metric("Est. GP%",    fmt_percent(proj.get('estimated_gp_percent')))
    m4.metric("Actual GP%",  fmt_percent(proj.get('actual_gp_percent')))

    # Detail tabs
    d_tab_info, d_tab_milestones = st.tabs(["📋 Info", "🎯 Milestones"])

    with d_tab_info:
        c1, c2 = st.columns(2)
        c1.markdown(f"**Customer:** {proj.get('customer_name') or proj.get('end_customer_name') or '—'}")
        c1.markdown(f"**Type:** {proj.get('type_name', '—')}")
        c1.markdown(f"**Location:** {proj.get('location', '—')} ({proj.get('site_distance_category', '—')})")
        c1.markdown(f"**PM:** {proj.get('pm_name', '—')}")
        c1.markdown(f"**Sales:** {proj.get('sales_name', '—')}")
        c2.markdown(f"**Billing Type:** {proj.get('billing_type', '—')}")
        c2.markdown(f"**Import Category:** {proj.get('import_category', '—')}")
        c2.markdown(f"**Environment:** {proj.get('environment_category', '—')}")
        c2.markdown(f"**Warranty:** {proj.get('warranty_months', '—')} months ({proj.get('warranty_type', '—')})")
        if proj.get('decision_notes'):
            st.info(f"📝 {proj['decision_notes']}")

    with d_tab_milestones:
        _milestone_panel(project_id, proj)


def _milestone_panel(project_id: int, proj: dict):
    """Milestones display + add form (inside a view dialog — no nested dialog)."""
    ms_df = get_milestones_df(project_id)
    if not ms_df.empty:
        st.dataframe(
            ms_df, width="stretch", hide_index=True,
            column_config={
                'sequence_no':     st.column_config.NumberColumn('#', width=40),
                'milestone_name':  st.column_config.TextColumn('Milestone'),
                'milestone_type':  st.column_config.TextColumn('Type'),
                'billing_percent': st.column_config.NumberColumn('Billing%', format="%.1f%%"),
                'billing_amount':  st.column_config.NumberColumn('Amount', format="%.0f"),
                'planned_date':    st.column_config.DateColumn('Planned'),
                'actual_date':     st.column_config.DateColumn('Actual'),
                'status':          st.column_config.TextColumn('Status'),
            },
        )
    else:
        st.info("No milestones yet.")

    with st.expander("➕ Add Milestone"):
        with st.form(f"ms_form_{project_id}"):
            mc1, mc2, mc3 = st.columns(3)
            ms_seq    = mc1.number_input("Sequence #", min_value=1, value=len(ms_df) + 1)
            ms_name   = mc2.text_input("Milestone Name *")
            ms_types  = ['DELIVERY', 'PAYMENT', 'ACCEPTANCE', 'HANDOVER', 'WARRANTY_START', 'OTHER']
            ms_type   = mc3.selectbox("Type", ms_types)
            md1, md2, md3 = st.columns(3)
            ms_bpct   = md1.number_input("Billing % (0=none)", min_value=0.0, max_value=100.0, value=0.0)
            ms_bamt   = md2.number_input("Billing Amount (0=none)", min_value=0.0, value=0.0, format="%.0f")
            ms_plan   = md3.date_input("Planned Date")
            ms_stats  = ['PENDING', 'IN_PROGRESS', 'COMPLETED', 'INVOICED', 'PAID', 'OVERDUE']
            ms_stat   = st.selectbox("Status", ms_stats)
            ms_notes  = st.text_input("Completion Notes")
            cur_opts  = [c['code'] for c in currencies]
            ms_cur    = st.selectbox("Currency", cur_opts)
            ms_cur_id = currencies[cur_opts.index(ms_cur)]['id']

            if st.form_submit_button("Add Milestone", type="primary"):
                if not ctx.can('project.milestones', project_id):
                    st.error("⛔ Chỉ PM hoặc Admin mới có thể thêm milestone.")
                elif not ms_name:
                    st.error("Name required.")
                elif ms_bpct > 0 and ms_bamt > 0:
                    st.error("Set either Billing % OR Amount, not both.")
                else:
                    create_milestone({
                        'project_id':     project_id,
                        'sequence_no':    ms_seq,
                        'milestone_name': ms_name,
                        'milestone_type': ms_type,
                        'billing_percent': ms_bpct if ms_bpct > 0 else None,
                        'billing_amount':  ms_bamt if ms_bamt > 0 else None,
                        'currency_id':    ms_cur_id,
                        'planned_date':   ms_plan,
                        'actual_date':    None,
                        'status':         ms_stat,
                        'completion_notes': ms_notes or None,
                    }, user_id)
                    st.success("Milestone added!")
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# EXPORT HELPERS (Phase 3)
# ══════════════════════════════════════════════════════════════════════════════

def _build_export_df(df: pd.DataFrame, pending_map: dict, completion_map: dict) -> pd.DataFrame:
    """Build a clean DataFrame for Excel export — human-readable columns, no emoji noise."""
    if df.empty:
        return df

    export = pd.DataFrame({
        'Project Code':     df['project_code'],
        'Project Name':     df['project_name'],
        'Type':             df['project_type'],
        'Customer':         df['customer_name'],
        'Status':           df['status'],
        'Health':           df.apply(_compute_health, axis=1).map(
                                {'🟢': 'Healthy', '🟡': 'Watch', '🔴': 'At Risk', '⚪': 'N/A'}),
        'PM':               df['pm_name'],
        'Contract Value':   df['effective_contract_value'],
        'CCY':              df['currency_code'],
        'Est GP%':          df['estimated_gp_percent'],
        'Actual GP%':       df['actual_gp_percent'],
        'Est COGS':         df['estimated_cogs'],
        'Actual COGS':      df['actual_cogs'],
        'Budget %':         df.apply(
                                lambda r: round(_safe_float(r.get('actual_cogs')) / _safe_float(r.get('estimated_cogs')) * 100, 1)
                                if _safe_float(r.get('estimated_cogs')) > 0 and _safe_float(r.get('actual_cogs')) > 0
                                else None, axis=1),
        'Start Date':       df['estimated_start_date'],
        'End Date':         df['estimated_end_date'],
        'Days Left':        df.apply(lambda r: _compute_days_left(r).replace('⚠️ ', '').replace('⏰ ', '').replace('📍 ', ''), axis=1),
        'Completion %':     df['project_id'].map(lambda pid: completion_map.get(int(pid)) if completion_map else None),
        'Pending Items':    df['project_id'].map(lambda pid: pending_map.get(int(pid), {}).get('total', 0) if pending_map else 0),
    })
    return export


def _to_excel(df: pd.DataFrame) -> bytes:
    """Convert DataFrame to Excel bytes for download."""
    import io
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Projects')

        # Auto-adjust column widths
        ws = writer.sheets['Projects']
        for col_cells in ws.columns:
            max_len = 0
            col_letter = col_cells[0].column_letter
            for cell in col_cells:
                val = str(cell.value) if cell.value is not None else ''
                max_len = max(max_len, len(val))
            ws.column_dimensions[col_letter].width = min(max_len + 3, 40)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# VISUAL ANALYTICS (Phase 2)
# ══════════════════════════════════════════════════════════════════════════════

# Status → display color mapping (for charts)
_STATUS_CHART_COLORS = {
    'DRAFT':           '#9e9e9e',   # gray
    'ESTIMATING':      '#42a5f5',   # blue
    'PROPOSAL_SENT':   '#7e57c2',   # purple
    'GO':              '#66bb6a',   # green
    'CONDITIONAL':     '#ffca28',   # amber
    'NO_GO':           '#ef5350',   # red
    'CONTRACTED':      '#26a69a',   # teal
    'IN_PROGRESS':     '#1e88e5',   # blue
    'COMMISSIONING':   '#5c6bc0',   # indigo
    'COMPLETED':       '#4caf50',   # green
    'WARRANTY':        '#78909c',   # blue-gray
    'CLOSED':          '#455a64',   # dark gray
    'CANCELLED':       '#b71c1c',   # dark red
}

# Logical phase groupings for pipeline
_STATUS_PHASES = {
    'Pipeline':  ['DRAFT', 'ESTIMATING', 'PROPOSAL_SENT'],
    'Decision':  ['GO', 'CONDITIONAL', 'NO_GO'],
    'Execution': ['CONTRACTED', 'IN_PROGRESS', 'COMMISSIONING'],
    'Closed':    ['COMPLETED', 'WARRANTY', 'CLOSED', 'CANCELLED'],
}


def _render_visual_analytics(df: pd.DataFrame):
    """
    Render visual analytics in tabs inside an expanded expander.
    Tab order: Timeline (default) | Portfolio (pipeline + GP).
    """
    with st.expander("📊 **Visual Analytics**", expanded=True):
        tab_timeline, tab_portfolio = st.tabs(["📅 Timeline", "📊 Portfolio Overview"])

        with tab_timeline:
            _chart_timeline(df)

        with tab_portfolio:
            col_pipe, col_gp = st.columns([1, 2])
            with col_pipe:
                _chart_status_pipeline(df)
            with col_gp:
                _chart_gp_analysis(df)


def _chart_status_pipeline(df: pd.DataFrame):
    """Status distribution — stacked horizontal bar grouped by phase."""
    import plotly.graph_objects as go

    st.caption("**Status Pipeline**")

    # Count per status
    status_counts = df['status'].value_counts().to_dict()

    # Build phase-grouped data
    phases = []
    for phase_name, statuses in _STATUS_PHASES.items():
        count = sum(status_counts.get(s, 0) for s in statuses)
        if count > 0:
            phases.append((phase_name, count, statuses))

    if not phases:
        st.info("No data.")
        return

    # Horizontal stacked bar
    fig = go.Figure()
    for phase_name, _, statuses in phases:
        for s in statuses:
            cnt = status_counts.get(s, 0)
            if cnt == 0:
                continue
            fig.add_trace(go.Bar(
                y=['Projects'],
                x=[cnt],
                name=s.replace('_', ' ').title(),
                orientation='h',
                marker_color=_STATUS_CHART_COLORS.get(s, '#9e9e9e'),
                text=f"{cnt}",
                textposition='inside',
                hovertemplate=f"<b>{s}</b><br>{cnt} project(s)<extra></extra>",
            ))

    fig.update_layout(
        barmode='stack',
        height=80,
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
    )
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

    # Legend as compact text
    legend_parts = []
    for phase_name, phase_count, statuses in phases:
        detail = ', '.join(
            f"{s.replace('_', ' ').title()}: {status_counts[s]}"
            for s in statuses if status_counts.get(s, 0) > 0
        )
        legend_parts.append(f"**{phase_name}** ({phase_count}): {detail}")
    st.caption(' · '.join(legend_parts))

    # PM workload
    if 'pm_name' in df.columns:
        pm_counts = df[df['status'].isin({'IN_PROGRESS', 'COMMISSIONING', 'CONTRACTED'})]['pm_name'].value_counts()
        if not pm_counts.empty:
            st.caption("**PM Workload (active):** " +
                       ' · '.join(f"{name}: {cnt}" for name, cnt in pm_counts.items()))


def _chart_gp_analysis(df: pd.DataFrame):
    """
    GP% bubble chart — each project is a bubble.
    X = Est GP%, Y = Contract Value, color = health, size = contract value.
    If actual GP% exists for some projects, show Est vs Actual scatter instead.
    """
    import plotly.graph_objects as go

    has_actual = df['actual_gp_percent'].notna().any()
    has_est    = df['estimated_gp_percent'].notna().any()

    if not has_est:
        st.info("No estimate data available for GP analysis.")
        return

    # Prepare data
    chart_df = df[df['estimated_gp_percent'].notna()].copy()
    chart_df['health'] = chart_df.apply(_compute_health, axis=1)
    chart_df['label']  = chart_df['project_code'].str[-3:]  # Short label (last 3 chars)
    chart_df['contract_val'] = chart_df['effective_contract_value'].fillna(0)

    health_color_map = {'🟢': '#4caf50', '🟡': '#ff9800', '🔴': '#f44336', '⚪': '#9e9e9e'}

    if has_actual and chart_df['actual_gp_percent'].notna().sum() >= 2:
        # ── Mode A: Est GP% vs Actual GP% scatter ────────────────────
        both = chart_df[chart_df['actual_gp_percent'].notna()].copy()

        fig = go.Figure()

        # Reference line (Est = Actual)
        gp_min = min(both['estimated_gp_percent'].min(), both['actual_gp_percent'].min()) - 5
        gp_max = max(both['estimated_gp_percent'].max(), both['actual_gp_percent'].max()) + 5
        fig.add_trace(go.Scatter(
            x=[gp_min, gp_max], y=[gp_min, gp_max],
            mode='lines', line=dict(color='gray', dash='dash', width=1),
            showlegend=False, hoverinfo='skip',
        ))

        # Project bubbles
        for _, row in both.iterrows():
            color = health_color_map.get(row['health'], '#9e9e9e')
            fig.add_trace(go.Scatter(
                x=[row['estimated_gp_percent']],
                y=[row['actual_gp_percent']],
                mode='markers+text',
                marker=dict(size=14, color=color, line=dict(width=1, color='white')),
                text=[row['label']],
                textposition='top center',
                textfont=dict(size=9),
                hovertemplate=(
                    f"<b>{row['project_code']}</b><br>"
                    f"{row['project_name'][:30]}<br>"
                    f"Est GP: {row['estimated_gp_percent']:.1f}%<br>"
                    f"Act GP: {row['actual_gp_percent']:.1f}%<br>"
                    f"Contract: {row['contract_val']:,.0f}<br>"
                    f"<extra></extra>"
                ),
                showlegend=False,
            ))

        fig.update_layout(
            height=280,
            margin=dict(l=40, r=10, t=25, b=40),
            xaxis=dict(title="Est GP%", zeroline=False),
            yaxis=dict(title="Actual GP%", zeroline=False),
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
        )
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
        st.caption("Diagonal = breakeven. **Below** diagonal = GP erosion (actual < estimate).")

    else:
        # ── Mode B: Est GP% distribution (no actual data yet) ────────
        chart_df = chart_df.sort_values('estimated_gp_percent', ascending=True)

        fig = go.Figure()
        for _, row in chart_df.iterrows():
            color = health_color_map.get(row['health'], '#9e9e9e')
            fig.add_trace(go.Bar(
                y=[row['label']],
                x=[row['estimated_gp_percent']],
                orientation='h',
                marker_color=color,
                hovertemplate=(
                    f"<b>{row['project_code']}</b><br>"
                    f"{row['project_name'][:30]}<br>"
                    f"Est GP: {row['estimated_gp_percent']:.1f}%<br>"
                    f"Contract: {row['contract_val']:,.0f}<br>"
                    f"<extra></extra>"
                ),
                showlegend=False,
            ))

        fig.update_layout(
            height=max(180, 28 * len(chart_df)),
            margin=dict(l=50, r=10, t=5, b=30),
            xaxis=dict(title="Est GP%", range=[0, 100]),
            yaxis=dict(title=""),
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            bargap=0.3,
        )
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
        st.caption("Bars show estimated GP%. Color = health status. Actual GP% not yet available.")


def _chart_timeline(df: pd.DataFrame):
    """
    Simplified Gantt — horizontal bars per project from start to end date.
    Color = status. Vertical line = today.
    """
    import plotly.express as px
    import plotly.graph_objects as go

    # Filter projects with at least start or end date
    tl = df[
        df['estimated_start_date'].notna() | df['estimated_end_date'].notna()
    ].copy()

    if tl.empty:
        st.info("No timeline data (no start/end dates set).")
        return

    today = pd.Timestamp(date.today())

    # Parse dates
    tl['start'] = pd.to_datetime(tl['estimated_start_date'], errors='coerce')
    tl['end']   = pd.to_datetime(tl['estimated_end_date'], errors='coerce')

    # Fill missing: if no start, use end-90d; if no end, use start+180d
    tl['start'] = tl['start'].fillna(tl['end'] - pd.Timedelta(days=90))
    tl['end']   = tl['end'].fillna(tl['start'] + pd.Timedelta(days=180))

    # Drop any that still have NaT
    tl = tl.dropna(subset=['start', 'end'])
    if tl.empty:
        st.info("No valid timeline data.")
        return

    # Sort by start date (reversed so earliest at top)
    tl = tl.sort_values('start', ascending=False)

    # Label: short code + name snippet
    tl['label'] = tl.apply(
        lambda r: f"{r['project_code'][-3:]} {r['project_name'][:18]}", axis=1)

    # Overdue flag
    tl['overdue'] = (tl['end'] < today) & (tl['status'].isin(_ACTIVE_STATUSES))
    tl['display_status'] = tl.apply(
        lambda r: '⚠️ OVERDUE' if r['overdue'] else r['status'].replace('_', ' ').title(),
        axis=1)

    # Color map
    color_map = {s.replace('_', ' ').title(): c for s, c in _STATUS_CHART_COLORS.items()}
    color_map['⚠️ OVERDUE'] = '#f44336'

    fig = px.timeline(
        tl,
        x_start='start',
        x_end='end',
        y='label',
        color='display_status',
        color_discrete_map=color_map,
        hover_data={
            'project_code': True,
            'project_name': True,
            'status': True,
            'start': '|%Y-%m-%d',
            'end': '|%Y-%m-%d',
            'label': False,
            'display_status': False,
            'overdue': False,
        },
    )

    # Today marker (shape + annotation separately — add_vline annotation has a bug)
    today_str = today.strftime('%Y-%m-%d')
    fig.add_shape(
        type="line", x0=today_str, x1=today_str, y0=0, y1=1,
        yref="paper", line=dict(color="red", width=1.5, dash="dash"),
    )
    fig.add_annotation(
        x=today_str, y=1.05, yref="paper",
        text="Today", showarrow=False,
        font=dict(size=10, color="red"),
    )

    fig.update_layout(
        height=max(200, 30 * len(tl)),
        margin=dict(l=10, r=10, t=5, b=30),
        xaxis_title="",
        yaxis_title="",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(size=9)),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
    )
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

    # Overdue callout
    overdue_list = tl[tl['overdue']]['project_code'].tolist()
    if overdue_list:
        st.caption(f"🔴 **Overdue:** {', '.join(overdue_list)}")


# ══════════════════════════════════════════════════════════════════════════════
# PROJECT TABLE + KPI DASHBOARD (Phase 1 Enhancement)
# ══════════════════════════════════════════════════════════════════════════════

def _render_project_table(status_filter, type_filter_id, pm_filter_id, f_search,
                          health_filter=None, date_from=None, date_to=None):
    """Render KPI dashboard + visual analytics + enhanced project table. Returns selected project_id or None."""
    df = get_projects_df(
        status=status_filter,
        type_id=type_filter_id,
        pm_id=pm_filter_id,
        search=f_search or None,
    )

    # ── Load supplementary data ──────────────────────────────────────────────
    pending_map    = _load_pending_counts()
    completion_map = _load_completion_map()

    # ── Client-side filters (health, date range) ─────────────────────────────
    # These filter AFTER DB query because they depend on computed columns.

    if date_from and date_to and not df.empty:
        _end = pd.to_datetime(df['estimated_end_date'], errors='coerce')
        _mask = _end.notna() & (_end.dt.date >= date_from) & (_end.dt.date <= date_to)
        df = df[_mask].copy()

    if health_filter and not df.empty:
        _health_col = df.apply(_compute_health, axis=1)
        df = df[_health_col == health_filter].copy()

    # ── ROW 1: Financial KPIs ────────────────────────────────────────────────
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Projects", len(df))

    # Portfolio value (sum of contract values)
    if not df.empty and 'effective_contract_value' in df.columns:
        portfolio_val = df['effective_contract_value'].dropna().sum()
        k2.metric("Portfolio Value", fmt_vnd(portfolio_val) if portfolio_val > 0 else "—")
    else:
        k2.metric("Portfolio Value", "—")

    k3.metric("Avg Est. GP%",
        f"{df['estimated_gp_percent'].mean():.1f}%"
        if not df.empty and df['estimated_gp_percent'].notna().any() else "—")
    k4.metric("Avg Actual GP%",
        f"{df['actual_gp_percent'].mean():.1f}%"
        if not df.empty and df['actual_gp_percent'].notna().any() else "—")

    # ── ROW 2: Operational KPIs ──────────────────────────────────────────────
    o1, o2, o3, o4 = st.columns(4)

    # Active projects
    active_statuses = {'IN_PROGRESS', 'COMMISSIONING'}
    active_count = len(df[df['status'].isin(active_statuses)]) if not df.empty else 0
    contracted   = len(df[df['status'] == 'CONTRACTED']) if not df.empty else 0
    o1.metric("Active", active_count, delta=f"+{contracted} contracted" if contracted > 0 else None,
              delta_color="off")

    # Total pending approvals (across filtered projects)
    total_pending = 0
    if not df.empty and pending_map:
        for pid in df['project_id']:
            total_pending += pending_map.get(int(pid), {}).get('total', 0)
    o2.metric("Pending Approval", total_pending,
              delta="items" if total_pending > 0 else None, delta_color="off")

    # Overdue projects (estimated_end_date < today, still active)
    overdue_count = 0
    if not df.empty:
        for _, row in df.iterrows():
            if row['status'] in _ACTIVE_STATUSES:
                end = row.get('estimated_end_date')
                if end is not None:
                    try:
                        if pd.to_datetime(end).date() < date.today():
                            overdue_count += 1
                    except Exception:
                        pass
    o3.metric("Overdue", overdue_count,
              delta="⚠️ needs attention" if overdue_count > 0 else "all on track",
              delta_color="inverse" if overdue_count > 0 else "off")

    # No estimate (no estimated_gp_percent → never estimated)
    no_est_count = 0
    if not df.empty:
        no_est_mask = (
            df['estimated_gp_percent'].isna()
            & ~df['status'].isin({'COMPLETED', 'CLOSED', 'CANCELLED'})
        )
        no_est_count = int(no_est_mask.sum())
    o4.metric("No Estimate", no_est_count,
              delta="projects" if no_est_count > 0 else None, delta_color="off")

    # ── Empty state (early exit) ────────────────────────────────────────────
    if df.empty:
        st.divider()
        st.info("No projects found.")
        return None

    # ── PHASE 2: Visual Analytics ────────────────────────────────────────────
    _render_visual_analytics(df)

    st.divider()

    # ── Enrich dataframe ─────────────────────────────────────────────────────
    display_df = df[[
        'project_code', 'project_name', 'project_type', 'customer_name',
        'status', 'pm_name',
        'effective_contract_value', 'currency_code',
        'estimated_gp_percent', 'actual_gp_percent',
        'estimated_cogs', 'actual_cogs',
        'estimated_start_date', 'estimated_end_date',
    ]].copy()

    # Health indicator (first column)
    display_df.insert(0, 'health', df.apply(_compute_health, axis=1))

    # Merge status icon INTO status text: "🔵 IN_PROGRESS"
    display_df['status'] = display_df['status'].map(
        lambda s: f"{STATUS_COLORS.get(s, '⚪')} {s}")

    # Formatted columns
    display_df['contract_value_fmt'] = display_df['effective_contract_value'].apply(
        lambda v: f"{v:,.0f}" if _is_num(v) else '—')
    display_df['est_gp_fmt'] = display_df['estimated_gp_percent'].apply(fmt_percent)
    display_df['act_gp_fmt'] = display_df['actual_gp_percent'].apply(fmt_percent)
    display_df['budget_pct'] = df.apply(_compute_budget_pct, axis=1)
    display_df['days_left']  = df.apply(_compute_days_left, axis=1)

    # Pending items column
    display_df['pending'] = df['project_id'].map(
        lambda pid: pending_map.get(int(pid), {}).get('total', 0) if pending_map else 0
    )
    display_df['pending_fmt'] = display_df['pending'].apply(
        lambda v: f"🔔 {v}" if v > 0 else '')

    # Completion % column (from WBS tasks)
    display_df['completion'] = df['project_id'].map(
        lambda pid: completion_map.get(int(pid)) if completion_map else None
    )
    display_df['completion_fmt'] = display_df['completion'].apply(
        lambda v: f"{int(v)}%" if _is_num(v) else '—')

    # ── Export button (above table) ──────────────────────────────────────────
    _exp_col1, _exp_col2 = st.columns([6, 1])
    _exp_col1.caption(f"**{len(display_df)} projects** matching filters")
    _export_df = _build_export_df(df, pending_map, completion_map)
    _exp_col2.download_button(
        "📥 Excel",
        data=_to_excel(_export_df),
        file_name=f"IL_Projects_{date.today().isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    # ── Render table ─────────────────────────────────────────────────────────
    event = st.dataframe(
        display_df,
        key=f"proj_table_{st.session_state.get('_tbl_key', 0)}",
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            'health':                   st.column_config.TextColumn('Health', width=55,
                                            help="🟢 Healthy | 🟡 Watch | 🔴 At Risk | ⚪ N/A — based on GP deviation, budget, schedule"),
            'project_code':             st.column_config.TextColumn('Code', width=140),
            'project_name':             st.column_config.TextColumn('Project Name'),
            'project_type':             st.column_config.TextColumn('Type', width=100),
            'customer_name':            st.column_config.TextColumn('Customer'),
            'status':                   st.column_config.TextColumn('Status', width=140),
            'pm_name':                  st.column_config.TextColumn('PM', width=90),
            'contract_value_fmt':       st.column_config.TextColumn('Contract Value', width=110),
            'currency_code':            st.column_config.TextColumn('CCY', width=45),
            'est_gp_fmt':               st.column_config.TextColumn('Est GP%', width=75),
            'act_gp_fmt':               st.column_config.TextColumn('Act GP%', width=75),
            'budget_pct':               st.column_config.TextColumn('Budget', width=75),
            'days_left':                st.column_config.TextColumn('Deadline', width=90),
            'completion_fmt':           st.column_config.TextColumn('Done%', width=55,
                                            help="Average task completion from WBS"),
            'pending_fmt':              st.column_config.TextColumn('Pending', width=65),
            # Hidden raw columns
            'effective_contract_value': None,
            'estimated_gp_percent':     None,
            'actual_gp_percent':        None,
            'estimated_cogs':           None,
            'actual_cogs':              None,
            'estimated_start_date':     None,
            'estimated_end_date':       None,
            'pending':                  None,
            'completion':               None,
        },
    )

    # ── Legend ────────────────────────────────────────────────────────────────
    st.caption("**Health:** 🟢 On track &nbsp;|&nbsp; 🟡 Watch &nbsp;|&nbsp; 🔴 At risk &nbsp;|&nbsp; ⚪ N/A "
               "&nbsp;&nbsp;•&nbsp;&nbsp; **Status:** icon in Status column")

    sel = event.selection.rows
    if sel:
        return int(df.iloc[sel[0]]['project_id'])
    return None


# ══════════════════════════════════════════════════════════════════════════════
# PAGE LAYOUT
# ══════════════════════════════════════════════════════════════════════════════

st.title("🏗️ IL Projects")

# ── Sidebar filters ───────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filters")

    # My Projects toggle
    my_projects = st.toggle("📌 My Projects Only", value=False, key="my_proj_toggle",
                            help="Chỉ hiển thị dự án bạn là PM")

    f_search = st.text_input("Search", placeholder="code / name / customer")
    f_status = st.selectbox("Status", ["All", "DRAFT", "ESTIMATING", "PROPOSAL_SENT",
                                        "GO", "CONDITIONAL", "NO_GO", "CONTRACTED",
                                        "IN_PROGRESS", "COMMISSIONING", "COMPLETED",
                                        "WARRANTY", "CLOSED", "CANCELLED"])
    f_type   = st.selectbox("Project Type", ["All"] + [f"[{t['code']}] {t['name']}" for t in proj_types])
    f_pm     = st.selectbox("PM", ["All"] + [e['full_name'] for e in employees])

    # Health filter (Phase 3)
    f_health = st.selectbox("Health", ["All", "🟢 On track", "🟡 Watch", "🔴 At risk", "⚪ N/A"],
                            key="f_health", help="Filter by composite health indicator")

    # Date range filter (Phase 3)
    use_date = st.checkbox("📅 Filter by end date", value=False, key="f_use_date")
    if use_date:
        _dc1, _dc2 = st.columns(2)
        f_date_from = _dc1.date_input("From", value=date.today().replace(day=1), key="f_date_from")
        f_date_to   = _dc2.date_input("To", value=date.today(), key="f_date_to")
    else:
        f_date_from = f_date_to = None

    st.divider()
    if ctx.can('project.create'):
        if st.button("➕ New Project", width="stretch", type="primary"):
            st.session_state["open_create"] = True
    st.divider()
    st.caption(f"Role: {get_role_badge(ctx.role())}")

# ── Resolve filters ───────────────────────────────────────────────────────────
status_filter  = None if f_status == "All" else f_status
type_filter_id = None
if f_type != "All":
    _code = f_type.split("]")[0][1:]
    hit   = next((t for t in proj_types if t['code'] == _code), None)
    type_filter_id = hit['id'] if hit else None
pm_filter_id = None
if f_pm != "All":
    hit  = next((e for e in employees if e['full_name'] == f_pm), None)
    pm_filter_id = hit['id'] if hit else None

# Health filter → emoji prefix
health_filter = None
if f_health != "All":
    health_filter = f_health[0]  # '🟢', '🟡', '🔴', '⚪'

# "My Projects" override — filter by current user's employee_id as PM
if my_projects and emp_int_id and not pm_filter_id:
    pm_filter_id = emp_int_id

# ── Project table ─────────────────────────────────────────────────────────────
selected_pid = _render_project_table(
    status_filter, type_filter_id, pm_filter_id, f_search,
    health_filter=health_filter,
    date_from=f_date_from, date_to=f_date_to,
)

# ── Action bar (shown when row selected) ─────────────────────────────────────
if selected_pid:
    proj_info = get_project(selected_pid)
    if proj_info:
        st.markdown(
            f"**Selected:** `{proj_info['project_code']}` — {proj_info['project_name']} "
            f"({STATUS_COLORS.get(proj_info['status'], '⚪')} {proj_info['status']})"
        )

        # ── Primary actions ──────────────────────────────────────────────
        ab1, ab2, ab3, ab4, ab5 = st.columns([1, 1, 1, 1, 1])
        if ab1.button("👁️ View", type="primary", use_container_width=True):
            st.session_state["open_view_pid"] = selected_pid
            st.rerun()
        if ctx.can('project.edit', selected_pid):
            if ab2.button("✏️ Edit", use_container_width=True):
                st.session_state["open_edit_pid"] = selected_pid
                st.rerun()
        if ctx.can('project.delete', selected_pid):
            if ab3.button("🗑 Delete", use_container_width=True):
                if soft_delete_project(selected_pid, user_id):
                    st.success("Project deleted.")
                    _load_lookups.clear()
                    _load_pending_counts.clear()
                    _load_completion_map.clear()
                    st.rerun()
        if ab4.button("✖ Deselect", use_container_width=True):
            st.session_state["_tbl_key"] = st.session_state.get("_tbl_key", 0) + 1
            st.rerun()

        # ── Quick Jump (navigate to other pages pre-filtered) ────────────
        # Pre-select project on target page by setting its selectbox key
        _qj_label = f"{proj_info['project_code']} — {proj_info['project_name']}"
        st.caption("**Quick Jump** — open this project in:")
        jc1, jc2, jc3, jc4 = st.columns(4)
        if jc1.button("📊 Estimate GP", use_container_width=True, key="qj_est"):
            st.session_state["est_project"] = _qj_label
            st.switch_page("pages/2_📊_Estimate_GP.py")
        if jc2.button("⏱️ Cost Tracking", use_container_width=True, key="qj_cost"):
            st.session_state["ct_project"] = _qj_label
            st.switch_page("pages/3_⏱️_Cost_Tracking.py")
        if jc3.button("📈 COGS Dashboard", use_container_width=True, key="qj_cogs"):
            st.session_state["cogs_project"] = _qj_label
            st.switch_page("pages/4_📈_COGS_Dashboard.py")
        if jc4.button("🛒 Purchase Request", use_container_width=True, key="qj_pr"):
            st.session_state["pr_project"] = _qj_label
            st.switch_page("pages/IL_5_🛒_Purchase_Request.py")


# ── Dialog triggers (only via explicit button click) ──────────────────────────
if st.session_state.pop("open_create", False):
    _dialog_create_project()

if "open_view_pid" in st.session_state:
    pid = st.session_state.pop("open_view_pid")
    _dialog_view_project(pid)

if "open_edit_pid" in st.session_state:
    pid = st.session_state.pop("open_edit_pid")
    _dialog_edit_project(pid)