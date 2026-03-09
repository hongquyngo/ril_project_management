# pages/IL_2_📊_Estimate_GP.py
"""
Estimate GP — Pre-feasibility A→F formula + Go/No-Go decision.

Redesigned:
  - Sidebar: project selector, pre-fill from active estimate option
  - Tabbed COGS entry (A+B | C | D+E | F) — each with room for detail
  - Line-item calculator for A (equipment) and C (fabrication)
  - Attachment upload per estimate (S3)
  - Live preview always visible in right column
  - Better Active Estimate view with coefficient details
"""

import json
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
    ILProjectS3Manager,
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
    return df[['project_id', 'project_code', 'project_name', 'status']].copy() if not df.empty else df

@st.cache_data(ttl=300)
def _load_types():
    return get_project_types()

@st.cache_resource
def _get_s3():
    try:
        return ILProjectS3Manager()
    except Exception:
        return None

proj_df    = _load_projects()
proj_types = _load_types()
type_map   = {t['id']: t for t in proj_types}


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

st.title("📊 Estimate GP")

if proj_df.empty:
    st.warning("No projects found. Create a project first.")
    st.stop()

with st.sidebar:
    st.header("Project")
    proj_options = [f"{r.project_code} — {r.project_name}" for r in proj_df.itertuples()]
    sel_label    = st.selectbox("Select Project", proj_options, key="est_project")
    sel_idx      = proj_options.index(sel_label)
    project_id   = int(proj_df.iloc[sel_idx]['project_id'])
    project      = get_project(project_id)

    if not project:
        st.error("Project not found.")
        st.stop()

    pt = type_map.get(project.get('project_type_id', 0), {})
    st.caption(f"**Type:** {project.get('type_name', '—')}")
    st.caption(f"**Distance:** {project.get('site_distance_category', '—')}")
    st.caption(f"**Environment:** {project.get('environment_category', '—')}")
    st.caption(f"**Import:** {project.get('import_category', '—')}")

    st.divider()
    st.markdown("**Default Coefficients**")
    st.caption(f"α = {pt.get('default_alpha', 0.06)} | β = {pt.get('default_beta', 0.40)} | γ = {pt.get('default_gamma', 0.04)}")
    st.caption(f"GO ≥ {pt.get('gp_go_threshold', 25)}% | COND ≥ {pt.get('gp_conditional_threshold', 18)}%")

# Load estimates
all_estimates = get_estimates(project_id)
active_est    = next((e for e in all_estimates if e.get('is_active')), None)
next_version  = max((e['estimate_version'] for e in all_estimates), default=0) + 1

# Type defaults
def_alpha = float(pt.get('default_alpha', 0.06))
def_beta  = float(pt.get('default_beta', 0.40))
def_gamma = float(pt.get('default_gamma', 0.04))
go_thresh = float(pt.get('gp_go_threshold', 25))
cond_thr  = float(pt.get('gp_conditional_threshold', 18))


# ══════════════════════════════════════════════════════════════════════════════
# LINE-ITEM CALCULATOR — Session state based
# ══════════════════════════════════════════════════════════════════════════════

