# pages/IL_9_📊_Progress.py
"""
Progress Reports & Quality Checklists.

v3.0 — Role-based UX:
  Phase 1: Role resolution + access control
  Phase 2: KPI banner (latest RAG, QC summary, upcoming inspections)
  Phase 3: Reports tab: permission-gated CRUD
  Phase 4: Quality tab: quick filters, permission-gated CRUD
  Phase 5: User Guide (wbs_guide_9_progress.py)

  (v2.0 bootstrap cache preserved)
"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta
import logging

from utils.auth import AuthManager
from utils.il_project import (
    get_projects_df, get_project, get_employees, get_milestones_df,
    fmt_vnd, STATUS_COLORS,
)
from utils.il_project.wbs_queries import get_project_members_df
from utils.il_project.wbs_execution_queries import (
    bootstrap_progress_data,
    get_progress_reports_df, get_progress_report, generate_report_number,
    create_progress_report, update_progress_report,
    get_quality_checklists_df, get_quality_checklist,
    create_quality_checklist, update_quality_checklist, soft_delete_quality_checklist,
    get_entity_medias, upload_and_attach, unlink_media, get_attachment_url,
)
from utils.il_project.wbs_helpers import (
    MEMBER_ROLE_LABELS,
    invalidate_progress_cache, render_attachments,
    resolve_project_role,
)
from utils.il_project.wbs_guide_common import search_guide
from utils.il_project.wbs_guide_9_progress import (
    get_progress_guide_sections, get_progress_faq, get_progress_workflows,
    get_progress_context_tips,
)

logger = logging.getLogger(__name__)
auth = AuthManager()

st.set_page_config(page_title="Progress & Quality", page_icon="📊", layout="wide")
auth.require_auth()
user_id     = str(auth.get_user_id())
employee_id = st.session_state.get('employee_id')
is_admin    = auth.is_admin()

# ── Constants ────────────────────────────────────────────────────────────────
REPORT_TYPES    = ['WEEKLY', 'BIWEEKLY', 'MONTHLY', 'MILESTONE', 'AD_HOC']
RAG_STATUSES    = ['ON_TRACK', 'AT_RISK', 'DELAYED', 'AHEAD', 'CRITICAL']
RAG_ICONS       = {'ON_TRACK': '🟢', 'AT_RISK': '🟡', 'DELAYED': '🔴', 'AHEAD': '🔵', 'CRITICAL': '🔴'}
SCHEDULE_OPTS   = ['ON_TRACK', 'AT_RISK', 'DELAYED', 'AHEAD']
COST_OPTS       = ['UNDER_BUDGET', 'ON_BUDGET', 'OVER_BUDGET']
QUALITY_OPTS    = ['SATISFACTORY', 'NEEDS_IMPROVEMENT', 'UNSATISFACTORY']
REPORT_STATUSES = ['DRAFT', 'SUBMITTED', 'REVIEWED']

QC_TYPES = ['FAT', 'SAT', 'INSPECTION', 'COMMISSIONING', 'HANDOVER', 'SAFETY', 'OTHER']
QC_STATUSES = ['PLANNED', 'IN_PROGRESS', 'PASSED', 'FAILED', 'CONDITIONAL', 'CANCELLED']
QC_STATUS_ICONS = {'PLANNED': '⚪', 'IN_PROGRESS': '🔵', 'PASSED': '✅',
                   'FAILED': '🔴', 'CONDITIONAL': '🟡', 'CANCELLED': '❌'}

# ── Cached lookups ───────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load_employees():
    return get_employees()

employees = _load_employees()
emp_map = {e['id']: e['full_name'] for e in employees}

@st.cache_data(ttl=60, show_spinner=False)
def _cached_progress_data(project_id: int, _v: int = 0):
    return bootstrap_progress_data(project_id)

def _get_prog(project_id: int) -> dict:
    v = st.session_state.get(f'_prog_v_{project_id}', 0)
    return _cached_progress_data(project_id, _v=v)

@st.cache_data(ttl=60, show_spinner=False)
def _cached_members(project_id: int, _v: int = 0):
    return get_project_members_df(project_id)


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

st.title("📊 Progress & Quality")

with st.sidebar:
    st.header("Project")
    proj_df = get_projects_df(status=None)
    if proj_df.empty:
        st.warning("No projects found.")
        st.stop()
    proj_opts = proj_df.apply(lambda r: f"{r['project_code']} — {r['project_name']}", axis=1).tolist()
    proj_idx = st.selectbox("Select Project", range(len(proj_opts)),
                            format_func=lambda i: proj_opts[i], key="pq_proj")
    selected_project_id = int(proj_df.iloc[proj_idx]['project_id'])
    proj_info = get_project(selected_project_id)

    st.divider()
    if st.button("❓ User Guide", use_container_width=True, key="sidebar_prog_guide"):
        st.session_state["open_progress_guide"] = True

# ── Load data ──
prog = _get_prog(selected_project_id)
if not prog['ok']:
    st.error(f"⚠️ {prog['error']}")
    st.stop()

v_mem = st.session_state.get(f'_wbs_v_{selected_project_id}', 0)
members_df = _cached_members(selected_project_id, _v=v_mem)


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1: ROLE RESOLUTION + ACCESS CONTROL
# ══════════════════════════════════════════════════════════════════════════════

perms = resolve_project_role(members_df, employee_id, is_admin)

if perms['tier'] == 'restricted' and not is_admin:
    st.warning("🔒 Progress & Quality is not available for your role.")
    st.page_link("pages/IL_6_📋_WBS.py", label="📋 Go to WBS", icon="📋")
    st.stop()

# Permission flags
can_create_report = perms['tier'] in ('manager', 'lead')
can_create_qc     = perms['tier'] in ('manager', 'lead')
can_delete_qc     = perms['tier'] == 'manager'

_my_name = emp_map.get(employee_id, 'there')
_my_role_label = MEMBER_ROLE_LABELS.get(perms['role'], perms.get('role') or 'Guest')


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2: WELCOME BANNER + KPIs
# ══════════════════════════════════════════════════════════════════════════════

if proj_info:
    wc1, wc2 = st.columns([7, 1])
    wc1.markdown(f"Hi **{_my_name}** · `{_my_role_label}` on **{proj_info['project_code']}** — {proj_info['project_name']}")
    if wc2.button("❓", key="banner_prog_guide", help="Open User Guide"):
        st.session_state["open_progress_guide"] = True

rpt_df = prog['reports']
qc_df  = prog['quality']
today  = date.today()

# KPI row
k1, k2, k3, k4, k5 = st.columns(5)

# Latest report RAG
latest_rag = '—'
if not rpt_df.empty:
    latest = rpt_df.iloc[0]  # sorted by date DESC
    latest_rag = f"{RAG_ICONS.get(latest.get('overall_status'), '⚪')} {latest.get('overall_status', '—')}"
k1.metric("Latest RAG", latest_rag)

# Reports count
rpt_total = len(rpt_df) if not rpt_df.empty else 0
rpt_draft = len(rpt_df[rpt_df['status'] == 'DRAFT']) if rpt_total else 0
k2.metric("Reports", f"{rpt_total}", delta=f"{rpt_draft} draft" if rpt_draft else None)

# QC summary
qc_total  = len(qc_df) if not qc_df.empty else 0
qc_passed = len(qc_df[qc_df['status'] == 'PASSED']) if qc_total else 0
qc_failed = len(qc_df[qc_df['status'] == 'FAILED']) if qc_total else 0
k3.metric("QC Passed", f"{qc_passed}/{qc_total}")
k4.metric("QC Failed", qc_failed,
          delta=None if qc_failed == 0 else f"-{qc_failed}",
          delta_color="inverse")

# Upcoming inspections
upcoming_insp = 0
if qc_total and 'inspection_date' in qc_df.columns:
    planned_qc = qc_df[qc_df['status'].isin(['PLANNED', 'IN_PROGRESS'])]
    has_date = planned_qc[planned_qc['inspection_date'].notna()]
    if not has_date.empty:
        insp_dates = pd.to_datetime(has_date['inspection_date']).dt.date
        upcoming_insp = int(((insp_dates >= today) & (insp_dates <= today + timedelta(days=14))).sum())
k5.metric("Upcoming QC (14d)", upcoming_insp)

# Customer sign-off pending
if qc_total and 'customer_signed_off' in qc_df.columns:
    passed_no_sign = qc_df[(qc_df['status'] == 'PASSED') & (qc_df['customer_signed_off'] == 0)]
    if len(passed_no_sign) > 0 and perms['tier'] == 'manager':
        st.caption(f"⏳ **{len(passed_no_sign)}** QC passed but pending customer sign-off")

st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════

tab_reports, tab_quality = st.tabs(["📊 Progress Reports", "✅ Quality Checklists"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: PROGRESS REPORTS — Permission-gated
# ══════════════════════════════════════════════════════════════════════════════

with tab_reports:
    ra1, _ = st.columns([1, 6])
    if can_create_report:
        if ra1.button("➕ New Report", type="primary", key="btn_rpt"):
            st.session_state["open_create_report"] = True

    if not rpt_df.empty:
        display_rpt = rpt_df.copy()
        display_rpt['rag'] = display_rpt['overall_status'].map(lambda s: RAG_ICONS.get(s, '⚪'))
        display_rpt['pct_fmt'] = display_rpt['overall_completion_percent'].apply(
            lambda v: f"{v:.0f}%" if pd.notna(v) else '—'
        )

        event_rpt = st.dataframe(
            display_rpt, key="rpt_tbl", width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            column_config={
                'rag':               st.column_config.TextColumn('', width=30),
                'report_number':     st.column_config.TextColumn('#', width=80),
                'report_type':       st.column_config.TextColumn('Type', width=80),
                'report_date':       st.column_config.DateColumn('Date'),
                'overall_status':    st.column_config.TextColumn('RAG', width=90),
                'pct_fmt':           st.column_config.TextColumn('%', width=60),
                'schedule_status':   st.column_config.TextColumn('Schedule', width=90),
                'cost_status':       st.column_config.TextColumn('Cost', width=100),
                'status':            st.column_config.TextColumn('Status', width=80),
                'prepared_by_name':  st.column_config.TextColumn('By'),
                'file_count':        st.column_config.NumberColumn('📎', width=40),
                'id': None, 'overall_completion_percent': None,
                'quality_status': None, 'reviewed_by_name': None,
            },
        )
        sel_rpt = event_rpt.selection.rows
        if sel_rpt:
            sel_rpt_id = int(display_rpt.iloc[sel_rpt[0]]['id'])
            is_preparer = display_rpt.iloc[sel_rpt[0]].get('prepared_by') == employee_id
            rb1, rb2, _ = st.columns([1, 1, 5])
            if rb1.button("👁️ View", type="primary", key="rpt_view"):
                st.session_state["open_view_report"] = sel_rpt_id
                st.rerun()
            if perms.get('can_edit_any_task') or is_preparer:
                if rb2.button("✏️ Edit", key="rpt_edit"):
                    st.session_state["open_edit_report"] = sel_rpt_id
                    st.rerun()
    else:
        st.info("No progress reports yet." + (" Click **➕ New Report** to create one." if can_create_report else ""))


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: QUALITY CHECKLISTS — Quick filters + permission-gated
# ══════════════════════════════════════════════════════════════════════════════

with tab_quality:
    qa1, _ = st.columns([1, 6])
    if can_create_qc:
        if qa1.button("➕ New Checklist", type="primary", key="btn_qc"):
            st.session_state["open_create_qc"] = True

    if not qc_df.empty:
        # Quick filter chips
        st.caption("Quick filters:")
        fc1, fc2, fc3, fc4, _ = st.columns([1, 1, 1, 1, 3])
        qf_pending  = fc1.toggle("⚪ Planned", value=False, key="qc_qf_pending")
        qf_failed   = fc2.toggle("🔴 Failed", value=False, key="qc_qf_failed")
        qf_no_sign  = fc3.toggle("⏳ No Cust. Sign", value=False, key="qc_qf_nosign")
        qf_my_insp  = fc4.toggle("🙋 My Inspections", value=False, key="qc_qf_mine")

        filtered_qc = qc_df.copy()
        if qf_pending:
            filtered_qc = filtered_qc[filtered_qc['status'].isin(['PLANNED', 'IN_PROGRESS'])]
        if qf_failed:
            filtered_qc = filtered_qc[filtered_qc['status'].isin(['FAILED', 'CONDITIONAL'])]
        if qf_no_sign and 'customer_signed_off' in filtered_qc.columns:
            filtered_qc = filtered_qc[
                (filtered_qc['status'] == 'PASSED') & (filtered_qc['customer_signed_off'] == 0)
            ]
        if qf_my_insp and employee_id and 'inspector_id' in qc_df.columns:
            filtered_qc = filtered_qc[filtered_qc.get('inspector_id') == employee_id]

        # KPIs
        qk1, qk2, qk3, qk4 = st.columns(4)
        qk1.metric("Total", len(qc_df))
        qk2.metric("Passed", qc_passed)
        qk3.metric("Failed", qc_failed)
        cust_signed = int(qc_df['customer_signed_off'].sum()) if 'customer_signed_off' in qc_df.columns else 0
        qk4.metric("Customer Signed", cust_signed)

        if filtered_qc.empty:
            st.info("No checklists match current filters.")
        else:
            display_qc = filtered_qc.copy()
            display_qc['st_icon'] = display_qc['status'].map(lambda s: QC_STATUS_ICONS.get(s, '⚪'))
            display_qc['rate_fmt'] = display_qc['pass_rate'].apply(
                lambda v: f"{v:.0f}%" if pd.notna(v) else '—')
            display_qc['cust'] = display_qc['customer_signed_off'].map(lambda v: '✅' if v else '⚪')

            event_qc = st.dataframe(
                display_qc, key="qc_tbl", width="stretch", hide_index=True,
                on_select="rerun", selection_mode="single-row",
                column_config={
                    'st_icon':            st.column_config.TextColumn('', width=30),
                    'checklist_type':     st.column_config.TextColumn('Type', width=100),
                    'checklist_name':     st.column_config.TextColumn('Name'),
                    'status':             st.column_config.TextColumn('Status', width=90),
                    'inspection_date':    st.column_config.DateColumn('Date'),
                    'inspector_name':     st.column_config.TextColumn('Inspector'),
                    'rate_fmt':           st.column_config.TextColumn('Pass %', width=70),
                    'cust':               st.column_config.TextColumn('Cust.', width=50),
                    'retest_date':        st.column_config.DateColumn('Retest'),
                    'file_count':         st.column_config.NumberColumn('📎', width=40),
                    'id': None, 'location': None, 'customer_witness': None,
                    'total_items': None, 'passed_items': None, 'failed_items': None,
                    'pass_rate': None, 'customer_signed_off': None,
                    'signed_off_by_name': None, 'milestone_name': None,
                },
            )
            sel_qc = event_qc.selection.rows
            if sel_qc:
                sel_qc_row = display_qc.iloc[sel_qc[0]]
                sel_qc_id = int(sel_qc_row['id'])
                is_inspector = sel_qc_row.get('inspector_id') == employee_id

                qb1, qb2, qb3, _ = st.columns([1, 1, 1, 4])
                if qb1.button("👁️ View", type="primary", key="qc_view"):
                    st.session_state["open_view_qc"] = sel_qc_id
                    st.rerun()
                if perms.get('can_edit_any_task') or is_inspector:
                    if qb2.button("✏️ Edit", key="qc_edit"):
                        st.session_state["open_edit_qc"] = sel_qc_id
                        st.rerun()
                if can_delete_qc:
                    if qb3.button("🗑 Delete", key="qc_del"):
                        soft_delete_quality_checklist(sel_qc_id, user_id)
                        invalidate_progress_cache(selected_project_id)
                        st.rerun()
    else:
        st.info("No quality checklists yet." + (" Click **➕ New Checklist** to create one." if can_create_qc else ""))


# ══════════════════════════════════════════════════════════════════════════════
# DIALOGS — Progress Reports
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("📊 New Progress Report", width="large")
def _dialog_create_report():
    with st.form("create_report_form"):
        c1, c2 = st.columns(2)
        rpt_type = c1.selectbox("Report Type", REPORT_TYPES)
        rpt_date = c2.date_input("Report Date", value=date.today())
        d1, d2 = st.columns(2)
        period_from = d1.date_input("Period From", value=date.today() - timedelta(days=7))
        period_to   = d2.date_input("Period To", value=date.today())
        st.markdown("**Status Indicators**")
        s1, s2, s3, s4 = st.columns(4)
        rag = s1.selectbox("Overall RAG", RAG_STATUSES)
        sched = s2.selectbox("Schedule", SCHEDULE_OPTS)
        cost = s3.selectbox("Cost", COST_OPTS, index=1)
        qual = s4.selectbox("Quality", QUALITY_OPTS)
        pct = st.number_input("Completion %", value=float(proj_info.get('overall_completion_percent') or 0),
                               min_value=0.0, max_value=100.0)
        st.markdown("**Narrative**")
        summary = st.text_area("Executive Summary", height=80)
        accomplishments = st.text_area("Accomplishments This Period", height=80)
        planned = st.text_area("Planned Next Period", height=80)
        blockers = st.text_area("Blockers & Risks", height=60)
        col_s, col_c = st.columns(2)
        submitted = col_s.form_submit_button("💾 Create", type="primary", width="stretch")
        cancelled = col_c.form_submit_button("✖ Cancel", width="stretch")

    if cancelled:
        st.rerun()
    if submitted:
        new_id = create_progress_report({
            'project_id': selected_project_id,
            'report_number': generate_report_number(selected_project_id),
            'report_type': rpt_type, 'report_date': rpt_date,
            'reporting_period_from': period_from, 'reporting_period_to': period_to,
            'overall_status': rag, 'overall_completion_percent': pct,
            'schedule_status': sched, 'cost_status': cost, 'quality_status': qual,
            'summary': summary.strip() or None,
            'accomplishments': accomplishments.strip() or None,
            'planned_next_period': planned.strip() or None,
            'blockers': blockers.strip() or None,
            'planned_completion_percent': None,
            'actual_cost_to_date': None, 'budget_at_completion': None,
            'prepared_by': employee_id,
        }, user_id)
        st.success(f"✅ Report created: RPT-{new_id}")
        invalidate_progress_cache(selected_project_id)
        st.rerun()


@st.dialog("📊 Progress Report", width="large")
def _dialog_view_report(report_id: int):
    rpt = get_progress_report(report_id)
    if not rpt:
        st.warning("Report not found.")
        return
    hc1, hc2 = st.columns([5, 1])
    hc1.subheader(f"{RAG_ICONS.get(rpt.get('overall_status'), '⚪')} {rpt.get('report_number', '')} — {rpt.get('report_type', '')}")
    is_preparer = rpt.get('prepared_by') == employee_id
    if perms.get('can_edit_any_task') or is_preparer:
        if hc2.button("✏️ Edit", type="primary"):
            st.session_state["open_edit_report"] = report_id
            st.rerun()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("RAG", rpt.get('overall_status', '—'))
    k2.metric("Completion", f"{rpt.get('overall_completion_percent') or 0:.0f}%")
    k3.metric("Schedule", rpt.get('schedule_status', '—'))
    k4.metric("Cost", rpt.get('cost_status', '—'))

    st.markdown(f"**Date:** {rpt.get('report_date', '—')} · **Period:** {rpt.get('reporting_period_from', '—')} → {rpt.get('reporting_period_to', '—')}")
    st.markdown(f"**Prepared by:** {rpt.get('prepared_by_name', '—')} · **Status:** {rpt.get('status', '—')}")

    if rpt.get('summary'):
        st.markdown(f"**Summary:**\n{rpt['summary']}")
    if rpt.get('accomplishments'):
        st.success(f"**Accomplishments:**\n{rpt['accomplishments']}")
    if rpt.get('planned_next_period'):
        st.info(f"**Planned Next:**\n{rpt['planned_next_period']}")
    if rpt.get('blockers'):
        st.warning(f"**Blockers:**\n{rpt['blockers']}")

    render_attachments('progress_report', report_id, selected_project_id, user_id)


@st.dialog("✏️ Edit Report", width="large")
def _dialog_edit_report(report_id: int):
    rpt = get_progress_report(report_id) or {}
    with st.form("edit_report_form"):
        c1, c2, c3 = st.columns(3)
        rpt_type = c1.selectbox("Type", REPORT_TYPES,
                                index=REPORT_TYPES.index(rpt['report_type']) if rpt.get('report_type') in REPORT_TYPES else 0)
        rpt_date = c2.date_input("Date", value=rpt.get('report_date') or date.today())
        rpt_status = c3.selectbox("Report Status", REPORT_STATUSES,
                                  index=REPORT_STATUSES.index(rpt['status']) if rpt.get('status') in REPORT_STATUSES else 0)
        d1, d2 = st.columns(2)
        pf = d1.date_input("Period From", value=rpt.get('reporting_period_from'))
        pt = d2.date_input("Period To", value=rpt.get('reporting_period_to'))
        s1, s2, s3, s4 = st.columns(4)
        rag = s1.selectbox("RAG", RAG_STATUSES,
                           index=RAG_STATUSES.index(rpt['overall_status']) if rpt.get('overall_status') in RAG_STATUSES else 0)
        sched = s2.selectbox("Schedule", SCHEDULE_OPTS,
                             index=SCHEDULE_OPTS.index(rpt['schedule_status']) if rpt.get('schedule_status') in SCHEDULE_OPTS else 0)
        cost = s3.selectbox("Cost", COST_OPTS,
                            index=COST_OPTS.index(rpt['cost_status']) if rpt.get('cost_status') in COST_OPTS else 1)
        qual = s4.selectbox("Quality", QUALITY_OPTS,
                            index=QUALITY_OPTS.index(rpt['quality_status']) if rpt.get('quality_status') in QUALITY_OPTS else 0)
        pct = st.number_input("Completion %", value=float(rpt.get('overall_completion_percent') or 0),
                               min_value=0.0, max_value=100.0)
        summary = st.text_area("Summary", value=rpt.get('summary') or '', height=80)
        accomplishments = st.text_area("Accomplishments", value=rpt.get('accomplishments') or '', height=80)
        planned = st.text_area("Planned Next", value=rpt.get('planned_next_period') or '', height=80)
        blockers = st.text_area("Blockers", value=rpt.get('blockers') or '', height=60)
        emp_opts = ["(None)"] + [e['full_name'] for e in employees]
        rev_idx = next((i + 1 for i, e in enumerate(employees) if e['id'] == rpt.get('reviewed_by')), 0)
        reviewer = st.selectbox("Reviewed By", emp_opts, index=rev_idx)
        reviewer_id = employees[emp_opts.index(reviewer) - 1]['id'] if reviewer != "(None)" else None
        col_s, col_c = st.columns(2)
        submitted = col_s.form_submit_button("💾 Save", type="primary", width="stretch")
        cancelled = col_c.form_submit_button("✖ Cancel", width="stretch")

    if cancelled:
        st.rerun()
    if submitted:
        update_progress_report(report_id, {
            'report_type': rpt_type, 'report_date': rpt_date,
            'reporting_period_from': pf, 'reporting_period_to': pt,
            'overall_status': rag, 'overall_completion_percent': pct,
            'schedule_status': sched, 'cost_status': cost, 'quality_status': qual,
            'summary': summary.strip() or None,
            'accomplishments': accomplishments.strip() or None,
            'planned_next_period': planned.strip() or None,
            'blockers': blockers.strip() or None,
            'planned_completion_percent': rpt.get('planned_completion_percent'),
            'actual_cost_to_date': rpt.get('actual_cost_to_date'),
            'budget_at_completion': rpt.get('budget_at_completion'),
            'reviewed_by': reviewer_id, 'status': rpt_status,
        }, user_id)
        st.success("✅ Report updated!")
        invalidate_progress_cache(selected_project_id)
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# DIALOGS — Quality Checklists
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("✅ New Quality Checklist", width="large")
def _dialog_create_qc():
    ms_df = get_milestones_df(selected_project_id)
    with st.form("create_qc_form"):
        c1, c2 = st.columns(2)
        qc_type = c1.selectbox("Type", QC_TYPES)
        qc_name = c2.text_input("Name *", placeholder="FAT — Conveyor Line 1")
        desc = st.text_area("Description", height=60)
        d1, d2, d3 = st.columns(3)
        insp_date = d1.date_input("Inspection Date", value=None)
        location = d2.text_input("Location")
        customer_witness = d3.text_input("Customer Witness")
        emp_opts = ["(Unassigned)"] + [e['full_name'] for e in employees]
        inspector = st.selectbox("Inspector", emp_opts)
        inspector_id = employees[emp_opts.index(inspector) - 1]['id'] if inspector != "(Unassigned)" else None
        ms_opts = ["(None)"]
        ms_ids = [None]
        if not ms_df.empty:
            for _, m in ms_df.iterrows():
                ms_opts.append(f"{m['milestone_name']} ({m['milestone_type']})")
                ms_ids.append(int(m['id']))
        ms_sel = st.selectbox("Linked Milestone", ms_opts)
        milestone_id = ms_ids[ms_opts.index(ms_sel)]
        st.markdown("**Results** (fill after inspection)")
        r1, r2, r3 = st.columns(3)
        total = r1.number_input("Total Items", min_value=0, value=0)
        passed = r2.number_input("Passed", min_value=0, value=0)
        failed = r3.number_input("Failed", min_value=0, value=0)
        col_s, col_c = st.columns(2)
        submitted = col_s.form_submit_button("💾 Create", type="primary", width="stretch")
        cancelled = col_c.form_submit_button("✖ Cancel", width="stretch")

    if cancelled:
        st.rerun()
    if submitted:
        if not qc_name.strip():
            st.error("Name is required.")
            return
        pass_rate = (passed / total * 100) if total > 0 else None
        create_quality_checklist({
            'project_id': selected_project_id, 'milestone_id': milestone_id,
            'checklist_type': qc_type, 'checklist_name': qc_name.strip(),
            'description': desc.strip() or None,
            'inspection_date': insp_date, 'location': location.strip() or None,
            'inspector_id': inspector_id, 'customer_witness': customer_witness.strip() or None,
            'status': 'PLANNED',
            'total_items': total or None, 'passed_items': passed or None,
            'failed_items': failed or None, 'pass_rate': pass_rate,
            'remarks': None, 'next_action': None, 'retest_date': None,
        }, user_id)
        st.success("✅ Quality checklist created!")
        invalidate_progress_cache(selected_project_id)
        st.rerun()


@st.dialog("✅ Quality Checklist", width="large")
def _dialog_view_qc(qc_id: int):
    qc = get_quality_checklist(qc_id)
    if not qc:
        st.warning("Checklist not found.")
        return
    hc1, hc2 = st.columns([5, 1])
    hc1.subheader(f"{QC_STATUS_ICONS.get(qc['status'], '⚪')} {qc['checklist_name']}")
    is_inspector = qc.get('inspector_id') == employee_id
    if perms.get('can_edit_any_task') or is_inspector:
        if hc2.button("✏️ Edit", type="primary"):
            st.session_state["open_edit_qc"] = qc_id
            st.rerun()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Type", qc['checklist_type'])
    k2.metric("Status", qc['status'])
    k3.metric("Pass Rate", f"{qc['pass_rate']:.0f}%" if qc.get('pass_rate') else '—')
    k4.metric("Customer", "✅ Signed" if qc.get('customer_signed_off') else "⚪ Pending")
    st.markdown(f"**Inspector:** {qc.get('inspector_name', '—')} · **Date:** {qc.get('inspection_date', '—')} · **Location:** {qc.get('location', '—')}")
    st.markdown(f"**Customer Witness:** {qc.get('customer_witness', '—')}")
    st.markdown(f"**Milestone:** {qc.get('milestone_name', '—')}")
    if qc.get('total_items'):
        r1, r2, r3 = st.columns(3)
        r1.metric("Total Items", qc['total_items'])
        r2.metric("Passed", qc.get('passed_items') or 0)
        r3.metric("Failed", qc.get('failed_items') or 0)
    if qc.get('description'):
        st.markdown(f"**Description:**\n{qc['description']}")
    if qc.get('remarks'):
        st.info(f"**Remarks:** {qc['remarks']}")
    if qc.get('next_action'):
        st.warning(f"**Next Action:** {qc['next_action']}")
    if qc.get('signed_off_by_name'):
        st.success(f"**Signed off by:** {qc['signed_off_by_name']} on {qc.get('signed_off_date', '—')}")
    render_attachments('quality_checklist', qc_id, selected_project_id, user_id)


@st.dialog("✏️ Edit Quality Checklist", width="large")
def _dialog_edit_qc(qc_id: int):
    qc = get_quality_checklist(qc_id) or {}
    ms_df = get_milestones_df(selected_project_id)
    with st.form("edit_qc_form"):
        c1, c2 = st.columns(2)
        qc_type = c1.selectbox("Type", QC_TYPES,
                               index=QC_TYPES.index(qc['checklist_type']) if qc.get('checklist_type') in QC_TYPES else 0)
        qc_name = c2.text_input("Name *", value=qc.get('checklist_name', ''))
        status = st.selectbox("Status", QC_STATUSES,
                              index=QC_STATUSES.index(qc['status']) if qc.get('status') in QC_STATUSES else 0)
        desc = st.text_area("Description", value=qc.get('description') or '', height=60)
        d1, d2, d3 = st.columns(3)
        insp_date = d1.date_input("Inspection Date", value=qc.get('inspection_date'))
        location = d2.text_input("Location", value=qc.get('location') or '')
        customer_witness = d3.text_input("Customer Witness", value=qc.get('customer_witness') or '')
        emp_opts = ["(Unassigned)"] + [e['full_name'] for e in employees]
        ins_idx = next((i + 1 for i, e in enumerate(employees) if e['id'] == qc.get('inspector_id')), 0)
        inspector = st.selectbox("Inspector", emp_opts, index=ins_idx)
        inspector_id = employees[emp_opts.index(inspector) - 1]['id'] if inspector != "(Unassigned)" else None
        st.markdown("**Results**")
        r1, r2, r3 = st.columns(3)
        total = r1.number_input("Total Items", min_value=0, value=int(qc.get('total_items') or 0))
        passed = r2.number_input("Passed", min_value=0, value=int(qc.get('passed_items') or 0))
        failed = r3.number_input("Failed", min_value=0, value=int(qc.get('failed_items') or 0))
        remarks = st.text_area("Remarks", value=qc.get('remarks') or '', height=60)
        next_action = st.text_area("Next Action", value=qc.get('next_action') or '', height=60)
        retest = st.date_input("Retest Date", value=qc.get('retest_date'))
        st.markdown("**Sign-off**")
        so1, so2 = st.columns(2)
        so_idx = next((i + 1 for i, e in enumerate(employees) if e['id'] == qc.get('signed_off_by')), 0)
        signoff = so1.selectbox("Signed Off By", emp_opts, index=so_idx)
        signoff_id = employees[emp_opts.index(signoff) - 1]['id'] if signoff != "(Unassigned)" else None
        cust_signed = so2.checkbox("Customer Signed Off", value=bool(qc.get('customer_signed_off')))
        col_s, col_c = st.columns(2)
        submitted = col_s.form_submit_button("💾 Save", type="primary", width="stretch")
        cancelled = col_c.form_submit_button("✖ Cancel", width="stretch")

    if cancelled:
        st.rerun()
    if submitted:
        if not qc_name.strip():
            st.error("Name is required.")
            return
        pass_rate = (passed / total * 100) if total > 0 else None
        update_quality_checklist(qc_id, {
            'checklist_type': qc_type, 'checklist_name': qc_name.strip(),
            'description': desc.strip() or None, 'status': status,
            'inspection_date': insp_date, 'location': location.strip() or None,
            'inspector_id': inspector_id, 'customer_witness': customer_witness.strip() or None,
            'total_items': total or None, 'passed_items': passed or None,
            'failed_items': failed or None, 'pass_rate': pass_rate,
            'remarks': remarks.strip() or None, 'next_action': next_action.strip() or None,
            'retest_date': retest,
            'signed_off_by': signoff_id,
            'signed_off_date': date.today() if signoff_id else None,
            'customer_signed_off': 1 if cust_signed else 0,
        }, user_id)
        st.success("✅ Quality checklist updated!")
        invalidate_progress_cache(selected_project_id)
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# DIALOG — User Guide
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("❓ Progress & Quality Guide", width="large")
def _dialog_progress_guide():
    lang_col, search_col = st.columns([1, 4])
    with lang_col:
        lang_opts = {"🇻🇳 Tiếng Việt": "vi", "🇬🇧 English": "en"}
        lang_label = st.radio("Lang", list(lang_opts.keys()), index=0,
                              key="_pg_lang", horizontal=True, label_visibility="collapsed")
        lang = lang_opts[lang_label]
    with search_col:
        ph = "Tìm: report, quality, RAG, inspection..." if lang == 'vi' else "Search: report, quality, RAG, inspection..."
        search_q = st.text_input("🔍", placeholder=ph, key="_pg_search", label_visibility="collapsed")

    prog_kpis = {'qc_failed': qc_failed, 'upcoming_insp': upcoming_insp,
                 'rpt_draft': rpt_draft, 'qc_no_sign': len(qc_df[(qc_df['status'] == 'PASSED') & (qc_df['customer_signed_off'] == 0)]) if not qc_df.empty and 'customer_signed_off' in qc_df.columns else 0}
    ctx_tips = get_progress_context_tips(prog_kpis, perms, lang=lang)
    for tip in ctx_tips:
        st.info(tip)
    if ctx_tips:
        st.divider()

    sections  = get_progress_guide_sections(perms['tier'], lang=lang)
    faq_items = get_progress_faq(perms['tier'], lang=lang)
    workflows = get_progress_workflows(perms['tier'], lang=lang)

    if search_q and len(search_q) >= 2:
        result = search_guide(search_q, sections, faq_items)
        sections = result['sections']
        faq_items = result['faq']
        q_lower = search_q.lower()
        workflows = [w for w in workflows if q_lower in w['title'].lower()
                     or any(q_lower in s.lower() for s in w.get('steps', []))
                     or any(q_lower in t for t in w.get('tags', []))]
        if not sections and not faq_items and not workflows:
            st.warning(f"Không tìm thấy '{search_q}'." if lang == 'vi' else f"No results for '{search_q}'.")
            return

    lbl_g = "📖 Hướng dẫn" if lang == 'vi' else "📖 Guide"
    lbl_w = "🔄 Quy trình"  if lang == 'vi' else "🔄 Workflows"
    lbl_f = "❓ Hỏi đáp"    if lang == 'vi' else "❓ FAQ"
    tab_labels = [lbl_g]
    if workflows: tab_labels.append(lbl_w)
    if faq_items: tab_labels.append(lbl_f)
    guide_tabs = st.tabs(tab_labels)

    with guide_tabs[0]:
        for s in sections:
            with st.expander(f"{s['icon']} {s['title']}", expanded=bool(search_q)):
                st.markdown(s['content'])

    if workflows and lbl_w in tab_labels:
        with guide_tabs[tab_labels.index(lbl_w)]:
            for wf in workflows:
                with st.expander(f"{wf['icon']} {wf['title']}", expanded=bool(search_q)):
                    sn = 0
                    for step in wf['steps']:
                        if step.startswith("  "):
                            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;{step.strip()}")
                        else:
                            sn += 1
                            st.markdown(f"**{sn}.** {step}")

    if faq_items and lbl_f in tab_labels:
        with guide_tabs[tab_labels.index(lbl_f)]:
            for item in faq_items:
                with st.expander(f"❓ {item['q']}", expanded=bool(search_q)):
                    st.markdown(item['a'])


# ══════════════════════════════════════════════════════════════════════════════
# DIALOG TRIGGERS — Permission-checked
# ══════════════════════════════════════════════════════════════════════════════

if st.session_state.pop("open_create_report", False) and can_create_report:
    _dialog_create_report()
if "open_view_report" in st.session_state:
    _dialog_view_report(st.session_state.pop("open_view_report"))
if "open_edit_report" in st.session_state:
    _dialog_edit_report(st.session_state.pop("open_edit_report"))

if st.session_state.pop("open_create_qc", False) and can_create_qc:
    _dialog_create_qc()
if "open_view_qc" in st.session_state:
    _dialog_view_qc(st.session_state.pop("open_view_qc"))
if "open_edit_qc" in st.session_state:
    _dialog_edit_qc(st.session_state.pop("open_edit_qc"))

if st.session_state.pop("open_progress_guide", False):
    _dialog_progress_guide()