# utils/il_project/wbs_notify.py
"""
Email Notification for WBS / Task Management workflow.

Uses same infrastructure as email_notify.py:
  - SMTP via Gmail (smtp.gmail.com:587)
  - App password from .env (OUTBOUND_EMAIL_SENDER / OUTBOUND_EMAIL_PASSWORD)
  - Feature flag: ENABLE_EMAIL_NOTIFICATIONS

Triggers:
  1. Task Assigned     → email to assignee (new task or reassign)
  2. Member Added      → email to new team member
  3. Task BLOCKED      → email to PM
  4. Task COMPLETED    → email to PM

All sends are non-blocking: failures are logged but never crash the app.
"""

import logging
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# REUSE _send_email and _base_template from email_notify.py
# ══════════════════════════════════════════════════════════════════════
# Import core email plumbing — avoids duplicating SMTP logic.

from .email_notify import (
    _send_email,
    _base_template,
    _info_row,
    _is_configured,
    _merge_cc,
)


# ══════════════════════════════════════════════════════════════════════
# DEEP LINK BUILDER
# ══════════════════════════════════════════════════════════════════════

def _get_base_url() -> str:
    try:
        from ..config import config
        return (config.get_app_setting('APP_BASE_URL', '') or '').rstrip('/')
    except Exception:
        return ''


def build_wbs_deep_link(project_id: int, task_id: Optional[int] = None) -> Optional[str]:
    """
    Build deep link to WBS page, optionally opening a specific task.
    Example: https://app.example.com/IL_6_%F0%9F%93%8B_WBS?project_id=42&task_id=123
    Returns None if base URL not configured.
    """
    base = _get_base_url()
    if not base:
        return None
    page_path = 'IL_6_%F0%9F%93%8B_WBS'
    url = f"{base}/{page_path}?project_id={project_id}"
    if task_id:
        url += f"&task_id={task_id}"
    return url


def build_team_deep_link(project_id: int) -> Optional[str]:
    """Build deep link to Team page for a project."""
    base = _get_base_url()
    if not base:
        return None
    page_path = 'IL_7_%F0%9F%91%A5_Team'
    return f"{base}/{page_path}?project_id={project_id}"


# ══════════════════════════════════════════════════════════════════════
# LOOKUP HELPERS (lightweight — only fetch what we need for email)
# ══════════════════════════════════════════════════════════════════════

def _get_employee_email(employee_id: int) -> Optional[str]:
    """Get employee email by ID."""
    try:
        from ..db import execute_query
        rows = execute_query(
            "SELECT email FROM employees WHERE id = :id AND delete_flag = 0",
            {'id': employee_id},
        )
        return rows[0]['email'] if rows else None
    except Exception as e:
        logger.warning(f"Could not get email for employee {employee_id}: {e}")
        return None


def _get_employee_name(employee_id: int) -> str:
    """Get employee full name by ID."""
    try:
        from ..db import execute_query
        rows = execute_query(
            "SELECT CONCAT(first_name, ' ', last_name) AS name FROM employees WHERE id = :id",
            {'id': employee_id},
        )
        return rows[0]['name'] if rows else f"Employee #{employee_id}"
    except Exception:
        return f"Employee #{employee_id}"


