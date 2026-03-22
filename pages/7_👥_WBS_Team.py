# pages/IL_7_👥_Team.py
"""
Team & Resource Management — Project members, allocation, workload.

v2.0 — Performance optimization:
  - Bootstrap: members from shared WBS cache (0 extra queries when navigating from page 6)
  - Targeted cache invalidation: invalidate_wbs_cache() replaces st.cache_data.clear()

UX: @st.dialog cho CRUD | tabs cho Team Roster / Workload | session state cho dialog chaining
"""

import streamlit as st
import pandas as pd
from datetime import date
import logging

from utils.auth import AuthManager
from utils.il_project import (
    get_projects_df, get_project, get_employees, fmt_vnd, STATUS_COLORS,
)
from utils.il_project.wbs_queries import (
    bootstrap_wbs_data,
    get_project_members_df, get_member,
    create_member, update_member, remove_member,
    get_member_workload,
)
from utils.il_project.wbs_helpers import (
    MEMBER_ROLES, MEMBER_ROLE_LABELS,
    invalidate_wbs_cache,
    render_cc_selector,
)
from utils.il_project.helpers import DEFAULT_RATES_BY_LEVEL
from utils.il_project.wbs_notify import notify_member_added

logger = logging.getLogger(__name__)
auth = AuthManager()

st.set_page_config(page_title="Team & Resources", page_icon="👥", layout="wide")
auth.require_auth()
user_id     = str(auth.get_user_id())
employee_id = st.session_state.get('employee_id')
is_admin    = auth.is_admin()


# ── Cached lookups ────────────────────────────────────────────────────────────
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

employees = _load_employees()
emp_map   = {e['id']: e['full_name'] for e in employees}


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

st.title("👥 Team & Resources")

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
                            format_func=lambda i: proj_options[i], key="team_proj_sel")
    selected_project_id = int(proj_df.iloc[proj_idx]['project_id'])
    proj_info = get_project(selected_project_id)

    st.divider()
    st.header("Quick Actions")
    if st.button("➕ Add Member", type="primary", use_container_width=True):
        st.session_state["open_create_member_7"] = True
    if st.button("📊 My Workload", use_container_width=True):
        if employee_id:
            st.session_state["open_workload_emp"] = employee_id
        else:
            st.warning("Employee ID not found.")

# ── Load data (from shared bootstrap cache) ──
wbs = _get_wbs(selected_project_id)

if proj_info:
    c1, c2, c3 = st.columns(3)
    c1.metric("Project", f"{proj_info['project_code']} — {proj_info['project_name']}")
    c2.metric("Status", f"{STATUS_COLORS.get(proj_info['status'], '⚪')} {proj_info['status']}")
    c3.metric("PM", proj_info.get('pm_name', '—'))
    st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN TABS
# ══════════════════════════════════════════════════════════════════════════════

