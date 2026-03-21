# pages/IL_8_⚠️_Issues.py
"""
Issues & Risks — Track project issues, risk register, change orders.

v2.0 — Performance optimization:
  - Bootstrap: 4 cached queries replace individual per-tab queries
  - Targeted cache invalidation: invalidate_execution_cache()
  - Shared render_attachments() from wbs_helpers (DRY)

UX: @st.dialog cho CRUD | tabs cho Issues / Risks / Change Orders
"""

import streamlit as st
import pandas as pd
from datetime import date
import logging

from utils.auth import AuthManager
from utils.il_project import (
    get_projects_df, get_project, get_employees, get_currencies,
    fmt_vnd, STATUS_COLORS, get_milestones_df,
)
from utils.il_project.wbs_queries import get_tasks_df
from utils.il_project.wbs_execution_queries import (
    # Bootstrap
    bootstrap_execution_data,
    # Issues
    get_issues_df, get_issue, generate_issue_code,
    create_issue, update_issue, soft_delete_issue,
    # Risks
    get_risks_df, get_risk, generate_risk_code,
    create_risk, update_risk, soft_delete_risk, get_risk_matrix_summary,
    PROBABILITY_VALUES, IMPACT_VALUES,
    # Change Orders
    get_change_orders_df, get_change_order, generate_co_number,
    create_change_order, update_change_order, get_co_impact_summary,
    # Attachments
    get_entity_medias, upload_and_attach, unlink_media, get_attachment_url,
)
from utils.il_project.wbs_helpers import (
    invalidate_execution_cache, render_attachments,
)

logger = logging.getLogger(__name__)
auth = AuthManager()

st.set_page_config(page_title="Issues & Risks", page_icon="⚠️", layout="wide")
auth.require_auth()
user_id     = str(auth.get_user_id())
employee_id = st.session_state.get('employee_id')
is_admin    = auth.is_admin()

# ── Cached lookups ────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load_lookups():
    return get_employees(), get_currencies()

employees, currencies = _load_lookups()
emp_map = {e['id']: e['full_name'] for e in employees}
cur_map = {c['id']: c['code'] for c in currencies}

# ── Bootstrap cache ───────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def _cached_exec_data(project_id: int, _v: int = 0):
    return bootstrap_execution_data(project_id)

def _get_exec(project_id: int) -> dict:
    v = st.session_state.get(f'_exec_v_{project_id}', 0)
    return _cached_exec_data(project_id, _v=v)

ISSUE_CATEGORIES = ['TECHNICAL', 'COMMERCIAL', 'LOGISTICS', 'RESOURCE', 'CUSTOMER', 'VENDOR', 'OTHER']
ISSUE_SEVERITIES = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
ISSUE_STATUSES = ['OPEN', 'IN_PROGRESS', 'RESOLVED', 'CLOSED', 'ESCALATED']
SEVERITY_ICONS = {'LOW': '🟢', 'MEDIUM': '🟡', 'HIGH': '🟠', 'CRITICAL': '🔴'}

RISK_CATEGORIES = ['TECHNICAL', 'SCHEDULE', 'COST', 'RESOURCE', 'SUPPLY_CHAIN', 'REGULATORY', 'OTHER']
RISK_PROBABILITIES = ['RARE', 'UNLIKELY', 'POSSIBLE', 'LIKELY', 'ALMOST_CERTAIN']
RISK_IMPACTS = ['NEGLIGIBLE', 'MINOR', 'MODERATE', 'MAJOR', 'SEVERE']
RISK_STATUSES = ['IDENTIFIED', 'MITIGATING', 'ACCEPTED', 'CLOSED', 'OCCURRED']

CO_TYPES = ['SCOPE', 'SCHEDULE', 'COST', 'SCOPE_AND_COST', 'OTHER']
CO_STATUSES = ['DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED', 'CANCELLED']

# ── Sidebar ───────────────────────────────────────────────────────────────────
st.title("⚠️ Issues & Risks")

