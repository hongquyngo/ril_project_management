# utils/il_project/email_notify.py
"""
Email Notification for IL Purchase Request workflow.

Uses existing config.py infrastructure:
  - SMTP via Gmail (smtp.gmail.com:587)
  - App password from .env (OUTBOUND_EMAIL_SENDER / OUTBOUND_EMAIL_PASSWORD)
  - Feature flag: ENABLE_EMAIL_NOTIFICATIONS

Triggers:
  1. PR Submitted     → email to approver
  2. PR Approved      → email to requester (+ next approver if multi-level)
  3. PR Rejected      → email to requester
  4. Revision Request  → email to requester
  5. PO Created       → email to requester + finance team

All sends are non-blocking: failures are logged but never crash the app.
"""

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# CONFIG LOADER
# ══════════════════════════════════════════════════════════════════════

def _get_email_config() -> Dict:
    """Load email config from utils.config. Returns dict with sender, password, host, port."""
    try:
        from ..config import config
        if not config.is_feature_enabled("EMAIL_NOTIFICATIONS"):
            logger.info("Email notifications disabled by feature flag.")
            return {}
        return config.get_email_config("outbound")
    except Exception as e:
        logger.warning(f"Could not load email config: {e}")
        return {}


def _is_configured() -> bool:
    """Check if outbound email is properly configured."""
    cfg = _get_email_config()
    return bool(cfg.get('sender') and cfg.get('password'))


# ══════════════════════════════════════════════════════════════════════
# CORE SEND
# ══════════════════════════════════════════════════════════════════════

