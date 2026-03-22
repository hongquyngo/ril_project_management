# pages/IL_6_📋_WBS.py
"""
WBS Management — Phases, Tasks, Checklists, Comments, Team.

v3.0 — Role-based UX + Dashboard:
  Phase 1: Role resolution from il_project_members → 5 tiers × 12 permissions
  Phase 2: Dashboard tab with KPIs, action items, phase progress
  Phase 3: Tasks tab with quick filters, overdue indicators, permission-gated actions

  (v2.0 performance features preserved: bootstrap cache, client-side filter, @st.fragment)
"""

import streamlit as st
import pandas as pd
import logging
from datetime import date, timedelta

from utils.auth import AuthManager
from utils.il_project import (
    get_projects_df, get_project, get_employees, fmt_vnd, STATUS_COLORS,
)
from utils.il_project.wbs_queries import (
    # Bootstrap
    bootstrap_wbs_data, filter_tasks_client,
    # Phases
    get_phases_df, get_phase, create_phase, update_phase, soft_delete_phase,
    # Tasks
    get_tasks_df, get_my_tasks_df, get_task,
    create_task, update_task, quick_update_task, soft_delete_task,
    generate_wbs_code,
    # Checklists
    get_checklists, create_checklist_item, toggle_checklist_item, delete_checklist_item,
    # Comments
    get_task_comments, create_comment,
    # Members (read-only)
    get_project_members_df,
    # Completion sync
    sync_completion_up,
)
from utils.il_project.wbs_execution_queries import (
    get_entity_medias, upload_and_attach, unlink_media, get_attachment_url,
)
from utils.il_project.wbs_helpers import (
    TASK_STATUS_OPTIONS, TASK_STATUS_ICONS, PHASE_STATUS_OPTIONS,
    PRIORITY_OPTIONS, PRIORITY_ICONS,
    DEPENDENCY_TYPES, DEPENDENCY_LABELS, DEFAULT_PHASE_TEMPLATES,
    MEMBER_ROLE_LABELS,
    fmt_status, fmt_priority, fmt_completion, fmt_hours, comment_type_icon,
    invalidate_wbs_cache, render_attachments,
    render_cc_selector,
    # v3.0 — Role + Dashboard
    resolve_project_role, can_edit_task, can_quick_update_task,
    compute_dashboard_kpis, compute_action_items,
)
from utils.il_project.wbs_notify import (
    notify_on_task_status_change,
    notify_on_task_assign,
)
from utils.il_project.wbs_user_guide import (
    get_guide_sections_for_role, get_faq_for_role, get_workflows_for_role,
    get_context_tips, search_guide,
)

logger = logging.getLogger(__name__)
auth = AuthManager()

st.set_page_config(page_title="WBS Management", page_icon="📋", layout="wide")
auth.require_auth()
user_id     = str(auth.get_user_id())
employee_id = st.session_state.get('employee_id')
user_role   = st.session_state.get('user_role', '')
is_admin    = auth.is_admin()


# ══════════════════════════════════════════════════════════════════════════════
# CACHED DATA LOADING — Bootstrap pattern (unchanged from v2.0)
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def _load_employees():
    return get_employees()

@st.cache_data(ttl=120)
def _load_projects():
    return get_projects_df(status=None)

@st.cache_data(ttl=60, show_spinner=False)
def _cached_wbs_data(project_id: int, _v: int = 0):
    return bootstrap_wbs_data(project_id)

def _get_wbs(project_id: int) -> dict:
    v = st.session_state.get(f'_wbs_v_{project_id}', 0)
    return _cached_wbs_data(project_id, _v=v)

@st.cache_data(ttl=60, show_spinner=False)
def _cached_my_tasks(employee_id: int, _v: int = 0):
    return get_my_tasks_df(employee_id)

def _get_my_tasks(emp_id: int) -> pd.DataFrame:
    v = st.session_state.get('_mytasks_v', 0)
    return _cached_my_tasks(emp_id, _v=v)

employees = _load_employees()
emp_map   = {e['id']: e['full_name'] for e in employees}


# ══════════════════════════════════════════════════════════════════════════════
# HELPER — Due date formatting (Phase 3)
# ══════════════════════════════════════════════════════════════════════════════

def _format_due_date(planned_end, status) -> str:
    """Format due date with overdue indicator."""
    if not planned_end or status in ('COMPLETED', 'CANCELLED'):
        return str(planned_end) if planned_end else '—'
    try:
        if hasattr(planned_end, 'date'):
            d = planned_end.date()
        elif isinstance(planned_end, date):
            d = planned_end
        else:
            d = pd.to_datetime(planned_end).date()

        today = date.today()
        diff = (d - today).days

        if diff < 0:
            return f"🔴 {-diff}d late"
        elif diff == 0:
            return "⚠️ Today"
        elif diff <= 3:
            return f"🟡 {diff}d left"
        elif diff <= 7:
            return f"📅 {diff}d"
        else:
            return str(d)
    except Exception:
        return str(planned_end) if planned_end else '—'


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — Project selector + filters + user guide
# ══════════════════════════════════════════════════════════════════════════════

st.title("📋 WBS Management")

with st.sidebar:
    st.header("Project")
    proj_df = _load_projects()
    if proj_df.empty:
        st.warning("No projects found.")
        st.stop()

    proj_options = proj_df.apply(
        lambda r: f"{r['project_code']} — {r['project_name']}", axis=1
    ).tolist()
    proj_idx = st.selectbox("Select Project", range(len(proj_options)),
                            format_func=lambda i: proj_options[i], key="wbs_proj_sel")
    selected_project_id = int(proj_df.iloc[proj_idx]['project_id'])
    proj_info = get_project(selected_project_id)

    st.divider()
    if st.button("❓ User Guide", use_container_width=True, key="sidebar_guide"):
        st.session_state["open_user_guide"] = True

    st.divider()
    st.header("Filters")
    f_phase  = st.selectbox("Phase", ["All"], key="wbs_f_phase")
    f_status = st.selectbox("Task Status", ["All"] + TASK_STATUS_OPTIONS)
    f_assignee = st.selectbox("Assignee", ["All", "🙋 Me"] +
                               [e['full_name'] for e in employees])

# Resolve filters
phase_filter_id = None
status_filter   = None if f_status == "All" else f_status
assignee_filter = None
if f_assignee == "🙋 Me":
    assignee_filter = employee_id
elif f_assignee not in ("All",):
    hit = next((e for e in employees if e['full_name'] == f_assignee), None)
    assignee_filter = hit['id'] if hit else None

# ── Load bootstrap data (3 queries, cached) ──
wbs = _get_wbs(selected_project_id)
if not wbs['ok']:
    st.error(f"⚠️ {wbs['error']}")
    st.stop()


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1: ROLE RESOLUTION — Determine permissions for current user
# ══════════════════════════════════════════════════════════════════════════════