with st.sidebar:
    st.header("Project")
    proj_df = get_projects_df(status=None)
    if proj_df.empty:
        st.warning("No projects found.")
        st.stop()
    proj_opts = proj_df.apply(lambda r: f"{r['project_code']} — {r['project_name']}", axis=1).tolist()
    proj_idx = st.selectbox("Select Project", range(len(proj_opts)),
                            format_func=lambda i: proj_opts[i], key="ir_proj")
    selected_project_id = int(proj_df.iloc[proj_idx]['project_id'])
    proj_info = get_project(selected_project_id)

# ── Load bootstrap data (4 queries, cached) ──
exec_data = _get_exec(selected_project_id)
if not exec_data['ok']:
    st.error(f"⚠️ {exec_data['error']}")
    st.stop()

if proj_info:
    c1, c2, c3 = st.columns(3)
    c1.metric("Project", proj_info['project_code'])
    c2.metric("Status", proj_info['status'])
    c3.metric("PM", proj_info.get('pm_name', '—'))
    st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════

tab_issues, tab_risks, tab_co = st.tabs(["🔧 Issues", "⚠️ Risks", "📝 Change Orders"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: ISSUES (from bootstrap cache)
# ══════════════════════════════════════════════════════════════════════════════

with tab_issues:
    iss_df = exec_data['issues']

    ia1, _ = st.columns([1, 6])
    if ia1.button("➕ Report Issue", type="primary", key="btn_iss"):
        st.session_state["open_create_issue"] = True

    if not iss_df.empty:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total", len(iss_df))
        k2.metric("Open", len(iss_df[iss_df['status'] == 'OPEN']))
        k3.metric("Critical", len(iss_df[iss_df['severity'] == 'CRITICAL']))
        k4.metric("Resolved", len(iss_df[iss_df['status'].isin(['RESOLVED', 'CLOSED'])]))

        display = iss_df.copy()
        display['sev_icon'] = display['severity'].map(lambda s: SEVERITY_ICONS.get(s, '⚪'))

        event = st.dataframe(
            display, key="iss_tbl", width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            column_config={
                'sev_icon':          st.column_config.TextColumn('!', width=30),
                'issue_code':        st.column_config.TextColumn('Code', width=80),
                'title':             st.column_config.TextColumn('Title'),
                'category':          st.column_config.TextColumn('Category', width=100),
                'severity':          st.column_config.TextColumn('Severity', width=80),
                'status':            st.column_config.TextColumn('Status', width=100),
                'assigned_to_name':  st.column_config.TextColumn('Assigned To'),
                'due_date':          st.column_config.DateColumn('Due'),
                'file_count': st.column_config.NumberColumn('📎', width=40),
                'id': None, 'reported_by_name': None, 'reported_date': None,
                'resolved_date': None, 'impact_description': None,
                'related_task_id': None, 'related_task_name': None,
            },
        )
        sel = event.selection.rows
        if sel:
            sel_iss_id = int(display.iloc[sel[0]]['id'])
            ab1, ab2, ab3, _ = st.columns([1, 1, 1, 4])
            if ab1.button("👁️ View", type="primary", key="iss_view"):
                st.session_state["open_view_issue"] = sel_iss_id
                st.rerun()
            if ab2.button("✏️ Edit", key="iss_edit"):
                st.session_state["open_edit_issue"] = sel_iss_id
                st.rerun()
            if ab3.button("🗑 Delete", key="iss_del"):
                soft_delete_issue(sel_iss_id, user_id)
                invalidate_execution_cache(selected_project_id)
                st.rerun()
    else:
        st.info("No issues reported.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: RISKS (from bootstrap cache)
# ══════════════════════════════════════════════════════════════════════════════

with tab_risks:
    risk_df = exec_data['risks']

    ra1, _ = st.columns([1, 6])
    if ra1.button("➕ Add Risk", type="primary", key="btn_risk"):
        st.session_state["open_create_risk"] = True

    if not risk_df.empty:
        k1, k2, k3 = st.columns(3)
        k1.metric("Total Risks", len(risk_df))
        active = risk_df[~risk_df['status'].isin(['CLOSED'])]
        high_risks = active[active['risk_score'] >= 10] if 'risk_score' in active.columns else pd.DataFrame()
        k2.metric("High/Critical", len(high_risks))
        k3.metric("Occurred", len(risk_df[risk_df['status'] == 'OCCURRED']))

        def _score_color(score):
            if pd.isna(score) or score is None: return '⚪'
            s = int(score)
            if s >= 16: return '🔴'
            if s >= 10: return '🟠'
            if s >= 5:  return '🟡'
            return '🟢'

        display_r = risk_df.copy()
        display_r['score_icon'] = display_r['risk_score'].map(_score_color)

        event_r = st.dataframe(
            display_r, key="risk_tbl", width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            column_config={
                'score_icon':  st.column_config.TextColumn('!', width=30),
                'risk_code':   st.column_config.TextColumn('Code', width=80),
                'title':       st.column_config.TextColumn('Title'),
                'category':    st.column_config.TextColumn('Category', width=100),
                'probability': st.column_config.TextColumn('Prob.', width=90),
                'impact':      st.column_config.TextColumn('Impact', width=80),
                'risk_score':  st.column_config.NumberColumn('Score', width=60),
                'status':      st.column_config.TextColumn('Status', width=90),
                'owner_name':  st.column_config.TextColumn('Owner'),
                'review_date': st.column_config.DateColumn('Review'),
                'id': None, 'identified_date': None,
            },
        )
        sel_r = event_r.selection.rows
        if sel_r:
            sel_risk_id = int(display_r.iloc[sel_r[0]]['id'])
            rb1, rb2, rb3, _ = st.columns([1, 1, 1, 4])
            if rb1.button("👁️ View", type="primary", key="risk_view"):
                st.session_state["open_view_risk"] = sel_risk_id
                st.rerun()
            if rb2.button("✏️ Edit", key="risk_edit"):
                st.session_state["open_edit_risk"] = sel_risk_id
                st.rerun()
            if rb3.button("🗑 Delete", key="risk_del"):
                soft_delete_risk(sel_risk_id, user_id)
                invalidate_execution_cache(selected_project_id)
                st.rerun()
    else:
        st.info("No risks identified.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: CHANGE ORDERS (from bootstrap cache)
# ══════════════════════════════════════════════════════════════════════════════

with tab_co:
    co_df = exec_data['change_orders']
    co_summary = exec_data['co_summary']

    ca1, _ = st.columns([1, 6])
    if ca1.button("➕ New Change Order", type="primary", key="btn_co"):
        st.session_state["open_create_co"] = True

    if co_summary:
        k1, k2, k3 = st.columns(3)
        k1.metric("Approved Impact", fmt_vnd(co_summary.get('approved_impact')))
        k2.metric("Pending Impact", fmt_vnd(co_summary.get('pending_impact')))
        k3.metric("Schedule Impact", f"{co_summary.get('approved_days') or 0} days")

    if not co_df.empty:
        display_co = co_df.copy()
        display_co['impact_fmt'] = display_co['cost_impact'].apply(
            lambda v: f"+{v:,.0f}" if pd.notna(v) and v > 0 else (f"{v:,.0f}" if pd.notna(v) else '—')
        )
        display_co['cust'] = display_co['customer_approval'].map(lambda v: '✅' if v else '⚪')

        event_co = st.dataframe(
            display_co, key="co_tbl", width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            column_config={
                'co_number':         st.column_config.TextColumn('CO #', width=80),
                'title':             st.column_config.TextColumn('Title'),
                'change_type':       st.column_config.TextColumn('Type', width=100),
                'status':            st.column_config.TextColumn('Status', width=90),
                'impact_fmt':        st.column_config.TextColumn('Cost Impact', width=100),
                'currency_code':     st.column_config.TextColumn('CCY', width=50),
                'schedule_impact_days': st.column_config.NumberColumn('Days', width=60),
                'cust':              st.column_config.TextColumn('Cust.', width=50),
                'requested_date':    st.column_config.DateColumn('Requested'),
                'id': None, 'cost_impact': None, 'customer_approval': None,
                'requested_by_name': None, 'approved_by_name': None,
                'approved_date': None,
            },
        )
        sel_co = event_co.selection.rows
        if sel_co:
            sel_co_id = int(display_co.iloc[sel_co[0]]['id'])
            cb1, cb2, _ = st.columns([1, 1, 5])
            if cb1.button("👁️ View", type="primary", key="co_view"):
                st.session_state["open_view_co"] = sel_co_id
                st.rerun()
            if cb2.button("✏️ Edit", key="co_edit"):
                st.session_state["open_edit_co"] = sel_co_id
                st.rerun()
    else:
        st.info("No change orders.")


# ══════════════════════════════════════════════════════════════════════════════
# DIALOGS — Issues
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("🔧 Report Issue", width="large")
def _dialog_create_issue():
    with st.form("create_issue_form"):
        c1, c2, c3 = st.columns(3)
        title    = c1.text_input("Title *")
        category = c2.selectbox("Category", ISSUE_CATEGORIES)
        severity = c3.selectbox("Severity", ISSUE_SEVERITIES, index=1)
        desc     = st.text_area("Description", height=80)

        d1, d2 = st.columns(2)
        emp_opts = ["(Unassigned)"] + [e['full_name'] for e in employees]
        assigned = d1.selectbox("Assign To", emp_opts)
        assigned_id = employees[emp_opts.index(assigned) - 1]['id'] if assigned != "(Unassigned)" else None
        due = d2.date_input("Due Date", value=None)
        impact = st.text_input("Impact Description")

        task_df = get_tasks_df(selected_project_id)
        task_opts = ["(None)"] + [f"[{r['wbs_code']}] {r['task_name']}" for _, r in task_df.iterrows()] if not task_df.empty else ["(None)"]
        task_sel = st.selectbox("Related Task", task_opts)
        task_id = int(task_df.iloc[task_opts.index(task_sel) - 1]['id']) if task_sel != "(None)" else None

        col_s, col_c = st.columns(2)
        submitted = col_s.form_submit_button("💾 Create", type="primary", width="stretch")
        cancelled = col_c.form_submit_button("✖ Cancel", width="stretch")

    if cancelled:
        st.rerun()
    if submitted:
        if not title.strip():
            st.error("Title is required.")
            return
        new_id = create_issue({
            'project_id': selected_project_id,
            'issue_code': generate_issue_code(selected_project_id),
            'title': title.strip(), 'description': desc.strip() or None,
            'category': category, 'severity': severity, 'status': 'OPEN',
            'reported_by': employee_id, 'assigned_to': assigned_id,
            'reported_date': date.today(), 'due_date': due,
            'impact_description': impact.strip() or None,
            'related_task_id': task_id,
        }, user_id)
        st.success(f"✅ Issue created: ISS-{new_id}")
        invalidate_execution_cache(selected_project_id)
        st.rerun()


@st.dialog("🔧 Issue Details", width="large")
def _dialog_view_issue(issue_id: int):
    iss = get_issue(issue_id)
    if not iss:
        st.warning("Issue not found.")
        return
    hc1, hc2 = st.columns([5, 1])
    hc1.subheader(f"{SEVERITY_ICONS.get(iss['severity'], '⚪')} {iss.get('issue_code', '')} — {iss['title']}")
    if hc2.button("✏️ Edit", type="primary"):
        st.session_state["open_edit_issue"] = issue_id
        st.rerun()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Status", iss['status'])
    k2.metric("Severity", iss['severity'])
    k3.metric("Assigned", iss.get('assigned_to_name') or '—')
    k4.metric("Due", str(iss.get('due_date') or '—'))

    ic1, ic2 = st.columns(2)
    ic1.markdown(f"**Category:** {iss['category']}")
    ic1.markdown(f"**Reported by:** {iss.get('reported_by_name', '—')} on {iss.get('reported_date', '—')}")
    ic2.markdown(f"**Related Task:** {iss.get('related_task_name') or '—'}")
    if iss.get('impact_description'):
        ic2.markdown(f"**Impact:** {iss['impact_description']}")
    if iss.get('description'):
        st.markdown(f"**Description:**\n{iss['description']}")
    if iss.get('resolution'):
        st.success(f"**Resolution:** {iss['resolution']}")

    render_attachments('issue', issue_id, selected_project_id, user_id)


@st.dialog("✏️ Edit Issue", width="large")
def _dialog_edit_issue(issue_id: int):
    iss = get_issue(issue_id) or {}
    with st.form("edit_issue_form"):
        c1, c2, c3 = st.columns(3)
        title    = c1.text_input("Title *", value=iss.get('title', ''))
        category = c2.selectbox("Category", ISSUE_CATEGORIES,
                                index=ISSUE_CATEGORIES.index(iss['category']) if iss.get('category') in ISSUE_CATEGORIES else 0)
        severity = c3.selectbox("Severity", ISSUE_SEVERITIES,
                                index=ISSUE_SEVERITIES.index(iss['severity']) if iss.get('severity') in ISSUE_SEVERITIES else 1)
        status = st.selectbox("Status", ISSUE_STATUSES,
                              index=ISSUE_STATUSES.index(iss['status']) if iss.get('status') in ISSUE_STATUSES else 0)
        desc = st.text_area("Description", value=iss.get('description') or '', height=80)

        d1, d2 = st.columns(2)
        emp_opts = ["(Unassigned)"] + [e['full_name'] for e in employees]
        emp_idx = next((i + 1 for i, e in enumerate(employees) if e['id'] == iss.get('assigned_to')), 0)
        assigned = d1.selectbox("Assign To", emp_opts, index=emp_idx)
        assigned_id = employees[emp_opts.index(assigned) - 1]['id'] if assigned != "(Unassigned)" else None
        due = d2.date_input("Due Date", value=iss.get('due_date'))

        resolved_date = st.date_input("Resolved Date", value=iss.get('resolved_date'))
        resolution = st.text_area("Resolution", value=iss.get('resolution') or '', height=60)
        impact = st.text_input("Impact", value=iss.get('impact_description') or '')

        col_s, col_c = st.columns(2)
        submitted = col_s.form_submit_button("💾 Save", type="primary", width="stretch")
        cancelled = col_c.form_submit_button("✖ Cancel", width="stretch")

    if cancelled:
        st.rerun()
    if submitted:
        if not title.strip():
            st.error("Title is required.")
            return
        update_issue(issue_id, {
            'title': title.strip(), 'description': desc.strip() or None,
            'category': category, 'severity': severity, 'status': status,
            'assigned_to': assigned_id, 'due_date': due,
            'resolved_date': resolved_date if status in ('RESOLVED', 'CLOSED') else None,
            'resolution': resolution.strip() or None,
            'impact_description': impact.strip() or None,
            'related_task_id': iss.get('related_task_id'),
        }, user_id)
        st.success("✅ Issue updated!")
        invalidate_execution_cache(selected_project_id)
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# DIALOGS — Risks
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("⚠️ Add Risk", width="large")
def _dialog_create_risk():
    with st.form("create_risk_form"):
        title = st.text_input("Risk Title *")
        c1, c2, c3 = st.columns(3)
        category = c1.selectbox("Category", RISK_CATEGORIES)
        prob = c2.selectbox("Probability", RISK_PROBABILITIES, index=2)
        impact = c3.selectbox("Impact", RISK_IMPACTS, index=2)
        st.caption(f"Risk Score: **{PROBABILITY_VALUES[prob] * IMPACT_VALUES[impact]}** / 25")
        desc = st.text_area("Description", height=60)
        mitigation = st.text_area("Mitigation Plan", height=60)
        contingency = st.text_area("Contingency Plan", height=60)

        emp_opts = ["(Unassigned)"] + [e['full_name'] for e in employees]
        owner = st.selectbox("Risk Owner", emp_opts)
        owner_id = employees[emp_opts.index(owner) - 1]['id'] if owner != "(Unassigned)" else None
        review = st.date_input("Next Review Date", value=None)

        col_s, col_c = st.columns(2)
        submitted = col_s.form_submit_button("💾 Create", type="primary", width="stretch")
        cancelled = col_c.form_submit_button("✖ Cancel", width="stretch")

    if cancelled:
        st.rerun()
    if submitted:
        if not title.strip():
            st.error("Title is required.")
            return
        create_risk({
            'project_id': selected_project_id,
            'risk_code': generate_risk_code(selected_project_id),
            'title': title.strip(), 'description': desc.strip() or None,
            'category': category, 'probability': prob, 'impact': impact,
            'status': 'IDENTIFIED',
            'mitigation_plan': mitigation.strip() or None,
            'contingency_plan': contingency.strip() or None,
            'owner_id': owner_id, 'identified_date': date.today(), 'review_date': review,
        }, user_id)
        st.success("✅ Risk added!")
        invalidate_execution_cache(selected_project_id)
        st.rerun()


@st.dialog("⚠️ Risk Details", width="large")
def _dialog_view_risk(risk_id: int):
    r = get_risk(risk_id)
    if not r:
        st.warning("Risk not found.")
        return
    st.subheader(f"{r.get('risk_code', '')} — {r['title']}")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Score", f"{r.get('risk_score', '—')} / 25")
    k2.metric("Probability", r.get('probability', '—'))
    k3.metric("Impact", r.get('impact', '—'))
    k4.metric("Status", r.get('status', '—'))
    st.markdown(f"**Owner:** {r.get('owner_name', '—')} · **Category:** {r['category']}")
    if r.get('description'):
        st.markdown(f"**Description:**\n{r['description']}")
    if r.get('mitigation_plan'):
        st.info(f"**Mitigation:** {r['mitigation_plan']}")
    if r.get('contingency_plan'):
        st.warning(f"**Contingency:** {r['contingency_plan']}")

    render_attachments('risk', risk_id, selected_project_id, user_id)


@st.dialog("✏️ Edit Risk", width="large")
def _dialog_edit_risk(risk_id: int):
    r = get_risk(risk_id) or {}
    with st.form("edit_risk_form"):
        title = st.text_input("Title *", value=r.get('title', ''))
        c1, c2, c3 = st.columns(3)
        category = c1.selectbox("Category", RISK_CATEGORIES,
                                index=RISK_CATEGORIES.index(r['category']) if r.get('category') in RISK_CATEGORIES else 0)
        prob = c2.selectbox("Probability", RISK_PROBABILITIES,
                            index=RISK_PROBABILITIES.index(r['probability']) if r.get('probability') in RISK_PROBABILITIES else 2)
        impact = c3.selectbox("Impact", RISK_IMPACTS,
                              index=RISK_IMPACTS.index(r['impact']) if r.get('impact') in RISK_IMPACTS else 2)
        status = st.selectbox("Status", RISK_STATUSES,
                              index=RISK_STATUSES.index(r['status']) if r.get('status') in RISK_STATUSES else 0)
        desc = st.text_area("Description", value=r.get('description') or '', height=60)
        mitigation = st.text_area("Mitigation Plan", value=r.get('mitigation_plan') or '', height=60)
        contingency = st.text_area("Contingency Plan", value=r.get('contingency_plan') or '', height=60)
        emp_opts = ["(Unassigned)"] + [e['full_name'] for e in employees]
        emp_idx = next((i + 1 for i, e in enumerate(employees) if e['id'] == r.get('owner_id')), 0)
        owner = st.selectbox("Owner", emp_opts, index=emp_idx)
        owner_id = employees[emp_opts.index(owner) - 1]['id'] if owner != "(Unassigned)" else None
        review = st.date_input("Review Date", value=r.get('review_date'))

        col_s, col_c = st.columns(2)
        submitted = col_s.form_submit_button("💾 Save", type="primary", width="stretch")
        cancelled = col_c.form_submit_button("✖ Cancel", width="stretch")

    if cancelled:
        st.rerun()
    if submitted:
        update_risk(risk_id, {
            'title': title.strip(), 'description': desc.strip() or None,
            'category': category, 'probability': prob, 'impact': impact, 'status': status,
            'mitigation_plan': mitigation.strip() or None,
            'contingency_plan': contingency.strip() or None,
            'owner_id': owner_id, 'review_date': review,
        }, user_id)
        st.success("✅ Risk updated!")
        invalidate_execution_cache(selected_project_id)
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# DIALOGS — Change Orders
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("📝 New Change Order", width="large")
def _dialog_create_co():
    with st.form("create_co_form"):
        title = st.text_input("Title *")
        c1, c2 = st.columns(2)
        co_type = c1.selectbox("Change Type", CO_TYPES)
        cur_opts = [c['code'] for c in currencies]
        cur_sel = c2.selectbox("Currency", cur_opts)
        cur_id = currencies[cur_opts.index(cur_sel)]['id']

        desc = st.text_area("Description", height=60)
        reason = st.text_area("Reason for Change", height=60)

        v1, v2, v3 = st.columns(3)
        orig = v1.number_input("Original Value", value=float(proj_info.get('contract_value') or 0), format="%.0f")
        revised = v2.number_input("Revised Value", value=0.0, format="%.0f")
        days = v3.number_input("Schedule Impact (days)", value=0, help="+ = extend, - = accelerate")

        col_s, col_c = st.columns(2)
        submitted = col_s.form_submit_button("💾 Create", type="primary", width="stretch")
        cancelled = col_c.form_submit_button("✖ Cancel", width="stretch")

    if cancelled:
        st.rerun()
    if submitted:
        if not title.strip():
            st.error("Title is required.")
            return
        cost_impact = revised - orig if revised > 0 else None
        create_change_order({
            'project_id': selected_project_id,
            'co_number': generate_co_number(selected_project_id),
            'title': title.strip(), 'description': desc.strip() or None,
            'change_type': co_type, 'reason': reason.strip() or None,
            'original_value': orig or None, 'revised_value': revised or None,
            'cost_impact': cost_impact, 'currency_id': cur_id,
            'schedule_impact_days': days or None,
            'status': 'DRAFT', 'requested_by': employee_id,
            'requested_date': date.today(),
            'customer_approval_ref': None,
        }, user_id)
        st.success("✅ Change Order created!")
        invalidate_execution_cache(selected_project_id)
        st.rerun()


@st.dialog("📝 Change Order Details", width="large")
def _dialog_view_co(co_id: int):
    co = get_change_order(co_id)
    if not co:
        st.warning("Change Order not found.")
        return
    hc1, hc2 = st.columns([5, 1])
    hc1.subheader(f"{co.get('co_number', '')} — {co['title']}")
    if hc2.button("✏️ Edit", type="primary"):
        st.session_state["open_edit_co"] = co_id
        st.rerun()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Status", co['status'])
    k2.metric("Type", co['change_type'])
    k3.metric("Cost Impact", fmt_vnd(co.get('cost_impact')))
    k4.metric("Schedule", f"{co.get('schedule_impact_days') or 0} days")

    st.markdown(f"**Requested by:** {co.get('requested_by_name', '—')} on {co.get('requested_date', '—')}")
    if co.get('approved_by_name'):
        st.markdown(f"**Approved by:** {co['approved_by_name']} on {co.get('approved_date', '—')}")
    cust = "✅ Confirmed" if co.get('customer_approval') else "⚪ Pending"
    st.markdown(f"**Customer Approval:** {cust} {co.get('customer_approval_ref') or ''}")
    if co.get('description'):
        st.markdown(f"**Description:**\n{co['description']}")
    if co.get('reason'):
        st.info(f"**Reason:** {co['reason']}")

    render_attachments('change_order', co_id, selected_project_id, user_id)


@st.dialog("✏️ Edit Change Order", width="large")
def _dialog_edit_co(co_id: int):
    co = get_change_order(co_id) or {}
    with st.form("edit_co_form"):
        title = st.text_input("Title *", value=co.get('title', ''))
        c1, c2 = st.columns(2)
        co_type = c1.selectbox("Type", CO_TYPES,
                               index=CO_TYPES.index(co['change_type']) if co.get('change_type') in CO_TYPES else 0)
        status = c2.selectbox("Status", CO_STATUSES,
                              index=CO_STATUSES.index(co['status']) if co.get('status') in CO_STATUSES else 0)
        desc = st.text_area("Description", value=co.get('description') or '', height=60)
        reason = st.text_area("Reason", value=co.get('reason') or '', height=60)

        v1, v2, v3 = st.columns(3)
        orig = v1.number_input("Original", value=float(co.get('original_value') or 0), format="%.0f")
        revised = v2.number_input("Revised", value=float(co.get('revised_value') or 0), format="%.0f")
        days = v3.number_input("Days Impact", value=int(co.get('schedule_impact_days') or 0))

        a1, a2 = st.columns(2)
        emp_opts = ["(None)"] + [e['full_name'] for e in employees]
        apr_idx = next((i + 1 for i, e in enumerate(employees) if e['id'] == co.get('approved_by')), 0)
        approver = a1.selectbox("Approved By", emp_opts, index=apr_idx)
        approver_id = employees[emp_opts.index(approver) - 1]['id'] if approver != "(None)" else None
        cust_approval = a2.checkbox("Customer Approved", value=bool(co.get('customer_approval')))
        cust_ref = st.text_input("Customer Ref", value=co.get('customer_approval_ref') or '')

        col_s, col_c = st.columns(2)
        submitted = col_s.form_submit_button("💾 Save", type="primary", width="stretch")
        cancelled = col_c.form_submit_button("✖ Cancel", width="stretch")

    if cancelled:
        st.rerun()
    if submitted:
        cost_impact = revised - orig if revised > 0 else co.get('cost_impact')
        update_change_order(co_id, {
            'title': title.strip(), 'description': desc.strip() or None,
            'change_type': co_type, 'reason': reason.strip() or None,
            'original_value': orig or None, 'revised_value': revised or None,
            'cost_impact': cost_impact,
            'currency_id': co.get('currency_id'),
            'schedule_impact_days': days or None,
            'status': status,
            'approved_by': approver_id,
            'approved_date': date.today() if approver_id and status == 'APPROVED' else co.get('approved_date'),
            'customer_approval': 1 if cust_approval else 0,
            'customer_approval_ref': cust_ref.strip() or None,
        }, user_id)
        st.success("✅ Change Order updated!")
        invalidate_execution_cache(selected_project_id)
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# DIALOG TRIGGERS
# ══════════════════════════════════════════════════════════════════════════════

# Issues
if st.session_state.pop("open_create_issue", False):
    _dialog_create_issue()
if "open_view_issue" in st.session_state:
    _dialog_view_issue(st.session_state.pop("open_view_issue"))
if "open_edit_issue" in st.session_state:
    _dialog_edit_issue(st.session_state.pop("open_edit_issue"))

# Risks
if st.session_state.pop("open_create_risk", False):
    _dialog_create_risk()
if "open_view_risk" in st.session_state:
    _dialog_view_risk(st.session_state.pop("open_view_risk"))
if "open_edit_risk" in st.session_state:
    _dialog_edit_risk(st.session_state.pop("open_edit_risk"))

# Change Orders
if st.session_state.pop("open_create_co", False):
    _dialog_create_co()
if "open_view_co" in st.session_state:
    _dialog_view_co(st.session_state.pop("open_view_co"))
if "open_edit_co" in st.session_state:
    _dialog_edit_co(st.session_state.pop("open_edit_co"))