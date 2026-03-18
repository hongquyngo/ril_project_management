# pages/IL_5_🛒_Purchase_Request.py
"""
Purchase Request — Create / Submit / Approve / Track / Create PO

Redesigned v2:
  - All Projects → Overview dashboard with cross-project KPIs + per-project summary
  - Specific project → context banner + 3 tabs (My PRs / Pending / All PRs)
  - Pending Approval tab: dataframe pattern (consistent with IL_3/IL_4) + bulk approve
  - PR Detail: separate View / Edit dialogs (consistent with IL_1 pattern)
  - Quick actions on action bar (Submit, Create PO without opening dialog)
  - Approval progress visualization
  - Budget tracking (Estimate vs PR totals)
  - Enhanced sidebar: project info, budget context, more filters
  - Age/urgency indicators on pending PRs
  - Confirmation for destructive actions
"""

import streamlit as st
import pandas as pd
from datetime import date, datetime
import logging

from utils.auth import AuthManager
from utils.il_project import (
    get_projects_df, get_project,
    get_active_estimate, get_estimate_line_items,
    get_companies, get_currencies, get_employees,
    fmt_vnd,
)
from utils.il_project.pr_queries import (
    generate_pr_number,
    get_pr_list_df, get_pending_for_approver, get_pr, get_pr_items_df,
    create_pr, update_pr, create_pr_item, delete_pr_item, recalc_pr_totals,
    reduce_pr_item,
    cancel_pr,
    submit_pr, approve_pr, reject_pr, request_revision,
    get_pr_approval_history, get_approval_chain, determine_max_level,
    get_importable_estimate_items,
    create_po_from_pr,
    is_project_pm, is_approver_for_pr,
    get_project_pm_email,
    get_budget_vs_pr,
    get_pr_costbook_status,
    get_costbook_warnings_batch,
    # PO readiness (new)
    resolve_product_ids,
    validate_po_readiness,
    link_product_to_pr_item,
    search_products_for_linking,
    # PO enrichment
    get_payment_terms,
    get_trade_terms,
    get_contacts_for_company,
    get_company_address,
    get_po_enrichment_data,
)
from utils.il_project.currency import get_rate_to_vnd
from utils.il_project.helpers import get_vendor_companies
from utils.il_project.po_pdf_widget import (
    render_po_pdf_download,
    render_po_pdf_downloads_for_pr,
    render_po_created_success,
    cleanup_pdf_state,
)
from utils.il_project.email_notify import (
    notify_pr_submitted,
    notify_pr_approved,
    notify_pr_rejected,
    notify_pr_revision_requested,
    notify_po_created,
    notify_pr_cancelled,
    notify_pr_reminder,
)

logger = logging.getLogger(__name__)
auth = AuthManager()

st.set_page_config(page_title="Purchase Request", page_icon="🛒", layout="wide")

# ── Deep link: capture query params BEFORE auth check ─────────────
# Session state survives across login → deep link triggers after auth
_qp = st.query_params
if _qp.get('pr_id'):
    st.session_state['_deep_link'] = {
        'pr_id': _qp.get('pr_id'),
        'action': _qp.get('action', 'view'),
    }
    st.query_params.clear()

# ── Auth: inline login when accessed via deep link ────────────────
if not auth.check_session():
    _has_deep_link = '_deep_link' in st.session_state
    if _has_deep_link:
        # Show inline login form (user clicked link from email)
        st.title("🛒 Purchase Request")
        st.info("🔗 Bạn được chuyển đến từ email thông báo. Vui lòng đăng nhập để tiếp tục.")
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.form("pr_deep_link_login", clear_on_submit=False):
                st.markdown("#### 🔐 Login")
                _dl_user = st.text_input("Username", placeholder="Enter your username")
                _dl_pass = st.text_input("Password", type="password", placeholder="Enter your password")
                _dl_submit = st.form_submit_button("🔑 Login", type="primary", use_container_width=True)
            if _dl_submit:
                if _dl_user and _dl_pass:
                    with st.spinner("Authenticating..."):
                        _ok, _result = auth.authenticate(_dl_user, _dl_pass)
                    if _ok:
                        auth.login(_result)
                        st.success("✅ Login successful!")
                        st.rerun()  # Rerun → now authenticated → deep link handler triggers
                    else:
                        st.error(_result.get("error", "Authentication failed"))
                else:
                    st.warning("Please enter both username and password")
        st.stop()
    else:
        # Normal flow — redirect to main page
        st.warning("⚠️ Please login to access this page")
        st.stop()

user_id    = str(auth.get_user_id())       # users.id as string — for audit (created_by)
emp_int_id = st.session_state.get('employee_id')  # employees.id — for FK requester_id, PM checks
is_admin   = auth.is_admin()

if not emp_int_id:
    st.error("⚠️ Employee ID not found in session. Please re-login.")
    st.stop()


# ── Lookups (cached) ─────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load():
    return (
        get_projects_df(),
        get_employees(),
        get_currencies(),
        get_companies(),
        get_vendor_companies(),
    )

proj_df, employees, currencies, companies, vendors = _load()
emp_map  = {e['id']: e['full_name'] for e in employees}


def _get_employee_email(employee_id: int) -> str:
    """Get employee email by ID. Cached per session."""
    cache_key = f'_emp_email_{employee_id}'
    if cache_key in st.session_state:
        return st.session_state[cache_key]
    try:
        from utils.db import execute_query as _eq
        rows = _eq("SELECT email FROM employees WHERE id = :id LIMIT 1", {'id': employee_id})
        email = rows[0]['email'] if rows else ''
        st.session_state[cache_key] = email
        return email
    except Exception:
        return ''


cur_map  = {c['id']: c['code'] for c in currencies}


# ── CC employee selector (reusable) ──────────────────────────────

@st.cache_data(ttl=300)
def _get_employees_with_email():
    """Get employees with email for CC selector. Cached."""
    from utils.db import execute_query as _eq
    rows = _eq("""
        SELECT id, CONCAT(first_name, ' ', last_name) AS name, email
        FROM employees
        WHERE delete_flag = 0 AND email IS NOT NULL AND email != ''
        ORDER BY first_name, last_name
    """)
    return rows


def _cc_email_selector(key_suffix: str, label: str = "CC (optional)") -> list:
    """
    Multiselect widget to pick CC recipients from employee list.
    Returns list of email strings.
    """
    emp_list = _get_employees_with_email()
    options = [f"{e['name']} ({e['email']})" for e in emp_list]
    selected = st.multiselect(label, options, key=f"cc_sel_{key_suffix}",
                              help="Chọn nhân viên để CC email thông báo")
    # Extract emails from selected labels
    email_map = {f"{e['name']} ({e['email']})": e['email'] for e in emp_list}
    return [email_map[s] for s in selected if s in email_map]


# ── Deep link URL builder ────────────────────────────────────────

def _pr_link(pr_id: int, action: str = 'view') -> str:
    """Build deep link URL for a PR. Returns None if not configured."""
    from utils.il_project.email_notify import build_pr_deep_link
    return build_pr_deep_link(pr_id, action)


# ══════════════════════════════════════════════════════════════════
# DISPLAY CONSTANTS
# ══════════════════════════════════════════════════════════════════

PR_STATUS_ICONS = {
    'DRAFT':              '⚪',
    'SUBMITTED':          '📤',
    'PENDING_APPROVAL':   '🔵',
    'APPROVED':           '✅',
    'REJECTED':           '🔴',
    'REVISION_REQUESTED': '🟡',
    'PO_CREATED':         '🟢',
    'CANCELLED':          '⬛',
}

PRIORITY_ICONS = {
    'LOW': '🔽', 'NORMAL': '➖', 'HIGH': '🔼', 'URGENT': '🔴',
}


# ══════════════════════════════════════════════════════════════════
# HELPER — Vendor selector (consistent with IL_3 pattern)
# ══════════════════════════════════════════════════════════════════

def _vendor_selector(col, current_name: str = "", key_suffix: str = "") -> tuple:
    """Returns (vendor_id, vendor_name)."""
    vendor_names = [v['name'] for v in vendors]
    options = ["(Select later)"] + vendor_names + ["— Enter manually —"]
    if current_name in vendor_names:
        default_idx = options.index(current_name)
    elif current_name:
        default_idx = options.index("— Enter manually —")
    else:
        default_idx = 0
    sel = col.selectbox("Vendor", options, index=default_idx, key=f"vendor_sel_{key_suffix}",
                        help="Chọn từ danh sách hoặc nhập thủ công")
    if sel == "— Enter manually —":
        name = st.text_input("Vendor Name (manual)",
                             value=current_name if current_name not in vendor_names else "",
                             key=f"vendor_manual_{key_suffix}")
        return None, name
    elif sel == "(Select later)":
        return None, ""
    else:
        vid = next((v['id'] for v in vendors if v['name'] == sel), None)
        return vid, sel


# ══════════════════════════════════════════════════════════════════
# HELPER — Approval progress visualization (P3.3)
# ══════════════════════════════════════════════════════════════════

def _render_approval_progress(pr: dict, history: list):
    """Visual approval pipeline: Submit → L1 → L2 → ... → Approved."""
    cur_level = int(pr.get('current_approval_level') or 0)
    max_level = int(pr.get('max_approval_level') or 1)
    status = pr['status']

    # Build step list
    steps = []
    # Submit step
    if status == 'DRAFT':
        steps.append('⚪ Draft')
    else:
        steps.append('✅ Submitted')

    # Approval levels
    approved_levels = set()
    for h in (history or []):
        if h.get('approval_status') == 'APPROVED':
            approved_levels.add(h.get('approval_level', 0))

    # Get chain for approver names
    chain = get_approval_chain(float(pr.get('total_amount_vnd') or 0))
    chain_map = {c['level']: c.get('employee_name', f'L{c["level"]}') for c in chain}

    for lvl in range(1, max_level + 1):
        name = chain_map.get(lvl, f'Level {lvl}')
        short_name = name.split(' ')[-1] if name else f'L{lvl}'  # Last name only
        if lvl in approved_levels:
            steps.append(f'✅ L{lvl} ({short_name})')
        elif status == 'PENDING_APPROVAL' and lvl == cur_level:
            steps.append(f'🔵 **L{lvl} ({short_name})**')
        elif status == 'REJECTED':
            steps.append(f'🔴 L{lvl}')
        elif status == 'REVISION_REQUESTED':
            steps.append(f'🟡 L{lvl}')
        else:
            steps.append(f'⚪ L{lvl}')

    # Final status
    if status == 'APPROVED':
        steps.append('✅ **Approved**')
    elif status == 'PO_CREATED':
        steps.append(f'🟢 **PO: {pr.get("po_number", "")}**')
    elif status == 'REJECTED':
        steps.append('🔴 Rejected')
    elif status == 'REVISION_REQUESTED':
        steps.append('🟡 Revision')

    st.caption(' → '.join(steps))


# ══════════════════════════════════════════════════════════════════
# HELPER — Budget Comparison: Estimate vs PR (with drill-down)
# ══════════════════════════════════════════════════════════════════

_STATUS_ICONS_BUDGET = {'ok': '🟢', 'warning': '🟡', 'over': '🔴', 'empty': '⚪', 'info': '🔵'}
_STATUS_COLORS_BUDGET = {'ok': 'green', 'warning': 'orange', 'over': 'red', 'empty': 'gray', 'info': 'blue'}


def _render_budget_comparison(project_id: int, mode: str = 'full', current_pr_id: int = None):
    """
    Render Estimate vs PR budget comparison with drill-down.

    Args:
        project_id: project to analyze
        mode: 'full' = table + drill-down, 'compact' = progress bar only, 'inline' = table no drill-down
        current_pr_id: highlight this PR in drill-down (optional)
    """
    budget = get_budget_vs_pr(project_id)
    if not budget.get('has_data'):
        return budget  # Return even if empty so caller knows

    # ── Compact mode: just a progress bar ──
    if mode == 'compact':
        t_est = budget['total_estimated']
        t_com = budget['total_committed']
        if t_est > 0:
            pct = t_com / t_est
            bc1, bc2 = st.columns([3, 1])
            bc1.progress(
                min(pct, 1.0),
                text=f"PR Committed: {fmt_vnd(t_com)} / {fmt_vnd(t_est)} ({pct * 100:.0f}%)"
            )
            if pct > 1.0:
                bc2.error(f"⚠️ Over by {fmt_vnd(t_com - t_est)}")
            elif pct > 0.85:
                bc2.warning(f"Remaining: {fmt_vnd(t_est - t_com)}")
            else:
                bc2.caption(f"Remaining: {fmt_vnd(t_est - t_com)}")
        return budget

    # ── Full / Inline mode: comparison table ──
    st.markdown(f"##### 📊 Budget vs PR Committed (Estimate Rev {budget.get('estimate_version', '—')})")

    categories = budget.get('categories', [])
    # Filter out empty rows for display
    visible_cats = [c for c in categories if c['estimated'] > 0 or c['pr_committed'] > 0]

    if not visible_cats:
        st.caption("No budget data or PR activity yet.")
        return budget

    # Build summary table
    rows = []
    for cat in visible_cats:
        icon = _STATUS_ICONS_BUDGET.get(cat['status'], '⚪')
        pct_str = f"{cat['pct_used']:.0f}%"
        rem = cat['remaining']
        rem_str = fmt_vnd(rem) if rem >= 0 else f"**({fmt_vnd(abs(rem))})**"

        rows.append({
            '●': icon,
            'Category': cat['label'],
            'Estimated': f"{cat['estimated']:,.0f}" if cat['estimated'] > 0 else '—',
            'PR Committed': f"{cat['pr_committed']:,.0f}" if cat['pr_committed'] > 0 else '—',
            'Remaining': f"{rem:,.0f}" if rem >= 0 else f"({abs(rem):,.0f})",
            'Used %': pct_str,
            'PRs': cat['pr_count'],
        })

    # Total row
    t = budget
    rows.append({
        '●': '🔴' if t['total_pct_used'] > 100 else '🟡' if t['total_pct_used'] > 85 else '🟢',
        'Category': '**TOTAL**',
        'Estimated': f"{t['total_estimated']:,.0f}",
        'PR Committed': f"{t['total_committed']:,.0f}",
        'Remaining': f"{t['total_remaining']:,.0f}" if t['total_remaining'] >= 0 else f"({abs(t['total_remaining']):,.0f})",
        'Used %': f"{t['total_pct_used']:.0f}%",
        'PRs': None,
    })

    st.dataframe(
        pd.DataFrame(rows), width="stretch", hide_index=True,
        column_config={
            '●': st.column_config.TextColumn('', width=30),
            'Category': st.column_config.TextColumn('Category'),
            'Estimated': st.column_config.TextColumn('Estimated (VND)'),
            'PR Committed': st.column_config.TextColumn('PR Committed (VND)'),
            'Remaining': st.column_config.TextColumn('Remaining (VND)'),
            'Used %': st.column_config.TextColumn('Used %', width=70),
            'PRs': st.column_config.NumberColumn('#PRs', width=55),
        },
    )

    # Legend
    st.caption("🟢 < 85% &nbsp;|&nbsp; 🟡 85–100% &nbsp;|&nbsp; 🔴 > 100% (over budget)")

    # ── Drill-down (full mode only) ──
    if mode == 'full':
        drillable = [c for c in visible_cats if c['pr_count'] > 0]
        if drillable:
            with st.expander("🔍 Drill-down — View PR details by category", expanded=False):
                for cat in drillable:
                    icon = _STATUS_ICONS_BUDGET.get(cat['status'], '⚪')
                    st.markdown(f"**{icon} {cat['label']}** — "
                                f"{fmt_vnd(cat['pr_committed'])} / {fmt_vnd(cat['estimated'])} "
                                f"({cat['pct_used']:.0f}%, {cat['pr_count']} PR{'s' if cat['pr_count'] > 1 else ''})")

                    for pr in cat.get('prs', []):
                        pr_icon = PR_STATUS_ICONS.get(pr['status'], '⚪')
                        is_current = False
                        if current_pr_id:
                            # Can't match by ID directly, match by pr_number approximation
                            pass
                        highlight = '**' if is_current else ''
                        st.caption(
                            f"&nbsp;&nbsp;&nbsp;&nbsp;{pr_icon} {highlight}{pr['pr_number']}{highlight} — "
                            f"{pr.get('vendor', '—')} — {fmt_vnd(pr['amount_vnd'])} "
                            f"({pr['status']})"
                        )

                        # Item-level detail
                        items = pr.get('items', [])
                        if items:
                            item_rows = []
                            for it in items:
                                item_rows.append({
                                    'Product': it.get('desc', ''),
                                    'Qty': f"{it.get('qty', 0):.1f}",
                                    'Unit Cost': f"{it.get('cost', 0):,.2f}",
                                    'CCY': it.get('ccy', ''),
                                    'VND': f"{it.get('vnd', 0):,.0f}",
                                })
                            st.dataframe(
                                pd.DataFrame(item_rows),
                                width="stretch", hide_index=True,
                                height=min(35 * len(item_rows) + 38, 200),
                                column_config={
                                    'Product': st.column_config.TextColumn('Product'),
                                    'Qty': st.column_config.TextColumn('Qty', width=50),
                                    'Unit Cost': st.column_config.TextColumn('Cost', width=100),
                                    'CCY': st.column_config.TextColumn('CCY', width=45),
                                    'VND': st.column_config.TextColumn('VND'),
                                },
                            )
                    st.markdown("---")

    return budget


# ══════════════════════════════════════════════════════════════════
# HELPER — Age indicator (P3.4)
# ══════════════════════════════════════════════════════════════════

def _age_icon(submitted_date) -> str:
    """Return urgency icon based on age since submission."""
    if submitted_date is None:
        return ''
    try:
        if isinstance(submitted_date, str):
            sub_dt = pd.to_datetime(submitted_date)
        else:
            sub_dt = pd.Timestamp(submitted_date)
        if pd.isna(sub_dt):
            return ''
        days = (pd.Timestamp.now() - sub_dt).days
        if days > 7:
            return '🔴'
        if days > 3:
            return '🟡'
        if days > 0:
            return ''
    except Exception:
        pass
    return ''


# ══════════════════════════════════════════════════════════════════
# HELPER — Reusable PR Action Bar (consistent across all views)
# ══════════════════════════════════════════════════════════════════

