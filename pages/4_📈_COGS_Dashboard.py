# pages/IL_4_📈_COGS_Dashboard.py
"""
COGS Dashboard — Actual COGS sync + Variance Analysis + Benchmarks

Redesigned:
  - Sidebar: Project selector (All default), status filter
  - "All Projects" → Portfolio health dashboard
  - Specific project → 3 tabs (Actual COGS / Variance / Benchmarks)
  - No @st.fragment — plain functions
  - Auto-fill Variance from estimate/actual data
  - Generate All Variance in 1 click
  - Budget consumption progress bar
  - Auto-populate Benchmark from project data
"""

import streamlit as st
import pandas as pd
import logging

from utils.auth import AuthManager
from utils.il_project import (
    get_projects_df, get_project,
    get_active_estimate,
    get_cogs_actual, get_all_cogs_summary_df,
    sync_cogs_actual, update_cogs_actual_fields, finalize_cogs_actual,
    get_variance_df, upsert_variance_row,
    get_benchmarks_df, create_benchmark,
    get_project_types,
    fmt_vnd, fmt_percent, pct_change, COGS_LABELS,
)
from utils.il_project.helpers import impact_color, go_no_go_badge

logger = logging.getLogger(__name__)
auth = AuthManager()

st.set_page_config(page_title="COGS Dashboard", page_icon="📈", layout="wide")
auth.require_auth()
user_id = str(auth.get_user_id())
is_pm   = st.session_state.get('user_role') in ('admin', 'manager')


# ── Lookups ───────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load():
    return get_projects_df(), get_project_types()

proj_df, proj_types = _load()
type_map = {t['id']: t for t in proj_types}


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

st.title("📈 COGS Dashboard")

if proj_df.empty:
    st.warning("No projects found.")
    st.stop()

with st.sidebar:
    st.header("Filters")
    proj_options = ["All Projects"] + [f"{r.project_code} — {r.project_name}" for r in proj_df.itertuples()]
    sel_label = st.selectbox("Project", proj_options, key="cogs_project")
    is_all_projects = sel_label == "All Projects"

    if not is_all_projects:
        sel_idx    = proj_options.index(sel_label) - 1
        project_id = int(proj_df.iloc[sel_idx]['project_id'])
        project    = get_project(project_id)
    else:
        project_id = None
        project    = None

    if is_all_projects:
        f_status = st.selectbox("Status", ["All", "IN_PROGRESS", "COMPLETED", "WARRANTY", "CLOSED"], key="cogs_status")
    else:
        st.divider()
        if project:
            st.caption(f"**{project['project_code']}**")
            st.caption(f"{project.get('customer_name', '—')}")
            st.caption(f"Status: **{project['status']}**")


# ══════════════════════════════════════════════════════════════════════════════
# DIALOGS
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("✏️ Manual Entry — A / B / C / F", width="large")
def _dialog_cogs_manual(pid: int, actual: dict):
    st.caption("Enter from source documents: PI, B/L, subcontractor invoice. After saving, click 🔄 Sync to recalculate.")
    with st.form("cogs_manual_form"):
        ma1, ma2 = st.columns(2)
        a_act = ma1.number_input("A: Equipment (from PI)",
                                  value=float(actual.get('a_equipment_cost') or 0), format="%.0f")
        a_n   = ma2.text_input("Notes A", value=actual.get('a_notes') or '')

        mb1, mb2 = st.columns(2)
        b_act = mb1.number_input("B: Logistics & Import (from BoL/Tax Invoice)",
                                  value=float(actual.get('b_logistics_import') or 0), format="%.0f")
        b_n   = mb2.text_input("Notes B", value=actual.get('b_notes') or '')

        mc1, mc2 = st.columns(2)
        c_act = mc1.number_input("C: Custom Fabrication (from subcon PO)",
                                  value=float(actual.get('c_custom_fabrication') or 0), format="%.0f")
        c_n   = mc2.text_input("Notes C", value=actual.get('c_notes') or '')

        st.markdown("**F — Warranty Reserve**")
        mf1, mf2, mf3 = st.columns(3)
        f_prov = mf1.number_input("F: Provision (accrued)",
                                   value=float(actual.get('f_warranty_provision') or 0), format="%.0f")
        f_used = mf2.number_input("F: Actual Used",
                                   value=float(actual.get('f_warranty_actual_used') or 0), format="%.0f")
        f_rel  = mf3.number_input("F: Released (unused)",
                                   value=float(actual.get('f_warranty_released') or 0), format="%.0f")
        f_n    = st.text_input("Notes F", value=actual.get('f_notes') or '')

        submitted = st.form_submit_button("💾 Save", type="primary", use_container_width=True)

    if submitted:
        ok = update_cogs_actual_fields(pid, {
            'a_equipment_cost': a_act, 'a_notes': a_n or None,
            'b_logistics_import': b_act, 'b_notes': b_n or None,
            'c_custom_fabrication': c_act, 'c_notes': c_n or None,
            'f_warranty_provision': f_prov,
            'f_warranty_actual_used': f_used,
            'f_warranty_released': f_rel, 'f_notes': f_n or None,
        }, user_id)
        if ok:
            st.success("✅ Saved. Click 🔄 Sync to update COGS totals.")
            st.rerun()
        else:
            st.warning("Record not found — run Sync first to initialize.")