perms = resolve_project_role(wbs['members'], employee_id, is_admin)

_my_name = emp_map.get(employee_id, 'there')
_my_role_label = MEMBER_ROLE_LABELS.get(perms['role'], perms.get('role') or 'Guest')


# ══════════════════════════════════════════════════════════════════════════════
# WELCOME BANNER + KPIs (role-aware)
# ══════════════════════════════════════════════════════════════════════════════

kpis = compute_dashboard_kpis(wbs['tasks'], wbs['phases'], proj_info or {})

_project_label = f"**{proj_info['project_code']}** — {proj_info['project_name']}" if proj_info else ""
_role_chip = f"`{_my_role_label}`" if perms['is_member'] else "`Guest`"

welcome_col, guide_col = st.columns([7, 1])
with welcome_col:
    st.markdown(f"Hi **{_my_name}** · {_role_chip} on {_project_label}")
with guide_col:
    if st.button("❓", key="banner_guide", help="Open User Guide"):
        st.session_state["open_user_guide"] = True
    if not perms['is_member'] and not is_admin:
        st.caption("🔒 Read-only")

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Overall", f"{kpis['overall_pct']:.0f}%")
k2.metric("Tasks Done", kpis['completion_rate'])
k3.metric("Overdue", kpis['overdue'],
          delta=None if kpis['overdue'] == 0 else f"-{kpis['overdue']}",
          delta_color="inverse")
k4.metric("Blocked", kpis['blocked'],
          delta=None if kpis['blocked'] == 0 else f"-{kpis['blocked']}",
          delta_color="inverse")
k5.metric("Due This Week", kpis['due_this_week'])
st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN TABS — Built dynamically based on role permissions
# ══════════════════════════════════════════════════════════════════════════════

tab_labels = []
tab_keys   = []

if perms.get('show_dashboard'):
    tab_labels.append("📊 Dashboard")
    tab_keys.append("dashboard")

tab_labels.append("🙋 My Tasks")
tab_keys.append("mytasks")

if perms.get('show_all_tasks_tab'):
    tab_labels.append("📋 All Tasks")
    tab_keys.append("tasks")

if perms.get('show_phases_tab'):
    tab_labels.append("🔷 Phases")
    tab_keys.append("phases")

if perms.get('show_team_tab'):
    tab_labels.append("👥 Team")
    tab_keys.append("team")

tabs_obj = st.tabs(tab_labels)
tab_map = dict(zip(tab_keys, tabs_obj))


# ══════════════════════════════════════════════════════════════════════════════
# TAB: DASHBOARD (📊) — Phase 2
# ══════════════════════════════════════════════════════════════════════════════

if 'dashboard' in tab_map:
    with tab_map['dashboard']:
        action_items = compute_action_items(wbs['tasks'], employee_id, perms['tier'])

        # ── Action Required Panel ──
        if action_items:
            st.subheader(f"🎯 Action Required ({len(action_items)})")
            for item in action_items[:15]:
                with st.container(border=True):
                    ic1, ic2, ic3 = st.columns([5, 2, 3])
                    ic1.markdown(
                        f"{item['icon']} **[{item['wbs_code']}]** {item['task_name']}"
                    )
                    ic2.caption(f"👤 {item['assignee']}")
                    ic3.caption(f"{item['message']}")

                    ba1, ba2, ba3, _ = st.columns([1, 1, 1, 4])
                    _tid = item['task_id']

                    if 'view' in item.get('actions', []):
                        if ba1.button("👁️", key=f"ai_v_{_tid}_{item['type']}", help="View task"):
                            st.session_state["open_view_task"] = _tid
                            st.rerun()

                    if 'quick_update' in item.get('actions', []):
                        if can_quick_update_task(perms, None, employee_id) or perms.get('can_quick_update_any'):
                            if ba2.button("⚡", key=f"ai_q_{_tid}_{item['type']}", help="Quick update"):
                                st.session_state["open_quick_task"] = _tid
                                st.rerun()

                    if 'edit' in item.get('actions', []):
                        if perms.get('can_edit_any_task') or perms['tier'] == 'lead':
                            if ba3.button("✏️", key=f"ai_e_{_tid}_{item['type']}", help="Edit task"):
                                st.session_state["open_edit_task"] = _tid
                                st.rerun()
        else:
            st.success("🎉 No action items — all tasks are on track!")

        st.divider()

        # ── Phase Progress Strip ──
        ph_df = wbs['phases']
        if not ph_df.empty:
            st.subheader("📊 Phase Progress")
            today_d = date.today()
            for _, ph in ph_df.iterrows():
                pc1, pc2, pc3 = st.columns([3, 4, 2])
                pct = float(ph['completion_percent'] or 0)
                task_info = f"{ph['tasks_done']:.0f}/{ph['task_count']:.0f} tasks"

                pc1.markdown(f"**{ph['sequence_no']}. {ph['phase_name']}**")
                pc2.progress(min(pct / 100, 1.0), text=f"{pct:.0f}% · {task_info}")

                # Count overdue in this phase
                n_overdue = 0
                if not wbs['tasks'].empty:
                    pt = wbs['tasks'][
                        (wbs['tasks']['phase_id'] == ph['id']) &
                        (~wbs['tasks']['status'].isin(['COMPLETED', 'CANCELLED'])) &
                        (wbs['tasks']['planned_end'].notna())
                    ]
                    if not pt.empty:
                        n_overdue = int((pd.to_datetime(pt['planned_end']).dt.date < today_d).sum())

                if n_overdue > 0:
                    pc3.caption(f"⏰ {n_overdue} overdue")
                else:
                    pc3.caption(fmt_status(ph['status']))

        # ── Quick Stats ──
        st.divider()
        qs1, qs2, qs3 = st.columns(3)
        if kpis['unassigned'] > 0 and perms['tier'] == 'manager':
            qs1.warning(f"❓ **{kpis['unassigned']}** unassigned tasks")
        if not wbs['members'].empty:
            active_mem = wbs['members']
            if 'is_active' in active_mem.columns:
                active_mem = active_mem[active_mem['is_active'] == 1]
            qs2.info(f"👥 **{len(active_mem)}** active team members")
        if not wbs['tasks'].empty:
            in_prog = int((wbs['tasks']['status'] == 'IN_PROGRESS').sum())
            qs3.info(f"🔵 **{in_prog}** tasks in progress")


# ══════════════════════════════════════════════════════════════════════════════
# TAB: MY TASKS (🙋) — Phase 4 Enhanced: action cards + grouped view + table
# ══════════════════════════════════════════════════════════════════════════════

