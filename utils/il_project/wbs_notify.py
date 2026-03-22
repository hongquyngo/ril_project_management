# utils/il_project/wbs_notify.py
"""
Email Notification for WBS / Task Management workflow.

v3.1 — COALESCE fix + name resolution:
  - _resolve_person: COALESCE(employees.email, users.email) + CONCAT_WS
  - _get_project_context: same COALESCE for PM email
  - notify_task_assigned: PM fallback when assignee has no email
  - Diagnostic logging with 📧 prefix at every checkpoint

v3.0 — Enhanced notifications:
  - Fixed deep links: configurable page slugs + proper URL encoding
  - Always CC the performer (person who triggered the action)
  - Extra CC/TO support (from UI cc_selector widget)
  - User-friendly content: full names everywhere (fix "Employee #51" bug)
  - Action Required section per trigger type
  - performer_id uses employee_id (NOT user_id) to resolve names correctly
  - 2 new triggers: Issue Created, CO Status Changed

Uses same infrastructure as email_notify.py:
  - SMTP via Gmail (smtp.gmail.com:587)
  - App password from .env (OUTBOUND_EMAIL_SENDER / OUTBOUND_EMAIL_PASSWORD)
  - Feature flag: ENABLE_EMAIL_NOTIFICATIONS

Triggers:
  1. Task Assigned     → TO: assignee | CC: PM + performer + watchers
  2. Member Added      → TO: member   | CC: PM + performer
  3. Task BLOCKED      → TO: PM       | CC: assignee + performer
  4. Task COMPLETED    → TO: PM       | CC: assignee + performer
  5. Issue Created     → TO: assigned  | CC: PM + performer + reporter  (NEW)
  6. CO Status Changed → TO: requester | CC: PM + performer + approver  (NEW)

All sends are non-blocking: failures are logged but never crash the app.
"""

_WBS_NOTIFY_VERSION = '3.2'  # ← removed employee_code column reference

import logging
from typing import List, Optional, Dict
from urllib.parse import quote

logger = logging.getLogger(__name__)
logger.info(f"📧 wbs_notify module loaded — version {_WBS_NOTIFY_VERSION}")


# ══════════════════════════════════════════════════════════════════════
# REUSE core email plumbing from email_notify.py
# ══════════════════════════════════════════════════════════════════════

from .email_notify import (
    _send_email,
    _base_template,
    _info_row,
    _is_configured,
    _merge_cc,
)


# ══════════════════════════════════════════════════════════════════════
# DEEP LINK BUILDER — Configurable page slugs
# ══════════════════════════════════════════════════════════════════════
# Streamlit multipage routing: {base_url}/{page_slug}?params
#
# Page slugs are derived from filenames in pages/ directory.
# If Streamlit URL routing changes or filenames are renamed,
# update ONLY this dict — all deep links auto-update.
#
# Pattern follows email_notify.py: build_pr_deep_link() → IL_5_🛒_Purchase_Request

_PAGE_SLUGS = {
    'wbs':      'IL_6_📋_WBS',
    'team':     'IL_7_👥_Team',
    'issues':   'IL_8_⚠️_Issues',
    'progress': 'IL_9_📊_Progress',
}


def _get_base_url() -> str:
    try:
        from ..config import config
        return (config.get_app_setting('APP_BASE_URL', '') or '').rstrip('/')
    except Exception:
        return ''


def _build_deep_link(page_key: str, **params) -> Optional[str]:
    """
    Build deep link URL for any WBS page.

    Uses urllib.parse.quote() to properly encode the emoji in page slugs.
    This matches how browsers encode URLs — Streamlit receives the decoded
    UTF-8 path and routes correctly.

    Args:
        page_key: Key in _PAGE_SLUGS (e.g. 'wbs', 'team', 'issues')
        **params: Query parameters (project_id=4, task_id=2, etc.)

    Returns:
        Full URL string, or None if base URL not configured.

    Example:
        _build_deep_link('wbs', project_id=4, task_id=2)
        → https://ril-projects.streamlit.app/IL_6_%F0%9F%93%8B_WBS?project_id=4&task_id=2
    """
    base = _get_base_url()
    if not base:
        return None

    slug = _PAGE_SLUGS.get(page_key)
    if not slug:
        logger.warning(f"Unknown page_key: {page_key}")
        return None

    # URL-encode the slug (handles emoji → %F0%9F%93%8B etc.)
    # safe='_' keeps underscores unencoded for readability
    encoded_slug = quote(slug, safe='_')

    # Build query string
    query_parts = [f"{k}={v}" for k, v in params.items() if v is not None]
    query = '&'.join(query_parts)

    url = f"{base}/{encoded_slug}"
    if query:
        url += f"?{query}"
    return url


def build_wbs_deep_link(project_id: int, task_id: Optional[int] = None) -> Optional[str]:
    """Build deep link to WBS page, optionally opening a specific task."""
    return _build_deep_link('wbs', project_id=project_id, task_id=task_id)


