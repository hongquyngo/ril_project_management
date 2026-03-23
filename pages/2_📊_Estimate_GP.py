# pages/2_📊_Estimate_GP.py
"""
Estimate GP — A→F formula + Go/No-Go + Product/Costbook integration.
Products from DB catalog, cost from Costbooks (vendor quotes), sell from Quotations.
Line items persisted to il_estimate_line_items table.
"""
import streamlit as st
import pandas as pd
import logging
from utils.auth import AuthManager
from utils.il_project import (
    get_projects_df, get_project,
    get_estimates, get_active_estimate, create_estimate, activate_estimate,
    get_project_types, calculate_estimate, get_go_no_go, fmt_vnd, fmt_percent,
    COGS_LABELS, ILProjectS3Manager,
    search_products, get_costbook_for_product, get_quotation_for_product,
    get_estimate_line_items, create_estimate_line_item, delete_estimate_line_item,
    get_costbook_products_for_import, get_active_costbooks,
    get_rate_to_vnd,
    create_estimate_media, get_estimate_medias, delete_estimate_media,
    create_line_item_media, get_line_item_medias,
)
logger = logging.getLogger(__name__)
auth = AuthManager()
st.set_page_config(page_title="Estimate GP", page_icon="📊", layout="wide")
auth.require_auth()
user_id = str(auth.get_user_id())
user_role = st.session_state.get('user_role', '')
is_admin = auth.is_admin()
emp_int_id = st.session_state.get('employee_id')

from utils.il_project.permissions import PermissionContext, get_role_badge
ctx = PermissionContext(employee_id=emp_int_id, is_admin=is_admin, user_role=user_role)

@st.cache_data(ttl=300)
def _load_projects():
    df = get_projects_df()
    return df[['project_id','project_code','project_name','status']].copy() if not df.empty else df
@st.cache_data(ttl=300)
def _load_types():
    return get_project_types()
proj_df = _load_projects()
proj_types = _load_types()
type_map = {t['id']: t for t in proj_types}

@st.cache_data(ttl=60, show_spinner=False)
def _cached_estimates(project_id: int, _v: int = 0):
    return get_estimates(project_id)

def _invalidate_estimates():
    st.session_state['_est_v'] = st.session_state.get('_est_v', 0) + 1

@st.cache_resource
def _get_s3():
    try:
        return ILProjectS3Manager()
    except Exception:
        return None

# ── Sidebar ──────────────────────────────────────────────────────────────────
st.title("📊 Estimate GP")
if proj_df.empty:
    st.warning("No projects found."); st.stop()
with st.sidebar:
    st.header("Project")
    proj_options = [f"{r.project_code} — {r.project_name}" for r in proj_df.itertuples()]
    sel_label = st.selectbox("Select Project", proj_options, key="est_project")
    project_id = int(proj_df.iloc[proj_options.index(sel_label)]['project_id'])
    project = get_project(project_id)
    if not project: st.error("Project not found."); st.stop()
    pt = type_map.get(project.get('project_type_id', 0), {})
    st.caption(f"**Type:** {project.get('type_name','—')} | **Customer:** {project.get('customer_name','—')}")
    st.caption(f"**Distance:** {project.get('site_distance_category','—')} | **Env:** {project.get('environment_category','—')}")
    st.divider()
    st.caption(f"α={pt.get('default_alpha',0.06)} β={pt.get('default_beta',0.40)} γ={pt.get('default_gamma',0.04)}")
    st.caption(f"GO ≥{pt.get('gp_go_threshold',25)}% | COND ≥{pt.get('gp_conditional_threshold',18)}%")
    st.divider()
    st.caption(f"Role: {get_role_badge(ctx.role(project_id))}")

# ── Page-level access check ──────────────────────────────────────────────────
if not ctx.can('estimate.view', project_id):
    st.warning("⛔ Bạn không có quyền xem Estimate của dự án này.")
    st.stop()

_can_view_costs = ctx.can('estimate.view_costs', project_id)
_can_create     = ctx.can('estimate.create', project_id)
_can_activate   = ctx.can('estimate.activate', project_id)

all_estimates = _cached_estimates(project_id, _v=st.session_state.get('_est_v', 0))
active_est = next((e for e in all_estimates if e.get('is_active')), None)
next_version = max((e['estimate_version'] for e in all_estimates), default=0) + 1
def_alpha = float(pt.get('default_alpha', 0.06))
def_beta = float(pt.get('default_beta', 0.40))
def_gamma = float(pt.get('default_gamma', 0.04))
go_thresh = float(pt.get('gp_go_threshold', 25))
cond_thr = float(pt.get('gp_conditional_threshold', 18))

# ── Session state items ──────────────────────────────────────────────────────
if "_est_items" not in st.session_state:
    st.session_state["_est_items"] = []

# Track project_id — clear line items when user switches project
if st.session_state.get("_est_project_id") != project_id:
    st.session_state["_est_items"] = []
    st.session_state["_est_project_id"] = project_id
    st.session_state["_prefill_loaded"] = False

def _sanitize_item(item: dict) -> dict:
    """Clean pandas NaN/NaT → None so MySQL doesn't choke.
    Called when loading items from DataFrame (active estimate prefill)
    and before saving to DB."""
    import math
    clean = {}
    for k, v in item.items():
        if isinstance(v, float) and math.isnan(v):
            clean[k] = None
        elif hasattr(v, 'isoformat'):  # pd.Timestamp / NaT
            try:
                if pd.isna(v):
                    clean[k] = None
                else:
                    clean[k] = v
            except (TypeError, ValueError):
                clean[k] = v
        else:
            try:
                if pd.isna(v):
                    clean[k] = None
                    continue
            except (TypeError, ValueError):
                pass
            clean[k] = v
    return clean