if 'mytasks' in tab_map:
    with tab_map['mytasks']:
        if not employee_id:
            st.warning("Cannot determine your employee ID. Please contact admin.")
        else:
            my_df = _get_my_tasks(employee_id)

            # ── My Tasks KPIs ──
            my_total = len(my_df)
            my_in_progress = len(my_df[my_df['status'] == 'IN_PROGRESS']) if my_total else 0
            my_not_started = len(my_df[my_df['status'] == 'NOT_STARTED']) if my_total else 0
            my_blocked_n   = len(my_df[my_df['status'] == 'BLOCKED']) if my_total else 0

            mk1, mk2, mk3, mk4 = st.columns(4)
            mk1.metric("Active Tasks", my_total)
            mk2.metric("In Progress", my_in_progress)
            mk3.metric("Not Started", my_not_started)
            mk4.metric("Blocked", my_blocked_n,
                        delta=None if my_blocked_n == 0 else f"-{my_blocked_n}",
                        delta_color="inverse")

            if my_df.empty:
                st.success("🎉 No pending tasks assigned to you!")
            else:
                # ── Action Cards: urgent items at top ──
                my_actions = compute_action_items(wbs['tasks'], employee_id, 'member')
                if my_actions:
                    st.markdown(f"#### 🎯 Needs Your Attention ({len(my_actions)})")

                    # Group by severity
                    for sev_label, sev_key, sev_color in [
                        ("🔴 Critical", 'critical', 'red'),
                        ("🟠 High Priority", 'high', 'orange'),
                        ("🔵 Action Items", 'medium', 'blue'),
                    ]:
                        sev_items = [a for a in my_actions if a['severity'] == sev_key]
                        if not sev_items:
                            continue

                        st.caption(f"**{sev_label}** ({len(sev_items)})")

                        for item in sev_items:
                            _tid = item['task_id']
                            with st.container(border=True):
                                row1, row2 = st.columns([6, 2])
                                row1.markdown(
                                    f"{item['icon']} **[{item['wbs_code']}]** {item['task_name']}"
                                )
                                row2.caption(item['message'])

                                # Inline actions
                                ba1, ba2, ba3, _ = st.columns([1, 1, 1, 4])
                                if ba1.button("⚡ Update", key=f"my_ai_q_{_tid}_{item['type']}",
                                              use_container_width=True, type="primary"):
                                    st.session_state["open_quick_task"] = _tid
                                    st.rerun()
                                if ba2.button("👁️ View", key=f"my_ai_v_{_tid}_{item['type']}",
                                              use_container_width=True):
                                    st.session_state["open_view_task"] = _tid
                                    st.rerun()
                                if ba3.button("💬 Comment", key=f"my_ai_c_{_tid}_{item['type']}",
                                              use_container_width=True):
                                    st.session_state["open_view_task"] = _tid
                                    st.rerun()

                    st.divider()

                # ── Priority-Grouped Table View ──
                st.markdown("#### 📋 All My Tasks")

                my_display = my_df.copy()
                my_display['prio'] = my_display['priority'].map(lambda p: PRIORITY_ICONS.get(p, '🔵'))
                my_display['status_icon'] = my_display['status'].map(lambda s: TASK_STATUS_ICONS.get(s, '⚪'))
                my_display['pct_fmt'] = my_display['completion_percent'].apply(fmt_completion)
                my_display['due_fmt'] = my_display.apply(
                    lambda r: _format_due_date(r.get('planned_end'), r.get('status')), axis=1
                )
                my_display['hours_fmt'] = my_display.apply(
                    lambda r: f"{fmt_hours(r.get('actual_hours'))}/{fmt_hours(r.get('estimated_hours'))}", axis=1
                )

                # View toggle: grouped cards vs flat table
                view_mode = st.radio(
                    "View", ["📊 Grouped", "📋 Table"],
                    horizontal=True, key="my_view_mode", label_visibility="collapsed"
                )

                if view_mode == "📊 Grouped":
                    # ── Priority-grouped card layout ──
                    prio_order = ['CRITICAL', 'HIGH', 'NORMAL', 'LOW']
                    prio_labels = {
                        'CRITICAL': '🔴 Critical',
                        'HIGH': '🟠 High',
                        'NORMAL': '🔵 Normal',
                        'LOW': '🟢 Low',
                    }

                    for prio in prio_order:
                        prio_tasks = my_display[my_display['priority'] == prio]
                        if prio_tasks.empty:
                            continue

                        st.markdown(f"**{prio_labels.get(prio, prio)}** ({len(prio_tasks)})")

                        for _, t in prio_tasks.iterrows():
                            _tid = int(t['id'])
                            with st.container(border=True):
                                tc1, tc2, tc3, tc4, tc5 = st.columns([4, 2, 2, 1, 1])

                                # Task info
                                tc1.markdown(
                                    f"{t['status_icon']} **[{t['wbs_code']}]** {t['task_name']}"
                                )
                                tc1.caption(f"📁 {t['project_code']} · {t.get('phase_name', '—')}")

                                # Progress
                                tc2.markdown(f"**{t['pct_fmt']}**")
                                tc2.caption(f"⏱️ {t['hours_fmt']}")

                                # Due date
                                tc3.markdown(f"**{t['due_fmt']}**")
                                tc3.caption(f"{t['status']}")

                                # Actions — one button per column
                                if tc4.button("⚡", key=f"myg_q_{_tid}", help="Quick Update", use_container_width=True):
                                    st.session_state["open_quick_task"] = _tid
                                    st.rerun()
                                if tc5.button("👁️", key=f"myg_v_{_tid}", help="View Details", use_container_width=True):
                                    st.session_state["open_view_task"] = _tid
                                    st.rerun()

                else:
                    # ── Flat table view (original) ──
                    event_my = st.dataframe(
                        my_display,
                        key="my_task_tbl", width="stretch", hide_index=True,
                        on_select="rerun", selection_mode="single-row",
                        column_config={
                            'prio':            st.column_config.TextColumn('!', width=30),
                            'status_icon':     st.column_config.TextColumn('', width=30),
                            'project_code':    st.column_config.TextColumn('Project', width=100),
                            'phase_name':      st.column_config.TextColumn('Phase'),
                            'wbs_code':        st.column_config.TextColumn('WBS', width=60),
                            'task_name':       st.column_config.TextColumn('Task'),
                            'status':          st.column_config.TextColumn('Status', width=100),
                            'pct_fmt':         st.column_config.TextColumn('%', width=70),
                            'due_fmt':         st.column_config.TextColumn('Due', width=100),
                            'hours_fmt':       st.column_config.TextColumn('Hours', width=80),
                            'id': None, 'priority': None, 'completion_percent': None,
                            'actual_start': None, 'estimated_hours': None,
                            'actual_hours': None, 'project_name': None,
                            'planned_end': None,
                        },
                    )
                    sel_my = event_my.selection.rows
                    if sel_my:
                        my_tid = int(my_display.iloc[sel_my[0]]['id'])
                        mc1, mc2, _ = st.columns([1, 1, 5])
                        if mc1.button("⚡ Quick Update", type="primary", key="my_quick"):
                            st.session_state["open_quick_task"] = my_tid
                            st.rerun()
                        if mc2.button("👁️ View", key="my_view"):
                            st.session_state["open_view_task"] = my_tid
                            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB: ALL TASKS (📋) — Phase 3 Enhanced