def build_team_deep_link(project_id: int) -> Optional[str]:
    """Build deep link to Team page."""
    return _build_deep_link('team', project_id=project_id)


def build_issues_deep_link(project_id: int) -> Optional[str]:
    """Build deep link to Issues page."""
    return _build_deep_link('issues', project_id=project_id)


# ══════════════════════════════════════════════════════════════════════
# PERSON RESOLVER — Single source of truth for name + email
# ══════════════════════════════════════════════════════════════════════
# Why this exists: the old code used _get_employee_name(user_id) which
# resolved the auth user ID, not the employee ID — producing
# "Employee #51" in emails. This resolver uses employee_id exclusively.

def _resolve_person(employee_id: Optional[int]) -> Optional[Dict]:
    """
    Resolve employee to {id, name, email, code}.
    Returns None if not found or employee_id is None.

    Email resolution (priority order):
      1. employees.email (primary)
      2. users.email WHERE users.employee_id = :id (fallback)

    This ensures contractors/customers who have a users account
    but no email in the employees table still get notifications.
    """
    if not employee_id:
        return None
    try:
        from ..db import execute_query
        rows = execute_query("""
            SELECT e.id,
                   NULLIF(TRIM(CONCAT_WS(' ', e.first_name, e.last_name)), '') AS full_name,
                   COALESCE(NULLIF(TRIM(e.email), ''), u.email) AS email,
                   u.username
            FROM employees e
            LEFT JOIN users u
                ON u.employee_id = e.id
                AND u.delete_flag = 0
                AND u.is_active = 1
            WHERE e.id = :id AND e.delete_flag = 0
            LIMIT 1
        """, {'id': employee_id})
        if rows:
            r = rows[0]
            result = {
                'id': r['id'],
                'name': r['full_name'] or r.get('username') or f"Employee #{employee_id}",
                'email': r.get('email'),
                'code': '',
            }
            logger.info(f"📧 _resolve_person({employee_id}) → name='{result['name']}', email='{result['email']}'")
            return result
        logger.warning(f"📧 _resolve_person({employee_id}) → no rows found in employees table")
        return None
    except Exception as e:
        logger.warning(f"📧 _resolve_person({employee_id}) EXCEPTION: {e}", exc_info=True)
        return None


def _resolve_persons(employee_ids: List[int]) -> List[Dict]:
    """Resolve multiple employees. Skips None/invalid IDs."""
    return [p for eid in (employee_ids or []) if (p := _resolve_person(eid))]


# ══════════════════════════════════════════════════════════════════════
# PROJECT CONTEXT — Rich project info for emails
# ══════════════════════════════════════════════════════════════════════

def _get_project_context(project_id: int) -> Dict:
    """
    Get project details + PM info in one query.
    PM email: employees.email → fallback users.email.
    """
    try:
        from ..db import execute_query
        rows = execute_query("""
            SELECT p.project_code, p.project_name, p.pm_employee_id,
                   NULLIF(TRIM(CONCAT_WS(' ', e.first_name, e.last_name)), '') AS pm_name,
                   COALESCE(NULLIF(TRIM(e.email), ''), u.email) AS pm_email
            FROM il_projects p
            LEFT JOIN employees e ON p.pm_employee_id = e.id
            LEFT JOIN users u
                ON u.employee_id = p.pm_employee_id
                AND u.delete_flag = 0
                AND u.is_active = 1
            WHERE p.id = :pid AND p.delete_flag = 0
            LIMIT 1
        """, {'pid': project_id})
        if rows:
            r = rows[0]
            return {
                'project_code': r.get('project_code', ''),
                'project_name': r.get('project_name', ''),
                'pm_id': r.get('pm_employee_id'),
                'pm_name': r.get('pm_name', '—'),
                'pm_email': r.get('pm_email'),
            }
        return {}
    except Exception as e:
        logger.warning(f"_get_project_context({project_id}) failed: {e}")
        return {}


# ══════════════════════════════════════════════════════════════════════
# CC LIST BUILDER — Always include performer + dedup
# ══════════════════════════════════════════════════════════════════════

def _build_cc_list(
    performer_id: Optional[int] = None,
    pm_email: Optional[str] = None,
    extra_person_ids: Optional[List[int]] = None,
    extra_emails: Optional[List[str]] = None,
    exclude_emails: Optional[List[str]] = None,
) -> List[str]:
    """
    Build deduplicated CC list. Always includes:
    1. Performer (person who did the action) ← KEY FIX: was missing before
    2. PM
    3. Extra CCs from UI selector (employee IDs or raw emails)

    Excludes any email already in TO list (pass via exclude_emails).
    """
    cc_set: set = set()
    exclude = set(e.lower() for e in (exclude_emails or []) if e)

    # 1. Performer — ALWAYS CC'd
    if performer_id:
        performer = _resolve_person(performer_id)
        if performer and performer.get('email'):
            cc_set.add(performer['email'].lower())

    # 2. PM
    if pm_email:
        cc_set.add(pm_email.lower())

    # 3. Extra CC from employee IDs (from UI cc_selector widget)
    for p in _resolve_persons(extra_person_ids or []):
        if p.get('email'):
            cc_set.add(p['email'].lower())

    # 4. Extra CC from raw emails (manual input in UI)
    for email in (extra_emails or []):
        if email and '@' in email:
            cc_set.add(email.strip().lower())

    # Remove anyone already in TO list
    cc_set -= exclude

    return sorted(cc_set)


