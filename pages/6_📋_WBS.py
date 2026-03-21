# pages/IL_6_📋_WBS.py
"""
WBS Management — Phases, Tasks, Checklists, Comments, Team.
UX: @st.dialog cho CRUD | tabs cho Phases/Tasks/My Tasks | session state cho dialog chaining
"""

import streamlit as st
import pandas as pd
import logging

from utils.auth import AuthManager
from utils.il_project import (
    get_projects_df, get_project, get_employees, fmt_vnd, STATUS_COLORS,
)
from utils.il_project.wbs_queries import (
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
    fmt_status, fmt_priority, fmt_completion, fmt_hours, comment_type_icon,
)
from utils.il_project.wbs_notify import (
    notify_on_task_status_change,
    notify_on_task_assign,
)

logger = logging.getLogger(__name__)
auth = AuthManager()

st.set_page_config(page_title="WBS Management", page_icon="📋", layout="wide")
auth.require_auth()
user_id     = str(auth.get_user_id())
employee_id = st.session_state.get('employee_id')
user_role   = st.session_state.get('user_role', '')
is_admin    = auth.is_admin()


# ── Lookups (cached) ──────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load_employees():
    return get_employees()

@st.cache_data(ttl=120)
def _load_projects():
    return get_projects_df(status=None)

employees = _load_employees()
emp_map   = {e['id']: e['full_name'] for e in employees}


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — Project selector + filters
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
    st.header("Filters")
    f_phase  = st.selectbox("Phase", ["All"], key="wbs_f_phase")   # populated dynamically below
    f_status = st.selectbox("Task Status", ["All"] + TASK_STATUS_OPTIONS)
    f_assignee = st.selectbox("Assignee", ["All", "🙋 Me"] +
                               [e['full_name'] for e in employees])

# Resolve filters
phase_filter_id = None  # updated after phases load
status_filter   = None if f_status == "All" else f_status
assignee_filter = None
if f_assignee == "🙋 Me":
    assignee_filter = employee_id
elif f_assignee not in ("All",):
    hit = next((e for e in employees if e['full_name'] == f_assignee), None)
    assignee_filter = hit['id'] if hit else None

# Project header
if proj_info:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Project", proj_info['project_code'])
    c2.metric("Status", proj_info['status'])
    c3.metric("PM", proj_info.get('pm_name', '—'))
    c4.metric("Completion", fmt_completion(proj_info.get('overall_completion_percent')))
    st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN TABS
# ══════════════════════════════════════════════════════════════════════════════

tab_phases, tab_tasks, tab_mytasks, tab_team = st.tabs(
    ["🔷 Phases", "📋 Tasks", "🙋 My Tasks", "👥 Team"]
)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: PHASES
# ══════════════════════════════════════════════════════════════════════════════

with tab_phases:
    ph_df = get_phases_df(selected_project_id)

    # Action bar
    pa1, pa2, pa3 = st.columns([1, 1, 5])
    if pa1.button("➕ Add Phase", type="primary"):
        st.session_state["open_create_phase"] = True
    if pa2.button("📦 Load Template"):
        st.session_state["open_phase_template"] = True

    if ph_df.empty:
        st.info("No phases defined. Add phases or load a template to get started.")
    else:
        # Progress bar per phase
        for _, ph in ph_df.iterrows():
            with st.container(border=True):
                pc1, pc2, pc3, pc4, pc5 = st.columns([3, 2, 2, 1, 1])
                pc1.markdown(f"**{ph['sequence_no']}. {ph['phase_name']}** `{ph['phase_code']}`")
                pc2.caption(f"{fmt_status(ph['status'])} · {ph['task_count']:.0f} tasks ({ph['tasks_done']:.0f} done)")
                pc3.progress(float(ph['completion_percent'] or 0) / 100,
                             text=f"{ph['completion_percent']:.0f}%")
                if pc4.button("✏️", key=f"ph_edit_{ph['id']}", help="Edit phase"):
                    st.session_state["open_edit_phase"] = int(ph['id'])
                    st.rerun()
                if pc5.button("🗑", key=f"ph_del_{ph['id']}", help="Delete phase"):
                    if soft_delete_phase(int(ph['id']), user_id):
                        st.success("Phase deleted.")
                        st.cache_data.clear()
                        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: TASKS