def _add_item(item): st.session_state["_est_items"].append(_sanitize_item(item))
def _remove_item(idx):
    if 0 <= idx < len(st.session_state["_est_items"]):
        st.session_state["_est_items"].pop(idx)
def _clear_items(): st.session_state["_est_items"] = []
def _update_item(idx, item):
    if 0 <= idx < len(st.session_state["_est_items"]):
        st.session_state["_est_items"][idx] = _sanitize_item(item)
def _items_total(cat=None):
    items = st.session_state["_est_items"]
    if cat: items = [i for i in items if i.get('cogs_category') == cat]
    return sum(i.get('quantity',0)*i.get('unit_cost',0)*i.get('cost_exchange_rate',1) for i in items)
def _items_sell_total():
    return sum(i.get('quantity',0)*i.get('unit_sell',0)*i.get('sell_exchange_rate',1) for i in st.session_state["_est_items"])

def _show_rate(col, label: str, rate_result) -> float:
    """Display exchange rate with source badge. Returns the rate value."""
    _badges = {
        'same': ('ℹ️', 'Same currency'),
        'api': ('🟢', 'Live'),
        'cache': ('🟢', 'Live (cached)'),
        'db': ('🔵', 'DB'),
        'fallback': ('🟠', 'Fallback'),
    }
    icon, src = _badges.get(rate_result.source, ('⚪', rate_result.source))
    col.metric(label, f"{rate_result.rate:,.2f}")
    col.caption(f"{icon} {src}")
    return rate_result.rate

# ── Dialog: Add Product ──────────────────────────────────────────────────────
@st.dialog("🔍 Add Product from Catalog", width="large")
def _dialog_add_product(category):
    is_svc = category == 'SERVICE'
    products = search_products('', is_service=is_svc if is_svc else None, limit=99999)
    if not products: st.info("No products found."); return
    prod_opts = [f"{p['pt_code']} — {p['name']} [{p.get('brand_name','')}]" for p in products]
    sel_prod = st.selectbox("🔍 Select Product", prod_opts)
    product = products[prod_opts.index(sel_prod)]
    st.caption(f"UOM: {product.get('uom','—')} | Brand: {product.get('brand_name','—')}")
    st.divider()
    st.markdown("**💰 Vendor Cost (Costbook)**")
    cb_entries = get_costbook_for_product(product['id'])
    cb = None; _r_cost = None
    if cb_entries:
        cb_opts = [f"{c['costbook_number']} | {c['vendor_name']} | {c['unit_price']:,.2f} {c['currency_code']} [{c['status']}]" for c in cb_entries]
        cb = cb_entries[cb_opts.index(st.selectbox("Costbook Entry", cb_opts))]
        _r_cost = get_rate_to_vnd(cb['currency_code'])
    else:
        st.warning("No costbook found. Enter cost manually below.")
    st.divider()
    st.markdown("**📤 Selling Price (Quotation, optional)**")
    quot_entries = get_quotation_for_product(product['id'], customer_id=project.get('customer_id'))
    sel_qd = None
    if quot_entries:
        qt_opts = ["(Skip)"] + [f"{q['quotation_number']} | {q['customer_name']} | {q['selling_unit_price']:,.2f} {q['currency_code']}" for q in quot_entries]
        sel_qt = st.selectbox("Quotation Entry", qt_opts)
        if sel_qt != "(Skip)": sel_qd = quot_entries[qt_opts.index(sel_qt)-1]
    st.divider()
    qc1, qc2, qc3 = st.columns(3)
    qty = qc1.number_input("Quantity", value=1.0, min_value=0.01, format="%.2f")
    cost_price = float(cb['unit_price'] if cb else 0)
    cost_cur = cb['currency_code'] if cb else 'VND'
    if _r_cost:
        cost_rate = _show_rate(qc2, f"Cost Rate ({cost_cur}→VND)", _r_cost)
    else:
        cost_rate = 1.0
        qc2.metric(f"Cost Rate ({cost_cur}→VND)", "1.00")
    sell_price = float(sel_qd['selling_unit_price'] if sel_qd else 0)
    sell_cur = sel_qd['currency_code'] if sel_qd else 'VND'
    if sel_qd:
        _r_sell = get_rate_to_vnd(sell_cur)
        sell_rate = _show_rate(qc3, f"Sell Rate ({sell_cur}→VND)", _r_sell)
    else:
        sell_rate = 1.0
        qc3.metric(f"Sell Rate ({sell_cur}→VND)", "1.00")
    if not cb:
        mc1, mc2 = st.columns(2)
        cost_price = mc1.number_input("Manual Cost", value=0.0, format="%.2f")
        cost_cur = mc2.text_input("Currency", value="VND")
        if cost_cur != 'VND':
            r2 = get_rate_to_vnd(cost_cur)
            cost_rate = r2.rate if r2.ok else 1.0
            _badges = {'api': '🟢 Live', 'cache': '🟢 Live (cached)', 'db': '🔵 DB', 'fallback': '🟠 Fallback'}
            st.caption(f"💱 1 {cost_cur} = **{cost_rate:,.2f}** VND — {_badges.get(r2.source, r2.source)}")
        else:
            cost_rate = 1.0
    cost_vnd = qty*cost_price*cost_rate
    sell_vnd = qty*sell_price*sell_rate
    pc1, pc2, pc3 = st.columns(3)
    pc1.metric("Cost VND", fmt_vnd(cost_vnd))
    pc2.metric("Sell VND", fmt_vnd(sell_vnd) if sell_vnd > 0 else '—')
    pc3.metric("Item GP%", f"{(sell_vnd-cost_vnd)/sell_vnd*100:.1f}%" if sell_vnd > 0 else '—')
    notes = st.text_input("Notes", placeholder="Optional")
    att_file = st.file_uploader("📎 Attach vendor quote (optional)",
                                 type=["pdf","jpg","jpeg","png","xlsx","docx"], key="li_att")
    if st.button("✅ Add to Estimate", type="primary", use_container_width=True):
        # Store file bytes in session for later S3 upload on save
        att_data = None
        if att_file:
            att_data = {'bytes': att_file.read(), 'name': att_file.name}
        _add_item({
            'cogs_category': category, 'product_id': product['id'],
            'item_description': product['name'], 'brand_name': product.get('brand_name',''),
            'pt_code': product.get('pt_code',''),
            'costbook_detail_id': cb['costbook_detail_id'] if cb else None,
            'vendor_name': cb['vendor_name'] if cb else '',
            'vendor_quote_ref': cb.get('vendor_quote_number','') if cb else '',
            'costbook_number': cb['costbook_number'] if cb else '',
            'unit_cost': cost_price, 'cost_currency_code': cost_cur,
            'cost_currency_id': cb['currency_id'] if cb else None, 'cost_exchange_rate': cost_rate,
            'quotation_detail_id': sel_qd['quotation_detail_id'] if sel_qd else None,
            'unit_sell': sell_price, 'sell_currency_code': sell_cur,
            'sell_currency_id': sel_qd['currency_id'] if sel_qd else None, 'sell_exchange_rate': sell_rate,
            'quantity': qty, 'uom': product.get('uom','Pcs'), 'notes': notes or None,
            '_attachment': att_data,
        })
        st.success(f"✅ Added {product['name']} × {qty}"); st.rerun()