# ══════════════════════════════════════════════════════════════════════
# ACTION REQUIRED BLOCK — Actionable emails
# ══════════════════════════════════════════════════════════════════════

def _action_required_block(items: List[str], title: str = "Action Required") -> str:
    """Render an Action Required section with checkbox-style items."""
    if not items:
        return ''
    li_html = ''.join(
        f'<li style="margin:6px 0;color:#1f2937;">{item}</li>'
        for item in items
    )
    return f'''
    <div style="background:#fffbeb;border-left:4px solid #f59e0b;padding:14px 16px;margin:20px 0;border-radius:0 6px 6px 0;">
        <p style="margin:0 0 8px;font-weight:700;color:#92400e;font-size:14px;">
            🎯 {title}
        </p>
        <ul style="margin:0;padding-left:20px;font-size:13px;">
            {li_html}
        </ul>
    </div>'''


# ══════════════════════════════════════════════════════════════════════
# FORMATTING HELPERS — User-friendly display
# ══════════════════════════════════════════════════════════════════════

def _fmt_project(ctx: Dict) -> str:
    """Format: 'IL-2026-051-010 — Watson Thailand AMR' """
    code = ctx.get('project_code', '')
    name = ctx.get('project_name', '')
    if code and name:
        return f"<strong>{code}</strong> — {name}"
    return code or name or '—'


def _fmt_person(name: Optional[str], role: Optional[str] = None) -> str:
    """Format: 'Quý Ngô (PM)' or 'Hiệp Phạm' """
    if not name or name.startswith('Employee #'):
        return '—'
    return f"{name} ({role})" if role else name


def _fmt_priority_badge(priority: str) -> str:
    return {
        'CRITICAL': '<span style="color:#dc2626;font-weight:700;">🔴 CRITICAL</span>',
        'HIGH':     '<span style="color:#ea580c;font-weight:700;">🟠 HIGH</span>',
        'NORMAL':   '🔵 Normal',
        'LOW':      '🟢 Low',
    }.get(priority, priority)


def _fmt_date(d) -> str:
    if not d:
        return '—'
    return str(d)


# ══════════════════════════════════════════════════════════════════════
# 1. TASK ASSIGNED → TO: assignee | CC: PM + performer + watchers
# ══════════════════════════════════════════════════════════════════════