# ══════════════════════════════════════════════════════════════════════════════

if 'tasks' in tab_map:
    with tab_map['tasks']:
        # ── Action buttons (permission-gated) ──
        ta1, _ = st.columns([1, 6])
        if perms['can_create_tasks']:
            if ta1.button("➕ Add Task", type="primary", key="btn_add_task"):
                st.session_state["open_create_task"] = True

        # ── Phase 3: Quick Filter Chips ──
        st.caption("Quick filters:")
        fc1, fc2, fc3, fc4, fc5, _ = st.columns([1, 1, 1, 1, 1, 2])
        qf_overdue  = fc1.toggle("⏰ Overdue", value=False, key="qf_overdue")
        qf_blocked  = fc2.toggle("🔴 Blocked", value=False, key="qf_blocked")
        qf_mine     = fc3.toggle("🙋 Mine", value=False, key="qf_mine")
        qf_critical = fc4.toggle("🔴 Crit/High", value=False, key="qf_critical")
        qf_noassign = False
        if perms['tier'] in ('manager', 'lead'):
            qf_noassign = fc5.toggle("❓ No assignee", value=False, key="qf_noassign")

        # ── Apply sidebar + quick filters (~0ms) ──
        task_df = filter_tasks_client(
            wbs['tasks'],
            phase_id=phase_filter_id,
            assignee_id=assignee_filter,
            status=status_filter,
        )

        if not task_df.empty:
            today_d = date.today()
            mask = pd.Series(True, index=task_df.index)

            if qf_overdue:
                has_due = task_df['planned_end'].notna()
                not_done = ~task_df['status'].isin(['COMPLETED', 'CANCELLED'])
                mask &= has_due & not_done & (pd.to_datetime(task_df['planned_end']).dt.date < today_d)

            if qf_blocked:
                mask &= (task_df['status'] == 'BLOCKED')

            if qf_mine and employee_id:
                mask &= (task_df['assignee_id'] == employee_id)

            if qf_critical:
                mask &= task_df['priority'].isin(['CRITICAL', 'HIGH'])

            if qf_noassign:
                mask &= task_df['assignee_id'].isna()

            task_df = task_df[mask].reset_index(drop=True)

        if task_df.empty:
            st.info("No tasks match current filters.")
        else:
            display = task_df.copy()
            display['●'] = display['status'].map(lambda s: TASK_STATUS_ICONS.get(s, '⚪'))
            display['prio'] = display['priority'].map(lambda p: PRIORITY_ICONS.get(p, '🔵'))
            display['pct_fmt'] = display['completion_percent'].apply(fmt_completion)
            display['cl_fmt'] = display.apply(
                lambda r: f"{r['checklist_done']:.0f}/{r['checklist_total']:.0f}"
                if r['checklist_total'] > 0 else '—', axis=1
            )
            display['due_fmt'] = display.apply(
                lambda r: _format_due_date(r.get('planned_end'), r.get('status')), axis=1
            )

            event = st.dataframe(
                display,
                key=f"task_tbl_{st.session_state.get('_task_tbl_key', 0)}",
                width="stretch", hide_index=True,
                on_select="rerun", selection_mode="single-row",
                column_config={
                    '●':                st.column_config.TextColumn('', width=30),
                    'prio':             st.column_config.TextColumn('!', width=30),
                    'wbs_code':         st.column_config.TextColumn('WBS', width=60),
                    'task_name':        st.column_config.TextColumn('Task'),
                    'phase_name':       st.column_config.TextColumn('Phase'),
                    'assignee_name':    st.column_config.TextColumn('Assignee'),
                    'status':           st.column_config.TextColumn('Status', width=100),
                    'pct_fmt':          st.column_config.TextColumn('%', width=70),
                    'due_fmt':          st.column_config.TextColumn('Due', width=100),
                    'cl_fmt':           st.column_config.TextColumn('✓', width=50),
                    'comment_count':    st.column_config.NumberColumn('💬', width=40),
                    'id': None, 'project_id': None, 'phase_id': None,
                    'parent_task_id': None, 'description': None,
                    'assignee_id': None, 'priority': None,
                    'planned_start': None, 'planned_end': None,
                    'actual_start': None, 'actual_end': None,
                    'estimated_hours': None, 'actual_hours': None,
                    'completion_percent': None,
                    'dependency_task_id': None, 'dependency_type': None,
                    'phase_code': None, 'checklist_total': None, 'checklist_done': None,
                },
            )

            # ── Permission-gated action buttons ──
            sel = event.selection.rows
            if sel:
                selected_task_id = int(display.iloc[sel[0]]['id'])
                sel_assignee_id  = display.iloc[sel[0]].get('assignee_id')
                task_info = get_task(selected_task_id)

                if task_info:
                    st.markdown(
                        f"**Selected:** `{task_info.get('wbs_code', '')}` {task_info['task_name']} "
                        f"({TASK_STATUS_ICONS.get(task_info['status'], '⚪')} {task_info['status']})"
                    )
                    ab1, ab2, ab3, ab4, _ = st.columns([1, 1, 1, 1, 3])

                    if ab1.button("👁️ View", type="primary", use_container_width=True, key="task_view"):
                        st.session_state["open_view_task"] = selected_task_id
                        st.rerun()

                    if can_quick_update_task(perms, sel_assignee_id, employee_id):
                        if ab2.button("⚡ Quick Update", use_container_width=True, key="task_quick"):
                            st.session_state["open_quick_task"] = selected_task_id
                            st.rerun()

                    if can_edit_task(perms, sel_assignee_id, employee_id):
                        if ab3.button("✏️ Edit", use_container_width=True, key="task_edit"):
                            st.session_state["open_edit_task"] = selected_task_id
                            st.rerun()

                    if perms['can_delete']:
                        if ab4.button("🗑 Delete", use_container_width=True, key="task_del"):
                            if soft_delete_task(selected_task_id, user_id):
                                st.success("Task deleted.")
                                invalidate_wbs_cache(selected_project_id)
                                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB: PHASES (🔷) — Permission-gated CRUD
# ══════════════════════════════════════════════════════════════════════════════

