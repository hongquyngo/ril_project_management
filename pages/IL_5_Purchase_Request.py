# pages/IL_5_🛒_Purchase_Request.py
"""
Purchase Request — Create / Submit / Approve / Track / Create PO

UX Flow:
  Sidebar: Project selector, filters
  Tab 1 — My PRs: PM's own PRs (create, edit, submit, track)
  Tab 2 — Pending Approval: PRs waiting for current user's approval
  Tab 3 — All PRs: Dashboard with filters

Permissions:
  - Submit PR: only PM of the project
  - Approve/Reject/Revision: only configured approvers in approval_authorities
  - Create PO: anyone with approval, or admin
"""

import streamlit as st
import pandas as pd
from datetime import date
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


# ── Lookups ──────────────────────────────────────────────────────────
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


# ══════════════════════════════════════════════════════════════════════
# STATUS DISPLAY HELPERS
# ══════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════
# DIALOGS — Create PR
# ══════════════════════════════════════════════════════════════════════

@st.dialog("🛒 New Purchase Request", width="large")
def _dialog_create_pr(project_id: int):
    project = get_project(project_id)
    if not project:
        st.error("Project not found."); return

    # Check PM
    if not is_project_pm(project_id, emp_int_id) and not is_admin:
        st.warning("Only the PM of this project can create a PR."); return

    st.markdown(f"**Project:** `{project['project_code']}` — {project['project_name']}")

    with st.form("create_pr_form"):
        # ── Header fields ──
        h1, h2 = st.columns(2)
        pr_number = generate_pr_number()
        h1.text_input("PR Number", value=pr_number, disabled=True)
        priority = h2.selectbox("Priority", ['NORMAL', 'LOW', 'HIGH', 'URGENT'])

        h3, h4, h5 = st.columns(3)
        pr_type = h3.selectbox("Type", ['EQUIPMENT', 'FABRICATION', 'SERVICE', 'MIXED'])
        cogs_cat = h4.selectbox("COGS Category", ['A', 'C', 'MIXED', 'SERVICE'])
        req_date = h5.date_input("Required Date", value=None)

        # Vendor
        v1, v2 = st.columns(2)
        vendor_names = ["(Select later)"] + [v['name'] for v in vendors]
        vendor_sel = v1.selectbox("Primary Vendor", vendor_names)
        vendor_id = None
        if vendor_sel != "(Select later)":
            vendor_id = next((v['id'] for v in vendors if v['name'] == vendor_sel), None)

        cur_opts = [c['code'] for c in currencies]
        cur_sel = v2.selectbox("Currency", cur_opts,
                               index=cur_opts.index('VND') if 'VND' in cur_opts else 0)
        currency_id = currencies[cur_opts.index(cur_sel)]['id']

        # Exchange rate
        _rate_res = get_rate_to_vnd(cur_sel)
        exc_rate = st.number_input(
            f"Exchange Rate (1 {cur_sel} = ? VND)",
            value=_rate_res.rate if _rate_res.ok else 1.0,
            min_value=0.0, format="%.4f"
        )

        justification = st.text_area("Justification / Business Reason", height=80,
                                      help="Mô tả lý do mua hàng, phục vụ phase nào của project")

        submitted = st.form_submit_button("💾 Create PR", type="primary", use_container_width=True)

    if submitted:
        try:
            est = get_active_estimate(project_id)
            new_id = create_pr({
                'pr_number': pr_number,
                'project_id': project_id,
                'estimate_id': est['id'] if est else None,
                'requester_id': emp_int_id,
                'vendor_id': vendor_id,
                'vendor_contact_id': None,
                'currency_id': currency_id,
                'exchange_rate': exc_rate,
                'priority': priority,
                'pr_type': pr_type,
                'cogs_category': cogs_cat,
                'required_date': req_date,
                'justification': justification or None,
            }, user_id)
            st.success(f"✅ PR {pr_number} created!")
            st.session_state['open_pr_detail'] = new_id
            st.cache_data.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Create failed: {e}")


# ══════════════════════════════════════════════════════════════════════
# DIALOGS — Import Estimate Items
# ══════════════════════════════════════════════════════════════════════