def notify_task_assigned(
    task_id: int,
    task_name: str,
    wbs_code: str,
    project_id: int,
    assignee_id: int,
    performer_id: int,
    priority: str = 'NORMAL',
    planned_start=None,
    planned_end=None,
    description: Optional[str] = None,
    phase_name: Optional[str] = None,
    is_reassign: bool = False,
    extra_cc_ids: Optional[List[int]] = None,
    extra_cc_emails: Optional[List[str]] = None,
) -> bool:
    """
    Notify assignee when a task is assigned/reassigned.

    v2 → v3 changes:
      - performer_id replaces assigned_by_name (resolves server-side)
      - performer always CC'd
      - PM always CC'd
      - extra CC from UI selector
      - Action Required section added
    """
    if not _is_configured():
        logger.warning(f"📧 [SKIP] notify_task_assigned(task={task_id}): email not configured — check ENABLE_EMAIL_NOTIFICATIONS + EMAIL_SENDER/PASSWORD in .env")
        return False

    assignee = _resolve_person(assignee_id)
    performer = _resolve_person(performer_id)
    ctx = _get_project_context(project_id)

    # ── Determine TO recipient — fallback to PM if assignee has no email ──
    _assignee_no_email = False
    if not assignee:
        logger.warning(f"📧 [FALLBACK] notify_task_assigned(task={task_id}): _resolve_person({assignee_id}) returned None — employee not found in DB")
        _assignee_no_email = True
    elif not assignee.get('email'):
        logger.warning(f"📧 [FALLBACK] notify_task_assigned(task={task_id}): assignee '{assignee.get('name')}' (id={assignee_id}) has NO EMAIL in employees table")
        _assignee_no_email = True

    if _assignee_no_email:
        # Fallback: send to PM instead, so CC recipients (performer, extras) still get notified
        if ctx.get('pm_email'):
            logger.info(f"📧 [SEND] notify_task_assigned(task={task_id}): TO=PM ({ctx['pm_email']}) — assignee has no email, CC will still receive")
            to_emails = [ctx['pm_email']]
            greeting_name = ctx.get('pm_name', 'PM')
        else:
            logger.warning(f"📧 [SKIP] notify_task_assigned(task={task_id}): assignee has no email AND no PM email — cannot send to anyone")
            return False
    else:
        logger.info(f"📧 [SEND] notify_task_assigned(task={task_id}): TO={assignee['email']}, project={ctx.get('project_code','?')}")
        to_emails = [assignee['email']]
        greeting_name = assignee['name']

    performer_name = _fmt_person(
        performer['name'] if performer else None,
        'PM' if performer and ctx.get('pm_id') == performer_id else None,
    )

    action = "reassigned to you" if is_reassign else "assigned to you"
    subject_prefix = "[Task Reassigned]" if is_reassign else "[New Task]"

    # If fallback to PM, adjust email content
    if _assignee_no_email:
        assignee_display = assignee['name'] if assignee else f"Employee #{assignee_id}"
        action = f"assigned to <strong>{assignee_display}</strong> (⚠️ no email on file)"
        subject_prefix = "[New Task — Assignee No Email]" if not is_reassign else "[Task Reassigned — Assignee No Email]"

    desc_block = ''
    if description:
        desc_block = f'''
        <div style="background:#f0f9ff;border-left:3px solid #3b82f6;padding:12px;margin:16px 0;font-size:13px;">
            <strong>Description:</strong><br>{description[:500]}{'...' if len(description) > 500 else ''}
        </div>'''

    actions = [
        "Review the task details and description",
        "Confirm the timeline is achievable — flag concerns to PM",
        "Update status to <strong>IN_PROGRESS</strong> when you begin",
        "Log actual hours regularly via Quick Update",
    ]
    if _assignee_no_email:
        actions.insert(0, f"⚠️ <strong>Assignee has no email</strong> — please add their email to the employee record")
    if planned_end:
        actions.append(f"Complete by <strong>{_fmt_date(planned_end)}</strong>")

    body = f'''
    <p>Hi <strong>{greeting_name}</strong>,</p>
    <p>A task has been {action}:</p>

    <table style="width:100%;margin:16px 0;">
        {_info_row('Task', f'<strong>[{wbs_code or "—"}] {task_name}</strong>')}
        {_info_row('Project', _fmt_project(ctx))}
        {_info_row('Phase', phase_name or '—')}
        {_info_row('Priority', _fmt_priority_badge(priority))}
        {_info_row('Planned', f'{_fmt_date(planned_start)} → {_fmt_date(planned_end)}')}
        {_info_row('Assigned by', performer_name)}
        {_info_row('Project Manager', _fmt_person(ctx.get('pm_name')))}
    </table>

    {desc_block}
    {_action_required_block(actions)}'''

    cc_emails = _build_cc_list(
        performer_id=performer_id,
        pm_email=ctx.get('pm_email'),
        extra_person_ids=extra_cc_ids,
        extra_emails=extra_cc_emails,
        exclude_emails=to_emails,
    )

    app_url = build_wbs_deep_link(project_id, task_id)

    return _send_email(
        to_emails=to_emails,
        subject=f"{subject_prefix} [{wbs_code or '—'}] {task_name} — {ctx.get('project_code', '')}",
        html_body=_base_template(
            f"Task {'Reassigned' if is_reassign else 'Assigned'}", body, app_url
        ),
        cc_emails=cc_emails,
    )


# ══════════════════════════════════════════════════════════════════════
# 2. MEMBER ADDED → TO: member | CC: PM + performer
# ══════════════════════════════════════════════════════════════════════

def notify_member_added(
    project_code: str,
    project_name: str,
    project_id: int,
    employee_id: int,
    role: str,
    allocation_percent: float,
    performer_id: int,
    pm_name: Optional[str] = None,
    extra_cc_ids: Optional[List[int]] = None,
    extra_cc_emails: Optional[List[str]] = None,
) -> bool:
    """
    Notify new team member.

    v2 → v3 changes:
      - added_by_name → performer_id (resolved server-side)
      - PM now CC'd (was missing)
      - Action Required section
    """
    if not _is_configured():
        return False

    member = _resolve_person(employee_id)
    performer = _resolve_person(performer_id)
    ctx = _get_project_context(project_id)

    if not member or not member.get('email'):
        logger.warning(f"No email for employee {employee_id} — skipping.")
        return False

    role_label = {
        'PROJECT_MANAGER': 'Project Manager', 'SOLUTION_ARCHITECT': 'Solution Architect',
        'ENGINEER': 'Engineer', 'SENIOR_ENGINEER': 'Senior Engineer',
        'SITE_ENGINEER': 'Site Engineer', 'FAE': 'FAE',
        'SALES': 'Sales', 'SUBCONTRACTOR': 'Subcontractor', 'OTHER': 'Other',
    }.get(role, role)

    actions = [
        "Log in to ERP to view your project details",
        "Review the project scope, timeline, and deliverables",
        "Await task assignments from the Project Manager",
        "Update availability if allocation conflicts with other projects",
    ]

    body = f'''
    <p>Hi <strong>{member['name']}</strong>,</p>
    <p>You have been added to a project team:</p>

    <table style="width:100%;margin:16px 0;">
        {_info_row('Project', _fmt_project(ctx))}
        {_info_row('Your Role', f'<strong>{role_label}</strong>')}
        {_info_row('Allocation', f'{allocation_percent:.0f}%')}
        {_info_row('Project Manager', _fmt_person(ctx.get('pm_name')))}
        {_info_row('Added by', _fmt_person(performer['name'] if performer else None))}
    </table>

    {_action_required_block(actions)}'''

    to_emails = [member['email']]
    cc_emails = _build_cc_list(
        performer_id=performer_id,
        pm_email=ctx.get('pm_email'),
        extra_person_ids=extra_cc_ids,
        extra_emails=extra_cc_emails,
        exclude_emails=to_emails,
    )

    app_url = build_team_deep_link(project_id)

    return _send_email(
        to_emails=to_emails,
        subject=f"[Team] You've been added to {ctx.get('project_code', project_code)} — {ctx.get('project_name', project_name)}",
        html_body=_base_template("Added to Project Team", body, app_url),
        cc_emails=cc_emails,
    )