# ══════════════════════════════════════════════════════════════════════════════

with tab_tasks:
    # Reload phases for filter
    ph_df_for_filter = get_phases_df(selected_project_id)
    phase_opts = {int(r['id']): f"{r['sequence_no']}. {r['phase_name']}" for _, r in ph_df_for_filter.iterrows()}

    ta1, ta2, _ = st.columns([1, 1, 5])
    if ta1.button("➕ Add Task", type="primary", key="btn_add_task"):
        st.session_state["open_create_task"] = True

    task_df = get_tasks_df(
        project_id=selected_project_id,
        phase_id=phase_filter_id,
        assignee_id=assignee_filter,
        status=status_filter,
    )

    if task_df.empty:
        st.info("No tasks found. Create phases first, then add tasks.")
    else:
        # Add display columns
        display = task_df.copy()
        display['●'] = display['status'].map(lambda s: TASK_STATUS_ICONS.get(s, '⚪'))
        display['prio'] = display['priority'].map(lambda p: PRIORITY_ICONS.get(p, '🔵'))
        display['pct_fmt'] = display['completion_percent'].apply(fmt_completion)
        display['cl_fmt'] = display.apply(
            lambda r: f"{r['checklist_done']:.0f}/{r['checklist_total']:.0f}"
            if r['checklist_total'] > 0 else '—', axis=1
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
                'planned_end':      st.column_config.DateColumn('Due'),
                'cl_fmt':           st.column_config.TextColumn('✓', width=50),
                'comment_count':    st.column_config.NumberColumn('💬', width=40),
                # Hide raw columns
                'id': None, 'project_id': None, 'phase_id': None,
                'parent_task_id': None, 'description': None,
                'assignee_id': None, 'priority': None,
                'planned_start': None, 'actual_start': None, 'actual_end': None,
                'estimated_hours': None, 'actual_hours': None,
                'completion_percent': None,
                'dependency_task_id': None, 'dependency_type': None,
                'phase_code': None, 'checklist_total': None, 'checklist_done': None,
            },
        )

        sel = event.selection.rows
        if sel:
            selected_task_id = int(display.iloc[sel[0]]['id'])
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
                if ab2.button("✏️ Edit", use_container_width=True, key="task_edit"):
                    st.session_state["open_edit_task"] = selected_task_id
                    st.rerun()
                if ab3.button("⚡ Quick Update", use_container_width=True, key="task_quick"):
                    st.session_state["open_quick_task"] = selected_task_id
                    st.rerun()
                if ab4.button("🗑 Delete", use_container_width=True, key="task_del"):
                    if soft_delete_task(selected_task_id, user_id):
                        st.success("Task deleted.")
                        st.cache_data.clear()
                        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: MY TASKS
# ══════════════════════════════════════════════════════════════════════════════

