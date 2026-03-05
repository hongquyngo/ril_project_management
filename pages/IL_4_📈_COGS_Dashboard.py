# pages/IL_4_📈_COGS_Dashboard.py
"""
COGS Dashboard — Actual COGS sync + Variance Analysis + Benchmarks
UX: @st.dialog cho manual entry/variance/benchmark | @st.fragment cho tables
"""

import streamlit as st
import pandas as pd
import logging

from utils.auth import AuthManager
from utils.il_project import (
    get_projects_df, get_project,
    get_active_estimate,
    get_cogs_actual, sync_cogs_actual, update_cogs_actual_fields, finalize_cogs_actual,
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


# ── Page header ───────────────────────────────────────────────────────────────
st.title("📈 COGS Dashboard")

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

st.caption(f"**{project['project_code']}** | {project.get('customer_name', '—')} | Status: {project['status']}")


# ══════════════════════════════════════════════════════════════════════════════
# DIALOGS
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("✏️ Manual Entry — A / B / C / F", width="large")
def _dialog_cogs_manual(project_id: int, actual: dict):
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

        submitted = st.form_submit_button("💾 Save", type="primary", width="stretch")

    if submitted:
        ok = update_cogs_actual_fields(project_id, {
            'a_equipment_cost':       a_act, 'a_notes': a_n or None,
            'b_logistics_import':     b_act, 'b_notes': b_n or None,
            'c_custom_fabrication':   c_act, 'c_notes': c_n or None,
            'f_warranty_provision':   f_prov,
            'f_warranty_actual_used': f_used,
            'f_warranty_released':    f_rel,  'f_notes': f_n or None,
        }, user_id)
        if ok:
            st.success("✅ Saved. Click 🔄 Sync to update COGS totals.")
            st.rerun()
        else:
            st.warning("Record not found — run Sync first to initialize.")


@st.dialog("📉 Record Variance Analysis", width="large")
def _dialog_variance(project_id: int):
    with st.form("variance_form"):
        cat_opts = ['A', 'B', 'C', 'D', 'E', 'F', 'PRESALES', 'TOTAL']
        va1, va2, va3 = st.columns(3)
        var_cat  = va1.selectbox("COGS Category", cat_opts)
        var_est  = va2.number_input("Estimated Amount", value=0.0, format="%.0f")
        var_act  = va3.number_input("Actual Amount",    value=0.0, format="%.0f")

        var_impact_sel = st.selectbox("Impact", ['(auto from sign)', 'FAVORABLE', 'NEUTRAL', 'UNFAVORABLE'])
        if var_impact_sel == '(auto from sign)':
            auto_pct   = pct_change(var_est, var_act)
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

        submitted = st.form_submit_button("💾 Save", type="primary", width="stretch")

    if submitted:
        ok = upsert_variance_row(
            project_id, var_cat,
            var_est, var_act,
            var_rc, var_ca, var_impact,
            c_used  if has_coeff and c_used  else None,
            c_act_v if has_coeff and c_act_v else None,
            c_rec   if has_coeff and c_rec   else None,
            user_id,
        )
        if ok:
            st.success("✅ Saved!")
            st.rerun()
        else:
            st.error("Save failed.")


@st.dialog("📚 Add Benchmark Record", width="large")
def _dialog_benchmark(project_id: int):
    with st.form("benchmark_form"):
        type_opts  = [f"[{t['code']}] {t['name']}" for t in proj_types]
        bt1, bt2, bt3 = st.columns(3)
        bm_type    = bt1.selectbox("Project Type", type_opts)
        _bm_code   = bm_type.split("]")[0][1:]
        bm_type_id = next((t for t in proj_types if t['code'] == _bm_code), proj_types[0])['id']
        bm_date    = bt2.date_input("Benchmark Date")

        src_opts   = ["(None)"] + [f"{r.project_code}" for r in proj_df.itertuples()]
        bm_src     = bt3.selectbox("Source Project", src_opts)
        bm_src_id  = None
        if bm_src != "(None)":
            src_row   = proj_df[proj_df['project_code'] == bm_src]
            bm_src_id = int(src_row.iloc[0]['project_id']) if not src_row.empty else None

        st.markdown("**Coefficients — α (Logistics ratio)**")
        bc1, bc2, bc3 = st.columns(3)
        alpha_u = bc1.number_input("α Used",   value=0.06, format="%.4f")
        alpha_a = bc2.number_input("α Actual", value=0.06, format="%.4f")
        alpha_r = bc3.number_input("α Rec.",   value=0.06, format="%.4f")

        st.markdown("**β (Travel & Site OH ratio)**")
        bd1, bd2, bd3 = st.columns(3)
        beta_u  = bd1.number_input("β Used",   value=0.40, format="%.4f")
        beta_a  = bd2.number_input("β Actual", value=0.40, format="%.4f")
        beta_r  = bd3.number_input("β Rec.",   value=0.40, format="%.4f")

        st.markdown("**γ (Warranty Reserve ratio)**")
        be1, be2, be3 = st.columns(3)
        gamma_u = be1.number_input("γ Used",   value=0.04, format="%.4f")
        gamma_a = be2.number_input("γ Actual", value=0.04, format="%.4f")
        gamma_r = be3.number_input("γ Rec.",   value=0.04, format="%.4f")

        bf1, bf2, bf3, bf4 = st.columns(4)
        days_est = bf1.number_input("Man-Days Estimated", value=0, min_value=0)
        days_act = bf2.number_input("Man-Days Actual",    value=0, min_value=0)
        gp_est   = bf3.number_input("GP Est%",            value=0.0, format="%.1f")
        gp_act   = bf4.number_input("GP Act%",            value=0.0, format="%.1f")

        lessons = st.text_area("Lessons Learned",  height=80)
        risks   = st.text_area("Key Risk Factors", height=60)
        recs    = st.text_area("Recommendations",  height=60)

        submitted = st.form_submit_button("💾 Save Benchmark", type="primary", width="stretch")

    if submitted:
        try:
            create_benchmark({
                'project_type_id':      bm_type_id,
                'source_project_id':    bm_src_id,
                'benchmark_date':       bm_date,
                'alpha_used':  alpha_u, 'alpha_actual':  alpha_a, 'alpha_recommended': alpha_r,
                'beta_used':   beta_u,  'beta_actual':   beta_a,  'beta_recommended':  beta_r,
                'gamma_used':  gamma_u, 'gamma_actual':  gamma_a, 'gamma_recommended': gamma_r,
                'man_days_estimated': days_est or None,
                'man_days_actual':    days_act or None,
                'man_days_by_phase':  None,
                'gp_estimated_percent': gp_est or None,
                'gp_actual_percent':    gp_act or None,
                'lessons_learned':    lessons or None,
                'key_risk_factors':   risks   or None,
                'recommendations':    recs    or None,
            }, user_id)
            st.success("✅ Benchmark saved!")
            st.rerun()
        except Exception as e:
            st.error(f"Save failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# FRAGMENT — Actual COGS tab
# ══════════════════════════════════════════════════════════════════════════════

@st.fragment
def _actual_cogs_tab(project_id: int):
    actual = get_cogs_actual(project_id)
    est    = get_active_estimate(project_id)

    # ── Sync / Finalize toolbar ───────────────────────────────────────────────
    ac1, ac2, ac3, ac4 = st.columns([2, 2, 2, 1])

    if ac2.button("🔄 Sync from Timesheets & Expenses", type="primary", width="stretch"):
        with st.spinner("Syncing..."):
            try:
                sync_cogs_actual(project_id, user_id)
                st.success("Sync complete!")
                st.rerun(scope="fragment")
            except Exception as e:
                st.error(f"Sync failed: {e}")

    if is_pm:
        if ac3.button("✏️ Manual Entry (A/B/C/F)", width="stretch"):
            _dialog_cogs_manual(project_id, actual or {})
        if actual and not actual.get('is_finalized'):
            if ac4.button("🔒 Finalize"):
                if finalize_cogs_actual(project_id, user_id):
                    st.success("COGS finalized.")
                    st.rerun(scope="fragment")

    if actual and actual.get('is_finalized'):
        st.info(f"✅ Finalized on {actual.get('finalized_date', '—')} by {actual.get('finalized_by', '—')}")
    if actual and actual.get('last_sync_date'):
        st.caption(f"Last sync: {actual['last_sync_date']}")

    # ── Estimated vs Actual table ─────────────────────────────────────────────
    st.divider()

    def _get_est_val(key: str) -> float:
        if not est:
            return 0.0
        field_map = {
            'A': 'a_equipment_cost',    'B': 'b_logistics_import',
            'C': 'c_custom_fabrication', 'D': 'd_direct_labor',
            'E': 'e_travel_site_oh',    'F': 'f_warranty_reserve',
        }
        return float(est.get(field_map.get(key, ''), 0) or 0)

    def _get_act_val(key: str) -> float:
        if not actual:
            return 0.0
        field_map = {
            'A': 'a_equipment_cost',    'B': 'b_logistics_import',
            'C': 'c_custom_fabrication',
            'D': ('d_direct_labor', 'd_presales_labor'),
            'E': ('e_travel_site_oh', 'e_presales_travel'),
            'F': 'f_warranty_provision',
        }
        fld = field_map.get(key)
        if isinstance(fld, tuple):
            return sum(float(actual.get(f, 0) or 0) for f in fld)
        return float(actual.get(fld, 0) or 0)

    rows = []
    for k in ['A', 'B', 'C', 'D', 'E', 'F']:
        est_v = _get_est_val(k)
        act_v = _get_act_val(k)
        var_v = act_v - est_v
        var_p = pct_change(est_v, act_v)
        rows.append({
            'Item':      COGS_LABELS[k],
            'Estimated': est_v,
            'Actual':    act_v,
            'Variance':  var_v,
            'Var %':     var_p,
            '':          impact_color(var_p),
        })

    est_total = float(est['total_cogs'] if est else 0)
    act_total = float(actual['total_cogs'] if actual else 0)
    tot_var   = act_total - est_total
    tot_pct   = pct_change(est_total, act_total)
    rows.append({
        'Item': '**TOTAL COGS**',
        'Estimated': est_total, 'Actual': act_total,
        'Variance':  tot_var,   'Var %':  tot_pct,
        '': impact_color(tot_pct),
    })

    st.dataframe(
        pd.DataFrame(rows), width="stretch", hide_index=True,
        column_config={
            'Item':      st.column_config.TextColumn('Item'),
            'Estimated': st.column_config.NumberColumn('Estimated (VND)', format="%.0f"),
            'Actual':    st.column_config.NumberColumn('Actual (VND)',    format="%.0f"),
            'Variance':  st.column_config.NumberColumn('Variance (VND)',  format="+%.0f"),
            'Var %':     st.column_config.NumberColumn('Var %',           format="+%.1f%%"),
            '':          st.column_config.TextColumn('',                  width=30),
        },
    )

    # ── GP comparison ─────────────────────────────────────────────────────────
    st.divider()
    gp1, gp2, gp3, gp4 = st.columns(4)
    sales_est  = float(est['sales_value'] if est else 0)
    sales_act  = float(actual['sales_value'] if actual else 0)
    gp1.metric("Est. Sales",  fmt_vnd(sales_est))
    gp2.metric("Act. Sales",  fmt_vnd(sales_act))
    gp3.metric("Est. GP%",    fmt_percent(est['estimated_gp_percent'] if est else None))
    act_gp_pct = float(actual['actual_gp_percent'] if actual else 0)
    delta_gp   = act_gp_pct - float(est['estimated_gp_percent'] if est else 0)
    gp4.metric("Act. GP%",    fmt_percent(act_gp_pct), delta=f"{delta_gp:+.1f}pp")


# ══════════════════════════════════════════════════════════════════════════════
# FRAGMENT — Variance tab
# ══════════════════════════════════════════════════════════════════════════════

@st.fragment
def _variance_tab(project_id: int):
    vh1, vh2 = st.columns([5, 1])
    if vh2.button("➕ Add", type="primary", width="stretch", key="btn_add_variance"):
        _dialog_variance(project_id)

    var_df = get_variance_df(project_id)

    if not var_df.empty:
        display_df = var_df.copy()
        display_df.insert(0, '●', display_df['variance_percent'].map(impact_color))
        st.dataframe(
            display_df, width="stretch", hide_index=True,
            column_config={
                '●':                       st.column_config.TextColumn('', width=30),
                'cogs_category':           st.column_config.TextColumn('Category'),
                'estimated_amount':        st.column_config.NumberColumn('Estimated', format="%.0f"),
                'actual_amount':           st.column_config.NumberColumn('Actual',    format="%.0f"),
                'variance_amount':         st.column_config.NumberColumn('Variance',  format="+%.0f"),
                'variance_percent':        st.column_config.NumberColumn('Var %',     format="+%.1f%%"),
                'impact_assessment':       st.column_config.TextColumn('Impact'),
                'coefficient_used':        st.column_config.NumberColumn('Coeff Used',  format="%.4f"),
                'coefficient_actual':      st.column_config.NumberColumn('Coeff Actual', format="%.4f"),
                'coefficient_recommended': st.column_config.NumberColumn('Coeff Rec.',  format="%.4f"),
                'root_cause':              st.column_config.TextColumn('Root Cause'),
            },
        )
    else:
        st.info("No variance records yet. Add one using the button above.")


# ══════════════════════════════════════════════════════════════════════════════
# FRAGMENT — Benchmarks tab
# ══════════════════════════════════════════════════════════════════════════════

@st.fragment
def _benchmark_tab(project_id: int):
    bh1, bh2, bh3 = st.columns([3, 2, 1])

    bf_type     = bh1.selectbox("Filter by Type", ["All"] + [f"[{t['code']}] {t['name']}" for t in proj_types])
    type_filter = None
    if bf_type != "All":
        code = bf_type.split("]")[0][1:]
        hit  = next((t for t in proj_types if t['code'] == code), None)
        type_filter = hit['id'] if hit else None

    if bh3.button("➕ Add", type="primary", width="stretch", key="btn_add_benchmark"):
        _dialog_benchmark(project_id)

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


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

tab_actual, tab_variance, tab_bench = st.tabs(["📊 Actual COGS", "📉 Variance Analysis", "📚 Benchmarks"])

with tab_actual:
    _actual_cogs_tab(project_id)

with tab_variance:
    _variance_tab(project_id)

with tab_bench:
    _benchmark_tab(project_id)