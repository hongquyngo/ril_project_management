# pages/IL_3_⏱️_Cost_Tracking.py
"""
Cost Tracking — Labor Logs / Expenses / Pre-sales Costs
"""

import streamlit as st
import pandas as pd
from datetime import date
import logging

from utils.auth import AuthManager
from utils.il_project import (
    get_projects_df, get_project,
    get_labor_logs_df, create_labor_log, approve_labor_log, soft_delete_labor_log,
    get_expenses_df, create_expense, approve_expense, soft_delete_expense,
    get_presales_costs_df, create_presales_cost, bulk_update_presales_allocation,
    get_employees, get_currencies,
    fmt_vnd, PHASE_LABELS,
)
from utils.il_project.helpers import (
    EXPENSE_CATEGORIES, PRESALES_CATEGORIES_L1, PRESALES_CATEGORIES_L2,
    EMPLOYEE_LEVELS, DEFAULT_RATES_BY_LEVEL,
)

logger = logging.getLogger(__name__)
auth = AuthManager()

st.set_page_config(page_title="Cost Tracking", page_icon="⏱️", layout="wide")
auth.require_auth()
user_id    = str(auth.get_user_id())
emp_int_id = auth.get_user_id()
is_pm      = st.session_state.get('user_role') in ('admin', 'manager')

# ── Lookups ────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load():
    return get_projects_df(), get_employees(), get_currencies()

proj_df, employees, currencies = _load()
emp_map  = {e['id']: e['full_name'] for e in employees}
cur_map  = {c['id']: c['code'] for c in currencies}

# ── Page header ────────────────────────────────────────────────────────────────
st.title("⏱️ Cost Tracking")

# ── Project selector ───────────────────────────────────────────────────────────
if proj_df.empty:
    st.warning("No projects found.")
    st.stop()

proj_options = [f"{r.project_code} — {r.project_name}" for r in proj_df.itertuples()]
sel_label    = st.selectbox("Select Project", proj_options)
project_id   = int(proj_df.iloc[proj_options.index(sel_label)]['project_id'])
project      = get_project(project_id)
if not project:
    st.error("Project not found.")
    st.stop()

