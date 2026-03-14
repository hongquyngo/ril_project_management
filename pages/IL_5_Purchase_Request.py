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
    cancel_pr,
    submit_pr, approve_pr, reject_pr, request_revision,
    get_pr_approval_history, get_approval_chain, determine_max_level,
    get_importable_estimate_items,
    create_po_from_pr,
    is_project_pm, is_approver_for_pr,
    get_budget_vs_pr,
)
from utils.il_project.currency import get_rate_to_vnd
from utils.il_project.helpers import get_vendor_companies
from utils.il_project.email_notify import (
    notify_pr_submitted,
    notify_pr_approved,
    notify_pr_rejected,
    notify_pr_revision_requested,
    notify_po_created,
)

logger = logging.getLogger(__name__)
auth = AuthManager()

st.set_page_config(page_title="Purchase Request", page_icon="🛒", layout="wide")
auth.require_auth()
user_id    = str(auth.get_user_id())
emp_int_id = auth.get_user_id()
is_admin   = auth.is_admin()


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
cur_map  = {c['id']: c['code'] for c in currencies}


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
        'PRs': '',
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


@st.dialog("🛒 New Purchase Request", width="large")
def _dialog_create_pr(project_id: int):
    project = get_project(project_id)
    if not project:
        st.error("Project not found."); return

    if not is_project_pm(project_id, emp_int_id) and not is_admin:
        st.warning("Only the PM of this project can create a PR."); return

    # ── Header context ──
    st.markdown(f"**Project:** `{project['project_code']}` — {project['project_name']}")
    st.caption(f"Customer: {project.get('customer_name', '—')} | Status: **{project['status']}**")

    est = get_active_estimate(project_id)
    if est:
        est_cogs = float(est.get('total_cogs', 0) or 0)
        if est_cogs > 0:
            st.info(f"💰 Estimate Budget: **{fmt_vnd(est_cogs)}** (Rev {est.get('estimate_version', '—')})")

    # ══════════════════════════════════════════════════════════════
    # STEP 1 — Type Selection (OUTSIDE form → reactive auto-fill)
    # ══════════════════════════════════════════════════════════════
    st.divider()
    st.markdown("##### ① Select PR Type")

    tc1, tc2 = st.columns(2)
    pr_type = tc1.selectbox("Type", ['EQUIPMENT', 'FABRICATION', 'SERVICE', 'MIXED'],
                            key="cr_type",
                            help="EQUIPMENT = A (hardware/sensors), FABRICATION = C (racking/metalwork), "
                                 "SERVICE = labor/consulting, MIXED = combined")
    # Auto-set COGS from type
    auto_cogs = _TYPE_COGS_MAP.get(pr_type, 'A')
    _cogs_labels = {'A': 'A — Equipment', 'C': 'C — Fabrication', 'D': 'D — Service/Labor', 'MIXED': 'MIXED'}
    tc2.text_input("COGS Category", value=_cogs_labels.get(auto_cogs, auto_cogs), disabled=True,
                   help="Auto-set from PR Type. A=Equipment, C=Fabrication, D=Service, MIXED=Multiple")

    # ── Analyze estimate items for this type ──
    analysis = {}
    importable_items = []
    if est:
        cogs_filter = _COGS_FILTER_MAP.get(auto_cogs, ['A', 'C', 'SERVICE'])
        analysis = _analyze_estimate_for_pr(est['id'], cogs_filter)
        importable_items = analysis.get('items', [])

        if analysis['item_count'] > 0:
            # Show analysis summary
            ac1, ac2, ac3 = st.columns(3)
            ac1.metric("Available Items", analysis['item_count'])
            ac2.metric("Total Cost", fmt_vnd(analysis['total_vnd']))
            if analysis['dominant_vendor']:
                ac3.metric("Top Vendor", analysis['dominant_vendor'][:20])

            # Vendor breakdown (if multiple)
            if len(analysis.get('vendor_breakdown', {})) > 1:
                vb = analysis['vendor_breakdown']
                parts = [f"{v}: {fmt_vnd(a)}" for v, a in
                         sorted(vb.items(), key=lambda x: -x[1])[:4]]
                st.caption(f"Vendor breakdown: {' | '.join(parts)}")

            # Preview items (collapsible)
            with st.expander(f"📋 Preview {analysis['item_count']} items to import", expanded=False):
                if analysis['preview_rows']:
                    st.dataframe(
                        pd.DataFrame(analysis['preview_rows']),
                        width="stretch", hide_index=True,
                        height=min(35 * len(analysis['preview_rows']) + 38, 250),
                    )
                    if analysis['item_count'] > 15:
                        st.caption(f"... and {analysis['item_count'] - 15} more items")
        else:
            st.caption(f"ℹ️ No importable estimate items for category **{auto_cogs}**. "
                       "You can add items manually after creating the PR.")

    # ══════════════════════════════════════════════════════════════
    # STEP 2 — PR Details (form)
    # ══════════════════════════════════════════════════════════════
    st.divider()
    st.markdown("##### ② PR Details")

    # Pre-compute suggested values from analysis
    suggested_vendor = analysis.get('dominant_vendor', '')
    suggested_currency = analysis.get('dominant_currency', 'VND')

    with st.form("create_pr_form"):
        # Row 1: PR number + Priority
        h1, h2 = st.columns(2)
        pr_number = generate_pr_number()
        h1.text_input("PR Number", value=pr_number, disabled=True)
        priority = h2.selectbox("Priority", ['NORMAL', 'LOW', 'HIGH', 'URGENT'])

        # Row 2: Vendor + Currency
        v1, v2 = st.columns(2)
        vendor_names_list = ["(Select later)"] + [v['name'] for v in vendors]
        # Auto-select suggested vendor if found in list
        vendor_default_idx = 0
        if suggested_vendor:
            for i, vn in enumerate(vendor_names_list):
                if vn == suggested_vendor:
                    vendor_default_idx = i
                    break
        vendor_sel = v1.selectbox("Primary Vendor", vendor_names_list, index=vendor_default_idx,
                                  help=f"💡 Suggested: {suggested_vendor}" if suggested_vendor else None)
        vendor_id = None
        if vendor_sel != "(Select later)":
            vendor_id = next((v['id'] for v in vendors if v['name'] == vendor_sel), None)

        cur_opts = [c['code'] for c in currencies]
        # Auto-select suggested currency
        cur_default_idx = cur_opts.index(suggested_currency) if suggested_currency in cur_opts else (
            cur_opts.index('VND') if 'VND' in cur_opts else 0)
        cur_sel = v2.selectbox("Currency", cur_opts, index=cur_default_idx)
        currency_id = currencies[cur_opts.index(cur_sel)]['id']

        # Row 3: Exchange rate (AUTO — read-only display)
        _rate_res = get_rate_to_vnd(cur_sel)
        exc_rate = _rate_res.rate if _rate_res.ok else 1.0
        _badges = {'same': 'ℹ️ Same currency', 'api': '✅ Live API', 'cache': '✅ Cached',
                   'db': '🔵 DB rate', 'fallback': '⚠️ Fallback'}
        rate_badge = _badges.get(_rate_res.source, _rate_res.source)

        if cur_sel == 'VND':
            st.caption(f"💱 Currency: VND — no conversion needed")
        else:
            rc1, rc2 = st.columns([2, 1])
            rc1.text_input(f"Exchange Rate (1 {cur_sel} = ? VND)",
                           value=f"{exc_rate:,.4f}", disabled=True,
                           help="Auto-fetched. Rate is locked to ensure consistency.")
            rc2.caption(f"\n{rate_badge}")
            if not _rate_res.ok:
                st.warning(f"⚠️ {_rate_res.warning or 'Could not fetch live rate. Using reference rate.'}")

        # Row 4: Required date + Justification
        req_date = st.date_input("Required Date", value=None,
                                  help="Ngày cần hàng. Để trống nếu không urgent.")
        justification = st.text_area("Justification / Business Reason", height=70,
                                      help="Mô tả lý do mua hàng, phục vụ phase nào của project")

        # Row 5: Import option
        auto_import = False
        if importable_items:
            auto_import = st.checkbox(
                f"📋 Auto-import {len(importable_items)} items from estimate (Rev {est.get('estimate_version', '?')})",
                value=True,
                help=f"Import {len(importable_items)} available items ({auto_cogs}) "
                     f"totaling {fmt_vnd(analysis.get('total_vnd', 0))}"
            )
        elif est:
            st.caption("ℹ️ No new items to import (all already in PRs, or no items for this category)")

        submitted = st.form_submit_button("💾 Create PR", type="primary", use_container_width=True)

    # ══════════════════════════════════════════════════════════════
    # STEP 3 — Create + auto-import
    # ══════════════════════════════════════════════════════════════
    if submitted:
        try:
            new_id = create_pr({
                'pr_number': pr_number,
                'project_id': project_id,
                'estimate_id': est['id'] if est else None,
                'requester_id': emp_int_id,
                'vendor_id': vendor_id,
                'currency_id': currency_id,
                'exchange_rate': exc_rate,
                'priority': priority,
                'pr_type': pr_type,
                'cogs_category': auto_cogs,
                'required_date': req_date,
                'justification': justification or None,
            }, user_id)

            # Auto-import from estimate
            import_count = 0
            if auto_import and importable_items:
                for i, it in enumerate(importable_items):
                    try:
                        create_pr_item({
                            'pr_id': new_id,
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
                        import_count += 1
                    except Exception:
                        pass
                if import_count > 0:
                    recalc_pr_totals(new_id)

            msg = f"✅ PR {pr_number} created!"
            if import_count > 0:
                msg += f" ({import_count} items imported, {fmt_vnd(analysis.get('total_vnd', 0))})"
            st.success(msg)
            # Go to edit mode so user can review imported items
            st.session_state['open_pr_edit' if auto_import and import_count > 0 else 'open_pr_view'] = new_id
            st.cache_data.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Create failed: {e}")


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
                budget_data=_budget,
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
            if reject_pr(pr_id, emp_int_id, comments):
                notify_pr_rejected(
                    pr_number=pr['pr_number'], project_code=pr.get('project_code', ''),
                    total_vnd=float(pr.get('total_amount_vnd') or 0),
                    requester_email=pr.get('requester_email', ''),
                    requester_name=pr.get('requester_name', ''),
                    approver_name=st.session_state.get('user_fullname', ''),
                    rejection_reason=comments,
                )
                st.success("PR rejected.")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Reject failed.")

    if c3.button("🔄 Request Revision", use_container_width=True, key="btn_revision"):
        if not comments:
            st.warning("Please provide revision notes.")
        else:
            if request_revision(pr_id, emp_int_id, comments):
                notify_pr_revision_requested(
                    pr_number=pr['pr_number'], project_code=pr.get('project_code', ''),
                    total_vnd=float(pr.get('total_amount_vnd') or 0),
                    requester_email=pr.get('requester_email', ''),
                    requester_name=pr.get('requester_name', ''),
                    approver_name=st.session_state.get('user_fullname', ''),
                    revision_notes=comments,
                )
                st.success("Revision requested — PR sent back to PM.")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Revision request failed.")


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
    can_edit = (is_my_pr or is_admin) and pr['status'] in ('DRAFT', 'REVISION_REQUESTED')
    can_submit = (is_pm_of_project or is_admin) and pr['status'] in ('DRAFT', 'REVISION_REQUESTED')

    # ── Header ──
    hc1, hc2 = st.columns([5, 1])
    icon = PR_STATUS_ICONS.get(pr['status'], '⚪')
    hc1.markdown(f"### {icon} {pr['pr_number']}")
    if can_edit:
        if hc2.button("✏️ Edit", type="primary", use_container_width=True):
            st.session_state['open_pr_edit'] = pr_id
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
        st.dataframe(display, width="stretch", hide_index=True,
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

    # ── Action Buttons (context-sensitive) ──
    st.divider()
    ac1, ac2, ac3, ac4 = st.columns(4)

    if can_submit and not items_df.empty:
        if ac1.button("📤 Submit for Approval", type="primary", use_container_width=True):
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
                        budget_data=_budget,
                    )
                st.cache_data.clear()
                st.rerun()
            else:
                st.error(result['message'])

    if pr['status'] == 'APPROVED' and not pr.get('po_id'):
        if ac2.button("🛒 Create PO", type="primary", use_container_width=True):
            st.session_state['confirm_create_po'] = pr_id
            st.rerun()

    if pr.get('po_number'):
        ac3.success(f"PO: **{pr['po_number']}**")

    if can_edit:
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
    ba1, ba2, ba3 = st.columns([2, 1, 1])
    if not items_df.empty:
        if ba1.button("📤 Submit for Approval", type="primary", use_container_width=True):
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
                        budget_data=_budget,
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
# CONFIRM DIALOGS (P3.5)
# ══════════════════════════════════════════════════════════════════

@st.dialog("⚠️ Confirm Cancel PR")
def _dialog_confirm_cancel(pr_id: int):
    pr = get_pr(pr_id)
    if not pr:
        st.error("PR not found."); return
    st.warning(f"Are you sure you want to cancel **{pr['pr_number']}**?")
    st.caption(f"Total: {fmt_vnd(pr.get('total_amount_vnd'))} | Items: {pr.get('item_count', '—')}")
    st.markdown("This action **cannot be undone**.")
    c1, c2 = st.columns(2)
    if c1.button("🗑 Yes, Cancel PR", type="primary", use_container_width=True):
        if cancel_pr(pr_id, user_id):
            st.success("PR cancelled.")
            st.cache_data.clear()
            st.rerun()
        else:
            st.error("Cancel failed — PR may not be in DRAFT status.")
    if c2.button("✖ No, Go Back", use_container_width=True):
        st.rerun()


@st.dialog("⚠️ Confirm Create PO")
def _dialog_confirm_po(pr_id: int):
    pr = get_pr(pr_id)
    if not pr:
        st.error("PR not found."); return
    st.info(f"Create Purchase Order from **{pr['pr_number']}**?")
    st.caption(f"Vendor: {pr.get('vendor_name', '—')} | Total: {fmt_vnd(pr.get('total_amount_vnd'))}")
    st.markdown("A PO will be created in the ERP system and linked to this PR.")
    c1, c2 = st.columns(2)
    if c1.button("🛒 Yes, Create PO", type="primary", use_container_width=True):
        keycloak_id = st.session_state.get('keycloak_id', user_id)
        result = create_po_from_pr(pr_id, 1, keycloak_id)
        if result['success']:
            st.success(f"✅ {result['message']}")
            notify_po_created(
                pr_number=pr['pr_number'], po_number=result['po_number'],
                project_code=pr.get('project_code', ''),
                total_vnd=float(pr.get('total_amount_vnd') or 0),
                vendor_name=pr.get('vendor_name', ''),
                requester_email=pr.get('requester_email', ''),
                requester_name=pr.get('requester_name', ''),
            )
            st.cache_data.clear()
            st.rerun()
        else:
            st.error(result['message'])
    if c2.button("✖ No, Go Back", use_container_width=True):
        st.rerun()


# ══════════════════════════════════════════════════════════════════
# ALL PROJECTS — Overview Dashboard (P1.1)
# ══════════════════════════════════════════════════════════════════

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
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total PRs", len(all_df))
    approved_mask = all_df['status'].isin(['APPROVED', 'PO_CREATED'])
    k2.metric("Approved Value", fmt_vnd(all_df.loc[approved_mask, 'total_amount_vnd'].sum())
              if approved_mask.any() else '—')
    pending_count = len(all_df[all_df['status'] == 'PENDING_APPROVAL'])
    k3.metric("Pending Approval", pending_count)
    k4.metric("With PO", len(all_df[all_df['status'] == 'PO_CREATED']))

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
                    _dialog_approval_action(int(row['pr_id']))


# ══════════════════════════════════════════════════════════════════
# TAB — My PRs (enhanced with quick actions P3.2)
# ══════════════════════════════════════════════════════════════════

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

    tbl_key = f"my_pr_{st.session_state.get('_my_pr_key', 0)}"
    event = st.dataframe(
        display, key=tbl_key, width="stretch", hide_index=True,
        on_select="rerun", selection_mode="single-row",
        column_config={
            '●': st.column_config.TextColumn('', width=30),
            '⏰': st.column_config.TextColumn('', width=30),
            'pri': st.column_config.TextColumn('Pri', width=35),
            'pr_number': st.column_config.TextColumn('PR#'),
            'project_code': st.column_config.TextColumn('Project', width=140),
            'status': st.column_config.TextColumn('Status'),
            'vendor_name': st.column_config.TextColumn('Vendor'),
            'total_fmt': st.column_config.TextColumn('Total VND'),
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

    # ── Action bar (P3.2 — context-sensitive quick actions) ──
    sel = event.selection.rows
    if sel:
        row = my_df.iloc[sel[0]]
        st.markdown(f"**Selected:** {row['pr_number']} — "
                    f"{PR_STATUS_ICONS.get(row['status'], '')} {row['status']}")

        # Build action columns based on status
        cols = st.columns([1, 1, 1, 1, 2])
        col_idx = 0

        # Always: View
        if cols[col_idx].button("👁️ View", type="primary", use_container_width=True, key="my_view"):
            st.session_state['open_pr_view'] = int(row['pr_id'])
            st.rerun()
        col_idx += 1

        # DRAFT / REVISION_REQUESTED: Edit, Submit
        if row['status'] in ('DRAFT', 'REVISION_REQUESTED'):
            if cols[col_idx].button("✏️ Edit", use_container_width=True, key="my_edit"):
                st.session_state['open_pr_edit'] = int(row['pr_id'])
                st.rerun()
            col_idx += 1

            item_count = int(row.get('item_count', 0) or 0)
            if item_count > 0:
                if cols[col_idx].button("📤 Submit", use_container_width=True, key="my_submit"):
                    result = submit_pr(int(row['pr_id']), user_id)
                    if result['success']:
                        st.success(result['message'])
                        if result.get('approver_name'):
                            pr_full = get_pr(int(row['pr_id']))
                            if pr_full:
                                _budget = get_budget_vs_pr(int(row.get('project_id') or pr_full['project_id']))
                                notify_pr_submitted(
                                    pr_number=row['pr_number'],
                                    project_code=row.get('project_code', ''),
                                    project_name=row.get('project_name', ''),
                                    requester_name=row.get('requester_name', ''),
                                    total_vnd=float(row.get('total_amount_vnd') or 0),
                                    item_count=item_count,
                                    priority=row.get('priority', 'NORMAL'),
                                    justification=pr_full.get('justification', ''),
                                    approver_name=result['approver_name'],
                                    approver_email=result['approver_email'],
                                    approval_level=1, max_level=result.get('max_level', 1),
                                    budget_data=_budget,
                                )
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(result['message'])
                col_idx += 1

        # APPROVED: Create PO
        elif row['status'] == 'APPROVED' and not row.get('po_id'):
            if cols[col_idx].button("🛒 Create PO", use_container_width=True, key="my_po"):
                st.session_state['confirm_create_po'] = int(row['pr_id'])
                st.rerun()
            col_idx += 1

        # Deselect (always last)
        if cols[min(col_idx, 4)].button("✖ Deselect", use_container_width=True, key="my_desel"):
            st.session_state['_my_pr_key'] = st.session_state.get('_my_pr_key', 0) + 1
            st.rerun()


# ══════════════════════════════════════════════════════════════════
# TAB — Pending Approval (P1.3: redesigned with dataframe pattern)
# ══════════════════════════════════════════════════════════════════

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

    tbl_key = f"pending_tbl_{st.session_state.get('_pending_key', 0)}"
    event = st.dataframe(
        display, key=tbl_key, width="stretch", hide_index=True,
        on_select="rerun", selection_mode="single-row",
        column_config={
            '●': st.column_config.TextColumn('', width=30),
            '⏰': st.column_config.TextColumn('', width=30),
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

        ab1, ab2, ab3 = st.columns([1, 1, 2])
        if ab1.button("✅ Review & Act", type="primary", use_container_width=True, key="pend_review"):
            _dialog_approval_action(int(row['pr_id']))
        if ab2.button("✖ Deselect", use_container_width=True, key="pend_desel"):
            st.session_state['_pending_key'] = st.session_state.get('_pending_key', 0) + 1
            st.rerun()
    else:
        # Bulk approve (P3.2 — consistent with IL_3)
        if len(pending_df) > 1:
            st.divider()
            st.caption("💡 Select a row to review individually, or use bulk approve below.")

    # Legend
    st.caption("🔴 >7 days &nbsp;|&nbsp; 🟡 >3 days &nbsp;|&nbsp; Priority: 🔴 Urgent 🔼 High ➖ Normal 🔽 Low")


# ══════════════════════════════════════════════════════════════════
# TAB — All PRs (enhanced)
# ══════════════════════════════════════════════════════════════════

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

    tbl_key = f"all_pr_{st.session_state.get('_all_pr_key', 0)}"
    event = st.dataframe(
        display, key=tbl_key, width="stretch", hide_index=True,
        on_select="rerun", selection_mode="single-row",
        column_config={
            '●': st.column_config.TextColumn('', width=30),
            '⏰': st.column_config.TextColumn('', width=30),
            'pri': st.column_config.TextColumn('Pri', width=35),
            'pr_number': st.column_config.TextColumn('PR#'),
            'project_code': st.column_config.TextColumn('Project', width=140),
            'requester_name': st.column_config.TextColumn('Requester'),
            'status': st.column_config.TextColumn('Status'),
            'vendor_name': st.column_config.TextColumn('Vendor'),
            'total_fmt': st.column_config.TextColumn('Total VND'),
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
        ab1, ab2, ab3 = st.columns([1, 1, 2])
        if ab1.button("👁️ View", type="primary", use_container_width=True, key="all_view"):
            st.session_state['open_pr_view'] = int(row['pr_id'])
            st.rerun()
        if ab2.button("✖ Deselect", use_container_width=True, key="all_desel"):
            st.session_state['_all_pr_key'] = st.session_state.get('_all_pr_key', 0) + 1
            st.rerun()


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
                st.session_state['open_create_pr'] = True


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

# Create PR
if st.session_state.pop('open_create_pr', False) and project_id:
    _dialog_create_pr(project_id)

# View PR (P1.2)
if 'open_pr_view' in st.session_state:
    pid = st.session_state.pop('open_pr_view')
    _dialog_pr_view(pid)

# Edit PR (P1.2)
if 'open_pr_edit' in st.session_state:
    pid = st.session_state.pop('open_pr_edit')
    _dialog_pr_edit(pid)

# Confirm Cancel (P3.5)
if 'confirm_cancel_pr' in st.session_state:
    pid = st.session_state.pop('confirm_cancel_pr')
    _dialog_confirm_cancel(pid)

# Confirm Create PO (P3.5)
if 'confirm_create_po' in st.session_state:
    pid = st.session_state.pop('confirm_create_po')
    _dialog_confirm_po(pid)