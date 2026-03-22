# utils/il_project/wbs_helpers.py
"""
Constants, display helpers, shared UI components, and performance utilities
for WBS module.

v3.0 — Enhanced:
  - Added render_cc_selector() — shared UI to pick extra CC recipients for notifications
  - log_perf() decorator for query timing
  - render_attachments() shared UI component (DRY across pages 8/9)
  - Cache invalidation helpers (targeted, not global clear)
"""

import time
import functools
import logging
from typing import Dict, List, Optional, Tuple
import pandas as pd

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# PERFORMANCE LOGGING
# ══════════════════════════════════════════════════════════════════════════════

def log_perf(func):
    """Decorator: log execution time and row count for DB functions."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        result = func(*args, **kwargs)
        ms = (time.perf_counter() - t0) * 1000
        # Detect row count from result type
        if hasattr(result, '__len__'):
            rows = len(result)
        elif result is None:
            rows = 0
        else:
            rows = '?'
        logger.info(f"[PERF] {func.__name__}: {ms:.0f}ms ({rows} rows)")
        return result
    return wrapper


# ══════════════════════════════════════════════════════════════════════════════
# CACHE INVALIDATION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def invalidate_wbs_cache(project_id: int):
    """
    Increment version counter for WBS bootstrap cache.
    Next call to _cached_wbs_data(project_id, _v=new_version) → cache miss → fresh data.
    Also invalidates My Tasks cache for all employees.
    """
    import streamlit as st
    k = f'_wbs_v_{project_id}'
    st.session_state[k] = st.session_state.get(k, 0) + 1
    # Also bump My Tasks version (cross-project)
    st.session_state['_mytasks_v'] = st.session_state.get('_mytasks_v', 0) + 1


def invalidate_execution_cache(project_id: int):
    """Increment version counter for Execution (Issues/Risks/CO) bootstrap cache."""
    import streamlit as st
    k = f'_exec_v_{project_id}'
    st.session_state[k] = st.session_state.get(k, 0) + 1


def invalidate_progress_cache(project_id: int):
    """Increment version counter for Progress/Quality bootstrap cache."""
    import streamlit as st
    k = f'_prog_v_{project_id}'
    st.session_state[k] = st.session_state.get(k, 0) + 1


# ══════════════════════════════════════════════════════════════════════════════
# DISPLAY CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

TASK_STATUS_OPTIONS: List[str] = [
    'NOT_STARTED', 'IN_PROGRESS', 'COMPLETED', 'ON_HOLD', 'BLOCKED', 'CANCELLED',
]

TASK_STATUS_ICONS: Dict[str, str] = {
    'NOT_STARTED': '⚪',
    'IN_PROGRESS': '🔵',
    'COMPLETED':   '✅',
    'ON_HOLD':     '⏸️',
    'BLOCKED':     '🔴',
    'CANCELLED':   '❌',
}

PHASE_STATUS_OPTIONS: List[str] = [
    'NOT_STARTED', 'IN_PROGRESS', 'COMPLETED', 'ON_HOLD', 'CANCELLED',
]

PRIORITY_OPTIONS: List[str] = ['LOW', 'NORMAL', 'HIGH', 'CRITICAL']

PRIORITY_ICONS: Dict[str, str] = {
    'LOW':      '🟢',
    'NORMAL':   '🔵',
    'HIGH':     '🟠',
    'CRITICAL': '🔴',
}

MEMBER_ROLES: List[str] = [
    'PROJECT_MANAGER', 'SOLUTION_ARCHITECT', 'ENGINEER', 'SENIOR_ENGINEER',
    'SITE_ENGINEER', 'FAE', 'SALES', 'SUBCONTRACTOR', 'OTHER',
]

MEMBER_ROLE_LABELS: Dict[str, str] = {
    'PROJECT_MANAGER':    'Project Manager',
    'SOLUTION_ARCHITECT': 'Solution Architect',
    'ENGINEER':           'Engineer',
    'SENIOR_ENGINEER':    'Senior Engineer',
    'SITE_ENGINEER':      'Site Engineer',
    'FAE':                'FAE',
    'SALES':              'Sales',
    'SUBCONTRACTOR':      'Subcontractor',
    'OTHER':              'Other',
}

# ══════════════════════════════════════════════════════════════════════════════
# ROLE-BASED PERMISSIONS (Phase 1 v3.0)
# ══════════════════════════════════════════════════════════════════════════════

ROLE_TIERS: Dict[str, str] = {
    # Tier 1: Full project control
    'PROJECT_MANAGER':    'manager',
    # Tier 2: Can create tasks, assign within scope
    'SOLUTION_ARCHITECT': 'lead',
    'SENIOR_ENGINEER':    'lead',
    # Tier 3: Own tasks, quick update
    'ENGINEER':           'member',
    'SITE_ENGINEER':      'member',
    'FAE':                'member',
    # Tier 4: Read-only + own tasks
    'SALES':              'viewer',
    # Tier 5: Restricted — own tasks only
    'SUBCONTRACTOR':      'restricted',
    'OTHER':              'viewer',
}

# Permission matrix per tier
_TIER_PERMISSIONS: Dict[str, Dict[str, bool]] = {
    'manager': {
        'can_manage_phases': True,   # create/edit/delete phase, load template
        'can_create_tasks':  True,
        'can_edit_any_task': True,   # full edit on ANY task
        'can_assign_tasks':  True,   # assign/reassign to anyone
        'can_delete':        True,   # delete phase/task
        'can_see_all_tasks': True,
        'can_manage_team':   True,
        'can_quick_update_any': True,
        'show_dashboard':    True,
        'show_phases_tab':   True,
        'show_all_tasks_tab': True,
        'show_team_tab':     True,
        'default_tab_index': 0,      # Dashboard
    },
    'lead': {
        'can_manage_phases': False,
        'can_create_tasks':  True,
        'can_edit_any_task': False,   # only own tasks
        'can_assign_tasks':  True,
        'can_delete':        False,
        'can_see_all_tasks': True,
        'can_manage_team':   False,
        'can_quick_update_any': False,
        'show_dashboard':    True,
        'show_phases_tab':   True,   # read-only
        'show_all_tasks_tab': True,
        'show_team_tab':     True,   # read-only
        'default_tab_index': 0,      # Dashboard
    },
    'member': {
        'can_manage_phases': False,
        'can_create_tasks':  False,
        'can_edit_any_task': False,
        'can_assign_tasks':  False,
        'can_delete':        False,
        'can_see_all_tasks': True,   # can see, not edit
        'can_manage_team':   False,
        'can_quick_update_any': False,
        'show_dashboard':    False,
        'show_phases_tab':   False,
        'show_all_tasks_tab': True,  # read-only on others' tasks
        'show_team_tab':     False,
        'default_tab_index': 0,      # My Tasks (first visible tab)
    },
    'viewer': {
        'can_manage_phases': False,
        'can_create_tasks':  False,
        'can_edit_any_task': False,
        'can_assign_tasks':  False,
        'can_delete':        False,
        'can_see_all_tasks': True,
        'can_manage_team':   False,
        'can_quick_update_any': False,
        'show_dashboard':    True,
        'show_phases_tab':   False,
        'show_all_tasks_tab': True,  # read-only
        'show_team_tab':     False,
        'default_tab_index': 0,      # Dashboard
    },
    'restricted': {
        'can_manage_phases': False,
        'can_create_tasks':  False,
        'can_edit_any_task': False,
        'can_assign_tasks':  False,
        'can_delete':        False,
        'can_see_all_tasks': False,  # only own tasks
        'can_manage_team':   False,
        'can_quick_update_any': False,
        'show_dashboard':    False,
        'show_phases_tab':   False,
        'show_all_tasks_tab': False,
        'show_team_tab':     False,
        'default_tab_index': 0,      # My Tasks only
    },
}


def resolve_project_role(
    members_df,  # pd.DataFrame from wbs['members']
    employee_id: Optional[int],
    is_admin: bool = False,
) -> Dict:
    """
    Resolve current user's role and permissions for THIS project.

    Lookup employee_id in members_df → get highest-tier role → derive permissions.
    Admin users always get 'manager' tier regardless of project membership.
    Non-members get 'viewer' tier (can see but not modify).

    Returns dict with:
        role, tier, is_pm, is_member, + all boolean permissions from _TIER_PERMISSIONS
    """
    import pandas as pd

    result = {
        'role': None,
        'tier': 'viewer',
        'is_pm': False,
        'is_member': False,
    }

    # Admin override → manager tier
    if is_admin:
        result['tier'] = 'manager'
        result['is_pm'] = True
        result['is_member'] = True
        result['role'] = 'ADMIN'
        result.update(_TIER_PERMISSIONS['manager'])
        return result

    # Lookup in project members
    if employee_id and not members_df.empty and 'employee_id' in members_df.columns:
        my_memberships = members_df[members_df['employee_id'] == employee_id]
        if not my_memberships.empty:
            result['is_member'] = True
            # Pick highest-tier role (lowest rank in tier hierarchy)
            tier_rank = {'manager': 0, 'lead': 1, 'member': 2, 'viewer': 3, 'restricted': 4}
            best_tier = 'restricted'
            best_role = None
            for _, row in my_memberships.iterrows():
                role = row.get('role', 'OTHER')
                tier = ROLE_TIERS.get(role, 'viewer')
                if tier_rank.get(tier, 9) < tier_rank.get(best_tier, 9):
                    best_tier = tier
                    best_role = role
            result['role'] = best_role
            result['tier'] = best_tier
            result['is_pm'] = (best_role == 'PROJECT_MANAGER')
        # Non-member: stays at 'viewer' tier (read-only guest)

    # Apply tier permissions
    result.update(_TIER_PERMISSIONS.get(result['tier'], _TIER_PERMISSIONS['viewer']))
    return result


def can_edit_task(perms: Dict, task_assignee_id: Optional[int], employee_id: Optional[int]) -> bool:
    """Check if user can edit a specific task (full edit)."""
    if perms.get('can_edit_any_task'):
        return True
    # Lead/member/restricted can edit own tasks
    if employee_id and task_assignee_id == employee_id:
        return perms['tier'] in ('lead', 'member')
    return False


def can_quick_update_task(perms: Dict, task_assignee_id: Optional[int], employee_id: Optional[int]) -> bool:
    """Check if user can quick-update a specific task."""
    if perms.get('can_quick_update_any'):
        return True
    # Own task: lead/member/restricted can quick-update
    if employee_id and task_assignee_id == employee_id:
        return perms['tier'] in ('lead', 'member', 'restricted')
    return False


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD COMPUTATION (Phase 2 v3.0) — All client-side, zero DB queries
# ══════════════════════════════════════════════════════════════════════════════

def compute_dashboard_kpis(task_df, phases_df, proj_info: Dict) -> Dict:
    """
    Compute dashboard KPIs from cached bootstrap data.
    Cost: ~0ms (pandas operations on cached DataFrames).
    """
    import pandas as pd
    from datetime import date

    today = date.today()
    active = task_df[~task_df['status'].isin(['CANCELLED'])] if not task_df.empty else task_df

    total = len(active)
    completed = len(active[active['status'] == 'COMPLETED']) if total else 0

    overdue = 0
    blocked = 0
    due_this_week = 0
    unassigned = 0

    if total > 0:
        blocked = int((active['status'] == 'BLOCKED').sum())
        not_done = active[~active['status'].isin(['COMPLETED', 'CANCELLED'])]

        if 'planned_end' in not_done.columns:
            has_due = not_done[not_done['planned_end'].notna()]
            if not has_due.empty:
                due_dates = pd.to_datetime(has_due['planned_end']).dt.date
                overdue = int((due_dates < today).sum())
                week_end = today + pd.Timedelta(days=7)
                due_this_week = int(((due_dates >= today) & (due_dates <= week_end)).sum())

        if 'assignee_id' in not_done.columns:
            unassigned = int(not_done['assignee_id'].isna().sum())

    overall_pct = float(proj_info.get('overall_completion_percent') or 0)

    return {
        'total_tasks':    total,
        'completed':      completed,
        'overdue':        overdue,
        'blocked':        blocked,
        'due_this_week':  due_this_week,
        'unassigned':     unassigned,
        'overall_pct':    overall_pct,
        'completion_rate': f"{completed}/{total}" if total else "0/0",
    }


def compute_action_items(
    task_df,
    employee_id: Optional[int],
    role_tier: str,
) -> List[Dict]:
    """
    Compute role-specific action items from cached task data.
    Returns list of dicts sorted by severity (critical → high → medium).
    Cost: ~0ms.
    """
    import pandas as pd
    from datetime import date

    today = date.today()
    items: List[Dict] = []

    if task_df.empty:
        return items

    active = task_df[~task_df['status'].isin(['COMPLETED', 'CANCELLED'])].copy()
    if active.empty:
        return items

    # Parse planned_end to date for comparison
    if 'planned_end' in active.columns:
        active['_due'] = pd.to_datetime(active['planned_end'], errors='coerce').dt.date
    else:
        active['_due'] = None

    if role_tier in ('manager', 'lead'):
        # ── PM/Lead: project-wide action items ──

        # 1. Blocked tasks → critical
        blocked = active[active['status'] == 'BLOCKED']
        for _, t in blocked.iterrows():
            items.append({
                'type': 'blocked', 'severity': 'critical', 'icon': '🔴',
                'task_id': int(t['id']),
                'wbs_code': t.get('wbs_code', ''),
                'task_name': t['task_name'],
                'assignee': t.get('assignee_name', '—'),
                'message': "BLOCKED — needs unblock or escalation",
                'actions': ['view', 'edit', 'comment'],
            })

        # 2. Overdue tasks → high
        has_due = active[active['_due'].notna()]
        overdue = has_due[has_due['_due'] < today].sort_values('_due')
        for _, t in overdue.iterrows():
            days_late = (today - t['_due']).days
            items.append({
                'type': 'overdue', 'severity': 'high', 'icon': '⏰',
                'task_id': int(t['id']),
                'wbs_code': t.get('wbs_code', ''),
                'task_name': t['task_name'],
                'assignee': t.get('assignee_name', '—'),
                'message': f"Overdue by {days_late} day{'s' if days_late != 1 else ''}",
                'actions': ['view', 'quick_update', 'edit'],
            })

        # 3. Unassigned tasks → medium (PM only)
        if role_tier == 'manager':
            unassigned = active[active['assignee_id'].isna()]
            for _, t in unassigned.iterrows():
                items.append({
                    'type': 'unassigned', 'severity': 'medium', 'icon': '❓',
                    'task_id': int(t['id']),
                    'wbs_code': t.get('wbs_code', ''),
                    'task_name': t['task_name'],
                    'assignee': '(Unassigned)',
                    'message': "Needs assignee",
                    'actions': ['edit'],
                })

        # 4. Due this week → medium
        if not has_due.empty:
            week_end = today + pd.Timedelta(days=7)
            due_soon = has_due[(has_due['_due'] >= today) & (has_due['_due'] <= week_end)]
            due_soon = due_soon[due_soon['status'] != 'BLOCKED']  # already listed above
            for _, t in due_soon.sort_values('_due').iterrows():
                days_left = (t['_due'] - today).days
                label = "Due today" if days_left == 0 else f"Due in {days_left}d"
                items.append({
                    'type': 'due_soon', 'severity': 'medium', 'icon': '📋',
                    'task_id': int(t['id']),
                    'wbs_code': t.get('wbs_code', ''),
                    'task_name': t['task_name'],
                    'assignee': t.get('assignee_name', '—'),
                    'message': label,
                    'actions': ['view', 'quick_update'],
                })

    else:
        # ── Member/Viewer/Restricted: own tasks only ──
        if employee_id:
            my = active[active['assignee_id'] == employee_id].copy()
        else:
            my = pd.DataFrame()

        if not my.empty:
            # 1. My blocked tasks
            my_blocked = my[my['status'] == 'BLOCKED']
            for _, t in my_blocked.iterrows():
                items.append({
                    'type': 'my_blocked', 'severity': 'critical', 'icon': '🔴',
                    'task_id': int(t['id']),
                    'wbs_code': t.get('wbs_code', ''),
                    'task_name': t['task_name'],
                    'assignee': 'You',
                    'message': "Your task is BLOCKED — update PM on status",
                    'actions': ['view', 'quick_update', 'comment'],
                })

            # 2. My overdue
            my_has_due = my[my['_due'].notna()]
            my_overdue = my_has_due[my_has_due['_due'] < today]
            for _, t in my_overdue.sort_values('_due').iterrows():
                days_late = (today - t['_due']).days
                items.append({
                    'type': 'my_overdue', 'severity': 'high', 'icon': '⏰',
                    'task_id': int(t['id']),
                    'wbs_code': t.get('wbs_code', ''),
                    'task_name': t['task_name'],
                    'assignee': 'You',
                    'message': f"Overdue by {days_late}d — update progress or flag blocker",
                    'actions': ['quick_update', 'comment'],
                })

            # 3. My NOT_STARTED (newly assigned)
            my_new = my[my['status'] == 'NOT_STARTED']
            for _, t in my_new.iterrows():
                items.append({
                    'type': 'my_new', 'severity': 'medium', 'icon': '🆕',
                    'task_id': int(t['id']),
                    'wbs_code': t.get('wbs_code', ''),
                    'task_name': t['task_name'],
                    'assignee': 'You',
                    'message': "Not started — set to IN_PROGRESS when you begin",
                    'actions': ['quick_update', 'view'],
                })

            # 4. My due this week
            if not my_has_due.empty:
                week_end = today + pd.Timedelta(days=7)
                my_soon = my_has_due[
                    (my_has_due['_due'] >= today) & (my_has_due['_due'] <= week_end) &
                    (~my_has_due['status'].isin(['BLOCKED']))
                ]
                for _, t in my_soon.sort_values('_due').iterrows():
                    days_left = (t['_due'] - today).days
                    label = "Due today" if days_left == 0 else f"Due in {days_left}d"
                    items.append({
                        'type': 'my_due_soon', 'severity': 'medium', 'icon': '📋',
                        'task_id': int(t['id']),
                        'wbs_code': t.get('wbs_code', ''),
                        'task_name': t['task_name'],
                        'assignee': 'You',
                        'message': label,
                        'actions': ['quick_update', 'view'],
                    })

    # Sort: critical → high → medium
    sev_order = {'critical': 0, 'high': 1, 'medium': 2}
    items.sort(key=lambda x: sev_order.get(x['severity'], 9))
    return items


# ══════════════════════════════════════════════════════════════════════════════
# TEAM ENRICHMENT & ALERTS (Phase 2-4 for Page 7 v3.0)
# ══════════════════════════════════════════════════════════════════════════════

def enrich_members_with_tasks(members_df, tasks_df) -> 'pd.DataFrame':
    """
    Add task stats per member from cached bootstrap data.
    Columns added: task_count, overdue_count, avg_completion, total_est_hours, total_actual_hours
    Cost: ~0ms (pandas groupby on cached DataFrames).
    """
    import pandas as pd
    from datetime import date

    if members_df.empty:
        return members_df

    result = members_df.copy()
    # Init default columns
    for col in ['task_count', 'overdue_count', 'avg_completion', 'total_est_hours', 'total_actual_hours']:
        result[col] = 0
    result['avg_completion'] = result['avg_completion'].astype(float)

    if tasks_df.empty or 'assignee_id' not in tasks_df.columns:
        return result

    active = tasks_df[~tasks_df['status'].isin(['COMPLETED', 'CANCELLED'])].copy()
    if active.empty:
        return result

    today = date.today()

    # Task count per assignee
    counts = active.groupby('assignee_id')['id'].count().rename('task_count')

    # Overdue count
    if 'planned_end' in active.columns:
        has_due = active[active['planned_end'].notna()].copy()
        if not has_due.empty:
            has_due['_overdue'] = pd.to_datetime(has_due['planned_end']).dt.date < today
            overdue = has_due.groupby('assignee_id')['_overdue'].sum().rename('overdue_count')
        else:
            overdue = pd.Series(dtype=float, name='overdue_count')
    else:
        overdue = pd.Series(dtype=float, name='overdue_count')

    # Avg completion
    avg_comp = active.groupby('assignee_id')['completion_percent'].mean().rename('avg_completion')

    # Hours
    est_h = active.groupby('assignee_id')['estimated_hours'].sum().rename('total_est_hours')
    act_h = active.groupby('assignee_id')['actual_hours'].sum().rename('total_actual_hours')

    # Merge all stats
    stats = pd.concat([counts, overdue, avg_comp, est_h, act_h], axis=1).reset_index()
    stats.columns = ['assignee_id', 'task_count', 'overdue_count', 'avg_completion', 'total_est_hours', 'total_actual_hours']
    stats = stats.fillna(0)

    # Also count completed tasks
    completed = tasks_df[tasks_df['status'] == 'COMPLETED']
    if not completed.empty:
        done_counts = completed.groupby('assignee_id')['id'].count().rename('done_count').reset_index()
        stats = stats.merge(done_counts, on='assignee_id', how='left')
        stats['done_count'] = stats['done_count'].fillna(0)
    else:
        stats['done_count'] = 0

    # Drop default columns and merge enriched ones
    result = result.drop(columns=['task_count', 'overdue_count', 'avg_completion',
                                   'total_est_hours', 'total_actual_hours'], errors='ignore')
    result = result.merge(stats, left_on='employee_id', right_on='assignee_id', how='left')
    result = result.drop(columns=['assignee_id'], errors='ignore')

    # Fill NaN for members with no tasks
    for col in ['task_count', 'overdue_count', 'avg_completion', 'total_est_hours', 'total_actual_hours', 'done_count']:
        if col in result.columns:
            result[col] = result[col].fillna(0)

    return result


def compute_team_alerts(enriched_df) -> List[Dict]:
    """
    Generate actionable alerts about team health for PM.
    Input: enriched members DataFrame (from enrich_members_with_tasks).
    """
    alerts: List[Dict] = []

    if enriched_df.empty:
        return alerts

    active_members = enriched_df
    if 'is_active' in enriched_df.columns:
        active_members = enriched_df[enriched_df['is_active'] == 1]

    # Members with overdue tasks
    if 'overdue_count' in active_members.columns:
        overdue = active_members[active_members['overdue_count'] > 0]
        for _, m in overdue.iterrows():
            alerts.append({
                'type': 'overdue', 'severity': 'high', 'icon': '⏰',
                'member': m.get('member_name', '—'),
                'role': MEMBER_ROLE_LABELS.get(m.get('role', ''), m.get('role', '')),
                'message': f"has {int(m['overdue_count'])} overdue task(s) — follow up",
            })

    # Active members with 0 tasks (idle)
    if 'task_count' in active_members.columns:
        idle = active_members[active_members['task_count'] == 0]
        for _, m in idle.iterrows():
            alerts.append({
                'type': 'idle', 'severity': 'medium', 'icon': '💤',
                'member': m.get('member_name', '—'),
                'role': MEMBER_ROLE_LABELS.get(m.get('role', ''), m.get('role', '')),
                'message': "has 0 active tasks — consider assigning work",
            })

    # Inactive members still on roster
    if 'is_active' in enriched_df.columns:
        inactive = enriched_df[enriched_df['is_active'] == 0]
        for _, m in inactive.iterrows():
            alerts.append({
                'type': 'inactive', 'severity': 'low', 'icon': '⚪',
                'member': m.get('member_name', '—'),
                'role': MEMBER_ROLE_LABELS.get(m.get('role', ''), m.get('role', '')),
                'message': "is inactive — consider removing from project",
            })

    # Check if PM role exists
    if 'role' in enriched_df.columns:
        has_pm = (enriched_df['role'] == 'PROJECT_MANAGER').any()
        if not has_pm:
            alerts.insert(0, {
                'type': 'no_pm', 'severity': 'high', 'icon': '🔴',
                'member': '—', 'role': '—',
                'message': "No PM assigned to this project!",
            })

    sev_order = {'high': 0, 'medium': 1, 'low': 2}
    alerts.sort(key=lambda x: sev_order.get(x['severity'], 9))
    return alerts


def compute_cost_summary(members_df, working_days: int = 22) -> List[Dict]:
    """
    Compute cost summary grouped by role.
    Est. monthly cost = daily_rate × allocation% / 100 × working_days.
    """
    import pandas as pd

    if members_df.empty:
        return []

    active = members_df
    if 'is_active' in members_df.columns:
        active = members_df[members_df['is_active'] == 1]

    if active.empty or 'role' not in active.columns:
        return []

    rows = []
    for role, grp in active.groupby('role'):
        count = len(grp)
        avg_rate = grp['daily_rate'].mean() if grp['daily_rate'].notna().any() else 0
        total_alloc = grp['allocation_percent'].sum() if 'allocation_percent' in grp.columns else 0
        est_monthly = avg_rate * (total_alloc / 100) * working_days

        rows.append({
            'role': role,
            'role_label': MEMBER_ROLE_LABELS.get(role, role),
            'count': count,
            'avg_rate': avg_rate,
            'total_alloc': total_alloc,
            'est_monthly': est_monthly,
        })

    # Sort by role hierarchy
    role_order = {r: i for i, r in enumerate(MEMBER_ROLES)}
    rows.sort(key=lambda x: role_order.get(x['role'], 99))
    return rows


DEPENDENCY_TYPES: List[str] = ['FS', 'FF', 'SS', 'SF']

DEPENDENCY_LABELS: Dict[str, str] = {
    'FS': 'Finish → Start',
    'FF': 'Finish → Finish',
    'SS': 'Start → Start',
    'SF': 'Start → Finish',
}

# Standard phase templates for quick setup
DEFAULT_PHASE_TEMPLATES: List[Dict] = [
    {'code': 'PRESALES',       'name': 'Pre-Sales / Site Survey',     'weight': 5},
    {'code': 'DESIGN',         'name': 'Design & Engineering',        'weight': 15},
    {'code': 'PROCUREMENT',    'name': 'Procurement',                 'weight': 10},
    {'code': 'IMPLEMENTATION', 'name': 'Implementation / Installation', 'weight': 35},
    {'code': 'COMMISSIONING',  'name': 'Commissioning & FAT',         'weight': 20},
    {'code': 'TRAINING',       'name': 'Training & Handover',         'weight': 10},
    {'code': 'WARRANTY',       'name': 'Warranty Support',            'weight': 5},
]


# ══════════════════════════════════════════════════════════════════════════════
# FORMATTING HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def fmt_status(status: str) -> str:
    """Format task/phase status with icon."""
    icon = TASK_STATUS_ICONS.get(status, '⚪')
    return f"{icon} {status}"


def fmt_priority(priority: str) -> str:
    """Format priority with icon."""
    icon = PRIORITY_ICONS.get(priority, '🔵')
    return f"{icon} {priority}"


def fmt_completion(pct) -> str:
    """Format completion percentage with progress indicator."""
    if pct is None:
        return '—'
    try:
        p = float(pct)
        if p >= 100:
            return '✅ 100%'
        if p >= 75:
            return f'🟢 {p:.0f}%'
        if p >= 50:
            return f'🟡 {p:.0f}%'
        if p > 0:
            return f'🟠 {p:.0f}%'
        return '⚪ 0%'
    except (TypeError, ValueError):
        return '—'


def fmt_hours(hours) -> str:
    """Format hours with 1 decimal."""
    if hours is None:
        return '—'
    try:
        return f"{float(hours):.1f}h"
    except (TypeError, ValueError):
        return '—'


def comment_type_icon(ctype: str) -> str:
    """Icon for comment type."""
    return {
        'COMMENT':         '💬',
        'STATUS_CHANGE':   '🔄',
        'PROGRESS_UPDATE': '📊',
        'BLOCKER':         '🚧',
    }.get(ctype, '💬')


# ══════════════════════════════════════════════════════════════════════════════
# SHARED UI COMPONENT — Email CC/TO Selector
# ══════════════════════════════════════════════════════════════════════════════

def render_cc_selector(
    employees: List[Dict],
    key_prefix: str,
    label: str = "📧 Notification CC",
    help_text: str = "Select additional people to notify about this action.",
    show_manual_email: bool = True,
) -> Tuple[List[int], List[str]]:
    """
    Shared CC selector widget for CRUD dialogs.
    Place OUTSIDE st.form (multiselect needs to be interactive).

    Returns:
        (cc_employee_ids, cc_manual_emails)
        Pass directly to notify_* functions as extra_cc_ids / extra_cc_emails.

    Usage in dialog:
        # OUTSIDE the form, before or after submit logic:
        cc_ids, cc_emails = render_cc_selector(employees, key_prefix="task_create")
        # Then pass to notify function:
        notify_on_task_assign(..., extra_cc_ids=cc_ids, extra_cc_emails=cc_emails)
    """
    import streamlit as st

    with st.expander(label, expanded=False):
        st.caption(help_text)

        # Employee multiselect
        emp_options = [e['full_name'] for e in employees]
        selected_names = st.multiselect(
            "CC team members",
            options=emp_options,
            default=[],
            key=f"_cc_emp_{key_prefix}",
            placeholder="Search by name...",
        )

        cc_ids = []
        for name in selected_names:
            match = next((e for e in employees if e['full_name'] == name), None)
            if match:
                cc_ids.append(match['id'])

        cc_emails = []
        if show_manual_email:
            manual = st.text_input(
                "CC external emails (comma-separated)",
                key=f"_cc_manual_{key_prefix}",
                placeholder="email1@company.com, email2@company.com",
                help="For people not in the employee list.",
            )
            if manual.strip():
                cc_emails = [
                    e.strip()
                    for e in manual.split(',')
                    if e.strip() and '@' in e.strip()
                ]

        total_cc = len(cc_ids) + len(cc_emails)
        if total_cc > 0:
            names = selected_names + cc_emails
            st.caption(f"📤 Will CC {total_cc} additional recipient(s): {', '.join(names)}")

    return cc_ids, cc_emails


# ══════════════════════════════════════════════════════════════════════════════
# SHARED UI COMPONENT — Attachments (Pattern A: junction → medias)
# ══════════════════════════════════════════════════════════════════════════════

def render_attachments(entity_type: str, entity_id: int, project_id: int, user_id: str):
    """
    Shared attachment list + upload widget.
    Call inside View dialog, OUTSIDE st.form.

    Used by: Issues (page 8), Risks, Change Orders, Progress Reports,
    Quality Checklists (page 9), and Tasks (page 6 files tab).

    Requires: streamlit, wbs_execution_queries
    """
    import streamlit as st
    from .wbs_execution_queries import (
        get_entity_medias, upload_and_attach, unlink_media, get_attachment_url,
    )

    files = get_entity_medias(entity_type, entity_id)

    if files:
        st.markdown(f"**📎 Attachments ({len(files)})**")
        for f in files:
            fc1, fc2 = st.columns([5, 1])
            url = get_attachment_url(f['s3_key'])
            label = f['file_name'] or 'file'
            desc = f" — {f['description']}" if f.get('description') else ''
            if url:
                fc1.markdown(f"📄 [{label}]({url}){desc}")
            else:
                fc1.caption(f"📄 {label}{desc}")
            if fc2.button("🗑", key=f"_rm_{entity_type}_{f['junction_id']}"):
                unlink_media(entity_type, f['junction_id'])
                st.rerun()
    else:
        st.caption("No files attached.")

    uploaded = st.file_uploader(
        "Attach file", type=['pdf', 'png', 'jpg', 'jpeg', 'xlsx', 'docx'],
        key=f"_upload_{entity_type}_{entity_id}",
    )
    if uploaded:
        desc = st.text_input("Description (optional)", key=f"_desc_{entity_type}_{entity_id}")
        if st.button("📤 Upload", key=f"_do_upload_{entity_type}_{entity_id}"):
            ok = upload_and_attach(
                entity_type, entity_id, project_id,
                uploaded.getvalue(), uploaded.name,
                description=desc.strip() or None, created_by=user_id,
            )
            if ok:
                st.success(f"✅ Attached: {uploaded.name}")
                st.rerun()
            else:
                st.error("Upload failed.")