with tab_mytasks:
    if not employee_id:
        st.warning("Cannot determine your employee ID. Please contact admin.")
    else:
        my_df = get_my_tasks_df(employee_id)
        st.metric("Active Tasks", len(my_df))

        if my_df.empty:
            st.success("🎉 No pending tasks assigned to you!")
        else:
            my_display = my_df.copy()
            my_display['prio'] = my_display['priority'].map(lambda p: PRIORITY_ICONS.get(p, '🔵'))
            my_display['pct_fmt'] = my_display['completion_percent'].apply(fmt_completion)

            event_my = st.dataframe(
                my_display,
                key="my_task_tbl", width="stretch", hide_index=True,
                on_select="rerun", selection_mode="single-row",
                column_config={
                    'prio':            st.column_config.TextColumn('!', width=30),
                    'project_code':    st.column_config.TextColumn('Project', width=100),
                    'phase_name':      st.column_config.TextColumn('Phase'),
                    'wbs_code':        st.column_config.TextColumn('WBS', width=60),
                    'task_name':       st.column_config.TextColumn('Task'),
                    'status':          st.column_config.TextColumn('Status', width=100),
                    'pct_fmt':         st.column_config.TextColumn('%', width=70),
                    'planned_end':     st.column_config.DateColumn('Due'),
                    'id': None, 'priority': None, 'completion_percent': None,
                    'actual_start': None, 'estimated_hours': None,
                    'actual_hours': None, 'project_name': None,
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
# TAB 4: TEAM (read-only summary — full CRUD in IL_7_Team)
# ══════════════════════════════════════════════════════════════════════════════

with tab_team:
    mem_df = get_project_members_df(selected_project_id)

    if mem_df.empty:
        st.info("No team members assigned yet. Go to **👥 Team & Resources** to add members.")
    else:
        # Summary metrics
        active_df = mem_df[mem_df['is_active'] == 1] if 'is_active' in mem_df.columns else mem_df
        tm1, tm2, tm3 = st.columns(3)
        tm1.metric("Team Size", len(active_df))
        tm2.metric("Total Allocation",
                   f"{active_df['allocation_percent'].sum():.0f}%"
                   if 'allocation_percent' in active_df.columns else '—')
        roles = active_df['role'].nunique() if 'role' in active_df.columns else 0
        tm3.metric("Roles", roles)

        # Read-only table
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

    st.page_link("pages/7_👥_WBS_Team.py", label="👥 Manage Team & Resources →", icon="👥")


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
        st.cache_data.clear()
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
        st.cache_data.clear()
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
        st.cache_data.clear()
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# DIALOGS — Task CRUD
# ══════════════════════════════════════════════════════════════════════════════

def _task_form_fields(task: dict, is_create: bool):
    """Shared task form fields. Returns dict of values."""
    ph_df_form = get_phases_df(selected_project_id)
    phase_opts = [(int(r['id']), f"{r['sequence_no']}. {r['phase_name']}") for _, r in ph_df_form.iterrows()]

    c1, c2 = st.columns(2)
    task_name = c1.text_input("Task Name *", value=task.get('task_name', ''))
    # Phase selector
    phase_labels = [p[1] for p in phase_opts]
    cur_phase_idx = next((i for i, p in enumerate(phase_opts) if p[0] == task.get('phase_id')), 0)
    phase_sel = c2.selectbox("Phase", phase_labels, index=cur_phase_idx if phase_opts else 0)
    phase_id = phase_opts[phase_labels.index(phase_sel)][0] if phase_opts else None

    c3, c4, c5 = st.columns(3)
    # Assignee
    emp_opts = ["(Unassigned)"] + [e['full_name'] for e in employees]
    emp_idx  = next((i + 1 for i, e in enumerate(employees) if e['id'] == task.get('assignee_id')), 0)
    emp_sel  = c3.selectbox("Assignee", emp_opts, index=emp_idx)
    assignee_id = employees[emp_opts.index(emp_sel) - 1]['id'] if emp_sel != "(Unassigned)" else None

    priority = c4.selectbox("Priority", PRIORITY_OPTIONS,
                            index=PRIORITY_OPTIONS.index(task['priority']) if task.get('priority') in PRIORITY_OPTIONS else 1)
    if is_create:
        wbs = c5.text_input("WBS Code", value=generate_wbs_code(phase_id) if phase_id else '',
                            help="Auto-generated. Edit if needed.")
    else:
        wbs = c5.text_input("WBS Code", value=task.get('wbs_code', ''))

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
        'project_id':       selected_project_id,
        'phase_id':         phase_id,
        'parent_task_id':   task.get('parent_task_id'),
        'wbs_code':         wbs.strip() or None,
        'task_name':        task_name.strip(),
        'description':      description.strip() or None,
        'assignee_id':      assignee_id,
        'priority':         priority,
        'status':           status,
        'planned_start':    p_start,
        'planned_end':      p_end,
        'actual_start':     task.get('actual_start'),
        'actual_end':       task.get('actual_end'),
        'estimated_hours':  est_hrs or None,
        'actual_hours':     task.get('actual_hours'),
        'completion_percent': float(task.get('completion_percent', 0)),
        'dependency_task_id': task.get('dependency_task_id'),
        'dependency_type':    task.get('dependency_type', 'FS'),
    }


@st.dialog("➕ New Task", width="large")
def _dialog_create_task():
    with st.form("create_task_form"):
        data = _task_form_fields({}, is_create=True)
        col_s, col_c = st.columns(2)
        submitted = col_s.form_submit_button("💾 Create", type="primary", width="stretch")
        cancelled = col_c.form_submit_button("✖ Cancel", width="stretch")

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
            notify_on_task_assign(new_id, None, data.get('assignee_id'), int(user_id))
            st.success(f"✅ Task created! (ID: {new_id})")
            st.cache_data.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Save failed: {e}")


@st.dialog("✏️ Edit Task", width="large")
def _dialog_edit_task(task_id: int):
    task = get_task(task_id) or {}
    with st.form("edit_task_form"):
        data = _task_form_fields(task, is_create=False)
        # Extra fields for edit
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
            notify_on_task_assign(task_id, old_assignee, data.get('assignee_id'), int(user_id))
            notify_on_task_status_change(task_id, old_status, data.get('status', old_status), int(user_id))
            st.success("✅ Task updated!")
            st.cache_data.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Save failed: {e}")


@st.dialog("⚡ Quick Update", width="small")
def _dialog_quick_update(task_id: int):
    """Engineer fast-update: status, %, hours only."""
    task = get_task(task_id) or {}
    st.markdown(f"**{task.get('wbs_code', '')}** {task.get('task_name', '')}")

    with st.form("quick_update_form"):
        status = st.selectbox("Status", TASK_STATUS_OPTIONS,
                              index=TASK_STATUS_OPTIONS.index(task['status']) if task.get('status') in TASK_STATUS_OPTIONS else 0)
        pct = st.slider("Completion %", 0, 100, int(task.get('completion_percent') or 0), step=5)
        hours = st.number_input("Actual Hours", value=float(task.get('actual_hours') or 0), min_value=0.0)
        blocker_note = st.text_input("Blocker reason (if blocked)", help="Required when status = BLOCKED")
        submitted = st.form_submit_button("💾 Update", type="primary", width="stretch")

    if submitted:
        try:
            old_status = task.get('status', '')
            quick_update_task(task_id, status, float(pct), hours or None, user_id)
            sync_completion_up(task_id, user_id)
            # Post blocker comment if provided
            if blocker_note.strip() and status == 'BLOCKED':
                create_comment(task_id, int(user_id), f"🚧 {blocker_note.strip()}", 'BLOCKER')
            notify_on_task_status_change(task_id, old_status, status, int(user_id),
                                         blocker_reason=blocker_note.strip() or None)
            st.success("✅ Updated!")
            st.cache_data.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Update failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# DIALOG — Task Detail View (with tabs: Info, Checklist, Comments)
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("📋 Task Details", width="large")
def _dialog_view_task(task_id: int):
    task = get_task(task_id)
    if not task:
        st.warning("Task not found.")
        return

    # Header
    hc1, hc2 = st.columns([5, 1])
    hc1.subheader(f"{TASK_STATUS_ICONS.get(task['status'], '⚪')} {task.get('wbs_code', '')} — {task['task_name']}")
    if hc2.button("✏️ Edit", type="primary"):
        st.session_state["open_edit_task"] = task_id
        st.rerun()

    # KPIs
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Status", task['status'])
    k2.metric("Completion", fmt_completion(task.get('completion_percent')))
    k3.metric("Hours", f"{fmt_hours(task.get('actual_hours'))} / {fmt_hours(task.get('estimated_hours'))}")
    k4.metric("Assignee", task.get('assignee_name') or '—')

    # Tabs inside dialog (no nested dialog — follows milestone panel pattern)
    dt_info, dt_checklist, dt_comments, dt_files = st.tabs(["📋 Info", "✅ Checklist", "💬 Comments", "📎 Files"])

    # ── Info tab ──────────────────────────────────────────────────────────────
    with dt_info:
        ic1, ic2 = st.columns(2)
        ic1.markdown(f"**Phase:** {task.get('phase_name', '—')}")
        ic1.markdown(f"**Priority:** {fmt_priority(task.get('priority', 'NORMAL'))}")
        ic1.markdown(f"**Planned:** {task.get('planned_start', '—')} → {task.get('planned_end', '—')}")
        ic2.markdown(f"**Actual:** {task.get('actual_start', '—')} → {task.get('actual_end', '—')}")
        ic2.markdown(f"**Dependency:** {task.get('dependency_task_name') or '—'} ({task.get('dependency_type', '—')})")
        if task.get('description'):
            st.markdown(f"**Description:**\n{task['description']}")

    # ── Checklist tab ─────────────────────────────────────────────────────────
    with dt_checklist:
        items = get_checklists(task_id)
        if items:
            for item in items:
                cc1, cc2 = st.columns([5, 1])
                checked = bool(item['is_completed'])
                new_val = cc1.checkbox(
                    item['item_name'],
                    value=checked,
                    key=f"cl_{item['id']}",
                    help=f"{'Done by ' + item['completed_by_name'] if item.get('completed_by_name') else ''}",
                )
                if new_val != checked:
                    toggle_checklist_item(item['id'], employee_id, new_val)
                    st.rerun()
                if cc2.button("🗑", key=f"cl_del_{item['id']}"):
                    delete_checklist_item(item['id'])
                    st.rerun()
        else:
            st.caption("No checklist items.")

        with st.expander("➕ Add Checklist Item"):
            with st.form(f"cl_form_{task_id}"):
                cl_name = st.text_input("Item Name *")
                cl_seq  = st.number_input("Sequence", min_value=1, value=len(items) + 1)
                if st.form_submit_button("Add", type="primary"):
                    if cl_name.strip():
                        create_checklist_item({
                            'task_id': task_id,
                            'sequence_no': cl_seq,
                            'item_name': cl_name.strip(),
                            'notes': None,
                        }, user_id)
                        st.rerun()
                    else:
                        st.error("Item name required.")

    # ── Comments tab ──────────────────────────────────────────────────────────
    with dt_comments:
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

    # ── Files tab ─────────────────────────────────────────────────────────────
    with dt_files:
        files = get_entity_medias('task', task_id)
        if files:
            st.markdown(f"**{len(files)} file(s)**")
            for f in files:
                fc1, fc2 = st.columns([5, 1])
                url = get_attachment_url(f['s3_key'])
                label = f['file_name'] or 'file'
                desc = f" — {f['description']}" if f.get('description') else ''
                if url:
                    fc1.markdown(f"📄 [{label}]({url}){desc}")
                else:
                    fc1.caption(f"📄 {label}{desc}")
                if fc2.button("🗑", key=f"tf_rm_{f['junction_id']}"):
                    unlink_media('task', f['junction_id'])
                    st.rerun()
        else:
            st.caption("No files attached.")

        with st.expander("➕ Attach File"):
            uploaded = st.file_uploader(
                "Choose file", type=['pdf', 'png', 'jpg', 'jpeg', 'xlsx', 'docx'],
                key=f"tf_upload_{task_id}",
            )
            tf_desc = st.text_input("Description (optional)", key=f"tf_desc_{task_id}")
            if uploaded:
                if st.button("📤 Upload", key=f"tf_do_{task_id}"):
                    ok = upload_and_attach(
                        'task', task_id, task['project_id'],
                        uploaded.getvalue(), uploaded.name,
                        description=tf_desc.strip() or None, created_by=user_id,
                    )
                    if ok:
                        st.success(f"✅ Attached: {uploaded.name}")
                        st.rerun()
                    else:
                        st.error("Upload failed.")


# ══════════════════════════════════════════════════════════════════════════════
# DIALOG TRIGGERS (at end of page — same pattern as IL_1)
# ══════════════════════════════════════════════════════════════════════════════

if st.session_state.pop("open_create_phase", False):
    _dialog_create_phase()

if st.session_state.pop("open_phase_template", False):
    _dialog_phase_template()

if "open_edit_phase" in st.session_state:
    pid = st.session_state.pop("open_edit_phase")
    _dialog_edit_phase(pid)

if st.session_state.pop("open_create_task", False):
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