# utils/il_project/approval_notify.py
"""
Approval Config Notification — Email for approval authority changes & summaries.

Reuses _send_email infrastructure from email_notify.py.

Triggers:
  Phase 1 — On-demand Summary: admin sends current config snapshot
  Phase 2 — Config Change Alert: auto-notify when authority is added/edited/deleted
  Phase 3 — Saved Presets + Notification Log (audit trail)

Public API:
    send_config_summary()       → Phase 1 on-demand summary
    send_config_change_alert()  → Phase 2 auto-notify
    auto_notify_crud()          → Phase 2 single entry point for CRUD auto-notify
    get_mandatory_cc()          → Resolve mandatory CC list (sender + approvers in scope)
    get_presets()               → Phase 3 saved recipient presets
    save_preset()               → Phase 3 create/update preset
    delete_preset()             → Phase 3 remove preset
    resolve_preset_emails()     → Phase 3 resolve preset → email list
    log_notification_sent()     → Phase 3 audit trail
    get_notification_log()      → Phase 3 audit trail read
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# DB HELPERS (lazy import — avoid circular)
# ══════════════════════════════════════════════════════════════════════

def _execute_query(sql, params=None):
    from ..db import execute_query
    return execute_query(sql, params or {})


def _execute_update(sql, params=None):
    from ..db import execute_update
    return execute_update(sql, params or {})


def _get_engine():
    from ..db import get_db_engine
    return get_db_engine()


# ══════════════════════════════════════════════════════════════════════
# SHARED: EMAIL SEND (reuses email_notify infra)
# ══════════════════════════════════════════════════════════════════════

def _send_email(to_emails, subject, html_body, cc_emails=None) -> bool:
    """Delegate to email_notify._send_email. Non-blocking."""
    try:
        from .email_notify import _send_email as _do_send
        return _do_send(to_emails, subject, html_body, cc_emails)
    except Exception as e:
        logger.error(f"approval_notify._send_email failed: {e}")
        return False


def _is_configured() -> bool:
    try:
        from .email_notify import _is_configured as _check
        return _check()
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════
# HTML TEMPLATES
# ══════════════════════════════════════════════════════════════════════

def _base_template(title: str, body_html: str, action_url: Optional[str] = None) -> str:
    """Wrap body in a clean HTML email template — matches email_notify style."""
    action_btn = ""
    if action_url:
        action_btn = f'''
        <div style="text-align:center;margin:24px 0;">
            <a href="{action_url}"
               style="background:#2563eb;color:#fff;padding:12px 28px;
                      border-radius:6px;text-decoration:none;font-weight:600;
                      display:inline-block;">
                View Details
            </a>
        </div>'''

    return f'''
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:960px;margin:0 auto;
                background:#fff;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
        <div style="background:#1e3a5f;padding:16px 24px;">
            <h2 style="color:#fff;margin:0;font-size:18px;">{title}</h2>
        </div>
        <div style="padding:24px;">
            {body_html}
            {action_btn}
        </div>
        <div style="background:#f9fafb;padding:12px 24px;border-top:1px solid #e5e7eb;
                    font-size:12px;color:#6b7280;">
            Rozitek Intralogistic Solution<br>
            This is an automated notification. Please do not reply directly to this email.
        </div>
    </div>'''


def _fmt_amount(val) -> str:
    if val is None:
        return 'Unlimited'
    try:
        v = float(val)
        if v >= 1_000_000_000:
            return f"{v / 1_000_000_000:,.1f}B ₫"
        if v >= 1_000_000:
            return f"{v / 1_000_000:,.0f}M ₫"
        return f"{v:,.0f} ₫"
    except (TypeError, ValueError):
        return str(val)


def _fmt_amount_flow(val) -> str:
    """Shorter format for flow summary chains (≤500M ₫ or No limit)."""
    if val is None:
        return 'No limit'
    return f"≤{_fmt_amount(val)}"


def _fmt_amount_exact(val) -> str:
    """Full exact number for workflow section (500,000,000 ₫)."""
    if val is None:
        return 'Unlimited'
    try:
        v = float(val)
        return f"{v:,.0f} ₫"
    except (TypeError, ValueError):
        return str(val)


def _build_flow_steps_html(auths_sorted: List[Dict]) -> str:
    """
    Build a clear approval workflow visualization.
    Shows each level as a rule card with threshold logic.
    Includes a scenario guide so Finance understands when each level applies.
    Email-client safe (inline styles, table layout).
    """
    if not auths_sorted:
        return ''

    # ── Level cards ──
    rows = []
    for a in auths_sorted:
        name = a.get('employee_name', '?')
        pos = a.get('position', '') or ''
        lvl = a.get('approval_level', '?')
        max_amt = a.get('max_amount')
        amt_display = _fmt_amount_exact(max_amt)

        # Describe what this level handles
        if max_amt is not None:
            rule_text = f"Approves requests up to <strong>{amt_display}</strong>"
        else:
            rule_text = "Approves requests of <strong>any amount</strong>"

        rows.append(f'''
        <tr>
            <td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;text-align:center;
                       vertical-align:middle;width:70px;">
                <div style="background:#1e3a5f;color:#fff;font-size:11px;font-weight:700;
                            display:inline-block;padding:3px 12px;border-radius:10px;">
                    Level {lvl}</div>
            </td>
            <td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;vertical-align:middle;">
                <div style="font-weight:700;font-size:13px;color:#1e293b;">{name}</div>
                <div style="font-size:11px;color:#64748b;">{pos}</div>
            </td>
            <td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;
                       vertical-align:middle;font-size:12px;color:#374151;">
                {rule_text}
            </td>
        </tr>''')

    cards_html = f'''
    <table style="width:100%;border-collapse:collapse;background:#fff;
                  border:1px solid #e2e8f0;border-radius:8px;font-size:13px;">
        <tr style="background:#f1f5f9;">
            <th style="padding:8px 12px;text-align:center;font-size:11px;
                       color:#64748b;font-weight:600;">LEVEL</th>
            <th style="padding:8px 12px;text-align:left;font-size:11px;
                       color:#64748b;font-weight:600;">APPROVER</th>
            <th style="padding:8px 12px;text-align:left;font-size:11px;
                       color:#64748b;font-weight:600;">AUTHORITY</th>
        </tr>
        {''.join(rows)}
    </table>'''

    # ── Scenario guide (when does each level apply?) ──
    # Build threshold breakpoints from the sorted levels
    scenarios = []
    for i, a in enumerate(auths_sorted):
        lvl = a.get('approval_level', '?')
        max_amt = a.get('max_amount')
        name_short = a.get('employee_name', '?').split()[0]

        if max_amt is not None:
            amt_label = _fmt_amount_exact(max_amt)
            # This level is sufficient for amounts up to max_amt
            levels_needed = ' + '.join(
                f"L{auths_sorted[j].get('approval_level', '?')}"
                for j in range(i + 1)
            )
            approvers_needed = ' → '.join(
                auths_sorted[j].get('employee_name', '?').split()[0]
                for j in range(i + 1)
            )
            scenarios.append(
                f'<span style="font-weight:600;color:#1e3a5f;">≤ {amt_label}</span>'
                f' — {levels_needed} ({approvers_needed})'
            )
        else:
            # Unlimited level — only show if there were previous limited levels
            if i > 0:
                prev_amt = auths_sorted[i - 1].get('max_amount')
                if prev_amt is not None:
                    prev_label = _fmt_amount_exact(prev_amt)
                    levels_needed = ' + '.join(
                        f"L{auths_sorted[j].get('approval_level', '?')}"
                        for j in range(i + 1)
                    )
                    approvers_needed = ' → '.join(
                        auths_sorted[j].get('employee_name', '?').split()[0]
                        for j in range(i + 1)
                    )
                    scenarios.append(
                        f'<span style="font-weight:600;color:#1e3a5f;">&gt; {prev_label}</span>'
                        f' — {levels_needed} ({approvers_needed})'
                    )

    scenario_html = ''
    if scenarios:
        scenario_items = ''.join(
            f'<div style="padding:3px 0;font-size:12px;color:#374151;">'
            f'<span style="color:#94a3b8;margin-right:4px;">●</span> {s}</div>'
            for s in scenarios
        )
        scenario_html = f'''
        <div style="margin-top:10px;padding:10px 14px;background:#f0f9ff;
                    border-radius:6px;border:1px solid #dbeafe;">
            <div style="font-size:11px;font-weight:600;color:#1e40af;
                        margin-bottom:4px;">When is each level required?</div>
            {scenario_items}
        </div>'''

    return f'{cards_html}{scenario_html}'


def _info_row(label: str, value: str) -> str:
    return f'''<tr>
        <td style="padding:4px 0;color:#6b7280;width:160px;">{label}</td>
        <td style="padding:4px 0;font-weight:500;">{value}</td>
    </tr>'''


# ══════════════════════════════════════════════════════════════════════
# PHASE 1: ON-DEMAND CONFIG SUMMARY
# ══════════════════════════════════════════════════════════════════════

def build_summary_html(
    authorities: List[Dict],
    type_filter: Optional[str] = None,
    admin_note: str = "",
    include_validity: bool = True,
    include_history: bool = False,
    recent_changes: Optional[List[Dict]] = None,
) -> str:
    """
    Build HTML email body for approval config summary.
    Used for both preview (in UI) and actual email send.

    Args:
        authorities: list of authority dicts (from _load_authorities query)
        type_filter: filter to specific approval type code, or None for all
        admin_note: optional note from admin
        include_validity: include valid_from/valid_to columns
        include_history: include recent changes section
        recent_changes: list of recent change dicts for history section

    Returns:
        HTML string (body only — caller wraps with _base_template for email)
    """
    if type_filter:
        authorities = [a for a in authorities if a.get('type_code') == type_filter]

    # Only active
    active_auth = [a for a in authorities if a.get('is_active')]

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

    # Group by type
    type_groups: Dict[str, List[Dict]] = {}
    for a in active_auth:
        key = a.get('type_code', 'UNKNOWN')
        if key not in type_groups:
            type_groups[key] = []
        type_groups[key].append(a)

    # Header info
    scope_label = type_filter or "All"
    summary_meta = f'''
    <table style="width:100%;margin:8px 0 16px 0;">
        {_info_row('Date', f'<strong>{now_str}</strong>')}
        {_info_row('Category', scope_label)}
        {_info_row('Authorized Personnel', f'{len(active_auth)}')}
        {_info_row('Approval Categories', f'{len(type_groups)}')}
    </table>'''

    # Admin note
    note_html = ""
    if admin_note and admin_note.strip():
        note_html = f'''
        <div style="background:#f0f9ff;border-left:3px solid #3b82f6;padding:12px;
                    margin:12px 0;font-size:13px;">
            <strong>Remarks:</strong> {admin_note}
        </div>'''

    # Authority tables (grouped by type)
    tables_html = ""
    for type_code, auths in type_groups.items():
        type_name = auths[0].get('type_name', type_code) if auths else type_code
        auths_sorted = sorted(auths, key=lambda a: (a.get('approval_level', 0)))

        # Table header
        validity_hdr = '<th style="padding:8px;text-align:left;">Effective Period</th>' if include_validity else ''
        tables_html += f'''
        <div style="margin:20px 0 8px 0;">
            <strong style="color:#1e3a5f;font-size:14px;">{type_name}</strong>
            <span style="color:#6b7280;font-size:12px;"> ({type_code})</span>
        </div>
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
            <tr style="background:#f3f4f6;">
                <th style="padding:8px;text-align:center;width:50px;">Level</th>
                <th style="padding:8px;text-align:left;">Approver</th>
                <th style="padding:8px;text-align:left;">Position</th>
                <th style="padding:8px;text-align:left;">Email</th>
                <th style="padding:8px;text-align:right;">Approval Limit</th>
                <th style="padding:8px;text-align:center;">Status</th>
                {validity_hdr}
            </tr>'''

        for a in auths_sorted:
            lvl = a.get('approval_level', '—')
            name = a.get('employee_name', '—')
            pos = a.get('position', '—') or '—'
            email = a.get('email', '—') or '—'
            amt = _fmt_amount(a.get('max_amount'))
            # Text + color fallback for email clients that don't render emoji
            if a.get('is_active'):
                status_html = '<span style="color:#16a34a;font-weight:600;">● Active</span>'
            else:
                status_html = '<span style="color:#dc2626;font-weight:600;">● Inactive</span>'

            validity_cell = ""
            if include_validity:
                vf = str(a.get('valid_from', ''))[:10] if a.get('valid_from') else '—'
                vt = str(a.get('valid_to', ''))[:10] if a.get('valid_to') else 'No expiry'
                validity_cell = f'<td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;font-size:12px;">{vf} → {vt}</td>'

            tables_html += f'''
            <tr>
                <td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;text-align:center;
                           font-weight:700;color:#1e3a5f;">L{lvl}</td>
                <td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;font-weight:600;">{name}</td>
                <td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;color:#6b7280;">{pos}</td>
                <td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;color:#6b7280;font-size:12px;">{email}</td>
                <td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;text-align:right;font-weight:600;">{amt}</td>
                <td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;text-align:center;">{status_html}</td>
                {validity_cell}
            </tr>'''

        tables_html += '</table>'

    # Approval flow visualization (per type)
    flow_html = ""
    for type_code, auths in type_groups.items():
        type_name = auths[0].get('type_name', type_code) if auths else type_code
        auths_sorted = sorted(auths, key=lambda a: a.get('approval_level', 0))
        steps_html = _build_flow_steps_html(auths_sorted)
        flow_html += f'''
        <div style="margin:8px 0 16px 0;">
            <div style="font-size:12px;color:#64748b;margin-bottom:8px;text-align:center;">
                {type_name}
            </div>
            {steps_html}
        </div>'''

    if flow_html:
        flow_html = f'''
        <div style="margin:24px 0 8px 0;">
            <strong style="color:#1e3a5f;">Approval Workflow</strong>
        </div>
        <div style="background:#f8fafc;border-radius:8px;padding:16px 12px;">
            {flow_html}
        </div>'''

    # Recent changes (Phase 3)
    history_html = ""
    if include_history and recent_changes:
        history_html = '''
        <div style="margin:24px 0 8px 0;">
            <strong style="color:#1e3a5f;">Recent Updates (Last 30 days)</strong>
        </div>
        <table style="width:100%;border-collapse:collapse;font-size:12px;">
            <tr style="background:#f3f4f6;">
                <th style="padding:6px 8px;text-align:left;">Date</th>
                <th style="padding:6px 8px;text-align:left;">Action</th>
                <th style="padding:6px 8px;text-align:left;">Details</th>
                <th style="padding:6px 8px;text-align:left;">Updated by</th>
            </tr>'''
        for ch in recent_changes[:15]:
            history_html += f'''
            <tr>
                <td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;">{ch.get('date', '')}</td>
                <td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;">{ch.get('action', '')}</td>
                <td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;">{ch.get('details', '')}</td>
                <td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;">{ch.get('changed_by', '')}</td>
            </tr>'''
        history_html += '</table>'

    # Finance callout — only show for purchase/payment-related types
    finance_callout = ""
    _finance_keywords = {'PURCHASE', 'PAYMENT', 'INVOICE', 'PO', 'PR', 'FINANCE', 'COST'}
    _type_codes_upper = {tc.upper() for tc in type_groups.keys()}
    _has_finance_scope = (
        not type_filter  # "All Types" → always relevant
        or any(kw in code for code in _type_codes_upper for kw in _finance_keywords)
    )
    if _has_finance_scope:
        finance_callout = '''
        <div style="background:#fffbeb;border-left:3px solid #f59e0b;padding:12px;
                    margin:20px 0;font-size:13px;">
            <strong>Important — Finance Department:</strong> Please review and update your
            payment verification checklist accordingly. All payments must be authorized
            through the designated approval chain before processing.
        </div>'''

    body = f'''
    <p style="margin-top:0;">To whom it may concern,</p>
    <p style="margin-top:0;color:#374151;">
        Please be informed of the current approval authority assignments as of
        <strong>{now_str}</strong>. The details are provided below for your reference.
    </p>
    {summary_meta}
    {note_html}
    {tables_html}
    {flow_html}
    {finance_callout}
    {history_html}
    <p style="margin-top:20px;color:#374151;font-size:13px;">
        Should you have any questions or require further clarification, please contact the Administration team.
    </p>
    '''
    return body


def send_config_summary(
    to_emails: List[str],
    cc_emails: Optional[List[str]] = None,
    authorities: Optional[List[Dict]] = None,
    type_filter: Optional[str] = None,
    admin_note: str = "",
    include_validity: bool = True,
    include_history: bool = False,
    recent_changes: Optional[List[Dict]] = None,
    app_url: Optional[str] = None,
    sent_by: str = "",
    sent_by_employee_id: Optional[int] = None,
    sender_email: Optional[str] = None,
) -> Dict:
    """
    Phase 1: Send on-demand approval config summary email.

    Automatically merges mandatory CC (sender + all approvers in scope)
    into the CC list. Manual TO/CC from the UI are preserved.

    Returns: {success: bool, message: str, recipient_count: int,
              mandatory_cc: [...], final_to: [...], final_cc: [...]}
    """
    if not _is_configured():
        return {'success': False, 'message': 'Email not configured', 'recipient_count': 0}

    if not to_emails:
        return {'success': False, 'message': 'No recipients specified', 'recipient_count': 0}

    # Load authorities if not provided
    if authorities is None:
        authorities = _load_all_authorities()

    # Resolve sender email if not provided
    if not sender_email:
        sender_email = _get_sender_email(sent_by_employee_id, sent_by)

    # Auto-merge mandatory CC (sender + approvers in scope)
    mandatory_emails, _ = get_mandatory_cc(
        type_filter=type_filter,
        sender_email=sender_email,
        authorities=authorities,
    )

    # Merge: mandatory CC that are not already in TO
    merged_cc = list(cc_emails or [])
    for me in mandatory_emails:
        if me and me not in to_emails and me not in merged_cc:
            merged_cc.append(me)

    body = build_summary_html(
        authorities=authorities,
        type_filter=type_filter,
        admin_note=admin_note,
        include_validity=include_validity,
        include_history=include_history,
        recent_changes=recent_changes,
    )

    scope = type_filter or "All Categories"
    subject = f"[Notice] Approval Authority — {scope} ({datetime.now().strftime('%Y-%m-%d')})"

    html = _base_template("Approval Authority Notification", body, app_url)
    ok = _send_email(to_emails, subject, html, merged_cc or None)

    recipient_count = len(to_emails) + len(merged_cc)
    if ok:
        # Log the send (Phase 3)
        _log_notification(
            notification_type='SUMMARY',
            subject=subject,
            to_emails=to_emails,
            cc_emails=merged_cc,
            sent_by=sent_by,
            sent_by_employee_id=sent_by_employee_id,
            details=f"Scope: {scope}, Recipients: {recipient_count}",
        )

    return {
        'success': ok,
        'message': f'Notification sent to {recipient_count} recipient(s)' if ok else 'Failed to send email',
        'recipient_count': recipient_count,
        'mandatory_cc': mandatory_emails,
        'final_to': to_emails,
        'final_cc': merged_cc,
    }


# ══════════════════════════════════════════════════════════════════════
# PHASE 2: CONFIG CHANGE ALERT
# ══════════════════════════════════════════════════════════════════════

def build_change_html(
    change_type: str,
    changed_by_name: str,
    authority_data: Dict,
    old_data: Optional[Dict] = None,
    change_note: str = "",
    current_chain: Optional[List[Dict]] = None,
) -> str:
    """
    Build HTML body for a config change alert.

    Args:
        change_type: 'CREATED' | 'UPDATED' | 'DELETED' | 'DEACTIVATED' | 'ACTIVATED'
        changed_by_name: admin who made the change
        authority_data: current authority dict (after change)
        old_data: previous values (for UPDATED — shows diff)
        change_note: optional note from admin
        current_chain: full current chain for this type (for flow visualization)
    """
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

    # Human-readable change type labels
    _change_labels = {
        'CREATED': 'New Assignment',
        'UPDATED': 'Updated',
        'DELETED': 'Removed',
        'DEACTIVATED': 'Deactivated',
        'ACTIVATED': 'Activated',
    }
    change_label = _change_labels.get(change_type, change_type)

    # Change meta
    type_name = authority_data.get('type_name', '') or authority_data.get('type_code', '—')
    meta_html = f'''
    <table style="width:100%;margin:8px 0 16px 0;">
        {_info_row('Action', f'<strong>{change_label}</strong>')}
        {_info_row('Updated by', changed_by_name)}
        {_info_row('Date', now_str)}
        {_info_row('Category', f"<strong>{type_name}</strong>")}
    </table>'''

    # What changed (detail box)
    _active = authority_data.get('is_active')
    _status_label = '<span style="color:#16a34a;font-weight:600;">● Active</span>' if _active else '<span style="color:#dc2626;font-weight:600;">● Inactive</span>'
    detail_rows = f'''
        {_info_row('Approver', f"<strong>{authority_data.get('employee_name', '—')}</strong>")}
        {_info_row('Email', authority_data.get('email', '—'))}
        {_info_row('Position', authority_data.get('position', '—') or '—')}
        {_info_row('Level', str(authority_data.get('approval_level', '—')))}
        {_info_row('Approval Limit', _fmt_amount(authority_data.get('max_amount')))}
        {_info_row('Status', _status_label)}
    '''

    detail_title = 'New Approver Details' if change_type == 'CREATED' else 'Approver Details'
    detail_html = f'''
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;
                padding:16px;margin:12px 0;">
        <div style="font-weight:600;color:#1e3a5f;margin-bottom:8px;">
            {detail_title}
        </div>
        <table style="width:100%;">{detail_rows}</table>
    </div>'''

    # Diff for UPDATED
    diff_html = ""
    if change_type == 'UPDATED' and old_data:
        changes = []
        field_labels = {
            'employee_name': 'Approver', 'approval_level': 'Level',
            'max_amount': 'Approval Limit', 'is_active': 'Status',
            'valid_from': 'Effective From', 'valid_to': 'Effective To',
            'notes': 'Notes', 'company_name': 'Company',
        }
        for field, label in field_labels.items():
            old_val = old_data.get(field)
            new_val = authority_data.get(field)
            if field == 'max_amount':
                old_val = _fmt_amount(old_val)
                new_val = _fmt_amount(new_val)
            elif field == 'is_active':
                old_val = '● Active' if old_val else '● Inactive'
                new_val = '● Active' if new_val else '● Inactive'
            else:
                old_val = str(old_val or '—')[:50]
                new_val = str(new_val or '—')[:50]

            if old_val != new_val:
                changes.append(f'''
                <tr>
                    <td style="padding:4px 8px;color:#6b7280;width:120px;">{label}</td>
                    <td style="padding:4px 8px;text-decoration:line-through;color:#ef4444;">{old_val}</td>
                    <td style="padding:4px 8px;font-weight:600;color:#16a34a;">{new_val}</td>
                </tr>''')

        if changes:
            diff_html = f'''
            <div style="background:#fefce8;border:1px solid #fde68a;border-radius:6px;
                        padding:16px;margin:12px 0;">
                <div style="font-weight:600;color:#92400e;margin-bottom:8px;">What Changed</div>
                <table style="width:100%;font-size:13px;">
                    <tr style="color:#6b7280;font-size:11px;">
                        <td style="padding:2px 8px;">Field</td>
                        <td style="padding:2px 8px;">Before</td>
                        <td style="padding:2px 8px;">After</td>
                    </tr>
                    {''.join(changes)}
                </table>
            </div>'''

    # Current chain
    chain_html = ""
    if current_chain:
        sorted_chain = sorted(current_chain, key=lambda a: a.get('approval_level', 0))
        active_chain = [a for a in sorted_chain if a.get('is_active')]
        if active_chain:
            steps_html = _build_flow_steps_html(active_chain)
            chain_html = f'''
            <div style="margin:16px 0;">
                <div style="font-weight:600;color:#1e3a5f;margin-bottom:8px;">
                    Current Approval Workflow
                </div>
                <div style="background:#f8fafc;border-radius:8px;padding:16px 12px;">
                    {steps_html}
                </div>
            </div>'''

    # Change note
    note_html = ""
    if change_note and change_note.strip():
        note_html = f'''
        <div style="background:#f9fafb;border-left:3px solid #d1d5db;padding:12px;
                    margin:12px 0;font-size:13px;">
            <strong>Remarks:</strong> {change_note}
        </div>'''

    # Finance callout — only for purchase/payment-related types
    finance_html = ""
    _tc = (authority_data.get('type_code', '') or '').upper()
    _finance_keywords = {'PURCHASE', 'PAYMENT', 'INVOICE', 'PO', 'PR', 'FINANCE', 'COST'}
    if any(kw in _tc for kw in _finance_keywords):
        finance_html = '''
        <div style="background:#fffbeb;border-left:3px solid #f59e0b;padding:12px;
                    margin:16px 0;font-size:13px;">
            <strong>Important — Finance Department:</strong> Please verify this update
            aligns with your payment authorization procedures and update your records accordingly.
        </div>'''

    body = f'''
    <p style="margin-top:0;">To whom it may concern,</p>
    <p style="margin-top:0;color:#374151;">
        Please be informed that an approval authority has been <strong>{change_label.lower()}</strong>.
        The details of this change are provided below for your reference.
    </p>
    {meta_html}
    {detail_html}
    {diff_html}
    {chain_html}
    {note_html}
    {finance_html}
    <p style="margin-top:20px;color:#374151;font-size:13px;">
        Should you have any questions regarding this change, please contact the Administration team.
    </p>
    '''
    return body


def send_config_change_alert(
    change_type: str,
    authority_data: Dict,
    to_emails: List[str],
    cc_emails: Optional[List[str]] = None,
    old_data: Optional[Dict] = None,
    changed_by_name: str = "",
    change_note: str = "",
    current_chain: Optional[List[Dict]] = None,
    app_url: Optional[str] = None,
    sent_by: str = "",
    sent_by_employee_id: Optional[int] = None,
) -> Dict:
    """
    Phase 2: Send config change alert email.

    Returns: {success: bool, message: str}
    """
    if not _is_configured():
        return {'success': False, 'message': 'Email not configured'}

    if not to_emails:
        return {'success': False, 'message': 'No recipients specified'}

    body = build_change_html(
        change_type=change_type,
        changed_by_name=changed_by_name,
        authority_data=authority_data,
        old_data=old_data,
        change_note=change_note,
        current_chain=current_chain,
    )

    type_code = authority_data.get('type_code', '')
    type_name = authority_data.get('type_name', '') or type_code
    emp_name = authority_data.get('employee_name', '')
    _change_labels = {
        'CREATED': 'New Assignment',
        'UPDATED': 'Updated',
        'DELETED': 'Removed',
        'DEACTIVATED': 'Deactivated',
        'ACTIVATED': 'Activated',
    }
    change_label = _change_labels.get(change_type, change_type)
    subject = f"[Notice] Approval Authority {change_label} — {emp_name} ({type_name})"

    html = _base_template("Approval Authority Update", body, app_url)
    ok = _send_email(to_emails, subject, html, cc_emails)

    if ok:
        _log_notification(
            notification_type='CHANGE_ALERT',
            subject=subject,
            to_emails=to_emails,
            cc_emails=cc_emails,
            sent_by=sent_by,
            sent_by_employee_id=sent_by_employee_id,
            details=f"{change_type}: {emp_name} — {type_code} L{authority_data.get('approval_level', '?')}",
        )

    return {
        'success': ok,
        'message': f'Change alert sent ({change_type})' if ok else 'Failed to send email',
    }


# ══════════════════════════════════════════════════════════════════════
# MANDATORY RECIPIENTS & AUTO-NOTIFY
# ══════════════════════════════════════════════════════════════════════

def _get_sender_email(sent_by_employee_id: Optional[int] = None, sent_by: str = "") -> Optional[str]:
    """Resolve current admin/sender email from employee_id or user_id."""
    try:
        if sent_by_employee_id:
            rows = _execute_query(
                "SELECT email FROM employees WHERE id = :id AND delete_flag = 0",
                {'id': sent_by_employee_id},
            )
            if rows and rows[0].get('email'):
                return rows[0]['email']
        if sent_by:
            rows = _execute_query(
                "SELECT email FROM employees WHERE (id = :uid OR keycloak_id = :uid) AND delete_flag = 0 LIMIT 1",
                {'uid': sent_by},
            )
            if rows and rows[0].get('email'):
                return rows[0]['email']
    except Exception as e:
        logger.debug(f"_get_sender_email failed: {e}")
    return None


def get_mandatory_cc(
    type_filter: Optional[str] = None,
    sender_email: Optional[str] = None,
    authorities: Optional[List[Dict]] = None,
) -> Tuple[List[str], List[str]]:
    """
    Resolve mandatory CC recipients that must always be included.

    Returns:
        (emails, labels) — deduplicated, with human-readable labels.

    Mandatory CC includes:
      1. Sender (admin performing the action)
      2. All active approvers in the filtered scope
    """
    if authorities is None:
        authorities = _load_all_authorities()

    emails: List[str] = []
    labels: List[str] = []

    # 1. Sender
    if sender_email and sender_email not in emails:
        emails.append(sender_email)
        labels.append(f"{sender_email} (sender)")

    # 2. Active approvers in scope
    scope_auth = authorities
    if type_filter:
        scope_auth = [a for a in authorities if a.get('type_code') == type_filter]
    active_auth = [a for a in scope_auth if a.get('is_active')]

    for a in active_auth:
        email = a.get('email', '')
        if email and email not in emails:
            emails.append(email)
            name = a.get('employee_name', '—')
            lvl = a.get('approval_level', '?')
            labels.append(f"{name} — L{lvl} ({email})")

    return emails, labels


def auto_notify_crud(
    change_type: str,
    authority_data: Dict,
    old_data: Optional[Dict] = None,
    changed_by_name: str = "",
    sender_email: Optional[str] = None,
    sent_by: str = "",
    sent_by_employee_id: Optional[int] = None,
) -> Dict:
    """
    Auto-notify after a CRUD operation on approval authorities.
    Automatically resolves all recipients — no manual selection needed.

    TO:  The affected approver (the one being created/updated/deleted)
    CC:  Sender + all other active approvers in the same type + finance preset

    Args:
        change_type: 'CREATED' | 'UPDATED' | 'DELETED' | 'DEACTIVATED' | 'ACTIVATED'
        authority_data: dict with employee_name, email, type_code, type_name,
                        approval_level, max_amount, is_active, position
        old_data: previous values (for UPDATED — shows diff)
        changed_by_name: display name of admin performing the change
        sender_email: email of admin performing the change
        sent_by: user_id string
        sent_by_employee_id: employee_id int

    Returns: {success: bool, message: str, to: [...], cc: [...]}
    """
    if not _is_configured():
        return {'success': False, 'message': 'Email not configured', 'to': [], 'cc': []}

    # Resolve sender email if not provided
    if not sender_email:
        sender_email = _get_sender_email(sent_by_employee_id, sent_by)

    type_code = authority_data.get('type_code', '')
    affected_email = authority_data.get('email', '')

    # ── Build TO list ──
    to_emails: List[str] = []
    if affected_email:
        to_emails.append(affected_email)

    # ── Build CC list ──
    cc_emails: List[str] = []

    # 1. Sender (admin)
    if sender_email and sender_email not in to_emails:
        cc_emails.append(sender_email)

    # 2. All active approvers in the same type (excluding affected)
    try:
        all_auth = _load_all_authorities()
        same_type = [
            a for a in all_auth
            if a.get('type_code') == type_code and a.get('is_active')
        ]
        for a in same_type:
            email = a.get('email', '')
            if email and email not in to_emails and email not in cc_emails:
                cc_emails.append(email)
    except Exception as e:
        logger.debug(f"auto_notify_crud: failed to load approvers: {e}")

    # 3. Finance preset (if type is finance-related)
    _finance_keywords = {'PURCHASE', 'PAYMENT', 'INVOICE', 'PO', 'PR', 'FINANCE', 'COST'}
    if any(kw in type_code.upper() for kw in _finance_keywords):
        try:
            presets = get_presets()
            finance_preset = next(
                (p for p in presets
                 if 'finance' in (p.get('preset_name', '') or '').lower()),
                None,
            )
            if finance_preset:
                f_emails, _ = resolve_preset_emails(finance_preset)
                for fe in f_emails:
                    if fe and fe not in to_emails and fe not in cc_emails:
                        cc_emails.append(fe)
        except Exception as e:
            logger.debug(f"auto_notify_crud: failed to resolve finance preset: {e}")

    # Ensure at least one TO
    if not to_emails:
        if cc_emails:
            to_emails.append(cc_emails.pop(0))
        else:
            return {'success': False, 'message': 'No recipients resolved', 'to': [], 'cc': []}

    # Build chain for visualization
    current_chain = []
    try:
        current_chain = [
            a for a in _load_all_authorities()
            if a.get('type_code') == type_code and a.get('is_active')
        ]
    except Exception:
        pass

    # Send
    result = send_config_change_alert(
        change_type=change_type,
        authority_data=authority_data,
        to_emails=to_emails,
        cc_emails=cc_emails or None,
        old_data=old_data,
        changed_by_name=changed_by_name,
        current_chain=current_chain,
        sent_by=sent_by,
        sent_by_employee_id=sent_by_employee_id,
    )

    result['to'] = to_emails
    result['cc'] = cc_emails
    return result


# ══════════════════════════════════════════════════════════════════════
# PHASE 3: NOTIFICATION PRESETS (CRUD)
# ══════════════════════════════════════════════════════════════════════

def get_presets(approval_type_code: Optional[str] = None) -> List[Dict]:
    """Get saved notification presets from il_notification_presets."""
    try:
        sql = """
            SELECT id, preset_name, preset_type, email_list, employee_ids,
                   approval_type_code, created_by, created_date, modified_date
            FROM il_notification_presets
            WHERE delete_flag = 0
        """
        params = {}
        if approval_type_code:
            sql += " AND (approval_type_code = :code OR approval_type_code IS NULL)"
            params['code'] = approval_type_code
        sql += " ORDER BY preset_name"
        rows = _execute_query(sql, params)
        # Parse JSON fields
        result = []
        for r in rows:
            d = dict(r)
            d['email_list'] = _parse_json_field(d.get('email_list'))
            d['employee_ids'] = _parse_json_field(d.get('employee_ids'))
            result.append(d)
        return result
    except Exception as e:
        logger.error(f"get_presets failed: {e}")
        return []


def save_preset(
    preset_name: str,
    preset_type: str = 'MANUAL',
    email_list: Optional[List[str]] = None,
    employee_ids: Optional[List[int]] = None,
    approval_type_code: Optional[str] = None,
    created_by: str = "",
    preset_id: Optional[int] = None,
) -> Dict:
    """
    Create or update a notification preset.
    If preset_id is provided, updates existing; else creates new.
    """
    try:
        email_json = json.dumps(email_list or [])
        emp_json = json.dumps(employee_ids or [])

        if preset_id:
            _execute_update("""
                UPDATE il_notification_presets SET
                    preset_name = :name,
                    preset_type = :ptype,
                    email_list = :emails,
                    employee_ids = :eids,
                    approval_type_code = :acode
                WHERE id = :id AND delete_flag = 0
            """, {
                'id': preset_id, 'name': preset_name.strip(),
                'ptype': preset_type,
                'emails': email_json, 'eids': emp_json,
                'acode': approval_type_code,
            })
            return {'success': True, 'message': f'Preset "{preset_name}" updated', 'id': preset_id}
        else:
            from sqlalchemy import text as _text
            engine = _get_engine()
            with engine.connect() as conn:
                result = conn.execute(_text("""
                    INSERT INTO il_notification_presets
                        (preset_name, preset_type, email_list, employee_ids,
                         approval_type_code, created_by)
                    VALUES (:name, :ptype, :emails, :eids, :acode, :by)
                """), {
                    'name': preset_name.strip(), 'ptype': preset_type,
                    'emails': email_json, 'eids': emp_json,
                    'acode': approval_type_code, 'by': created_by,
                })
                conn.commit()
                new_id = result.lastrowid
            return {'success': True, 'message': f'Preset "{preset_name}" created', 'id': new_id}
    except Exception as e:
        logger.error(f"save_preset failed: {e}")
        return {'success': False, 'message': str(e)}


def delete_preset(preset_id: int) -> bool:
    """Soft-delete a preset."""
    try:
        _execute_update(
            "UPDATE il_notification_presets SET delete_flag = 1 WHERE id = :id",
            {'id': preset_id}
        )
        return True
    except Exception as e:
        logger.error(f"delete_preset failed: {e}")
        return False


def resolve_preset_emails(preset: Dict) -> Tuple[List[str], List[str]]:
    """
    Resolve a preset to actual email addresses.

    For AUTO_APPROVERS: query all active approvers for the type.
    For AUTO_PMS: query all PMs.
    For MANUAL: use stored email_list + resolve employee_ids.

    Returns: (resolved_emails, labels_for_display)
    """
    preset_type = preset.get('preset_type', 'MANUAL')
    emails = []
    labels = []

    if preset_type == 'AUTO_APPROVERS':
        # Resolve all active approvers for this approval type
        code = preset.get('approval_type_code')
        sql = """
            SELECT DISTINCT e.email, CONCAT(e.first_name, ' ', e.last_name) AS name
            FROM approval_authorities aa
            JOIN employees e ON aa.employee_id = e.id
            JOIN approval_types at2 ON aa.approval_type_id = at2.id
            WHERE aa.is_active = 1 AND aa.delete_flag = 0
              AND e.email IS NOT NULL AND e.email != ''
        """
        params = {}
        if code:
            sql += " AND at2.code = :code"
            params['code'] = code
        try:
            rows = _execute_query(sql, params)
            for r in rows:
                if r['email'] and r['email'] not in emails:
                    emails.append(r['email'])
                    labels.append(f"{r['name']} ({r['email']})")
        except Exception as e:
            logger.error(f"resolve AUTO_APPROVERS failed: {e}")

    elif preset_type == 'AUTO_PMS':
        try:
            rows = _execute_query("""
                SELECT DISTINCT e.email, CONCAT(e.first_name, ' ', e.last_name) AS name
                FROM il_projects p
                JOIN employees e ON p.pm_employee_id = e.id
                WHERE p.delete_flag = 0 AND p.status NOT IN ('CLOSED', 'CANCELLED')
                  AND e.email IS NOT NULL AND e.email != ''
            """)
            for r in rows:
                if r['email'] and r['email'] not in emails:
                    emails.append(r['email'])
                    labels.append(f"{r['name']} ({r['email']})")
        except Exception as e:
            logger.error(f"resolve AUTO_PMS failed: {e}")

    else:
        # MANUAL: stored emails + employee IDs
        stored_emails = preset.get('email_list', []) or []
        for e in stored_emails:
            if e and '@' in e and e not in emails:
                emails.append(e)
                labels.append(e)

        emp_ids = preset.get('employee_ids', []) or []
        if emp_ids:
            placeholders = ', '.join(f':id{i}' for i in range(len(emp_ids)))
            params = {f'id{i}': eid for i, eid in enumerate(emp_ids)}
            try:
                rows = _execute_query(f"""
                    SELECT email, CONCAT(first_name, ' ', last_name) AS name
                    FROM employees
                    WHERE id IN ({placeholders}) AND delete_flag = 0
                      AND email IS NOT NULL AND email != ''
                """, params)
                for r in rows:
                    if r['email'] and r['email'] not in emails:
                        emails.append(r['email'])
                        labels.append(f"{r['name']} ({r['email']})")
            except Exception as e:
                logger.error(f"resolve employee_ids failed: {e}")

    return emails, labels


# ══════════════════════════════════════════════════════════════════════
# PHASE 3: NOTIFICATION LOG (audit trail)
# ══════════════════════════════════════════════════════════════════════

def _log_notification(
    notification_type: str,
    subject: str,
    to_emails: List[str],
    cc_emails: Optional[List[str]] = None,
    sent_by: str = "",
    sent_by_employee_id: Optional[int] = None,
    details: str = "",
) -> None:
    """
    Log notification send to approval_history table as a CONFIG_NOTIFICATION record.
    Uses a dedicated approval_type code so it's visible in the History tab.
    Falls back silently — non-critical.

    NOTE: approval_history.approver_id has FK → employees.id,
          so we MUST use a valid employee_id (not 0).
    """
    try:
        from sqlalchemy import text as _text
        engine = _get_engine()
        with engine.connect() as conn:
            # Find approval_type for config notifications
            at_row = conn.execute(_text(
                "SELECT id FROM approval_types WHERE code = 'APPROVAL_CONFIG_NOTIFY' AND delete_flag = 0 LIMIT 1"
            )).fetchone()

            if not at_row:
                logger.debug("APPROVAL_CONFIG_NOTIFY type not found — skipping log.")
                return

            # Resolve approver_id: must be valid FK to employees
            approver_id = sent_by_employee_id
            if not approver_id:
                # Try to resolve from sent_by (users.id string → employees.keycloak_id or id)
                if sent_by:
                    emp_row = conn.execute(_text("""
                        SELECT id FROM employees
                        WHERE (id = :uid OR keycloak_id = :uid)
                          AND delete_flag = 0
                        LIMIT 1
                    """), {'uid': sent_by}).fetchone()
                    if emp_row:
                        approver_id = emp_row[0]

            if not approver_id:
                # Last resort: use the first active admin/approver as placeholder
                fallback = conn.execute(_text("""
                    SELECT employee_id FROM approval_authorities
                    WHERE is_active = 1 AND delete_flag = 0
                    ORDER BY approval_level DESC LIMIT 1
                """)).fetchone()
                approver_id = fallback[0] if fallback else None

            if not approver_id:
                logger.debug("No valid employee_id for notification log — skipping.")
                return

            recipients_str = ', '.join(to_emails[:5])
            if len(to_emails) > 5:
                recipients_str += f' (+{len(to_emails) - 5} more)'

            conn.execute(_text("""
                INSERT INTO approval_history
                    (approval_type_id, entity_id, entity_reference, approver_id,
                     approval_status, approval_level, comments, created_by,
                     created_date)
                VALUES (:atid, :entity_id, :ref, :approver_id,
                        :status, 0, :comments, :by,
                        NOW())
            """), {
                'atid': at_row[0],
                'entity_id': approver_id,  # use admin's employee_id as entity_id too
                'ref': f'NOTIFY: {notification_type}',
                'approver_id': approver_id,
                'status': 'SENT',
                'comments': f"[{notification_type}] {subject} | To: {recipients_str} | {details}"[:500],
                'by': sent_by or 'SYSTEM',
            })
            conn.commit()
            logger.debug(f"Notification logged: {notification_type}, approver_id={approver_id}")
    except Exception as e:
        logger.debug(f"_log_notification failed (non-critical): {e}")


def get_notification_log(limit: int = 30) -> List[Dict]:
    """Get recent notification sends from approval_history."""
    try:
        return _execute_query("""
            SELECT
                ah.id,
                ah.entity_reference,
                ah.comments,
                CONCAT(e.first_name, ' ', e.last_name) AS sent_by_name,
                ah.created_by,
                ah.created_date
            FROM approval_history ah
            JOIN approval_types at2 ON ah.approval_type_id = at2.id
            JOIN employees e ON ah.approver_id = e.id
            WHERE at2.code = 'APPROVAL_CONFIG_NOTIFY'
              AND ah.delete_flag = 0
            ORDER BY ah.created_date DESC
            LIMIT :lim
        """, {'lim': limit})
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ══════════════════════════════════════════════════════════════════════

def _load_all_authorities() -> List[Dict]:
    """Load all authorities (same query as IL_98 page)."""
    return _execute_query("""
        SELECT
            aa.id,
            aa.employee_id,
            CONCAT(e.first_name, ' ', e.last_name) AS employee_name,
            e.email,
            p.name AS position,
            aa.approval_type_id,
            at2.code AS type_code,
            at2.name AS type_name,
            aa.company_id,
            c.english_name AS company_name,
            aa.approval_level,
            aa.max_amount,
            aa.is_active,
            aa.valid_from,
            aa.valid_to,
            aa.notes,
            aa.created_date,
            aa.modified_date
        FROM approval_authorities aa
        JOIN employees e ON aa.employee_id = e.id
        JOIN approval_types at2 ON aa.approval_type_id = at2.id
        LEFT JOIN companies c ON aa.company_id = c.id
        LEFT JOIN positions p ON e.position_id = p.id
        WHERE aa.delete_flag = 0
        ORDER BY at2.code, aa.approval_level, e.first_name
    """)


def _parse_json_field(val) -> list:
    """Parse JSON string → list. Returns [] on failure."""
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    return []