@st.dialog("📋 Import from Estimate", width="large")
def _dialog_import_estimate(pr_id: int, estimate_id: int):
    items = get_importable_estimate_items(estimate_id)
    if not items:
        st.info("No estimate line items found."); return

    st.markdown(f"**{len(items)} items** from active estimate")

    # Show items with selection
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
                        'notes': f"Imported from estimate",
                        'view_order': i,
                    }, user_id)
                    count += 1
                except Exception as e:
                    st.warning(f"Failed to import {it.get('item_description', '')}: {e}")
            recalc_pr_totals(pr_id)
            st.success(f"✅ Imported {count} items!")
            st.rerun()


# ══════════════════════════════════════════════════════════════════════
# DIALOGS — Add Manual Item
# ══════════════════════════════════════════════════════════════════════

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
        vendor_names = ["(None)"] + [v['name'] for v in vendors]
        vendor_sel = m6.selectbox("Vendor", vendor_names)
        vendor_ref = m7.text_input("Quote Reference")

        specs = st.text_area("Specifications", height=60)
        notes = st.text_input("Notes")

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


# ══════════════════════════════════════════════════════════════════════
# DIALOGS — Approval Actions
# ══════════════════════════════════════════════════════════════════════

@st.dialog("✅ Approve / ❌ Reject", width="large")
def _dialog_approval_action(pr_id: int):
    pr = get_pr(pr_id)
    if not pr:
        st.error("PR not found."); return

    st.markdown(f"### {pr['pr_number']} — {pr.get('vendor_name', 'No vendor')}")
    st.caption(f"Project: {pr['project_code']} | Amount: {fmt_vnd(pr.get('total_amount_vnd'))} | "
               f"Level: {pr['current_approval_level']}/{pr['max_approval_level']}")

    # Show items
    items_df = get_pr_items_df(pr_id)
    if not items_df.empty:
        st.subheader(f"📋 Items ({len(items_df)})")
        display_df = items_df[['cogs_category', 'item_description', 'vendor_name',
                                'quantity', 'unit_cost', 'currency_code', 'amount_vnd']].copy()
        display_df['amount_vnd'] = display_df['amount_vnd'].apply(
            lambda v: f"{v:,.0f}" if v else '—')
        st.dataframe(display_df, width="stretch", hide_index=True)

    if pr.get('justification'):
        st.info(f"📝 **Justification:** {pr['justification']}")

    # Approval history
    history = get_pr_approval_history(pr_id)
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


# ══════════════════════════════════════════════════════════════════════
# PR DETAIL VIEW
# ══════════════════════════════════════════════════════════════════════