tab_roster, tab_workload = st.tabs(["📋 Team Roster", "📊 Workload Overview"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: TEAM ROSTER (from bootstrap cache)
# ══════════════════════════════════════════════════════════════════════════════

with tab_roster:
    mem_df = wbs['members']  # From bootstrap — no extra query

    if not mem_df.empty:
        active_df = mem_df[mem_df['is_active'] == 1] if 'is_active' in mem_df.columns else mem_df
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Team Size", len(active_df))
        m2.metric("Total Allocation",
                  f"{active_df['allocation_percent'].sum():.0f}%"
                  if 'allocation_percent' in active_df.columns else '—')
        avg_rate = active_df['daily_rate'].mean() if 'daily_rate' in active_df.columns and active_df['daily_rate'].notna().any() else 0
        m3.metric("Avg Daily Rate", fmt_vnd(avg_rate))
        roles_count = active_df['role'].nunique() if 'role' in active_df.columns else 0
        m4.metric("Roles", roles_count)
        st.divider()

    ba1, _ = st.columns([1, 6])
    if ba1.button("➕ Add Member", type="primary", key="roster_add"):
        st.session_state["open_create_member_7"] = True

    if mem_df.empty:
        st.info("No team members assigned to this project yet.")
    else:
        display = mem_df.copy()
        display['role_label'] = display['role'].map(lambda r: MEMBER_ROLE_LABELS.get(r, r))
        display['alloc_fmt'] = display['allocation_percent'].apply(
            lambda v: f"{v:.0f}%" if pd.notna(v) else '—'
        )
        display['rate_fmt'] = display['daily_rate'].apply(
            lambda v: f"{v:,.0f}" if pd.notna(v) and v else '—'
        )
        display['active_icon'] = display['is_active'].map(lambda v: '✅' if v else '⚪')

        event = st.dataframe(
            display,
            key=f"mem_tbl_{st.session_state.get('_mem_tbl_key', 0)}",
            width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            column_config={
                'active_icon':       st.column_config.TextColumn('', width=30),
                'member_name':       st.column_config.TextColumn('Name'),
                'email':             st.column_config.TextColumn('Email'),
                'role_label':        st.column_config.TextColumn('Role'),
                'alloc_fmt':         st.column_config.TextColumn('Allocation', width=80),
                'rate_fmt':          st.column_config.TextColumn('Daily Rate (₫)', width=110),
                'start_date':        st.column_config.DateColumn('Start'),
                'end_date':          st.column_config.DateColumn('End'),
                'notes':             st.column_config.TextColumn('Notes'),
                'id': None, 'employee_id': None, 'role': None,
                'allocation_percent': None, 'daily_rate': None,
                'is_active': None,
            },
        )

        sel = event.selection.rows
        if sel:
            selected_mem = display.iloc[sel[0]]
            selected_mem_id = int(selected_mem['id'])
            st.markdown(
                f"**Selected:** {selected_mem['member_name']} — "
                f"{selected_mem['role_label']} ({selected_mem['alloc_fmt']})"
            )
            ab1, ab2, ab3, ab4, _ = st.columns([1, 1, 1, 1, 3])
            if ab1.button("✏️ Edit", type="primary", use_container_width=True, key="mem_edit"):
                st.session_state["open_edit_member"] = selected_mem_id
                st.rerun()
            if ab2.button("📊 Workload", use_container_width=True, key="mem_workload"):
                st.session_state["open_workload_emp"] = int(selected_mem['employee_id'])
                st.rerun()
            if ab3.button("🗑 Remove", use_container_width=True, key="mem_remove"):
                if remove_member(selected_mem_id, user_id):
                    st.success(f"Removed {selected_mem['member_name']} from project.")
                    invalidate_wbs_cache(selected_project_id)
                    st.rerun()
            if ab4.button("✖ Deselect", use_container_width=True, key="mem_desel"):
                st.session_state["_mem_tbl_key"] = st.session_state.get("_mem_tbl_key", 0) + 1
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: WORKLOAD OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════

with tab_workload:
    st.caption("View resource allocation across active projects for any employee.")

    emp_opts = [e['full_name'] for e in employees]
    default_idx = next((i for i, e in enumerate(employees) if e['id'] == employee_id), 0)
    wl_emp_sel = st.selectbox("Select Employee", emp_opts, index=default_idx, key="wl_emp_sel")
    wl_emp_id = employees[emp_opts.index(wl_emp_sel)]['id']

    if st.button("🔍 Load Workload", key="wl_load"):
        st.session_state["_wl_emp_id"] = wl_emp_id

    wl_target = st.session_state.get("_wl_emp_id")
    if wl_target:
        wl_data = get_member_workload(wl_target)
        if not wl_data:
            st.info(f"No active project allocations found for {emp_map.get(wl_target, 'this employee')}.")
        else:
            wl_df = pd.DataFrame(wl_data)
            total_alloc = wl_df['allocation_percent'].sum()

            wm1, wm2, wm3 = st.columns(3)
            wm1.metric("Active Projects", len(wl_df))
            wm2.metric("Total Allocation", f"{total_alloc:.0f}%")
            if total_alloc > 100:
                wm3.metric("Status", "🔴 Over-allocated")
            elif total_alloc > 80:
                wm3.metric("Status", "🟡 Near capacity")
            else:
                wm3.metric("Status", "🟢 Available")

            st.dataframe(
                wl_df, width="stretch", hide_index=True,
                column_config={
                    'project_code':      st.column_config.TextColumn('Project'),
                    'project_name':      st.column_config.TextColumn('Name'),
                    'role':              st.column_config.TextColumn('Role'),
                    'allocation_percent': st.column_config.NumberColumn('Allocation %', format="%.0f%%"),
                    'daily_rate':        st.column_config.NumberColumn('Daily Rate', format="%.0f"),
                    'project_id': None,
                },
            )

            st.progress(
                min(total_alloc / 100, 1.0),
                text=f"Total allocation: {total_alloc:.0f}% {'⚠️ Over-allocated!' if total_alloc > 100 else ''}"
            )


# ══════════════════════════════════════════════════════════════════════════════
# DIALOGS
# ══════════════════════════════════════════════════════════════════════════════

def _member_form_fields(member: dict, is_create: bool):
    """Shared member form fields. Returns dict."""
    emp_opts = [e['full_name'] for e in employees]

    if is_create:
        emp_sel = st.selectbox("Employee *", emp_opts)
        emp_id  = employees[emp_opts.index(emp_sel)]['id']
    else:
        emp_name = emp_map.get(member.get('employee_id'), '—')
        st.text_input("Employee", value=emp_name, disabled=True)
        emp_id = member.get('employee_id')

    c1, c2 = st.columns(2)
    role = c1.selectbox(
        "Role *", MEMBER_ROLES,
        format_func=lambda r: MEMBER_ROLE_LABELS.get(r, r),
        index=MEMBER_ROLES.index(member['role']) if member.get('role') in MEMBER_ROLES else 0,
    )
    alloc = c2.number_input(
        "Allocation %", min_value=0.0, max_value=200.0,
        value=float(member.get('allocation_percent') or 100),
        help="100 = full-time. Can exceed 100 for short bursts.",
    )

    c3, c4 = st.columns(2)
    rate = c3.number_input(
        "Daily Rate (VND)", min_value=0.0,
        value=float(member.get('daily_rate') or DEFAULT_RATES_BY_LEVEL.get(role, 1_200_000)),
        format="%.0f",
        help="Cost rate per man-day. Used for budget calculation.",
    )
    is_active = c4.selectbox(
        "Active", [True, False],
        index=0 if member.get('is_active', True) else 1,
        format_func=lambda v: "✅ Active" if v else "⚪ Inactive",
    )

    d1, d2 = st.columns(2)
    m_start = d1.date_input("Start Date", value=member.get('start_date') or date.today())
    m_end   = d2.date_input("End Date (optional)", value=member.get('end_date'))

    notes = st.text_input("Notes", value=member.get('notes') or '')

    return {
        'project_id':       selected_project_id,
        'employee_id':      emp_id,
        'role':             role,
        'allocation_percent': alloc,
        'daily_rate':       rate or None,
        'start_date':       m_start,
        'end_date':         m_end,
        'is_active':        1 if is_active else 0,
        'notes':            notes.strip() or None,
    }


@st.dialog("➕ Add Team Member", width="large")
def _dialog_create_member():
    with st.form("create_member_form_7"):
        data = _member_form_fields({}, is_create=True)
        col_s, col_c = st.columns(2)
        submitted = col_s.form_submit_button("💾 Add", type="primary", width="stretch")
        cancelled = col_c.form_submit_button("✖ Cancel", width="stretch")

    # CC selector OUTSIDE form
    cc_ids, cc_emails = render_cc_selector(employees, key_prefix="member_create")

    if cancelled:
        st.rerun()
    if submitted:
        try:
            # Check for duplicate using bootstrap cache
            existing = wbs['members']
            if not existing.empty:
                dup = existing[
                    (existing['employee_id'] == data['employee_id']) &
                    (existing['role'] == data['role'])
                ]
                if not dup.empty:
                    st.error(f"This employee already has the role '{MEMBER_ROLE_LABELS.get(data['role'], data['role'])}' on this project.")
                    return

            new_id = create_member(data, user_id)
            notify_member_added(
                project_code=proj_info.get('project_code', ''),
                project_name=proj_info.get('project_name', ''),
                project_id=selected_project_id,
                employee_id=data['employee_id'],
                role=data['role'],
                allocation_percent=data.get('allocation_percent', 100),
                performer_id=employee_id,
                pm_name=proj_info.get('pm_name'),
                extra_cc_ids=cc_ids,
                extra_cc_emails=cc_emails,
            )
            st.success(f"✅ Member added! (ID: {new_id})")
            invalidate_wbs_cache(selected_project_id)
            st.rerun()
        except Exception as e:
            st.error(f"Failed: {e}")


@st.dialog("✏️ Edit Team Member", width="large")
def _dialog_edit_member(member_id: int):
    member = get_member(member_id) or {}
    with st.form("edit_member_form_7"):
        data = _member_form_fields(member, is_create=False)
        col_s, col_c = st.columns(2)
        submitted = col_s.form_submit_button("💾 Save", type="primary", width="stretch")
        cancelled = col_c.form_submit_button("✖ Cancel", width="stretch")

    if cancelled:
        st.rerun()
    if submitted:
        try:
            update_member(member_id, data, user_id)
            st.success("✅ Member updated!")
            invalidate_wbs_cache(selected_project_id)
            st.rerun()
        except Exception as e:
            st.error(f"Failed: {e}")


@st.dialog("📊 Employee Workload", width="large")
def _dialog_workload(emp_id: int):
    emp_name = emp_map.get(emp_id, f"Employee #{emp_id}")
    st.subheader(f"📊 {emp_name}")

    wl_data = get_member_workload(emp_id)
    if not wl_data:
        st.info("No active project allocations.")
        return

    wl_df = pd.DataFrame(wl_data)
    total_alloc = wl_df['allocation_percent'].sum()

    m1, m2 = st.columns(2)
    m1.metric("Projects", len(wl_df))
    m2.metric("Total Allocation", f"{total_alloc:.0f}%")

    if total_alloc > 100:
        st.warning(f"⚠️ Over-allocated by {total_alloc - 100:.0f}%")
    elif total_alloc > 80:
        st.info(f"ℹ️ Near capacity ({total_alloc:.0f}%)")
    else:
        st.success(f"✅ Available ({100 - total_alloc:.0f}% remaining)")

    st.dataframe(
        wl_df, width="stretch", hide_index=True,
        column_config={
            'project_code':      st.column_config.TextColumn('Project'),
            'project_name':      st.column_config.TextColumn('Name'),
            'role':              st.column_config.TextColumn('Role'),
            'allocation_percent': st.column_config.NumberColumn('Alloc %', format="%.0f%%"),
            'daily_rate':        st.column_config.NumberColumn('Rate', format="%.0f"),
            'project_id': None,
        },
    )

    st.progress(
        min(total_alloc / 100, 1.0),
        text=f"{total_alloc:.0f}% allocated"
    )


# ══════════════════════════════════════════════════════════════════════════════
# DIALOG TRIGGERS
# ══════════════════════════════════════════════════════════════════════════════

if st.session_state.pop("open_create_member_7", False):
    _dialog_create_member()

if "open_edit_member" in st.session_state:
    mid = st.session_state.pop("open_edit_member")
    _dialog_edit_member(mid)

if "open_workload_emp" in st.session_state:
    eid = st.session_state.pop("open_workload_emp")
    _dialog_workload(eid)