# ══════════════════════════════════════════════════════════════════════
# 3. TASK BLOCKED → TO: PM | CC: assignee + performer
# ══════════════════════════════════════════════════════════════════════

def notify_task_blocked(
    task_id: int,
    task_name: str,
    wbs_code: str,
    project_id: int,
    blocked_by_id: int,
    performer_id: int,
    assignee_id: Optional[int] = None,
    blocker_reason: Optional[str] = None,
    extra_cc_ids: Optional[List[int]] = None,
    extra_cc_emails: Optional[List[str]] = None,
) -> bool:
    """
    Alert PM when a task is BLOCKED.

    v2 → v3 changes:
      - Assignee now CC'd (was missing — they need to know PM is alerted)
      - Performer CC'd
      - Action Required for PM
    """
    if not _is_configured():
        logger.warning(f"📧 [SKIP] notify_task_blocked(task={task_id}): email not configured")
        return False

    ctx = _get_project_context(project_id)
    if not ctx.get('pm_email'):
        logger.warning(f"📧 [SKIP] notify_task_blocked(task={task_id}): No PM email for project {project_id} — check il_projects.pm_employee_id → employees.email")
        return False

    logger.info(f"📧 [SEND] notify_task_blocked(task={task_id}): TO={ctx['pm_email']} (PM)")
    blocker = _resolve_person(blocked_by_id)
    blocker_name = blocker['name'] if blocker else '—'

    reason_block = ''
    if blocker_reason:
        reason_block = f'''
        <div style="background:#fef2f2;border-left:4px solid #ef4444;padding:14px 16px;margin:16px 0;border-radius:0 6px 6px 0;">
            <p style="margin:0 0 4px;font-weight:700;color:#991b1b;font-size:13px;">🚧 Blocker reason:</p>
            <p style="margin:0;color:#1f2937;font-size:13px;">{blocker_reason}</p>
        </div>'''

    actions = [
        "Review the blocker reason above",
        "Contact the team member for details",
        "Remove the blocker or escalate to stakeholders",
        "Update the task status once resolved",
    ]

    body = f'''
    <p>Hi <strong>{ctx['pm_name']}</strong>,</p>
    <p>A task has been marked as <strong style="color:#dc2626;">🔴 BLOCKED</strong> and needs your attention:</p>

    <table style="width:100%;margin:16px 0;">
        {_info_row('Task', f'<strong>[{wbs_code or "—"}] {task_name}</strong>')}
        {_info_row('Project', _fmt_project(ctx))}
        {_info_row('Blocked by', blocker_name)}
        {_info_row('Status', '<span style="color:#dc2626;font-weight:700;">🔴 BLOCKED</span>')}
    </table>

    {reason_block}
    {_action_required_block(actions, title="PM Action Required")}'''

    to_emails = [ctx['pm_email']]

    extra = list(extra_cc_ids or [])
    if assignee_id:
        extra.append(assignee_id)

    cc_emails = _build_cc_list(
        performer_id=performer_id,
        extra_person_ids=extra,
        extra_emails=extra_cc_emails,
        exclude_emails=to_emails,
    )

    app_url = build_wbs_deep_link(project_id, task_id)

    return _send_email(
        to_emails=to_emails,
        subject=f"🔴 [BLOCKED] [{wbs_code or '—'}] {task_name} — {ctx.get('project_code', '')}",
        html_body=_base_template("Task Blocked — Action Required", body, app_url),
        cc_emails=cc_emails,
    )


# ══════════════════════════════════════════════════════════════════════
# 4. TASK COMPLETED → TO: PM | CC: assignee + performer
# ══════════════════════════════════════════════════════════════════════