@st.dialog("🛒 Purchase Request Detail", width="large")
def _dialog_pr_detail(pr_id: int):
    pr = get_pr(pr_id)
    if not pr:
        st.error("PR not found."); return

    is_pm_of_project = is_project_pm(pr['project_id'], emp_int_id)
    is_my_pr = pr['requester_id'] == emp_int_id
    can_edit = (is_my_pr or is_admin) and pr['status'] in ('DRAFT', 'REVISION_REQUESTED')
    can_submit = (is_pm_of_project or is_admin) and pr['status'] in ('DRAFT', 'REVISION_REQUESTED')

    # ── Header ──
    icon = PR_STATUS_ICONS.get(pr['status'], '⚪')
    st.markdown(f"### {icon} {pr['pr_number']} — {pr['status']}")
    st.caption(f"Project: **{pr['project_code']}** — {pr['project_name']} | "
               f"Requester: {pr.get('requester_name', '—')}")

    # ── KPIs ──
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total (VND)", fmt_vnd(pr.get('total_amount_vnd')))
    k2.metric("Priority", f"{PRIORITY_ICONS.get(pr['priority'], '')} {pr['priority']}")
    k3.metric("Approval", f"L{pr['current_approval_level']}/{pr['max_approval_level']}")
    k4.metric("Status", pr['status'])

    # ── Revision/Rejection notes ──
    if pr.get('revision_notes') and pr['status'] == 'REVISION_REQUESTED':
        st.warning(f"🔄 **Revision requested:** {pr['revision_notes']}")
    if pr.get('rejection_reason') and pr['status'] == 'REJECTED':
        st.error(f"❌ **Rejected:** {pr['rejection_reason']}")

    # ── Line Items ──
    items_df = get_pr_items_df(pr_id)
    st.divider()
    st.subheader(f"📋 Items ({len(items_df)})")

    if can_edit:
        btn1, btn2, btn3, _ = st.columns([1, 1, 1, 2])
        if pr.get('estimate_id') and btn1.button("📋 Import Estimate", use_container_width=True):
            _dialog_import_estimate(pr_id, pr['estimate_id'])
        if btn2.button("➕ Add Manual", use_container_width=True):
            _dialog_add_manual_item(pr_id, pr.get('currency_id'), float(pr.get('exchange_rate', 1)))
        if not items_df.empty and btn3.button("🗑 Remove Last", use_container_width=True):
            last_id = int(items_df.iloc[-1]['id'])
            delete_pr_item(last_id)
            recalc_pr_totals(pr_id)
            st.rerun()

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
                'vendor_quote_ref': None, 'pt_code': None,
            })
    else:
        st.info("No items yet. Use Import or Add Manual above.")

    # ── Justification ──
    if pr.get('justification'):
        st.divider()
        st.markdown(f"**Justification:** {pr['justification']}")

    # ── Approval History ──
    history = get_pr_approval_history(pr_id)
    if history:
        st.divider()
        st.subheader("📜 Approval History")
        for h in history:
            hicon = {'APPROVED': '✅', 'REJECTED': '❌', 'REVISION_REQUESTED': '🔄',
                     'SUBMITTED': '📤'}.get(h['approval_status'], '⚪')
            st.caption(f"{hicon} Level {h['approval_level']} — {h['approver_name']} — "
                       f"**{h['approval_status']}** — {h.get('comments', '')}")

    # ── Action Buttons ──
    st.divider()
    ac1, ac2, ac3, ac4 = st.columns(4)

    if can_submit and not items_df.empty:
        if ac1.button("📤 Submit for Approval", type="primary", use_container_width=True):
            result = submit_pr(pr_id, user_id)
            if result['success']:
                st.success(result['message'])
                if result.get('approver_name'):
                    st.info(f"📧 Sent to: **{result['approver_name']}** ({result.get('approver_email', '')})")
                    # Email notification
                    notify_pr_submitted(
                        pr_number=pr['pr_number'], project_code=pr.get('project_code', ''),
                        project_name=pr.get('project_name', ''), requester_name=pr.get('requester_name', ''),
                        total_vnd=float(pr.get('total_amount_vnd') or 0),
                        item_count=len(items_df), priority=pr.get('priority', 'NORMAL'),
                        justification=pr.get('justification', ''),
                        approver_name=result['approver_name'], approver_email=result['approver_email'],
                        approval_level=1, max_level=result.get('max_level', 1),
                    )
                st.cache_data.clear()
                st.rerun()
            else:
                st.error(result['message'])

    if pr['status'] == 'APPROVED' and not pr.get('po_id'):
        if ac2.button("🛒 Create PO", type="primary", use_container_width=True):
            keycloak_id = st.session_state.get('keycloak_id', user_id)
            result = create_po_from_pr(pr_id, 1, keycloak_id)  # buyer_company_id=1 (ROZITEK)
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

    if pr.get('po_number'):
        ac3.success(f"PO: **{pr['po_number']}**")

    if can_edit:
        if ac4.button("🗑 Cancel PR", use_container_width=True):
            if cancel_pr(pr_id, user_id):
                st.success("PR cancelled.")
                st.cache_data.clear()
                st.rerun()


# ══════════════════════════════════════════════════════════════════════
# MAIN PAGE
# ══════════════════════════════════════════════════════════════════════

st.title("🛒 Purchase Request")

if proj_df.empty:
    st.warning("No projects found."); st.stop()

