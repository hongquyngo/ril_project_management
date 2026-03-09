# pages/IL_1_🏗️_Projects.py
"""
IL Projects — Master list + Create / Edit
UX: @st.dialog cho CRUD | @st.fragment cho project table | session state cho dialog chaining
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

logger = logging.getLogger(__name__)
auth = AuthManager()

st.set_page_config(page_title="IL Projects", page_icon="🏗️", layout="wide")
auth.require_auth()
user_id   = str(auth.get_user_id())
user_role = st.session_state.get('user_role', '')
is_admin  = auth.is_admin()


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
            st.cache_data.clear()
            st.session_state["open_view_pid"] = new_id
            st.rerun()
        except Exception as e:
            st.error(f"Save failed: {e}")


@st.dialog("✏️ Edit Project", width="large")
def _dialog_edit_project(project_id: int):
    proj = get_project(project_id) or {}
    with st.form("edit_project_form"):
        data = _project_form_fields(proj, is_create=False)
        col_save, col_cancel = st.columns(2)
        submitted = col_save.form_submit_button("💾 Save", type="primary", width="stretch")
        cancelled = col_cancel.form_submit_button("✖ Cancel", width="stretch")

    if cancelled:
        st.session_state["open_view_pid"] = project_id
        st.rerun()
    if submitted:
        if not data['project_name']:
            st.error("Project Name is required.")
            return
        try:
            update_project(project_id, data, user_id)
            st.success("✅ Project updated!")
            st.cache_data.clear()
            st.session_state["open_view_pid"] = project_id
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
                if not ms_name:
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
# PROJECT TABLE + ACTION BAR (no @st.fragment — avoids dialog timing issues)
# ══════════════════════════════════════════════════════════════════════════════

def _render_project_table(status_filter, type_filter_id, pm_filter_id, f_search):
    """Render project table. Returns selected project_id or None."""
    df = get_projects_df(
        status=status_filter,
        type_id=type_filter_id,
        pm_id=pm_filter_id,
        search=f_search or None,
    )

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Projects", len(df))
    col2.metric("In Progress",    len(df[df['status'] == 'IN_PROGRESS']) if not df.empty else 0)
    col3.metric("Avg Est. GP%",
        f"{df['estimated_gp_percent'].mean():.1f}%" if not df.empty and df['estimated_gp_percent'].notna().any() else "—")
    col4.metric("Avg Actual GP%",
        f"{df['actual_gp_percent'].mean():.1f}%" if not df.empty and df['actual_gp_percent'].notna().any() else "—")

    st.divider()

    if df.empty:
        st.info("No projects found.")
        return None

    display_df = df[[
        'project_code', 'project_name', 'project_type', 'customer_name',
        'status', 'pm_name',
        'effective_contract_value', 'currency_code',
        'estimated_gp_percent', 'actual_gp_percent',
        'estimated_start_date', 'estimated_end_date',
    ]].copy()
    display_df.insert(0, '●', display_df['status'].map(lambda s: STATUS_COLORS.get(s, '⚪')))

    display_df['contract_value_fmt'] = display_df['effective_contract_value'].apply(
        lambda v: f"{v:,.0f}" if v is not None and str(v) not in ('', 'nan', 'None') else '—'
    )
    display_df['est_gp_fmt'] = display_df['estimated_gp_percent'].apply(fmt_percent)
    display_df['act_gp_fmt'] = display_df['actual_gp_percent'].apply(fmt_percent)

    event = st.dataframe(
        display_df,
        key="proj_table",
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            '●':                        st.column_config.TextColumn('', width=30),
            'project_code':             st.column_config.TextColumn('Code'),
            'project_name':             st.column_config.TextColumn('Project Name'),
            'project_type':             st.column_config.TextColumn('Type'),
            'customer_name':            st.column_config.TextColumn('Customer'),
            'status':                   st.column_config.TextColumn('Status'),
            'pm_name':                  st.column_config.TextColumn('PM'),
            'contract_value_fmt':       st.column_config.TextColumn('Contract Value'),
            'currency_code':            st.column_config.TextColumn('CCY', width=50),
            'est_gp_fmt':               st.column_config.TextColumn('Est. GP%', width=90),
            'act_gp_fmt':               st.column_config.TextColumn('Act. GP%', width=90),
            'estimated_start_date':     st.column_config.DateColumn('Start'),
            'estimated_end_date':       st.column_config.DateColumn('End'),
            'effective_contract_value': None,
            'estimated_gp_percent':     None,
            'actual_gp_percent':        None,
        },
    )

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
    f_search = st.text_input("Search", placeholder="code / name / customer")
    f_status = st.selectbox("Status", ["All", "DRAFT", "ESTIMATING", "PROPOSAL_SENT",
                                        "GO", "CONDITIONAL", "NO_GO", "CONTRACTED",
                                        "IN_PROGRESS", "COMMISSIONING", "COMPLETED",
                                        "WARRANTY", "CLOSED", "CANCELLED"])
    f_type   = st.selectbox("Project Type", ["All"] + [f"[{t['code']}] {t['name']}" for t in proj_types])
    f_pm     = st.selectbox("PM", ["All"] + [e['full_name'] for e in employees])

    st.divider()
    if st.button("➕ New Project", width="stretch", type="primary"):
        st.session_state["open_create"] = True

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

# ── Project table ─────────────────────────────────────────────────────────────
selected_pid = _render_project_table(status_filter, type_filter_id, pm_filter_id, f_search)

# ── Action bar (shown when row selected) ─────────────────────────────────────
if selected_pid:
    proj_info = get_project(selected_pid)
    if proj_info:
        st.markdown(
            f"**Selected:** `{proj_info['project_code']}` — {proj_info['project_name']} "
            f"({STATUS_COLORS.get(proj_info['status'], '⚪')} {proj_info['status']})"
        )
        ab1, ab2, ab3, _ = st.columns([1, 1, 1, 4])
        if ab1.button("👁️ View", type="primary", use_container_width=True):
            st.session_state["open_view_pid"] = selected_pid
            st.rerun()
        if ab2.button("✏️ Edit", use_container_width=True):
            st.session_state["open_edit_pid"] = selected_pid
            st.rerun()
        if is_admin:
            if ab3.button("🗑 Delete", use_container_width=True):
                if soft_delete_project(selected_pid, user_id):
                    st.success("Project deleted.")
                    st.cache_data.clear()
                    st.rerun()

# ── Dialog triggers (only via explicit button click) ──────────────────────────
if st.session_state.pop("open_create", False):
    _dialog_create_project()

if "open_view_pid" in st.session_state:
    pid = st.session_state.pop("open_view_pid")
    _dialog_view_project(pid)

if "open_edit_pid" in st.session_state:
    pid = st.session_state.pop("open_edit_pid")
    _dialog_edit_project(pid)