@st.dialog("📉 Record Variance Analysis", width="large")
def _dialog_variance(pid: int, category: str = '', est_val: float = 0.0, act_val: float = 0.0):
    """Variance dialog with auto-filled estimated/actual values."""
    with st.form("variance_form"):
        cat_opts = ['A', 'B', 'C', 'D', 'E', 'F', 'PRESALES', 'TOTAL']
        va1, va2, va3 = st.columns(3)
        cat_idx  = cat_opts.index(category) if category in cat_opts else 0
        var_cat  = va1.selectbox("COGS Category", cat_opts, index=cat_idx)
        var_est  = va2.number_input("Estimated Amount", value=est_val, format="%.0f")
        var_act  = va3.number_input("Actual Amount",    value=act_val, format="%.0f")

        # Auto-compute variance info
        auto_pct = pct_change(var_est, var_act)
        if auto_pct is not None:
            var_amt = var_act - var_est
            st.caption(
                f"Variance: **{var_amt:+,.0f}** ({auto_pct:+.1f}%) — "
                f"{'🟢 Favorable' if auto_pct < -5 else '🔴 Unfavorable' if auto_pct > 5 else '🟡 Neutral'}"
            )

        var_impact_sel = st.selectbox("Impact", ['(auto from sign)', 'FAVORABLE', 'NEUTRAL', 'UNFAVORABLE'])
        if var_impact_sel == '(auto from sign)':
            var_impact = 'FAVORABLE' if (auto_pct or 0) < -5 else 'UNFAVORABLE' if (auto_pct or 0) > 5 else 'NEUTRAL'
        else:
            var_impact = var_impact_sel

        var_rc = st.text_area("Root Cause",        height=70)
        var_ca = st.text_area("Corrective Action", height=70)

        has_coeff = var_cat in ('B', 'E', 'F')
        c_used = c_act_v = c_rec = None
        if has_coeff:
            vc1, vc2, vc3 = st.columns(3)
            c_used  = vc1.number_input("Coefficient Used",        value=0.0, format="%.4f")
            c_act_v = vc2.number_input("Coefficient Actual",      value=0.0, format="%.4f")
            c_rec   = vc3.number_input("Coefficient Recommended", value=0.0, format="%.4f")

        submitted = st.form_submit_button("💾 Save", type="primary", use_container_width=True)

    if submitted:
        ok = upsert_variance_row(
            pid, var_cat, var_est, var_act,
            var_rc, var_ca, var_impact,
            c_used if has_coeff and c_used else None,
            c_act_v if has_coeff and c_act_v else None,
            c_rec if has_coeff and c_rec else None,
            user_id,
        )
        if ok:
            st.success("✅ Saved!")
            st.rerun()
        else:
            st.error("Save failed.")