def _get_pm_for_project(project_id: int) -> Optional[Dict]:
    """Get PM employee_id, name, email for a project."""
    try:
        from ..db import execute_query
        rows = execute_query("""
            SELECT p.pm_employee_id,
                   CONCAT(e.first_name, ' ', e.last_name) AS pm_name,
                   e.email AS pm_email
            FROM il_projects p
            JOIN employees e ON p.pm_employee_id = e.id
            WHERE p.id = :pid AND p.delete_flag = 0
        """, {'pid': project_id})
        return rows[0] if rows else None
    except Exception as e:
        logger.warning(f"Could not get PM for project {project_id}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════
# 1. TASK ASSIGNED → email to assignee
# ══════════════════════════════════════════════════════════════════════

def notify_task_assigned(
    task_id: int,
    task_name: str,
    wbs_code: str,
    project_code: str,
    project_name: str,
    project_id: int,
    assignee_id: int,
    assigned_by_name: str,
    priority: str = 'NORMAL',
    planned_start: Optional[str] = None,
    planned_end: Optional[str] = None,
    description: Optional[str] = None,
    phase_name: Optional[str] = None,
    is_reassign: bool = False,
) -> bool:
    """
    Send notification when a task is assigned/reassigned to an engineer.

    Args:
        task_id: Task ID
        task_name: Task name
        wbs_code: WBS code (e.g. "3.2.1")
        project_code: Project code
        project_name: Project name
        project_id: Project ID (for deep link)
        assignee_id: Employee ID of the assignee
        assigned_by_name: Name of person who assigned
        priority: Task priority
        planned_start: Planned start date (string)
        planned_end: Planned end date / deadline (string)
        description: Task description (optional)
        phase_name: Phase name (optional)
        is_reassign: True if this is a reassignment (not first assign)
    """
    if not _is_configured():
        return False

    assignee_email = _get_employee_email(assignee_id)
    assignee_name  = _get_employee_name(assignee_id)
    if not assignee_email:
        logger.warning(f"No email for assignee {assignee_id} — skipping task notification.")
        return False

    priority_badge = {
        'CRITICAL': '🔴 CRITICAL', 'HIGH': '🟠 HIGH',
        'NORMAL': '🔵 Normal', 'LOW': '🟢 Low',
    }.get(priority, priority)

    action = "reassigned to you" if is_reassign else "assigned to you"
    subject_prefix = "[Task Reassigned]" if is_reassign else "[New Task]"

    desc_block = ''
    if description:
        desc_block = f'''
        <div style="background:#f0f9ff;border-left:3px solid #3b82f6;padding:12px;margin:16px 0;font-size:13px;">
            <strong>Description:</strong> {description[:300]}{'...' if len(description) > 300 else ''}
        </div>'''

    body = f'''
    <p>Hi <strong>{assignee_name}</strong>,</p>
    <p>A task has been {action}:</p>

    <table style="width:100%;margin:16px 0;">
        {_info_row('Task', f'<strong>[{wbs_code or "—"}] {task_name}</strong>')}
        {_info_row('Project', f'{project_code} — {project_name}')}
        {_info_row('Phase', phase_name or '—')}
        {_info_row('Priority', priority_badge)}
        {_info_row('Deadline', str(planned_end) if planned_end else '—')}
        {_info_row('Assigned by', assigned_by_name)}
    </table>

    {desc_block}

    <p style="color:#6b7280;font-size:13px;">
        Please log in to the ERP to review the task details and start working on it.
    </p>'''

    # CC the PM
    pm_info = _get_pm_for_project(project_id)
    pm_email = pm_info['pm_email'] if pm_info else None

    app_url = build_wbs_deep_link(project_id, task_id)

    return _send_email(
        to_emails=[assignee_email],
        subject=f"{subject_prefix} [{wbs_code or '—'}] {task_name} — {project_code}",
        html_body=_base_template(f"Task {'Reassigned' if is_reassign else 'Assigned'}", body, app_url),
        cc_emails=_merge_cc(pm_email, exclude=[assignee_email]),
    )


# ══════════════════════════════════════════════════════════════════════
# 2. MEMBER ADDED → email to new team member
# ══════════════════════════════════════════════════════════════════════

def notify_member_added(
    project_code: str,
    project_name: str,
    project_id: int,
    employee_id: int,
    role: str,
    allocation_percent: float,
    added_by_name: str,
    pm_name: Optional[str] = None,
) -> bool:
    """
    Send notification when an employee is added to a project team.
    """
    if not _is_configured():
        return False

    member_email = _get_employee_email(employee_id)
    member_name  = _get_employee_name(employee_id)
    if not member_email:
        logger.warning(f"No email for employee {employee_id} — skipping member notification.")
        return False

    role_label = {
        'PROJECT_MANAGER': 'Project Manager', 'SOLUTION_ARCHITECT': 'Solution Architect',
        'ENGINEER': 'Engineer', 'SENIOR_ENGINEER': 'Senior Engineer',
        'SITE_ENGINEER': 'Site Engineer', 'FAE': 'FAE',
        'SALES': 'Sales', 'SUBCONTRACTOR': 'Subcontractor', 'OTHER': 'Other',
    }.get(role, role)

    body = f'''
    <p>Hi <strong>{member_name}</strong>,</p>
    <p>You have been added to a project team:</p>

    <table style="width:100%;margin:16px 0;">
        {_info_row('Project', f'<strong>{project_code} — {project_name}</strong>')}
        {_info_row('Your Role', role_label)}
        {_info_row('Allocation', f'{allocation_percent:.0f}%')}
        {_info_row('PM', pm_name or '—')}
        {_info_row('Added by', added_by_name)}
    </table>

    <p style="color:#6b7280;font-size:13px;">
        You can now access this project in the ERP system. Tasks will be assigned to you via the WBS page.
    </p>'''

    app_url = build_team_deep_link(project_id)

    return _send_email(
        to_emails=[member_email],
        subject=f"[Team] You've been added to {project_code} — {project_name}",
        html_body=_base_template("Added to Project Team", body, app_url),
    )


# ══════════════════════════════════════════════════════════════════════
# 3. TASK BLOCKED → email to PM
# ══════════════════════════════════════════════════════════════════════

def notify_task_blocked(
    task_id: int,
    task_name: str,
    wbs_code: str,
    project_code: str,
    project_name: str,
    project_id: int,
    blocked_by_id: int,
    blocker_reason: Optional[str] = None,
) -> bool:
    """
    Send notification to PM when a task is marked BLOCKED.
    This is a critical alert — PM needs to act.
    """
    if not _is_configured():
        return False

    pm_info = _get_pm_for_project(project_id)
    if not pm_info or not pm_info.get('pm_email'):
        logger.warning(f"No PM email for project {project_id} — skipping BLOCKED notification.")
        return False

    blocker_name = _get_employee_name(blocked_by_id)

    reason_block = ''
    if blocker_reason:
        reason_block = f'''
        <div style="background:#fef2f2;border-left:3px solid #ef4444;padding:12px;margin:16px 0;font-size:13px;">
            <strong>Blocker:</strong> {blocker_reason}
        </div>'''

    body = f'''
    <p>Hi <strong>{pm_info['pm_name']}</strong>,</p>
    <p>A task has been marked as <strong style="color:#dc2626;">BLOCKED</strong> and needs your attention:</p>

    <table style="width:100%;margin:16px 0;">
        {_info_row('Task', f'<strong>[{wbs_code or "—"}] {task_name}</strong>')}
        {_info_row('Project', f'{project_code} — {project_name}')}
        {_info_row('Blocked by', blocker_name)}
        {_info_row('Status', '<span style="color:#dc2626;font-weight:700;">🔴 BLOCKED</span>')}
    </table>

    {reason_block}

    <p style="color:#6b7280;font-size:13px;">
        Please review the blocker and take action to unblock the task.
    </p>'''

    app_url = build_wbs_deep_link(project_id, task_id)

    return _send_email(
        to_emails=[pm_info['pm_email']],
        subject=f"🔴 [BLOCKED] [{wbs_code or '—'}] {task_name} — {project_code}",
        html_body=_base_template("Task Blocked — Action Required", body, app_url),
    )


# ══════════════════════════════════════════════════════════════════════
# 4. TASK COMPLETED → email to PM
# ══════════════════════════════════════════════════════════════════════

def notify_task_completed(
    task_id: int,
    task_name: str,
    wbs_code: str,
    project_code: str,
    project_name: str,
    project_id: int,
    completed_by_id: int,
    actual_hours: Optional[float] = None,
    phase_name: Optional[str] = None,
    phase_completion: Optional[float] = None,
    project_completion: Optional[float] = None,
) -> bool:
    """
    Send notification to PM when a task is completed.
    Includes phase and project completion progress for context.
    """
    if not _is_configured():
        return False

    pm_info = _get_pm_for_project(project_id)
    if not pm_info or not pm_info.get('pm_email'):
        logger.warning(f"No PM email for project {project_id} — skipping COMPLETED notification.")
        return False

    completed_by_name = _get_employee_name(completed_by_id)

    progress_block = ''
    if phase_completion is not None or project_completion is not None:
        items = []
        if phase_name and phase_completion is not None:
            items.append(f"Phase ({phase_name}): <strong>{phase_completion:.0f}%</strong>")
        if project_completion is not None:
            items.append(f"Project overall: <strong>{project_completion:.0f}%</strong>")
        if items:
            progress_block = f'''
            <div style="background:#f0fdf4;border-left:3px solid #22c55e;padding:12px;margin:16px 0;font-size:13px;">
                📊 <strong>Progress update:</strong><br>
                {'<br>'.join(items)}
            </div>'''

    body = f'''
    <p>Hi <strong>{pm_info['pm_name']}</strong>,</p>
    <p>A task has been marked as <strong style="color:#16a34a;">COMPLETED</strong>:</p>

    <table style="width:100%;margin:16px 0;">
        {_info_row('Task', f'<strong>[{wbs_code or "—"}] {task_name}</strong>')}
        {_info_row('Project', f'{project_code} — {project_name}')}
        {_info_row('Phase', phase_name or '—')}
        {_info_row('Completed by', completed_by_name)}
        {_info_row('Actual Hours', f'{actual_hours:.1f}h' if actual_hours else '—')}
        {_info_row('Status', '<span style="color:#16a34a;font-weight:700;">✅ COMPLETED</span>')}
    </table>

    {progress_block}'''

    app_url = build_wbs_deep_link(project_id, task_id)

    return _send_email(
        to_emails=[pm_info['pm_email']],
        subject=f"✅ [Completed] [{wbs_code or '—'}] {task_name} — {project_code}",
        html_body=_base_template("Task Completed", body, app_url),
    )


# ══════════════════════════════════════════════════════════════════════
# CONVENIENCE — auto-detect and send from task update context
# ══════════════════════════════════════════════════════════════════════

def notify_on_task_status_change(
    task_id: int,
    old_status: str,
    new_status: str,
    changed_by_id: int,
    blocker_reason: Optional[str] = None,
) -> bool:
    """
    Auto-send the right notification based on status transition.
    Call this from quick_update_task() or update_task() after save.

    Only fires for: BLOCKED → notify PM, COMPLETED → notify PM.
    Other transitions are logged but no email sent.

    Returns True if email was sent (or not needed), False on error.
    """
    if old_status == new_status:
        return True  # No change — nothing to send

    if new_status not in ('BLOCKED', 'COMPLETED'):
        return True  # No email trigger for this transition

    try:
        from .wbs_queries import get_task
        task = get_task(task_id)
        if not task:
            logger.warning(f"notify_on_task_status_change: task {task_id} not found")
            return False

        from ..db import execute_query
        proj_rows = execute_query(
            "SELECT project_code, project_name FROM il_projects WHERE id = :pid",
            {'pid': task['project_id']},
        )
        proj = proj_rows[0] if proj_rows else {}

        if new_status == 'BLOCKED':
            return notify_task_blocked(
                task_id=task_id,
                task_name=task['task_name'],
                wbs_code=task.get('wbs_code', ''),
                project_code=proj.get('project_code', ''),
                project_name=proj.get('project_name', ''),
                project_id=task['project_id'],
                blocked_by_id=changed_by_id,
                blocker_reason=blocker_reason,
            )

        if new_status == 'COMPLETED':
            # Fetch latest completion percentages for context
            phase_completion = None
            phase_name = task.get('phase_name')
            if task.get('phase_id'):
                ph_rows = execute_query(
                    "SELECT completion_percent FROM il_project_phases WHERE id = :pid AND delete_flag = 0",
                    {'pid': task['phase_id']},
                )
                if ph_rows:
                    phase_completion = ph_rows[0]['completion_percent']

            proj_completion = None
            pc_rows = execute_query(
                "SELECT overall_completion_percent FROM il_projects WHERE id = :pid",
                {'pid': task['project_id']},
            )
            if pc_rows:
                proj_completion = pc_rows[0].get('overall_completion_percent')

            return notify_task_completed(
                task_id=task_id,
                task_name=task['task_name'],
                wbs_code=task.get('wbs_code', ''),
                project_code=proj.get('project_code', ''),
                project_name=proj.get('project_name', ''),
                project_id=task['project_id'],
                completed_by_id=changed_by_id,
                actual_hours=task.get('actual_hours'),
                phase_name=phase_name,
                phase_completion=phase_completion,
                project_completion=proj_completion,
            )

    except Exception as e:
        logger.error(f"notify_on_task_status_change failed: {e}")
        return False

    return True


def notify_on_task_assign(
    task_id: int,
    old_assignee_id: Optional[int],
    new_assignee_id: Optional[int],
    assigned_by_id: int,
) -> bool:
    """
    Auto-send assignment notification when assignee changes.
    Call this from create_task() or update_task() after save.

    Fires when:
    - new_assignee_id is set and differs from old_assignee_id
    - Skips if assignee unchanged or removed (set to None)

    Returns True if email sent (or not needed), False on error.
    """
    if not new_assignee_id:
        return True  # Unassigned — nothing to send
    if old_assignee_id == new_assignee_id:
        return True  # No change

    try:
        from .wbs_queries import get_task
        task = get_task(task_id)
        if not task:
            return False

        from ..db import execute_query
        proj_rows = execute_query(
            "SELECT project_code, project_name FROM il_projects WHERE id = :pid",
            {'pid': task['project_id']},
        )
        proj = proj_rows[0] if proj_rows else {}

        assigned_by_name = _get_employee_name(assigned_by_id)

        return notify_task_assigned(
            task_id=task_id,
            task_name=task['task_name'],
            wbs_code=task.get('wbs_code', ''),
            project_code=proj.get('project_code', ''),
            project_name=proj.get('project_name', ''),
            project_id=task['project_id'],
            assignee_id=new_assignee_id,
            assigned_by_name=assigned_by_name,
            priority=task.get('priority', 'NORMAL'),
            planned_start=str(task.get('planned_start') or ''),
            planned_end=str(task.get('planned_end') or ''),
            description=task.get('description'),
            phase_name=task.get('phase_name'),
            is_reassign=(old_assignee_id is not None),
        )

    except Exception as e:
        logger.error(f"notify_on_task_assign failed: {e}")
        return False