def _render_pr_action_bar(row, key_prefix: str, show_approve: bool = False):
    """
    Render context-sensitive action buttons for a selected PR row.
    Used by: My PRs, All PRs, Overview, Pending tabs — all views.

    Args:
        row: DataFrame row with pr_id, status, requester_id, project_id, etc.
        key_prefix: unique prefix to avoid widget key conflicts
        show_approve: True for Pending tab — show Review & Act button
    """
    pr_id = int(row['pr_id'])
    status = row['status']
    is_my_pr = (row.get('requester_id') == emp_int_id)
    is_pm = is_project_pm(int(row.get('project_id', 0)), emp_int_id) if row.get('project_id') else False
    has_items = int(row.get('item_count', 0) or 0) > 0
    can_act = is_my_pr or is_pm or is_admin

    # Determine which buttons to show
    buttons = ['view']  # always

    if status in ('DRAFT', 'REVISION_REQUESTED') and can_act:
        buttons.append('edit')
        if has_items:
            buttons.append('submit')
    elif status == 'APPROVED':
        buttons.append('create_po')
    elif status == 'PENDING_APPROVAL':
        if show_approve:
            buttons.append('approve')
        if can_act:
            buttons.append('remind')

    buttons.append('deselect')

    # Render
    cols = st.columns(len(buttons))
    for i, btn in enumerate(buttons):
        if btn == 'view':
            if cols[i].button("👁️ View", type="primary", use_container_width=True,
                              key=f"{key_prefix}_view"):
                st.session_state['open_pr_view'] = pr_id
                st.rerun(scope="app")

        elif btn == 'edit':
            if cols[i].button("✏️ Edit", use_container_width=True,
                              key=f"{key_prefix}_edit"):
                st.session_state['open_pr_edit'] = pr_id
                st.rerun(scope="app")

        elif btn == 'submit':
            if cols[i].button("📤 Submit", use_container_width=True,
                              key=f"{key_prefix}_submit"):
                resolve_product_ids(pr_id)
                result = submit_pr(pr_id, user_id)
                if result['success']:
                    st.success(result['message'])
                    if result.get('approver_name'):
                        pr_full = get_pr(pr_id)
                        if pr_full:
                            _budget = get_budget_vs_pr(int(row.get('project_id', 0)))
                            notify_pr_submitted(
                                pr_number=row['pr_number'],
                                project_code=row.get('project_code', ''),
                                project_name=row.get('project_name', ''),
                                requester_name=row.get('requester_name', ''),
                                total_vnd=float(row.get('total_amount_vnd') or 0),
                                item_count=int(row.get('item_count', 0) or 0),
                                priority=row.get('priority', 'NORMAL'),
                                justification=pr_full.get('justification', ''),
                                approver_name=result['approver_name'],
                                approver_email=result['approver_email'],
                                approval_level=1,
                                max_level=result.get('max_level', 1),
                                requester_email=pr_full.get('requester_email', ''),
                                budget_data=_budget,
                                app_url=_pr_link(pr_id, 'approve'),
                            )
                    st.cache_data.clear()
                    st.rerun(scope="app")
                else:
                    st.error(result['message'])

        elif btn == 'create_po':
            if cols[i].button("🛒 Create PO", use_container_width=True,
                              key=f"{key_prefix}_po"):
                st.session_state['confirm_create_po'] = pr_id
                st.rerun(scope="app")

        elif btn == 'approve':
            if cols[i].button("✅ Review & Act", type="primary", use_container_width=True,
                              key=f"{key_prefix}_approve"):
                st.session_state['open_pr_approve'] = pr_id
                st.rerun(scope="app")

        elif btn == 'remind':
            if cols[i].button("📧 Remind", use_container_width=True,
                              key=f"{key_prefix}_remind"):
                from utils.il_project.pr_queries import get_current_approver
                cur_app = get_current_approver(pr_id)
                if cur_app:
                    pr_full = get_pr(pr_id)
                    _days = 0
                    if row.get('submitted_date'):
                        try:
                            _days = (pd.Timestamp.now() - pd.Timestamp(row['submitted_date'])).days
                        except Exception:
                            pass
                    _budget = get_budget_vs_pr(int(row.get('project_id', 0)))
                    notify_pr_reminder(
                        pr_number=row['pr_number'],
                        project_code=row.get('project_code', ''),
                        total_vnd=float(row.get('total_amount_vnd') or 0),
                        requester_name=row.get('requester_name', ''),
                        requester_email=pr_full.get('requester_email', '') if pr_full else '',
                        approver_name=cur_app['approver_name'],
                        approver_email=cur_app['approver_email'],
                        approval_level=int(row.get('current_approval_level', 1)),
                        max_level=int(row.get('max_approval_level', 1)),
                        days_pending=_days,
                        priority=row.get('priority', 'NORMAL'),
                        justification=pr_full.get('justification', '') if pr_full else '',
                        budget_data=_budget,
                        app_url=_pr_link(pr_id, 'approve'),
                    )
                    st.success(f"📧 Nhắc nhở đã gửi đến **{cur_app['approver_name']}**")
                    st.rerun(scope="app")
                else:
                    st.warning("Không tìm thấy approver hiện tại.")

        elif btn == 'deselect':
            if cols[i].button("✖ Deselect", use_container_width=True,
                              key=f"{key_prefix}_desel"):
                # Bump table version to clear selection
                _ver_key = f'_{key_prefix}_tbl_key'
                st.session_state[_ver_key] = st.session_state.get(_ver_key, 0) + 1
                st.rerun()