@st.dialog("📚 Add Benchmark Record", width="large")
def _dialog_benchmark(pid: int, auto_data: dict = None):
    """Benchmark dialog with auto-populated data from project."""
    ad = auto_data or {}
    with st.form("benchmark_form"):
        type_opts  = [f"[{t['code']}] {t['name']}" for t in proj_types]
        bt1, bt2, bt3 = st.columns(3)
        # Auto-select current project type
        auto_type_idx = 0
        if ad.get('type_code'):
            for i, opt in enumerate(type_opts):
                if opt.startswith(f"[{ad['type_code']}]"):
                    auto_type_idx = i
                    break
        bm_type    = bt1.selectbox("Project Type", type_opts, index=auto_type_idx)
        _bm_code   = bm_type.split("]")[0][1:]
        bm_type_id = next((t for t in proj_types if t['code'] == _bm_code), proj_types[0])['id']
        bm_date    = bt2.date_input("Benchmark Date")

        src_opts   = ["(None)"] + [f"{r.project_code}" for r in proj_df.itertuples()]
        auto_src_idx = 0
        if ad.get('project_code') and ad['project_code'] in src_opts:
            auto_src_idx = src_opts.index(ad['project_code'])
        bm_src     = bt3.selectbox("Source Project", src_opts, index=auto_src_idx)
        bm_src_id  = None
        if bm_src != "(None)":
            src_row   = proj_df[proj_df['project_code'] == bm_src]
            bm_src_id = int(src_row.iloc[0]['project_id']) if not src_row.empty else None

        st.markdown("**Coefficients — α (Logistics ratio)**")
        bc1, bc2, bc3 = st.columns(3)
        alpha_u = bc1.number_input("α Used",   value=ad.get('alpha_used', 0.06), format="%.4f")
        alpha_a = bc2.number_input("α Actual", value=ad.get('alpha_actual', 0.06), format="%.4f")
        alpha_r = bc3.number_input("α Rec.",   value=ad.get('alpha_actual', 0.06), format="%.4f")

        st.markdown("**β (Travel & Site OH ratio)**")
        bd1, bd2, bd3 = st.columns(3)
        beta_u  = bd1.number_input("β Used",   value=ad.get('beta_used', 0.40), format="%.4f")
        beta_a  = bd2.number_input("β Actual", value=ad.get('beta_actual', 0.40), format="%.4f")
        beta_r  = bd3.number_input("β Rec.",   value=ad.get('beta_actual', 0.40), format="%.4f")

        st.markdown("**γ (Warranty Reserve ratio)**")
        be1, be2, be3 = st.columns(3)
        gamma_u = be1.number_input("γ Used",   value=ad.get('gamma_used', 0.04), format="%.4f")
        gamma_a = be2.number_input("γ Actual", value=ad.get('gamma_actual', 0.04), format="%.4f")
        gamma_r = be3.number_input("γ Rec.",   value=ad.get('gamma_actual', 0.04), format="%.4f")

        bf1, bf2, bf3, bf4 = st.columns(4)
        days_est = bf1.number_input("Man-Days Estimated", value=int(ad.get('days_est', 0)), min_value=0)
        days_act = bf2.number_input("Man-Days Actual",    value=int(ad.get('days_act', 0)), min_value=0)
        gp_est   = bf3.number_input("GP Est%", value=float(ad.get('gp_est_pct', 0)), format="%.1f")
        gp_act   = bf4.number_input("GP Act%", value=float(ad.get('gp_act_pct', 0)), format="%.1f")

        lessons = st.text_area("Lessons Learned",  height=80)
        risks   = st.text_area("Key Risk Factors", height=60)
        recs    = st.text_area("Recommendations",  height=60)

        submitted = st.form_submit_button("💾 Save Benchmark", type="primary", use_container_width=True)

    if submitted:
        try:
            create_benchmark({
                'project_type_id': bm_type_id, 'source_project_id': bm_src_id,
                'benchmark_date': bm_date,
                'alpha_used': alpha_u, 'alpha_actual': alpha_a, 'alpha_recommended': alpha_r,
                'beta_used': beta_u, 'beta_actual': beta_a, 'beta_recommended': beta_r,
                'gamma_used': gamma_u, 'gamma_actual': gamma_a, 'gamma_recommended': gamma_r,
                'man_days_estimated': days_est or None, 'man_days_actual': days_act or None,
                'man_days_by_phase': None,
                'gp_estimated_percent': gp_est or None, 'gp_actual_percent': gp_act or None,
                'lessons_learned': lessons or None,
                'key_risk_factors': risks or None, 'recommendations': recs or None,
            }, user_id)
            st.success("✅ Benchmark saved!")
            st.rerun()
        except Exception as e:
            st.error(f"Save failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS — Estimate/Actual value getters
# ══════════════════════════════════════════════════════════════════════════════

def _get_est_val(est: dict, key: str) -> float:
    if not est:
        return 0.0
    field_map = {
        'A': 'a_equipment_cost', 'B': 'b_logistics_import',
        'C': 'c_custom_fabrication', 'D': 'd_direct_labor',
        'E': 'e_travel_site_oh', 'F': 'f_warranty_reserve',
    }
    return float(est.get(field_map.get(key, ''), 0) or 0)


def _get_act_val(actual: dict, key: str) -> float:
    if not actual:
        return 0.0
    field_map = {
        'A': 'a_equipment_cost', 'B': 'b_logistics_import',
        'C': 'c_custom_fabrication',
        'D': ('d_direct_labor', 'd_presales_labor'),
        'E': ('e_travel_site_oh', 'e_presales_travel'),
        'F': 'f_warranty_provision',
    }
    fld = field_map.get(key)
    if isinstance(fld, tuple):
        return sum(float(actual.get(f, 0) or 0) for f in fld)
    return float(actual.get(fld, 0) or 0)


def _build_cogs_rows(est, actual):
    """Build A–F + TOTAL comparison rows. Returns list of dicts with raw values."""
    rows = []
    for k in ['A', 'B', 'C', 'D', 'E', 'F']:
        est_v = _get_est_val(est, k)
        act_v = _get_act_val(actual, k)
        rows.append({
            'key': k, 'label': COGS_LABELS[k],
            'estimated': est_v, 'actual': act_v,
            'variance': act_v - est_v,
            'var_pct': pct_change(est_v, act_v),
        })
    est_total = float(est['total_cogs'] if est else 0)
    act_total = float(actual['total_cogs'] if actual else 0)
    rows.append({
        'key': 'TOTAL', 'label': 'TOTAL COGS',
        'estimated': est_total, 'actual': act_total,
        'variance': act_total - est_total,
        'var_pct': pct_change(est_total, act_total),
    })
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO OVERVIEW — All Projects
# ══════════════════════════════════════════════════════════════════════════════

def _render_portfolio():
    summary_df = get_all_cogs_summary_df()

    # Apply status filter
    if f_status != "All" and not summary_df.empty:
        summary_df = summary_df[summary_df['status'] == f_status]

    if summary_df.empty:
        st.info("No projects found for selected filter.")
        return

    has_est = summary_df['est_cogs'].notna()
    has_act = summary_df['act_cogs'].notna()

    # ── KPIs ─────────────────────────────────────────────────────────────────
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Avg Est. GP%",
              f"{summary_df.loc[has_est, 'est_gp_pct'].mean():.1f}%" if has_est.any() else "—")
    k2.metric("Avg Act. GP%",
              f"{summary_df.loc[has_act, 'act_gp_pct'].mean():.1f}%" if has_act.any() else "—")
    k3.metric("Projects Synced", int(has_act.sum()))
    k4.metric("Not Synced", int((~has_act).sum()))

    st.divider()

    # ── Portfolio table ──────────────────────────────────────────────────────
    st.subheader("📊 Portfolio COGS Health")

    display_rows = []
    for _, r in summary_df.iterrows():
        est_c = float(r['est_cogs'] or 0)
        act_c = float(r['act_cogs'] or 0)
        var_pct = pct_change(est_c, act_c) if est_c > 0 and act_c > 0 else None

        # Health indicator
        if var_pct is None:
            health = '⚪'
        elif var_pct > 10:
            health = '🔴'
        elif var_pct > 5:
            health = '🟡'
        else:
            health = '🟢'

        # Budget consumption
        budget_pct = (act_c / est_c * 100) if est_c > 0 else 0

        display_rows.append({
            '●':          health,
            'Project':    r['project_code'],
            'Name':       r['project_name'],
            'Type':       r.get('type_code', '—'),
            'Status':     r['status'],
            'Est COGS':   f"{est_c:,.0f}" if est_c > 0 else '—',
            'Act COGS':   f"{act_c:,.0f}" if act_c > 0 else '—',
            'Variance':   f"{var_pct:+.1f}%" if var_pct is not None else '—',
            'Budget %':   f"{budget_pct:.0f}%" if est_c > 0 else '—',
            'Est GP%':    f"{r['est_gp_pct']:.1f}%" if r['est_gp_pct'] is not None and str(r['est_gp_pct']) != 'nan' else '—',
            'Act GP%':    f"{r['act_gp_pct']:.1f}%" if r['act_gp_pct'] is not None and str(r['act_gp_pct']) != 'nan' else '—',
            'Finalized':  '✅' if r.get('is_finalized') else '',
        })

    if display_rows:
        st.dataframe(
            pd.DataFrame(display_rows), width="stretch", hide_index=True,
            column_config={
                '●':         st.column_config.TextColumn('', width=30),
                'Project':   st.column_config.TextColumn('Project', width=150),
                'Name':      st.column_config.TextColumn('Name'),
                'Type':      st.column_config.TextColumn('Type', width=70),
                'Status':    st.column_config.TextColumn('Status', width=120),
                'Est COGS':  st.column_config.TextColumn('Est COGS'),
                'Act COGS':  st.column_config.TextColumn('Act COGS'),
                'Variance':  st.column_config.TextColumn('Var %', width=80),
                'Budget %':  st.column_config.TextColumn('Budget', width=80),
                'Est GP%':   st.column_config.TextColumn('Est GP%', width=80),
                'Act GP%':   st.column_config.TextColumn('Act GP%', width=80),
                'Finalized': st.column_config.TextColumn('Final', width=50),
            },
        )

    # ── Legend ────────────────────────────────────────────────────────────────
    st.caption("🟢 Variance ≤5% &nbsp;|&nbsp; 🟡 5–10% &nbsp;|&nbsp; 🔴 >10% &nbsp;|&nbsp; ⚪ No data")