def notify_task_completed(
    task_id: int,
    task_name: str,
    wbs_code: str,
    project_id: int,
    completed_by_id: int,
    performer_id: int,
    assignee_id: Optional[int] = None,
    actual_hours: Optional[float] = None,
    phase_name: Optional[str] = None,
    phase_completion: Optional[float] = None,
    project_completion: Optional[float] = None,
    extra_cc_ids: Optional[List[int]] = None,
    extra_cc_emails: Optional[List[str]] = None,
) -> bool:
    """
    Notify PM when a task is COMPLETED.

    v2 → v3 changes:
      - Assignee CC'd (confirmation that completion was notified)
      - Performer CC'd
      - Progress context + Action Required
    """
    if not _is_configured():
        logger.warning(f"📧 [SKIP] notify_task_completed(task={task_id}): email not configured")
        return False

    ctx = _get_project_context(project_id)
    if not ctx.get('pm_email'):
        logger.warning(f"📧 [SKIP] notify_task_completed(task={task_id}): No PM email for project {project_id}")
        return False

    logger.info(f"📧 [SEND] notify_task_completed(task={task_id}): TO={ctx['pm_email']} (PM)")

    completed_by = _resolve_person(completed_by_id)
    completed_by_name = completed_by['name'] if completed_by else '—'

    progress_block = ''
    if phase_completion is not None or project_completion is not None:
        items = []
        if phase_name and phase_completion is not None:
            items.append(f"Phase ({phase_name}): <strong>{phase_completion:.0f}%</strong>")
        if project_completion is not None:
            items.append(f"Project overall: <strong>{project_completion:.0f}%</strong>")
        if items:
            progress_block = f'''
            <div style="background:#f0fdf4;border-left:4px solid #22c55e;padding:14px 16px;margin:16px 0;border-radius:0 6px 6px 0;">
                <p style="margin:0 0 4px;font-weight:700;color:#166534;font-size:13px;">📊 Progress update</p>
                <p style="margin:0;font-size:13px;">{'<br>'.join(items)}</p>
            </div>'''

    actions = [
        "Review the completed deliverables",
        "Verify quality meets project requirements",
        "Update progress report if this is a key milestone",
    ]

    body = f'''
    <p>Hi <strong>{ctx['pm_name']}</strong>,</p>
    <p>A task has been marked as <strong style="color:#16a34a;">✅ COMPLETED</strong>:</p>

    <table style="width:100%;margin:16px 0;">
        {_info_row('Task', f'<strong>[{wbs_code or "—"}] {task_name}</strong>')}
        {_info_row('Project', _fmt_project(ctx))}
        {_info_row('Phase', phase_name or '—')}
        {_info_row('Completed by', completed_by_name)}
        {_info_row('Actual Hours', f'{actual_hours:.1f}h' if actual_hours else '—')}
        {_info_row('Status', '<span style="color:#16a34a;font-weight:700;">✅ COMPLETED</span>')}
    </table>

    {progress_block}
    {_action_required_block(actions)}'''

    to_emails = [ctx['pm_email']]

    extra = list(extra_cc_ids or [])
    if assignee_id:
        extra.append(assignee_id)

    cc_emails = _build_cc_list(
        performer_id=performer_id,
        extra_person_ids=extra,
        extra_emails=extra_cc_emails,
        exclude_emails=to_emails,
    )

    app_url = build_wbs_deep_link(project_id, task_id)

    return _send_email(
        to_emails=to_emails,
        subject=f"✅ [Completed] [{wbs_code or '—'}] {task_name} — {ctx.get('project_code', '')}",
        html_body=_base_template("Task Completed", body, app_url),
        cc_emails=cc_emails,
    )


# ══════════════════════════════════════════════════════════════════════
# 5. ISSUE CREATED → TO: assigned | CC: PM + performer + reporter (NEW)
# ══════════════════════════════════════════════════════════════════════

