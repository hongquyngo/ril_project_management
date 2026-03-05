# pages/IL_2_📊_Estimate_GP.py
"""
Estimate GP — Pre-feasibility A→F formula + Go/No-Go decision.
"""

import streamlit as st
import pandas as pd
import logging

from utils.auth import AuthManager
from utils.il_project import (
    get_projects_df, get_project,
    get_estimates, get_active_estimate, create_estimate, update_estimate, activate_estimate,
    get_project_types,
    calculate_estimate, get_go_no_go, fmt_vnd, fmt_percent,
    COGS_LABELS,
)

logger = logging.getLogger(__name__)
auth = AuthManager()

st.set_page_config(page_title="Estimate GP", page_icon="📊", layout="wide")
auth.require_auth()
user_id = str(auth.get_user_id())


# ── Lookups ────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load_projects():
    df = get_projects_df()
    return df[['project_id','project_code','project_name','status']].copy() if not df.empty else df

@st.cache_data(ttl=300)
def _load_types():
    return get_project_types()

proj_df   = _load_projects()
proj_types = _load_types()
type_map  = {t['id']: t for t in proj_types}


# ── Page header ────────────────────────────────────────────────────────────────
st.title("📊 Estimate GP")
st.caption("Pre-feasibility Go/No-Go assessment using A→F formula")

# ── Project selector ───────────────────────────────────────────────────────────
if proj_df.empty:
    st.warning("No projects found. Create a project first.")
    st.stop()

proj_options = [f"{r.project_code} — {r.project_name}" for r in proj_df.itertuples()]
sel_label    = st.selectbox("Select Project", proj_options)
sel_idx      = proj_options.index(sel_label)
project_id   = int(proj_df.iloc[sel_idx]['project_id'])
project      = get_project(project_id)

if not project:
    st.error("Project not found.")
    st.stop()

# ── Load estimate versions ─────────────────────────────────────────────────────
all_estimates = get_estimates(project_id)
active_est    = next((e for e in all_estimates if e.get('is_active')), None)
next_version  = (max((e['estimate_version'] for e in all_estimates), default=0) + 1)