# ══════════════════════════════════════════════════════════════════════════════
# ACTUAL COGS TAB — Per project
# ══════════════════════════════════════════════════════════════════════════════

def _render_actual_cogs_tab(pid: int, actual: dict, est: dict):

    # ── Toolbar ──────────────────────────────────────────────────────────────
    ac1, ac2, ac3, ac4 = st.columns([2, 2, 2, 1])
    if ac2.button("🔄 Sync from Timesheets & Expenses", type="primary", use_container_width=True):
        with st.spinner("Syncing..."):
            try:
                sync_cogs_actual(pid, user_id)
                st.success("Sync complete!")
                st.rerun()
            except Exception as e:
                st.error(f"Sync failed: {e}")

    if is_pm:
        if ac3.button("✏️ Manual Entry (A/B/C/F)", use_container_width=True):
            _dialog_cogs_manual(pid, actual or {})
        if actual and not actual.get('is_finalized'):
            if ac4.button("🔒 Finalize"):
                if finalize_cogs_actual(pid, user_id):
                    st.success("COGS finalized.")
                    st.rerun()

    if actual and actual.get('is_finalized'):
        st.info(f"✅ Finalized on {actual.get('finalized_date', '—')} by {actual.get('finalized_by', '—')}")
    if actual and actual.get('last_sync_date'):
        st.caption(f"Last sync: {actual['last_sync_date']}")

    # ── Budget consumption progress bar ──────────────────────────────────────
    if est and actual:
        est_total = float(est.get('total_cogs', 0) or 0)
        act_total = float(actual.get('total_cogs', 0) or 0)
        if est_total > 0:
            budget_pct = act_total / est_total
            st.divider()
            bc1, bc2 = st.columns([3, 1])
            bc1.progress(min(budget_pct, 1.0),
                         text=f"Budget consumed: {budget_pct * 100:.1f}% ({fmt_vnd(act_total)} / {fmt_vnd(est_total)})")
            if budget_pct > 1.0:
                bc2.error(f"⚠️ OVER by {(budget_pct - 1) * 100:.1f}%")
            elif budget_pct > 0.9:
                bc2.warning(f"⚠️ {(1 - budget_pct) * 100:.1f}% remaining")
            else:
                bc2.success(f"✅ {(1 - budget_pct) * 100:.1f}% remaining")

    # ── Estimated vs Actual table ────────────────────────────────────────────
    st.divider()

    rows = _build_cogs_rows(est, actual)

    cogs_display_rows = []
    for r in rows:
        var_p = r['var_pct']
        cogs_display_rows.append({
            '':          impact_color(var_p),
            'Item':      r['label'],
            'Estimated': f"{r['estimated']:,.0f}",
            'Actual':    f"{r['actual']:,.0f}",
            'Variance':  f"{r['variance']:+,.0f}",
            'Var %':     f"{var_p:+.1f}%" if var_p is not None else '—',
        })

    st.dataframe(
        pd.DataFrame(cogs_display_rows), width="stretch", hide_index=True,
        column_config={
            '':          st.column_config.TextColumn('', width=30),
            'Item':      st.column_config.TextColumn('Item'),
            'Estimated': st.column_config.TextColumn('Estimated (VND)'),
            'Actual':    st.column_config.TextColumn('Actual (VND)'),
            'Variance':  st.column_config.TextColumn('Variance (VND)'),
            'Var %':     st.column_config.TextColumn('Var %', width=80),
        },
    )

    # ── GP comparison ────────────────────────────────────────────────────────
    st.divider()
    gp1, gp2, gp3, gp4 = st.columns(4)
    sales_est = float(est['sales_value'] if est else 0)
    sales_act = float(actual['sales_value'] if actual else 0)
    gp1.metric("Est. Sales", fmt_vnd(sales_est))
    gp2.metric("Act. Sales", fmt_vnd(sales_act))
    gp3.metric("Est. GP%",   fmt_percent(est['estimated_gp_percent'] if est else None))
    act_gp_pct = float(actual['actual_gp_percent'] if actual else 0)
    delta_gp   = act_gp_pct - float(est['estimated_gp_percent'] if est else 0)
    gp4.metric("Act. GP%",   fmt_percent(act_gp_pct), delta=f"{delta_gp:+.1f}pp")


