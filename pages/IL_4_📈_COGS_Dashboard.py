# pages/IL_4_📈_COGS_Dashboard.py
"""
COGS Dashboard — Actual COGS sync + Variance Analysis + Benchmarks
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

# ── Lookups ────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load():
    return get_projects_df(), get_project_types()

proj_df, proj_types = _load()
type_map = {t['id']: t for t in proj_types}

# ── Page header ────────────────────────────────────────────────────────────────
st.title("📈 COGS Dashboard")

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

st.caption(f"**{project['project_code']}** | {project.get('customer_name','—')} | Status: {project['status']}")

# ── Main tabs ──────────────────────────────────────────────────────────────────
tab_actual, tab_variance, tab_bench = st.tabs(["📊 Actual COGS", "📉 Variance Analysis", "📚 Benchmarks"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — ACTUAL COGS
# ══════════════════════════════════════════════════════════════════════════════
with tab_actual:
    actual = get_cogs_actual(project_id)
    est    = get_active_estimate(project_id)

    ac1, ac2, ac3 = st.columns([2,2,1])
    if ac2.button("🔄 Sync from Timesheets & Expenses", type="primary", use_container_width=True):
        with st.spinner("Syncing..."):
            try:
                sync_cogs_actual(project_id, user_id)
                st.success("Sync complete!")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Sync failed: {e}")

    if actual and actual.get('is_finalized'):
        st.info(f"✅ Finalized on {actual.get('finalized_date','—')} by {actual.get('finalized_by','—')}")
    elif is_pm and actual and ac3.button("🔒 Finalize"):
        if finalize_cogs_actual(project_id, user_id):
            st.success("COGS finalized.")
            st.rerun()

    if actual and actual.get('last_sync_date'):
        st.caption(f"Last sync: {actual['last_sync_date']}")

    # ── Side-by-side Estimated vs Actual ──────────────────────────────────────
    st.divider()

    def _get_est_val(key: str) -> float:
        if not est:
            return 0.0
        field_map = {
            'A': 'a_equipment_cost', 'B': 'b_logistics_import',
            'C': 'c_custom_fabrication', 'D': 'd_direct_labor',
            'E': 'e_travel_site_oh', 'F': 'f_warranty_reserve',
        }
        return float(est.get(field_map.get(key, ''), 0) or 0)

    def _get_act_val(key: str) -> float:
        if not actual:
            return 0.0
        field_map = {
            'A': 'a_equipment_cost', 'B': 'b_logistics_import',
            'C': 'c_custom_fabrication',
            'D': ('d_direct_labor', 'd_presales_labor'),  # combined
            'E': ('e_travel_site_oh', 'e_presales_travel'),
            'F': 'f_warranty_provision',
        }
        fld = field_map.get(key)
        if isinstance(fld, tuple):
            return sum(float(actual.get(f, 0) or 0) for f in fld)
        return float(actual.get(fld, 0) or 0)

    rows = []
    for k in ['A','B','C','D','E','F']:
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

    # Totals
    est_total = float(est['total_cogs'] if est else 0)
    act_total = float(actual['total_cogs'] if actual else 0)
    tot_var   = act_total - est_total
    tot_pct   = pct_change(est_total, act_total)
    rows.append({
        'Item': '**TOTAL COGS**',
        'Estimated': est_total, 'Actual': act_total,
        'Variance': tot_var, 'Var %': tot_pct,
        '': impact_color(tot_pct),
    })

    cmp_df = pd.DataFrame(rows)
    st.dataframe(
        cmp_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            'Item':      st.column_config.TextColumn('Item'),
            'Estimated': st.column_config.NumberColumn('Estimated (VND)', format="%.0f"),
            'Actual':    st.column_config.NumberColumn('Actual (VND)',    format="%.0f"),
            'Variance':  st.column_config.NumberColumn('Variance (VND)',  format="+%.0f"),
            'Var %':     st.column_config.NumberColumn('Var %',           format="+%.1f%%"),
            '':          st.column_config.TextColumn('',                  width=30),
        }
    )

    # GP comparison
    st.divider()
    gp1, gp2, gp3, gp4 = st.columns(4)
    sales_est = float(est['sales_value'] if est else 0)
    sales_act = float(actual['sales_value'] if actual else 0)
    gp1.metric("Est. Sales",   fmt_vnd(sales_est))
    gp2.metric("Act. Sales",   fmt_vnd(sales_act))
    gp3.metric("Est. GP%",     fmt_percent(est['estimated_gp_percent'] if est else None))
    act_gp_pct = float(actual['actual_gp_percent'] if actual else 0)
    delta_gp   = act_gp_pct - float(est['estimated_gp_percent'] if est else 0)
    gp4.metric("Act. GP%",     fmt_percent(act_gp_pct), delta=f"{delta_gp:+.1f}pp")

    # ── Manual entry for A, B, C, F ───────────────────────────────────────────
    if is_pm:
        with st.expander("✏️ Enter A / B / C / F manually (from invoices)"):
            with st.form("cogs_actual_manual"):
                ma1, ma2 = st.columns(2)
                a_act = ma1.number_input("A: Equipment (from PI)", value=float(actual['a_equipment_cost'] if actual else 0), format="%.0f")
                a_n   = ma2.text_input("Notes A", value=actual.get('a_notes','') if actual else '')
                mb1, mb2 = st.columns(2)
                b_act = mb1.number_input("B: Logistics & Import (from BoL/Tax Invoice)", value=float(actual['b_logistics_import'] if actual else 0), format="%.0f")
                b_n   = mb2.text_input("Notes B", value=actual.get('b_notes','') if actual else '')
                mc1, mc2 = st.columns(2)
                c_act = mc1.number_input("C: Custom Fabrication (from subcon PO)", value=float(actual['c_custom_fabrication'] if actual else 0), format="%.0f")
                c_n   = mc2.text_input("Notes C", value=actual.get('c_notes','') if actual else '')
                st.markdown("**F — Warranty**")
                mf1, mf2, mf3 = st.columns(3)
                f_prov = mf1.number_input("F: Provision (accrued)", value=float(actual['f_warranty_provision'] if actual else 0), format="%.0f")
                f_used = mf2.number_input("F: Actual Used",         value=float(actual['f_warranty_actual_used'] if actual else 0), format="%.0f")
                f_rel  = mf3.number_input("F: Released (unused)",   value=float(actual['f_warranty_released'] if actual else 0), format="%.0f")
                f_n    = st.text_input("Notes F", value=actual.get('f_notes','') if actual else '')

                if st.form_submit_button("💾 Save Manual Entries", type="primary"):
                    ok = update_cogs_actual_fields(project_id, {
                        'a_equipment_cost': a_act, 'a_notes': a_n or None,
                        'b_logistics_import': b_act, 'b_notes': b_n or None,
                        'c_custom_fabrication': c_act, 'c_notes': c_n or None,
                        'f_warranty_provision': f_prov,
                        'f_warranty_actual_used': f_used,
                        'f_warranty_released': f_rel, 'f_notes': f_n or None,
                    }, user_id)
                    if ok:
                        st.success("Saved. Click 🔄 Sync to recalculate totals.")
                        st.rerun()
                    else:
                        st.warning("No record updated — try Sync first to initialise.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — VARIANCE ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
with tab_variance:
    var_df = get_variance_df(project_id)

    if not var_df.empty:
        var_df.insert(0, '●', var_df['variance_percent'].map(impact_color))
        st.dataframe(
            var_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                '●':                     st.column_config.TextColumn('', width=30),
                'cogs_category':         st.column_config.TextColumn('Category'),
                'estimated_amount':      st.column_config.NumberColumn('Estimated', format="%.0f"),
                'actual_amount':         st.column_config.NumberColumn('Actual',    format="%.0f"),
                'variance_amount':       st.column_config.NumberColumn('Variance',  format="+%.0f"),
                'variance_percent':      st.column_config.NumberColumn('Var %',     format="+%.1f%%"),
                'impact_assessment':     st.column_config.TextColumn('Impact'),
                'coefficient_used':      st.column_config.NumberColumn('Coeff Used',  format="%.4f"),
                'coefficient_actual':    st.column_config.NumberColumn('Coeff Actual', format="%.4f"),
                'coefficient_recommended': st.column_config.NumberColumn('Coeff Rec.', format="%.4f"),
                'root_cause':            st.column_config.TextColumn('Root Cause'),
            }
        )
    else:
        st.info("No variance records yet. Use the form below to record analysis.")

    # Add / update variance row
    with st.expander("➕ Record Variance Analysis"):
        with st.form("variance_form"):
            cat_opts = ['A','B','C','D','E','F','PRESALES','TOTAL']
            va1, va2, va3 = st.columns(3)
            var_cat  = va1.selectbox("COGS Category", cat_opts)
            var_est  = va2.number_input("Estimated Amount", value=0.0, format="%.0f")
            var_act  = va3.number_input("Actual Amount",    value=0.0, format="%.0f")

            var_impact_opts = [None, 'FAVORABLE','NEUTRAL','UNFAVORABLE']
            var_impact = st.selectbox("Impact", ['(auto from sign)','FAVORABLE','NEUTRAL','UNFAVORABLE'])
            if var_impact == '(auto from sign)':
                auto_pct   = pct_change(var_est, var_act)
                var_impact = 'FAVORABLE' if (auto_pct or 0) < -5 else 'UNFAVORABLE' if (auto_pct or 0) > 5 else 'NEUTRAL'

            var_rc  = st.text_area("Root Cause",        height=70)
            var_ca  = st.text_area("Corrective Action", height=70)

            has_coeff = var_cat in ('B','E','F')
            if has_coeff:
                vc1, vc2, vc3 = st.columns(3)
                c_used = vc1.number_input("Coefficient Used",        value=0.0, format="%.4f")
                c_act  = vc2.number_input("Coefficient Actual",      value=0.0, format="%.4f")
                c_rec  = vc3.number_input("Coefficient Recommended", value=0.0, format="%.4f")
            else:
                c_used = c_act = c_rec = None

            if st.form_submit_button("Save Variance Record", type="primary"):
                ok = upsert_variance_row(
                    project_id, var_cat,
                    var_est, var_act,
                    var_rc, var_ca, var_impact,
                    c_used if has_coeff and c_used else None,
                    c_act  if has_coeff and c_act  else None,
                    c_rec  if has_coeff and c_rec  else None,
                    user_id,
                )
                if ok:
                    st.success("Saved!")
                    st.rerun()
                else:
                    st.error("Save failed.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — BENCHMARKS
# ══════════════════════════════════════════════════════════════════════════════
with tab_bench:
    bf_type  = st.selectbox("Filter by Type", ["All"] + [f"[{t['code']}] {t['name']}" for t in proj_types])
    type_filter = None
    if bf_type != "All":
        code = bf_type.split("]")[0][1:]
        hit  = next((t for t in proj_types if t['code'] == code), None)
        type_filter = hit['id'] if hit else None

    bench_df = get_benchmarks_df(type_filter)

    if not bench_df.empty:
        st.dataframe(
            bench_df,
            use_container_width=True,
            hide_index=True,
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
            }
        )
    else:
        st.info("No benchmarks yet.")

    with st.expander("➕ Add Benchmark Record"):
        with st.form("benchmark_form"):
            type_opts = [f"[{t['code']}] {t['name']}" for t in proj_types]
            bt1, bt2, bt3 = st.columns(3)
            bm_type    = bt1.selectbox("Project Type", type_opts)
            bm_type_id = proj_types[[t['code'] for t in proj_types].index(bm_type.split("]")[0][1:])]['id']
            bm_date    = bt2.date_input("Benchmark Date")

            src_opts   = ["(None)"] + [f"{r.project_code}" for r in proj_df.itertuples()]
            bm_src     = bt3.selectbox("Source Project", src_opts)
            bm_src_id  = None
            if bm_src != "(None)":
                src_row = proj_df[proj_df['project_code'] == bm_src]
                bm_src_id = int(src_row.iloc[0]['project_id']) if not src_row.empty else None

            st.markdown("**Coefficients**")
            bc1, bc2, bc3 = st.columns(3)
            alpha_u = bc1.number_input("α Used",   value=0.06, format="%.4f")
            alpha_a = bc2.number_input("α Actual", value=0.06, format="%.4f")
            alpha_r = bc3.number_input("α Rec.",   value=0.06, format="%.4f")
            bd1, bd2, bd3 = st.columns(3)
            beta_u  = bd1.number_input("β Used",   value=0.40, format="%.4f")
            beta_a  = bd2.number_input("β Actual", value=0.40, format="%.4f")
            beta_r  = bd3.number_input("β Rec.",   value=0.40, format="%.4f")
            be1, be2, be3 = st.columns(3)
            gamma_u = be1.number_input("γ Used",   value=0.04, format="%.4f")
            gamma_a = be2.number_input("γ Actual", value=0.04, format="%.4f")
            gamma_r = be3.number_input("γ Rec.",   value=0.04, format="%.4f")

            bf1, bf2, bf3, bf4 = st.columns(4)
            days_est  = bf1.number_input("Man-Days Estimated", value=0, min_value=0)
            days_act  = bf2.number_input("Man-Days Actual",    value=0, min_value=0)
            gp_est    = bf3.number_input("GP Est%",            value=0.0, format="%.1f")
            gp_act    = bf4.number_input("GP Act%",            value=0.0, format="%.1f")

            lessons   = st.text_area("Lessons Learned",   height=80)
            risks     = st.text_area("Key Risk Factors",  height=60)
            recs      = st.text_area("Recommendations",   height=60)

            if st.form_submit_button("Save Benchmark", type="primary"):
                create_benchmark({
                    'project_type_id': bm_type_id,
                    'source_project_id': bm_src_id,
                    'benchmark_date': bm_date,
                    'alpha_used': alpha_u, 'alpha_actual': alpha_a, 'alpha_recommended': alpha_r,
                    'beta_used': beta_u,  'beta_actual': beta_a,  'beta_recommended': beta_r,
                    'gamma_used': gamma_u, 'gamma_actual': gamma_a, 'gamma_recommended': gamma_r,
                    'man_days_estimated': days_est or None,
                    'man_days_actual': days_act or None,
                    'man_days_by_phase': None,
                    'gp_estimated_percent': gp_est or None,
                    'gp_actual_percent': gp_act or None,
                    'lessons_learned': lessons or None,
                    'key_risk_factors': risks or None,
                    'recommendations': recs or None,
                }, user_id)
                st.success("Benchmark saved!")
                st.rerun()