# ── Sidebar ──
with st.sidebar:
    st.header("Filters")
    proj_options = ["All Projects"] + [f"{r.project_code} — {r.project_name}" for r in proj_df.itertuples()]
    sel_label = st.selectbox("Project", proj_options, key="pr_project")

    is_all = sel_label == "All Projects"
    project_id = None
    if not is_all:
        sel_idx = proj_options.index(sel_label) - 1
        project_id = int(proj_df.iloc[sel_idx]['project_id'])

    f_status = st.selectbox("Status", ["All", "DRAFT", "PENDING_APPROVAL", "APPROVED",
                                        "REJECTED", "REVISION_REQUESTED", "PO_CREATED", "CANCELLED"])

    # Create button (only when project selected and user is PM)
    if project_id:
        st.divider()
        project = get_project(project_id)
        if project:
            is_pm = is_project_pm(project_id, emp_int_id)
            st.caption(f"**{project['project_code']}**")
            st.caption(f"PM: {project.get('pm_name', '—')}")
            if is_pm or is_admin:
                if st.button("➕ New PR", type="primary", use_container_width=True):
                    st.session_state['open_create_pr'] = True


# ── Tabs ──
tab_my, tab_pending, tab_all = st.tabs([
    "📋 My PRs",
    "⏳ Pending Approval",
    "📊 All PRs",
])


# ══════════════════════════════════════════════════════════════════════
# TAB 1 — My PRs
# ══════════════════════════════════════════════════════════════════════

with tab_my:
    my_df = get_pr_list_df(
        project_id=project_id,
        status=None if f_status == "All" else f_status,
        requester_id=emp_int_id,
    )

    # KPIs
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total PRs", len(my_df))
    k2.metric("Pending", len(my_df[my_df['status'] == 'PENDING_APPROVAL']) if not my_df.empty else 0)
    k3.metric("Approved", len(my_df[my_df['status'] == 'APPROVED']) if not my_df.empty else 0)
    k4.metric("Need Revision", len(my_df[my_df['status'] == 'REVISION_REQUESTED']) if not my_df.empty else 0)

    if my_df.empty:
        st.info("No PRs found. Create one from the sidebar.")
    else:
        display = my_df.copy()
        display.insert(0, '●', display['status'].map(PR_STATUS_ICONS))
        display['total_fmt'] = display['total_amount_vnd'].apply(
            lambda v: f"{v:,.0f}" if v and str(v) not in ('', 'nan', 'None', '0') else '—')

        tbl_key = f"my_pr_{st.session_state.get('_my_pr_key', 0)}"
        event = st.dataframe(
            display, key=tbl_key, width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            column_config={
                '●': st.column_config.TextColumn('', width=30),
                'pr_number': st.column_config.TextColumn('PR#'),
                'project_code': st.column_config.TextColumn('Project', width=140),
                'status': st.column_config.TextColumn('Status'),
                'priority': st.column_config.TextColumn('Priority', width=80),
                'vendor_name': st.column_config.TextColumn('Vendor'),
                'total_fmt': st.column_config.TextColumn('Total VND'),
                'item_count': st.column_config.NumberColumn('Items', width=60),
                'created_date': st.column_config.DatetimeColumn('Created'),
                'pr_id': None, 'project_id': None, 'requester_id': None,
                'requester_name': None, 'requester_email': None, 'vendor_id': None,
                'total_amount': None, 'total_amount_vnd': None, 'currency_code': None,
                'exchange_rate': None, 'current_approval_level': None,
                'max_approval_level': None, 'submitted_date': None,
                'approved_date': None, 'required_date': None,
                'po_id': None, 'po_number': None, 'justification': None,
                'rejection_reason': None, 'project_name': None,
                'pr_type': None, 'cogs_category': None,
            },
        )

        sel = event.selection.rows
        if sel:
            row = my_df.iloc[sel[0]]
            st.markdown(f"**Selected:** {row['pr_number']} — {PR_STATUS_ICONS.get(row['status'], '')} {row['status']}")
            ab1, ab2, ab3 = st.columns([1, 1, 2])
            if ab1.button("👁️ View / Edit", type="primary", use_container_width=True):
                st.session_state['open_pr_detail'] = int(row['pr_id'])
                st.rerun()
            if ab2.button("✖ Deselect", use_container_width=True):
                st.session_state['_my_pr_key'] = st.session_state.get('_my_pr_key', 0) + 1
                st.rerun()