def notify_issue_created(
    issue_id: int,
    issue_code: str,
    title: str,
    project_id: int,
    severity: str,
    category: str,
    assigned_to_id: Optional[int],
    reporter_id: Optional[int],
    performer_id: int,
    description: Optional[str] = None,
    due_date=None,
    related_task_name: Optional[str] = None,
    extra_cc_ids: Optional[List[int]] = None,
    extra_cc_emails: Optional[List[str]] = None,
) -> bool:
    """
    Notify when a new issue is created.
    TO: assigned person (or PM if unassigned).
    """
    if not _is_configured():
        logger.warning(f"📧 [SKIP] notify_issue_created(issue={issue_code}): email not configured")
        return False

    ctx = _get_project_context(project_id)
    assigned = _resolve_person(assigned_to_id)
    reporter = _resolve_person(reporter_id)

    # TO: assigned person, fallback to PM
    if assigned and assigned.get('email'):
        to_emails = [assigned['email']]
        greeting_name = assigned['name']
        logger.info(f"📧 [SEND] notify_issue_created({issue_code}): TO={assigned['email']} (assignee)")
    elif ctx.get('pm_email'):
        to_emails = [ctx['pm_email']]
        greeting_name = ctx['pm_name']
    else:
        logger.warning(f"No recipient for issue {issue_code} — skipping.")
        return False

    severity_badge = {
        'CRITICAL': '<span style="color:#dc2626;font-weight:700;">🔴 CRITICAL</span>',
        'HIGH': '<span style="color:#ea580c;font-weight:700;">🟠 HIGH</span>',
        'MEDIUM': '🟡 Medium',
        'LOW': '🟢 Low',
    }.get(severity, severity)

    desc_block = ''
    if description:
        desc_block = f'''
        <div style="background:#fef2f2;border-left:3px solid #ef4444;padding:12px;margin:16px 0;font-size:13px;">
            <strong>Description:</strong><br>{description[:500]}{'...' if len(description) > 500 else ''}
        </div>'''

    actions = [
        "Review the issue details and assess impact",
        "Investigate root cause",
        f"Target resolution by <strong>{_fmt_date(due_date)}</strong>" if due_date else "Set a target resolution date",
        "Update status to <strong>IN_PROGRESS</strong> when you begin",
    ]

    body = f'''
    <p>Hi <strong>{greeting_name}</strong>,</p>
    <p>A new issue has been reported that requires your attention:</p>

    <table style="width:100%;margin:16px 0;">
        {_info_row('Issue', f'<strong>{issue_code} — {title}</strong>')}
        {_info_row('Project', _fmt_project(ctx))}
        {_info_row('Severity', severity_badge)}
        {_info_row('Category', category)}
        {_info_row('Due Date', _fmt_date(due_date))}
        {_info_row('Related Task', related_task_name or '—')}
        {_info_row('Reported by', _fmt_person(reporter['name'] if reporter else None))}
    </table>

    {desc_block}
    {_action_required_block(actions)}'''

    extra = list(extra_cc_ids or [])
    if reporter_id and reporter_id != performer_id:
        extra.append(reporter_id)

    cc_emails = _build_cc_list(
        performer_id=performer_id,
        pm_email=ctx.get('pm_email'),
        extra_person_ids=extra,
        extra_emails=extra_cc_emails,
        exclude_emails=to_emails,
    )

    app_url = build_issues_deep_link(project_id)

    return _send_email(
        to_emails=to_emails,
        subject=f"🔧 [Issue] {issue_code} — {title} ({severity}) — {ctx.get('project_code', '')}",
        html_body=_base_template("New Issue Reported", body, app_url),
        cc_emails=cc_emails,
    )


# ══════════════════════════════════════════════════════════════════════
# 6. CO STATUS CHANGED → TO: requester | CC: PM + approver + performer (NEW)
# ══════════════════════════════════════════════════════════════════════

def notify_co_status_change(
    co_id: int,
    co_number: str,
    title: str,
    project_id: int,
    old_status: str,
    new_status: str,
    requested_by_id: Optional[int],
    approved_by_id: Optional[int],
    performer_id: int,
    cost_impact=None,
    schedule_impact_days: Optional[int] = None,
    extra_cc_ids: Optional[List[int]] = None,
    extra_cc_emails: Optional[List[str]] = None,
) -> bool:
    """Notify requester when CO status changes (SUBMITTED → APPROVED, etc.)."""
    if not _is_configured():
        return False

    ctx = _get_project_context(project_id)
    requester = _resolve_person(requested_by_id)
    approver = _resolve_person(approved_by_id)

    if not requester or not requester.get('email'):
        logger.warning(f"No email for CO requester — skipping.")
        return False

    status_badge = {
        'APPROVED': '<span style="color:#16a34a;font-weight:700;">✅ APPROVED</span>',
        'REJECTED': '<span style="color:#dc2626;font-weight:700;">❌ REJECTED</span>',
        'SUBMITTED': '<span style="color:#2563eb;font-weight:700;">📤 SUBMITTED</span>',
        'CANCELLED': '<span style="color:#6b7280;">🚫 CANCELLED</span>',
    }.get(new_status, new_status)

    impact_str = '—'
    if cost_impact is not None:
        try:
            v = float(cost_impact)
            impact_str = f"+{v:,.0f}" if v > 0 else f"{v:,.0f}"
        except (TypeError, ValueError):
            pass

    actions_map = {
        'APPROVED': [
            "Proceed with implementing the approved changes",
            "Update project plan for new scope/schedule",
            "Communicate changes to the team",
        ],
        'REJECTED': [
            "Review the rejection reasoning",
            "Discuss alternatives with PM",
            "Revise and resubmit if appropriate",
        ],
        'SUBMITTED': [
            "Review the change order details",
            "Evaluate cost and schedule impact",
            "Approve or reject with reasoning",
        ],
    }
    actions = actions_map.get(new_status, ["Review the status change"])

    body = f'''
    <p>Hi <strong>{requester['name']}</strong>,</p>
    <p>A Change Order status has been updated:</p>

    <table style="width:100%;margin:16px 0;">
        {_info_row('Change Order', f'<strong>{co_number} — {title}</strong>')}
        {_info_row('Project', _fmt_project(ctx))}
        {_info_row('Status Change', f'{old_status} → {status_badge}')}
        {_info_row('Cost Impact', impact_str)}
        {_info_row('Schedule Impact', f'{schedule_impact_days or 0} days')}
        {_info_row('Approved by', _fmt_person(approver['name'] if approver else None))}
    </table>

    {_action_required_block(actions)}'''

    to_emails = [requester['email']]

    extra = list(extra_cc_ids or [])
    if approved_by_id:
        extra.append(approved_by_id)

    cc_emails = _build_cc_list(
        performer_id=performer_id,
        pm_email=ctx.get('pm_email'),
        extra_person_ids=extra,
        extra_emails=extra_cc_emails,
        exclude_emails=to_emails,
    )

    app_url = build_issues_deep_link(project_id)
    icon = {'APPROVED': '✅', 'REJECTED': '❌', 'SUBMITTED': '📤'}.get(new_status, '📝')

    return _send_email(
        to_emails=to_emails,
        subject=f"{icon} [CO {new_status}] {co_number} — {title} — {ctx.get('project_code', '')}",
        html_body=_base_template(f"Change Order — {new_status}", body, app_url),
        cc_emails=cc_emails,
    )