def _add_cb_warning_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add 'CB' column to a PR list dataframe showing costbook warning
    for APPROVED PRs that have items missing costbook.
    Batch query — no N+1.
    """
    if df.empty or 'pr_id' not in df.columns:
        return df

    # Only query for APPROVED PRs (the ones that need PO)
    approved_ids = df.loc[df['status'] == 'APPROVED', 'pr_id'].tolist()
    cb_map = {}
    if approved_ids:
        cb_map = get_costbook_warnings_batch([int(x) for x in approved_ids])

    def _cb_icon(row):
        if row['status'] != 'APPROVED':
            return ''
        info = cb_map.get(int(row['pr_id']), {})
        if not info:
            return ''
        no_cb = info.get('without_cb', 0)
        total = info.get('total', 0)
        if no_cb == 0:
            return '✅'
        if no_cb == total:
            return '🔴'   # all items missing costbook
        return '⚠️'       # partial

    result = df.copy()
    result['CB'] = result.apply(_cb_icon, axis=1)
    return result


# ══════════════════════════════════════════════════════════════════
# DIALOGS — Create PR (smart flow: type→auto-suggest, rate auto)
# ══════════════════════════════════════════════════════════════════

# Type → COGS mapping for PR HEADER table
# Header enum: ('A','B','C','D','E','F','MIXED')
# Schema comment: EQUIPMENT=A, FABRICATION=C, SERVICE=D/E, MIXED=multiple
_TYPE_COGS_MAP = {
    'EQUIPMENT':   'A',
    'FABRICATION': 'C',
    'SERVICE':     'D',      # Service/labor → D (Direct Labor) in header
    'MIXED':       'MIXED',
}

# COGS category filter for ESTIMATE ITEMS (items enum: 'A','C','SERVICE')
# Maps header cogs_category → which item categories to look for
_COGS_FILTER_MAP = {
    'A':     ['A'],
    'C':     ['C'],
    'D':     ['SERVICE'],       # Header D → items SERVICE
    'MIXED': ['A', 'C', 'SERVICE'],
}


def _analyze_estimate_for_pr(est_id: int, cogs_filter: list) -> dict:
    """
    Analyze estimate line items for PR auto-fill suggestions.
    Returns: {
        items: list, item_count: int, total_vnd: float,
        dominant_vendor: str, dominant_currency: str,
        vendor_breakdown: dict, preview_rows: list
    }
    """
    all_items = get_importable_estimate_items(est_id)
    # Filter by COGS category
    items = [it for it in all_items
             if it.get('cogs_category', '') in cogs_filter
             and it.get('already_in_pr', 0) == 0]

    if not items:
        return {'items': [], 'item_count': 0, 'total_vnd': 0,
                'dominant_vendor': '', 'dominant_currency': 'VND',
                'vendor_breakdown': {}, 'preview_rows': []}

    # Total VND
    total_vnd = sum(float(it.get('amount_cost_vnd', 0) or 0) for it in items)

    # Vendor breakdown (by total VND)
    vendor_totals: dict = {}
    for it in items:
        vn = (it.get('vendor_name', '') or '').strip()
        if vn:
            vendor_totals[vn] = vendor_totals.get(vn, 0) + float(it.get('amount_cost_vnd', 0) or 0)

    dominant_vendor = max(vendor_totals, key=vendor_totals.get) if vendor_totals else ''

    # Dominant currency (most items)
    cur_counts: dict = {}
    for it in items:
        cc = it.get('cost_currency_code', 'VND') or 'VND'
        cur_counts[cc] = cur_counts.get(cc, 0) + 1
    dominant_currency = max(cur_counts, key=cur_counts.get) if cur_counts else 'VND'

    # Preview rows (top items for display)
    preview_rows = []
    for it in items[:15]:
        preview_rows.append({
            'Cat': it.get('cogs_category', ''),
            'Product': (it.get('item_description', '') or '')[:35],
            'Vendor': (it.get('vendor_name', '') or '')[:20],
            'Qty': it.get('quantity', 0),
            'Cost': f"{it.get('unit_cost', 0):,.2f}",
            'CCY': it.get('cost_currency_code', ''),
            'VND': f"{float(it.get('amount_cost_vnd', 0) or 0):,.0f}",
        })

    return {
        'items': items,
        'item_count': len(items),
        'total_vnd': total_vnd,
        'dominant_vendor': dominant_vendor,
        'dominant_currency': dominant_currency,
        'vendor_breakdown': vendor_totals,
        'preview_rows': preview_rows,
    }


# ══════════════════════════════════════════════════════════════════
# WIZARD — Create PR (multi-step flow)
# ══════════════════════════════════════════════════════════════════
# Steps:  ① Setup (header) → ② Items (import/add/edit) → ③ Review & Confirm
# State:  pr_wiz_*  keys in session_state (cleaned on create or cancel)

def _init_pr_wizard(project_id: int):
    """Initialize wizard state — only if fresh or different project."""
    if st.session_state.get('pr_wiz_pid') != project_id:
        st.session_state.update({
            'pr_wiz_pid':          project_id,
            'pr_wiz_step':         1,
            'pr_wiz_header':       {},
            'pr_wiz_items':        [],      # list[dict] — in-memory items
            'pr_wiz_show_import':  False,
            'pr_wiz_show_add':     False,
            'pr_wiz_edit_idx':     -1,
            'pr_wiz_tbl_ver':      0,       # bump to deselect dataframe
        })


def _cleanup_pr_wizard():
    """Remove all wizard keys + dialog trigger from session_state."""
    for k in [k for k in st.session_state if k.startswith('pr_wiz_')]:
        del st.session_state[k]
    st.session_state.pop('open_create_pr', None)


def _wiz_step_bar(step: int):
    """Render horizontal step indicator."""
    labels = {1: '① Setup', 2: '② Items', 3: '③ Review & Confirm'}
    parts = []
    for i, lbl in labels.items():
        if   i <  step: parts.append(f'✅ ~~{lbl}~~')
        elif i == step: parts.append(f'🔵 **{lbl}**')
        else:           parts.append(f'⚪ {lbl}')
    st.markdown(' &nbsp;→&nbsp; '.join(parts))


@st.dialog("🛒 New Purchase Request", width="large")
def _dialog_create_pr(project_id: int):
    project = get_project(project_id)
    if not project:
        st.error("Project not found."); return
    if not is_project_pm(project_id, emp_int_id) and not is_admin:
        st.warning("Only the PM of this project can create a PR."); return

    _init_pr_wizard(project_id)
    step = st.session_state['pr_wiz_step']

    # ── Project banner (always visible) ──────────────────────────
    st.markdown(f"**Project:** `{project['project_code']}` — {project['project_name']}")
    st.caption(f"Customer: {project.get('customer_name', '—')} | Status: **{project['status']}**")

    est = get_active_estimate(project_id)
    if est:
        est_cogs = float(est.get('total_cogs', 0) or 0)
        if est_cogs > 0:
            st.info(f"💰 Budget: **{fmt_vnd(est_cogs)}** (Rev {est.get('estimate_version', '—')})")

    _wiz_step_bar(step)
    st.divider()

    if   step == 1: _wiz_step1_setup(project_id, project, est)
    elif step == 2: _wiz_step2_items(project_id, project, est)
    elif step == 3: _wiz_step3_review(project_id, project, est)


# ──────────────────────────────────────────────────────────────────
# STEP 1 — Setup (type, vendor, currency, priority …)
# ──────────────────────────────────────────────────────────────────

def _wiz_step1_setup(project_id, project, est):
    header = st.session_state.get('pr_wiz_header', {})

    st.markdown("##### ① PR Setup")

    # ── Reactive selectors (OUTSIDE form — instant rerun) ────
    # Type + COGS
    tc1, tc2 = st.columns(2)
    types = ['EQUIPMENT', 'FABRICATION', 'SERVICE', 'MIXED']
    type_idx = types.index(header['pr_type']) if header.get('pr_type') in types else 0
    pr_type = tc1.selectbox(
        "Type", types, index=type_idx, key="wiz_s1_type",
        help="EQUIPMENT = A (hardware/sensors), FABRICATION = C (racking), "
             "SERVICE = D (labor/consulting), MIXED = multiple categories",
    )
    auto_cogs = _TYPE_COGS_MAP.get(pr_type, 'A')
    _cogs_lbl = {'A': 'A — Equipment', 'C': 'C — Fabrication',
                 'D': 'D — Service/Labor', 'MIXED': 'MIXED'}
    tc2.text_input("COGS Category", value=_cogs_lbl.get(auto_cogs, auto_cogs),
                   disabled=True, help="Auto-set from PR Type")

    # Quick preview of matching estimate items
    if est:
        cogs_filter = _COGS_FILTER_MAP.get(auto_cogs, ['A', 'C', 'SERVICE'])
        analysis = _analyze_estimate_for_pr(est['id'], cogs_filter)
        if analysis['item_count'] > 0:
            st.caption(f"📋 **{analysis['item_count']} estimate items** available "
                       f"for import ({fmt_vnd(analysis['total_vnd'])})")
        else:
            st.caption(f"ℹ️ No importable estimate items for **{auto_cogs}** — "
                       "you can add items manually in the next step.")

    # Currency + Exchange Rate (reactive — updates immediately on change)
    cc1, cc2 = st.columns(2)
    cur_opts = [c['code'] for c in currencies]
    cur_default = header.get('currency_code', 'VND')
    cur_idx = cur_opts.index(cur_default) if cur_default in cur_opts else (
        cur_opts.index('VND') if 'VND' in cur_opts else 0)
    cur_sel = cc1.selectbox("Currency", cur_opts, index=cur_idx, key="wiz_s1_cur")
    currency_id = currencies[cur_opts.index(cur_sel)]['id']

    _rate_res = get_rate_to_vnd(cur_sel)
    exc_rate = _rate_res.rate if _rate_res.ok else 1.0
    if cur_sel != 'VND':
        _badges = {'same': 'ℹ️', 'api': '✅ Live', 'cache': '✅ Cache',
                   'db': '🔵 DB', 'fallback': '⚠️ Fallback'}
        cc2.text_input(
            f"Rate (1 {cur_sel} → VND)",
            value=f"{exc_rate:,.4f}  ({_badges.get(_rate_res.source, _rate_res.source)})",
            disabled=True,
        )
        if not _rate_res.ok:
            st.warning(_rate_res.warning or 'Using reference rate — verify before use.')
    else:
        cc2.text_input("Rate", value="VND — no conversion needed", disabled=True)

    # ── Form fields (submitted together) ─────────────────────
    with st.form("wiz_step1_form"):
        h1, h2 = st.columns(2)
        # Reuse PR number if already generated (user may have gone Back)
        pr_number = header.get('pr_number') or generate_pr_number()
        h1.text_input("PR Number (auto)", value=pr_number, disabled=True)
        priorities = ['NORMAL', 'LOW', 'HIGH', 'URGENT']
        pri_idx = priorities.index(header['priority']) if header.get('priority') in priorities else 0
        priority = h2.selectbox("Priority", priorities, index=pri_idx)

        # Vendor
        vendor_names_list = ["(Select later)"] + [v['name'] for v in vendors]
        vd_idx = 0
        if header.get('vendor_name') and header['vendor_name'] in vendor_names_list:
            vd_idx = vendor_names_list.index(header['vendor_name'])
        vendor_sel = st.selectbox("Primary Vendor", vendor_names_list, index=vd_idx)

        # Date + justification
        req_date = st.date_input("Required Date", value=header.get('required_date'),
                                 help="Ngày cần hàng. Để trống nếu không urgent.")
        justification = st.text_area("Justification / Business Reason",
                                     value=header.get('justification', ''), height=70)

        go_next = st.form_submit_button("Next: Items →", type="primary",
                                        use_container_width=True)

    if go_next:
        vendor_id, vendor_name = None, ''
        if vendor_sel != "(Select later)":
            vendor_name = vendor_sel
            vendor_id = next((v['id'] for v in vendors if v['name'] == vendor_sel), None)

        st.session_state['pr_wiz_header'] = {
            'pr_number':     pr_number,
            'pr_type':       pr_type,
            'cogs_category': auto_cogs,
            'priority':      priority,
            'vendor_id':     vendor_id,
            'vendor_name':   vendor_name,
            'currency_id':   currency_id,
            'currency_code': cur_sel,
            'exchange_rate': exc_rate,
            'required_date': req_date,
            'justification': justification,
            'estimate_id':   est['id'] if est else None,
        }
        st.session_state['pr_wiz_step'] = 2
        st.rerun()


# ──────────────────────────────────────────────────────────────────
# STEP 2 — Items (import / add / edit / delete)
# ──────────────────────────────────────────────────────────────────

def _wiz_step2_items(project_id, project, est):
    header = st.session_state['pr_wiz_header']
    items  = st.session_state['pr_wiz_items']

    st.markdown("##### ② Items")
    st.caption(f"Type: **{header['pr_type']}** | COGS: **{header['cogs_category']}** | "
               f"Vendor: {header.get('vendor_name') or '—'} | "
               f"Currency: **{header['currency_code']}**")

    # ── Action buttons ───────────────────────────────────────
    ab1, ab2, _ab3 = st.columns([1.3, 1.1, 1.5])
    if est and ab1.button("📋 Import from Estimate", use_container_width=True):
        st.session_state['pr_wiz_show_import'] = True
        st.session_state['pr_wiz_show_add']    = False
        st.session_state['pr_wiz_edit_idx']    = -1
        st.rerun()
    if ab2.button("➕ Add Manual Item", use_container_width=True):
        st.session_state['pr_wiz_show_add']    = True
        st.session_state['pr_wiz_show_import'] = False
        st.session_state['pr_wiz_edit_idx']    = -1
        st.rerun()

    # ── Import panel ─────────────────────────────────────────
    if st.session_state.get('pr_wiz_show_import') and est:
        _wiz_import_panel(est, header, items)

    # ── Add manual panel ─────────────────────────────────────
    if st.session_state.get('pr_wiz_show_add'):
        _wiz_add_panel(header, items)

    # ── Items table ──────────────────────────────────────────
    st.divider()
    if items:
        rows = []
        _no_cb_count = 0
        for i, it in enumerate(items):
            has_cb = bool(it.get('costbook_detail_id'))
            if not has_cb:
                _no_cb_count += 1
            rows.append({
                '#': i + 1,
                'Cat':     it.get('cogs_category', ''),
                'Description': (it.get('item_description', '') or '')[:45],
                'Vendor':  (it.get('vendor_name', '') or '')[:25],
                'Qty':     f"{it.get('quantity', 0):.1f}",
                'Unit Cost': f"{it.get('unit_cost', 0):,.2f}",
                'CCY':     it.get('currency_code', ''),
                'VND':     f"{float(it.get('amount_vnd', 0)):,.0f}",
                'CB':      '✅' if has_cb else '⚠️',
                'Source':  '📋' if it.get('estimate_line_item_id') else '✏️',
            })

        # Warning if items missing costbook
        if _no_cb_count > 0:
            st.warning(f"⚠️ **{_no_cb_count}/{len(items)} item(s) thiếu costbook link** — "
                       f"Các item này sẽ KHÔNG được đưa vào PO. "
                       f"Tạo vendor costbook (Vendor Quotation) trước khi convert sang PO.")

        tbl_key = f"wiz_items_{st.session_state.get('pr_wiz_tbl_ver', 0)}"
        event = st.dataframe(
            pd.DataFrame(rows), key=tbl_key, width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            height=min(35 * len(rows) + 38, 320),
            column_config={
                '#':          st.column_config.NumberColumn('#', width=40),
                'Cat':        st.column_config.TextColumn('Cat', width=50),
                'Description':st.column_config.TextColumn('Description'),
                'Vendor':     st.column_config.TextColumn('Vendor'),
                'Qty':        st.column_config.TextColumn('Qty', width=55),
                'Unit Cost':  st.column_config.TextColumn('Cost'),
                'CCY':        st.column_config.TextColumn('CCY', width=45),
                'VND':        st.column_config.TextColumn('VND'),
                'CB':         st.column_config.TextColumn('CB', width=30,
                              help='Costbook: ✅ = linked, ⚠️ = missing (cannot go to PO)'),
                'Source':     st.column_config.TextColumn('', width=30),
            },
        )

        total_vnd = sum(float(it.get('amount_vnd', 0) or 0) for it in items)
        st.markdown(f"**Total: {fmt_vnd(total_vnd)}** &nbsp;·&nbsp; {len(items)} items "
                    f"&nbsp;·&nbsp; 📋 = estimate &nbsp; ✏️ = manual "
                    f"&nbsp;·&nbsp; CB: ✅ = costbook linked &nbsp; ⚠️ = no costbook")

        # ── Selected-item actions ────────────────────────────
        sel = event.selection.rows
        if sel:
            idx = sel[0]
            sel_item = items[idx]
            sc1, sc2, sc3 = st.columns([3, 1, 1])
            sc1.caption(f"**#{idx+1}** — {sel_item.get('item_description', '')[:50]}")
            if sc2.button("✏️ Edit", use_container_width=True, key="wiz_edit_sel"):
                st.session_state['pr_wiz_edit_idx'] = idx
                st.session_state['pr_wiz_show_import'] = False
                st.session_state['pr_wiz_show_add'] = False
                st.rerun()
            if sc3.button("🗑 Remove", use_container_width=True, key="wiz_rm_sel"):
                items.pop(idx)
                st.session_state['pr_wiz_items'] = items
                st.session_state['pr_wiz_tbl_ver'] = st.session_state.get('pr_wiz_tbl_ver', 0) + 1
                st.rerun()

        # ── Inline edit form ─────────────────────────────────
        edit_idx = st.session_state.get('pr_wiz_edit_idx', -1)
        if 0 <= edit_idx < len(items):
            _wiz_edit_panel(items, edit_idx)

    else:
        st.info("No items yet.  Use **📋 Import from Estimate** or **➕ Add Manual Item** above.")

    # ── Navigation ───────────────────────────────────────────
    st.divider()
    n1, _n2, n3 = st.columns([1, 2, 1])
    if n1.button("← Back", use_container_width=True, key="wiz_back_2"):
        st.session_state['pr_wiz_step'] = 1
        st.rerun()
    if items:
        if n3.button("Next: Review →", type="primary", use_container_width=True, key="wiz_next_2"):
            st.session_state['pr_wiz_step'] = 3
            st.session_state['pr_wiz_show_import'] = False
            st.session_state['pr_wiz_show_add']    = False
            st.session_state['pr_wiz_edit_idx']    = -1
            st.rerun()
    else:
        n3.button("Next: Review →", disabled=True, use_container_width=True,
                  key="wiz_next_2_dis", help="Add at least one item to continue")


# ── Step 2 sub-panels ────────────────────────────────────────────

def _wiz_import_panel(est, header, items):
    """Collapsible panel: import estimate items into wizard."""
    with st.container(border=True):
        st.markdown("**📋 Import from Estimate**")
        cogs_filter = _COGS_FILTER_MAP.get(header['cogs_category'], ['A', 'C', 'SERVICE'])
        all_avail = _analyze_estimate_for_pr(est['id'], cogs_filter).get('items', [])

        # Exclude items already in wizard list
        existing_elis = {it['estimate_line_item_id']
                         for it in items if it.get('estimate_line_item_id')}
        avail = [it for it in all_avail if it.get('estimate_line_item_id') not in existing_elis]

        if not avail:
            st.caption("✅ All matching estimate items already added (or none available).")
            if st.button("Close", key="wiz_imp_close"):
                st.session_state['pr_wiz_show_import'] = False
                st.rerun()
            return

        # Preview table
        preview = []
        for it in avail:
            preview.append({
                'Cat':     it.get('cogs_category', ''),
                'Product': (it.get('item_description', '') or '')[:40],
                'Vendor':  (it.get('vendor_name', '') or '')[:25],
                'Qty':     it.get('quantity', 0),
                'Cost':    f"{it.get('unit_cost', 0):,.2f}",
                'CCY':     it.get('cost_currency_code', ''),
                'VND':     f"{float(it.get('amount_cost_vnd', 0) or 0):,.0f}",
            })
        st.dataframe(pd.DataFrame(preview), width="stretch", hide_index=True,
                     height=min(35 * len(preview) + 38, 250))

        total = sum(float(it.get('amount_cost_vnd', 0) or 0) for it in avail)

        ic1, ic2 = st.columns([2, 1])
        if ic1.button(f"✅ Import {len(avail)} items ({fmt_vnd(total)})",
                      type="primary", use_container_width=True, key="wiz_do_import"):
            for it in avail:
                items.append({
                    'estimate_line_item_id': it.get('estimate_line_item_id'),
                    'costbook_detail_id':    it.get('costbook_detail_id'),
                    'product_id':            it.get('product_id'),
                    'cogs_category':         it.get('cogs_category', 'A'),
                    'item_description':      it.get('item_description', ''),
                    'brand_name':            it.get('brand_name', ''),
                    'pt_code':               it.get('pt_code', ''),
                    'vendor_id':             None,
                    'vendor_name':           it.get('vendor_name', ''),
                    'vendor_quote_ref':      it.get('vendor_quote_ref', ''),
                    'quantity':              float(it.get('quantity', 1) or 1),
                    'uom':                   it.get('uom', 'Pcs'),
                    'unit_cost':             float(it.get('unit_cost', 0) or 0),
                    'currency_id':           it.get('cost_currency_id'),
                    'currency_code':         it.get('cost_currency_code', 'VND'),
                    'exchange_rate':         float(it.get('cost_exchange_rate', 1) or 1),
                    'amount_vnd':            float(it.get('amount_cost_vnd', 0) or 0),
                    'specifications':        None,
                    'notes':                 'Imported from estimate',
                })
            st.session_state['pr_wiz_items'] = items
            st.session_state['pr_wiz_show_import'] = False
            st.session_state['pr_wiz_tbl_ver'] = st.session_state.get('pr_wiz_tbl_ver', 0) + 1
            st.rerun()
        if ic2.button("Cancel", use_container_width=True, key="wiz_imp_cancel"):
            st.session_state['pr_wiz_show_import'] = False
            st.rerun()


def _wiz_add_panel(header, items):
    """Inline form to add a manual item to the wizard list."""
    with st.container(border=True):
        st.markdown("**➕ Add Manual Item**")
        with st.form("wiz_add_item_form"):
            m1, m2 = st.columns(2)
            cat  = m1.selectbox("COGS Category", ['A', 'C', 'SERVICE'], key="wiz_add_cat")
            desc = m2.text_input("Description *", key="wiz_add_desc")

            m3, m4, m5 = st.columns(3)
            qty  = m3.number_input("Qty",       value=1.0, min_value=0.01, format="%.2f", key="wiz_add_qty")
            cost = m4.number_input("Unit Cost",  value=0.0, format="%.2f",                 key="wiz_add_cost")
            uom  = m5.text_input("UOM",          value="Pcs",                              key="wiz_add_uom")

            m6, m7 = st.columns(2)
            vn_list    = ["(None)"] + [v['name'] for v in vendors]
            vendor_sel = m6.selectbox("Vendor", vn_list, key="wiz_add_vendor")
            vendor_ref = m7.text_input("Quote Ref",      key="wiz_add_ref")

            specs = st.text_input("Specifications", key="wiz_add_specs")

            if cost > 0 and qty > 0:
                line_vnd = qty * cost * header['exchange_rate']
                st.caption(f"💰 Line total: **{fmt_vnd(line_vnd)}**")

            fc1, fc2 = st.columns(2)
            add_ok = fc1.form_submit_button("➕ Add Item", type="primary", use_container_width=True)
            cancel_add = fc2.form_submit_button("Cancel", use_container_width=True)

        if cancel_add:
            st.session_state['pr_wiz_show_add'] = False
            st.rerun()

        if add_ok:
            if not desc:
                st.error("Description is required."); return
            if cost <= 0:
                st.error("Unit cost must be > 0."); return

            v_id, v_name = None, ''
            if vendor_sel != "(None)":
                v_name = vendor_sel
                v_id   = next((v['id'] for v in vendors if v['name'] == vendor_sel), None)

            items.append({
                'estimate_line_item_id': None,
                'costbook_detail_id':    None,
                'product_id':            None,
                'cogs_category':         cat,
                'item_description':      desc,
                'brand_name':            '',
                'pt_code':               '',
                'vendor_id':             v_id,
                'vendor_name':           v_name,
                'vendor_quote_ref':      vendor_ref or '',
                'quantity':              qty,
                'uom':                   uom,
                'unit_cost':             cost,
                'currency_id':           header['currency_id'],
                'currency_code':         header['currency_code'],
                'exchange_rate':         header['exchange_rate'],
                'amount_vnd':            round(qty * cost * header['exchange_rate'], 0),
                'specifications':        specs or None,
                'notes':                 'Manual entry',
            })
            st.session_state['pr_wiz_items']    = items
            st.session_state['pr_wiz_show_add'] = False
            st.session_state['pr_wiz_tbl_ver']  = st.session_state.get('pr_wiz_tbl_ver', 0) + 1
            st.rerun()


def _wiz_edit_panel(items, idx):
    """Inline form to edit an existing wizard item."""
    eit = items[idx]
    with st.container(border=True):
        st.markdown(f"**✏️ Edit Item #{idx + 1}**")
        with st.form("wiz_edit_item_form"):
            e1, e2 = st.columns(2)
            e_desc = e1.text_input("Description", value=eit.get('item_description', ''))
            cogs_opts = ['A', 'C', 'SERVICE']
            e_cat = e2.selectbox("COGS", cogs_opts,
                                 index=cogs_opts.index(eit['cogs_category'])
                                 if eit.get('cogs_category') in cogs_opts else 0)

            e3, e4, e5 = st.columns(3)
            e_qty  = e3.number_input("Qty",  value=float(eit.get('quantity', 1)), format="%.2f")
            e_cost = e4.number_input("Cost", value=float(eit.get('unit_cost', 0)), format="%.2f")
            e_uom  = e5.text_input("UOM",    value=eit.get('uom', 'Pcs'))

            e6, e7 = st.columns(2)
            vn_list    = ["(None)"] + [v['name'] for v in vendors]
            vn_current = eit.get('vendor_name', '')
            vn_idx     = vn_list.index(vn_current) if vn_current in vn_list else 0
            e_vendor   = e6.selectbox("Vendor", vn_list, index=vn_idx, key="wiz_edit_vendor")
            e_ref      = e7.text_input("Quote Ref", value=eit.get('vendor_quote_ref', ''))
            e_spec     = st.text_input("Specifications", value=eit.get('specifications') or '')

            rate = float(eit.get('exchange_rate', 1) or 1)
            if e_cost > 0 and e_qty > 0:
                st.caption(f"💰 Line total: **{fmt_vnd(e_qty * e_cost * rate)}**")

            sc1, sc2 = st.columns(2)
            save_ok    = sc1.form_submit_button("💾 Save", type="primary", use_container_width=True)
            cancel_ok  = sc2.form_submit_button("Cancel", use_container_width=True)

        if cancel_ok:
            st.session_state['pr_wiz_edit_idx'] = -1
            st.rerun()

        if save_ok:
            v_id, v_name = None, ''
            if e_vendor != "(None)":
                v_name = e_vendor
                v_id   = next((v['id'] for v in vendors if v['name'] == e_vendor), None)

            items[idx].update({
                'item_description': e_desc,
                'cogs_category':    e_cat,
                'quantity':         e_qty,
                'unit_cost':        e_cost,
                'uom':              e_uom,
                'vendor_id':        v_id,
                'vendor_name':      v_name,
                'vendor_quote_ref': e_ref,
                'specifications':   e_spec or None,
                'amount_vnd':       round(e_qty * e_cost * rate, 0),
            })
            st.session_state['pr_wiz_items']   = items
            st.session_state['pr_wiz_edit_idx'] = -1
            st.session_state['pr_wiz_tbl_ver']  = st.session_state.get('pr_wiz_tbl_ver', 0) + 1
            st.rerun()


# ──────────────────────────────────────────────────────────────────
# STEP 3 — Review & Confirm
# ──────────────────────────────────────────────────────────────────

def _wiz_step3_review(project_id, project, est):
    header = st.session_state['pr_wiz_header']
    items  = st.session_state['pr_wiz_items']
    total_vnd = sum(float(it.get('amount_vnd', 0) or 0) for it in items)

    st.markdown("##### ③ Review & Confirm")

    # ── PR Summary card ──────────────────────────────────────
    with st.container(border=True):
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("PR Number", header['pr_number'])
        s2.metric("Items", len(items))
        s3.metric("Total VND", fmt_vnd(total_vnd))
        s4.metric("Priority", f"{PRIORITY_ICONS.get(header['priority'], '')} {header['priority']}")

        st.caption(
            f"Type: **{header['pr_type']}** | COGS: **{header['cogs_category']}** | "
            f"Vendor: {header.get('vendor_name') or '—'} | Currency: **{header['currency_code']}** | "
            f"Rate: {header['exchange_rate']:,.2f}"
        )
        if header.get('justification'):
            st.caption(f"📝 {header['justification']}")
        if header.get('required_date'):
            st.caption(f"📅 Required: {header['required_date']}")

    # ── Items table (read-only) — with costbook status ─────
    st.divider()
    _items_with_cb = [it for it in items if it.get('costbook_detail_id')]
    _items_no_cb = [it for it in items if not it.get('costbook_detail_id')]
    _no_cb_vnd = sum(float(it.get('amount_vnd', 0) or 0) for it in _items_no_cb)

    if _items_no_cb:
        st.warning(
            f"⚠️ **{len(_items_no_cb)}/{len(items)} item(s) thiếu costbook link** "
            f"({fmt_vnd(_no_cb_vnd)})\n\n"
            f"Các item thiếu costbook sẽ **KHÔNG** được đưa vào PO. "
            f"Tạo vendor costbook (Vendor Quotation) cho các sản phẩm này trước khi convert sang PO."
        )

    st.markdown("**📋 Line Items**")
    rows = []
    for it in items:
        has_cb = bool(it.get('costbook_detail_id'))
        rows.append({
            'CB':          '✅' if has_cb else '⚠️',
            'Cat':         it.get('cogs_category', ''),
            'Description': it.get('item_description', ''),
            'Vendor':      (it.get('vendor_name', '') or '')[:25],
            'Qty':         f"{it.get('quantity', 0):.1f}",
            'Unit Cost':   f"{it.get('unit_cost', 0):,.2f}",
            'CCY':         it.get('currency_code', ''),
            'Amount VND':  f"{float(it.get('amount_vnd', 0)):,.0f}",
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True,
                 height=min(35 * len(rows) + 38, 300))

    # ── Budget Comparison (Estimate vs Existing PRs + This PR) ─
    if est:
        st.divider()
        st.markdown("**📊 Budget Impact — Estimate vs PR Committed + This PR**")

        budget = get_budget_vs_pr(project_id)

        # Aggregate this PR by COGS category
        pr_by_cat: dict = {}
        for it in items:
            cat = it.get('cogs_category', 'A') or 'A'
            # SERVICE items → map to D for budget comparison
            if cat == 'SERVICE':
                cat = 'D'
            pr_by_cat[cat] = pr_by_cat.get(cat, 0) + float(it.get('amount_vnd', 0) or 0)

        if budget.get('has_data'):
            comp_rows = []
            for cat_data in budget['categories']:
                cat = cat_data['category']
                if cat not in ('A', 'B', 'C', 'D', 'E', 'F'):
                    continue

                estimated     = cat_data['estimated']
                prev_committed = cat_data['pr_committed']
                this_pr       = pr_by_cat.get(cat, 0)
                new_total     = prev_committed + this_pr
                remaining     = estimated - new_total
                pct           = (new_total / estimated * 100) if estimated > 0 else (100.0 if new_total > 0 else 0)

                if   estimated <= 0 and new_total <= 0: icon = '⚪'
                elif pct > 100: icon = '🔴'
                elif pct > 85:  icon = '🟡'
                else:           icon = '🟢'

                comp_rows.append({
                    '●':         icon,
                    'Category':  cat_data['label'],
                    'Estimated': f"{estimated:,.0f}" if estimated > 0 else '—',
                    'Prev PRs':  f"{prev_committed:,.0f}" if prev_committed > 0 else '—',
                    '⭐ This PR': f"{this_pr:,.0f}" if this_pr > 0 else '—',
                    'New Total': f"{new_total:,.0f}" if new_total > 0 else '—',
                    'Remaining': f"{remaining:,.0f}" if remaining >= 0 else f"({abs(remaining):,.0f})",
                    'Used %':    f"{pct:.0f}%",
                })

            # Totals
            t_est  = budget['total_estimated']
            t_prev = budget['total_committed']
            t_this = total_vnd
            t_new  = t_prev + t_this
            t_rem  = t_est  - t_new
            t_pct  = (t_new / t_est * 100) if t_est > 0 else 0
            comp_rows.append({
                '●':          '🔴' if t_pct > 100 else '🟡' if t_pct > 85 else '🟢',
                'Category':   '**TOTAL**',
                'Estimated':  f"{t_est:,.0f}",
                'Prev PRs':   f"{t_prev:,.0f}",
                '⭐ This PR':  f"{t_this:,.0f}",
                'New Total':  f"{t_new:,.0f}",
                'Remaining':  f"{t_rem:,.0f}" if t_rem >= 0 else f"({abs(t_rem):,.0f})",
                'Used %':     f"{t_pct:.0f}%",
            })

            st.dataframe(
                pd.DataFrame(comp_rows), width="stretch", hide_index=True,
                column_config={
                    '●':          st.column_config.TextColumn('', width=30),
                    'Category':   st.column_config.TextColumn('Category'),
                    'Estimated':  st.column_config.TextColumn('Estimated'),
                    'Prev PRs':   st.column_config.TextColumn('Prev PRs'),
                    '⭐ This PR':  st.column_config.TextColumn('⭐ This PR'),
                    'New Total':  st.column_config.TextColumn('New Total'),
                    'Remaining':  st.column_config.TextColumn('Remaining'),
                    'Used %':     st.column_config.TextColumn('Used %', width=70),
                },
            )

            # Warnings
            if t_pct > 100:
                st.error(f"⚠️ **Over budget!** Tổng committed sẽ vượt estimate "
                         f"**{fmt_vnd(abs(t_rem))}**")
            elif t_pct > 85:
                st.warning(f"⚠️ Budget gần giới hạn — còn lại **{fmt_vnd(t_rem)}** sau PR này")

            st.caption("🟢 < 85% &nbsp;|&nbsp; 🟡 85–100% &nbsp;|&nbsp; 🔴 > 100% (over budget)")
        else:
            st.caption("ℹ️ No active estimate — budget comparison unavailable.")

    # ── Approval Chain Preview ─────────────────────────────────
    st.divider()
    st.markdown("**📧 Approval Flow**")
    chain = get_approval_chain(total_vnd)
    has_chain = bool(chain)
    if has_chain:
        max_level = determine_max_level(total_vnd, chain)
        chain_parts = []
        for entry in chain:
            lvl = entry['level']
            name = entry.get('employee_name', f'L{lvl}')
            email = entry.get('email', '')
            if lvl <= max_level:
                if lvl == 1:
                    chain_parts.append(f"📧 **L{lvl} — {name}** ({email})")
                else:
                    chain_parts.append(f"⏳ L{lvl} — {name}")
        st.caption(' &nbsp;→&nbsp; '.join(chain_parts))
        st.caption(f"Cần **{max_level} level** phê duyệt cho **{fmt_vnd(total_vnd)}**. "
                   f"Email sẽ gửi đến **{chain[0].get('employee_name', '')}** ngay khi submit.")
    else:
        st.warning("⚠️ Chưa cấu hình approval chain cho IL_PURCHASE_REQUEST. "
                   "PR sẽ lưu Draft — không thể submit.")

    # ── CC Recipients (optional) ─────────────────────────────
    _wiz_cc = _cc_email_selector("wiz_step3", label="📧 CC thêm (optional)")

    # ── Navigation ───────────────────────────────────────────
    st.divider()
    n1, n2, n3 = st.columns([1, 1, 1.5])
    if n1.button("← Back to Items", use_container_width=True, key="wiz_back_3"):
        st.session_state['pr_wiz_step'] = 2
        st.rerun()
    if n2.button("💾 Save as Draft", use_container_width=True, key="wiz_save_draft"):
        _wiz_do_create(project_id, project, est, submit_now=False)
    if has_chain:
        if n3.button("✅ Create & Submit for Approval", type="primary",
                     use_container_width=True, key="wiz_confirm_submit"):
            _wiz_do_create(project_id, project, est, submit_now=True, cc_emails=_wiz_cc)
    else:
        n3.button("✅ Create & Submit", disabled=True,
                  use_container_width=True, key="wiz_confirm_submit_dis",
                  help="Approval chain chưa được cấu hình")


# ──────────────────────────────────────────────────────────────────
# WIZARD — Create PR in DB + optional submit
# ──────────────────────────────────────────────────────────────────

def _wiz_do_create(project_id, project, est, submit_now: bool = False, cc_emails: list = None):
    """Insert PR header + all items into DB.  Optionally submit for approval."""
    header = st.session_state['pr_wiz_header']
    items  = st.session_state['pr_wiz_items']

    try:
        # 0. Pre-validate all FK values before INSERT ──────────
        from utils.db import execute_query as _eq

        estimate_id = header.get('estimate_id')
        if estimate_id:
            chk = _eq("SELECT id FROM il_project_cogs_estimate WHERE id = :id AND delete_flag = 0",
                       {'id': estimate_id})
            if not chk:
                logger.warning(f"estimate_id={estimate_id} invalid FK — setting NULL")
                estimate_id = None

        vendor_id = header.get('vendor_id')
        if vendor_id:
            chk = _eq("SELECT id FROM companies WHERE id = :id AND delete_flag = 0",
                       {'id': vendor_id})
            if not chk:
                logger.warning(f"vendor_id={vendor_id} invalid FK — setting NULL")
                vendor_id = None

        currency_id = header.get('currency_id')
        if currency_id:
            chk = _eq("SELECT id FROM currencies WHERE id = :id AND delete_flag = 0",
                       {'id': currency_id})
            if not chk:
                st.error(f"❌ currency_id={currency_id} not found."); return

        # Re-generate PR number (another user may have taken it since Step 1)
        pr_number = generate_pr_number()

        logger.info(
            f"PR wizard INSERT: project={project_id}, requester={emp_int_id}, "
            f"estimate={estimate_id}, vendor={vendor_id}, "
            f"currency={currency_id} ({header.get('currency_code')}), "
            f"rate={header.get('exchange_rate')}"
        )

        # 1. Create header ─────────────────────────────────────
        new_id = create_pr({
            'pr_number':     pr_number,
            'project_id':    project_id,
            'requester_id':  emp_int_id,
            'estimate_id':   estimate_id,
            'vendor_id':     vendor_id,
            'vendor_contact_id': None,
            'currency_id':   currency_id,
            'exchange_rate': header['exchange_rate'],
            'priority':      header['priority'],
            'pr_type':       header['pr_type'],
            'cogs_category': header['cogs_category'],
            'required_date': header.get('required_date') or None,
            'justification': header.get('justification') or None,
        }, user_id)

        # 2. Create items ──────────────────────────────────────
        for i, it in enumerate(items):
            create_pr_item({
                'pr_id':                 new_id,
                'estimate_line_item_id': it.get('estimate_line_item_id'),
                'costbook_detail_id':    it.get('costbook_detail_id'),
                'product_id':            it.get('product_id'),
                'item_description':      it.get('item_description', ''),
                'brand_name':            it.get('brand_name', ''),
                'pt_code':               it.get('pt_code', ''),
                'vendor_id':             it.get('vendor_id'),
                'vendor_name':           it.get('vendor_name', ''),
                'vendor_quote_ref':      it.get('vendor_quote_ref', ''),
                'quantity':              it.get('quantity', 1),
                'uom':                   it.get('uom', 'Pcs'),
                'unit_cost':             it.get('unit_cost', 0),
                'currency_id':           it.get('currency_id') or header['currency_id'],
                'exchange_rate':         it.get('exchange_rate', header['exchange_rate']),
                'cogs_category':         it.get('cogs_category', 'A'),
                'specifications':        it.get('specifications'),
                'notes':                 it.get('notes'),
                'view_order':            i,
            }, user_id)

        # 3. Recalc totals ─────────────────────────────────────
        recalc_pr_totals(new_id)

        total_vnd = sum(float(it.get('amount_vnd', 0) or 0) for it in items)

        # 4. Optionally submit ─────────────────────────────────
        if submit_now:
            resolve_product_ids(new_id)  # auto-link costbook before submit
            result = submit_pr(new_id, user_id)
            if result['success']:
                st.success(f"✅ **{pr_number}** created ({len(items)} items, "
                           f"{fmt_vnd(total_vnd)}) and **submitted for approval**.")
                if result.get('approver_name'):
                    st.info(f"📧 Pending approval: **{result['approver_name']}** "
                            f"(Level 1/{result.get('max_level', 1)})")
                    # Send email
                    _budget = get_budget_vs_pr(project_id)
                    notify_pr_submitted(
                        pr_number=pr_number,
                        project_code=project.get('project_code', ''),
                        project_name=project.get('project_name', ''),
                        requester_name=emp_map.get(emp_int_id, ''),
                        total_vnd=total_vnd,
                        item_count=len(items),
                        priority=header['priority'],
                        justification=header.get('justification', ''),
                        approver_name=result['approver_name'],
                        approver_email=result['approver_email'],
                        approval_level=1,
                        max_level=result.get('max_level', 1),
                        requester_email=_get_employee_email(emp_int_id),
                        cc_emails=cc_emails,
                        budget_data=_budget,
                        app_url=_pr_link(new_id, 'approve'),
                    )
            else:
                st.warning(f"PR created as Draft — submit failed: {result['message']}")
        else:
            st.success(f"✅ **{pr_number}** saved as Draft "
                       f"({len(items)} items, {fmt_vnd(total_vnd)}).")

        # 5. Cleanup & navigate ────────────────────────────────
        _cleanup_pr_wizard()
        st.cache_data.clear()
        st.session_state['open_pr_view'] = new_id
        st.rerun()

    except Exception as e:
        err_str = str(e)
        # Safely get variables that may not have been assigned before the error
        _est_id = header.get('estimate_id')
        _vendor_id = header.get('vendor_id')
        _currency_id = header.get('currency_id')
        _pr_number = locals().get('pr_number', '(not generated)')

        # FK constraint failure — retry without optional FKs
        if 'IntegrityError' in err_str and '1216' in err_str:
            logger.warning(f"FK constraint failed — retrying without estimate/vendor: {e}")
            try:
                retry_pr_number = generate_pr_number()
                new_id = create_pr({
                    'pr_number':     retry_pr_number,
                    'project_id':    project_id,
                    'requester_id':  emp_int_id,
                    'estimate_id':   None,       # ← skip
                    'vendor_id':     None,        # ← skip
                    'vendor_contact_id': None,
                    'currency_id':   _currency_id,
                    'exchange_rate': header['exchange_rate'],
                    'priority':      header['priority'],
                    'pr_type':       header['pr_type'],
                    'cogs_category': header['cogs_category'],
                    'required_date': header.get('required_date') or None,
                    'justification': header.get('justification') or None,
                }, user_id)

                for i, it in enumerate(items):
                    try:
                        create_pr_item({
                            'pr_id': new_id,
                            'estimate_line_item_id': None,  # ← skip FK
                            'costbook_detail_id': None,     # ← skip FK
                            'product_id': None,             # ← skip FK
                            'item_description': it.get('item_description', ''),
                            'brand_name': it.get('brand_name', ''),
                            'pt_code': it.get('pt_code', ''),
                            'vendor_id': None,
                            'vendor_name': it.get('vendor_name', ''),
                            'vendor_quote_ref': it.get('vendor_quote_ref', ''),
                            'quantity': it.get('quantity', 1),
                            'uom': it.get('uom', 'Pcs'),
                            'unit_cost': it.get('unit_cost', 0),
                            'currency_id': it.get('currency_id') or _currency_id,
                            'exchange_rate': it.get('exchange_rate', header['exchange_rate']),
                            'cogs_category': it.get('cogs_category', 'A'),
                            'specifications': it.get('specifications'),
                            'notes': it.get('notes'),
                            'view_order': i,
                        }, user_id)
                    except Exception:
                        pass

                recalc_pr_totals(new_id)
                st.warning(f"⚠️ PR created but estimate/vendor link skipped (FK constraint). "
                           f"Please update manually in Edit mode.")
                _cleanup_pr_wizard()
                st.cache_data.clear()
                st.session_state['open_pr_edit'] = new_id
                st.rerun()

            except Exception as e2:
                st.error(f"❌ Retry also failed: {e2}")
                logger.error(f"PR wizard retry failed: {e2}")
        else:
            st.error(f"❌ Creation failed: {e}")
            logger.error(f"PR wizard create failed: {e}")
            # Debug info for troubleshooting
            with st.expander("🔧 Debug Info"):
                st.code(f"project_id: {project_id}\n"
                        f"requester_id: {emp_int_id}\n"
                        f"estimate_id: {_est_id}\n"
                        f"vendor_id: {_vendor_id}\n"
                        f"currency_id: {_currency_id}\n"
                        f"currency_code: {header.get('currency_code')}\n"
                        f"exchange_rate: {header.get('exchange_rate')}\n"
                        f"pr_number: {_pr_number}\n"
                        f"error: {err_str}")


# ══════════════════════════════════════════════════════════════════
# DIALOGS — Import Estimate Items
# ══════════════════════════════════════════════════════════════════

@st.dialog("📋 Import from Estimate", width="large")
def _dialog_import_estimate(pr_id: int, estimate_id: int):
    items = get_importable_estimate_items(estimate_id)
    if not items:
        st.info("No estimate line items found."); return

    st.markdown(f"**{len(items)} items** from active estimate")

    rows = []
    for it in items:
        already = it.get('already_in_pr', 0) > 0
        rows.append({
            'Cat': it['cogs_category'],
            'Product': (it.get('item_description', '') or '')[:40],
            'Brand': it.get('brand_name', ''),
            'Vendor': (it.get('vendor_name', '') or '')[:25],
            'Qty': it.get('quantity', 0),
            'Cost': f"{it.get('unit_cost', 0):,.2f}",
            'CCY': it.get('cost_currency_code', ''),
            'VND': f"{it.get('amount_cost_vnd', 0):,.0f}",
            'In PR': '✅' if already else '',
        })

    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=min(35*len(rows)+38, 400))

    available = [it for it in items if it.get('already_in_pr', 0) == 0]
    st.caption(f"**{len(available)}** available for import ({len(items) - len(available)} already in PR)")

    if available:
        if st.button(f"📦 Import {len(available)} items", type="primary", use_container_width=True):
            count = 0
            for i, it in enumerate(available):
                try:
                    create_pr_item({
                        'pr_id': pr_id,
                        'estimate_line_item_id': it['estimate_line_item_id'],
                        'costbook_detail_id': it.get('costbook_detail_id'),
                        'product_id': it.get('product_id'),
                        'item_description': it.get('item_description', ''),
                        'brand_name': it.get('brand_name', ''),
                        'pt_code': it.get('pt_code', ''),
                        'vendor_id': None,
                        'vendor_name': it.get('vendor_name', ''),
                        'vendor_quote_ref': it.get('vendor_quote_ref', ''),
                        'quantity': it.get('quantity', 1),
                        'uom': it.get('uom', 'Pcs'),
                        'unit_cost': it.get('unit_cost', 0),
                        'currency_id': it.get('cost_currency_id'),
                        'exchange_rate': it.get('cost_exchange_rate', 1),
                        'cogs_category': it.get('cogs_category', 'A'),
                        'specifications': None,
                        'notes': 'Imported from estimate',
                        'view_order': i,
                    }, user_id)
                    count += 1
                except Exception as e:
                    st.warning(f"Failed to import {it.get('item_description', '')}: {e}")
            recalc_pr_totals(pr_id)
            st.success(f"✅ Imported {count} items!")
            st.rerun()


# ══════════════════════════════════════════════════════════════════
# DIALOGS — Add Manual Item
# ══════════════════════════════════════════════════════════════════

@st.dialog("➕ Add Item Manually", width="large")
def _dialog_add_manual_item(pr_id: int, pr_currency_id: int, pr_exchange_rate: float):
    with st.form("add_item_form"):
        m1, m2 = st.columns(2)
        cat = m1.selectbox("COGS Category", ['A', 'C', 'SERVICE'])
        desc = m2.text_input("Description *")

        m3, m4, m5 = st.columns(3)
        qty = m3.number_input("Qty", value=1.0, min_value=0.01, format="%.2f")
        cost = m4.number_input("Unit Cost", value=0.0, format="%.2f")
        uom = m5.text_input("UOM", value="Pcs")

        m6, m7 = st.columns(2)
        vendor_names_list = ["(None)"] + [v['name'] for v in vendors]
        vendor_sel = m6.selectbox("Vendor", vendor_names_list)
        vendor_ref = m7.text_input("Quote Reference")

        specs = st.text_area("Specifications", height=60)
        notes = st.text_input("Notes")

        # Preview
        if cost > 0 and qty > 0:
            total = qty * cost * pr_exchange_rate
            st.caption(f"💰 Line total: **{fmt_vnd(total)}**")

        submitted = st.form_submit_button("➕ Add", type="primary", use_container_width=True)

    if submitted:
        if not desc:
            st.error("Description required."); return
        if cost <= 0:
            st.error("Unit cost must be > 0."); return

        vendor_id = None
        vendor_name = ""
        if vendor_sel != "(None)":
            vendor_name = vendor_sel
            vendor_id = next((v['id'] for v in vendors if v['name'] == vendor_sel), None)

        try:
            create_pr_item({
                'pr_id': pr_id,
                'estimate_line_item_id': None,
                'costbook_detail_id': None,
                'product_id': None,
                'item_description': desc,
                'brand_name': '',
                'pt_code': '',
                'vendor_id': vendor_id,
                'vendor_name': vendor_name,
                'vendor_quote_ref': vendor_ref or None,
                'quantity': qty,
                'uom': uom,
                'unit_cost': cost,
                'currency_id': pr_currency_id,
                'exchange_rate': pr_exchange_rate,
                'cogs_category': cat,
                'specifications': specs or None,
                'notes': notes or None,
                'view_order': 999,
            }, user_id)
            recalc_pr_totals(pr_id)
            st.success(f"✅ Added: {desc}")
            st.rerun()
        except Exception as e:
            st.error(f"Failed: {e}")


# ══════════════════════════════════════════════════════════════════
# DIALOGS — Approval Actions (kept + enhanced)
# ══════════════════════════════════════════════════════════════════

@st.dialog("✅ Approve / ❌ Reject", width="large")
def _dialog_approval_action(pr_id: int):
    pr = get_pr(pr_id)
    if not pr:
        st.error("PR not found."); return

    # ── Permission gate: only authorized approver or admin ──────
    is_current_approver = is_approver_for_pr(pr_id, emp_int_id)
    if not is_current_approver and not is_admin:
        st.error("⛔ Bạn không có quyền phê duyệt PR này.")
        st.caption(f"PR **{pr['pr_number']}** đang pending approval level "
                   f"**{pr.get('current_approval_level', '?')}**. "
                   f"Chỉ approver được chỉ định trong approval chain mới có quyền.")
        from utils.il_project.pr_queries import get_current_approver
        cur_app = get_current_approver(pr_id)
        if cur_app:
            st.info(f"📧 Approver hiện tại: **{cur_app['approver_name']}** ({cur_app['approver_email']})")
        return

    st.markdown(f"### {pr['pr_number']} — {pr.get('vendor_name', 'No vendor')}")
    st.caption(f"Project: {pr['project_code']} | Amount: {fmt_vnd(pr.get('total_amount_vnd'))} | "
               f"Priority: {PRIORITY_ICONS.get(pr.get('priority', 'NORMAL'), '')} {pr.get('priority', 'NORMAL')}")

    # Approval progress (P3.3)
    history = get_pr_approval_history(pr_id)
    _render_approval_progress(pr, history)

    # Show items
    items_df = get_pr_items_df(pr_id)
    if not items_df.empty:
        st.divider()
        st.subheader(f"📋 Items ({len(items_df)})")
        display_df = items_df[['cogs_category', 'item_description', 'vendor_name',
                                'quantity', 'unit_cost', 'currency_code', 'amount_vnd']].copy()
        display_df['amount_vnd'] = display_df['amount_vnd'].apply(
            lambda v: f"{v:,.0f}" if v else '—')
        st.dataframe(display_df, width="stretch", hide_index=True)

    if pr.get('justification'):
        st.info(f"📝 **Justification:** {pr['justification']}")

    # Budget vs PR Comparison (inline — approver needs to see budget impact)
    st.divider()
    _render_budget_comparison(pr['project_id'], mode='full', current_pr_id=pr_id)

    # Approval history
    if history:
        st.divider()
        st.caption("**Approval History**")
        for h in history:
            icon = {'APPROVED': '✅', 'REJECTED': '❌', 'REVISION_REQUESTED': '🔄',
                    'SUBMITTED': '📤'}.get(h['approval_status'], '⚪')
            st.caption(f"{icon} L{h['approval_level']} — {h['approver_name']} — "
                       f"{h['approval_status']} — {h.get('comments', '')}")

    st.divider()

    # Action buttons
    comments = st.text_area("Comments", height=60, key="approval_comments")
    _approval_cc = _cc_email_selector("approval", label="📧 CC thêm (optional)")

    c1, c2, c3 = st.columns(3)
    if c1.button("✅ Approve", type="primary", use_container_width=True, key="btn_approve"):
        result = approve_pr(pr_id, emp_int_id, comments)
        if result['success']:
            st.success(result['message'])
            approver_name = st.session_state.get('user_fullname', '')
            _budget = get_budget_vs_pr(pr['project_id'])
            notify_pr_approved(
                pr_number=pr['pr_number'], project_code=pr.get('project_code', ''),
                total_vnd=float(pr.get('total_amount_vnd') or 0),
                requester_email=pr.get('requester_email', ''),
                requester_name=pr.get('requester_name', ''),
                approver_name=approver_name,
                approval_level=pr['current_approval_level'],
                is_final=result.get('final', False),
                next_approver_name=result.get('next_approver_name'),
                next_approver_email=result.get('next_approver_email'),
                pm_email=get_project_pm_email(pr['project_id']),
                cc_emails=_approval_cc,
                budget_data=_budget,
                app_url=_pr_link(pr_id, 'view'),
            )
            if not result.get('final') and result.get('next_approver_name'):
                st.info(f"📧 Next approver: {result['next_approver_name']}")
            st.cache_data.clear()
            st.rerun()
        else:
            st.error(result['message'])

    if c2.button("❌ Reject", use_container_width=True, key="btn_reject"):
        if not comments:
            st.warning("Please provide a reason for rejection.")
        else:
            result = reject_pr(pr_id, emp_int_id, comments)
            if result['success']:
                notify_pr_rejected(
                    pr_number=pr['pr_number'], project_code=pr.get('project_code', ''),
                    total_vnd=float(pr.get('total_amount_vnd') or 0),
                    requester_email=pr.get('requester_email', ''),
                    requester_name=pr.get('requester_name', ''),
                    approver_name=st.session_state.get('user_fullname', ''),
                    rejection_reason=comments,
                    pm_email=get_project_pm_email(pr['project_id']),
                    cc_emails=_approval_cc,
                    app_url=_pr_link(pr_id, 'edit'),
                )
                st.success(result['message'])
                st.cache_data.clear()
                st.rerun()
            else:
                st.error(result['message'])

    if c3.button("🔄 Request Revision", use_container_width=True, key="btn_revision"):
        if not comments:
            st.warning("Please provide revision notes.")
        else:
            result = request_revision(pr_id, emp_int_id, comments)
            if result['success']:
                notify_pr_revision_requested(
                    pr_number=pr['pr_number'], project_code=pr.get('project_code', ''),
                    total_vnd=float(pr.get('total_amount_vnd') or 0),
                    requester_email=pr.get('requester_email', ''),
                    requester_name=pr.get('requester_name', ''),
                    approver_name=st.session_state.get('user_fullname', ''),
                    revision_notes=comments,
                    pm_email=get_project_pm_email(pr['project_id']),
                    cc_emails=_approval_cc,
                    app_url=_pr_link(pr_id, 'edit'),
                )
                st.success(result['message'])
                st.cache_data.clear()
                st.rerun()
            else:
                st.error(result['message'])


# ══════════════════════════════════════════════════════════════════
# DIALOG — PR View (P1.2: read-only, chain to Edit)
# ══════════════════════════════════════════════════════════════════

@st.dialog("🛒 Purchase Request", width="large")
def _dialog_pr_view(pr_id: int):
    pr = get_pr(pr_id)
    if not pr:
        st.error("PR not found."); return

    is_pm_of_project = is_project_pm(pr['project_id'], emp_int_id)
    is_my_pr = pr['requester_id'] == emp_int_id
    is_approved = pr['status'] == 'APPROVED'
    has_po = bool(pr.get('po_id'))
    can_edit = (is_my_pr or is_admin) and pr['status'] in ('DRAFT', 'REVISION_REQUESTED')
    can_edit_approved = (is_my_pr or is_pm_of_project or is_admin) and is_approved and not has_po
    can_submit = (is_pm_of_project or is_admin) and pr['status'] in ('DRAFT', 'REVISION_REQUESTED')
    can_cancel = ((is_my_pr or is_pm_of_project or is_admin)
                  and pr['status'] in ('DRAFT', 'REVISION_REQUESTED', 'PENDING_APPROVAL', 'APPROVED')
                  and not has_po)

    # ── Header ──
    hc1, hc2 = st.columns([5, 1])
    icon = PR_STATUS_ICONS.get(pr['status'], '⚪')
    hc1.markdown(f"### {icon} {pr['pr_number']}")
    if can_edit:
        if hc2.button("✏️ Edit", type="primary", use_container_width=True):
            st.session_state['open_pr_edit'] = pr_id
            st.rerun()
    elif can_edit_approved:
        if hc2.button("📉 Reduce", type="primary", use_container_width=True,
                      help="Giảm số lượng/đơn giá (chỉ giảm, không tăng)"):
            st.session_state['open_pr_reduce'] = pr_id
            st.rerun()

    st.caption(f"Project: **{pr['project_code']}** — {pr['project_name']} | "
               f"Requester: {pr.get('requester_name', '—')} | "
               f"Vendor: {pr.get('vendor_name', '—')}")

    # ── Approval Progress (P3.3) ──
    history = get_pr_approval_history(pr_id)
    _render_approval_progress(pr, history)

    # ── KPIs ──
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total (VND)", fmt_vnd(pr.get('total_amount_vnd')))
    k2.metric("Priority", f"{PRIORITY_ICONS.get(pr['priority'], '')} {pr['priority']}")
    k3.metric("Approval", f"L{pr['current_approval_level']}/{pr['max_approval_level']}")
    k4.metric("Status", pr['status'])

    # ── Revision/Rejection banners ──
    if pr.get('revision_notes') and pr['status'] == 'REVISION_REQUESTED':
        st.warning(f"🔄 **Revision requested:** {pr['revision_notes']}")
    if pr.get('rejection_reason') and pr['status'] == 'REJECTED':
        st.error(f"❌ **Rejected:** {pr['rejection_reason']}")

    # ── Line Items (read-only) ──
    items_df = get_pr_items_df(pr_id)
    st.divider()
    st.subheader(f"📋 Items ({len(items_df)})")

    if not items_df.empty:
        display = items_df.copy()
        display['amount_fmt'] = display['amount_vnd'].apply(
            lambda v: f"{v:,.0f}" if v else '—')
        # Costbook + PO status columns
        display.insert(0, 'CB', display['costbook_detail_id'].apply(
            lambda v: '✅' if v else '⚠️'))
        display['PO'] = display['po_number'].apply(
            lambda v: str(v) if v and str(v) not in ('', 'nan', 'None') else '')
        st.dataframe(display, width="stretch", hide_index=True,
            column_config={
                'CB': st.column_config.TextColumn('CB', width=30,
                      help='Costbook: ✅ = linked, ⚠️ = missing'),
                'cogs_category': st.column_config.TextColumn('Cat', width=40),
                'item_description': st.column_config.TextColumn('Product'),
                'brand_name': st.column_config.TextColumn('Brand', width=80),
                'vendor_name': st.column_config.TextColumn('Vendor'),
                'quantity': st.column_config.NumberColumn('Qty', format="%.1f", width=55),
                'unit_cost': st.column_config.NumberColumn('Cost', format="%.2f"),
                'currency_code': st.column_config.TextColumn('CCY', width=40),
                'amount_fmt': st.column_config.TextColumn('VND'),
                'PO': st.column_config.TextColumn('PO#', width=100),
                'id': None, 'product_id': None, 'costbook_detail_id': None,
                'estimate_line_item_id': None, 'vendor_id': None,
                'exchange_rate': None, 'amount_vnd': None,
                'specifications': None, 'notes': None, 'view_order': None,
                'vendor_quote_ref': None, 'pt_code': None, 'uom': None,
                'po_id': None, 'po_number': None,
            })
    else:
        st.info("No items yet." + (" Click ✏️ Edit to add items." if can_edit else ""))

    # ── Justification ──
    if pr.get('justification'):
        st.divider()
        st.markdown(f"**Justification:** {pr['justification']}")

    # ── Budget vs PR Comparison (full with drill-down) ──
    st.divider()
    _render_budget_comparison(pr['project_id'], mode='full', current_pr_id=pr_id)

    # ── Approval History ──
    if history:
        st.divider()
        st.subheader("📜 Approval History")
        for h in history:
            hicon = {'APPROVED': '✅', 'REJECTED': '❌', 'REVISION_REQUESTED': '🔄',
                     'SUBMITTED': '📤'}.get(h['approval_status'], '⚪')
            st.caption(f"{hicon} Level {h['approval_level']} — {h['approver_name']} — "
                       f"**{h['approval_status']}** — {h.get('comments', '')}")

    # ── PO PDF Download (supports multi-PO) ──
    render_po_pdf_downloads_for_pr(
        pr_id=pr_id, pr_data=pr, items_df=items_df, context="view",
    )

    # ── Action Buttons (context-sensitive) ──
    st.divider()
    if can_submit and not items_df.empty:
        _view_cc = _cc_email_selector("view_submit", label="📧 CC thêm khi submit (optional)")

    ac1, ac2, ac3, ac4 = st.columns(4)

    if can_submit and not items_df.empty:
        if ac1.button("📤 Submit for Approval", type="primary", use_container_width=True):
            resolve_product_ids(pr_id)  # auto-link costbook before submit
            result = submit_pr(pr_id, user_id)
            if result['success']:
                st.success(result['message'])
                if result.get('approver_name'):
                    st.info(f"📧 Sent to: **{result['approver_name']}** ({result.get('approver_email', '')})")
                    _budget = get_budget_vs_pr(pr['project_id'])
                    notify_pr_submitted(
                        pr_number=pr['pr_number'], project_code=pr.get('project_code', ''),
                        project_name=pr.get('project_name', ''), requester_name=pr.get('requester_name', ''),
                        total_vnd=float(pr.get('total_amount_vnd') or 0),
                        item_count=len(items_df), priority=pr.get('priority', 'NORMAL'),
                        justification=pr.get('justification', ''),
                        approver_name=result['approver_name'], approver_email=result['approver_email'],
                        approval_level=1, max_level=result.get('max_level', 1),
                        requester_email=pr.get('requester_email', ''),
                        cc_emails=_view_cc,
                        budget_data=_budget,
                        app_url=_pr_link(pr_id, 'approve'),
                    )
                st.cache_data.clear()
                st.rerun()
            else:
                st.error(result['message'])

    if pr['status'] == 'APPROVED':
        # Check if there are items eligible for PO (has costbook + no po_id)
        _cb_status = get_pr_costbook_status(pr_id) if not items_df.empty else {}
        _has_eligible = _cb_status.get('eligible_for_po', 0) > 0
        can_create_po = (is_pm_of_project or is_admin) and _has_eligible
        if can_create_po:
            _po_label = "🛒 Create PO"
            if pr.get('po_id'):
                _po_label = "🛒 Create Another PO"
            if ac2.button(_po_label, type="primary", use_container_width=True):
                st.session_state['confirm_create_po'] = pr_id
                st.rerun()
        elif not _has_eligible and not items_df.empty:
            if _cb_status.get('without_costbook', 0) > 0:
                ac2.button("🛒 Create PO", disabled=True, use_container_width=True,
                           help=f"{_cb_status['without_costbook']} item(s) thiếu costbook — "
                                f"tạo vendor costbook trước")
            else:
                ac2.button("🛒 Create PO", disabled=True, use_container_width=True,
                           help="All items already in PO")
        elif not (is_pm_of_project or is_admin):
            ac2.button("🛒 Create PO", disabled=True, use_container_width=True,
                       help="Chỉ PM của project hoặc Admin mới có thể tạo PO")

    if pr['status'] == 'PENDING_APPROVAL' and (is_my_pr or is_pm_of_project or is_admin):
        if ac2.button("📧 Remind Approver", use_container_width=True):
            from utils.il_project.pr_queries import get_current_approver
            cur_app = get_current_approver(pr_id)
            if cur_app:
                _days = 0
                if pr.get('submitted_date'):
                    try:
                        _days = (pd.Timestamp.now() - pd.Timestamp(pr['submitted_date'])).days
                    except Exception:
                        pass
                _budget = get_budget_vs_pr(pr['project_id'])
                notify_pr_reminder(
                    pr_number=pr['pr_number'],
                    project_code=pr.get('project_code', ''),
                    total_vnd=float(pr.get('total_amount_vnd') or 0),
                    requester_name=pr.get('requester_name', ''),
                    requester_email=pr.get('requester_email', ''),
                    approver_name=cur_app['approver_name'],
                    approver_email=cur_app['approver_email'],
                    approval_level=int(pr.get('current_approval_level', 1)),
                    max_level=int(pr.get('max_approval_level', 1)),
                    days_pending=_days,
                    priority=pr.get('priority', 'NORMAL'),
                    justification=pr.get('justification', ''),
                    budget_data=_budget,
                    app_url=_pr_link(pr_id, 'approve'),
                )
                st.success(f"📧 Nhắc nhở đã gửi đến **{cur_app['approver_name']}** ({cur_app['approver_email']})")
            else:
                st.warning("Không tìm thấy approver hiện tại.")

    if can_cancel:
        if ac4.button("🗑 Cancel PR", use_container_width=True):
            st.session_state['confirm_cancel_pr'] = pr_id
            st.rerun()


# ══════════════════════════════════════════════════════════════════
# DIALOG — PR Edit (P1.2: item management + header edit)
# ══════════════════════════════════════════════════════════════════

@st.dialog("✏️ Edit Purchase Request", width="large")
def _dialog_pr_edit(pr_id: int):
    pr = get_pr(pr_id)
    if not pr:
        st.error("PR not found."); return

    if pr['status'] not in ('DRAFT', 'REVISION_REQUESTED'):
        st.warning(f"Cannot edit PR in status: {pr['status']}")
        return

    icon = PR_STATUS_ICONS.get(pr['status'], '⚪')
    st.markdown(f"### {icon} {pr['pr_number']} — Edit Mode")

    if pr.get('revision_notes') and pr['status'] == 'REVISION_REQUESTED':
        st.warning(f"🔄 **Revision feedback:** {pr['revision_notes']}")

    # ── Budget context (inline — no drill-down to keep edit dialog focused) ──
    _render_budget_comparison(pr['project_id'], mode='inline')

    # ── Item Management ──
    items_df = get_pr_items_df(pr_id)
    st.subheader(f"📋 Items ({len(items_df)})")

    btn1, btn2, btn3, _ = st.columns([1, 1, 1, 2])
    if pr.get('estimate_id') and btn1.button("📋 Import Estimate", use_container_width=True):
        _dialog_import_estimate(pr_id, pr['estimate_id'])
    if btn2.button("➕ Add Manual", use_container_width=True):
        _dialog_add_manual_item(pr_id, pr.get('currency_id'), float(pr.get('exchange_rate', 1)))

    if not items_df.empty:
        display = items_df.copy()
        display['amount_fmt'] = display['amount_vnd'].apply(
            lambda v: f"{v:,.0f}" if v else '—')

        tbl_key = f"edit_items_{st.session_state.get('_edit_item_key', 0)}"
        event = st.dataframe(display, key=tbl_key, width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            column_config={
                'cogs_category': st.column_config.TextColumn('Cat', width=40),
                'item_description': st.column_config.TextColumn('Product'),
                'brand_name': st.column_config.TextColumn('Brand', width=80),
                'vendor_name': st.column_config.TextColumn('Vendor'),
                'quantity': st.column_config.NumberColumn('Qty', format="%.1f", width=55),
                'unit_cost': st.column_config.NumberColumn('Cost', format="%.2f"),
                'currency_code': st.column_config.TextColumn('CCY', width=40),
                'amount_fmt': st.column_config.TextColumn('VND'),
                'id': None, 'product_id': None, 'costbook_detail_id': None,
                'estimate_line_item_id': None, 'vendor_id': None,
                'exchange_rate': None, 'amount_vnd': None,
                'specifications': None, 'notes': None, 'view_order': None,
                'vendor_quote_ref': None, 'pt_code': None, 'uom': None,
            })

        sel = event.selection.rows
        if sel:
            sel_row = items_df.iloc[sel[0]]
            sc1, sc2, sc3 = st.columns(3)
            sc1.caption(f"Selected: **{sel_row['item_description']}**")
            if sc2.button("🗑 Remove Item", use_container_width=True, key="rm_sel_item"):
                delete_pr_item(int(sel_row['id']))
                recalc_pr_totals(pr_id)
                st.session_state['_edit_item_key'] = st.session_state.get('_edit_item_key', 0) + 1
                st.rerun()
            if sc3.button("✖ Deselect", use_container_width=True, key="desel_edit_item"):
                st.session_state['_edit_item_key'] = st.session_state.get('_edit_item_key', 0) + 1
                st.rerun()

        st.caption(f"**Total:** {fmt_vnd(pr.get('total_amount_vnd'))}")
    else:
        st.info("No items yet. Use Import or Add Manual above.")

    # ── Header Edit (inside expander to keep focus on items) ──
    st.divider()
    with st.expander("📝 Edit PR Header", expanded=False):
        with st.form("edit_pr_header"):
            eh1, eh2 = st.columns(2)
            priorities = ['NORMAL', 'LOW', 'HIGH', 'URGENT']
            pri_idx = priorities.index(pr['priority']) if pr.get('priority') in priorities else 0
            priority = eh1.selectbox("Priority", priorities, index=pri_idx)
            types = ['EQUIPMENT', 'FABRICATION', 'SERVICE', 'MIXED']
            type_idx = types.index(pr.get('pr_type', 'EQUIPMENT')) if pr.get('pr_type') in types else 0
            pr_type = eh2.selectbox("Type", types, index=type_idx)

            eh3, eh4 = st.columns(2)
            # Header enum: ('A','B','C','D','E','F','MIXED') — show practical options
            cogs_opts = ['A', 'C', 'D', 'MIXED']
            cogs_idx = cogs_opts.index(pr.get('cogs_category', 'A')) if pr.get('cogs_category') in cogs_opts else 0
            cogs_cat = eh3.selectbox("COGS Category", cogs_opts, index=cogs_idx,
                                      help="A=Equipment, C=Fabrication, D=Service/Labor, MIXED=Multiple")
            req_date = eh4.date_input("Required Date",
                                       value=pd.to_datetime(pr['required_date']).date() if pr.get('required_date') else None)

            justification = st.text_area("Justification", value=pr.get('justification') or '', height=70)

            if st.form_submit_button("💾 Save Header", type="primary", use_container_width=True):
                ok = update_pr(pr_id, {
                    'vendor_id': pr.get('vendor_id'),
                    'currency_id': pr.get('currency_id'),
                    'exchange_rate': pr.get('exchange_rate'),
                    'priority': priority,
                    'pr_type': pr_type,
                    'cogs_category': cogs_cat,
                    'required_date': req_date,
                    'justification': justification or None,
                }, user_id)
                if ok:
                    st.success("Header updated!")
                    st.rerun()
                else:
                    st.error("Update failed.")

    # ── Bottom actions ──
    st.divider()
    if not items_df.empty:
        _edit_cc = _cc_email_selector("edit_submit", label="📧 CC thêm khi submit (optional)")
    ba1, ba2, ba3 = st.columns([2, 1, 1])
    if not items_df.empty:
        if ba1.button("📤 Submit for Approval", type="primary", use_container_width=True):
            resolve_product_ids(pr_id)  # auto-link costbook before submit
            result = submit_pr(pr_id, user_id)
            if result['success']:
                st.success(result['message'])
                if result.get('approver_name'):
                    _budget = get_budget_vs_pr(pr['project_id'])
                    notify_pr_submitted(
                        pr_number=pr['pr_number'], project_code=pr.get('project_code', ''),
                        project_name=pr.get('project_name', ''), requester_name=pr.get('requester_name', ''),
                        total_vnd=float(pr.get('total_amount_vnd') or 0),
                        item_count=len(items_df), priority=pr.get('priority', 'NORMAL'),
                        justification=pr.get('justification', ''),
                        approver_name=result['approver_name'], approver_email=result['approver_email'],
                        approval_level=1, max_level=result.get('max_level', 1),
                        requester_email=pr.get('requester_email', ''),
                        cc_emails=_edit_cc,
                        budget_data=_budget,
                        app_url=_pr_link(pr_id, 'approve'),
                    )
                st.cache_data.clear()
                st.rerun()
            else:
                st.error(result['message'])

    if ba2.button("👁️ View Mode", use_container_width=True):
        st.session_state['open_pr_view'] = pr_id
        st.rerun()

    if ba3.button("🗑 Cancel PR", use_container_width=True):
        st.session_state['confirm_cancel_pr'] = pr_id
        st.rerun()


# ══════════════════════════════════════════════════════════════════
# DIALOG — Reduce PR Items (APPROVED status — scope reduction only)
# ══════════════════════════════════════════════════════════════════

@st.dialog("📉 Reduce PR Items", width="large")
def _dialog_pr_reduce(pr_id: int):
    """
    Restricted edit for APPROVED PRs.
    Only allows REDUCING quantity and/or unit_cost per item.
    No adding, no deleting, no increasing.
    """
    pr = get_pr(pr_id)
    if not pr:
        st.error("PR not found."); return

    if pr['status'] != 'APPROVED':
        st.warning(f"Reduce mode chỉ áp dụng cho PR đã APPROVED (hiện tại: {pr['status']})")
        return

    if pr.get('po_id'):
        st.error("PO đã được tạo — không thể giảm nữa.")
        return

    # Permission check
    is_pm_of_project = is_project_pm(pr['project_id'], emp_int_id)
    is_my_pr = pr['requester_id'] == emp_int_id
    if not (is_my_pr or is_pm_of_project or is_admin):
        st.error("⛔ Bạn không có quyền điều chỉnh PR này.")
        return

    st.markdown(f"### ✅ {pr['pr_number']} — Reduce Mode")
    st.caption(f"Project: {pr['project_code']} | Vendor: {pr.get('vendor_name', '—')} | "
               f"Current Total: **{fmt_vnd(pr.get('total_amount_vnd'))}**")
    st.info("📉 **Chế độ giảm scope** — Chỉ có thể giảm số lượng hoặc đơn giá. "
            "Không thể tăng hoặc thêm item mới.")

    # ── Items table ──
    items_df = get_pr_items_df(pr_id)
    if items_df.empty:
        st.warning("PR không có items."); return

    st.subheader(f"📋 Items ({len(items_df)})")

    for _, row in items_df.iterrows():
        item_id = int(row['id'])
        desc = (row.get('item_description', '') or '')[:60]
        orig_qty = float(row['quantity'])
        orig_cost = float(row['unit_cost'])
        ccy = row.get('currency_code', 'VND') or 'VND'
        orig_vnd = float(row.get('amount_vnd', 0) or 0)

        with st.container(border=True):
            st.markdown(f"**{row.get('cogs_category', '')}** — {desc}")
            st.caption(f"Hiện tại: **{orig_qty:.1f}** × **{orig_cost:,.2f} {ccy}** "
                       f"= **{fmt_vnd(orig_vnd)}**")

            rc1, rc2, rc3 = st.columns([1, 1, 1])
            new_qty = rc1.number_input(
                "Qty (max)", value=orig_qty,
                min_value=0.01, max_value=orig_qty,
                step=0.01, format="%.2f",
                key=f"reduce_qty_{item_id}",
            )
            new_cost = rc2.number_input(
                f"Cost (max) {ccy}", value=orig_cost,
                min_value=0.01, max_value=orig_cost,
                step=0.01, format="%.2f",
                key=f"reduce_cost_{item_id}",
            )

            changed = new_qty < orig_qty or new_cost < orig_cost
            if changed:
                rate = float(row.get('exchange_rate', 1) or 1)
                new_vnd = new_qty * new_cost * rate
                savings = orig_vnd - new_vnd
                rc3.markdown(f"<br>💰 Giảm **{fmt_vnd(savings)}**", unsafe_allow_html=True)

                if rc3.button("✅ Apply", key=f"reduce_apply_{item_id}", type="primary"):
                    result = reduce_pr_item(item_id, new_qty, new_cost, user_id)
                    if result['success']:
                        st.success(result['message'])
                        st.rerun()
                    else:
                        st.error(result['message'])
            else:
                rc3.caption("(Không thay đổi)")

    # ── Summary ──
    st.divider()
    sc1, sc2 = st.columns(2)
    sc1.metric("Current Total", fmt_vnd(pr.get('total_amount_vnd')))
    if sc2.button("👁️ View PR", use_container_width=True):
        st.session_state['open_pr_view'] = pr_id
        st.rerun()


# ══════════════════════════════════════════════════════════════════
# CONFIRM DIALOGS (P3.5)
# ══════════════════════════════════════════════════════════════════

@st.dialog("⚠️ Confirm Cancel PR")
def _dialog_confirm_cancel(pr_id: int):
    pr = get_pr(pr_id)
    if not pr:
        st.error("PR not found."); return

    if pr.get('po_id'):
        st.error("PO đã được tạo — không thể cancel PR này.")
        return

    st.warning(f"Are you sure you want to cancel **{pr['pr_number']}**?")
    st.caption(f"Total: {fmt_vnd(pr.get('total_amount_vnd'))} | Items: {pr.get('item_count', '—')}")

    if pr['status'] == 'APPROVED':
        st.error("⚠️ **PR này đã được APPROVED.** Cancel sẽ hủy bỏ toàn bộ approval. "
                 "Nếu chỉ muốn giảm scope, dùng nút 📉 Reduce thay vì Cancel.")

    st.markdown("This action **cannot be undone**.")
    _cancel_cc = _cc_email_selector("cancel_pr", label="📧 CC thêm (optional)")
    c1, c2 = st.columns(2)
    if c1.button("🗑 Yes, Cancel PR", type="primary", use_container_width=True):
        # Capture pending approver BEFORE cancel (status changes after)
        _pending_approver_email = None
        _pending_approver_name = None
        if pr['status'] == 'PENDING_APPROVAL':
            from utils.il_project.pr_queries import get_current_approver
            cur_app = get_current_approver(pr_id)
            if cur_app:
                _pending_approver_email = cur_app.get('approver_email')
                _pending_approver_name = cur_app.get('approver_name')

        if cancel_pr(pr_id, user_id):
            st.success("PR cancelled.")
            notify_pr_cancelled(
                pr_number=pr['pr_number'],
                project_code=pr.get('project_code', ''),
                total_vnd=float(pr.get('total_amount_vnd') or 0),
                requester_email=pr.get('requester_email', ''),
                requester_name=pr.get('requester_name', ''),
                cancelled_by=st.session_state.get('user_fullname', ''),
                pm_email=get_project_pm_email(pr['project_id']),
                pending_approver_email=_pending_approver_email,
                pending_approver_name=_pending_approver_name,
                cc_emails=_cancel_cc,
                app_url=_pr_link(pr_id, 'view'),
            )
            st.cache_data.clear()
            st.rerun()
        else:
            st.error("Cancel failed — PR may already be approved or cancelled.")
    if c2.button("✖ No, Go Back", use_container_width=True):
        st.rerun()


@st.dialog("⚠️ Confirm Create PO", width="large")
def _dialog_confirm_po(pr_id: int):
    pr = get_pr(pr_id)
    if not pr:
        st.error("PR not found."); return

    st.markdown(f"### 🛒 Create PO from {pr['pr_number']}")
    st.caption(f"Vendor: {pr.get('vendor_name', '—')} | Total: {fmt_vnd(pr.get('total_amount_vnd'))} | "
               f"Items: {pr.get('item_count', '—')}")

    # ── Permission gate: PM or Admin only ──────────────────────────
    _is_pm = is_project_pm(pr['project_id'], emp_int_id)
    if not _is_pm and not is_admin:
        st.error("⛔ Only the project PM or Admin can create a PO.")
        return

    # ── Step 1: Auto-resolve (cached, with manual re-check) ───────
    _resolve_key = f'_po_resolved_{pr_id}'
    if _resolve_key not in st.session_state:
        resolve_result = resolve_product_ids(pr_id)
        st.session_state[_resolve_key] = resolve_result
    else:
        resolve_result = st.session_state[_resolve_key]
    if resolve_result.get('resolved_count', 0) > 0 or resolve_result.get('costbook_resolved', 0) > 0:
        _msgs = []
        if resolve_result.get('resolved_count', 0) > 0:
            _msgs.append(f"{resolve_result['resolved_count']} product link(s)")
        if resolve_result.get('costbook_resolved', 0) > 0:
            _msgs.append(f"{resolve_result['costbook_resolved']} costbook link(s)")
        st.success(f"✅ Auto-resolved: {' + '.join(_msgs)} (from costbook/estimate)")

    # Re-check button (run resolve again after user creates costbook externally)
    if st.button("🔄 Re-check costbook links", use_container_width=False,
                 help="Chạy lại auto-resolve sau khi đã tạo costbook mới"):
        st.session_state.pop(_resolve_key, None)
        st.session_state.pop(f'_po_data_{pr_id}', None)
        st.rerun()

    # ── Step 2: Validate PO readiness ──────────────────────────────
    validation = validate_po_readiness(pr_id)
    for w in validation.get('warnings', []):
        st.warning(f"⚠️ {w}")

    # ── Step 3: Product linking for eligible items missing product ──
    missing_items = validation.get('items_without_product', [])
    if missing_items:
        _frag_product_linking(pr_id, missing_items)

    # Blockers
    for b in validation.get('blockers', []):
        st.error(f"❌ {b}")

    if not validation['ready']:
        st.divider()
        c1, c2 = st.columns(2)
        c1.button("🛒 Create PO", disabled=True, use_container_width=True,
                  help="Resolve all blockers above before creating PO")
        if c2.button("✖ Cancel", use_container_width=True):
            _cleanup_po_dialog(pr_id)
            st.rerun()
        return

    # ══════════════════════════════════════════════════════════════
    # SPLIT VIEW: Eligible vs Excluded items
    # ══════════════════════════════════════════════════════════════
    st.divider()
    eligible = validation['eligible_items']
    excluded = validation['excluded_items']
    already_in_po = validation.get('already_in_po_items', [])
    eligible_vnd = validation['eligible_amount_vnd']
    excluded_vnd = validation['excluded_amount_vnd']
    pr_total_vnd = float(pr.get('total_amount_vnd') or 0)
    is_partial = len(excluded) > 0

    # Summary comparison
    if is_partial:
        st.markdown("##### 📊 PO Coverage")
        comp_rows = []
        comp_rows.append({'': 'PR Total', 'Items': len(eligible) + len(excluded) + len(already_in_po),
                          'Amount VND': f"{pr_total_vnd:,.0f}"})
        if already_in_po:
            _aip_vnd = sum(it['amount_vnd'] for it in already_in_po)
            comp_rows.append({'': '✅ Already in PO', 'Items': len(already_in_po),
                              'Amount VND': f"{_aip_vnd:,.0f}"})
        comp_rows.append({'': '✅ This PO (has costbook)', 'Items': len(eligible),
                          'Amount VND': f"{eligible_vnd:,.0f}"})
        comp_rows.append({'': '⚠️ Excluded (no costbook)', 'Items': len(excluded),
                          'Amount VND': f"{excluded_vnd:,.0f}"})
        st.dataframe(pd.DataFrame(comp_rows), width="stretch", hide_index=True, height=38 + 35*len(comp_rows))

    # ── Eligible items (will be in PO) ────────────────────────────
    st.markdown(f"##### ✅ Items in this PO ({len(eligible)})")
    if eligible:
        elig_rows = []
        for it in eligible:
            elig_rows.append({
                'Cat': it.get('cogs_category', ''),
                'Description': (it.get('description', '') or '')[:40],
                'Amount VND': f"{it['amount_vnd']:,.0f}",
            })
        st.dataframe(pd.DataFrame(elig_rows), width="stretch", hide_index=True,
                     height=min(35*len(elig_rows)+38, 200))

    # ── Excluded items (no costbook) ─────────────────────────────
    if excluded:
        st.markdown(f"##### ⚠️ Excluded — no costbook ({len(excluded)})")
        excl_rows = []
        for it in excluded:
            excl_rows.append({
                'Cat': it.get('cogs_category', ''),
                'Description': (it.get('description', '') or '')[:40],
                'Amount VND': f"{it['amount_vnd']:,.0f}",
            })
        st.dataframe(pd.DataFrame(excl_rows), width="stretch", hide_index=True,
                     height=min(35*len(excl_rows)+38, 150))
        st.caption("💡 Tạo costbook cho các item trên rồi ấn **🔄 Re-check** để chuyển sang eligible. "
                   "Hoặc tạo PO riêng cho các item này sau.")

    # ── Already in PO ────────────────────────────────────────────
    if already_in_po:
        with st.expander(f"ℹ️ {len(already_in_po)} item(s) already in PO — skipped"):
            for it in already_in_po:
                st.caption(f"- {it.get('description', '')[:50]} — {fmt_vnd(it['amount_vnd'])}")

    # ── PO summary ────────────────────────────────────────────────
    st.divider()
    if is_partial:
        st.info(f"🛒 **PO sẽ tạo:** {len(eligible)} item(s) — "
                f"**{fmt_vnd(eligible_vnd)}** / {fmt_vnd(pr_total_vnd)} "
                f"({eligible_vnd / pr_total_vnd * 100:.0f}%)" if pr_total_vnd > 0 else
                f"🛒 **PO sẽ tạo:** {len(eligible)} item(s) — {fmt_vnd(eligible_vnd)}")
    else:
        st.success(f"✅ **PO sẽ tạo:** {len(eligible)} item(s) — {fmt_vnd(eligible_vnd)} (toàn bộ PR)")

    # ══════════════════════════════════════════════════════════════
    # LOAD ALL DATA ONCE — cache in session_state
    # ══════════════════════════════════════════════════════════════
    _data_key = f'_po_data_{pr_id}'
    if _data_key not in st.session_state:
        st.session_state[_data_key] = {
            'enrichment': get_po_enrichment_data(pr_id),
            'payment_terms': get_payment_terms(),
            'trade_terms': get_trade_terms(),
            'buyer_contacts': get_contacts_for_company(1),
            'auto_addr': get_company_address(1),
            'items_df': get_pr_items_df(pr_id),
            'cc_employees': _get_employees_with_email(),
        }
    _d = st.session_state[_data_key]
    enrichment      = _d['enrichment']
    cb_defaults     = enrichment.get('costbook_defaults', {})
    enriched_items  = enrichment.get('items', [])
    payment_terms_list = _d['payment_terms']
    trade_terms_list   = _d['trade_terms']
    buyer_contacts     = _d['buyer_contacts']
    _auto_addr         = _d['auto_addr']
    items_df           = _d['items_df']
    cc_emp_list        = _d['cc_employees']

    # Filter enriched_items to only eligible (has costbook + no po_id)
    _eligible_ids = {it['item_id'] for it in eligible}
    enriched_items = [eit for eit in enriched_items
                      if eit.get('item_id') in _eligible_ids]

    # ── Pre-calculate defaults for form (BEFORE form renders) ──────
    from datetime import timedelta

    _pr_required = pr.get('required_date')
    if _pr_required and not isinstance(_pr_required, str):
        _default_etd_val = _pr_required
    elif _pr_required:
        try:
            _default_etd_val = pd.to_datetime(_pr_required).date()
        except Exception:
            _default_etd_val = date.today() + timedelta(days=7)
    else:
        _default_etd_val = date.today() + timedelta(days=7)

    # Pre-calculate per-item ETA defaults from lead_time
    _item_eta_defaults = {}
    for eit in enriched_items:
        lt_num = eit.get('cb_lead_time_number', '')
        lt_min = eit.get('cb_lead_time_min')
        lt_max = eit.get('cb_lead_time_max')
        lt_uom = eit.get('cb_lead_time_uom', '')
        _lt_days = 0
        try:
            _lt_val = int(lt_max or lt_num or lt_min or 0)
            _lt_u = (lt_uom or '').lower()
            if 'week' in _lt_u:
                _lt_days = _lt_val * 7
            elif 'month' in _lt_u:
                _lt_days = _lt_val * 30
            else:
                _lt_days = _lt_val
        except (ValueError, TypeError):
            _lt_days = 0
        if _lt_days <= 0:
            _lt_days = 14
        _item_eta_defaults[eit.get('item_id')] = _default_etd_val + timedelta(days=_lt_days)

    # ── Build option lists (computed once) ─────────────────────────
    pt_names = ["(Auto from costbook)"] + [t['name'] for t in payment_terms_list]
    _pt_default_name = cb_defaults.get('payment_term_name', '')
    _pt_idx = pt_names.index(_pt_default_name) if _pt_default_name in pt_names else 0

    tt_names = ["(Auto from costbook)"] + [t['name'] for t in trade_terms_list]
    _tt_default_name = cb_defaults.get('trade_term_name', '')
    _tt_idx = tt_names.index(_tt_default_name) if _tt_default_name in tt_names else 0

    bc_options = ["(None)"] + [
        f"{c['full_name'].strip()} ({c.get('position', '') or c.get('email', '')})"
        for c in buyer_contacts
    ]

    emp_options = ["(None)"] + [f"{e['full_name']} (ID:{e['id']})" for e in employees]
    _pm_option = next((o for o in emp_options if f"ID:{emp_int_id})" in o), emp_options[0])
    _pm_idx = emp_options.index(_pm_option) if _pm_option in emp_options else 0

    _cb_notes = cb_defaults.get('important_notes_text', '')

    cc_options = [f"{e['name']} ({e['email']})" for e in cc_emp_list]
    cc_email_map = {f"{e['name']} ({e['email']})": e['email'] for e in cc_emp_list}

    # ══════════════════════════════════════════════════════════════
    # ④ + ⑤ + ⑥  ALL IN ONE FORM — zero reruns while filling
    # ══════════════════════════════════════════════════════════════
    with st.form("po_create_form"):

        # ── ④ PO Header Settings ──────────────────────────────────
        st.markdown("##### ④ PO Header Settings")

        h1, h2 = st.columns(2)
        sel_pt = h1.selectbox("Payment Term", pt_names, index=_pt_idx, key="po_f_pt",
                              help=f"Costbook default: {_pt_default_name or '—'}")
        sel_tt = h2.selectbox("Trade Term (Incoterm)", tt_names, index=_tt_idx, key="po_f_tt",
                              help=f"Costbook default: {_tt_default_name or '—'}")

        h3, h4 = st.columns(2)
        sel_ship_contact = h3.selectbox("Ship-to Contact", bc_options, key="po_f_ship_c",
                                        help="Receiving contact at buyer company")
        sel_bill_contact = h4.selectbox("Bill-to Contact", bc_options, key="po_f_bill_c",
                                        help="Billing/payment contact")

        h5, h6 = st.columns(2)
        ship_to_addr = h5.text_input("Ship-to Address", value=_auto_addr, key="po_f_ship_a",
                                     help="Shipping address (auto-filled from company)")
        bill_to_addr = h6.text_input("Bill-to Address", value=_auto_addr, key="po_f_bill_a",
                                     help="Invoice/billing address")

        po_notes = st.text_area("PO Notes / Special Instructions",
                                value=_cb_notes or '', height=70, key="po_f_notes",
                                help="Important notes for PO — saved to notes table")

        # ── ⑤ Shipping & Delivery ─────────────────────────────────
        st.divider()
        st.markdown("##### ⑤ Shipping & Delivery")

        g1, g2 = st.columns(2)
        default_etd = g1.date_input("Default ETD (all items)",
                                    value=_default_etd_val, key="po_f_etd",
                                    help="Default: PR required date, or today + 7 days")
        default_stock_owner = g2.selectbox("Stock Owner (default)", emp_options,
                                           index=_pm_idx, key="po_f_owner",
                                           help="Inventory owner — defaults to PM")

        # Per-item ETD / ETA (in expanders) — only eligible items
        _form_item_keys = []
        if enriched_items:
            st.caption(f"📦 {len(enriched_items)} eligible items — expand to set ETD/ETA per item")
            for idx, eit in enumerate(enriched_items):
                item_id = eit.get('item_id')
                desc = (eit.get('item_description', '') or '')[:50]
                pt = eit.get('pt_code', '') or ''
                lt_num = eit.get('cb_lead_time_number', '')
                lt_min = eit.get('cb_lead_time_min')
                lt_uom = eit.get('cb_lead_time_uom', '')
                shipping_mode = eit.get('cb_shipping_mode_name', '') or eit.get('cb_shipping_mode_code', '')
                pkg = eit.get('cb_package_size') or eit.get('product_package_size', '')

                info_parts = []
                if lt_num or lt_min:
                    info_parts.append(f"⏱ {lt_num or lt_min} {lt_uom}")
                if shipping_mode:
                    info_parts.append(f"🚢 {shipping_mode}")
                if pkg:
                    info_parts.append(f"📦 {pkg}")
                info_str = ' | '.join(info_parts)
                label = f"**{pt}** — {desc}" + (f"  ({info_str})" if info_parts else "")

                with st.expander(label, expanded=False):
                    ic1, ic2 = st.columns(2)
                    _etd_key = f"po_f_etd_{item_id}"
                    _eta_key = f"po_f_eta_{item_id}"
                    ic1.date_input("ETD", value=_default_etd_val, key=_etd_key,
                                   help=f"Lead time: {lt_num or lt_min or '—'} {lt_uom}")
                    _eta_def = _item_eta_defaults.get(item_id, _default_etd_val + timedelta(days=14))
                    ic2.date_input("ETA", value=_eta_def, key=_eta_key,
                                   help="Auto-calculated from ETD + lead time (override if needed)")
                    _form_item_keys.append((item_id, _etd_key, _eta_key))

        # ── ⑥ Confirmation + CC + Submit ──────────────────────────
        st.divider()

        # Mandatory checkbox for partial PO
        if is_partial:
            _confirm = st.checkbox(
                f"Tôi xác nhận PO chỉ gồm **{len(eligible)}/{len(eligible)+len(excluded)} items** "
                f"(**{fmt_vnd(eligible_vnd)}** / {fmt_vnd(pr_total_vnd)}). "
                f"{len(excluded)} item(s) không có costbook sẽ bị loại.",
                key="po_f_confirm_partial",
            )
        else:
            _confirm = True  # Full PO — no checkbox needed

        _po_cc_sel = st.multiselect("📧 CC (e.g. finance, optional)", cc_options,
                                    key="po_f_cc", help="Select employees to CC on email notification")

        fc1, fc2 = st.columns(2)
        submitted = fc1.form_submit_button("🛒 Create PO", type="primary", use_container_width=True)
        cancelled = fc2.form_submit_button("✖ Cancel", use_container_width=True)

    # ══════════════════════════════════════════════════════════════
    # HANDLE FORM SUBMISSION
    # ══════════════════════════════════════════════════════════════
    if cancelled:
        _cleanup_po_dialog(pr_id)
        st.rerun()

    if submitted:
        # Check confirmation for partial PO
        if is_partial and not _confirm:
            st.error("⚠️ Vui lòng tick xác nhận partial PO trước khi tạo.")
            return

        # ── Collect all values from form ──────────────────────
        _sel_pt_id = None
        if sel_pt != "(Auto from costbook)":
            _sel_pt_id = next((t['id'] for t in payment_terms_list if t['name'] == sel_pt), None)

        _sel_tt_id = None
        if sel_tt != "(Auto from costbook)":
            _sel_tt_id = next((t['id'] for t in trade_terms_list if t['name'] == sel_tt), None)

        _ship_contact_id = None
        if sel_ship_contact != "(None)" and buyer_contacts:
            _sc_idx = bc_options.index(sel_ship_contact) - 1
            if 0 <= _sc_idx < len(buyer_contacts):
                _ship_contact_id = buyer_contacts[_sc_idx]['id']

        _bill_contact_id = None
        if sel_bill_contact != "(None)" and buyer_contacts:
            _bc_idx = bc_options.index(sel_bill_contact) - 1
            if 0 <= _bc_idx < len(buyer_contacts):
                _bill_contact_id = buyer_contacts[_bc_idx]['id']

        _stock_owner_id = None
        if default_stock_owner != "(None)":
            try:
                _stock_owner_id = int(default_stock_owner.split("ID:")[1].rstrip(")"))
            except (ValueError, IndexError):
                _stock_owner_id = emp_int_id

        _item_etd_eta = {}
        for item_id, etd_key, eta_key in _form_item_keys:
            _etd_val = st.session_state.get(etd_key)
            _eta_val = st.session_state.get(eta_key)
            _item_etd_eta[str(item_id)] = {
                'etd': datetime.combine(_etd_val, datetime.min.time()) if _etd_val else None,
                'eta': datetime.combine(_eta_val, datetime.min.time()) if _eta_val else None,
                'stock_owner_id': _stock_owner_id,
            }

        if enriched_items and not _form_item_keys:
            for eit in enriched_items:
                _iid = str(eit.get('item_id'))
                _eta_def = _item_eta_defaults.get(eit.get('item_id'))
                _item_etd_eta[_iid] = {
                    'etd': datetime.combine(default_etd, datetime.min.time()) if default_etd else None,
                    'eta': datetime.combine(_eta_def, datetime.min.time()) if _eta_def else None,
                    'stock_owner_id': _stock_owner_id,
                }

        _po_cc = [cc_email_map[s] for s in _po_cc_sel if s in cc_email_map]

        po_settings = {
            'payment_term_id': _sel_pt_id,
            'trade_term_id': _sel_tt_id,
            'ship_to_contact_id': _ship_contact_id,
            'bill_to_contact_id': _bill_contact_id,
            'ship_to': ship_to_addr if ship_to_addr != '—' else None,
            'bill_to': bill_to_addr if bill_to_addr != '—' else None,
            'po_notes': po_notes if po_notes.strip() else '',
            'item_settings': _item_etd_eta,
        }

        keycloak_id = st.session_state.get('user_keycloak_id', user_id)
        result = create_po_from_pr(pr_id, 1, keycloak_id, po_settings=po_settings)
        if result['success']:
            # Store result for rendering outside the form submit handler
            st.session_state[f'_po_created_{pr_id}'] = result

            # Send email notification (non-blocking)
            notify_po_created(
                pr_number=pr['pr_number'], po_number=result['po_number'],
                project_code=pr.get('project_code', ''),
                total_vnd=float(eligible_vnd),
                vendor_name=pr.get('vendor_name', ''),
                requester_email=pr.get('requester_email', ''),
                requester_name=pr.get('requester_name', ''),
                pm_email=get_project_pm_email(pr['project_id']),
                cc_emails=_po_cc,
                app_url=_pr_link(pr_id, 'view'),
            )
        else:
            st.error(f"❌ {result['message']}")

    # ── Post-creation: Success message + PDF download ──────────────
    # Uses centralized widget — cached PDF, consistent UI, proper cleanup
    if render_po_created_success(pr_id):
        pass  # Panel rendered — Done button is inside the widget


# ── Product linking fragment (self-contained rerun) ───────────────

@st.fragment
def _frag_product_linking(pr_id: int, missing_items: list):
    """Fragment for product search + link. Reruns only this section."""
    st.divider()
    st.error(f"❌ **{len(missing_items)} item(s) not linked to Product** — "
             f"Legacy ERP requires product_id for every PO line item.")
    st.caption("Link a product for each item below, or go back to Edit PR to update.")

    for i, mi in enumerate(missing_items):
        item_id = mi['item_id']
        desc = mi.get('description', '(no description)')

        with st.container(border=True):
            st.markdown(f"**#{i+1}** — {desc}")
            keyword = st.text_input(
                f"🔍 Search product", key=f"prod_search_{item_id}",
                placeholder="Enter name, PT code, or description...",
            )
            if keyword and len(keyword) >= 2:
                results = search_products_for_linking(keyword)
                if results:
                    options = {
                        f"{r['pt_code'] or '—'} | {r['name']} ({r.get('brand_name', '')})"
                        .strip(' ()'): r['id']
                        for r in results
                    }
                    sel = st.selectbox("Select product",
                                       ["(Select...)"] + list(options.keys()),
                                       key=f"prod_sel_{item_id}")
                    if sel != "(Select...)":
                        if st.button(f"🔗 Link", key=f"prod_link_{item_id}", type="primary"):
                            ok = link_product_to_pr_item(item_id, options[sel])
                            if ok:
                                st.success(f"✅ Linked!")
                                # Clear cached resolve + data so parent re-validates
                                st.session_state.pop(f'_po_resolved_{pr_id}', None)
                                st.session_state.pop(f'_po_data_{pr_id}', None)
                                st.rerun(scope="app")
                            else:
                                st.error("Link failed.")
                else:
                    st.caption("No matching product found.")
            elif keyword:
                st.caption("Enter at least 2 characters to search.")


def _cleanup_po_dialog(pr_id: int):
    """Remove all PO dialog cached state including PDF widget keys."""
    for k in list(st.session_state):
        if k.startswith(f'_po_') and str(pr_id) in k:
            del st.session_state[k]
    # Also clean form keys
    for k in list(st.session_state):
        if k.startswith('po_f_'):
            del st.session_state[k]
    # Clean PDF widget state (new unified + legacy keys)
    cleanup_pdf_state(pr_id)


# ══════════════════════════════════════════════════════════════════
# ALL PROJECTS — Overview Dashboard (P1.1)
# ══════════════════════════════════════════════════════════════════

@st.fragment
def _render_overview(f_status_filter, f_priority_filter):
    """Cross-project PR dashboard."""
    all_df = get_pr_list_df(status=None if f_status_filter == "All" else f_status_filter)
    if all_df.empty:
        st.info("No PRs found.")
        return

    # Apply priority filter
    if f_priority_filter != "All" and not all_df.empty:
        all_df = all_df[all_df['priority'] == f_priority_filter]

    # ── KPIs ─────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total PRs", len(all_df))
    approved_mask = all_df['status'].isin(['APPROVED', 'PO_CREATED'])
    k2.metric("Approved Value", fmt_vnd(all_df.loc[approved_mask, 'total_amount_vnd'].sum())
              if approved_mask.any() else '—')
    pending_count = len(all_df[all_df['status'] == 'PENDING_APPROVAL'])
    k3.metric("Pending Approval", pending_count)
    k4.metric("With PO", len(all_df[all_df['status'] == 'PO_CREATED']))

    # Costbook warning KPI — APPROVED PRs with items missing costbook
    _approved_ids = all_df.loc[all_df['status'] == 'APPROVED', 'pr_id'].tolist()
    _need_cb_count = 0
    if _approved_ids:
        _cb_batch = get_costbook_warnings_batch([int(x) for x in _approved_ids])
        _need_cb_count = sum(1 for info in _cb_batch.values() if info.get('without_cb', 0) > 0)
    if _need_cb_count > 0:
        k5.metric("⚠️ Need Costbook", _need_cb_count)
    else:
        k5.metric("⚠️ Need Costbook", 0)

    st.divider()

    # ── Per-Project PR Summary ───────────────────────────────────
    st.subheader("📊 Per-Project PR Summary")
    summary_rows = []
    for _, row in proj_df.iterrows():
        pid = row['project_id']
        p_prs = all_df[all_df['project_id'] == pid] if not all_df.empty else pd.DataFrame()
        if p_prs.empty:
            continue

        active = p_prs[p_prs['status'].isin(['DRAFT', 'PENDING_APPROVAL', 'APPROVED'])]
        approved = p_prs[p_prs['status'].isin(['APPROVED', 'PO_CREATED'])]
        pending = p_prs[p_prs['status'] == 'PENDING_APPROVAL']
        with_po = p_prs[p_prs['status'] == 'PO_CREATED']

        summary_rows.append({
            'Project': row['project_code'],
            'Name': (str(row.get('project_name', '')) or '')[:30],
            'Status': row['status'],
            'Active': len(active),
            'Pending': len(pending),
            'Approved VND': f"{approved['total_amount_vnd'].sum():,.0f}" if not approved.empty else '—',
            'With PO': len(with_po),
            'Total PRs': len(p_prs),
        })

    if summary_rows:
        st.dataframe(
            pd.DataFrame(summary_rows), width="stretch", hide_index=True,
            column_config={
                'Project': st.column_config.TextColumn('Project', width=140),
                'Name': st.column_config.TextColumn('Name'),
                'Status': st.column_config.TextColumn('Status', width=120),
                'Active': st.column_config.NumberColumn('Active', width=70),
                'Pending': st.column_config.NumberColumn('Pending', width=75),
                'Approved VND': st.column_config.TextColumn('Approved VND'),
                'With PO': st.column_config.NumberColumn('PO', width=50),
                'Total PRs': st.column_config.NumberColumn('Total', width=60),
            },
        )
    else:
        st.info("No PR activity found for the selected filters.")

    # ── My Pending Actions ───────────────────────────────────────
    my_pending = get_pending_for_approver(emp_int_id)
    if not my_pending.empty:
        st.divider()
        st.subheader(f"⏳ My Pending Actions ({len(my_pending)})")
        for _, row in my_pending.iterrows():
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 1, 1])
                age = _age_icon(row.get('submitted_date'))
                c1.markdown(f"{age} **{row['pr_number']}** — {row.get('project_code', '')} | "
                            f"Vendor: {row.get('vendor_name', '—')} | "
                            f"By: {row.get('requester_name', '—')}")
                c2.metric("Amount", fmt_vnd(row.get('total_amount_vnd')))
                pri = row.get('priority', 'NORMAL')
                c3.markdown(f"{PRIORITY_ICONS.get(pri, '')} **{pri}**")
                if st.button("Review & Act", type="primary", key=f"ov_review_{row['pr_id']}",
                             use_container_width=False):
                    st.session_state['open_pr_approve'] = int(row['pr_id'])
                    st.rerun(scope="app")

    # ── All PRs — selectable list ────────────────────────────────
    st.divider()
    st.subheader(f"📋 All PRs ({len(all_df)})")

    display = all_df.copy()
    display.insert(0, '●', display['status'].map(PR_STATUS_ICONS))
    display['pri'] = display['priority'].map(PRIORITY_ICONS)
    display['total_fmt'] = display['total_amount_vnd'].apply(
        lambda v: f"{v:,.0f}" if v and str(v) not in ('', 'nan', 'None', '0') else '—')
    if 'submitted_date' in display.columns:
        display['⏰'] = display['submitted_date'].apply(_age_icon)
    else:
        display['⏰'] = ''
    display = _add_cb_warning_column(display)

    tbl_key = f"ov_all_pr_{st.session_state.get('_ov_all_pr_key', 0)}"
    event = st.dataframe(
        display, key=tbl_key, width="stretch", hide_index=True,
        on_select="rerun", selection_mode="single-row",
        column_config={
            '●': st.column_config.TextColumn('', width=30),
            '⏰': st.column_config.TextColumn('⏰', width=30, help='Pending age: 🔴 >7d, 🟡 >3d'),
            'pri': st.column_config.TextColumn('Pri', width=35),
            'pr_number': st.column_config.TextColumn('PR#'),
            'project_code': st.column_config.TextColumn('Project', width=140),
            'requester_name': st.column_config.TextColumn('Requester'),
            'status': st.column_config.TextColumn('Status'),
            'vendor_name': st.column_config.TextColumn('Vendor'),
            'total_fmt': st.column_config.TextColumn('Total VND'),
            'CB': st.column_config.TextColumn('CB', width=30,
                  help='Costbook: ✅ ready | ⚠️ partial | 🔴 none'),
            'po_number': st.column_config.TextColumn('PO#'),
            'created_date': st.column_config.DatetimeColumn('Created'),
            'pr_id': None, 'project_id': None, 'requester_id': None,
            'requester_email': None, 'vendor_id': None,
            'total_amount': None, 'total_amount_vnd': None, 'currency_code': None,
            'exchange_rate': None, 'current_approval_level': None,
            'max_approval_level': None, 'submitted_date': None,
            'approved_date': None, 'required_date': None,
            'po_id': None, 'justification': None, 'rejection_reason': None,
            'project_name': None, 'item_count': None,
            'pr_type': None, 'cogs_category': None, 'priority': None,
        },
    )

    sel = event.selection.rows
    if sel:
        row = all_df.iloc[sel[0]]
        st.markdown(f"**Selected:** {row['pr_number']} — "
                    f"{PR_STATUS_ICONS.get(row['status'], '')} {row['status']} | "
                    f"Project: {row.get('project_code', '—')} | "
                    f"By: {row.get('requester_name', '—')}")
        _render_pr_action_bar(row, "ov")


# ══════════════════════════════════════════════════════════════════
# TAB — My PRs (enhanced with quick actions P3.2)
# ══════════════════════════════════════════════════════════════════

@st.fragment
def _render_my_prs_tab(project_id_filter, status_filter, priority_filter):
    my_df = get_pr_list_df(
        project_id=project_id_filter,
        status=None if status_filter == "All" else status_filter,
        requester_id=emp_int_id,
    )

    # Apply priority filter
    if priority_filter != "All" and not my_df.empty:
        my_df = my_df[my_df['priority'] == priority_filter]

    # KPIs
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total PRs", len(my_df))
    k2.metric("Pending", len(my_df[my_df['status'] == 'PENDING_APPROVAL']) if not my_df.empty else 0)
    k3.metric("Approved", len(my_df[my_df['status'] == 'APPROVED']) if not my_df.empty else 0)
    k4.metric("Need Revision", len(my_df[my_df['status'] == 'REVISION_REQUESTED']) if not my_df.empty else 0)

    if my_df.empty:
        st.info("No PRs found. Create one from the sidebar.")
        return

    display = my_df.copy()
    display.insert(0, '●', display['status'].map(PR_STATUS_ICONS))
    display['pri'] = display['priority'].map(PRIORITY_ICONS)
    display['total_fmt'] = display['total_amount_vnd'].apply(
        lambda v: f"{v:,.0f}" if v and str(v) not in ('', 'nan', 'None', '0') else '—')
    # Age indicator (P3.4)
    display['⏰'] = display['submitted_date'].apply(_age_icon)
    display = _add_cb_warning_column(display)

    tbl_key = f"my_pr_{st.session_state.get('_my_pr_key', 0)}"
    event = st.dataframe(
        display, key=tbl_key, width="stretch", hide_index=True,
        on_select="rerun", selection_mode="single-row",
        column_config={
            '●': st.column_config.TextColumn('', width=30),
            '⏰': st.column_config.TextColumn('⏰', width=30, help='Pending age: 🔴 >7d, 🟡 >3d'),
            'pri': st.column_config.TextColumn('Pri', width=35),
            'pr_number': st.column_config.TextColumn('PR#'),
            'project_code': st.column_config.TextColumn('Project', width=140),
            'status': st.column_config.TextColumn('Status'),
            'vendor_name': st.column_config.TextColumn('Vendor'),
            'total_fmt': st.column_config.TextColumn('Total VND'),
            'CB': st.column_config.TextColumn('CB', width=30,
                  help='Costbook: ✅ ready | ⚠️ partial | 🔴 none'),
            'item_count': st.column_config.NumberColumn('Items', width=55),
            'created_date': st.column_config.DatetimeColumn('Created'),
            'pr_id': None, 'project_id': None, 'requester_id': None,
            'requester_name': None, 'requester_email': None, 'vendor_id': None,
            'total_amount': None, 'total_amount_vnd': None, 'currency_code': None,
            'exchange_rate': None, 'current_approval_level': None,
            'max_approval_level': None, 'submitted_date': None,
            'approved_date': None, 'required_date': None,
            'po_id': None, 'po_number': None, 'justification': None,
            'rejection_reason': None, 'project_name': None,
            'pr_type': None, 'cogs_category': None, 'priority': None,
        },
    )

    # ── Action bar (context-sensitive — reusable) ──
    sel = event.selection.rows
    if sel:
        row = my_df.iloc[sel[0]]
        st.markdown(f"**Selected:** {row['pr_number']} — "
                    f"{PR_STATUS_ICONS.get(row['status'], '')} {row['status']}")
        _render_pr_action_bar(row, "my")


# ══════════════════════════════════════════════════════════════════
# TAB — Pending Approval (P1.3: redesigned with dataframe pattern)
# ══════════════════════════════════════════════════════════════════

@st.fragment
def _render_pending_tab():
    pending_df = get_pending_for_approver(emp_int_id)

    if pending_df.empty:
        st.info("No PRs pending your approval.")
        return

    # KPIs
    k1, k2, k3, k4 = st.columns(4)
    urgent_count = len(pending_df[pending_df['priority'] == 'URGENT']) if 'priority' in pending_df.columns else 0
    high_count = len(pending_df[pending_df['priority'] == 'HIGH']) if 'priority' in pending_df.columns else 0
    k1.metric("🔴 Urgent", urgent_count)
    k2.metric("🔼 High", high_count)
    k3.metric("Total Pending", len(pending_df))
    total_val = pending_df['total_amount_vnd'].sum() if 'total_amount_vnd' in pending_df.columns else 0
    k4.metric("Total Value", fmt_vnd(total_val))

    st.divider()

    # Dataframe (consistent with IL_3/IL_4 table pattern)
    display = pending_df.copy()
    display.insert(0, '●', display['priority'].map(PRIORITY_ICONS) if 'priority' in display.columns else '➖')
    display['total_fmt'] = display['total_amount_vnd'].apply(
        lambda v: f"{v:,.0f}" if v and str(v) not in ('', 'nan', 'None', '0') else '—') \
        if 'total_amount_vnd' in display.columns else '—'
    # Age indicator
    if 'submitted_date' in display.columns:
        display['⏰'] = display['submitted_date'].apply(_age_icon)
    else:
        display['⏰'] = ''

    tbl_key = f"pending_tbl_{st.session_state.get('_pend_tbl_key', 0)}"
    event = st.dataframe(
        display, key=tbl_key, width="stretch", hide_index=True,
        on_select="rerun", selection_mode="single-row",
        column_config={
            '●': st.column_config.TextColumn('', width=30),
            '⏰': st.column_config.TextColumn('⏰', width=30, help='Pending age: 🔴 >7d, 🟡 >3d'),
            'pr_number': st.column_config.TextColumn('PR#'),
            'project_code': st.column_config.TextColumn('Project', width=140),
            'requester_name': st.column_config.TextColumn('Requester'),
            'vendor_name': st.column_config.TextColumn('Vendor'),
            'total_fmt': st.column_config.TextColumn('Total VND'),
            'priority': st.column_config.TextColumn('Priority', width=80),
            'submitted_date': st.column_config.DatetimeColumn('Submitted'),
            'pr_id': None, 'project_id': None, 'requester_id': None,
            'requester_email': None, 'vendor_id': None,
            'total_amount': None, 'total_amount_vnd': None, 'currency_code': None,
            'exchange_rate': None, 'current_approval_level': None,
            'max_approval_level': None, 'approved_date': None,
            'required_date': None, 'po_id': None, 'po_number': None,
            'justification': None, 'rejection_reason': None, 'project_name': None,
            'pr_type': None, 'cogs_category': None, 'status': None,
            'item_count': None, 'created_date': None, 'approver_id': None,
        },
    )

    # Action bar
    sel = event.selection.rows
    if sel:
        row = pending_df.iloc[sel[0]]
        st.markdown(
            f"**Selected:** {row['pr_number']} — "
            f"{row.get('requester_name', '—')} | "
            f"{fmt_vnd(row.get('total_amount_vnd'))}"
        )
        if row.get('justification'):
            st.caption(f"📝 {str(row['justification'])[:200]}")
        _render_pr_action_bar(row, "pend", show_approve=True)
    else:
        if len(pending_df) > 1:
            st.divider()
            st.caption("💡 Select a row to review individually.")

    # Legend
    st.caption("🔴 >7 days &nbsp;|&nbsp; 🟡 >3 days &nbsp;|&nbsp; Priority: 🔴 Urgent 🔼 High ➖ Normal 🔽 Low")


# ══════════════════════════════════════════════════════════════════
# TAB — All PRs (enhanced)
# ══════════════════════════════════════════════════════════════════

@st.fragment
def _render_all_prs_tab(project_id_filter, status_filter, priority_filter):
    all_df = get_pr_list_df(
        project_id=project_id_filter,
        status=None if status_filter == "All" else status_filter,
    )

    # Apply priority filter
    if priority_filter != "All" and not all_df.empty:
        all_df = all_df[all_df['priority'] == priority_filter]

    if all_df.empty:
        st.info("No PRs found.")
        return

    # KPIs
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total PRs", len(all_df))
    approved_vnd = all_df.loc[all_df['status'].isin(['APPROVED', 'PO_CREATED']), 'total_amount_vnd'].sum()
    k2.metric("Approved Value", fmt_vnd(approved_vnd))
    k3.metric("Pending", len(all_df[all_df['status'] == 'PENDING_APPROVAL']))
    k4.metric("With PO", len(all_df[all_df['status'] == 'PO_CREATED']))

    display = all_df.copy()
    display.insert(0, '●', display['status'].map(PR_STATUS_ICONS))
    display['pri'] = display['priority'].map(PRIORITY_ICONS)
    display['total_fmt'] = display['total_amount_vnd'].apply(
        lambda v: f"{v:,.0f}" if v and str(v) not in ('', 'nan', 'None', '0') else '—')
    if 'submitted_date' in display.columns:
        display['⏰'] = display['submitted_date'].apply(_age_icon)
    else:
        display['⏰'] = ''
    display = _add_cb_warning_column(display)

    tbl_key = f"all_pr_{st.session_state.get('_all_tbl_key', 0)}"
    event = st.dataframe(
        display, key=tbl_key, width="stretch", hide_index=True,
        on_select="rerun", selection_mode="single-row",
        column_config={
            '●': st.column_config.TextColumn('', width=30),
            '⏰': st.column_config.TextColumn('⏰', width=30, help='Pending age: 🔴 >7d, 🟡 >3d'),
            'pri': st.column_config.TextColumn('Pri', width=35),
            'pr_number': st.column_config.TextColumn('PR#'),
            'project_code': st.column_config.TextColumn('Project', width=140),
            'requester_name': st.column_config.TextColumn('Requester'),
            'status': st.column_config.TextColumn('Status'),
            'vendor_name': st.column_config.TextColumn('Vendor'),
            'total_fmt': st.column_config.TextColumn('Total VND'),
            'CB': st.column_config.TextColumn('CB', width=30,
                  help='Costbook: ✅ ready | ⚠️ partial | 🔴 none'),
            'po_number': st.column_config.TextColumn('PO#'),
            'created_date': st.column_config.DatetimeColumn('Created'),
            'pr_id': None, 'project_id': None, 'requester_id': None,
            'requester_email': None, 'vendor_id': None,
            'total_amount': None, 'total_amount_vnd': None, 'currency_code': None,
            'exchange_rate': None, 'current_approval_level': None,
            'max_approval_level': None, 'submitted_date': None,
            'approved_date': None, 'required_date': None,
            'po_id': None, 'justification': None, 'rejection_reason': None,
            'project_name': None, 'item_count': None,
            'pr_type': None, 'cogs_category': None, 'priority': None,
        },
    )

    sel = event.selection.rows
    if sel:
        row = all_df.iloc[sel[0]]
        st.markdown(f"**Selected:** {row['pr_number']} — "
                    f"{PR_STATUS_ICONS.get(row['status'], '')} {row['status']} | "
                    f"By: {row.get('requester_name', '—')}")
        _render_pr_action_bar(row, "all")


# ══════════════════════════════════════════════════════════════════
# MAIN PAGE LAYOUT
# ══════════════════════════════════════════════════════════════════

st.title("🛒 Purchase Request")

if proj_df.empty:
    st.warning("No projects found."); st.stop()

# ── Sidebar (P2.2, P3.1: enriched) ───────────────────────────────
with st.sidebar:
    st.header("Filters")

    # Project selector
    proj_options = ["All Projects"] + [f"{r.project_code} — {r.project_name}" for r in proj_df.itertuples()]
    sel_label = st.selectbox("Project", proj_options, key="pr_project")

    is_all = sel_label == "All Projects"
    project_id = None
    project = None
    if not is_all:
        sel_idx = proj_options.index(sel_label) - 1
        project_id = int(proj_df.iloc[sel_idx]['project_id'])
        project = get_project(project_id)

    # Filters (P3.1 — enhanced)
    f_status = st.selectbox("Status", ["All", "DRAFT", "PENDING_APPROVAL", "APPROVED",
                                        "REJECTED", "REVISION_REQUESTED", "PO_CREATED", "CANCELLED"])
    f_priority = st.selectbox("Priority", ["All", "URGENT", "HIGH", "NORMAL", "LOW"])

    # Project context (P2.2 — sidebar enrich)
    if project:
        st.divider()
        st.caption(f"**{project['project_code']}**")
        st.caption(f"Customer: {project.get('customer_name', '—')}")
        st.caption(f"PM: {project.get('pm_name', '—')}")
        st.caption(f"Status: **{project['status']}**")

        # Budget context in sidebar
        est = get_active_estimate(project_id)
        if est:
            est_cogs = float(est.get('total_cogs', 0) or 0)
            if est_cogs > 0:
                st.caption(f"💰 Budget: {fmt_vnd(est_cogs)}")

        # Quick PR count
        pr_count_df = get_pr_list_df(project_id=project_id)
        if not pr_count_df.empty:
            active = len(pr_count_df[pr_count_df['status'].isin(['DRAFT', 'PENDING_APPROVAL', 'APPROVED'])])
            st.caption(f"📋 PRs: {active} active / {len(pr_count_df)} total")

        # Action button
        is_pm = is_project_pm(project_id, emp_int_id)
        if is_pm or is_admin:
            st.divider()
            if st.button("➕ New PR", type="primary", use_container_width=True):
                # Reset wizard state for a fresh start
                for _k in [k for k in st.session_state if k.startswith('pr_wiz_')]:
                    del st.session_state[_k]
                st.session_state['open_create_pr'] = True


# ── Deep link handler (from email — saved in session state before auth) ──
_dl = st.session_state.pop('_deep_link', None)
if _dl:
    try:
        _deep_pr_id = int(_dl['pr_id'])
        _deep_action = _dl.get('action', 'view')
        _action_map = {
            'view':    'open_pr_view',
            'approve': 'open_pr_approve',
            'edit':    'open_pr_edit',
        }
        _ss_key = _action_map.get(_deep_action, 'open_pr_view')
        st.session_state[_ss_key] = _deep_pr_id
        st.rerun()
    except (ValueError, TypeError):
        pass


# ── Main content ─────────────────────────────────────────────────

if is_all:
    # ── All Projects — Overview Dashboard (P1.1) ─────────────────
    tab_overview, tab_pending_all, tab_all_prs = st.tabs([
        "📊 Overview",
        "⏳ Pending Approval",
        "📋 All PRs",
    ])

    with tab_overview:
        _render_overview(f_status, f_priority)

    with tab_pending_all:
        _render_pending_tab()

    with tab_all_prs:
        _render_all_prs_tab(None, f_status, f_priority)

else:
    # ── Per-project mode ─────────────────────────────────────────
    if not project:
        st.error("Project not found."); st.stop()

    # Context banner (P2.1)
    st.caption(
        f"**{project['project_code']}** — {project['project_name']} | "
        f"Customer: {project.get('customer_name') or project.get('end_customer_name', '—')} | "
        f"Status: **{project['status']}**"
    )

    # Budget tracking bar (compact)
    _render_budget_comparison(project_id, mode='compact')

    # Tabs
    tab_my, tab_pending, tab_all = st.tabs([
        "📋 My PRs",
        "⏳ Pending Approval",
        "📊 All PRs",
    ])

    with tab_my:
        _render_my_prs_tab(project_id, f_status, f_priority)

    with tab_pending:
        _render_pending_tab()

    with tab_all:
        _render_all_prs_tab(project_id, f_status, f_priority)


# ══════════════════════════════════════════════════════════════════
# DIALOG TRIGGERS
# ══════════════════════════════════════════════════════════════════

# Create PR — use 'get' (not pop) so dialog survives st.rerun() in wizard steps
if st.session_state.get('open_create_pr') and project_id:
    _dialog_create_pr(project_id)

# View PR (P1.2)
if 'open_pr_view' in st.session_state:
    pid = st.session_state.pop('open_pr_view')
    _dialog_pr_view(pid)

# Edit PR (P1.2)
if 'open_pr_edit' in st.session_state:
    pid = st.session_state.pop('open_pr_edit')
    _dialog_pr_edit(pid)

# Reduce PR Items (APPROVED status — reduce only)
if 'open_pr_reduce' in st.session_state:
    pid = st.session_state.pop('open_pr_reduce')
    _dialog_pr_reduce(pid)

# Confirm Cancel (P3.5)
if 'confirm_cancel_pr' in st.session_state:
    pid = st.session_state.pop('confirm_cancel_pr')
    _dialog_confirm_cancel(pid)

# Confirm Create PO (P3.5)
if 'confirm_create_po' in st.session_state:
    pid = st.session_state.pop('confirm_create_po')
    _dialog_confirm_po(pid)

# Approval Action (from fragment tabs)
if 'open_pr_approve' in st.session_state:
    pid = st.session_state.pop('open_pr_approve')
    _dialog_approval_action(pid)