@st.dialog("📦 Import from Costbook", width="large")
def _dialog_import_costbook(category):
    costbooks = get_active_costbooks()
    if not costbooks: st.warning("No costbooks."); return
    cb_opts = [f"{c['costbook_number']} | {c['vendor_name']} | {c['line_count']} items [{c['status']}]" for c in costbooks]
    cb = costbooks[cb_opts.index(st.selectbox("Costbook", cb_opts))]
    products = get_costbook_products_for_import(cb['id'])
    if not products: st.info("No products."); return
    st.markdown(f"**{len(products)} products** from {cb['vendor_name']}")
    preview = pd.DataFrame([{'Product': p['product_name'][:40], 'Code': p['pt_code'],
        'Price': f"{p['unit_price']:,.2f}" if p.get('unit_price') else '—', 'CCY': p.get('currency_code','')}
        for p in products])
    st.dataframe(preview, width="stretch", hide_index=True, height=min(35*len(products)+38, 300))
    cur_code = products[0].get('currency_code','USD') if products else 'USD'
    _r_cb = get_rate_to_vnd(cur_code)
    exc_rate = _show_rate(st, f"Rate ({cur_code}→VND)", _r_cb)
    if st.button(f"📦 Import {len(products)} items", type="primary", use_container_width=True):
        for p in products:
            cat = 'SERVICE' if p.get('is_service') else category
            _add_item({'cogs_category': cat, 'product_id': p['product_id'],
                'item_description': p['product_name'], 'brand_name': p.get('brand_name',''),
                'pt_code': p.get('pt_code',''),
                'costbook_detail_id': p['costbook_detail_id'], 'vendor_name': p.get('vendor_name',''),
                'vendor_quote_ref': p.get('vendor_quote_number',''), 'costbook_number': p.get('costbook_number',''),
                'unit_cost': float(p.get('unit_price',0) or 0), 'cost_currency_code': p.get('currency_code',''),
                'cost_currency_id': p.get('currency_id'), 'cost_exchange_rate': exc_rate,
                'quotation_detail_id': None, 'unit_sell': 0, 'sell_currency_code': '',
                'sell_currency_id': None, 'sell_exchange_rate': 1.0,
                'quantity': 1, 'uom': p.get('uom','Pcs'), 'notes': None})
        st.success(f"✅ Imported {len(products)} items!"); st.rerun()