# ══════════════════════════════════════════════════════════════════════
# CONVENIENCE — Auto-detect and send from task update context
# ══════════════════════════════════════════════════════════════════════

def notify_on_task_status_change(
    task_id: int,
    old_status: str,
    new_status: str,
    performer_id: int,
    blocker_reason: Optional[str] = None,
    extra_cc_ids: Optional[List[int]] = None,
    extra_cc_emails: Optional[List[str]] = None,
) -> bool:
    """
    Auto-send the right notification based on status transition.
    Call from quick_update_task() or update_task() after save.

    ⚠️ performer_id MUST be employee_id (from st.session_state['employee_id']),
    NOT user_id (from auth.get_user_id()). This was the "Employee #51" bug.

    Fires for: BLOCKED → notify PM, COMPLETED → notify PM.
    """
    if old_status == new_status:
        return True
    if new_status not in ('BLOCKED', 'COMPLETED'):
        return True

    logger.info(f"📧 notify_on_task_status_change: task={task_id}, {old_status}→{new_status}")

    try:
        from .wbs_queries import get_task
        task = get_task(task_id)
        if not task:
            logger.warning(f"📧 [SKIP] notify_on_task_status_change(task={task_id}): get_task returned None")
            return False

        if new_status == 'BLOCKED':
            return notify_task_blocked(
                task_id=task_id,
                task_name=task['task_name'],
                wbs_code=task.get('wbs_code', ''),
                project_id=task['project_id'],
                blocked_by_id=performer_id,
                performer_id=performer_id,
                assignee_id=task.get('assignee_id'),
                blocker_reason=blocker_reason,
                extra_cc_ids=extra_cc_ids,
                extra_cc_emails=extra_cc_emails,
            )

        if new_status == 'COMPLETED':
            from ..db import execute_query

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
                project_id=task['project_id'],
                completed_by_id=performer_id,
                performer_id=performer_id,
                assignee_id=task.get('assignee_id'),
                actual_hours=task.get('actual_hours'),
                phase_name=phase_name,
                phase_completion=phase_completion,
                project_completion=proj_completion,
                extra_cc_ids=extra_cc_ids,
                extra_cc_emails=extra_cc_emails,
            )

    except Exception as e:
        logger.error(f"📧 [ERROR] notify_on_task_status_change(task={task_id}, {old_status}→{new_status}) failed: {e}", exc_info=True)
        return False

    return True


def notify_on_task_assign(
    task_id: int,
    old_assignee_id: Optional[int],
    new_assignee_id: Optional[int],
    performer_id: int,
    extra_cc_ids: Optional[List[int]] = None,
    extra_cc_emails: Optional[List[str]] = None,
) -> bool:
    """
    Auto-send assignment notification when assignee changes.
    Call from create_task() or update_task() after save.

    ⚠️ performer_id MUST be employee_id, NOT user_id.
    """
    if not new_assignee_id:
        logger.info(f"📧 [SKIP] notify_on_task_assign(task={task_id}): no assignee_id — skipping")
        return True
    if old_assignee_id == new_assignee_id:
        return True

    try:
        from .wbs_queries import get_task
        task = get_task(task_id)
        if not task:
            logger.warning(f"📧 [SKIP] notify_on_task_assign(task={task_id}): get_task returned None")
            return False

        logger.info(f"📧 notify_on_task_assign: task={task_id} '{task['task_name']}', assignee={new_assignee_id}, performer={performer_id}")

        return notify_task_assigned(
            task_id=task_id,
            task_name=task['task_name'],
            wbs_code=task.get('wbs_code', ''),
            project_id=task['project_id'],
            assignee_id=new_assignee_id,
            performer_id=performer_id,
            priority=task.get('priority', 'NORMAL'),
            planned_start=task.get('planned_start'),
            planned_end=task.get('planned_end'),
            description=task.get('description'),
            phase_name=task.get('phase_name'),
            is_reassign=(old_assignee_id is not None),
            extra_cc_ids=extra_cc_ids,
            extra_cc_emails=extra_cc_emails,
        )

    except Exception as e:
        logger.error(f"📧 [ERROR] notify_on_task_assign(task={task_id}) failed: {e}", exc_info=True)
        return False