# ══════════════════════════════════════════════════════════════════════════════
# VARIANCE TAB — Per project
# ══════════════════════════════════════════════════════════════════════════════

def _render_variance_tab(pid: int, actual: dict, est: dict):
    cogs_rows = _build_cogs_rows(est, actual)

    # ── Toolbar ──────────────────────────────────────────────────────────────
    vh1, vh2, vh3 = st.columns([3, 2, 1])
    if vh2.button("⚡ Generate All Variance", type="primary", use_container_width=True, key="btn_gen_all_var"):
        if not est or not actual:
            st.warning("Need both an active Estimate and COGS Actual to generate variance.")
        else:
            count = 0
            for r in cogs_rows:
                auto_pct = r['var_pct']
                impact = 'FAVORABLE' if (auto_pct or 0) < -5 else 'UNFAVORABLE' if (auto_pct or 0) > 5 else 'NEUTRAL'
                ok = upsert_variance_row(
                    pid, r['key'], r['estimated'], r['actual'],
                    '', '', impact, None, None, None, user_id,
                )
                if ok:
                    count += 1
            st.success(f"✅ Generated {count} variance rows (A–F + TOTAL). Add Root Cause for items with >5% variance.")
            st.rerun()

    if vh3.button("➕ Add", use_container_width=True, key="btn_add_variance"):
        _dialog_variance(pid)

    # ── Variance table ───────────────────────────────────────────────────────
    var_df = get_variance_df(pid)

    if not var_df.empty:
        display_df = var_df.copy()
        display_df.insert(0, '●', display_df['variance_percent'].map(impact_color))
        display_df['estimated_amount_fmt'] = display_df['estimated_amount'].apply(
            lambda v: f"{v:,.0f}" if v is not None and str(v) not in ('', 'nan', 'None') else '—')
        display_df['actual_amount_fmt'] = display_df['actual_amount'].apply(
            lambda v: f"{v:,.0f}" if v is not None and str(v) not in ('', 'nan', 'None') else '—')
        display_df['variance_amount_fmt'] = display_df['variance_amount'].apply(
            lambda v: f"{v:+,.0f}" if v is not None and str(v) not in ('', 'nan', 'None') else '—')
        display_df['variance_percent_fmt'] = display_df['variance_percent'].apply(
            lambda v: f"{v:+.1f}%" if v is not None and str(v) not in ('', 'nan', 'None') else '—')

        tbl_key = f"var_tbl_{st.session_state.get('_var_key', 0)}"
        event = st.dataframe(
            display_df, key=tbl_key, width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            column_config={
                '●':                       st.column_config.TextColumn('', width=30),
                'cogs_category':           st.column_config.TextColumn('Category'),
                'estimated_amount_fmt':    st.column_config.TextColumn('Estimated'),
                'actual_amount_fmt':       st.column_config.TextColumn('Actual'),
                'variance_amount_fmt':     st.column_config.TextColumn('Variance'),
                'variance_percent_fmt':    st.column_config.TextColumn('Var %', width=80),
                'impact_assessment':       st.column_config.TextColumn('Impact'),
                'root_cause':              st.column_config.TextColumn('Root Cause'),
                'corrective_action':       st.column_config.TextColumn('Corrective Action'),
                'coefficient_used':        st.column_config.NumberColumn('Coeff Used', format="%.4f"),
                'coefficient_actual':      st.column_config.NumberColumn('Coeff Act.', format="%.4f"),
                'coefficient_recommended': st.column_config.NumberColumn('Coeff Rec.', format="%.4f"),
                'estimated_amount': None, 'actual_amount': None,
                'variance_amount': None, 'variance_percent': None,
            },
        )

        # Action bar for selected row
        sel = event.selection.rows
        if sel:
            row = var_df.iloc[sel[0]]
            cat = row['cogs_category']
            st.markdown(f"**Selected:** {cat} — {impact_color(row.get('variance_percent'))} {row.get('impact_assessment', '—')}")
            ab1, ab2, ab3 = st.columns([1, 1, 2])
            if ab1.button("✏️ Edit Variance", key="var_edit_btn", use_container_width=True):
                _dialog_variance(pid, category=cat,
                                 est_val=float(row.get('estimated_amount', 0) or 0),
                                 act_val=float(row.get('actual_amount', 0) or 0))
            if ab2.button("✖ Deselect", key="var_desel_btn", use_container_width=True):
                st.session_state["_var_key"] = st.session_state.get("_var_key", 0) + 1
                st.rerun()

        # Highlight rows needing root cause
        needs_rc = var_df[
            (var_df['variance_percent'].abs() > 5) &
            (var_df['root_cause'].isna() | (var_df['root_cause'] == ''))
        ]
        if not needs_rc.empty:
            cats = ', '.join(needs_rc['cogs_category'].tolist())
            st.warning(f"⚠️ Categories with >5% variance missing Root Cause: **{cats}**")

    else:
        st.info("No variance records yet. Use **⚡ Generate All** to auto-create from Estimate vs Actual.")