# ── Dialog: Edit Line Item ───────────────────────────────────────────────────
@st.dialog("✏️ Edit Line Item", width="large")
def _dialog_edit_item(idx):
    items = st.session_state["_est_items"]
    if idx < 0 or idx >= len(items):
        st.error("Item not found."); return
    it = items[idx].copy()

    st.markdown(f"**{it.get('item_description', '—')}**")
    if it.get('pt_code'):
        st.caption(f"Code: {it['pt_code']} | Brand: {it.get('brand_name', '—')}")

    ec1, ec2 = st.columns(2)
    cat_opts = ['A', 'C', 'SERVICE']
    cat_idx = cat_opts.index(it.get('cogs_category', 'A')) if it.get('cogs_category') in cat_opts else 0
    new_cat = ec1.selectbox("Category", cat_opts, index=cat_idx, key="edit_cat")
    new_desc = ec2.text_input("Description", value=it.get('item_description', ''), key="edit_desc")

    eq1, eq2, eq3 = st.columns(3)
    new_qty = eq1.number_input("Quantity", value=float(it.get('quantity', 1)), min_value=0.01, format="%.2f", key="edit_qty")
    new_cost = eq2.number_input("Unit Cost", value=float(it.get('unit_cost', 0)), format="%.2f", key="edit_cost")
    new_ccy = eq3.text_input("Cost Currency", value=it.get('cost_currency_code', 'VND'), key="edit_ccy")

    # Auto-fetch cost rate from currency
    _r_edit_cost = get_rate_to_vnd(new_ccy)
    new_cost_rate = _r_edit_cost.rate if _r_edit_cost.ok else float(it.get('cost_exchange_rate', 1))

    er1, er2 = st.columns(2)
    _show_rate(er1, f"Cost Rate ({new_ccy}→VND)", _r_edit_cost)
    new_vendor = er2.text_input("Vendor", value=it.get('vendor_name', '') or '', key="edit_vendor")

    st.divider()
    sell_ccy = it.get('sell_currency_code', 'VND') or 'VND'
    es1, es2, es3 = st.columns(3)
    new_sell = es1.number_input("Unit Sell", value=float(it.get('unit_sell', 0)), format="%.2f", key="edit_sell")
    new_sell_ccy = es2.text_input("Sell Currency", value=sell_ccy, key="edit_sell_ccy")

    # Auto-fetch sell rate from currency
    _r_edit_sell = get_rate_to_vnd(new_sell_ccy)
    new_sell_rate = _r_edit_sell.rate if _r_edit_sell.ok else float(it.get('sell_exchange_rate', 1))
    _show_rate(es3, f"Sell Rate ({new_sell_ccy}→VND)", _r_edit_sell)

    new_notes = st.text_input("Notes", value=it.get('notes', '') or '', key="edit_notes")

    cost_vnd = new_qty * new_cost * new_cost_rate
    sell_vnd = new_qty * new_sell * new_sell_rate
    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("Cost VND", fmt_vnd(cost_vnd))
    mc2.metric("Sell VND", fmt_vnd(sell_vnd) if sell_vnd > 0 else '—')
    mc3.metric("Item GP%", f"{(sell_vnd - cost_vnd) / sell_vnd * 100:.1f}%" if sell_vnd > 0 else '—')

    bc1, bc2 = st.columns(2)
    if bc1.button("💾 Save Changes", type="primary", use_container_width=True, key="edit_save"):
        it['cogs_category'] = new_cat
        it['item_description'] = new_desc
        it['quantity'] = new_qty
        it['unit_cost'] = new_cost
        it['cost_currency_code'] = new_ccy
        it['cost_exchange_rate'] = new_cost_rate
        it['vendor_name'] = new_vendor
        it['unit_sell'] = new_sell
        it['sell_currency_code'] = new_sell_ccy
        it['sell_exchange_rate'] = new_sell_rate
        it['notes'] = new_notes or None
        _update_item(idx, it)
        st.success("✅ Updated!")
        st.rerun()
    if bc2.button("✖ Cancel", use_container_width=True, key="edit_cancel"):
        st.rerun()