def _line_item_section(prefix: str, label: str, help_text: str = ""):
    """
    Render a line-item calculator. Items stored in session state.
    Returns (total_amount, notes_text).
    """
    ss_key = f"_items_{prefix}"
    if ss_key not in st.session_state:
        st.session_state[ss_key] = []

    items = st.session_state[ss_key]

    st.caption(f"💡 {help_text}" if help_text else "")

    # Display existing items
    if items:
        item_df = pd.DataFrame(items)
        st.dataframe(
            item_df, width="stretch", hide_index=True, height=min(35 * len(items) + 38, 250),
            column_config={
                'item':     st.column_config.TextColumn('Item Description', width=250),
                'qty':      st.column_config.NumberColumn('Qty', width=60),
                'unit':     st.column_config.TextColumn('Unit', width=60),
                'unit_price': st.column_config.NumberColumn('Unit Price', format="%.0f"),
                'amount':   st.column_config.NumberColumn('Amount', format="%.0f"),
                'supplier': st.column_config.TextColumn('Supplier/Quote Ref'),
            },
        )
        total = sum(i.get('amount', 0) for i in items)
        st.markdown(f"**Subtotal: {total:,.0f} VND** ({len(items)} items)")
    else:
        total = 0

    # Add new item
    with st.expander(f"➕ Add {label} item"):
        ic1, ic2, ic3 = st.columns([3, 1, 1])
        new_item = ic1.text_input("Description", key=f"{prefix}_desc", placeholder="e.g. Rack 1040x1340mm")
        new_qty  = ic2.number_input("Qty", value=1, min_value=1, key=f"{prefix}_qty")
        new_unit = ic3.text_input("Unit", value="Bộ", key=f"{prefix}_unit")

        ip1, ip2 = st.columns(2)
        new_price = ip1.number_input("Unit Price (VND)", value=0.0, min_value=0.0, format="%.0f", key=f"{prefix}_price")
        new_supplier = ip2.text_input("Supplier / Quote Ref", key=f"{prefix}_supplier",
                                       placeholder="e.g. Hải Long - QV25-3W")

        bc1, bc2 = st.columns(2)
        if bc1.button(f"✅ Add", key=f"{prefix}_add", use_container_width=True):
            if new_item and new_price > 0:
                st.session_state[ss_key].append({
                    'item': new_item, 'qty': new_qty, 'unit': new_unit,
                    'unit_price': new_price, 'amount': new_qty * new_price,
                    'supplier': new_supplier,
                })
                st.rerun()
            else:
                st.warning("Fill description and price.")
        if bc2.button("🗑 Clear all", key=f"{prefix}_clear", use_container_width=True):
            st.session_state[ss_key] = []
            st.rerun()

    # Build notes text from items
    notes_parts = []
    for i, item in enumerate(items, 1):
        notes_parts.append(f"{i}. {item['item']} x{item['qty']} @{item['unit_price']:,.0f} = {item['amount']:,.0f} [{item.get('supplier','')}]")
    notes_text = "; ".join(notes_parts) if notes_parts else ""

    return total, notes_text


# ══════════════════════════════════════════════════════════════════════════════
# TABS: New / Active / History
# ══════════════════════════════════════════════════════════════════════════════

