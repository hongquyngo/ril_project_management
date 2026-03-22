# pages/IL_8_⚠️_Issues.py
"""
Issues & Risks — Track project issues, risk register, change orders.

v3.0 — Role-based UX + Dashboard:
  Phase 1: Role resolution + access control + permission gating
  Phase 2: Cross-tab KPI banner + action items
  Phase 3: Issues: quick filters, aging, due indicator
  Phase 4: Risks: 5×5 heatmap + review-overdue
  Phase 5: COs: net impact summary, cost visibility gating
  Phase 6: User Guide (wbs_guide_8_issues.py)

  (v2.0 bootstrap cache preserved)
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
from utils.il_project.wbs_queries import (
    get_tasks_df, get_project_members_df,
)
from utils.il_project.wbs_execution_queries import (
    bootstrap_execution_data,
    get_issues_df, get_issue, generate_issue_code,
    create_issue, update_issue, soft_delete_issue,
    get_risks_df, get_risk, generate_risk_code,
    create_risk, update_risk, soft_delete_risk, get_risk_matrix_summary,
    PROBABILITY_VALUES, IMPACT_VALUES,
    get_change_orders_df, get_change_order, generate_co_number,
    create_change_order, update_change_order, get_co_impact_summary,
    get_entity_medias, upload_and_attach, unlink_media, get_attachment_url,
)
from utils.il_project.wbs_helpers import (
    MEMBER_ROLE_LABELS,
    invalidate_execution_cache, render_attachments, render_cc_selector,
    resolve_project_role,
    compute_exec_kpis, compute_exec_action_items,
)
from utils.il_project.wbs_notify import (
    notify_issue_created, notify_co_status_change,
)
from utils.il_project.wbs_guide_common import search_guide
from utils.il_project.wbs_guide_8_issues import (
    get_issues_guide_sections, get_issues_faq, get_issues_workflows,
    get_issues_context_tips,
)

logger = logging.getLogger(__name__)
auth = AuthManager()

st.set_page_config(page_title="Issues & Risks", page_icon="⚠️", layout="wide")
auth.require_auth()
user_id     = str(auth.get_user_id())
employee_id = st.session_state.get('employee_id')
is_admin    = auth.is_admin()

# ── Constants ────────────────────────────────────────────────────────────────
ISSUE_CATEGORIES = ['TECHNICAL', 'COMMERCIAL', 'LOGISTICS', 'RESOURCE', 'CUSTOMER', 'VENDOR', 'OTHER']
ISSUE_SEVERITIES = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
ISSUE_STATUSES   = ['OPEN', 'IN_PROGRESS', 'RESOLVED', 'CLOSED', 'ESCALATED']
SEVERITY_ICONS   = {'LOW': '🟢', 'MEDIUM': '🟡', 'HIGH': '🟠', 'CRITICAL': '🔴'}

RISK_CATEGORIES    = ['TECHNICAL', 'SCHEDULE', 'COST', 'RESOURCE', 'SUPPLY_CHAIN', 'REGULATORY', 'OTHER']
RISK_PROBABILITIES = ['RARE', 'UNLIKELY', 'POSSIBLE', 'LIKELY', 'ALMOST_CERTAIN']
RISK_IMPACTS       = ['NEGLIGIBLE', 'MINOR', 'MODERATE', 'MAJOR', 'SEVERE']
RISK_STATUSES      = ['IDENTIFIED', 'MITIGATING', 'ACCEPTED', 'CLOSED', 'OCCURRED']

CO_TYPES    = ['SCOPE', 'SCHEDULE', 'COST', 'SCOPE_AND_COST', 'OTHER']
CO_STATUSES = ['DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED', 'CANCELLED']


# ── Cached lookups ───────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load_lookups():
    return get_employees(), get_currencies()

employees, currencies = _load_lookups()
emp_map = {e['id']: e['full_name'] for e in employees}
cur_map = {c['id']: c['code'] for c in currencies}

@st.cache_data(ttl=60, show_spinner=False)
def _cached_exec_data(project_id: int, _v: int = 0):
    return bootstrap_execution_data(project_id)

def _get_exec(project_id: int) -> dict:
    v = st.session_state.get(f'_exec_v_{project_id}', 0)
    return _cached_exec_data(project_id, _v=v)

@st.cache_data(ttl=60, show_spinner=False)
def _cached_members(project_id: int, _v: int = 0):
    return get_project_members_df(project_id)


# ── Due date helper (reuse pattern from page 6) ─────────────────────────────
def _format_due(due_date, status) -> str:
    if not due_date or status in ('RESOLVED', 'CLOSED'):
        return str(due_date) if due_date else '—'
    try:
        d = pd.to_datetime(due_date).date() if not isinstance(due_date, date) else due_date
        diff = (d - date.today()).days
        if diff < 0:   return f"🔴 {-diff}d late"
        if diff == 0:  return "⚠️ Today"
        if diff <= 3:  return f"🟡 {diff}d left"
        if diff <= 7:  return f"📅 {diff}d"
        return str(d)
    except Exception:
        return str(due_date) if due_date else '—'


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

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

    st.divider()
    if st.button("❓ User Guide", use_container_width=True, key="sidebar_iss_guide"):
        st.session_state["open_issues_guide"] = True

# ── Load data ──
exec_data = _get_exec(selected_project_id)
if not exec_data['ok']:
    st.error(f"⚠️ {exec_data['error']}")
    st.stop()

v_mem = st.session_state.get(f'_wbs_v_{selected_project_id}', 0)
members_df = _cached_members(selected_project_id, _v=v_mem)


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1: ROLE RESOLUTION + ACCESS CONTROL
# ══════════════════════════════════════════════════════════════════════════════

perms = resolve_project_role(members_df, employee_id, is_admin)

if perms['tier'] == 'restricted' and not is_admin:
    st.warning("🔒 Issues & Risks is not available for your role.")
    st.info("Use the **📋 WBS** page to view and update your tasks.")
    st.page_link("pages/IL_6_📋_WBS.py", label="📋 Go to WBS", icon="📋")
    st.stop()

# Permission flags for this page
can_create_issue = perms['tier'] in ('manager', 'lead', 'member')
can_create_risk  = perms['tier'] in ('manager', 'lead')
can_create_co    = perms['tier'] == 'manager'
can_delete       = perms['tier'] == 'manager'
can_see_risks    = perms['tier'] in ('manager', 'lead')
can_see_co       = perms['tier'] in ('manager', 'lead')
can_see_co_cost  = perms['tier'] == 'manager'

_my_name = emp_map.get(employee_id, 'there')
_my_role_label = MEMBER_ROLE_LABELS.get(perms['role'], perms.get('role') or 'Guest')


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2: WELCOME BANNER + CROSS-TAB KPIs
# ══════════════════════════════════════════════════════════════════════════════

if proj_info:
    wc1, wc2 = st.columns([7, 1])
    wc1.markdown(f"Hi **{_my_name}** · `{_my_role_label}` on **{proj_info['project_code']}** — {proj_info['project_name']}")
    if wc2.button("❓", key="banner_iss_guide", help="Open User Guide"):
        st.session_state["open_issues_guide"] = True

kpis = compute_exec_kpis(exec_data['issues'], exec_data['risks'],
                          exec_data['change_orders'], exec_data['co_summary'])

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Open Issues", kpis['open_issues'],
          delta=None if kpis['critical_issues'] == 0 else f"{kpis['critical_issues']} critical",
          delta_color="inverse")
k2.metric("Overdue Issues", kpis['overdue_issues'],
          delta=None if kpis['overdue_issues'] == 0 else f"-{kpis['overdue_issues']}",
          delta_color="inverse")
k3.metric("High Risks", f"{kpis['high_risks']}/{kpis['total_risks']}")

if can_see_co_cost:
    k4.metric("Pending COs", f"{kpis['pending_co']}",
              delta=f"{fmt_vnd(kpis['pending_co_cost'])}" if kpis['pending_co_cost'] else None)
    k5.metric("Approved Impact", fmt_vnd(kpis['approved_co_cost']),
              delta=f"+{kpis['approved_co_days']}d" if kpis['approved_co_days'] else None)
else:
    k4.metric("Pending COs", kpis['pending_co'])
    k5.metric("Active Risks", kpis['total_risks'])

st.divider()

# ── Action Items (PM expander) ──
if perms['tier'] in ('manager', 'lead'):
    action_items = compute_exec_action_items(
        exec_data['issues'], exec_data['risks'], exec_data['change_orders'],
        employee_id, perms['tier'],
    )
    if action_items:
        with st.expander(f"🎯 Action Required ({len(action_items)})", expanded=len(action_items) <= 5):
            for item in action_items[:12]:
                st.markdown(f"{item['icon']} **{item['code']}** {item['title']} — {item['message']} · 👤 {item['assignee']}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN TABS — Dynamic based on role
# ══════════════════════════════════════════════════════════════════════════════

tab_labels = ["🔧 Issues"]
tab_keys   = ["issues"]

if can_see_risks:
    tab_labels.append("⚠️ Risks")
    tab_keys.append("risks")

if can_see_co:
    tab_labels.append("📝 Change Orders")
    tab_keys.append("co")

tabs_obj = st.tabs(tab_labels)
tab_map = dict(zip(tab_keys, tabs_obj))


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: ISSUES — Phase 3 Enhanced
# ══════════════════════════════════════════════════════════════════════════════

with tab_map['issues']:
    iss_df = exec_data['issues']

    # Action buttons
    ia1, _ = st.columns([1, 6])
    if can_create_issue:
        if ia1.button("➕ Report Issue", type="primary", key="btn_iss"):
            st.session_state["open_create_issue"] = True

    # Quick filter chips
    if not iss_df.empty:
        st.caption("Quick filters:")
        fc1, fc2, fc3, fc4, _ = st.columns([1, 1, 1, 1, 3])
        qf_overdue  = fc1.toggle("⏰ Overdue", value=False, key="iss_qf_overdue")
        qf_critical = fc2.toggle("🔴 Critical", value=False, key="iss_qf_crit")
        qf_mine     = fc3.toggle("🙋 Mine", value=False, key="iss_qf_mine")
        qf_open     = fc4.toggle("📋 Open only", value=False, key="iss_qf_open")

        # Apply filters
        filtered = iss_df.copy()
        today_d = date.today()
        if qf_open:
            filtered = filtered[~filtered['status'].isin(['RESOLVED', 'CLOSED'])]
        if qf_critical:
            filtered = filtered[filtered['severity'].isin(['CRITICAL', 'HIGH'])]
        if qf_mine and employee_id:
            filtered = filtered[
                (filtered.get('assigned_to') == employee_id) |
                (filtered.get('reported_by') == employee_id)
            ] if 'assigned_to' in filtered.columns else filtered
        if qf_overdue:
            has_due = filtered['due_date'].notna()
            not_done = ~filtered['status'].isin(['RESOLVED', 'CLOSED'])
            filtered = filtered[has_due & not_done & (pd.to_datetime(filtered['due_date']).dt.date < today_d)]

        # KPIs
        k1, k2, k3, k4 = st.columns(4)
        all_open = iss_df[~iss_df['status'].isin(['RESOLVED', 'CLOSED'])]
        k1.metric("Total", len(iss_df))
        k2.metric("Open", len(all_open))
        k3.metric("Critical", len(all_open[all_open['severity'] == 'CRITICAL']))
        k4.metric("Resolved", len(iss_df[iss_df['status'].isin(['RESOLVED', 'CLOSED'])]))

        if filtered.empty:
            st.info("No issues match current filters.")
        else:
            display = filtered.copy()
            display['sev_icon'] = display['severity'].map(lambda s: SEVERITY_ICONS.get(s, '⚪'))
            # Phase 3: aging + due indicator
            display['age'] = display['reported_date'].apply(
                lambda d: f"{(today_d - pd.to_datetime(d).date()).days}d" if pd.notna(d) else '—'
            )
            display['due_fmt'] = display.apply(
                lambda r: _format_due(r.get('due_date'), r.get('status')), axis=1
            )

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
                    'due_fmt':           st.column_config.TextColumn('Due', width=90),
                    'age':               st.column_config.TextColumn('Age', width=50),
                    'file_count':        st.column_config.NumberColumn('📎', width=40),
                    'id': None, 'reported_by_name': None, 'reported_date': None,
                    'due_date': None, 'resolved_date': None, 'impact_description': None,
                    'related_task_id': None, 'related_task_name': None,
                },
            )

            sel = event.selection.rows
            if sel:
                sel_iss = display.iloc[sel[0]]
                sel_iss_id = int(sel_iss['id'])
                is_own = (sel_iss.get('assigned_to') == employee_id or sel_iss.get('reported_by') == employee_id)

                ab1, ab2, ab3, _ = st.columns([1, 1, 1, 4])
                if ab1.button("👁️ View", type="primary", key="iss_view"):
                    st.session_state["open_view_issue"] = sel_iss_id
                    st.rerun()
                if perms['can_edit_any_task'] or is_own:
                    if ab2.button("✏️ Edit", key="iss_edit"):
                        st.session_state["open_edit_issue"] = sel_iss_id
                        st.rerun()
                if can_delete:
                    if ab3.button("🗑 Delete", key="iss_del"):
                        soft_delete_issue(sel_iss_id, user_id)
                        invalidate_execution_cache(selected_project_id)
                        st.rerun()
    else:
        st.info("No issues reported." + (" Click **➕ Report Issue** to create one." if can_create_issue else ""))


# ══════════════════════════════════════════════════════════════════════════════
# Risk Heatmap Renderer (must be defined before Risks tab calls it)
# ══════════════════════════════════════════════════════════════════════════════

def _render_risk_heatmap(risk_df):
    """Render 5×5 probability × impact heatmap from risk data."""
    active = risk_df[~risk_df['status'].isin(['CLOSED'])]
    if active.empty:
        st.caption("No active risks to display.")
        return

    prob_labels = list(reversed(RISK_PROBABILITIES))
    imp_labels = RISK_IMPACTS

    counts = {}
    for _, r in active.iterrows():
        key = (r.get('probability', ''), r.get('impact', ''))
        counts[key] = counts.get(key, 0) + 1

    def _cell_color(p, i):
        score = PROBABILITY_VALUES.get(p, 0) * IMPACT_VALUES.get(i, 0)
        if score >= 16: return "🔴"
        if score >= 10: return "🟠"
        if score >= 5:  return "🟡"
        return "🟢"

    header = st.columns([2] + [1] * 5)
    header[0].caption("")
    for j, imp in enumerate(imp_labels):
        header[j + 1].caption(f"**{imp[:3]}**")

    for prob in prob_labels:
        row = st.columns([2] + [1] * 5)
        row[0].caption(f"**{prob[:4]}**")
        for j, imp in enumerate(imp_labels):
            cnt = counts.get((prob, imp), 0)
            color = _cell_color(prob, imp)
            if cnt > 0:
                row[j + 1].markdown(f"{color} **{cnt}**")
            else:
                row[j + 1].markdown(f"<span style='color:#ccc'>·</span>", unsafe_allow_html=True)

    st.caption("↑ Probability × Impact → | 🟢 Low | 🟡 Medium | 🟠 High | 🔴 Critical")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: RISKS — Phase 4 Enhanced with Heatmap
# ══════════════════════════════════════════════════════════════════════════════

if 'risks' in tab_map:
    with tab_map['risks']:
        risk_df = exec_data['risks']

        ra1, _ = st.columns([1, 6])
        if can_create_risk:
            if ra1.button("➕ Add Risk", type="primary", key="btn_risk"):
                st.session_state["open_create_risk"] = True

        if not risk_df.empty:
            # KPIs
            rk1, rk2, rk3 = st.columns(3)
            active_r = risk_df[~risk_df['status'].isin(['CLOSED'])]
            high_r = active_r[active_r['risk_score'] >= 10] if 'risk_score' in active_r.columns else pd.DataFrame()
            rk1.metric("Active Risks", len(active_r))
            rk2.metric("High/Critical (≥10)", len(high_r))
            rk3.metric("Occurred", len(risk_df[risk_df['status'] == 'OCCURRED']))

            # Phase 4: Risk Heatmap
            st.markdown("#### 🔥 Risk Matrix")
            _render_risk_heatmap(risk_df)

            st.divider()

            # Table
            def _score_color(score):
                if pd.isna(score) or score is None: return '⚪'
                s = int(score)
                if s >= 16: return '🔴'
                if s >= 10: return '🟠'
                if s >= 5:  return '🟡'
                return '🟢'

            display_r = risk_df.copy()
            display_r['score_icon'] = display_r['risk_score'].map(_score_color)
            # Review overdue indicator
            display_r['review_fmt'] = display_r.apply(
                lambda r: _format_due(r.get('review_date'), r.get('status')), axis=1
            )

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
                    'review_fmt':  st.column_config.TextColumn('Review', width=90),
                    'id': None, 'identified_date': None, 'review_date': None,
                },
            )

            sel_r = event_r.selection.rows
            if sel_r:
                sel_risk_id = int(display_r.iloc[sel_r[0]]['id'])
                is_owner = display_r.iloc[sel_r[0]].get('owner_id') == employee_id
                rb1, rb2, rb3, _ = st.columns([1, 1, 1, 4])
                if rb1.button("👁️ View", type="primary", key="risk_view"):
                    st.session_state["open_view_risk"] = sel_risk_id
                    st.rerun()
                if perms['can_edit_any_task'] or is_owner:
                    if rb2.button("✏️ Edit", key="risk_edit"):
                        st.session_state["open_edit_risk"] = sel_risk_id
                        st.rerun()
                if can_delete:
                    if rb3.button("🗑 Delete", key="risk_del"):
                        soft_delete_risk(sel_risk_id, user_id)
                        invalidate_execution_cache(selected_project_id)
                        st.rerun()
        else:
            st.info("No risks identified." + (" Click **➕ Add Risk** to register one." if can_create_risk else ""))


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: CHANGE ORDERS — Phase 5 Enhanced
# ══════════════════════════════════════════════════════════════════════════════

if 'co' in tab_map:
    with tab_map['co']:
        co_df = exec_data['change_orders']
        co_summary = exec_data['co_summary']

        ca1, _ = st.columns([1, 6])
        if can_create_co:
            if ca1.button("➕ New Change Order", type="primary", key="btn_co"):
                st.session_state["open_create_co"] = True

        # Phase 5: Net Impact Summary (PM only)
        if can_see_co_cost and proj_info:
            original = float(proj_info.get('contract_value') or 0)
            approved_delta = float(co_summary.get('approved_impact') or 0)
            pending_delta = float(co_summary.get('pending_impact') or 0)
            approved_days = int(co_summary.get('approved_days') or 0)

            with st.container(border=True):
                nc1, nc2, nc3 = st.columns(3)
                nc1.metric("Original Contract", fmt_vnd(original))
                nc2.metric("Approved COs", fmt_vnd(approved_delta),
                           delta=f"+{approved_days}d schedule" if approved_days else None)
                nc3.metric("Revised Total", fmt_vnd(original + approved_delta))
                if pending_delta:
                    st.caption(f"⏳ Pending: {fmt_vnd(pending_delta)} across {kpis['pending_co']} CO(s)")

        elif co_summary:
            ck1, ck2, ck3 = st.columns(3)
            ck1.metric("Total COs", co_summary.get('total_cos', 0))
            ck2.metric("Pending", kpis['pending_co'])
            ck3.metric("Schedule Impact", f"+{co_summary.get('approved_days') or 0}d")

        if not co_df.empty:
            display_co = co_df.copy()
            if can_see_co_cost:
                display_co['impact_fmt'] = display_co['cost_impact'].apply(
                    lambda v: f"+{v:,.0f}" if pd.notna(v) and v > 0 else (f"{v:,.0f}" if pd.notna(v) else '—')
                )
            else:
                display_co['impact_fmt'] = '—'
            display_co['cust'] = display_co['customer_approval'].map(lambda v: '✅' if v else '⚪')

            co_col_config = {
                'co_number':      st.column_config.TextColumn('CO #', width=80),
                'title':          st.column_config.TextColumn('Title'),
                'change_type':    st.column_config.TextColumn('Type', width=100),
                'status':         st.column_config.TextColumn('Status', width=90),
                'cust':           st.column_config.TextColumn('Cust.', width=50),
                'requested_date': st.column_config.DateColumn('Requested'),
                'id': None, 'cost_impact': None, 'customer_approval': None,
                'requested_by_name': None, 'approved_by_name': None,
                'approved_date': None,
            }
            if can_see_co_cost:
                co_col_config['impact_fmt']        = st.column_config.TextColumn('Cost Impact', width=100)
                co_col_config['currency_code']      = st.column_config.TextColumn('CCY', width=50)
                co_col_config['schedule_impact_days'] = st.column_config.NumberColumn('Days', width=60)
            else:
                co_col_config['impact_fmt'] = None
                co_col_config['currency_code'] = None
                co_col_config['schedule_impact_days'] = None

            event_co = st.dataframe(
                display_co, key="co_tbl", width="stretch", hide_index=True,
                on_select="rerun", selection_mode="single-row",
                column_config=co_col_config,
            )

            sel_co = event_co.selection.rows
            if sel_co:
                sel_co_id = int(display_co.iloc[sel_co[0]]['id'])
                is_requester = display_co.iloc[sel_co[0]].get('requested_by') == employee_id
                cb1, cb2, _ = st.columns([1, 1, 5])
                if cb1.button("👁️ View", type="primary", key="co_view"):
                    st.session_state["open_view_co"] = sel_co_id
                    st.rerun()
                if can_create_co or is_requester:
                    if cb2.button("✏️ Edit", key="co_edit"):
                        st.session_state["open_edit_co"] = sel_co_id
                        st.rerun()
        else:
            st.info("No change orders." + (" Click **➕ New Change Order** to create one." if can_create_co else ""))


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

    cc_ids, cc_emails = render_cc_selector(employees, key_prefix="issue_create")

    if cancelled:
        st.rerun()
    if submitted:
        if not title.strip():
            st.error("Title is required.")
            return
        issue_code = generate_issue_code(selected_project_id)
        new_id = create_issue({
            'project_id': selected_project_id, 'issue_code': issue_code,
            'title': title.strip(), 'description': desc.strip() or None,
            'category': category, 'severity': severity, 'status': 'OPEN',
            'reported_by': employee_id, 'assigned_to': assigned_id,
            'reported_date': date.today(), 'due_date': due,
            'impact_description': impact.strip() or None, 'related_task_id': task_id,
        }, user_id)
        notify_issue_created(
            issue_id=new_id, issue_code=issue_code, title=title.strip(),
            project_id=selected_project_id, severity=severity, category=category,
            assigned_to_id=assigned_id, reporter_id=employee_id,
            performer_id=employee_id, description=desc.strip() or None,
            due_date=due,
            related_task_name=task_sel if task_sel != "(None)" else None,
            extra_cc_ids=cc_ids, extra_cc_emails=cc_emails,
        )
        st.success(f"✅ Issue created: {issue_code}")
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
    is_own = (iss.get('assigned_to') == employee_id or iss.get('reported_by') == employee_id)
    if perms['can_edit_any_task'] or is_own:
        if hc2.button("✏️ Edit", type="primary"):
            st.session_state["open_edit_issue"] = issue_id
            st.rerun()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Status", iss['status'])
    k2.metric("Severity", iss['severity'])
    k3.metric("Assigned", iss.get('assigned_to_name') or '—')
    k4.metric("Due", _format_due(iss.get('due_date'), iss.get('status')))

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
    st.markdown(f"**Review:** {_format_due(r.get('review_date'), r.get('status'))}")
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
            'requested_date': date.today(), 'customer_approval_ref': None,
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
    is_req = co.get('requested_by') == employee_id
    if can_create_co or is_req:
        if hc2.button("✏️ Edit", type="primary"):
            st.session_state["open_edit_co"] = co_id
            st.rerun()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Status", co['status'])
    k2.metric("Type", co['change_type'])
    if can_see_co_cost:
        k3.metric("Cost Impact", fmt_vnd(co.get('cost_impact')))
        k4.metric("Schedule", f"{co.get('schedule_impact_days') or 0} days")
    else:
        k3.metric("Schedule", f"{co.get('schedule_impact_days') or 0} days")

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

    cc_ids, cc_emails = render_cc_selector(employees, key_prefix="co_edit")

    if cancelled:
        st.rerun()
    if submitted:
        cost_impact = revised - orig if revised > 0 else co.get('cost_impact')
        old_co_status = co.get('status', '')
        update_change_order(co_id, {
            'title': title.strip(), 'description': desc.strip() or None,
            'change_type': co_type, 'reason': reason.strip() or None,
            'original_value': orig or None, 'revised_value': revised or None,
            'cost_impact': cost_impact, 'currency_id': co.get('currency_id'),
            'schedule_impact_days': days or None, 'status': status,
            'approved_by': approver_id,
            'approved_date': date.today() if approver_id and status == 'APPROVED' else co.get('approved_date'),
            'customer_approval': 1 if cust_approval else 0,
            'customer_approval_ref': cust_ref.strip() or None,
        }, user_id)
        if old_co_status != status:
            notify_co_status_change(
                co_id=co_id, co_number=co.get('co_number', ''), title=title.strip(),
                project_id=selected_project_id,
                old_status=old_co_status, new_status=status,
                requested_by_id=co.get('requested_by'), approved_by_id=approver_id,
                performer_id=employee_id,
                cost_impact=cost_impact, schedule_impact_days=days,
                extra_cc_ids=cc_ids, extra_cc_emails=cc_emails,
            )
        st.success("✅ Change Order updated!")
        invalidate_execution_cache(selected_project_id)
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# DIALOG — User Guide
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("❓ Issues & Risks Guide", width="large")
def _dialog_issues_guide():
    lang_col, search_col = st.columns([1, 4])
    with lang_col:
        lang_opts = {"🇻🇳 Tiếng Việt": "vi", "🇬🇧 English": "en"}
        lang_label = st.radio("Lang", list(lang_opts.keys()), index=0,
                              key="_ig_lang", horizontal=True, label_visibility="collapsed")
        lang = lang_opts[lang_label]
    with search_col:
        ph = "Tìm: issue, risk, change order, heatmap..." if lang == 'vi' else "Search: issue, risk, change order, heatmap..."
        search_q = st.text_input("🔍", placeholder=ph, key="_ig_search", label_visibility="collapsed")

    ctx_tips = get_issues_context_tips(kpis, perms, lang=lang)
    for tip in ctx_tips:
        st.info(tip)
    if ctx_tips:
        st.divider()

    sections  = get_issues_guide_sections(perms['tier'], lang=lang)
    faq_items = get_issues_faq(perms['tier'], lang=lang)
    workflows = get_issues_workflows(perms['tier'], lang=lang)

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

if st.session_state.pop("open_create_issue", False) and can_create_issue:
    _dialog_create_issue()
if "open_view_issue" in st.session_state:
    _dialog_view_issue(st.session_state.pop("open_view_issue"))
if "open_edit_issue" in st.session_state:
    _dialog_edit_issue(st.session_state.pop("open_edit_issue"))

if st.session_state.pop("open_create_risk", False) and can_create_risk:
    _dialog_create_risk()
if "open_view_risk" in st.session_state:
    _dialog_view_risk(st.session_state.pop("open_view_risk"))
if "open_edit_risk" in st.session_state:
    _dialog_edit_risk(st.session_state.pop("open_edit_risk"))

if st.session_state.pop("open_create_co", False) and can_create_co:
    _dialog_create_co()
if "open_view_co" in st.session_state:
    _dialog_view_co(st.session_state.pop("open_view_co"))
if "open_edit_co" in st.session_state:
    _dialog_edit_co(st.session_state.pop("open_edit_co"))

if st.session_state.pop("open_issues_guide", False):
    _dialog_issues_guide()