# ══════════════════════════════════════════════════════════════════════════════
# BENCHMARKS TAB — Per project (or global)
# ══════════════════════════════════════════════════════════════════════════════

def _render_benchmark_tab(pid: int, project_data: dict = None, actual_data: dict = None):
    bh1, bh2, bh3 = st.columns([3, 2, 1])

    bf_type     = bh1.selectbox("Filter by Type", ["All"] + [f"[{t['code']}] {t['name']}" for t in proj_types])
    type_filter = None
    if bf_type != "All":
        code = bf_type.split("]")[0][1:]
        hit  = next((t for t in proj_types if t['code'] == code), None)
        type_filter = hit['id'] if hit else None

    if bh3.button("➕ Add", type="primary", use_container_width=True, key="btn_add_benchmark"):
        # Auto-populate from project data
        auto_data = _compute_benchmark_data(pid, project_data=project_data, actual_data=actual_data)
        _dialog_benchmark(pid, auto_data=auto_data)

    bench_df = get_benchmarks_df(type_filter)

    if not bench_df.empty:
        st.dataframe(
            bench_df, width="stretch", hide_index=True,
            column_config={
                'project_type':         st.column_config.TextColumn('Type'),
                'source_project':       st.column_config.TextColumn('Source Project'),
                'benchmark_date':       st.column_config.DateColumn('Date'),
                'alpha_used':           st.column_config.NumberColumn('α Used',   format="%.4f"),
                'alpha_actual':         st.column_config.NumberColumn('α Actual', format="%.4f"),
                'alpha_recommended':    st.column_config.NumberColumn('α Rec.',   format="%.4f"),
                'beta_used':            st.column_config.NumberColumn('β Used',   format="%.4f"),
                'beta_actual':          st.column_config.NumberColumn('β Actual', format="%.4f"),
                'beta_recommended':     st.column_config.NumberColumn('β Rec.',   format="%.4f"),
                'gamma_used':           st.column_config.NumberColumn('γ Used',   format="%.4f"),
                'gamma_actual':         st.column_config.NumberColumn('γ Actual', format="%.4f"),
                'gamma_recommended':    st.column_config.NumberColumn('γ Rec.',   format="%.4f"),
                'man_days_estimated':   st.column_config.NumberColumn('Days Est.'),
                'man_days_actual':      st.column_config.NumberColumn('Days Act.'),
                'gp_estimated_percent': st.column_config.NumberColumn('GP Est%', format="%.1f%%"),
                'gp_actual_percent':    st.column_config.NumberColumn('GP Act%', format="%.1f%%"),
                'lessons_learned':      st.column_config.TextColumn('Lessons Learned'),
            },
        )
    else:
        st.info("No benchmarks yet.")


