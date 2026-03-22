# pages/IL_7_👥_Team.py
"""
Team & Resource Management — Project members, allocation, workload, cost.

v3.0 — Role-based UX + Enrichment:
  Phase 1: Role resolution + access control + permission gating
  Phase 2: Enriched roster (task counts, overdue, avg%) + team health alerts
  Phase 3: Workload matrix (all members × all projects, heatmap)
  Phase 4: Cost summary tab (PM only)
  Phase 5: Column visibility per role (mask rates, emails)

  (v2.0 bootstrap cache preserved)
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
    get_member_workload, get_team_workload_matrix,
)
from utils.il_project.wbs_helpers import (
    MEMBER_ROLES, MEMBER_ROLE_LABELS,
    invalidate_wbs_cache,
    render_cc_selector,
    # v3.0
    resolve_project_role, enrich_members_with_tasks,
    compute_team_alerts, compute_cost_summary,
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

@st.cache_data(ttl=120, show_spinner=False)
def _cached_workload_matrix(project_id: int, _v: int = 0):
    return get_team_workload_matrix(project_id)

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

# ── Load data ──
wbs = _get_wbs(selected_project_id)


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1: ROLE RESOLUTION + ACCESS CONTROL
# ══════════════════════════════════════════════════════════════════════════════

perms = resolve_project_role(wbs['members'], employee_id, is_admin)

# Block restricted tier → redirect to WBS page
if perms['tier'] == 'restricted' and not is_admin:
    st.warning("🔒 Team management is not available for your role.")
    st.info("Use the **📋 WBS** page to view and update your tasks.")
    st.page_link("pages/IL_6_📋_WBS.py", label="📋 Go to WBS", icon="📋")
    st.stop()

_my_name = emp_map.get(employee_id, 'there')
_my_role_label = MEMBER_ROLE_LABELS.get(perms['role'], perms.get('role') or 'Guest')


# ══════════════════════════════════════════════════════════════════════════════
# WELCOME BANNER + TEAM KPIs
# ══════════════════════════════════════════════════════════════════════════════

if proj_info:
    _project_label = f"**{proj_info['project_code']}** — {proj_info['project_name']}"
    _role_chip = f"`{_my_role_label}`" if perms['is_member'] else "`Guest`"
    st.markdown(f"Hi **{_my_name}** · {_role_chip} on {_project_label}")

# Enrich members with task data (Phase 2 — 0 extra queries)
mem_df = wbs['members']
enriched = enrich_members_with_tasks(mem_df, wbs['tasks'])

# KPIs
active_df = enriched[enriched['is_active'] == 1] if 'is_active' in enriched.columns else enriched
k1, k2, k3, k4 = st.columns(4)
k1.metric("Team Size", len(active_df))
total_alloc = active_df['allocation_percent'].sum() if not active_df.empty and 'allocation_percent' in active_df.columns else 0
k2.metric("Total Allocation", f"{total_alloc:.0f}%")

n_over = 0
if not active_df.empty and 'overdue_count' in active_df.columns:
    n_over = int((active_df['overdue_count'] > 0).sum())
k3.metric("Members w/ Overdue", n_over,
          delta=None if n_over == 0 else f"-{n_over}",
          delta_color="inverse")

n_idle = 0
if not active_df.empty and 'task_count' in active_df.columns:
    n_idle = int((active_df['task_count'] == 0).sum())
k4.metric("Idle (0 tasks)", n_idle,
          delta=None if n_idle == 0 else f"{n_idle}",
          delta_color="inverse")

st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# TEAM HEALTH ALERTS (Phase 2 — PM only)
# ══════════════════════════════════════════════════════════════════════════════

if perms['tier'] == 'manager':
    alerts = compute_team_alerts(enriched)
    if alerts:
        with st.expander(f"⚠️ Team Alerts ({len(alerts)})", expanded=len(alerts) <= 5):
            for a in alerts:
                st.markdown(f"{a['icon']} **{a['member']}** ({a.get('role', '')}) — {a['message']}")
        st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN TABS — Dynamic based on role
# ══════════════════════════════════════════════════════════════════════════════

tab_labels = ["📋 Team Roster"]
tab_keys   = ["roster"]

if perms['tier'] in ('manager', 'lead'):
    tab_labels.append("📊 Workload Matrix")
    tab_keys.append("workload")

if perms['tier'] == 'manager':
    tab_labels.append("💰 Cost Summary")
    tab_keys.append("cost")

tabs_obj = st.tabs(tab_labels)
tab_map = dict(zip(tab_keys, tabs_obj))


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: TEAM ROSTER (enriched, permission-gated columns)
# ══════════════════════════════════════════════════════════════════════════════

with tab_map['roster']:
    # Add Member button — PM only
    if perms['can_manage_team']:
        ba1, _ = st.columns([1, 6])
        if ba1.button("➕ Add Member", type="primary", key="roster_add"):
            st.session_state["open_create_member_7"] = True

    if enriched.empty:
        st.info("No team members assigned to this project yet." +
                (" Click **➕ Add Member** to get started." if perms['can_manage_team'] else ""))
    else:
        display = enriched.copy()
        display['role_label'] = display['role'].map(lambda r: MEMBER_ROLE_LABELS.get(r, r))
        display['alloc_fmt'] = display['allocation_percent'].apply(
            lambda v: f"{v:.0f}%" if pd.notna(v) else '—'
        )
        display['active_icon'] = display['is_active'].map(lambda v: '✅' if v else '⚪')

        # Phase 2: task enrichment columns
        display['tasks_fmt'] = display.apply(
            lambda r: f"{int(r.get('task_count', 0))} ({int(r.get('done_count', 0))} done)" if r.get('task_count', 0) > 0 else '—',
            axis=1
        )
        display['overdue_fmt'] = display['overdue_count'].apply(
            lambda v: f"⏰ {int(v)}" if v > 0 else '—'
        )
        display['avg_pct'] = display['avg_completion'].apply(
            lambda v: f"{v:.0f}%" if v > 0 else '—'
        )
        display['hours_fmt'] = display.apply(
            lambda r: f"{r.get('total_actual_hours', 0):.0f}h / {r.get('total_est_hours', 0):.0f}h"
            if r.get('total_est_hours', 0) > 0 else '—',
            axis=1
        )

        # Phase 5: Dynamic column_config based on role
        col_config = {
            'active_icon':  st.column_config.TextColumn('', width=30),
            'member_name':  st.column_config.TextColumn('Name'),
            'role_label':   st.column_config.TextColumn('Role'),
            'alloc_fmt':    st.column_config.TextColumn('Alloc', width=70),
            'tasks_fmt':    st.column_config.TextColumn('Tasks', width=110),
        }

        # Manager/Lead: show overdue, avg, hours
        if perms['tier'] in ('manager', 'lead'):
            col_config['overdue_fmt'] = st.column_config.TextColumn('Overdue', width=70)
            col_config['avg_pct']     = st.column_config.TextColumn('Avg %', width=60)
            col_config['hours_fmt']   = st.column_config.TextColumn('Hours', width=100)

        # Manager only: rates, emails, dates
        if perms['tier'] == 'manager':
            display['rate_fmt'] = display['daily_rate'].apply(
                lambda v: f"{v:,.0f}" if pd.notna(v) and v else '—'
            )
            col_config['email']      = st.column_config.TextColumn('Email')
            col_config['rate_fmt']   = st.column_config.TextColumn('Rate (₫)', width=100)
            col_config['start_date'] = st.column_config.DateColumn('Start')
            col_config['end_date']   = st.column_config.DateColumn('End')
            col_config['notes']      = st.column_config.TextColumn('Notes')

        # Hide raw columns
        hide_cols = ['id', 'employee_id', 'role', 'allocation_percent', 'daily_rate',
                     'is_active', 'task_count', 'overdue_count', 'avg_completion',
                     'total_est_hours', 'total_actual_hours', 'done_count']
        for c in hide_cols:
            if c in display.columns:
                col_config[c] = None

        event = st.dataframe(
            display,
            key=f"mem_tbl_{st.session_state.get('_mem_tbl_key', 0)}",
            width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            column_config=col_config,
        )

        # ── Selection → permission-gated actions ──
        sel = event.selection.rows
        if sel:
            selected_mem = display.iloc[sel[0]]
            selected_mem_id = int(selected_mem['id'])
            sel_emp_id = int(selected_mem['employee_id'])

            st.markdown(
                f"**Selected:** {selected_mem['member_name']} — "
                f"{selected_mem['role_label']} ({selected_mem['alloc_fmt']})"
            )

            cols = []
            col_count = 1  # View workload always available for PM

            if perms['can_manage_team']:
                col_count = 4
            elif perms['tier'] in ('manager', 'lead'):
                col_count = 2

            action_cols = st.columns(list([1] * col_count) + [max(0, 7 - col_count)])

            col_idx = 0

            # Edit — PM only
            if perms['can_manage_team']:
                if action_cols[col_idx].button("✏️ Edit", type="primary", use_container_width=True, key="mem_edit"):
                    st.session_state["open_edit_member"] = selected_mem_id
                    st.rerun()
                col_idx += 1

            # Workload — PM can view anyone, others only own
            can_view_wl = perms['tier'] == 'manager' or sel_emp_id == employee_id
            if can_view_wl:
                if action_cols[col_idx].button("📊 Workload", use_container_width=True, key="mem_workload"):
                    st.session_state["open_workload_emp"] = sel_emp_id
                    st.rerun()
                col_idx += 1

            # Remove — PM only
            if perms['can_manage_team']:
                if action_cols[col_idx].button("🗑 Remove", use_container_width=True, key="mem_remove"):
                    st.session_state["_confirm_remove"] = selected_mem_id
                col_idx += 1

            # Deselect
            if perms['can_manage_team']:
                if action_cols[col_idx].button("✖ Deselect", use_container_width=True, key="mem_desel"):
                    st.session_state["_mem_tbl_key"] = st.session_state.get("_mem_tbl_key", 0) + 1
                    st.rerun()

            # Confirm removal dialog
            if st.session_state.get("_confirm_remove") == selected_mem_id:
                st.warning(f"Are you sure you want to remove **{selected_mem['member_name']}** from this project?")
                rc1, rc2, _ = st.columns([1, 1, 5])
                if rc1.button("✅ Yes, remove", type="primary", key="confirm_rm"):
                    if remove_member(selected_mem_id, user_id):
                        st.success(f"Removed {selected_mem['member_name']}.")
                        invalidate_wbs_cache(selected_project_id)
                        st.session_state.pop("_confirm_remove", None)
                        st.rerun()
                if rc2.button("❌ Cancel", key="cancel_rm"):
                    st.session_state.pop("_confirm_remove", None)
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: WORKLOAD MATRIX (Phase 3 — PM + Lead)
# ══════════════════════════════════════════════════════════════════════════════

if 'workload' in tab_map:
    with tab_map['workload']:
        st.caption("Resource allocation across all active projects for this team.")

        v = st.session_state.get(f'_wbs_v_{selected_project_id}', 0)
        matrix_df = _cached_workload_matrix(selected_project_id, _v=v)

        if matrix_df.empty:
            st.info("No workload data available. Add active members first.")
        else:
            # Pivot: rows = member, columns = project, values = allocation%
            pivot = matrix_df.pivot_table(
                index=['employee_id', 'member_name', 'current_role'],
                columns='project_code',
                values='allocation_percent',
                aggfunc='sum',
                fill_value=0,
            ).reset_index()

            # Calculate total per member
            project_cols = [c for c in pivot.columns if c not in ('employee_id', 'member_name', 'current_role')]
            pivot['TOTAL'] = pivot[project_cols].sum(axis=1)

            # Status indicator
            def _alloc_status(total):
                if total > 100:
                    return '🔴 Over'
                elif total > 80:
                    return '🟡 Near'
                else:
                    return '🟢 OK'

            pivot['Status'] = pivot['TOTAL'].apply(_alloc_status)
            pivot['role_label'] = pivot['current_role'].map(lambda r: MEMBER_ROLE_LABELS.get(r, r))

            # Format for display
            display_wl = pivot.copy()
            for col in project_cols:
                display_wl[col] = display_wl[col].apply(lambda v: f"{v:.0f}%" if v > 0 else '—')
            display_wl['TOTAL'] = display_wl['TOTAL'].apply(lambda v: f"{v:.0f}%")

            # Build column config
            wl_col_config = {
                'member_name': st.column_config.TextColumn('Name'),
                'role_label':  st.column_config.TextColumn('Role', width=120),
            }
            for col in project_cols:
                wl_col_config[col] = st.column_config.TextColumn(col, width=90)
            wl_col_config['TOTAL']  = st.column_config.TextColumn('TOTAL', width=80)
            wl_col_config['Status'] = st.column_config.TextColumn('Status', width=80)

            # Hide internal columns
            wl_col_config['employee_id'] = None
            wl_col_config['current_role'] = None

            st.dataframe(
                display_wl, width="stretch", hide_index=True,
                column_config=wl_col_config,
            )

            # Summary
            over_count = len(pivot[pivot[project_cols].sum(axis=1) > 100])
            if over_count > 0:
                st.warning(f"⚠️ **{over_count} member(s)** are over-allocated (>100% total). Consider rebalancing.")
            else:
                st.success("✅ All members are within capacity.")

            # Quick access to individual workload
            if perms['tier'] == 'manager':
                st.divider()
                st.caption("Click a member to see detailed breakdown:")
                wl_emp_opts = [e['full_name'] for e in employees]
                default_idx = next((i for i, e in enumerate(employees) if e['id'] == employee_id), 0)
                wl_emp_sel = st.selectbox("Employee", wl_emp_opts, index=default_idx, key="wl_emp_sel")
                wl_emp_id = employees[wl_emp_opts.index(wl_emp_sel)]['id']
                if st.button("📊 View Detailed Workload", key="wl_detail"):
                    st.session_state["open_workload_emp"] = wl_emp_id
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: COST SUMMARY (Phase 4 — PM only)
# ══════════════════════════════════════════════════════════════════════════════

if 'cost' in tab_map:
    with tab_map['cost']:
        st.caption("Estimated team cost based on daily rates and allocation. Working days = 22/month.")

        cost_rows = compute_cost_summary(enriched)

        if not cost_rows:
            st.info("No cost data available. Set daily rates in member profiles.")
        else:
            cost_df = pd.DataFrame(cost_rows)

            # Display table
            st.dataframe(
                cost_df, width="stretch", hide_index=True,
                column_config={
                    'role_label':   st.column_config.TextColumn('Role'),
                    'count':        st.column_config.NumberColumn('Members', width=80),
                    'avg_rate':     st.column_config.NumberColumn('Avg Rate (₫/day)', format="%.0f"),
                    'total_alloc':  st.column_config.NumberColumn('Total Alloc %', format="%.0f%%"),
                    'est_monthly':  st.column_config.NumberColumn('Est. Monthly (₫)', format="%.0f"),
                    'role': None,
                },
            )

            # Totals
            total_members = sum(r['count'] for r in cost_rows)
            total_monthly = sum(r['est_monthly'] for r in cost_rows)
            total_alloc_all = sum(r['total_alloc'] for r in cost_rows)

            tc1, tc2, tc3 = st.columns(3)
            tc1.metric("Total Members", total_members)
            tc2.metric("Total Allocation", f"{total_alloc_all:.0f}%")
            tc3.metric("Est. Monthly Cost", fmt_vnd(total_monthly))

            # Budget context from project
            if proj_info and proj_info.get('contract_value'):
                contract = float(proj_info['contract_value'])
                if contract > 0 and total_monthly > 0:
                    months_budget = contract / total_monthly
                    st.info(f"💰 At current rate, team cost covers **{months_budget:.1f} months** of the contract value ({fmt_vnd(contract)}).")


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

    cc_ids, cc_emails = render_cc_selector(employees, key_prefix="member_create")

    if cancelled:
        st.rerun()
    if submitted:
        try:
            # Duplicate check
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
# DIALOG TRIGGERS — Permission-checked
# ══════════════════════════════════════════════════════════════════════════════

if st.session_state.pop("open_create_member_7", False) and perms['can_manage_team']:
    _dialog_create_member()

if "open_edit_member" in st.session_state:
    mid = st.session_state.pop("open_edit_member")
    if perms['can_manage_team']:
        _dialog_edit_member(mid)

if "open_workload_emp" in st.session_state:
    eid = st.session_state.pop("open_workload_emp")
    # PM can view anyone, others only own
    if perms['tier'] == 'manager' or eid == employee_id:
        _dialog_workload(eid)