tab_new, tab_active, tab_history = st.tabs(["📝 New Estimate", "✅ Active Estimate", "🗂 History"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — New Estimate
# ══════════════════════════════════════════════════════════════════════════════
with tab_new:
    st.markdown(f"**Project:** `{project['project_code']}` — {project['project_name']}")

    # ── Pre-fill option ──────────────────────────────────────────────────────
    prefill = {}
    if active_est:
        if st.checkbox("📋 Pre-fill from active estimate (Rev " +
                        str(active_est['estimate_version']) + ")", value=False, key="prefill_chk"):
            prefill = active_est

    st.divider()

    # ── Layout: form left, preview right ─────────────────────────────────────
    col_form, col_result = st.columns([3, 2])

    with col_form:
        # ── Header fields (outside category tabs, inside form) ───────────────
        with st.form("estimate_form"):
            hc1, hc2, hc3 = st.columns(3)
            label    = hc1.text_input("Estimate Label", value=f"Rev {next_version}")
            est_type = hc2.selectbox("Type", ["QUICK", "DETAILED"],
                                      index=1 if prefill.get('estimate_type') == 'DETAILED' else 0)
            sales_value = hc3.number_input("Sales Value (VND)",
                                            value=float(prefill.get('sales_value', 0) or 0),
                                            min_value=0.0, format="%.0f",
                                            help="Giá bán dự kiến cho khách hàng")

            # ── COGS Category Tabs ───────────────────────────────────────────
            cogs_tab_ab, cogs_tab_c, cogs_tab_de, cogs_tab_f = st.tabs([
                "📦 A+B Equipment & Logistics",
                "🔧 C Fabrication",
                "👷 D+E Labor & Travel",
                "🛡️ F Warranty",
            ])

            # ── A + B ────────────────────────────────────────────────────────
            with cogs_tab_ab:
                st.markdown("##### A — Equipment Cost")
                st.caption("Thiết bị, máy móc: AMR, charging station, PDA, SW license, IT hardware")
                a_cost = st.number_input("A: Equipment Total (VND)",
                                          value=float(prefill.get('a_equipment_cost', 0) or 0),
                                          min_value=0.0, format="%.0f",
                                          help="Tổng chi phí equipment. Nhập trực tiếp hoặc dùng line-item calculator bên dưới form")
                a_notes = st.text_area("Notes A — Chi tiết hạng mục / supplier / quote ref",
                                        value=prefill.get('a_equipment_notes') or '',
                                        height=80,
                                        placeholder="VD: 6 AMR VisionNav VNP15 @$18,500 = $111,000 [Q-VN-2026-001]; 3 charging @$2,100...")

                st.divider()
                st.markdown("##### B — Logistics & Import")
                st.caption("B = A × α (hoặc nhập thủ công)")
                ab1, ab2 = st.columns([1, 2])
                alpha = ab1.number_input("α (alpha)", value=float(prefill.get('alpha_rate', def_alpha) or def_alpha),
                                          min_value=0.0, max_value=1.0, format="%.4f",
                                          help="Domestic 3–5% | Imported 6–10%")
                b_manual = ab2.number_input("B Override (0 = formula)",
                                             value=0.0, min_value=0.0, format="%.0f",
                                             help="Nhập giá trị cụ thể nếu đã có báo giá forwarder")
                b_notes = st.text_input("Notes B", placeholder="VD: DHL quote #DHL-2026-123, CIF HCM $3,200")

            # ── C ────────────────────────────────────────────────────────────
            with cogs_tab_c:
                st.markdown("##### C — Custom Fabrication")
                st.caption("Gia công: trolley, rack, jig, frame — báo giá từ NCC nội địa")
                c_cost = st.number_input("C: Fabrication Total (VND)",
                                          value=float(prefill.get('c_custom_fabrication', 0) or 0),
                                          min_value=0.0, format="%.0f",
                                          help="Tổng chi phí gia công. Nhập trực tiếp hoặc dùng line-item calculator bên dưới form")
                c_notes = st.text_area("Notes C — Chi tiết hạng mục / NCC / báo giá",
                                        value=prefill.get('c_fabrication_notes') or '',
                                        height=80,
                                        placeholder="VD: 32 Rack 1040x1340mm @3,750,000 = 120,000,000 [Hải Long QV25-3W]; 18 trolley...")

            # ── D + E ────────────────────────────────────────────────────────
            with cogs_tab_de:
                st.markdown("##### D — Direct Labor")
                st.caption("D = Man-days × Day Rate × Team Size (hoặc override)")
                dd1, dd2, dd3 = st.columns(3)
                man_days  = dd1.number_input("Man-Days",
                                              value=int(prefill.get('d_man_days', 0) or 0),
                                              min_value=0, step=1,
                                              help=f"Benchmark {pt.get('code','')}: xem tab Benchmarks")
                day_rate  = dd2.number_input("Day Rate (VND)",
                                              value=float(prefill.get('d_man_day_rate', 1_500_000) or 1_500_000),
                                              min_value=0.0, format="%.0f",
                                              help="Engineer ~1.2M | PM ~2.1M | Senior ~1.5M")
                team_size = dd3.number_input("Team Size",
                                              value=float(prefill.get('d_team_size', 1.0) or 1.0),
                                              min_value=0.1, format="%.1f")
                d_manual  = st.number_input("D Override (0 = formula)",
                                             value=0.0, min_value=0.0, format="%.0f",
                                             help="Nhập tổng D nếu đã tính chi tiết bên ngoài")

                # Phase breakdown hint
                if man_days > 0:
                    st.caption(f"💡 Formula: {man_days} days × {day_rate:,.0f} VND × {team_size:.1f} team = **{man_days * day_rate * team_size:,.0f} VND**")

                st.divider()
                st.markdown("##### E — Travel & Site Overhead")
                st.caption("E = D × β (hoặc override). Gồm: vé máy bay, khách sạn, ăn uống, vận chuyển")
                ec1, ec2 = st.columns([1, 2])
                beta = ec1.number_input("β (beta)",
                                         value=float(prefill.get('beta_rate', def_beta) or def_beta),
                                         min_value=0.0, max_value=1.0, format="%.4f",
                                         help="LOCAL 30% | NEARBY 40% | FAR 50% | OVERSEAS 60%")
                e_manual = ec2.number_input("E Override (0 = formula)",
                                             value=0.0, min_value=0.0, format="%.0f")

            # ── F ────────────────────────────────────────────────────────────
            with cogs_tab_f:
                st.markdown("##### F — Warranty Reserve")
                st.caption("F = (A + C) × γ (hoặc override). Dự phòng sửa chữa, thay thế trong kỳ bảo hành")
                fc1, fc2 = st.columns([1, 2])
                gamma = fc1.number_input("γ (gamma)",
                                          value=float(prefill.get('gamma_rate', def_gamma) or def_gamma),
                                          min_value=0.0, max_value=1.0, format="%.4f",
                                          help="CLEAN env 2–3% | NORMAL 4% | HARSH 5%")
                f_manual = fc2.number_input("F Override (0 = formula)",
                                             value=0.0, min_value=0.0, format="%.0f")

            # ── Assessment notes + Submit ────────────────────────────────────
            st.divider()
            assessment_notes = st.text_area("Assessment Notes / Assumptions / Risks",
                                             value=prefill.get('assessment_notes') or '',
                                             height=80,
                                             placeholder="Giả định, rủi ro, điều kiện áp dụng...")

            submitted = st.form_submit_button("💾 Save & Activate", type="primary", use_container_width=True)

        # ── Line-item calculators (OUTSIDE form — interactive) ───────────────
        st.divider()
        st.subheader("📋 Line-Item Calculators")
        st.caption("Dùng calculator để tính chi tiết → copy tổng vào form bên trên. Notes sẽ tự động cập nhật khi Save.")

        li_tab_a, li_tab_c = st.tabs(["📦 A — Equipment Items", "🔧 C — Fabrication Items"])

        with li_tab_a:
            a_li_total, a_li_notes = _line_item_section(
                "equip", "equipment",
                "Liệt kê từng thiết bị: AMR, charging, PDA, software license..."
            )
            if a_li_total > 0:
                st.info(f"💡 Copy **{a_li_total:,.0f}** vào ô 'A: Equipment Total' ở form trên")

        with li_tab_c:
            c_li_total, c_li_notes = _line_item_section(
                "fab", "fabrication",
                "Liệt kê từng hạng mục gia công: rack, trolley, jig, frame..."
            )
            if c_li_total > 0:
                st.info(f"💡 Copy **{c_li_total:,.0f}** vào ô 'C: Fabrication Total' ở form trên")

        # ── Attachment upload (OUTSIDE form) ─────────────────────────────────
        st.divider()
        st.subheader("📎 Quotation Attachments")
        st.caption("Upload báo giá supplier, forwarder, NCC. Files lưu vào S3 dưới folder project.")
        uploaded_files = st.file_uploader(
            "Drag & drop quotation files",
            type=["pdf", "jpg", "jpeg", "png", "xlsx", "docx"],
            accept_multiple_files=True,
            key="est_attachments",
        )

    # ── Live preview (right column — always visible) ─────────────────────────
    with col_result:
        st.markdown("### 📐 Live Estimate")

        result = calculate_estimate(
            a_equipment=a_cost, alpha=alpha,
            c_fabrication=c_cost,
            man_days=man_days, man_day_rate=day_rate, team_size=team_size,
            beta=beta, gamma=gamma,
            sales_value=sales_value,
            b_override=b_manual if b_manual > 0 else None,
            d_override=d_manual if d_manual > 0 else None,
            e_override=e_manual if e_manual > 0 else None,
            f_override=f_manual if f_manual > 0 else None,
        )

        # COGS breakdown
        cogs_rows = []
        for key in ['a', 'b', 'c', 'd', 'e', 'f']:
            val = result.get(key, 0)
            pct = (val / result['total_cogs'] * 100) if result['total_cogs'] > 0 else 0
            cogs_rows.append({
                'Item': COGS_LABELS.get(key.upper(), key.upper()),
                'Amount': f"{val:,.0f}",
                '% COGS': f"{pct:.1f}%",
            })
        cogs_rows.append({
            'Item': '**TOTAL COGS**',
            'Amount': f"{result['total_cogs']:,.0f}",
            '% COGS': '100%',
        })

        st.dataframe(
            pd.DataFrame(cogs_rows), width="stretch", hide_index=True,
            column_config={
                'Item':   st.column_config.TextColumn('Item'),
                'Amount': st.column_config.TextColumn('Amount (VND)'),
                '% COGS': st.column_config.TextColumn('% COGS', width=80),
            }
        )

        st.divider()
        r1, r2 = st.columns(2)
        r1.metric("Sales",      fmt_vnd(result['sales']))
        r1.metric("Total COGS", fmt_vnd(result['total_cogs']))
        r2.metric("Gross Profit", fmt_vnd(result['gp']))
        r2.metric("GP%",          f"{result['gp_percent']:.1f}%")

        # Go/No-Go
        gng = get_go_no_go(result['gp_percent'], go_thresh, cond_thr)
        st.divider()
        if gng == 'GO':
            st.success(f"### ✅ GO  —  GP {result['gp_percent']:.1f}%")
        elif gng == 'CONDITIONAL':
            st.warning(f"### ⚠️ CONDITIONAL  —  GP {result['gp_percent']:.1f}%")
        else:
            st.error(f"### ❌ NO-GO  —  GP {result['gp_percent']:.1f}%")
        st.caption(f"Thresholds: GO ≥ {go_thresh}%  |  CONDITIONAL ≥ {cond_thr}%")

        # Coefficients used
        st.divider()
        st.caption("**Coefficients used in this estimate:**")
        cc1, cc2, cc3 = st.columns(3)
        cc1.caption(f"α = {alpha:.4f}" + (" *(override)*" if b_manual > 0 else ""))
        cc2.caption(f"β = {beta:.4f}" + (" *(override)*" if e_manual > 0 else ""))
        cc3.caption(f"γ = {gamma:.4f}" + (" *(override)*" if f_manual > 0 else ""))

    # ── Save logic ───────────────────────────────────────────────────────────
    if submitted:
        if a_cost <= 0 and c_cost <= 0 and sales_value <= 0:
            st.warning("Enter at least one cost component and Sales Value.")
        else:
            # Merge line-item notes into notes fields
            final_a_notes = a_notes.strip()
            if a_li_notes and a_li_notes not in final_a_notes:
                final_a_notes = (final_a_notes + " | " + a_li_notes).strip(" | ")
            final_c_notes = c_notes.strip() if isinstance(c_notes, str) else ''
            if c_li_notes and c_li_notes not in final_c_notes:
                final_c_notes = (final_c_notes + " | " + c_li_notes).strip(" | ")

            # Merge B notes into assessment if exists
            full_assessment = assessment_notes or ''
            if b_notes:
                full_assessment = f"[B] {b_notes}\n{full_assessment}".strip()

            gng_save = get_go_no_go(result['gp_percent'], go_thresh, cond_thr)
            est_data = {
                'project_id': project_id,
                'estimate_version': next_version,
                'estimate_label': label,
                'estimate_type': est_type,
                'a_equipment_cost': a_cost,
                'a_equipment_notes': final_a_notes[:500] if final_a_notes else None,
                'alpha_rate': alpha,
                'b_logistics_import': result['b'],
                'b_override': 1 if b_manual > 0 else 0,
                'c_custom_fabrication': c_cost,
                'c_fabrication_notes': final_c_notes[:500] if final_c_notes else None,
                'd_man_days': man_days,
                'd_man_day_rate': day_rate,
                'd_team_size': team_size,
                'd_direct_labor': result['d'],
                'd_override': 1 if d_manual > 0 else 0,
                'beta_rate': beta,
                'e_travel_site_oh': result['e'],
                'e_override': 1 if e_manual > 0 else 0,
                'gamma_rate': gamma,
                'f_warranty_reserve': result['f'],
                'f_override': 1 if f_manual > 0 else 0,
                'total_cogs': result['total_cogs'],
                'sales_value': result['sales'],
                'estimated_gp': result['gp'],
                'estimated_gp_percent': result['gp_percent'],
                'go_no_go_result': gng_save,
                'assessment_notes': full_assessment or None,
            }
            try:
                new_id = create_estimate(est_data, user_id)
                activate_estimate(project_id, new_id, user_id)

                # Upload attachments to S3
                if uploaded_files:
                    s3 = _get_s3()
                    if s3:
                        for f in uploaded_files:
                            ok, key = s3.upload_project_file(f.read(), f.name, project_id)
                            if ok:
                                logger.info(f"Uploaded estimate attachment: {key}")
                            else:
                                st.warning(f"Upload failed for {f.name}: {key}")

                st.success(f"✅ Estimate Rev {next_version} saved and activated!")
                # Clear line-item session state
                st.session_state.pop("_items_equip", None)
                st.session_state.pop("_items_fab", None)
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

    # Header
    gng_active = active_est.get('go_no_go_result', '')
    hc1, hc2 = st.columns([4, 1])
    hc1.markdown(f"### Rev {active_est['estimate_version']} — {active_est.get('estimate_label', '')}")
    if gng_active == 'GO':
        hc2.success(f"✅ GO")
    elif gng_active == 'CONDITIONAL':
        hc2.warning(f"⚠️ COND")
    elif gng_active == 'NO_GO':
        hc2.error(f"❌ NO-GO")

    # KPIs
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Sales Value",  fmt_vnd(active_est.get('sales_value')))
    mc2.metric("Total COGS",   fmt_vnd(active_est.get('total_cogs')))
    mc3.metric("Gross Profit",  fmt_vnd(active_est.get('estimated_gp')))
    mc4.metric("GP%",           fmt_percent(active_est.get('estimated_gp_percent')))

    st.divider()

    # Detailed breakdown
    col_table, col_detail = st.columns([3, 2])

    with col_table:
        rows = []
        field_map = {
            'A': 'a_equipment_cost', 'B': 'b_logistics_import',
            'C': 'c_custom_fabrication', 'D': 'd_direct_labor',
            'E': 'e_travel_site_oh', 'F': 'f_warranty_reserve',
        }
        total_cogs = float(active_est.get('total_cogs', 0) or 0)
        for k, fld in field_map.items():
            amt = float(active_est.get(fld, 0) or 0)
            pct = (amt / total_cogs * 100) if total_cogs > 0 else 0
            rows.append({
                'Item': COGS_LABELS[k],
                'Amount': f"{amt:,.0f}",
                '% COGS': f"{pct:.1f}%",
                'Override': '✏️' if active_est.get(f'{k.lower()}_override') else '',
            })
        rows.append({
            'Item': '**TOTAL COGS**',
            'Amount': f"{total_cogs:,.0f}",
            '% COGS': '100%',
            'Override': '',
        })

        st.dataframe(
            pd.DataFrame(rows), width="stretch", hide_index=True,
            column_config={
                'Item':     st.column_config.TextColumn('Item'),
                'Amount':   st.column_config.TextColumn('Amount (VND)'),
                '% COGS':   st.column_config.TextColumn('% COGS', width=80),
                'Override': st.column_config.TextColumn('', width=30),
            }
        )

    with col_detail:
        st.markdown("**Coefficients & Parameters**")
        st.caption(f"α (logistics) = {active_est.get('alpha_rate', '—')}")
        st.caption(f"β (travel)    = {active_est.get('beta_rate', '—')}")
        st.caption(f"γ (warranty)  = {active_est.get('gamma_rate', '—')}")
        st.caption(f"Man-days      = {active_est.get('d_man_days', '—')}")
        st.caption(f"Day rate      = {fmt_vnd(active_est.get('d_man_day_rate'))}")
        st.caption(f"Team size     = {active_est.get('d_team_size', '—')}")
        st.caption(f"Type          = {active_est.get('estimate_type', '—')}")

    # Notes
    if active_est.get('a_equipment_notes'):
        st.info(f"📦 **A Notes:** {active_est['a_equipment_notes']}")
    if active_est.get('c_fabrication_notes'):
        st.info(f"🔧 **C Notes:** {active_est['c_fabrication_notes']}")
    if active_est.get('assessment_notes'):
        st.info(f"📝 **Assessment:** {active_est['assessment_notes']}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — History
# ══════════════════════════════════════════════════════════════════════════════
with tab_history:
    if not all_estimates:
        st.info("No estimates yet.")
        st.stop()

    hist_rows = []
    for e in all_estimates:
        est_total = float(e.get('total_cogs', 0) or 0)
        sales_total = float(e.get('sales_value', 0) or 0)
        hist_rows.append({
            'Active': '✅' if e.get('is_active') else '',
            'Rev':    e['estimate_version'],
            'Label':  e.get('estimate_label', ''),
            'Type':   e.get('estimate_type', ''),
            'COGS':   f"{est_total:,.0f}",
            'Sales':  f"{sales_total:,.0f}",
            'GP%':    fmt_percent(e.get('estimated_gp_percent')),
            'Go/No-Go': e.get('go_no_go_result', '—'),
            'α':      e.get('alpha_rate', ''),
            'β':      e.get('beta_rate', ''),
            'γ':      e.get('gamma_rate', ''),
            'Created': e.get('created_date'),
        })

    st.dataframe(
        pd.DataFrame(hist_rows), width="stretch", hide_index=True,
        column_config={
            'Active':   st.column_config.TextColumn('', width=30),
            'Rev':      st.column_config.NumberColumn('Rev', width=50),
            'COGS':     st.column_config.TextColumn('Total COGS'),
            'Sales':    st.column_config.TextColumn('Sales'),
            'GP%':      st.column_config.TextColumn('GP%', width=70),
            'Go/No-Go': st.column_config.TextColumn('Result', width=100),
            'α':        st.column_config.NumberColumn('α', format="%.4f", width=70),
            'β':        st.column_config.NumberColumn('β', format="%.4f", width=70),
            'γ':        st.column_config.NumberColumn('γ', format="%.4f", width=70),
        }
    )

    # Activate a different version
    if len(all_estimates) > 1:
        st.divider()
        rev_opts = [f"Rev {e['estimate_version']} — {e.get('estimate_label', '')}" for e in all_estimates]
        sel_rev  = st.selectbox("Activate a version", rev_opts)
        sel_est  = all_estimates[rev_opts.index(sel_rev)]
        if st.button("Activate Selected Version", type="secondary"):
            if activate_estimate(project_id, sel_est['id'], user_id):
                st.success(f"Rev {sel_est['estimate_version']} is now active.")
                st.cache_data.clear()
                st.rerun()