if 'phases' in tab_map:
    with tab_map['phases']:
        ph_df = wbs['phases']

        if perms['can_manage_phases']:
            pa1, pa2, _ = st.columns([1, 1, 5])
            if pa1.button("➕ Add Phase", type="primary"):
                st.session_state["open_create_phase"] = True
            if pa2.button("📦 Load Template"):
                st.session_state["open_phase_template"] = True
        else:
            st.caption("📖 Phase overview (read-only for your role)")

        if ph_df.empty:
            msg = "No phases defined."
            if perms['can_manage_phases']:
                msg += " Add phases or load a template to get started."
            st.info(msg)
        else:
            for _, ph in ph_df.iterrows():
                with st.container(border=True):
                    pc1, pc2, pc3, pc4, pc5 = st.columns([3, 2, 2, 1, 1])
                    pc1.markdown(f"**{ph['sequence_no']}. {ph['phase_name']}** `{ph['phase_code']}`")
                    pc2.caption(f"{fmt_status(ph['status'])} · {ph['task_count']:.0f} tasks ({ph['tasks_done']:.0f} done)")
                    pc3.progress(float(ph['completion_percent'] or 0) / 100,
                                 text=f"{ph['completion_percent']:.0f}%")
                    if perms['can_manage_phases']:
                        if pc4.button("✏️", key=f"ph_edit_{ph['id']}", help="Edit phase"):
                            st.session_state["open_edit_phase"] = int(ph['id'])
                            st.rerun()
                        if pc5.button("🗑", key=f"ph_del_{ph['id']}", help="Delete phase"):
                            if soft_delete_phase(int(ph['id']), user_id):
                                st.success("Phase deleted.")
                                invalidate_wbs_cache(selected_project_id)
                                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB: TEAM (👥)
# ══════════════════════════════════════════════════════════════════════════════

if 'team' in tab_map:
    with tab_map['team']:
        mem_df = wbs['members']

        if mem_df.empty:
            st.info("No team members assigned yet.")
        else:
            active_df = mem_df[mem_df['is_active'] == 1] if 'is_active' in mem_df.columns else mem_df
            tm1, tm2, tm3 = st.columns(3)
            tm1.metric("Team Size", len(active_df))
            tm2.metric("Total Allocation",
                       f"{active_df['allocation_percent'].sum():.0f}%"
                       if 'allocation_percent' in active_df.columns else '—')
            tm3.metric("Roles", active_df['role'].nunique() if 'role' in active_df.columns else 0)

            st.dataframe(
                mem_df, width="stretch", hide_index=True,
                column_config={
                    'member_name':       st.column_config.TextColumn('Name'),
                    'email':             st.column_config.TextColumn('Email'),
                    'role':              st.column_config.TextColumn('Role'),
                    'allocation_percent': st.column_config.NumberColumn('Allocation %', format="%.0f%%"),
                    'daily_rate':        st.column_config.NumberColumn('Daily Rate', format="%.0f"),
                    'start_date':        st.column_config.DateColumn('Start'),
                    'end_date':          st.column_config.DateColumn('End'),
                    'is_active':         st.column_config.CheckboxColumn('Active'),
                    'id': None, 'employee_id': None, 'notes': None,
                },
            )

        label = "👥 Manage Team & Resources →" if perms['can_manage_team'] else "👥 View Team Details →"
        st.page_link("pages/7_👥_WBS_Team.py", label=label, icon="👥")


# ══════════════════════════════════════════════════════════════════════════════
# DIALOGS — Phase CRUD
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("➕ Add Phase", width="large")
def _dialog_create_phase():
    with st.form("create_phase_form"):
        c1, c2, c3 = st.columns(3)
        seq = c1.number_input("Sequence #", min_value=1, value=1)
        code = c2.text_input("Phase Code *", placeholder="DESIGN")
        name = c3.text_input("Phase Name *", placeholder="Design & Engineering")
        d1, d2, d3 = st.columns(3)
        p_start = d1.date_input("Planned Start", value=None)
        p_end   = d2.date_input("Planned End", value=None)
        weight  = d3.number_input("Weight %", min_value=0.0, max_value=100.0, value=0.0)
        status  = st.selectbox("Status", PHASE_STATUS_OPTIONS)
        notes   = st.text_area("Notes", height=70)
        col_s, col_c = st.columns(2)
        submitted = col_s.form_submit_button("💾 Create", type="primary", width="stretch")
        cancelled = col_c.form_submit_button("✖ Cancel", width="stretch")

    if cancelled:
        st.rerun()
    if submitted:
        if not code.strip() or not name.strip():
            st.error("Phase Code and Name are required.")
            return
        create_phase({
            'project_id': selected_project_id,
            'phase_code': code.strip().upper(),
            'phase_name': name.strip(),
            'sequence_no': seq,
            'planned_start': p_start, 'planned_end': p_end,
            'status': status, 'weight_percent': weight or None,
            'notes': notes.strip() or None,
        }, user_id)
        st.success("Phase created!")
        invalidate_wbs_cache(selected_project_id)
        st.rerun()


@st.dialog("📦 Load Phase Template", width="large")
def _dialog_phase_template():
    st.info("This will create standard phases for an IL project. Existing phases are NOT affected.")
    if st.button("✅ Load Template", type="primary"):
        for i, tmpl in enumerate(DEFAULT_PHASE_TEMPLATES, 1):
            create_phase({
                'project_id': selected_project_id,
                'phase_code': tmpl['code'],
                'phase_name': tmpl['name'],
                'sequence_no': i,
                'planned_start': None, 'planned_end': None,
                'status': 'NOT_STARTED',
                'weight_percent': tmpl['weight'],
                'notes': None,
            }, user_id)
        st.success(f"✅ {len(DEFAULT_PHASE_TEMPLATES)} phases created!")
        invalidate_wbs_cache(selected_project_id)
        st.rerun()
    if st.button("✖ Cancel"):
        st.rerun()