# ── Tabs: New / Active / History ───────────────────────────────────────────────
tab_new, tab_active, tab_history = st.tabs(["📝 New Estimate", "✅ Active Estimate", "🗂 History"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — New Estimate
# ══════════════════════════════════════════════════════════════════════════════
with tab_new:
    # Load type defaults for auto-fill
    pt = type_map.get(project.get('project_type_id', 0), {})
    def_alpha = float(pt.get('default_alpha', 0.06))
    def_beta  = float(pt.get('default_beta',  0.40))
    def_gamma = float(pt.get('default_gamma', 0.04))
    go_thresh = float(pt.get('gp_go_threshold', 25))
    cond_thr  = float(pt.get('gp_conditional_threshold', 18))

    st.markdown(f"**Project:** `{project['project_code']}` — {project['project_name']}")
    st.markdown(f"**Type:** {project.get('type_name','—')} &nbsp;|&nbsp; **Distance:** {project.get('site_distance_category','—')} &nbsp;|&nbsp; **Environment:** {project.get('environment_category','—')}")
    st.divider()

    col_form, col_result = st.columns([3, 2])

    with col_form:
        with st.form("estimate_form"):
            label = st.text_input("Estimate Label", value=f"Rev {next_version}", placeholder="Initial / Rev2 / Final")
            est_type = st.radio("Type", ["QUICK", "DETAILED"], horizontal=True)

            st.markdown("**Sales Value**")
            sales_value = st.number_input("Expected Selling Price (VND)", value=0.0, min_value=0.0, format="%.0f",
                                           help="Nhập giá bán dự kiến")

            st.markdown("---")
            st.markdown("**A — Equipment Cost**")
            a_cost  = st.number_input("A: Equipment (FOB/CIF) *", value=0.0, min_value=0.0, format="%.0f",
                                       help="AMR, charging station, PDA, SW license, IT hardware")
            a_notes = st.text_input("Notes A", placeholder="e.g. 6 AMR + 3 charging + 9 PDA")

            st.markdown("**B — Logistics & Import**  *(B = A × α)*")
            bc1, bc2 = st.columns([1,2])
            alpha       = bc1.number_input("α (alpha)", value=def_alpha, min_value=0.0, max_value=1.0, format="%.4f",
                                            help="In-country 3-5%, imported 6-10%")
            b_manual    = bc2.number_input("B Override (0 = use formula)", value=0.0, min_value=0.0, format="%.0f")

            st.markdown("**C — Custom Fabrication**")
            c_cost  = st.number_input("C: Trolley / Rack / Jig (VND)", value=0.0, min_value=0.0, format="%.0f")
            c_notes = st.text_input("Notes C", placeholder="e.g. 18 trolley big + 32 trolley small")

            st.markdown("**D — Direct Labor**  *(D = man-days × rate × team)*")
            dd1, dd2, dd3 = st.columns(3)
            man_days  = dd1.number_input("Man-Days", value=0, min_value=0, step=1,
                                          help=f"Benchmark for {pt.get('code','?')}: see Benchmark sheet")
            day_rate  = dd2.number_input("Day Rate (VND)", value=1_500_000.0, min_value=0.0, format="%.0f",
                                          help="All-in: Engineer ~1.2M, PM ~2.1M")
            team_size = dd3.number_input("Team Size (avg)", value=1.0, min_value=0.1, format="%.1f")
            d_manual  = st.number_input("D Override (0 = use formula)", value=0.0, min_value=0.0, format="%.0f")

            st.markdown("**E — Travel & Site OH**  *(E = D × β)*")
            ec1, ec2 = st.columns([1,2])
            beta     = ec1.number_input("β (beta)", value=def_beta, min_value=0.0, max_value=1.0, format="%.4f",
                                         help="LOCAL 30%, FAR 50%, OVERSEAS 60%")
            e_manual = ec2.number_input("E Override (0 = use formula)", value=0.0, min_value=0.0, format="%.0f")

            st.markdown("**F — Warranty Reserve**  *(F = (A+C) × γ)*")
            fc1, fc2 = st.columns([1,2])
            gamma    = fc1.number_input("γ (gamma)", value=def_gamma, min_value=0.0, max_value=1.0, format="%.4f",
                                         help="CLEAN env 3%, HARSH 5%")
            f_manual = fc2.number_input("F Override (0 = use formula)", value=0.0, min_value=0.0, format="%.0f")

            assessment_notes = st.text_area("Assessment Notes", height=80)
            submitted = st.form_submit_button("💾 Save & Activate", type="primary", width="stretch")

    # ── Live preview (updates as user types) ──────────────────────────────────
    with col_result:
        st.markdown("### 📐 Live Estimate")
        result = calculate_estimate(
            a_equipment=a_cost,
            alpha=alpha,
            c_fabrication=c_cost,
            man_days=man_days,
            man_day_rate=day_rate,
            team_size=team_size,
            beta=beta,
            gamma=gamma,
            sales_value=sales_value,
            b_override=b_manual if b_manual > 0 else None,
            d_override=d_manual if d_manual > 0 else None,
            e_override=e_manual if e_manual > 0 else None,
            f_override=f_manual if f_manual > 0 else None,
        )

        # COGS breakdown table
        cogs_rows = []
        for key in ['a','b','c','d','e','f']:
            label = COGS_LABELS.get(key.upper(), key.upper())
            val   = result.get(key, 0)
            pct   = (val / result['total_cogs'] * 100) if result['total_cogs'] > 0 else 0
            cogs_rows.append({'Item': label, 'Amount (VND)': val, '% COGS': pct})

        cogs_df = pd.DataFrame(cogs_rows)
        st.dataframe(
            cogs_df,
            width="stretch",
            hide_index=True,
            column_config={
                'Item':        st.column_config.TextColumn('Item'),
                'Amount (VND)': st.column_config.NumberColumn('Amount (VND)', format="%.0f"),
                '% COGS':      st.column_config.NumberColumn('% COGS', format="%.1f%%"),
            }
        )

        st.divider()
        r1, r2 = st.columns(2)
        r1.metric("Sales",      fmt_vnd(result['sales']))
        r1.metric("Total COGS", fmt_vnd(result['total_cogs']))
        r2.metric("Gross Profit", fmt_vnd(result['gp']))
        r2.metric("GP%",          f"{result['gp_percent']:.1f}%")

        gng = get_go_no_go(result['gp_percent'], go_thresh, cond_thr)
        st.divider()
        if gng == 'GO':
            st.success(f"### ✅ GO  —  GP {result['gp_percent']:.1f}%")
        elif gng == 'CONDITIONAL':
            st.warning(f"### ⚠️ CONDITIONAL  —  GP {result['gp_percent']:.1f}%")
        else:
            st.error(f"### ❌ NO-GO  —  GP {result['gp_percent']:.1f}%")
        st.caption(f"Thresholds: GO ≥ {go_thresh}%  |  CONDITIONAL ≥ {cond_thr}%")

    # ── Save ───────────────────────────────────────────────────────────────────
    if submitted:
        if a_cost <= 0 and sales_value <= 0:
            st.warning("Enter at least Equipment Cost and Sales Value.")
        else:
            gng_save = get_go_no_go(result['gp_percent'], go_thresh, cond_thr)
            est_data = {
                'project_id': project_id,
                'estimate_version': next_version,
                'estimate_label': label,
                'estimate_type': est_type,
                'a_equipment_cost': a_cost, 'a_equipment_notes': a_notes or None,
                'alpha_rate': alpha,
                'b_logistics_import': result['b'], 'b_override': 1 if b_manual > 0 else 0,
                'c_custom_fabrication': c_cost, 'c_fabrication_notes': c_notes or None,
                'd_man_days': man_days, 'd_man_day_rate': day_rate, 'd_team_size': team_size,
                'd_direct_labor': result['d'], 'd_override': 1 if d_manual > 0 else 0,
                'beta_rate': beta,
                'e_travel_site_oh': result['e'], 'e_override': 1 if e_manual > 0 else 0,
                'gamma_rate': gamma,
                'f_warranty_reserve': result['f'], 'f_override': 1 if f_manual > 0 else 0,
                'total_cogs': result['total_cogs'],
                'sales_value': result['sales'],
                'estimated_gp': result['gp'],
                'estimated_gp_percent': result['gp_percent'],
                'go_no_go_result': gng_save,
                'assessment_notes': assessment_notes or None,
            }
            try:
                new_id = create_estimate(est_data, user_id)
                activate_estimate(project_id, new_id, user_id)
                st.success(f"✅ Estimate Rev {next_version} saved and activated!")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Active Estimate
# ══════════════════════════════════════════════════════════════════════════════
with tab_active:
    if not active_est:
        st.info("No active estimate yet. Create one in the 'New Estimate' tab.")
        st.stop()

    st.markdown(f"**Rev {active_est['estimate_version']}** — {active_est.get('estimate_label','')}")
    gng_active = active_est.get('go_no_go_result','')
    if gng_active == 'GO':
        st.success(f"✅ GO — GP {active_est['estimated_gp_percent']:.1f}%")
    elif gng_active == 'CONDITIONAL':
        st.warning(f"⚠️ CONDITIONAL — GP {active_est['estimated_gp_percent']:.1f}%")
    elif gng_active == 'NO_GO':
        st.error(f"❌ NO-GO — GP {active_est['estimated_gp_percent']:.1f}%")

    # Summary table
    rows = []
    for key in ['a','b','c','d','e','f']:
        label = COGS_LABELS.get(key.upper(), key.upper())
        amt   = float(active_est.get(f'{key}_equipment_cost' if key == 'a'
                       else f'{key}_logistics_import' if key == 'b'
                       else f'{key}_custom_fabrication' if key == 'c'
                       else f'{key}_direct_labor' if key == 'd'
                       else f'{key}_travel_site_oh' if key == 'e'
                       else f'{key}_warranty_reserve', 0) or 0)
        rows.append({'Item': label, 'Estimate (VND)': amt})

    summary_df = pd.DataFrame(rows)
    total_row  = pd.DataFrame([{'Item': '**TOTAL COGS**', 'Estimate (VND)': active_est['total_cogs']}])
    summary_df = pd.concat([summary_df, total_row], ignore_index=True)

    st.dataframe(summary_df, width="stretch", hide_index=True,
                 column_config={'Estimate (VND)': st.column_config.NumberColumn(format="%.0f")})

    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("Sales Value",  fmt_vnd(active_est['sales_value']))
    mc2.metric("Gross Profit", fmt_vnd(active_est['estimated_gp']))
    mc3.metric("GP%",          fmt_percent(active_est['estimated_gp_percent']))

    if active_est.get('assessment_notes'):
        st.info(f"📝 {active_est['assessment_notes']}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — History
# ══════════════════════════════════════════════════════════════════════════════
with tab_history:
    if not all_estimates:
        st.info("No estimates yet.")
        st.stop()

    hist_df = pd.DataFrame([{
        'Rev':         e['estimate_version'],
        'Label':       e.get('estimate_label',''),
        'Type':        e.get('estimate_type',''),
        'Active':      '✅' if e.get('is_active') else '',
        'Total COGS':  float(e.get('total_cogs', 0)),
        'Sales':       float(e.get('sales_value', 0)),
        'GP%':         float(e.get('estimated_gp_percent', 0)),
        'Go/No-Go':    e.get('go_no_go_result','—'),
        'Created':     e.get('created_date'),
    } for e in all_estimates])

    st.dataframe(
        hist_df,
        width="stretch",
        hide_index=True,
        column_config={
            'Total COGS': st.column_config.NumberColumn(format="%.0f"),
            'Sales':      st.column_config.NumberColumn(format="%.0f"),
            'GP%':        st.column_config.NumberColumn(format="%.1f%%"),
        }
    )

    # Activate a different version
    if len(all_estimates) > 1:
        st.divider()
        rev_opts = [f"Rev {e['estimate_version']} — {e.get('estimate_label','')}" for e in all_estimates]
        sel_rev  = st.selectbox("Activate a version", rev_opts)
        sel_est  = all_estimates[rev_opts.index(sel_rev)]
        if st.button("Activate Selected Version", type="secondary"):
            if activate_estimate(project_id, sel_est['id'], user_id):
                st.success(f"Rev {sel_est['estimate_version']} is now active.")
                st.cache_data.clear()
                st.rerun()