# ══════════════════════════════════════════════════════════════════════
# TAB 2 — Pending Approval (for current user)
# ══════════════════════════════════════════════════════════════════════

with tab_pending:
    pending_df = get_pending_for_approver(emp_int_id)

    if pending_df.empty:
        st.info("No PRs pending your approval.")
    else:
        st.subheader(f"⏳ {len(pending_df)} PR(s) awaiting your approval")

        for _, row in pending_df.iterrows():
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
                c1.markdown(f"**{row['pr_number']}** — {row.get('project_code', '')}")
                c2.markdown(f"Vendor: {row.get('vendor_name', '—')} | "
                            f"By: {row.get('requester_name', '—')}")
                c3.metric("Amount", fmt_vnd(row.get('total_amount_vnd')))
                pri_icon = PRIORITY_ICONS.get(row.get('priority', 'NORMAL'), '')
                c4.markdown(f"{pri_icon} **{row.get('priority', 'NORMAL')}**")

                if row.get('justification'):
                    st.caption(f"📝 {row['justification'][:200]}")

                bc1, bc2 = st.columns([1, 3])
                if bc1.button("Review & Act", type="primary", key=f"review_{row['pr_id']}",
                              use_container_width=True):
                    _dialog_approval_action(int(row['pr_id']))


# ══════════════════════════════════════════════════════════════════════
# TAB 3 — All PRs (dashboard)
# ══════════════════════════════════════════════════════════════════════

with tab_all:
    all_df = get_pr_list_df(
        project_id=project_id,
        status=None if f_status == "All" else f_status,
    )

    if all_df.empty:
        st.info("No PRs found.")
    else:
        # KPIs
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total PRs", len(all_df))
        approved_vnd = all_df.loc[all_df['status'].isin(['APPROVED', 'PO_CREATED']), 'total_amount_vnd'].sum()
        k2.metric("Approved Value", fmt_vnd(approved_vnd))
        k3.metric("Pending", len(all_df[all_df['status'] == 'PENDING_APPROVAL']))
        k4.metric("With PO", len(all_df[all_df['status'] == 'PO_CREATED']))

        display = all_df.copy()
        display.insert(0, '●', display['status'].map(PR_STATUS_ICONS))
        display['total_fmt'] = display['total_amount_vnd'].apply(
            lambda v: f"{v:,.0f}" if v and str(v) not in ('', 'nan', 'None', '0') else '—')

        tbl_key = f"all_pr_{st.session_state.get('_all_pr_key', 0)}"
        event = st.dataframe(
            display, key=tbl_key, width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            column_config={
                '●': st.column_config.TextColumn('', width=30),
                'pr_number': st.column_config.TextColumn('PR#'),
                'project_code': st.column_config.TextColumn('Project', width=140),
                'requester_name': st.column_config.TextColumn('Requester'),
                'status': st.column_config.TextColumn('Status'),
                'priority': st.column_config.TextColumn('Pri', width=60),
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
                'pr_type': None, 'cogs_category': None,
            },
        )

        sel = event.selection.rows
        if sel:
            row = all_df.iloc[sel[0]]
            ab1, ab2, ab3 = st.columns([1, 1, 2])
            if ab1.button("👁️ View", type="primary", use_container_width=True, key="all_view"):
                st.session_state['open_pr_detail'] = int(row['pr_id'])
                st.rerun()
            if ab2.button("✖ Deselect", use_container_width=True, key="all_desel"):
                st.session_state['_all_pr_key'] = st.session_state.get('_all_pr_key', 0) + 1
                st.rerun()


# ══════════════════════════════════════════════════════════════════════
# DIALOG TRIGGERS
# ══════════════════════════════════════════════════════════════════════

if st.session_state.pop('open_create_pr', False) and project_id:
    _dialog_create_pr(project_id)

if 'open_pr_detail' in st.session_state:
    pid = st.session_state.pop('open_pr_detail')
    _dialog_pr_detail(pid)