def _send_email(
    to_emails: List[str],
    subject: str,
    html_body: str,
    cc_emails: Optional[List[str]] = None,
) -> bool:
    """
    Send email via SMTP. Non-blocking — returns False on failure.
    
    Args:
        to_emails: List of recipient email addresses
        subject: Email subject
        html_body: HTML email body
        cc_emails: Optional CC list
    
    Returns:
        True if sent successfully
    """
    cfg = _get_email_config()
    if not cfg.get('sender') or not cfg.get('password'):
        logger.warning("Email not configured — skipping notification.")
        return False

    sender = cfg['sender']
    password = cfg['password']
    host = cfg.get('host', 'smtp.gmail.com')
    port = cfg.get('port', 587)

    # Filter out empty/None emails
    to_emails = [e for e in to_emails if e and '@' in str(e)]
    if not to_emails:
        logger.warning("No valid recipients — skipping email.")
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = f"Rozitek ERP <{sender}>"
        msg['To'] = ', '.join(to_emails)
        msg['Subject'] = subject
        if cc_emails:
            cc_emails = [e for e in cc_emails if e and '@' in str(e)]
            msg['Cc'] = ', '.join(cc_emails)

        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        all_recipients = to_emails + (cc_emails or [])

        with smtplib.SMTP(host, port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(sender, password)
            server.sendmail(sender, all_recipients, msg.as_string())

        logger.info(f"📧 Email sent: '{subject}' → {', '.join(to_emails)}")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("📧 SMTP auth failed — check OUTBOUND_EMAIL_SENDER/PASSWORD in .env")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"📧 SMTP error: {e}")
        return False
    except Exception as e:
        logger.error(f"📧 Email send failed: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════
# HTML TEMPLATE
# ══════════════════════════════════════════════════════════════════════

def _base_template(title: str, body_html: str, action_url: Optional[str] = None) -> str:
    """Wrap body in a clean HTML email template."""
    action_btn = ""
    if action_url:
        action_btn = f'''
        <div style="text-align:center;margin:24px 0;">
            <a href="{action_url}" 
               style="background:#2563eb;color:#fff;padding:12px 28px;
                      border-radius:6px;text-decoration:none;font-weight:600;
                      display:inline-block;">
                Open in ERP
            </a>
        </div>'''

    return f'''
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:600px;margin:0 auto;
                background:#fff;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
        <div style="background:#1e3a5f;padding:16px 24px;">
            <h2 style="color:#fff;margin:0;font-size:18px;">🏗️ IL Project — {title}</h2>
        </div>
        <div style="padding:24px;">
            {body_html}
            {action_btn}
        </div>
        <div style="background:#f9fafb;padding:12px 24px;border-top:1px solid #e5e7eb;
                    font-size:12px;color:#6b7280;">
            Rozitek Intralogistic Solution — ERP System<br>
            This is an automated notification. Please do not reply to this email.
        </div>
    </div>'''


def _fmt_vnd(val) -> str:
    """Format number as VND for email."""
    if val is None:
        return '—'
    try:
        v = float(val)
        if v >= 1_000_000_000:
            return f"{v/1_000_000_000:,.1f}B ₫"
        if v >= 1_000_000:
            return f"{v/1_000_000:,.0f}M ₫"
        return f"{v:,.0f} ₫"
    except (TypeError, ValueError):
        return '—'


def _items_table(items: list) -> str:
    """Generate HTML table for PR line items."""
    if not items:
        return ''
    rows = ''
    for it in items:
        rows += f'''<tr>
            <td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;">{it.get('cogs_category','')}</td>
            <td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;">{(it.get('item_description','') or '')[:40]}</td>
            <td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;text-align:right;">{it.get('quantity',0):.1f}</td>
            <td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;text-align:right;">{_fmt_vnd(it.get('amount_vnd'))}</td>
        </tr>'''
    return f'''
    <table style="width:100%;border-collapse:collapse;margin:16px 0;font-size:13px;">
        <tr style="background:#f3f4f6;">
            <th style="padding:8px;text-align:left;">Cat</th>
            <th style="padding:8px;text-align:left;">Item</th>
            <th style="padding:8px;text-align:right;">Qty</th>
            <th style="padding:8px;text-align:right;">Amount VND</th>
        </tr>
        {rows}
    </table>'''


def _info_row(label: str, value: str) -> str:
    return f'''<tr>
        <td style="padding:4px 0;color:#6b7280;width:140px;">{label}</td>
        <td style="padding:4px 0;font-weight:500;">{value}</td>
    </tr>'''


def _budget_comparison_table(budget_data: Optional[Dict] = None) -> str:
    """
    Generate HTML table: Estimate Budget vs PR Committed by COGS category.
    budget_data comes from pr_queries.get_budget_vs_pr().
    Shows A–F rows with status colors.
    """
    if not budget_data or not budget_data.get('has_data'):
        return ''

    categories = budget_data.get('categories', [])
    if not categories:
        return ''

    def _status_color(status: str) -> str:
        return {'ok': '#16a34a', 'warning': '#d97706', 'over': '#dc2626',
                'empty': '#9ca3af', 'info': '#6366f1'}.get(status, '#6b7280')

    def _status_icon(status: str) -> str:
        return {'ok': '🟢', 'warning': '🟡', 'over': '🔴',
                'empty': '⚪', 'info': '🔵'}.get(status, '⚪')

    header = '''
    <table style="width:100%;border-collapse:collapse;margin:16px 0;font-size:13px;">
        <tr style="background:#f3f4f6;">
            <th style="padding:8px;text-align:left;">Category</th>
            <th style="padding:8px;text-align:right;">Estimated</th>
            <th style="padding:8px;text-align:right;">PR Committed</th>
            <th style="padding:8px;text-align:right;">Remaining</th>
            <th style="padding:8px;text-align:center;">Used %</th>
            <th style="padding:8px;text-align:center;">Status</th>
        </tr>'''

    rows_html = ''
    for cat in categories:
        est_v = cat.get('estimated', 0)
        com_v = cat.get('pr_committed', 0)
        rem_v = cat.get('remaining', 0)
        pct = cat.get('pct_used', 0)
        status = cat.get('status', 'empty')

        # Skip empty categories (no estimate and no PR)
        if est_v == 0 and com_v == 0:
            continue

        color = _status_color(status)
        icon = _status_icon(status)

        # Highlight row if over budget
        row_bg = ''
        if status == 'over':
            row_bg = 'background:#fef2f2;'
        elif status == 'warning':
            row_bg = 'background:#fffbeb;'

        rows_html += f'''
        <tr style="{row_bg}">
            <td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;font-weight:500;">{cat.get('label', cat['category'])}</td>
            <td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;text-align:right;">{_fmt_vnd(est_v)}</td>
            <td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;text-align:right;font-weight:600;">{_fmt_vnd(com_v)}</td>
            <td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;text-align:right;color:{color};">{_fmt_vnd(rem_v) if rem_v >= 0 else f'<strong>({_fmt_vnd(abs(rem_v))})</strong>'}</td>
            <td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;text-align:center;color:{color};font-weight:600;">{pct:.0f}%</td>
            <td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;text-align:center;">{icon}</td>
        </tr>'''

    # Total row
    t_est = budget_data.get('total_estimated', 0)
    t_com = budget_data.get('total_committed', 0)
    t_rem = budget_data.get('total_remaining', 0)
    t_pct = budget_data.get('total_pct_used', 0)
    t_color = '#dc2626' if t_pct > 100 else '#d97706' if t_pct > 85 else '#16a34a'

    rows_html += f'''
    <tr style="background:#f9fafb;font-weight:700;">
        <td style="padding:8px;border-top:2px solid #d1d5db;">TOTAL</td>
        <td style="padding:8px;border-top:2px solid #d1d5db;text-align:right;">{_fmt_vnd(t_est)}</td>
        <td style="padding:8px;border-top:2px solid #d1d5db;text-align:right;">{_fmt_vnd(t_com)}</td>
        <td style="padding:8px;border-top:2px solid #d1d5db;text-align:right;color:{t_color};">{_fmt_vnd(t_rem)}</td>
        <td style="padding:8px;border-top:2px solid #d1d5db;text-align:center;color:{t_color};">{t_pct:.0f}%</td>
        <td style="padding:8px;border-top:2px solid #d1d5db;text-align:center;">{'🔴' if t_pct > 100 else '🟡' if t_pct > 85 else '🟢'}</td>
    </tr>'''

    title_html = f'''
    <div style="margin:16px 0 4px 0;font-size:13px;font-weight:600;color:#374151;">
        📊 Budget vs PR Committed (Est Rev {budget_data.get('estimate_version', '—')})
    </div>'''

    return title_html + header + rows_html + '</table>'


# ══════════════════════════════════════════════════════════════════════
# CC MERGE HELPER
# ══════════════════════════════════════════════════════════════════════

def _merge_cc(*sources, exclude: Optional[List[str]] = None) -> Optional[List[str]]:
    """
    Merge multiple CC sources into a deduplicated list.
    Filters out empty/None values, TO recipients (via exclude), and duplicates.
    Returns None if empty (so _send_email skips CC header).

    Args:
        *sources: mix of str (single email) and list[str] (multiple)
        exclude: list of TO emails to exclude from CC (avoid duplicate)
    """
    exclude_set = {e.lower().strip() for e in (exclude or []) if e}
    seen = set()
    result = []
    for src in sources:
        if src is None:
            continue
        emails = [src] if isinstance(src, str) else list(src)
        for e in emails:
            if not e or '@' not in str(e):
                continue
            key = e.lower().strip()
            if key not in seen and key not in exclude_set:
                seen.add(key)
                result.append(e.strip())
    return result or None


# ══════════════════════════════════════════════════════════════════════
# PUBLIC API — Notification Triggers
# ══════════════════════════════════════════════════════════════════════

def notify_pr_submitted(
    pr_number: str,
    project_code: str,
    project_name: str,
    requester_name: str,
    total_vnd: float,
    item_count: int,
    priority: str,
    justification: str,
    approver_name: str,
    approver_email: str,
    approval_level: int,
    max_level: int,
    requester_email: Optional[str] = None,
    cc_emails: Optional[List[str]] = None,
    items: Optional[list] = None,
    budget_data: Optional[Dict] = None,
    app_url: Optional[str] = None,
) -> bool:
    """Send notification to approver when PR is submitted.
    Auto-CC: requester. User CC: from cc_emails param.
    """
    if not _is_configured():
        return False

    priority_badge = {
        'URGENT': '🔴 URGENT', 'HIGH': '🔼 HIGH',
        'NORMAL': '➖ Normal', 'LOW': '🔽 Low',
    }.get(priority, priority)

    body = f'''
    <p>Xin chào <strong>{approver_name}</strong>,</p>
    <p>Một Purchase Request mới cần phê duyệt của bạn:</p>
    
    <table style="width:100%;margin:16px 0;">
        {_info_row('PR Number', f'<strong>{pr_number}</strong>')}
        {_info_row('Project', f'{project_code} — {project_name}')}
        {_info_row('Requester', requester_name)}
        {_info_row('Total Amount', f'<strong style="color:#1e3a5f;">{_fmt_vnd(total_vnd)}</strong>')}
        {_info_row('Items', str(item_count))}
        {_info_row('Priority', priority_badge)}
        {_info_row('Approval Level', f'{approval_level} / {max_level}')}
    </table>
    
    {f'<div style="background:#f0f9ff;border-left:3px solid #3b82f6;padding:12px;margin:16px 0;font-size:13px;"><strong>Justification:</strong> {justification}</div>' if justification else ''}
    
    {_items_table(items or [])}
    
    {_budget_comparison_table(budget_data)}
    
    <p style="color:#6b7280;font-size:13px;">
        Vui lòng đăng nhập ERP để xem chi tiết và phê duyệt.
    </p>'''

    return _send_email(
        to_emails=[approver_email],
        subject=f"[PR Approval] {pr_number} — {project_code} — {_fmt_vnd(total_vnd)}",
        html_body=_base_template("Purchase Request — Pending Approval", body, app_url),
        cc_emails=_merge_cc(requester_email, cc_emails, exclude=[approver_email]),
    )


def notify_pr_approved(
    pr_number: str,
    project_code: str,
    total_vnd: float,
    requester_email: str,
    requester_name: str,
    approver_name: str,
    approval_level: int,
    is_final: bool,
    next_approver_name: Optional[str] = None,
    next_approver_email: Optional[str] = None,
    pm_email: Optional[str] = None,
    cc_emails: Optional[List[str]] = None,
    budget_data: Optional[Dict] = None,
    app_url: Optional[str] = None,
) -> bool:
    """
    Send notification when PR is approved.
    - To requester: always. Auto-CC PM on final. User CC from cc_emails.
    - To next approver: if not final (multi-level).
    """
    if not _is_configured():
        return False

    success = True

    # Notify requester
    if is_final:
        status_html = '<span style="color:#16a34a;font-weight:700;">✅ APPROVED (Final)</span>'
        action_note = 'Bạn có thể tạo Purchase Order từ PR này.'
    else:
        status_html = f'<span style="color:#2563eb;font-weight:700;">✅ Approved at Level {approval_level}</span>'
        action_note = f'PR đang chờ phê duyệt tiếp tại Level {approval_level + 1} ({next_approver_name or "—"}).'

    body_requester = f'''
    <p>Xin chào <strong>{requester_name}</strong>,</p>
    <p>PR của bạn đã được phê duyệt:</p>
    
    <table style="width:100%;margin:16px 0;">
        {_info_row('PR Number', f'<strong>{pr_number}</strong>')}
        {_info_row('Project', project_code)}
        {_info_row('Amount', _fmt_vnd(total_vnd))}
        {_info_row('Approved by', approver_name)}
        {_info_row('Status', status_html)}
    </table>
    
    <p>{action_note}</p>
    
    {_budget_comparison_table(budget_data)}'''

    _auto_cc = [pm_email] if is_final and pm_email else []
    ok1 = _send_email(
        to_emails=[requester_email],
        subject=f"[PR {'Approved' if is_final else 'Approved L' + str(approval_level)}] {pr_number} — {_fmt_vnd(total_vnd)}",
        html_body=_base_template("Purchase Request — Approved", body_requester, app_url),
        cc_emails=_merge_cc(_auto_cc, cc_emails, exclude=[requester_email]),
    )
    success = success and ok1

    # Notify next approver (if multi-level)
    if not is_final and next_approver_email and next_approver_name:
        body_next = f'''
        <p>Xin chào <strong>{next_approver_name}</strong>,</p>
        <p>Một Purchase Request cần phê duyệt Level {approval_level + 1} của bạn:</p>
        
        <table style="width:100%;margin:16px 0;">
            {_info_row('PR Number', f'<strong>{pr_number}</strong>')}
            {_info_row('Project', project_code)}
            {_info_row('Amount', f'<strong style="color:#1e3a5f;">{_fmt_vnd(total_vnd)}</strong>')}
            {_info_row('Previously approved by', f'{approver_name} (Level {approval_level})')}
        </table>
        
        <p style="color:#6b7280;font-size:13px;">
            Vui lòng đăng nhập ERP để xem chi tiết và phê duyệt.
        </p>
        
        {_budget_comparison_table(budget_data)}'''

        ok2 = _send_email(
            to_emails=[next_approver_email],
            subject=f"[PR Approval L{approval_level + 1}] {pr_number} — {_fmt_vnd(total_vnd)}",
            html_body=_base_template("Purchase Request — Pending Your Approval", body_next, app_url),
        )
        success = success and ok2

    return success


def notify_pr_rejected(
    pr_number: str,
    project_code: str,
    total_vnd: float,
    requester_email: str,
    requester_name: str,
    approver_name: str,
    rejection_reason: str,
    pm_email: Optional[str] = None,
    cc_emails: Optional[List[str]] = None,
    app_url: Optional[str] = None,
) -> bool:
    """Send notification to requester when PR is rejected.
    Auto-CC PM if different. User CC from cc_emails."""
    if not _is_configured():
        return False

    body = f'''
    <p>Xin chào <strong>{requester_name}</strong>,</p>
    <p>PR của bạn đã bị từ chối:</p>
    
    <table style="width:100%;margin:16px 0;">
        {_info_row('PR Number', f'<strong>{pr_number}</strong>')}
        {_info_row('Project', project_code)}
        {_info_row('Amount', _fmt_vnd(total_vnd))}
        {_info_row('Rejected by', approver_name)}
        {_info_row('Status', '<span style="color:#dc2626;font-weight:700;">❌ REJECTED</span>')}
    </table>
    
    <div style="background:#fef2f2;border-left:3px solid #ef4444;padding:12px;margin:16px 0;">
        <strong>Lý do:</strong> {rejection_reason}
    </div>
    
    <p style="color:#6b7280;font-size:13px;">
        Bạn có thể tạo PR mới hoặc liên hệ {approver_name} để thảo luận thêm.
    </p>'''

    return _send_email(
        to_emails=[requester_email],
        subject=f"[PR Rejected] {pr_number} — {project_code}",
        html_body=_base_template("Purchase Request — Rejected", body, app_url),
        cc_emails=_merge_cc(pm_email, cc_emails, exclude=[requester_email]),
    )


def notify_pr_revision_requested(
    pr_number: str,
    project_code: str,
    total_vnd: float,
    requester_email: str,
    requester_name: str,
    approver_name: str,
    revision_notes: str,
    pm_email: Optional[str] = None,
    cc_emails: Optional[List[str]] = None,
    app_url: Optional[str] = None,
) -> bool:
    """Send notification to requester when revision is requested.
    Auto-CC PM if different. User CC from cc_emails."""
    if not _is_configured():
        return False

    body = f'''
    <p>Xin chào <strong>{requester_name}</strong>,</p>
    <p>PR của bạn cần được chỉnh sửa trước khi phê duyệt:</p>
    
    <table style="width:100%;margin:16px 0;">
        {_info_row('PR Number', f'<strong>{pr_number}</strong>')}
        {_info_row('Project', project_code)}
        {_info_row('Amount', _fmt_vnd(total_vnd))}
        {_info_row('Requested by', approver_name)}
        {_info_row('Status', '<span style="color:#d97706;font-weight:700;">🔄 REVISION REQUESTED</span>')}
    </table>
    
    <div style="background:#fffbeb;border-left:3px solid #f59e0b;padding:12px;margin:16px 0;">
        <strong>Yêu cầu chỉnh sửa:</strong> {revision_notes}
    </div>
    
    <p style="color:#6b7280;font-size:13px;">
        Vui lòng đăng nhập ERP, chỉnh sửa PR và submit lại.
    </p>'''

    return _send_email(
        to_emails=[requester_email],
        subject=f"[PR Revision] {pr_number} — Cần chỉnh sửa",
        html_body=_base_template("Purchase Request — Revision Requested", body, app_url),
        cc_emails=_merge_cc(pm_email, cc_emails, exclude=[requester_email]),
    )


def notify_po_created(
    pr_number: str,
    po_number: str,
    project_code: str,
    total_vnd: float,
    vendor_name: str,
    requester_email: str,
    requester_name: str,
    pm_email: Optional[str] = None,
    cc_emails: Optional[List[str]] = None,
    app_url: Optional[str] = None,
) -> bool:
    """Send notification when PO is created from approved PR.
    Auto-CC PM. User CC from cc_emails (e.g. finance team).
    """
    if not _is_configured():
        return False

    body = f'''
    <p>Xin chào <strong>{requester_name}</strong>,</p>
    <p>Purchase Order đã được tạo từ PR của bạn:</p>
    
    <table style="width:100%;margin:16px 0;">
        {_info_row('PO Number', f'<strong style="color:#16a34a;">{po_number}</strong>')}
        {_info_row('From PR', pr_number)}
        {_info_row('Project', project_code)}
        {_info_row('Vendor', vendor_name or '—')}
        {_info_row('Amount', _fmt_vnd(total_vnd))}
    </table>
    
    <p style="color:#6b7280;font-size:13px;">
        PO đã sẵn sàng trên hệ thống ERP. Bước tiếp theo: gửi PO cho vendor.
    </p>'''

    return _send_email(
        to_emails=[requester_email],
        cc_emails=_merge_cc(pm_email, cc_emails, exclude=[requester_email]),
        subject=f"[PO Created] {po_number} from {pr_number} — {vendor_name or project_code}",
        html_body=_base_template("Purchase Order Created", body, app_url),
    )


def notify_pr_cancelled(
    pr_number: str,
    project_code: str,
    total_vnd: float,
    requester_email: str,
    requester_name: str,
    cancelled_by: str,
    pm_email: Optional[str] = None,
    pending_approver_email: Optional[str] = None,
    pending_approver_name: Optional[str] = None,
    cc_emails: Optional[List[str]] = None,
    app_url: Optional[str] = None,
) -> bool:
    """
    Send notification when PR is cancelled.
    Auto-CC: PM + pending approver. User CC from cc_emails.
    """
    if not _is_configured():
        return False

    body = f'''
    <p>Xin chào <strong>{requester_name}</strong>,</p>
    <p>Purchase Request đã bị hủy:</p>
    
    <table style="width:100%;margin:16px 0;">
        {_info_row('PR Number', f'<strong>{pr_number}</strong>')}
        {_info_row('Project', project_code)}
        {_info_row('Amount', _fmt_vnd(total_vnd))}
        {_info_row('Cancelled by', cancelled_by)}
        {_info_row('Status', '<span style="color:#6b7280;font-weight:700;">⬛ CANCELLED</span>')}
    </table>
    
    <p style="color:#6b7280;font-size:13px;">
        PR này đã bị hủy và không thể khôi phục. Bạn có thể tạo PR mới nếu cần.
    </p>'''

    return _send_email(
        to_emails=[requester_email],
        subject=f"[PR Cancelled] {pr_number} — {project_code}",
        html_body=_base_template("Purchase Request — Cancelled", body, app_url),
        cc_emails=_merge_cc(pm_email, pending_approver_email, cc_emails, exclude=[requester_email]),
    )