@st.dialog("✏️ Edit Phase", width="large")
def _dialog_edit_phase(phase_id: int):
    ph = get_phase(phase_id) or {}
    with st.form("edit_phase_form"):
        c1, c2, c3 = st.columns(3)
        seq  = c1.number_input("Sequence #", min_value=1, value=int(ph.get('sequence_no', 1)))
        code = c2.text_input("Phase Code", value=ph.get('phase_code', ''))
        name = c3.text_input("Phase Name *", value=ph.get('phase_name', ''))
        d1, d2, d3 = st.columns(3)
        p_start = d1.date_input("Planned Start", value=ph.get('planned_start'))
        p_end   = d2.date_input("Planned End", value=ph.get('planned_end'))
        weight  = d3.number_input("Weight %", min_value=0.0, max_value=100.0,
                                   value=float(ph.get('weight_percent') or 0))
        s1, s2 = st.columns(2)
        status = s1.selectbox("Status", PHASE_STATUS_OPTIONS,
                              index=PHASE_STATUS_OPTIONS.index(ph['status']) if ph.get('status') in PHASE_STATUS_OPTIONS else 0)
        pct = s2.number_input("Completion %", min_value=0.0, max_value=100.0,
                               value=float(ph.get('completion_percent') or 0))
        a_start = st.date_input("Actual Start", value=ph.get('actual_start'))
        a_end   = st.date_input("Actual End", value=ph.get('actual_end'))
        notes   = st.text_area("Notes", value=ph.get('notes') or '', height=70)
        col_s, col_c = st.columns(2)
        submitted = col_s.form_submit_button("💾 Save", type="primary", width="stretch")
        cancelled = col_c.form_submit_button("✖ Cancel", width="stretch")

    if cancelled:
        st.rerun()
    if submitted:
        if not name.strip():
            st.error("Phase Name is required.")
            return
        update_phase(phase_id, {
            'phase_code': code.strip().upper(), 'phase_name': name.strip(),
            'sequence_no': seq,
            'planned_start': p_start, 'planned_end': p_end,
            'actual_start': a_start, 'actual_end': a_end,
            'status': status, 'weight_percent': weight or None,
            'completion_percent': pct, 'notes': notes.strip() or None,
        }, user_id)
        st.success("Phase updated!")
        invalidate_wbs_cache(selected_project_id)
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# DIALOGS — Task CRUD
# ══════════════════════════════════════════════════════════════════════════════

def _task_form_fields(task: dict, is_create: bool):
    """Shared task form fields. Returns dict of values."""
    ph_df_form = wbs['phases']
    phase_opts = [(int(r['id']), f"{r['sequence_no']}. {r['phase_name']}") for _, r in ph_df_form.iterrows()]

    c1, c2 = st.columns(2)
    task_name = c1.text_input("Task Name *", value=task.get('task_name', ''))
    phase_labels = [p[1] for p in phase_opts]
    cur_phase_idx = next((i for i, p in enumerate(phase_opts) if p[0] == task.get('phase_id')), 0)
    phase_sel = c2.selectbox("Phase", phase_labels, index=cur_phase_idx if phase_opts else 0)
    phase_id = phase_opts[phase_labels.index(phase_sel)][0] if phase_opts else None

    c3, c4, c5 = st.columns(3)

    # Assignee — only if user has permission
    if perms['can_assign_tasks'] or is_create:
        emp_opts = ["(Unassigned)"] + [e['full_name'] for e in employees]
        emp_idx  = next((i + 1 for i, e in enumerate(employees) if e['id'] == task.get('assignee_id')), 0)
        emp_sel  = c3.selectbox("Assignee", emp_opts, index=emp_idx)
        assignee_id = employees[emp_opts.index(emp_sel) - 1]['id'] if emp_sel != "(Unassigned)" else None
    else:
        assignee_id = task.get('assignee_id')
        c3.text_input("Assignee", value=emp_map.get(assignee_id, '(Unassigned)'), disabled=True)

    # Priority — only manager/lead
    if perms['can_assign_tasks']:
        priority = c4.selectbox("Priority", PRIORITY_OPTIONS,
                                index=PRIORITY_OPTIONS.index(task['priority']) if task.get('priority') in PRIORITY_OPTIONS else 1)
    else:
        priority = task.get('priority', 'NORMAL')
        c4.text_input("Priority", value=priority, disabled=True)

    if is_create:
        wbs_code = c5.text_input("WBS Code", value=generate_wbs_code(phase_id) if phase_id else '',
                            help="Auto-generated. Edit if needed.")
    else:
        wbs_code = c5.text_input("WBS Code", value=task.get('wbs_code', ''))

    d1, d2, d3, d4 = st.columns(4)
    p_start = d1.date_input("Planned Start", value=task.get('planned_start'))
    p_end   = d2.date_input("Planned End", value=task.get('planned_end'))
    est_hrs = d3.number_input("Est. Hours", value=float(task.get('estimated_hours') or 0), min_value=0.0)

    if not is_create:
        status = d4.selectbox("Status", TASK_STATUS_OPTIONS,
                              index=TASK_STATUS_OPTIONS.index(task['status']) if task.get('status') in TASK_STATUS_OPTIONS else 0)
    else:
        status = 'NOT_STARTED'

    description = st.text_area("Description", value=task.get('description') or '', height=80)

    return {
        'project_id': selected_project_id, 'phase_id': phase_id,
        'parent_task_id': task.get('parent_task_id'),
        'wbs_code': wbs_code.strip() or None, 'task_name': task_name.strip(),
        'description': description.strip() or None, 'assignee_id': assignee_id,
        'priority': priority, 'status': status,
        'planned_start': p_start, 'planned_end': p_end,
        'actual_start': task.get('actual_start'), 'actual_end': task.get('actual_end'),
        'estimated_hours': est_hrs or None, 'actual_hours': task.get('actual_hours'),
        'completion_percent': float(task.get('completion_percent', 0)),
        'dependency_task_id': task.get('dependency_task_id'),
        'dependency_type': task.get('dependency_type', 'FS'),
    }


@st.dialog("➕ New Task", width="large")
def _dialog_create_task():
    with st.form("create_task_form"):
        data = _task_form_fields({}, is_create=True)
        col_s, col_c = st.columns(2)
        submitted = col_s.form_submit_button("💾 Create", type="primary", width="stretch")
        cancelled = col_c.form_submit_button("✖ Cancel", width="stretch")

    cc_ids, cc_emails = render_cc_selector(employees, key_prefix="task_create")

    if cancelled:
        st.rerun()
    if submitted:
        if not data['task_name']:
            st.error("Task Name is required.")
            return
        if not data['phase_id']:
            st.error("Please select a Phase.")
            return
        try:
            new_id = create_task(data, user_id)
            notify_on_task_assign(new_id, None, data.get('assignee_id'),
                                  performer_id=employee_id,
                                  extra_cc_ids=cc_ids, extra_cc_emails=cc_emails)
            st.success(f"✅ Task created! (ID: {new_id})")
            invalidate_wbs_cache(selected_project_id)
            st.rerun()
        except Exception as e:
            st.error(f"Save failed: {e}")