# ── Tabs ─────────────────────────────────────────────────────────────────────
tab_new, tab_active, tab_history = st.tabs(["📝 New Estimate", "✅ Active Estimate", "🗂 History"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — New Estimate
# ══════════════════════════════════════════════════════════════════════════════
with tab_new:
    if not _can_create:
        st.info("⛔ Bạn không có quyền tạo estimate cho dự án này. Chỉ PM, SA/Senior, hoặc Admin.")
        st.caption("Chuyển sang tab **Active Estimate** để xem estimate hiện tại.")
    st.markdown(f"**Project:** `{project['project_code']}` — {project['project_name']}")
    prefill = {}
    if active_est:
        # Auto-load coefficients + line items from active estimate by default
        # so users can add/remove items incrementally without losing existing data
        start_fresh = st.checkbox(
            "🔄 Start from scratch (ignore active estimate)",
            value=False, key="prefill_fresh_chk",
            help="Uncheck = build on current active estimate (coefficients + line items carried over). Check = start with empty slate."
        )
        if not start_fresh:
            prefill = active_est
            if not st.session_state["_est_items"]:
                existing = get_estimate_line_items(active_est['id'])
                if not existing.empty:
                    for _, row in existing.iterrows(): _add_item(row.to_dict())
                    st.toast(f"📋 Loaded {len(existing)} items from Rev {active_est['estimate_version']}")
        else:
            # User explicitly chose fresh start — clear if items were auto-loaded
            if st.session_state.get("_prefill_loaded"):
                _clear_items()
            st.session_state["_prefill_loaded"] = False
        if not start_fresh:
            st.session_state["_prefill_loaded"] = True
    st.divider()
    col_form, col_result = st.columns([3, 2])
    with col_form:
        # ── Section 1: Line Items ────────────────────────────────────────
        st.subheader("① Line Items")
        if not _can_create:
            pass  # Buttons hidden — read-only mode
        else:
            b1, b2, b3, b4 = st.columns(4)
            if b1.button("🔍 Equipment (A)", use_container_width=True,
                          help="Add equipment/hardware products from the product catalog (COGS category A)"):
                _dialog_add_product("A")
            if b2.button("🔧 Fabrication (C)", use_container_width=True,
                          help="Add custom fabrication items — metalwork, racking, wiring (COGS category C)"):
                _dialog_add_product("C")
            if b3.button("📦 Import Costbook", use_container_width=True,
                          help="Bulk import all products from a vendor costbook"):
                _dialog_import_costbook("A")
            if b4.button("🗑 Clear All", use_container_width=True,
                         help="Remove all line items"): _clear_items(); st.rerun()
        items = st.session_state["_est_items"]
        if items:
            rows = []
            for i, it in enumerate(items):
                cv = it.get('quantity',0)*it.get('unit_cost',0)*it.get('cost_exchange_rate',1)
                rows.append({'📎': '📎' if it.get('_attachment') else '', '#': i+1, 'Cat': it.get('cogs_category',''), 'Product': (it.get('item_description','') or '')[:35],
                    'Vendor': (it.get('vendor_name','') or '')[:20], 'Qty': it.get('quantity',0),
                    'Cost': f"{it.get('unit_cost',0):,.2f}", 'CCY': it.get('cost_currency_code',''),
                    'Total VND': f"{cv:,.0f}", 'Ref': (it.get('costbook_number','') or '')[:15]})
            tbl_key = f"li_tbl_{st.session_state.get('_li_key',0)}"
            event = st.dataframe(pd.DataFrame(rows), key=tbl_key, width="stretch", hide_index=True,
                on_select="rerun", selection_mode="single-row",
                column_config={'#': st.column_config.NumberColumn('#', width=35),
                    'Cat': st.column_config.TextColumn('', width=30), 'Qty': st.column_config.NumberColumn('Qty', format="%.1f", width=55)})
            sel = event.selection.rows
            if sel:
                sc1, sc2, sc3 = st.columns(3)
                if sc1.button("✏️ Edit", type="primary", use_container_width=True):
                    _dialog_edit_item(sel[0])
                if sc2.button("🗑 Remove", use_container_width=True):
                    _remove_item(sel[0]); st.session_state["_li_key"] = st.session_state.get("_li_key",0)+1; st.rerun()
                if sc3.button("✖ Deselect", use_container_width=True):
                    st.session_state["_li_key"] = st.session_state.get("_li_key",0)+1; st.rerun()
            a_total = _items_total('A'); c_total = _items_total('C')
            st.caption(f"**A (Equipment):** {a_total:,.0f} ₫ &nbsp;|&nbsp; **C (Fabrication):** {c_total:,.0f} ₫ &nbsp;|&nbsp; **Sell Total:** {_items_sell_total():,.0f} ₫")
        else:
            a_total = c_total = 0
            st.info("No items yet. Add from catalog or import costbook.")
        if _can_create:
            with st.expander("✏️ Manual item (not in catalog)"):
                mc1, mc2 = st.columns(2)
                m_cat = mc1.selectbox("Category", ["A","C","SERVICE"], key="m_cat",
                                       help="A = Equipment, C = Fabrication, SERVICE = Service items")
                m_desc = mc2.text_input("Description *", key="m_desc")
                md1, md2, md3 = st.columns(3)
                m_qty = md1.number_input("Qty", value=1.0, min_value=0.01, format="%.2f", key="m_qty")
                m_price = md2.number_input("Unit Cost (VND)", value=0.0, format="%.0f", key="m_price")
                m_vendor = md3.text_input("Vendor", key="m_vendor")
                if st.button("➕ Add manual", key="m_add", use_container_width=True):
                    if m_desc and m_price > 0:
                        _add_item({'cogs_category': m_cat, 'product_id': None, 'item_description': m_desc,
                            'brand_name': '', 'pt_code': '', 'costbook_detail_id': None, 'vendor_name': m_vendor,
                            'vendor_quote_ref': '', 'costbook_number': '', 'unit_cost': m_price,
                            'cost_currency_code': 'VND', 'cost_currency_id': None, 'cost_exchange_rate': 1.0,
                            'quotation_detail_id': None, 'unit_sell': 0, 'sell_currency_code': '',
                            'sell_currency_id': None, 'sell_exchange_rate': 1.0,
                            'quantity': m_qty, 'uom': 'Pcs', 'notes': None})
                        st.rerun()

        # ── Section 2: Coefficients & Formula ────────────────────────────
        st.divider()
        with st.form("estimate_form"):
            st.subheader("② COGS Formula")
            hc1, hc2, hc3 = st.columns(3)
            label = hc1.text_input("Label", value=f"Rev {next_version}",
                                    help="Short name for this estimate revision")
            est_type = hc2.selectbox("Type", ["QUICK","DETAILED"], index=1 if prefill.get('estimate_type')=='DETAILED' else 0,
                                      help="QUICK = rough estimate, DETAILED = full breakdown with line items")
            sales_value = hc3.number_input("Sales Value (VND)", value=float(prefill.get('sales_value',0) or 0), format="%.0f",
                                            help="Contract value in VND. Set 0 to use total Sell from line items.")

            st.divider()
            st.markdown("**A — Equipment &nbsp;&nbsp;|&nbsp;&nbsp; C — Fabrication**")
            st.caption("Leave 0 to use totals from line items above. Override to enter a manual value.")
            ac1, ac2 = st.columns(2)
            a_override = ac1.number_input("A Override (VND)", value=0.0, format="%.0f",
                                           help=f"Current line items total: {a_total:,.0f} ₫. Enter value > 0 to override.")
            c_override = ac2.number_input("C Override (VND)", value=0.0, format="%.0f",
                                           help=f"Current line items total: {c_total:,.0f} ₫. Enter value > 0 to override.")

            st.divider()
            st.markdown("**B — Logistics & Import** &nbsp; `B = A × α`")
            bc1, bc2 = st.columns([1,2])
            alpha = bc1.number_input("α (logistics ratio)", value=float(prefill.get('alpha_rate',def_alpha) or def_alpha), format="%.4f",
                                      help=f"Logistics cost as percentage of equipment cost. Default for this project type: {def_alpha}")
            b_manual = bc2.number_input("B Override (VND)", value=0.0, format="%.0f",
                                         help="Enter value > 0 to override the formula B = A × α")

            st.divider()
            st.markdown("**D — Direct Labor** &nbsp; `D = days × daily rate × team size`")
            dd1, dd2, dd3 = st.columns(3)
            man_days = dd1.number_input("Man-Days", value=int(prefill.get('d_man_days',0) or 0), min_value=0,
                                         help="Total estimated working days for the project")
            day_rate = dd2.number_input("Daily Rate (VND)", value=float(prefill.get('d_man_day_rate',1_500_000) or 1_500_000), format="%.0f",
                                         help="Average daily cost per person (VND)")
            team_size = dd3.number_input("Team Size", value=float(prefill.get('d_team_size',1.0) or 1.0), format="%.1f",
                                          help="Average number of people working simultaneously")
            d_manual = st.number_input("D Override (VND)", value=0.0, format="%.0f",
                                        help="Enter value > 0 to override the formula D = days × rate × team")

            st.divider()
            st.markdown("**E — Travel & Site Overhead** &nbsp; `E = D × β`")
            ec1, ec2 = st.columns([1,2])
            beta = ec1.number_input("β (travel ratio)", value=float(prefill.get('beta_rate',def_beta) or def_beta), format="%.4f",
                                     help=f"Travel & site cost as ratio of direct labor. Default: {def_beta}")
            e_manual = ec2.number_input("E Override (VND)", value=0.0, format="%.0f",
                                         help="Enter value > 0 to override the formula E = D × β")

            st.divider()
            st.markdown("**F — Warranty Reserve** &nbsp; `F = (A + C) × γ`")
            fc1, fc2 = st.columns([1,2])
            gamma = fc1.number_input("γ (warranty ratio)", value=float(prefill.get('gamma_rate',def_gamma) or def_gamma), format="%.4f",
                                      help=f"Warranty reserve as ratio of equipment + fabrication cost. Default: {def_gamma}")
            f_manual = fc2.number_input("F Override (VND)", value=0.0, format="%.0f",
                                         help="Enter value > 0 to override the formula F = (A+C) × γ")

            st.divider()
            assessment_notes = st.text_area("Assessment Notes", value=prefill.get('assessment_notes') or '', height=70,
                                             help="Assumptions, risks, or notes about this estimate")

            # ── Section 3: Attachments (inside form) ─────────────────────
            st.divider()
            st.markdown("**📎 Attachments** — scope documents, BOQ, vendor quotes")
            est_files = st.file_uploader("Drag & drop files", type=["pdf","jpg","jpeg","png","xlsx","docx"],
                                          accept_multiple_files=True, key="est_attachments")

            submitted = st.form_submit_button("💾 Save & Activate", type="primary", use_container_width=True)
    with col_result:
        st.markdown("### 📐 Live Estimate")
        eff_a = a_override if a_override > 0 else a_total
        eff_c = c_override if c_override > 0 else c_total
        eff_sales = sales_value if sales_value > 0 else _items_sell_total()
        result = calculate_estimate(a_equipment=eff_a, alpha=alpha, c_fabrication=eff_c,
            man_days=man_days, man_day_rate=day_rate, team_size=team_size,
            beta=beta, gamma=gamma, sales_value=eff_sales,
            b_override=b_manual if b_manual > 0 else None, d_override=d_manual if d_manual > 0 else None,
            e_override=e_manual if e_manual > 0 else None, f_override=f_manual if f_manual > 0 else None)
        cogs_rows = []
        for key in ['a','b','c','d','e','f']:
            val = result.get(key, 0)
            pct = (val/result['total_cogs']*100) if result['total_cogs'] > 0 else 0
            cogs_rows.append({'Item': COGS_LABELS[key.upper()], 'Amount': f"{val:,.0f}", '%': f"{pct:.1f}%"})
        cogs_rows.append({'Item': '**TOTAL COGS**', 'Amount': f"{result['total_cogs']:,.0f}", '%': ''})
        st.dataframe(pd.DataFrame(cogs_rows), width="stretch", hide_index=True,
            column_config={'Amount': st.column_config.TextColumn('VND'), '%': st.column_config.TextColumn('%', width=60)})
        st.divider()
        r1, r2 = st.columns(2)
        r1.metric("Sales", fmt_vnd(result['sales'])); r1.metric("COGS", fmt_vnd(result['total_cogs']))
        r2.metric("GP", fmt_vnd(result['gp'])); r2.metric("GP%", f"{result['gp_percent']:.1f}%")
        gng = get_go_no_go(result['gp_percent'], go_thresh, cond_thr)
        st.divider()
        if gng == 'GO': st.success(f"### ✅ GO — {result['gp_percent']:.1f}%")
        elif gng == 'CONDITIONAL': st.warning(f"### ⚠️ CONDITIONAL — {result['gp_percent']:.1f}%")
        else: st.error(f"### ❌ NO-GO — {result['gp_percent']:.1f}%")
        if items: st.caption(f"{len(items)} line items | A={'items' if a_override==0 else 'override'}")
    if submitted:
        if not _can_create:
            st.error("⛔ Bạn không có quyền tạo estimate."); st.stop()
        if eff_a <= 0 and eff_c <= 0 and man_days <= 0 and eff_sales <= 0:
            st.warning("Enter at least one cost + Sales."); st.stop()
        li_notes = "; ".join([f"{it.get('cogs_category','')}: {(it.get('item_description','') or '')[:25]} x{it.get('quantity',0):.0f}" for it in items[:10]])
        if len(items) > 10: li_notes += f" (+{len(items)-10})"
        gng_save = get_go_no_go(result['gp_percent'], go_thresh, cond_thr)
        est_data = {'project_id': project_id, 'estimate_version': next_version,
            'estimate_label': label, 'estimate_type': est_type,
            'a_equipment_cost': eff_a, 'a_equipment_notes': li_notes[:500] or None,
            'alpha_rate': alpha, 'b_logistics_import': result['b'], 'b_override': 1 if b_manual > 0 else 0,
            'c_custom_fabrication': eff_c, 'c_fabrication_notes': None,
            'd_man_days': man_days, 'd_man_day_rate': day_rate, 'd_team_size': team_size,
            'd_direct_labor': result['d'], 'd_override': 1 if d_manual > 0 else 0,
            'beta_rate': beta, 'e_travel_site_oh': result['e'], 'e_override': 1 if e_manual > 0 else 0,
            'gamma_rate': gamma, 'f_warranty_reserve': result['f'], 'f_override': 1 if f_manual > 0 else 0,
            'total_cogs': result['total_cogs'], 'sales_value': result['sales'],
            'estimated_gp': result['gp'], 'estimated_gp_percent': result['gp_percent'],
            'go_no_go_result': gng_save, 'assessment_notes': assessment_notes or None}
        try:
            new_id = create_estimate(est_data, user_id)
            activate_estimate(project_id, new_id, user_id)
            for i, it in enumerate(items):
                li_data = _sanitize_item({
                    'estimate_id': new_id, 'cogs_category': it.get('cogs_category','A'),
                    'product_id': it.get('product_id'), 'item_description': it.get('item_description',''),
                    'brand_name': it.get('brand_name',''), 'pt_code': it.get('pt_code',''),
                    'costbook_detail_id': it.get('costbook_detail_id'),
                    'vendor_name': it.get('vendor_name',''), 'vendor_quote_ref': it.get('vendor_quote_ref',''),
                    'costbook_number': it.get('costbook_number',''),
                    'unit_cost': it.get('unit_cost',0), 'cost_currency_id': it.get('cost_currency_id'),
                    'cost_exchange_rate': it.get('cost_exchange_rate',1),
                    'quotation_detail_id': it.get('quotation_detail_id'),
                    'unit_sell': it.get('unit_sell',0), 'sell_currency_id': it.get('sell_currency_id'),
                    'sell_exchange_rate': it.get('sell_exchange_rate',1),
                    'quantity': it.get('quantity',1), 'uom': it.get('uom','Pcs'),
                    'notes': it.get('notes'), 'view_order': i})
                create_estimate_line_item(li_data, user_id)
            # Upload line-item attachments (outside the line-item insert loop)
            s3 = _get_s3()
            if s3:
                for i, it in enumerate(items):
                    att = it.get('_attachment')
                    if att and att.get('bytes'):
                        ok, s3_key = s3.upload_project_file(att['bytes'], att['name'], project_id)
                        if ok:
                            li_saved = get_estimate_line_items(new_id)
                            if not li_saved.empty and i < len(li_saved):
                                create_line_item_media(
                                    int(li_saved.iloc[i]['id']),
                                    s3_key, att['name'], created_by=user_id)
                # Upload estimate-level attachments
                if est_files:
                    for f in est_files:
                        ok, s3_key = s3.upload_project_file(f.read(), f.name, project_id)
                        if ok:
                            create_estimate_media(
                                new_id, s3_key, f.name,
                                document_type='OTHER',
                                created_by=user_id)
            st.success(f"✅ Rev {next_version} saved with {len(items)} line items!")
            _clear_items(); _invalidate_estimates(); _load_projects.clear(); st.rerun()
        except Exception as e:
            st.error(f"Save failed: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Active Estimate
# ══════════════════════════════════════════════════════════════════════════════
with tab_active:
    if not active_est: st.info("No active estimate."); st.stop()
    gng_a = active_est.get('go_no_go_result','')
    hc1, hc2 = st.columns([4,1])
    hc1.markdown(f"### Rev {active_est['estimate_version']} — {active_est.get('estimate_label','')}")
    if gng_a == 'GO': hc2.success("✅ GO")
    elif gng_a == 'CONDITIONAL': hc2.warning("⚠️")
    elif gng_a == 'NO_GO': hc2.error("❌")

    if _can_view_costs:
        # Full view: Sales, COGS, GP, GP%
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("Sales", fmt_vnd(active_est.get('sales_value')))
        mc2.metric("COGS", fmt_vnd(active_est.get('total_cogs')))
        mc3.metric("GP", fmt_vnd(active_est.get('estimated_gp')))
        mc4.metric("GP%", fmt_percent(active_est.get('estimated_gp_percent')))
    else:
        # Limited view (Sales role): only sales value + result
        mc1, mc2 = st.columns(2)
        mc1.metric("Sales Value", fmt_vnd(active_est.get('sales_value')))
        mc2.metric("Result", gng_a or '—')
        st.caption("💡 Chi tiết vendor cost / GP chỉ hiển thị cho PM, SA, và Admin.")

    st.divider()
    li_df = get_estimate_line_items(active_est['id'])
    if not li_df.empty:
        st.subheader(f"📋 Line Items ({len(li_df)})")
        disp = li_df.copy()
        if _can_view_costs:
            # Full line item table with cost details
            disp['cost_total'] = disp['amount_cost_vnd'].apply(lambda v: f"{v:,.0f}" if v and str(v) not in ('','nan','None') else '—')
            disp['sell_total'] = disp['amount_sell_vnd'].apply(lambda v: f"{v:,.0f}" if v and str(v) not in ('','nan','None','0','0.0') else '—')
            st.dataframe(disp, width="stretch", hide_index=True,
                column_config={'cogs_category': st.column_config.TextColumn('Cat', width=35),
                    'item_description': st.column_config.TextColumn('Product'),
                    'brand_name': st.column_config.TextColumn('Brand', width=80),
                    'vendor_name': st.column_config.TextColumn('Vendor'),
                    'quantity': st.column_config.NumberColumn('Qty', format="%.1f", width=55),
                    'unit_cost': st.column_config.NumberColumn('Cost', format="%.2f"),
                    'cost_currency': st.column_config.TextColumn('CCY', width=40),
                    'cost_total': st.column_config.TextColumn('Cost VND'),
                    'sell_total': st.column_config.TextColumn('Sell VND'),
                    'costbook_number': st.column_config.TextColumn('Costbook'),
                    'vendor_quote_ref': st.column_config.TextColumn('Quote Ref'),
                    'id': None, 'product_id': None, 'pt_code': None, 'costbook_detail_id': None,
                    'quotation_detail_id': None, 'unit_sell': None, 'sell_currency': None,
                    'sell_exchange_rate': None, 'cost_exchange_rate': None, 'uom': None,
                    'view_order': None, 'amount_cost_vnd': None, 'amount_sell_vnd': None, 'notes': None})
        else:
            # Limited view: product + quantity only (no cost/vendor info)
            st.dataframe(disp, width="stretch", hide_index=True,
                column_config={'cogs_category': st.column_config.TextColumn('Cat', width=35),
                    'item_description': st.column_config.TextColumn('Product'),
                    'brand_name': st.column_config.TextColumn('Brand', width=80),
                    'quantity': st.column_config.NumberColumn('Qty', format="%.1f", width=55),
                    'uom': st.column_config.TextColumn('UOM', width=50),
                    'id': None, 'product_id': None, 'pt_code': None, 'costbook_detail_id': None,
                    'quotation_detail_id': None, 'unit_cost': None, 'unit_sell': None,
                    'cost_currency': None, 'sell_currency': None,
                    'cost_exchange_rate': None, 'sell_exchange_rate': None,
                    'vendor_name': None, 'vendor_quote_ref': None, 'costbook_number': None,
                    'view_order': None, 'amount_cost_vnd': None, 'amount_sell_vnd': None, 'notes': None})
    st.divider()
    if _can_view_costs:
        fmap = {'A':'a_equipment_cost','B':'b_logistics_import','C':'c_custom_fabrication','D':'d_direct_labor','E':'e_travel_site_oh','F':'f_warranty_reserve'}
        tc = float(active_est.get('total_cogs',0) or 0)
        rows = [{'Item': COGS_LABELS[k], 'Amount': f"{float(active_est.get(f,0) or 0):,.0f}",
                 '%': f"{float(active_est.get(f,0) or 0)/tc*100:.1f}%" if tc > 0 else '—'} for k, f in fmap.items()]
        rows.append({'Item': '**TOTAL**', 'Amount': f"{tc:,.0f}", '%': ''})
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        if active_est.get('assessment_notes'): st.info(f"📝 {active_est['assessment_notes']}")
        # Attachments (Pattern A: medias junction)
        est_atts = get_estimate_medias(active_est['id'])
        if est_atts:
            st.divider()
            st.subheader(f"📎 Attachments ({len(est_atts)})")
            for att in est_atts:
                s3 = _get_s3()
                url = s3.get_presigned_url(att['s3_key'], expiration=600) if s3 else None
                cols = st.columns([4, 1])
                desc_text = f" — {att['description']}" if att.get('description') else ""
                cols[0].markdown(f"📄 **{att['filename']}**{desc_text}")
                if url:
                    cols[1].markdown(f"[⬇️ Download]({url})")
        # Line item attachments (Pattern A: medias junction)
        li_atts = get_line_item_medias(active_est['id'])
        if li_atts:
            if not est_atts:
                st.divider(); st.subheader("📎 Line Item Attachments")
            else:
                st.caption("**Line item attachments:**")
            # Build lookup: line_item_id → item_description
            li_desc_map = {}
            if not li_df.empty:
                li_desc_map = dict(zip(li_df['id'].astype(int), li_df['item_description']))
            for att in li_atts:
                desc = li_desc_map.get(att.get('line_item_id', 0), '')
                st.caption(f"📎 {desc}: **{att['filename']}**")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — History
# ══════════════════════════════════════════════════════════════════════════════
with tab_history:
    if not all_estimates: st.info("No estimates."); st.stop()
    if _can_view_costs:
        hist = [{'': '✅' if e.get('is_active') else '', 'Rev': e['estimate_version'],
            'Label': e.get('estimate_label',''), 'Type': e.get('estimate_type',''),
            'COGS': f"{float(e.get('total_cogs',0) or 0):,.0f}", 'Sales': f"{float(e.get('sales_value',0) or 0):,.0f}",
            'GP%': fmt_percent(e.get('estimated_gp_percent')), 'Result': e.get('go_no_go_result','—'),
            'α': e.get('alpha_rate',''), 'β': e.get('beta_rate',''), 'γ': e.get('gamma_rate',''),
            'Created': e.get('created_date')} for e in all_estimates]
    else:
        # Limited view: no COGS/Sales/GP%/coefficients
        hist = [{'': '✅' if e.get('is_active') else '', 'Rev': e['estimate_version'],
            'Label': e.get('estimate_label',''), 'Type': e.get('estimate_type',''),
            'Result': e.get('go_no_go_result','—'),
            'Created': e.get('created_date')} for e in all_estimates]
    st.dataframe(pd.DataFrame(hist), width="stretch", hide_index=True,
        column_config={'': st.column_config.TextColumn('', width=30), 'Rev': st.column_config.NumberColumn('Rev', width=50),
            'α': st.column_config.NumberColumn('α', format="%.4f", width=70),
            'β': st.column_config.NumberColumn('β', format="%.4f", width=70),
            'γ': st.column_config.NumberColumn('γ', format="%.4f", width=70)})
    if _can_activate and len(all_estimates) > 1:
        st.divider()
        rev_opts = [f"Rev {e['estimate_version']} — {e.get('estimate_label','')}" for e in all_estimates]
        sel_est = all_estimates[rev_opts.index(st.selectbox("Activate version", rev_opts))]
        if st.button("Activate Selected"):
            if activate_estimate(project_id, sel_est['id'], user_id):
                st.success(f"Rev {sel_est['estimate_version']} active."); _invalidate_estimates(); _load_projects.clear(); st.rerun()