def _compute_benchmark_data(pid: int, project_data: dict = None, actual_data: dict = None) -> dict:
    """Compute auto-fill data for benchmark dialog from project estimate + actual."""
    est    = get_active_estimate(pid)
    actual = actual_data or get_cogs_actual(pid)
    proj   = project_data or get_project(pid)
    data   = {}

    if proj:
        data['project_code'] = proj.get('project_code', '')
        data['type_code']    = proj.get('type_code', '')

    if est:
        data['alpha_used'] = float(est.get('alpha_rate', 0) or 0)
        data['beta_used']  = float(est.get('beta_rate', 0) or 0)
        data['gamma_used'] = float(est.get('gamma_rate', 0) or 0)
        data['days_est']   = int(est.get('d_man_days', 0) or 0)
        data['gp_est_pct'] = float(est.get('estimated_gp_percent', 0) or 0)

    if actual:
        a = float(actual.get('a_equipment_cost', 0) or 0)
        b = float(actual.get('b_logistics_import', 0) or 0)
        c = float(actual.get('c_custom_fabrication', 0) or 0)
        d_total = float(actual.get('d_direct_labor', 0) or 0) + float(actual.get('d_presales_labor', 0) or 0)
        e_total = float(actual.get('e_travel_site_oh', 0) or 0) + float(actual.get('e_presales_travel', 0) or 0)
        f_prov  = float(actual.get('f_warranty_provision', 0) or 0)

        data['alpha_actual'] = round(b / a, 4) if a > 0 else 0
        data['beta_actual']  = round(e_total / d_total, 4) if d_total > 0 else 0
        data['gamma_actual'] = round(f_prov / (a + c), 4) if (a + c) > 0 else 0
        data['days_act']     = int(actual.get('d_total_man_days', 0) or 0)
        data['gp_act_pct']   = float(actual.get('actual_gp_percent', 0) or 0)

    return data


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if is_all_projects:
    _render_portfolio()
else:
    if not project:
        st.error("Project not found.")
        st.stop()

    # ── Fetch data once for all tabs (eliminates 3× duplicate queries) ──
    _actual = get_cogs_actual(project_id)
    _est    = get_active_estimate(project_id)

    tab_actual, tab_variance, tab_bench = st.tabs(
        ["📊 Actual COGS", "📉 Variance Analysis", "📚 Benchmarks"]
    )

    with tab_actual:
        _render_actual_cogs_tab(project_id, _actual, _est)

    with tab_variance:
        _render_variance_tab(project_id, _actual, _est)

    with tab_bench:
        _render_benchmark_tab(project_id, project, _actual)