st.caption(f"**{project['project_code']}** | {project.get('customer_name') or project.get('end_customer_name','—')} | Status: {project['status']}")

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_labor, tab_exp, tab_presales = st.tabs(["👷 Labor Logs", "🧾 Expenses", "🔍 Pre-sales Costs"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — LABOR LOGS
# ══════════════════════════════════════════════════════════════════════════════
with tab_labor:
    fc1, fc2 = st.columns(2)
    lf_phase  = fc1.selectbox("Filter Phase", ["All"] + list(PHASE_LABELS.keys()), key="lf_phase")
    lf_status = fc2.selectbox("Filter Approval", ["All", "PENDING", "APPROVED", "REJECTED"], key="lf_status")

    labor_df = get_labor_logs_df(
        project_id,
        phase=None if lf_phase == "All" else lf_phase,
        approval_status=None if lf_status == "All" else lf_status,
    )

    # Summary KPIs
    approved_df = labor_df[labor_df['approval_status'] == 'APPROVED'] if not labor_df.empty else labor_df
    k1, k2, k3 = st.columns(3)
    k1.metric("Total Man-Days (Approved)", f"{approved_df['man_days'].sum():.1f}" if not approved_df.empty else "0")
    k2.metric("Total Labor Cost (Approved)", fmt_vnd(approved_df['amount'].sum() if not approved_df.empty else 0))
    k3.metric("Pending Rows", len(labor_df[labor_df['approval_status'] == 'PENDING']) if not labor_df.empty else 0)

    if not labor_df.empty:
        st.dataframe(
            labor_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                'id':                 st.column_config.NumberColumn('ID', width=60),
                'work_date':          st.column_config.DateColumn('Date'),
                'phase':              st.column_config.TextColumn('Phase'),
                'worker':             st.column_config.TextColumn('Worker'),
                'employee_level':     st.column_config.TextColumn('Level'),
                'man_days':           st.column_config.NumberColumn('Days', format="%.1f"),
                'daily_rate':         st.column_config.NumberColumn('Rate', format="%.0f"),
                'amount':             st.column_config.NumberColumn('Amount', format="%.0f"),
                'is_on_site':         st.column_config.CheckboxColumn('On-site'),
                'presales_allocation':st.column_config.TextColumn('Pre-sales Alloc'),
                'approval_status':    st.column_config.TextColumn('Status'),
                'description':        st.column_config.TextColumn('Description'),
            }
        )

    # PM Bulk Approve
    if is_pm and not labor_df.empty:
        pending_ids = labor_df[labor_df['approval_status'] == 'PENDING']['id'].tolist()
        if pending_ids and st.button(f"✅ Approve All Pending ({len(pending_ids)})", key="bulk_approve_labor"):
            for lid in pending_ids:
                approve_labor_log(lid, emp_int_id)
            st.success(f"Approved {len(pending_ids)} entries.")
            st.rerun()

    # Add new entry
    with st.expander("➕ Log Labor Entry"):
        with st.form("labor_form"):
            is_subcon = st.checkbox("External / Subcontractor", value=False)
            la1, la2 = st.columns(2)

            if not is_subcon:
                emp_opts = [e['full_name'] for e in employees]
                worker   = la1.selectbox("Employee", emp_opts)
                worker_id = employees[emp_opts.index(worker)]['id']
                subcon_name = None
                subcon_co   = None
            else:
                worker_id   = None
                subcon_name = la1.text_input("Subcontractor Name *")
                subcon_co   = la2.text_input("Company")

            lb1, lb2, lb3, lb4 = st.columns(4)
            level_opts  = [""] + EMPLOYEE_LEVELS
            level_sel   = lb1.selectbox("Level", level_opts)
            work_date   = lb2.date_input("Work Date", value=date.today())
            man_days_v  = lb3.number_input("Man-Days", value=1.0, min_value=0.5, max_value=3.0, step=0.5, format="%.1f")
            is_on_site  = lb4.checkbox("On-site", value=True)

            lc1, lc2, lc3 = st.columns(3)
            # Auto-hint rate from level
            hint_rate  = DEFAULT_RATES_BY_LEVEL.get(level_sel, 1_200_000) if level_sel else 1_200_000
            daily_rate_v = lc1.number_input("Day Rate (VND)", value=float(hint_rate), min_value=0.0, format="%.0f")

            phase_opts  = list(PHASE_LABELS.keys())
            phase_sel   = lc2.selectbox("Phase", phase_opts, index=phase_opts.index('IMPLEMENTATION'))

            presales_alloc = None
            if phase_sel == 'PRE_SALES':
                alloc_opts   = ['PENDING', 'SGA', 'COGS']
                presales_alloc = lc3.selectbox("Pre-sales Allocation", alloc_opts)

            description_v = st.text_input("Description")

            if st.form_submit_button("Add Entry", type="primary"):
                if is_subcon and not subcon_name:
                    st.error("Subcontractor name required.")
                else:
                    create_labor_log({
                        'project_id': project_id,
                        'employee_id': worker_id,
                        'employee_level': level_sel or None,
                        'subcontractor_name': subcon_name,
                        'subcontractor_company': subcon_co,
                        'work_date': work_date,
                        'man_days': man_days_v,
                        'daily_rate': daily_rate_v,
                        'phase': phase_sel,
                        'description': description_v or None,
                        'is_on_site': 1 if is_on_site else 0,
                        'presales_allocation': presales_alloc,
                    }, user_id)
                    st.success("Labor entry added.")
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — EXPENSES
# ══════════════════════════════════════════════════════════════════════════════
with tab_exp:
    ef1, ef2 = st.columns(2)
    ef_phase  = ef1.selectbox("Filter Phase", ["All"] + list(PHASE_LABELS.keys()), key="ef_phase")
    ef_status = ef2.selectbox("Filter Approval", ["All","PENDING","APPROVED","REJECTED"], key="ef_status")

    exp_df = get_expenses_df(
        project_id,
        phase=None if ef_phase == "All" else ef_phase,
        approval_status=None if ef_status == "All" else ef_status,
    )

    approved_exp = exp_df[exp_df['approval_status'] == 'APPROVED'] if not exp_df.empty else exp_df
    ek1, ek2, ek3 = st.columns(3)
    ek1.metric("Total Expenses (Approved)", fmt_vnd(approved_exp['amount_vnd'].sum() if not approved_exp.empty else 0))
    ek2.metric("Transactions", len(approved_exp))
    ek3.metric("Pending", len(exp_df[exp_df['approval_status'] == 'PENDING']) if not exp_df.empty else 0)

    if not exp_df.empty:
        st.dataframe(
            exp_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                'expense_date':    st.column_config.DateColumn('Date'),
                'category':        st.column_config.TextColumn('Category'),
                'phase':           st.column_config.TextColumn('Phase'),
                'employee_name':   st.column_config.TextColumn('Employee'),
                'amount':          st.column_config.NumberColumn('Amount', format="%.0f"),
                'currency':        st.column_config.TextColumn('CCY', width=50),
                'amount_vnd':      st.column_config.NumberColumn('VND', format="%.0f"),
                'vendor_name':     st.column_config.TextColumn('Vendor'),
                'receipt_number':  st.column_config.TextColumn('Receipt#'),
                'approval_status': st.column_config.TextColumn('Status'),
                'description':     st.column_config.TextColumn('Description'),
            }
        )

    if is_pm and not exp_df.empty:
        pending_exp = exp_df[exp_df['approval_status'] == 'PENDING']['id'].tolist()
        if pending_exp and st.button(f"✅ Approve All Pending ({len(pending_exp)})", key="bulk_approve_exp"):
            for eid in pending_exp:
                approve_expense(eid, emp_int_id)
            st.success(f"Approved {len(pending_exp)} expenses.")
            st.rerun()

    with st.expander("➕ Add Expense"):
        with st.form("expense_form"):
            ea1, ea2, ea3 = st.columns(3)
            exp_date   = ea1.date_input("Date", value=date.today())
            cat_opts   = EXPENSE_CATEGORIES
            exp_cat    = ea2.selectbox("Category", cat_opts)
            exp_phase  = ea3.selectbox("Phase", list(PHASE_LABELS.keys()),
                                        index=list(PHASE_LABELS.keys()).index('IMPLEMENTATION'))

            eb1, eb2, eb3, eb4 = st.columns(4)
            exp_emp_opts = [e['full_name'] for e in employees]
            exp_emp      = eb1.selectbox("Employee", exp_emp_opts)
            exp_emp_id   = employees[exp_emp_opts.index(exp_emp)]['id']
            exp_amount   = eb2.number_input("Amount", value=0.0, min_value=0.0, format="%.0f")
            cur_opts     = [c['code'] for c in currencies]
            exp_cur      = eb3.selectbox("Currency", cur_opts)
            exp_cur_id   = currencies[cur_opts.index(exp_cur)]['id']
            is_vnd       = (exp_cur == 'VND')
            exp_rate     = eb4.number_input("Exchange Rate", value=1.0 if is_vnd else 25_000.0, format="%.2f")

            ec1, ec2 = st.columns(2)
            exp_vendor  = ec1.text_input("Vendor Name")
            exp_receipt = ec2.text_input("Receipt Number")
            exp_desc    = st.text_input("Description")

            if st.form_submit_button("Add Expense", type="primary"):
                if exp_amount <= 0:
                    st.error("Amount must be > 0.")
                else:
                    create_expense({
                        'project_id': project_id,
                        'employee_id': exp_emp_id,
                        'expense_date': exp_date,
                        'category': exp_cat,
                        'phase': exp_phase,
                        'amount': exp_amount,
                        'currency_id': exp_cur_id,
                        'exchange_rate': exp_rate,
                        'description': exp_desc or None,
                        'vendor_name': exp_vendor or None,
                        'receipt_number': exp_receipt or None,
                    }, user_id)
                    st.success("Expense added.")
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — PRE-SALES COSTS
# ══════════════════════════════════════════════════════════════════════════════
with tab_presales:
    ps_df = get_presales_costs_df(project_id)

    # Layer summary
    if not ps_df.empty:
        l1_total = ps_df[ps_df['cost_layer'] == 'STANDARD']['amount_vnd'].sum()
        l2_total = ps_df[ps_df['cost_layer'] == 'SPECIAL']['amount_vnd'].sum()
        l2_cogs  = ps_df[(ps_df['cost_layer'] == 'SPECIAL') & (ps_df['allocation'] == 'COGS')]['amount_vnd'].sum()
        pk1, pk2, pk3 = st.columns(3)
        pk1.metric("Layer 1 — SG&A", fmt_vnd(l1_total))
        pk2.metric("Layer 2 — Total", fmt_vnd(l2_total))
        pk3.metric("Layer 2 → COGS", fmt_vnd(l2_cogs))

        # Color allocation
        def _alloc_color(a):
            return {'SGA': '🔵', 'COGS': '🟢', 'PENDING': '⚪'}.get(a, '⚪')
        ps_df.insert(0, '●', ps_df['allocation'].map(_alloc_color))

        st.dataframe(
            ps_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                '●':             st.column_config.TextColumn('', width=30),
                'cost_layer':    st.column_config.TextColumn('Layer'),
                'category':      st.column_config.TextColumn('Category'),
                'worker':        st.column_config.TextColumn('Worker'),
                'amount':        st.column_config.NumberColumn('Amount', format="%.0f"),
                'currency':      st.column_config.TextColumn('CCY', width=50),
                'amount_vnd':    st.column_config.NumberColumn('VND', format="%.0f"),
                'man_days':      st.column_config.NumberColumn('Man-Days', format="%.1f"),
                'allocation':    st.column_config.TextColumn('Allocation'),
                'description':   st.column_config.TextColumn('Description'),
            }
        )

    # Win / Lose decision → bulk allocation
    if is_pm:
        st.divider()
        st.markdown("**Win/Lose Decision — Layer 2 allocation**")
        dc1, dc2, dc3 = st.columns(3)
        if dc1.button("🏆 WIN — Move Layer 2 → COGS", type="primary"):
            n = bulk_update_presales_allocation(project_id, 'COGS', user_id)
            st.success(f"Updated {n} Layer-2 costs → COGS.")
            st.rerun()
        if dc2.button("❌ LOSE — Move Layer 2 → SGA"):
            n = bulk_update_presales_allocation(project_id, 'SGA', user_id)
            st.info(f"Updated {n} Layer-2 costs → SGA.")
            st.rerun()

    with st.expander("➕ Add Pre-sales Cost"):
        with st.form("presales_form"):
            pa1, pa2 = st.columns(2)
            ps_layer    = pa1.radio("Layer", ["STANDARD (Layer 1 → SGA)", "SPECIAL (Layer 2 → COGS if win)"], horizontal=True)
            ps_layer_v  = "STANDARD" if "STANDARD" in ps_layer else "SPECIAL"

            cat_list    = PRESALES_CATEGORIES_L1 if ps_layer_v == "STANDARD" else PRESALES_CATEGORIES_L2
            ps_cat      = pa2.selectbox("Category", cat_list)

            pb1, pb2 = st.columns(2)
            is_ps_subcon = pb1.checkbox("External worker", value=False)
            if not is_ps_subcon:
                ps_emp_opts = [e['full_name'] for e in employees]
                ps_emp      = pb2.selectbox("Employee", ps_emp_opts)
                ps_emp_id   = employees[ps_emp_opts.index(ps_emp)]['id']
                ps_subcon   = None
            else:
                ps_emp_id   = None
                ps_subcon   = pb2.text_input("Subcontractor Name *")

            pc1, pc2, pc3, pc4 = st.columns(4)
            ps_amount   = pc1.number_input("Amount", value=0.0, min_value=0.0, format="%.0f")
            ps_cur_opts = [c['code'] for c in currencies]
            ps_cur      = pc2.selectbox("Currency", ps_cur_opts)
            ps_cur_id   = currencies[ps_cur_opts.index(ps_cur)]['id']
            is_vnd_ps   = (ps_cur == 'VND')
            ps_rate     = pc3.number_input("Exchange Rate", value=1.0 if is_vnd_ps else 25_000.0, format="%.2f")
            ps_days     = pc4.number_input("Man-Days (optional)", value=0.0, min_value=0.0, format="%.1f")

            alloc_opts  = ['PENDING','SGA','COGS']
            default_alloc = 'SGA' if ps_layer_v == 'STANDARD' else 'PENDING'
            ps_alloc    = st.selectbox("Allocation", alloc_opts,
                                        index=alloc_opts.index(default_alloc))
            ps_desc     = st.text_input("Description")

            if st.form_submit_button("Add Pre-sales Cost", type="primary"):
                if ps_amount <= 0:
                    st.error("Amount must be > 0.")
                elif is_ps_subcon and not ps_subcon:
                    st.error("Subcontractor name required.")
                else:
                    create_presales_cost({
                        'project_id': project_id,
                        'employee_id': ps_emp_id,
                        'subcontractor_name': ps_subcon,
                        'cost_layer': ps_layer_v,
                        'category': ps_cat,
                        'amount': ps_amount,
                        'currency_id': ps_cur_id,
                        'exchange_rate': ps_rate,
                        'allocation': ps_alloc,
                        'man_days': ps_days if ps_days > 0 else None,
                        'description': ps_desc or None,
                    }, user_id)
                    st.success("Pre-sales cost added.")
                    st.rerun()