@st.dialog("✏️ Edit Task", width="large")
def _dialog_edit_task(task_id: int):
    task = get_task(task_id) or {}
    if not can_edit_task(perms, task.get('assignee_id'), employee_id):
        st.warning("You don't have permission to edit this task.")
        return

    with st.form("edit_task_form"):
        data = _task_form_fields(task, is_create=False)
        e1, e2 = st.columns(2)
        data['actual_start'] = e1.date_input("Actual Start", value=task.get('actual_start'))
        data['actual_end']   = e2.date_input("Actual End", value=task.get('actual_end'))
        e3, e4 = st.columns(2)
        data['actual_hours'] = e3.number_input("Actual Hours", value=float(task.get('actual_hours') or 0), min_value=0.0)
        data['completion_percent'] = e4.number_input("Completion %", value=float(task.get('completion_percent') or 0),
                                                      min_value=0.0, max_value=100.0)
        col_s, col_c = st.columns(2)
        submitted = col_s.form_submit_button("💾 Save", type="primary", width="stretch")
        cancelled = col_c.form_submit_button("✖ Cancel", width="stretch")

    cc_ids, cc_emails = [], []
    if perms['can_assign_tasks']:
        cc_ids, cc_emails = render_cc_selector(employees, key_prefix="task_edit")

    if cancelled:
        st.rerun()
    if submitted:
        if not data['task_name']:
            st.error("Task Name is required.")
            return
        try:
            old_assignee = task.get('assignee_id')
            old_status   = task.get('status')
            update_task(task_id, data, user_id)
            sync_completion_up(task_id, user_id)
            notify_on_task_assign(task_id, old_assignee, data.get('assignee_id'),
                                  performer_id=employee_id,
                                  extra_cc_ids=cc_ids, extra_cc_emails=cc_emails)
            notify_on_task_status_change(task_id, old_status, data.get('status', old_status),
                                         performer_id=employee_id,
                                         extra_cc_ids=cc_ids, extra_cc_emails=cc_emails)
            st.success("✅ Task updated!")
            invalidate_wbs_cache(selected_project_id)
            st.rerun()
        except Exception as e:
            st.error(f"Save failed: {e}")


@st.dialog("⚡ Quick Update", width="small")
def _dialog_quick_update(task_id: int):
    task = get_task(task_id) or {}
    if not can_quick_update_task(perms, task.get('assignee_id'), employee_id):
        st.warning("You don't have permission to update this task.")
        return

    st.markdown(f"**{task.get('wbs_code', '')}** {task.get('task_name', '')}")

    with st.form("quick_update_form"):
        status = st.selectbox("Status", TASK_STATUS_OPTIONS,
                              index=TASK_STATUS_OPTIONS.index(task['status']) if task.get('status') in TASK_STATUS_OPTIONS else 0)
        pct = st.slider("Completion %", 0, 100, int(task.get('completion_percent') or 0), step=5)
        hours = st.number_input("Actual Hours", value=float(task.get('actual_hours') or 0), min_value=0.0)
        blocker_note = st.text_input("Blocker reason (if blocked)", help="Required when status = BLOCKED")
        submitted = st.form_submit_button("💾 Update", type="primary", width="stretch")

    cc_ids, cc_emails = [], []
    if perms['can_assign_tasks']:
        cc_ids, cc_emails = render_cc_selector(employees, key_prefix="task_quick")

    if submitted:
        try:
            old_status = task.get('status', '')
            quick_update_task(task_id, status, float(pct), hours or None, user_id)
            sync_completion_up(task_id, user_id)
            if blocker_note.strip() and status == 'BLOCKED':
                create_comment(task_id, int(user_id), f"🚧 {blocker_note.strip()}", 'BLOCKER')
            notify_on_task_status_change(task_id, old_status, status,
                                         performer_id=employee_id,
                                         blocker_reason=blocker_note.strip() or None,
                                         extra_cc_ids=cc_ids, extra_cc_emails=cc_emails)
            st.success("✅ Updated!")
            invalidate_wbs_cache(selected_project_id)
            st.rerun()
        except Exception as e:
            st.error(f"Update failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# DIALOG — Task Detail View
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("📋 Task Details", width="large")
def _dialog_view_task(task_id: int):
    task = get_task(task_id)
    if not task:
        st.warning("Task not found.")
        return

    hc1, hc2 = st.columns([5, 1])
    hc1.subheader(f"{TASK_STATUS_ICONS.get(task['status'], '⚪')} {task.get('wbs_code', '')} — {task['task_name']}")

    if can_edit_task(perms, task.get('assignee_id'), employee_id):
        if hc2.button("✏️ Edit", type="primary"):
            st.session_state["open_edit_task"] = task_id
            st.rerun()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Status", task['status'])
    k2.metric("Completion", fmt_completion(task.get('completion_percent')))
    k3.metric("Hours", f"{fmt_hours(task.get('actual_hours'))} / {fmt_hours(task.get('estimated_hours'))}")
    k4.metric("Assignee", task.get('assignee_name') or '—')

    dt_info, dt_checklist, dt_comments, dt_files = st.tabs(["📋 Info", "✅ Checklist", "💬 Comments", "📎 Files"])

    with dt_info:
        ic1, ic2 = st.columns(2)
        ic1.markdown(f"**Phase:** {task.get('phase_name', '—')}")
        ic1.markdown(f"**Priority:** {fmt_priority(task.get('priority', 'NORMAL'))}")
        ic1.markdown(f"**Planned:** {task.get('planned_start', '—')} → {task.get('planned_end', '—')}")
        ic2.markdown(f"**Actual:** {task.get('actual_start', '—')} → {task.get('actual_end', '—')}")
        ic2.markdown(f"**Dependency:** {task.get('dependency_task_name') or '—'} ({task.get('dependency_type', '—')})")
        due_label = _format_due_date(task.get('planned_end'), task.get('status'))
        if '🔴' in due_label or '⚠️' in due_label:
            ic2.warning(f"**Due:** {due_label}")
        if task.get('description'):
            st.markdown(f"**Description:**\n{task['description']}")

    with dt_checklist:
        _can_toggle = can_quick_update_task(perms, task.get('assignee_id'), employee_id)

        @st.fragment
        def _checklist_fragment():
            items = get_checklists(task_id)
            if items:
                for item in items:
                    cc1, cc2 = st.columns([5, 1])
                    checked = bool(item['is_completed'])
                    if _can_toggle:
                        new_val = cc1.checkbox(item['item_name'], value=checked, key=f"cl_{item['id']}",
                            help=f"{'Done by ' + item['completed_by_name'] if item.get('completed_by_name') else ''}")
                        if new_val != checked:
                            toggle_checklist_item(item['id'], employee_id, new_val)
                            st.rerun()
                        if cc2.button("🗑", key=f"cl_del_{item['id']}"):
                            delete_checklist_item(item['id'])
                            st.rerun()
                    else:
                        cc1.markdown(f"{'✅' if checked else '⬜'} {item['item_name']}")
            else:
                st.caption("No checklist items.")

            if _can_toggle or perms.get('can_edit_any_task'):
                with st.expander("➕ Add Checklist Item"):
                    with st.form(f"cl_form_{task_id}"):
                        cl_name = st.text_input("Item Name *")
                        cl_seq  = st.number_input("Sequence", min_value=1, value=len(items) + 1)
                        if st.form_submit_button("Add", type="primary"):
                            if cl_name.strip():
                                create_checklist_item({'task_id': task_id, 'sequence_no': cl_seq,
                                    'item_name': cl_name.strip(), 'notes': None}, user_id)
                                st.rerun()
                            else:
                                st.error("Item name required.")
        _checklist_fragment()

    with dt_comments:
        @st.fragment
        def _comments_fragment():
            comments = get_task_comments(task_id)
            if comments:
                for cm in comments:
                    icon = comment_type_icon(cm['comment_type'])
                    ts = cm['created_date'].strftime('%Y-%m-%d %H:%M') if cm.get('created_date') else ''
                    st.markdown(f"{icon} **{cm['author_name']}** · {ts}")
                    st.caption(cm['content'])
                    if cm['comment_type'] == 'STATUS_CHANGE':
                        st.caption(f"`{cm['old_value']}` → `{cm['new_value']}`")
                    st.divider()
            else:
                st.caption("No comments yet.")

            with st.expander("➕ Add Comment"):
                with st.form(f"cm_form_{task_id}"):
                    cm_text = st.text_area("Comment", height=80)
                    cm_type = st.selectbox("Type", ['COMMENT', 'BLOCKER'])
                    if st.form_submit_button("Post", type="primary"):
                        if cm_text.strip():
                            create_comment(task_id, int(user_id), cm_text.strip(), cm_type)
                            st.rerun()
                        else:
                            st.error("Comment text required.")
        _comments_fragment()

    with dt_files:
        @st.fragment
        def _files_fragment():
            render_attachments('task', task_id, task['project_id'], user_id)
        _files_fragment()


# ══════════════════════════════════════════════════════════════════════════════
# DIALOG — User Guide (Phase 5: bilingual, searchable, role-aware)
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("❓ WBS User Guide", width="large")
def _dialog_user_guide():
    """Bilingual (VI default / EN), searchable, role-aware user guide."""

    # ── Language toggle + Search bar on same row ──
    lang_col, search_col = st.columns([1, 4])
    with lang_col:
        lang_options = {"🇻🇳 Tiếng Việt": "vi", "🇬🇧 English": "en"}
        lang_label = st.radio(
            "Ngôn ngữ",
            list(lang_options.keys()),
            index=0,  # Vietnamese default
            key="_guide_lang",
            horizontal=True,
            label_visibility="collapsed",
        )
        lang = lang_options[lang_label]

    with search_col:
        placeholder = "Tìm: blocked, quá hạn, gán task..." if lang == 'vi' else "Search: blocked, overdue, assign..."
        search_q = st.text_input(
            "🔍",
            placeholder=placeholder,
            key="_guide_search",
            label_visibility="collapsed",
        )

    # ── Context-aware tips ──
    ctx_tips = get_context_tips(kpis, perms, not wbs['phases'].empty, lang=lang)
    if ctx_tips:
        for tip in ctx_tips:
            st.info(tip)

    st.divider()

    # ── Load content for role + language ──
    sections = get_guide_sections_for_role(perms['tier'], lang=lang)
    faq_items = get_faq_for_role(perms['tier'], lang=lang)
    workflows = get_workflows_for_role(perms['tier'], lang=lang)

    # Apply search filter
    if search_q and len(search_q) >= 2:
        result = search_guide(search_q, sections, faq_items)
        sections = result['sections']
        faq_items = result['faq']
        q_lower = search_q.lower()
        workflows = [w for w in workflows if q_lower in w['title'].lower()
                     or any(q_lower in s.lower() for s in w.get('steps', []))
                     or any(q_lower in t for t in w.get('tags', []))]

        if not sections and not faq_items and not workflows:
            no_result_msg = f"Không tìm thấy '{search_q}'. Thử từ khóa khác." if lang == 'vi' else f"No results for '{search_q}'. Try a different keyword."
            st.warning(no_result_msg)
            return

    # ── Guide tabs ──
    lbl_guide    = "📖 Hướng dẫn" if lang == 'vi' else "📖 Guide"
    lbl_workflow = "🔄 Quy trình"  if lang == 'vi' else "🔄 Workflows"
    lbl_faq      = "❓ Hỏi đáp"    if lang == 'vi' else "❓ FAQ"

    guide_tab_labels = [lbl_guide]
    if workflows:
        guide_tab_labels.append(lbl_workflow)
    if faq_items:
        guide_tab_labels.append(lbl_faq)

    guide_tabs = st.tabs(guide_tab_labels)

    # ── Tab 1: Guide Sections ──
    with guide_tabs[0]:
        if not sections:
            msg = "Không có nội dung khớp." if lang == 'vi' else "No sections match your search."
            st.caption(msg)
        else:
            for section in sections:
                with st.expander(f"{section['icon']} {section['title']}", expanded=bool(search_q)):
                    st.markdown(section['content'])

    # ── Tab 2: Workflows ──
    if workflows and lbl_workflow in guide_tab_labels:
        tab_idx = guide_tab_labels.index(lbl_workflow)
        with guide_tabs[tab_idx]:
            for wf in workflows:
                with st.expander(f"{wf['icon']} {wf['title']}", expanded=bool(search_q)):
                    step_num = 0
                    for step in wf['steps']:
                        if step.startswith("  "):
                            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;{step.strip()}")
                        else:
                            step_num += 1
                            st.markdown(f"**{step_num}.** {step}")

    # ── Tab 3: FAQ ──
    if faq_items and lbl_faq in guide_tab_labels:
        tab_idx = guide_tab_labels.index(lbl_faq)
        with guide_tabs[tab_idx]:
            for item in faq_items:
                with st.expander(f"❓ {item['q']}", expanded=bool(search_q)):
                    st.markdown(item['a'])


# ══════════════════════════════════════════════════════════════════════════════
# DIALOG TRIGGERS — Permission-checked
# ══════════════════════════════════════════════════════════════════════════════

if st.session_state.pop("open_create_phase", False) and perms['can_manage_phases']:
    _dialog_create_phase()

if st.session_state.pop("open_phase_template", False) and perms['can_manage_phases']:
    _dialog_phase_template()

if "open_edit_phase" in st.session_state:
    pid = st.session_state.pop("open_edit_phase")
    if perms['can_manage_phases']:
        _dialog_edit_phase(pid)

if st.session_state.pop("open_create_task", False) and perms['can_create_tasks']:
    _dialog_create_task()

if "open_edit_task" in st.session_state:
    tid = st.session_state.pop("open_edit_task")
    _dialog_edit_task(tid)

if "open_view_task" in st.session_state:
    tid = st.session_state.pop("open_view_task")
    _dialog_view_task(tid)

if "open_quick_task" in st.session_state:
    tid = st.session_state.pop("open_quick_task")
    _dialog_quick_update(tid)

if st.session_state.pop("open_user_guide", False):
    _dialog_user_guide()