# pages/2_📊_Estimate_GP.py
"""
Estimate GP — A→F formula + Go/No-Go + Product/Costbook integration.

Phase 1 Upgrade:
  - "All Projects" Dashboard mode (KPI rows + estimate table + analytics)
  - @st.fragment on Active Estimate & History tabs (no full-page rerun)
  - Context banner for per-project mode
  - Sidebar refactored: All Projects default, filters
"""
import streamlit as st
import pandas as pd
import logging
from datetime import date
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
from utils.il_project.permissions import PermissionContext, get_role_badge
logger = logging.getLogger(__name__)
auth = AuthManager()
st.set_page_config(page_title="Estimate GP", page_icon="📊", layout="wide")
auth.require_auth()
user_id    = str(auth.get_user_id())
user_role  = st.session_state.get('user_role', '')
is_admin   = auth.is_admin()
emp_int_id = st.session_state.get('employee_id')
ctx = PermissionContext(employee_id=emp_int_id, is_admin=is_admin, user_role=user_role)

# ══════════════════════════════════════════════════════════════════════════════
# LOOKUPS
# ══════════════════════════════════════════════════════════════════════════════
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
def _cached_estimates(project_id, _v=0):
    return get_estimates(project_id)
def _invalidate_estimates():
    st.session_state['_est_v'] = st.session_state.get('_est_v', 0) + 1

@st.cache_data(ttl=60, show_spinner=False)
def _cached_dashboard(_v=0, status=None, type_id=None, go_no_go=None):
    from utils.il_project.queries import get_estimate_dashboard_df
    return get_estimate_dashboard_df(status=status, type_id=type_id, go_no_go=go_no_go)
def _invalidate_dashboard():
    st.session_state['_dash_v'] = st.session_state.get('_dash_v', 0) + 1

@st.cache_resource
def _get_s3():
    try: return ILProjectS3Manager()
    except Exception: return None

def _sf(v, default=0.0):
    if v is None: return default
    try:
        f = float(v)
        return default if pd.isna(f) else f
    except (TypeError, ValueError):
        return default

# ══════════════════════════════════════════════════════════════════════════════
# PAGE HEADER + SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
st.title("📊 Estimate GP")
if proj_df.empty:
    st.warning("No projects found."); st.stop()

# ── Handle Quick Jump (must run BEFORE selectbox widget is created) ──
_jump_label = st.session_state.pop('_est_jump_to', None)
if _jump_label:
    # Clear widget key so selectbox index= takes effect on this run
    st.session_state.pop('est_project', None)

with st.sidebar:
    st.header("Filters")
    proj_options = ["All Projects"] + [f"{r.project_code} — {r.project_name}" for r in proj_df.itertuples()]
    _default_idx = 0
    if _jump_label and _jump_label in proj_options:
        _default_idx = proj_options.index(_jump_label)
    sel_label = st.selectbox("Project", proj_options, index=_default_idx, key="est_project")
    is_all_projects = sel_label == "All Projects"

    if not is_all_projects:
        sel_idx    = proj_options.index(sel_label) - 1
        project_id = int(proj_df.iloc[sel_idx]['project_id'])
        project    = get_project(project_id)
    else:
        project_id = None
        project    = None

    if is_all_projects:
        f_status = st.selectbox("Status", ["All","DRAFT","ESTIMATING","PROPOSAL_SENT","GO","CONDITIONAL","NO_GO","CONTRACTED","IN_PROGRESS","COMPLETED"], key="est_f_status")
        f_type = st.selectbox("Project Type", ["All"] + [f"[{t['code']}] {t['name']}" for t in proj_types], key="est_f_type")
        f_gng = st.selectbox("Go/No-Go", ["All","GO","CONDITIONAL","NO_GO","NONE (no estimate)"], key="est_f_gng")
        st.divider()
        st.caption(f"Role: {get_role_badge(ctx.role())}")
    else:
        if project:
            pt = type_map.get(project.get('project_type_id', 0), {})
            st.caption(f"**Type:** {project.get('type_name','—')} | **Customer:** {project.get('customer_name','—')}")
            st.caption(f"**Distance:** {project.get('site_distance_category','—')} | **Env:** {project.get('environment_category','—')}")
            st.divider()
            st.caption(f"α={pt.get('default_alpha',0.06)} β={pt.get('default_beta',0.40)} γ={pt.get('default_gamma',0.04)}")
            st.caption(f"GO ≥{pt.get('gp_go_threshold',25)}% | COND ≥{pt.get('gp_conditional_threshold',18)}%")
            st.divider()
            st.caption(f"Role: {get_role_badge(ctx.role(project_id))}")

# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD — All Projects
# ══════════════════════════════════════════════════════════════════════════════
def _render_dashboard():
    _status  = None if f_status == "All" else f_status
    _type_id = None
    if f_type != "All":
        _code = f_type.split("]")[0][1:]
        hit   = next((t for t in proj_types if t['code'] == _code), None)
        _type_id = hit['id'] if hit else None
    _gng = None
    if f_gng != "All":
        _gng = 'NONE' if 'NONE' in f_gng else f_gng

    df = _cached_dashboard(_v=st.session_state.get('_dash_v', 0), status=_status, type_id=_type_id, go_no_go=_gng)
    has_est = df['gp_percent'].notna() if not df.empty else pd.Series(dtype=bool)

    # ── KPI Row 1: Financial ──
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Projects", len(df))
    if not df.empty and has_est.any():
        _edf = df[has_est]
        k2.metric("Avg GP%", f"{_edf['gp_percent'].mean():.1f}%")
        _tgp = _edf['gp_amount'].fillna(0).sum()
        _tsl = _edf['sales_value'].fillna(0).sum()
        k3.metric("Weighted GP%", f"{_tgp/_tsl*100:.1f}%" if _tsl > 0 else "—",
                  help="SUM(GP) / SUM(Sales) — weighted by contract size")
        k4.metric("Total Est. COGS", fmt_vnd(_edf['total_cogs'].fillna(0).sum()))
    else:
        k2.metric("Avg GP%", "—"); k3.metric("Weighted GP%", "—"); k4.metric("Total Est. COGS", "—")

    # ── KPI Row 2: Operational ──
    o1, o2, o3, o4 = st.columns(4)
    with_est = int(has_est.sum()) if not df.empty else 0
    no_est   = len(df) - with_est
    o1.metric("With Estimate", with_est, delta=f"{no_est} without" if no_est > 0 else None, delta_color="off")

    if not df.empty and has_est.any():
        gc = df[has_est]['go_no_go_result'].value_counts().to_dict()
        o2.metric(f"✅ GO: {gc.get('GO',0)}", f"⚠️ {gc.get('CONDITIONAL',0)}  ❌ {gc.get('NO_GO',0)}", delta_color="off")
    else:
        o2.metric("Go/No-Go", "—")

    stale = int(df['is_stale'].fillna(0).sum()) if not df.empty else 0
    o3.metric("Stale (>30d)", stale, delta="needs refresh" if stale > 0 else "all fresh", delta_color="inverse" if stale > 0 else "off")
    drift = int(df['has_drift'].fillna(0).sum()) if not df.empty else 0
    o4.metric("GP Drift", drift, delta="snapshot ≠ estimate" if drift > 0 else "all synced", delta_color="inverse" if drift > 0 else "off")

    if df.empty:
        st.divider(); st.info("No projects found for selected filters."); return

    tab_table, tab_analytics = st.tabs(["📋 Project Estimates", "📈 Analytics"])
    with tab_table:
        _render_dashboard_table(df, has_est)
    with tab_analytics:
        _render_analytics(df, has_est)


def _render_dashboard_table(df, has_est):
    display = df[['project_code','project_name','customer_name','type_code','status','pm_name',
                   'gp_percent','go_no_go_result','sales_value','total_cogs',
                   'line_item_count','active_rev','estimate_created','has_drift','is_stale']].copy()
    display['gng'] = display['go_no_go_result'].map({'GO':'✅ GO','CONDITIONAL':'⚠️ COND','NO_GO':'❌ NO-GO'}).fillna('—')
    display['gp_fmt'] = display.apply(lambda r: (
        f"{r['gp_percent']:.1f}%" + (" ⚠️" if _sf(r.get('has_drift')) > 0 else "") + (" 🔄" if _sf(r.get('is_stale')) > 0 else "")
    ) if pd.notna(r['gp_percent']) else '—', axis=1)
    display['sales_fmt'] = display['sales_value'].apply(lambda v: f"{_sf(v):,.0f}" if _sf(v) > 0 else '—')
    display['cogs_fmt']  = display['total_cogs'].apply(lambda v: f"{_sf(v):,.0f}" if _sf(v) > 0 else '—')
    display['rev_fmt'] = display['active_rev'].apply(lambda v: f"Rev {int(v)}" if pd.notna(v) and v else '—')
    display['age'] = display['estimate_created'].apply(lambda v: _age_icon(v))
    display.insert(0, '●', display['go_no_go_result'].map({'GO':'🟢','CONDITIONAL':'🟡','NO_GO':'🔴'}).fillna('⚪'))

    _ec1, _ec2 = st.columns([6, 1])
    _ec1.caption(f"**{len(display)} projects** matching filters")
    _ec2.download_button("📥 Excel", data=_export_excel(df),
        file_name=f"Estimate_GP_{date.today().isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

    tbl_key = f"est_dash_{st.session_state.get('_edk', 0)}"
    event = st.dataframe(display, key=tbl_key, width="stretch", hide_index=True,
        on_select="rerun", selection_mode="single-row",
        column_config={
            '●': st.column_config.TextColumn('', width=30),
            'project_code': st.column_config.TextColumn('Code', width=145),
            'project_name': st.column_config.TextColumn('Name'),
            'customer_name': st.column_config.TextColumn('Customer', width=120),
            'type_code': st.column_config.TextColumn('Type', width=55),
            'status': st.column_config.TextColumn('Status', width=115),
            'pm_name': st.column_config.TextColumn('PM', width=90),
            'gp_fmt': st.column_config.TextColumn('GP%', width=90, help="⚠️ drift | 🔄 stale"),
            'gng': st.column_config.TextColumn('Go/No-Go', width=90),
            'sales_fmt': st.column_config.TextColumn('Sales VND', width=110),
            'cogs_fmt': st.column_config.TextColumn('COGS VND', width=110),
            'line_item_count': st.column_config.NumberColumn('Items', width=55),
            'rev_fmt': st.column_config.TextColumn('Rev', width=65),
            'age': st.column_config.TextColumn('Age', width=40, help="🟢 <7d 🟡 7-30d 🔴 >30d"),
            'gp_percent': None, 'go_no_go_result': None, 'sales_value': None,
            'total_cogs': None, 'active_rev': None, 'estimate_created': None,
            'has_drift': None, 'is_stale': None, 'project_id': None,
        })

    st.caption("**Health:** 🟢 GO | 🟡 Conditional | 🔴 No-Go | ⚪ No estimate")

    sel = event.selection.rows
    if sel:
        row = df.iloc[sel[0]]
        pid = int(row['project_id'])
        _qj = f"{row['project_code']} — {row['project_name']}"
        st.markdown(f"**Selected:** `{row['project_code']}` — {row['project_name']}")
        j1, j2, j3, j4 = st.columns(4)
        if j1.button("📊 Open Estimate", type="primary", use_container_width=True, key="dj1"):
            st.session_state["_est_jump_to"] = _qj; st.rerun()
        if j2.button("🏗️ Projects", use_container_width=True, key="dj2"):
            st.session_state["open_view_pid"] = pid; st.switch_page("pages/1_🏗️_Projects.py")
        if j3.button("📈 COGS Dashboard", use_container_width=True, key="dj3"):
            st.session_state["cogs_project"] = _qj; st.switch_page("pages/4_📈_COGS_Dashboard.py")
        if j4.button("✖ Deselect", use_container_width=True, key="dj4"):
            st.session_state["_edk"] = st.session_state.get("_edk", 0) + 1; st.rerun()

def _age_icon(v):
    if v is None or (isinstance(v, float) and pd.isna(v)): return '⚪'
    try:
        d = (pd.Timestamp.now() - pd.to_datetime(v)).days
        if d <= 7: return '🟢'
        if d <= 30: return '🟡'
        return '🔴'
    except Exception: return '⚪'

def _export_excel(df):
    import io
    export = pd.DataFrame({'Project Code': df['project_code'], 'Name': df['project_name'],
        'Customer': df['customer_name'], 'Type': df['type_code'], 'Status': df['status'],
        'PM': df['pm_name'], 'GP%': df['gp_percent'], 'Go/No-Go': df['go_no_go_result'],
        'Sales VND': df['sales_value'], 'COGS VND': df['total_cogs'], 'GP VND': df['gp_amount'],
        'Items': df['line_item_count'], 'Rev': df['active_rev'], 'Created': df['estimate_created'],
        'Stale': df['is_stale'].map({1:'Yes',0:'No'}), 'Drift': df['has_drift'].map({1:'Yes',0:'No'})})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        export.to_excel(w, index=False, sheet_name='Estimates')
        ws = w.sheets['Estimates']
        for cc in ws.columns:
            ml = max((len(str(c.value or '')) for c in cc), default=8)
            ws.column_dimensions[cc[0].column_letter].width = min(ml + 3, 40)
    return buf.getvalue()

# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS — Charts
# ══════════════════════════════════════════════════════════════════════════════
def _render_analytics(df, has_est):
    if not has_est.any():
        st.info("No estimates available for analytics."); return
    est_df = df[has_est].copy()
    col_dist, col_gng = st.columns(2)
    with col_dist:
        try:
            import plotly.express as px
            st.caption("**GP% Distribution**")
            fig = px.histogram(est_df, x='gp_percent', nbins=10,
                labels={'gp_percent':'GP%','count':'Projects'}, color_discrete_sequence=['#534AB7'])
            fig.update_layout(height=260, margin=dict(l=40,r=10,t=5,b=40),
                xaxis_title="GP%", yaxis_title="Count",
                plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', showlegend=False)
            for t in proj_types[:1]:
                fig.add_vline(x=float(t.get('gp_go_threshold',25)), line_dash="dash", line_color="#4caf50",
                    annotation_text=f"GO ≥{t.get('gp_go_threshold',25)}%", annotation_position="top right")
                fig.add_vline(x=float(t.get('gp_conditional_threshold',18)), line_dash="dash", line_color="#ff9800",
                    annotation_text=f"COND ≥{t.get('gp_conditional_threshold',18)}%", annotation_position="top left")
            st.plotly_chart(fig, width="stretch", config={'displayModeBar': False})
        except ImportError: st.info("Install plotly for charts.")
    with col_gng:
        try:
            import plotly.graph_objects as go
            st.caption("**Go/No-Go Decision**")
            gc = est_df['go_no_go_result'].value_counts()
            ne = len(df) - len(est_df)
            if ne > 0: gc['No Estimate'] = ne
            colors = {'GO':'#4caf50','CONDITIONAL':'#ff9800','NO_GO':'#f44336','No Estimate':'#9e9e9e'}
            fig = go.Figure(data=[go.Pie(labels=gc.index.tolist(), values=gc.values.tolist(),
                marker_colors=[colors.get(k,'#9e9e9e') for k in gc.index], hole=0.4,
                textinfo='label+value', textposition='outside')])
            fig.update_layout(height=260, margin=dict(l=10,r=10,t=5,b=30),
                plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', showlegend=False)
            st.plotly_chart(fig, width="stretch", config={'displayModeBar': False})
        except ImportError: pass

    # GP% vs Sales Value scatter
    if est_df['sales_value'].notna().any() and len(est_df) >= 2:
        try:
            import plotly.graph_objects as go
            chart = est_df[est_df['sales_value'].notna() & (est_df['sales_value'] > 0)].copy()
            if len(chart) >= 2:
                st.divider()
                st.caption("**GP% vs Sales Value**")
                cm = {'GO':'#4caf50','CONDITIONAL':'#ff9800','NO_GO':'#f44336'}
                fig = go.Figure()
                for _, r in chart.iterrows():
                    _sv = float(r['sales_value'])
                    fig.add_trace(go.Scatter(x=[r['gp_percent']], y=[_sv / 1e6],
                        mode='markers+text', marker=dict(size=12, color=cm.get(r['go_no_go_result'],'#9e9e9e'),
                            line=dict(width=1,color='white')),
                        text=[str(r['project_code'])[-3:]], textposition='top center', textfont=dict(size=9),
                        hovertemplate=(
                            f"<b>{r['project_code']}</b><br>"
                            f"{str(r['project_name'])[:30]}<br>"
                            f"GP: {r['gp_percent']:.1f}%<br>"
                            f"Sales: {_sv:,.0f} VND<br>"
                            f"<extra></extra>"
                        ),
                        showlegend=False))
                fig.update_layout(height=300, margin=dict(l=60,r=10,t=5,b=40),
                    xaxis=dict(title="GP%"), yaxis=dict(title="Sales (M VND)"),
                    plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
                st.plotly_chart(fig, width="stretch", config={'displayModeBar': False})
                st.caption("🟢 GO | 🟡 Conditional | 🔴 No-Go")
        except ImportError: pass

    # No-estimate callout
    no_est = df[~has_est]
    if not no_est.empty:
        st.divider()
        with st.expander(f"⚪ **{len(no_est)} project(s) without estimate**"):
            for _, r in no_est.head(10).iterrows():
                st.caption(f"`{r['project_code']}` — {r['project_name']} ({r['status']})")

# ══════════════════════════════════════════════════════════════════════════════
# CONTEXT BANNER
# ══════════════════════════════════════════════════════════════════════════════
def _render_context_banner(proj, active_est):
    c1, c2, c3, c4, c5 = st.columns([3, 2, 1, 1, 1])
    c1.markdown(f"**{proj['project_code']}** — {proj['project_name']}")
    c2.caption(f"Customer: {proj.get('customer_name') or proj.get('end_customer_name','—')} | Status: **{proj['status']}**")
    _bv = float(proj.get('contract_value_before_vat') or proj.get('contract_value') or 0)
    _er = float(proj.get('exchange_rate') or 1)
    c3.metric("Contract", fmt_vnd(_bv * _er) if _bv > 0 else "—")
    if active_est:
        c4.metric("GP%", fmt_percent(active_est.get('estimated_gp_percent')))
        gng = active_est.get('go_no_go_result','')
        _badge = {'GO':'✅ GO','CONDITIONAL':'⚠️','NO_GO':'❌'}.get(gng,'—')
        c5.markdown(f"### {_badge}")
    else:
        c4.metric("GP%", "—"); c5.warning("No est.")

# ══════════════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _show_rate(col, label, rate_result):
    _b = {'same':('ℹ️','Same'),'api':('🟢','Live'),'cache':('🟢','Cached'),'db':('🔵','DB'),'fallback':('🟠','Fallback')}
    i, s = _b.get(rate_result.source, ('⚪', rate_result.source))
    col.metric(label, f"{rate_result.rate:,.2f}"); col.caption(f"{i} {s}")
    return rate_result.rate

def _sanitize_item(item):
    import math
    clean = {}
    for k, v in item.items():
        if isinstance(v, float) and math.isnan(v): clean[k] = None
        elif hasattr(v, 'isoformat'):
            try: clean[k] = None if pd.isna(v) else v
            except (TypeError, ValueError): clean[k] = v
        else:
            try:
                if pd.isna(v): clean[k] = None; continue
            except (TypeError, ValueError): pass
            clean[k] = v
    return clean

# ══════════════════════════════════════════════════════════════════════════════
# WIZARD STATE — for Create Estimate dialog
# ══════════════════════════════════════════════════════════════════════════════

_WIZ = '_est_wiz_'  # prefix for all wizard keys

def _wiz_get(key, default=None):
    return st.session_state.get(f'{_WIZ}{key}', default)

def _wiz_set(key, value):
    st.session_state[f'{_WIZ}{key}'] = value

def _wiz_items():
    return st.session_state.get(f'{_WIZ}items', [])

def _wiz_add_item(item):
    st.session_state.setdefault(f'{_WIZ}items', []).append(_sanitize_item(item))

def _wiz_remove_item(idx):
    items = _wiz_items()
    if 0 <= idx < len(items):
        items.pop(idx)
        _wiz_set('items', items)

def _wiz_update_item(idx, item):
    items = _wiz_items()
    if 0 <= idx < len(items):
        items[idx] = _sanitize_item(item)
        _wiz_set('items', items)

def _wiz_items_total(cat=None):
    items = _wiz_items()
    if cat:
        items = [i for i in items if i.get('cogs_category') == cat]
    return sum(i.get('quantity', 0) * i.get('unit_cost', 0) * i.get('cost_exchange_rate', 1) for i in items)

def _wiz_items_sell_total():
    return sum(i.get('quantity', 0) * i.get('unit_sell', 0) * i.get('sell_exchange_rate', 1) for i in _wiz_items())

def _wiz_init(active_est=None, pid=None):
    """Initialize wizard state. Optionally prefill from active estimate."""
    _wiz_set('step', 1)
    _wiz_set('items', [])
    _wiz_set('header', {})
    _wiz_set('prefill_from', None)
    _wiz_set('show_add', False)
    _wiz_set('show_import', False)
    _wiz_set('show_manual', False)
    _wiz_set('edit_idx', -1)
    _wiz_set('tbl_ver', 0)

def _wiz_cleanup():
    """Remove all wizard keys from session state."""
    keys = [k for k in st.session_state if k.startswith(_WIZ)]
    for k in keys:
        del st.session_state[k]
    st.session_state.pop('_est_open_create', None)


# ══════════════════════════════════════════════════════════════════════════════
# WIZARD DIALOG — 3-step Create Estimate
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("📝 New Estimate", width="large")
def _dialog_create_estimate(pid, proj, pt, active_est):
    step = _wiz_get('step', 1)

    # ── Progress indicator ──
    cols = st.columns(3)
    for i, (icon, label) in enumerate([(("① ", "Header")), ("② ", "Line Items"), ("③ ", "COGS Formula")], 1):
        style = "**" if i == step else ""
        sep = " ✓" if i < step else ""
        cols[i - 1].markdown(f"{style}{icon}{label}{sep}{style}")
    st.divider()

    if step == 1:
        _wiz_step1_header(pid, proj, pt, active_est)
    elif step == 2:
        _wiz_step2_items(pid, proj)
    elif step == 3:
        _wiz_step3_formula(pid, proj, pt, active_est)


# ── Step 1: Header ──────────────────────────────────────────────────────────

def _wiz_step1_header(pid, proj, pt, active_est):
    from utils.il_project.queries import get_next_estimate_version
    nv = get_next_estimate_version(pid)

    header = _wiz_get('header', {})
    h1, h2 = st.columns(2)
    label = h1.text_input("Estimate Label", value=header.get('label', f"Rev {nv}"), key="wh_label")
    est_type = h2.selectbox("Type", ["QUICK", "DETAILED"],
                            index=1 if header.get('est_type') == 'DETAILED' else 0, key="wh_type")

    # Prefill mode
    prefill_mode = 'scratch'
    if active_est:
        prefill_mode = st.radio(
            "Start from",
            ["active", "scratch"],
            format_func=lambda x: f"📋 Active estimate (Rev {active_est['estimate_version']})" if x == "active" else "🆕 Start from scratch",
            horizontal=True, key="wh_prefill",
        )

    notes = st.text_area("Assessment Notes", value=header.get('notes', ''), height=80, key="wh_notes")

    st.divider()
    st.markdown("**📎 Attachments** — scope documents, BOQ, vendor quotes")
    est_files = st.file_uploader(
        "Drag & drop files",
        type=["pdf", "jpg", "jpeg", "png", "xlsx", "docx", "doc", "xls", "pptx", "csv", "zip"],
        accept_multiple_files=True, key="wh_files",
    )

    # Navigation
    st.divider()
    n1, _, n2 = st.columns([1, 3, 1])
    if n1.button("✖ Cancel", use_container_width=True, key="wh_cancel"):
        _wiz_cleanup()
        st.rerun()
    if n2.button("Next: Line Items →", type="primary", use_container_width=True, key="wh_next"):
        # Save header data
        _wiz_set('header', {'label': label, 'est_type': est_type, 'notes': notes, 'files': est_files})
        _wiz_set('next_version', nv)
        # Prefill items from active estimate if chosen
        if prefill_mode == 'active' and active_est and not _wiz_items():
            existing = get_estimate_line_items(active_est['id'])
            if not existing.empty:
                for _, row in existing.iterrows():
                    _wiz_add_item(row.to_dict())
            _wiz_set('prefill_from', active_est['id'])
            # Carry over coefficients
            _wiz_set('prefill_coeffs', {
                'alpha': active_est.get('alpha_rate'), 'beta': active_est.get('beta_rate'),
                'gamma': active_est.get('gamma_rate'), 'man_days': active_est.get('d_man_days'),
                'day_rate': active_est.get('d_man_day_rate'), 'team_size': active_est.get('d_team_size'),
            })
        _wiz_set('step', 2)
        st.rerun()


# ── Step 2: Line Items ──────────────────────────────────────────────────────

def _wiz_step2_items(pid, proj):
    items = _wiz_items()

    # ── Action buttons ──
    b1, b2, b3, b4 = st.columns(4)
    if b1.button("🔍 Add Equipment (A)", use_container_width=True, key="wi_add_a"):
        _wiz_set('show_add', 'A'); _wiz_set('show_import', False); _wiz_set('show_manual', False); _wiz_set('edit_idx', -1)
    if b2.button("🔧 Add Fabrication (C)", use_container_width=True, key="wi_add_c"):
        _wiz_set('show_add', 'C'); _wiz_set('show_import', False); _wiz_set('show_manual', False); _wiz_set('edit_idx', -1)
    if b3.button("📦 Import Costbook", use_container_width=True, key="wi_import"):
        _wiz_set('show_import', True); _wiz_set('show_add', False); _wiz_set('show_manual', False); _wiz_set('edit_idx', -1)
    if b4.button("✏️ Manual Item", use_container_width=True, key="wi_manual"):
        _wiz_set('show_manual', True); _wiz_set('show_add', False); _wiz_set('show_import', False); _wiz_set('edit_idx', -1)

    # ── Inline panels ──
    _show_add = _wiz_get('show_add', False)
    if _show_add:
        _wiz_panel_add_product(_show_add, proj)

    if _wiz_get('show_import', False):
        _wiz_panel_import_costbook()

    if _wiz_get('show_manual', False):
        _wiz_panel_manual_item()

    # ── Items table ──
    st.divider()
    items = _wiz_items()  # re-read after panel actions
    if items:
        rows = []
        for i, it in enumerate(items):
            cv = it.get('quantity', 0) * it.get('unit_cost', 0) * it.get('cost_exchange_rate', 1)
            rows.append({
                '#': i + 1, 'Cat': it.get('cogs_category', ''),
                'Product': (it.get('item_description', '') or '')[:40],
                'Vendor': (it.get('vendor_name', '') or '')[:25],
                'Qty': it.get('quantity', 0),
                'Cost': f"{it.get('unit_cost', 0):,.2f}",
                'CCY': it.get('cost_currency_code', ''),
                'Total VND': f"{cv:,.0f}",
            })
        tbl_key = f"wiz_li_{_wiz_get('tbl_ver', 0)}"
        event = st.dataframe(
            pd.DataFrame(rows), key=tbl_key, width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            column_config={
                '#': st.column_config.NumberColumn('#', width=35),
                'Cat': st.column_config.TextColumn('Cat', width=35),
                'Qty': st.column_config.NumberColumn('Qty', format="%.1f", width=55),
            },
        )

        # Subtotals
        a_t = _wiz_items_total('A')
        c_t = _wiz_items_total('C')
        st.caption(
            f"**{len(items)} items** | "
            f"A: {a_t:,.0f} ₫ | C: {c_t:,.0f} ₫ | "
            f"Sell: {_wiz_items_sell_total():,.0f} ₫"
        )

        # Row selection → Edit / Remove
        sel = event.selection.rows
        if sel:
            _sel_item = items[sel[0]]
            sc1, sc2, sc3, sc4 = st.columns([3, 1, 1, 1])
            sc1.caption(f"**#{sel[0]+1}** — {(_sel_item.get('item_description','') or '')[:50]}")
            if sc2.button("✏️ Edit", type="primary", use_container_width=True, key="wi_edit"):
                _wiz_set('edit_idx', sel[0])
                _wiz_set('show_add', False); _wiz_set('show_import', False); _wiz_set('show_manual', False)
            if sc3.button("🗑 Remove", use_container_width=True, key="wi_rm"):
                _wiz_remove_item(sel[0])
                _wiz_set('tbl_ver', _wiz_get('tbl_ver', 0) + 1)
                st.rerun()
            if sc4.button("✖", use_container_width=True, key="wi_desel"):
                _wiz_set('tbl_ver', _wiz_get('tbl_ver', 0) + 1)
                st.rerun()

        # Inline edit panel
        edit_idx = _wiz_get('edit_idx', -1)
        if 0 <= edit_idx < len(items):
            _wiz_panel_edit_item(edit_idx)

    else:
        st.info("No items yet. Use buttons above to add products.")

    # ── Navigation ──
    st.divider()
    n1, _, n2 = st.columns([1, 3, 1])
    if n1.button("← Back", use_container_width=True, key="wi_back"):
        _wiz_set('step', 1); st.rerun()
    if items:
        if n2.button("Next: Formula →", type="primary", use_container_width=True, key="wi_next"):
            _wiz_set('show_add', False); _wiz_set('show_import', False)
            _wiz_set('show_manual', False); _wiz_set('edit_idx', -1)
            _wiz_set('step', 3); st.rerun()
    else:
        n2.button("Next: Formula →", disabled=True, use_container_width=True, key="wi_next_dis",
                  help="Add at least one item")


# ── Step 2 inline panels ────────────────────────────────────────────────────

def _wiz_panel_add_product(category, proj):
    """Inline panel: search product catalog + costbook lookup."""
    with st.container(border=True):
        st.markdown(f"**🔍 Add Product — Category {category}**")
        is_svc = category == 'SERVICE'
        products = search_products('', is_service=is_svc if is_svc else None, limit=99999)
        if not products:
            st.info("No products found.")
            if st.button("Close", key="wp_close_add"): _wiz_set('show_add', False); st.rerun()
            return
        prod_opts = [f"{p['pt_code']} — {p['name']} [{p.get('brand_name', '')}]" for p in products]
        prod = products[prod_opts.index(st.selectbox("Select Product", prod_opts, key="wp_prod"))]
        st.caption(f"UOM: {prod.get('uom', '—')} | Brand: {prod.get('brand_name', '—')}")

        cbs = get_costbook_for_product(prod['id'])
        cb = None; _rc = None
        if cbs:
            cb_opts = [f"{c['costbook_number']} | {c['vendor_name']} | {c['unit_price']:,.2f} {c['currency_code']}" for c in cbs]
            cb = cbs[cb_opts.index(st.selectbox("Costbook Entry", cb_opts, key="wp_cb"))]
            _rc = get_rate_to_vnd(cb['currency_code'])
        qc1, qc2, qc3 = st.columns(3)
        qty = qc1.number_input("Quantity", value=1.0, min_value=0.01, format="%.2f", key="wp_qty")
        cp = float(cb['unit_price'] if cb else 0)
        cc = cb['currency_code'] if cb else 'VND'
        cr = _show_rate(qc2, f"Rate ({cc}→VND)", _rc) if _rc else 1.0
        if not cb:
            cp = qc3.number_input("Manual Cost", value=0.0, format="%.2f", key="wp_mc")
        else:
            qc3.metric("Cost VND", fmt_vnd(qty * cp * cr))

        ac1, ac2 = st.columns(2)
        if ac1.button("✅ Add Item", type="primary", use_container_width=True, key="wp_add"):
            _wiz_add_item({
                'cogs_category': category, 'product_id': prod['id'],
                'item_description': prod['name'], 'brand_name': prod.get('brand_name', ''),
                'pt_code': prod.get('pt_code', ''),
                'costbook_detail_id': cb['costbook_detail_id'] if cb else None,
                'vendor_name': cb['vendor_name'] if cb else '',
                'vendor_quote_ref': cb.get('vendor_quote_number', '') if cb else '',
                'costbook_number': cb['costbook_number'] if cb else '',
                'unit_cost': cp, 'cost_currency_code': cc,
                'cost_currency_id': cb['currency_id'] if cb else None, 'cost_exchange_rate': cr,
                'quotation_detail_id': None, 'unit_sell': 0, 'sell_currency_code': '',
                'sell_currency_id': None, 'sell_exchange_rate': 1.0,
                'quantity': qty, 'uom': prod.get('uom', 'Pcs'), 'notes': None,
            })
            st.success(f"✅ Added {prod['name']} × {qty}")
            _wiz_set('show_add', False); st.rerun()
        if ac2.button("Close", use_container_width=True, key="wp_close"):
            _wiz_set('show_add', False); st.rerun()


def _wiz_panel_import_costbook():
    """Inline panel: bulk import from costbook."""
    with st.container(border=True):
        st.markdown("**📦 Import from Costbook**")
        costbooks = get_active_costbooks()
        if not costbooks:
            st.warning("No active costbooks.")
            if st.button("Close", key="wpi_close_e"): _wiz_set('show_import', False); st.rerun()
            return
        cb_opts = [f"{c['costbook_number']} | {c['vendor_name']} | {c['line_count']} items" for c in costbooks]
        cb = costbooks[cb_opts.index(st.selectbox("Costbook", cb_opts, key="wpi_cb"))]
        prods = get_costbook_products_for_import(cb['id'])
        if not prods:
            st.info("No products in this costbook.")
            if st.button("Close", key="wpi_close_n"): _wiz_set('show_import', False); st.rerun()
            return
        st.caption(f"**{len(prods)} products** from {cb['vendor_name']}")
        # Dedup: exclude items already in wizard
        existing_pids = {it.get('product_id') for it in _wiz_items() if it.get('product_id')}
        new_prods = [p for p in prods if p['product_id'] not in existing_pids]
        if len(new_prods) < len(prods):
            st.caption(f"ℹ️ {len(prods) - len(new_prods)} already in list (skipped)")
        if not new_prods:
            st.success("All products already added!")
            if st.button("Close", key="wpi_close_a"): _wiz_set('show_import', False); st.rerun()
            return
        cc = new_prods[0].get('currency_code', 'USD')
        _r = get_rate_to_vnd(cc)
        er = _show_rate(st, f"Rate ({cc}→VND)", _r)
        ic1, ic2 = st.columns(2)
        if ic1.button(f"📦 Import {len(new_prods)} items", type="primary", use_container_width=True, key="wpi_do"):
            for p in new_prods:
                cat = 'SERVICE' if p.get('is_service') else 'A'
                _wiz_add_item({
                    'cogs_category': cat, 'product_id': p['product_id'],
                    'item_description': p['product_name'], 'brand_name': p.get('brand_name', ''),
                    'pt_code': p.get('pt_code', ''),
                    'costbook_detail_id': p['costbook_detail_id'], 'vendor_name': p.get('vendor_name', ''),
                    'vendor_quote_ref': p.get('vendor_quote_number', ''), 'costbook_number': p.get('costbook_number', ''),
                    'unit_cost': float(p.get('unit_price', 0) or 0), 'cost_currency_code': p.get('currency_code', ''),
                    'cost_currency_id': p.get('currency_id'), 'cost_exchange_rate': er,
                    'quotation_detail_id': None, 'unit_sell': 0, 'sell_currency_code': '',
                    'sell_currency_id': None, 'sell_exchange_rate': 1.0,
                    'quantity': 1, 'uom': p.get('uom', 'Pcs'), 'notes': None,
                })
            st.success(f"✅ Imported {len(new_prods)} items!")
            _wiz_set('show_import', False); st.rerun()
        if ic2.button("Close", use_container_width=True, key="wpi_close"):
            _wiz_set('show_import', False); st.rerun()


def _wiz_panel_manual_item():
    """Inline panel: add manual line item."""
    with st.container(border=True):
        st.markdown("**✏️ Manual Item**")
        mc1, mc2 = st.columns(2)
        m_cat = mc1.selectbox("Category", ["A", "C", "SERVICE"], key="wpm_cat")
        m_desc = mc2.text_input("Description *", key="wpm_desc")
        md1, md2, md3 = st.columns(3)
        m_qty = md1.number_input("Qty", value=1.0, min_value=0.01, format="%.2f", key="wpm_qty")
        m_price = md2.number_input("Unit Cost (VND)", value=0.0, format="%.0f", key="wpm_price")
        m_vendor = md3.text_input("Vendor", key="wpm_vendor")
        ac1, ac2 = st.columns(2)
        if ac1.button("✅ Add", type="primary", use_container_width=True, key="wpm_add"):
            if m_desc and m_price > 0:
                _wiz_add_item({
                    'cogs_category': m_cat, 'product_id': None, 'item_description': m_desc,
                    'brand_name': '', 'pt_code': '', 'costbook_detail_id': None, 'vendor_name': m_vendor,
                    'vendor_quote_ref': '', 'costbook_number': '', 'unit_cost': m_price,
                    'cost_currency_code': 'VND', 'cost_currency_id': None, 'cost_exchange_rate': 1.0,
                    'quotation_detail_id': None, 'unit_sell': 0, 'sell_currency_code': '',
                    'sell_currency_id': None, 'sell_exchange_rate': 1.0,
                    'quantity': m_qty, 'uom': 'Pcs', 'notes': None,
                })
                st.success(f"✅ Added {m_desc}")
                _wiz_set('show_manual', False); st.rerun()
            else:
                st.warning("Description and Cost required.")
        if ac2.button("Close", use_container_width=True, key="wpm_close"):
            _wiz_set('show_manual', False); st.rerun()


def _wiz_panel_edit_item(idx):
    """Inline panel: edit a line item."""
    items = _wiz_items()
    it = items[idx].copy()
    with st.container(border=True):
        st.markdown(f"**✏️ Edit Item #{idx + 1}** — {it.get('item_description', '—')}")
        e1, e2 = st.columns(2)
        co = ['A', 'C', 'SERVICE']
        ci = co.index(it.get('cogs_category', 'A')) if it.get('cogs_category') in co else 0
        nc = e1.selectbox("Category", co, index=ci, key="wpe_cat")
        nd = e2.text_input("Description", value=it.get('item_description', ''), key="wpe_desc")
        q1, q2, q3 = st.columns(3)
        nq = q1.number_input("Qty", value=float(it.get('quantity', 1)), min_value=0.01, format="%.2f", key="wpe_qty")
        nco = q2.number_input("Unit Cost", value=float(it.get('unit_cost', 0)), format="%.2f", key="wpe_cost")
        ncc = q3.text_input("Cost CCY", value=it.get('cost_currency_code', 'VND'), key="wpe_ccy")
        _re = get_rate_to_vnd(ncc)
        ncr = _re.rate if _re.ok else float(it.get('cost_exchange_rate', 1))
        nv = st.text_input("Vendor", value=it.get('vendor_name', '') or '', key="wpe_vendor")
        st.caption(f"Cost VND: **{fmt_vnd(nq * nco * ncr)}** | Rate: {ncr:,.2f}")
        bc1, bc2 = st.columns(2)
        if bc1.button("💾 Save Changes", type="primary", use_container_width=True, key="wpe_save"):
            it.update({
                'cogs_category': nc, 'item_description': nd, 'quantity': nq,
                'unit_cost': nco, 'cost_currency_code': ncc, 'cost_exchange_rate': ncr,
                'vendor_name': nv,
            })
            _wiz_update_item(idx, it)
            _wiz_set('edit_idx', -1); st.success("✅ Updated!"); st.rerun()
        if bc2.button("Cancel", use_container_width=True, key="wpe_cancel"):
            _wiz_set('edit_idx', -1); st.rerun()


# ── Step 3: COGS Formula + Live Preview + Save ──────────────────────────────

def _wiz_step3_formula(pid, proj, pt, active_est):
    items = _wiz_items()
    header = _wiz_get('header', {})
    prefill = _wiz_get('prefill_coeffs', {})
    nv = _wiz_get('next_version', 1)

    da = float(pt.get('default_alpha', 0.06))
    db = float(pt.get('default_beta', 0.40))
    dg = float(pt.get('default_gamma', 0.04))
    gt = float(pt.get('gp_go_threshold', 25))
    ct = float(pt.get('gp_conditional_threshold', 18))
    a_total = _wiz_items_total('A')
    c_total = _wiz_items_total('C')

    # Sales value (locked from contract)
    _bv = float(proj.get('contract_value_before_vat') or proj.get('contract_value') or 0)
    _er = float(proj.get('exchange_rate') or 1)
    sales_value = _bv * _er

    col_form, col_result = st.columns([3, 2])
    with col_form:
        with st.form("wiz_cogs_form"):
            # Sales display
            if sales_value > 0:
                st.metric("Sales Value (VND)", f"{sales_value:,.0f}")
                st.caption(f"🔒 From contract" + (f" (VAT {proj.get('vat_percent', 0)}%)" if proj.get('vat_percent') else ""))
            else:
                st.warning("⚠️ No contract value. Set in Projects page.")

            st.divider()
            st.markdown("**A — Equipment | C — Fabrication** (0 = use line items total)")
            ac1, ac2 = st.columns(2)
            a_ov = ac1.number_input("A Override", value=0.0, format="%.0f", help=f"Items: {a_total:,.0f} ₫")
            c_ov = ac2.number_input("C Override", value=0.0, format="%.0f", help=f"Items: {c_total:,.0f} ₫")

            st.divider()
            st.markdown("**B — Logistics** `B = A × α`")
            bc1, bc2 = st.columns([1, 2])
            alpha = bc1.number_input("α", value=float(prefill.get('alpha') or da), format="%.4f")
            b_m = bc2.number_input("B Override", value=0.0, format="%.0f")

            st.divider()
            st.markdown("**D — Direct Labor** `D = days × rate × team`")
            d1, d2, d3 = st.columns(3)
            md = d1.number_input("Man-Days", value=int(prefill.get('man_days') or 0), min_value=0)
            dr = d2.number_input("Daily Rate", value=float(prefill.get('day_rate') or 1_500_000), format="%.0f")
            ts = d3.number_input("Team Size", value=float(prefill.get('team_size') or 1.0), format="%.1f")
            d_m = st.number_input("D Override", value=0.0, format="%.0f")

            st.divider()
            st.markdown("**E — Travel & Site OH** `E = D × β`")
            ec1, ec2 = st.columns([1, 2])
            beta = ec1.number_input("β", value=float(prefill.get('beta') or db), format="%.4f")
            e_m = ec2.number_input("E Override", value=0.0, format="%.0f")

            st.divider()
            st.markdown("**F — Warranty Reserve** `F = (A+C) × γ`")
            fc1, fc2 = st.columns([1, 2])
            gamma = fc1.number_input("γ", value=float(prefill.get('gamma') or dg), format="%.4f")
            f_m = fc2.number_input("F Override", value=0.0, format="%.0f")

            submitted = st.form_submit_button("💾 Save & Activate", type="primary", use_container_width=True)

    # ── Live preview (right column) ──
    with col_result:
        st.markdown("### 📐 Live Estimate")
        ea = a_ov if a_ov > 0 else a_total
        ec = c_ov if c_ov > 0 else c_total
        es = sales_value if sales_value > 0 else _wiz_items_sell_total()
        res = calculate_estimate(
            a_equipment=ea, alpha=alpha, c_fabrication=ec,
            man_days=md, man_day_rate=dr, team_size=ts, beta=beta, gamma=gamma, sales_value=es,
            b_override=b_m if b_m > 0 else None, d_override=d_m if d_m > 0 else None,
            e_override=e_m if e_m > 0 else None, f_override=f_m if f_m > 0 else None,
        )
        cr = []
        for k in ['a', 'b', 'c', 'd', 'e', 'f']:
            v = res.get(k, 0)
            p = (v / res['total_cogs'] * 100) if res['total_cogs'] > 0 else 0
            cr.append({'Item': COGS_LABELS[k.upper()], 'Amount': f"{v:,.0f}", '%': f"{p:.1f}%"})
        cr.append({'Item': '**TOTAL COGS**', 'Amount': f"{res['total_cogs']:,.0f}", '%': ''})
        st.dataframe(pd.DataFrame(cr), width="stretch", hide_index=True,
                     column_config={'Amount': st.column_config.TextColumn('VND'),
                                    '%': st.column_config.TextColumn('%', width=60)})
        st.divider()
        r1, r2 = st.columns(2)
        r1.metric("Sales", fmt_vnd(res['sales']))
        r1.metric("COGS", fmt_vnd(res['total_cogs']))
        r2.metric("GP", fmt_vnd(res['gp']))
        r2.metric("GP%", f"{res['gp_percent']:.1f}%")
        gng = get_go_no_go(res['gp_percent'], gt, ct)
        st.divider()
        if gng == 'GO':
            st.success(f"### ✅ GO — {res['gp_percent']:.1f}%")
        elif gng == 'CONDITIONAL':
            st.warning(f"### ⚠️ CONDITIONAL — {res['gp_percent']:.1f}%")
        else:
            st.error(f"### ❌ NO-GO — {res['gp_percent']:.1f}%")
        st.caption(f"{len(items)} items | A={'items' if a_ov == 0 else 'override'}")

    # ── Back button (outside form) ──
    if st.button("← Back to Items", key="wf_back"):
        _wiz_set('step', 2); st.rerun()

    # ── Save logic ──
    if submitted:
        if ea <= 0 and ec <= 0 and md <= 0 and es <= 0:
            st.warning("Enter at least one cost + Sales.")
            return
        ln = "; ".join([
            f"{it.get('cogs_category', '')}: {(it.get('item_description', '') or '')[:25]} x{it.get('quantity', 0):.0f}"
            for it in items[:10]
        ])
        if len(items) > 10:
            ln += f" (+{len(items) - 10})"
        gs = get_go_no_go(res['gp_percent'], gt, ct)
        notes = header.get('notes', '')
        est_files = header.get('files', [])
        est_data = {
            'project_id': pid, 'estimate_version': nv,
            'estimate_label': header.get('label', f"Rev {nv}"),
            'estimate_type': header.get('est_type', 'DETAILED'),
            'a_equipment_cost': ea, 'a_equipment_notes': ln[:500] or None,
            'alpha_rate': alpha, 'b_logistics_import': res['b'], 'b_override': 1 if b_m > 0 else 0,
            'c_custom_fabrication': ec, 'c_fabrication_notes': None,
            'd_man_days': md, 'd_man_day_rate': dr, 'd_team_size': ts,
            'd_direct_labor': res['d'], 'd_override': 1 if d_m > 0 else 0,
            'beta_rate': beta, 'e_travel_site_oh': res['e'], 'e_override': 1 if e_m > 0 else 0,
            'gamma_rate': gamma, 'f_warranty_reserve': res['f'], 'f_override': 1 if f_m > 0 else 0,
            'total_cogs': res['total_cogs'], 'sales_value': res['sales'],
            'estimated_gp': res['gp'], 'estimated_gp_percent': res['gp_percent'],
            'go_no_go_result': gs, 'assessment_notes': notes or None,
        }
        try:
            nid = create_estimate(est_data, user_id)
            activate_estimate(pid, nid, user_id)
            for i, it in enumerate(items):
                ld = _sanitize_item({
                    'estimate_id': nid, 'cogs_category': it.get('cogs_category', 'A'),
                    'product_id': it.get('product_id'), 'item_description': it.get('item_description', ''),
                    'brand_name': it.get('brand_name', ''), 'pt_code': it.get('pt_code', ''),
                    'costbook_detail_id': it.get('costbook_detail_id'),
                    'vendor_name': it.get('vendor_name', ''), 'vendor_quote_ref': it.get('vendor_quote_ref', ''),
                    'costbook_number': it.get('costbook_number', ''),
                    'unit_cost': it.get('unit_cost', 0), 'cost_currency_id': it.get('cost_currency_id'),
                    'cost_exchange_rate': it.get('cost_exchange_rate', 1),
                    'quotation_detail_id': it.get('quotation_detail_id'),
                    'unit_sell': it.get('unit_sell', 0), 'sell_currency_id': it.get('sell_currency_id'),
                    'sell_exchange_rate': it.get('sell_exchange_rate', 1),
                    'quantity': it.get('quantity', 1), 'uom': it.get('uom', 'Pcs'),
                    'notes': it.get('notes'), 'view_order': i,
                })
                create_estimate_line_item(ld, user_id)
            s3 = _get_s3()
            if s3 and est_files:
                for f in est_files:
                    ok, sk = s3.upload_project_file(f.read(), f.name, pid)
                    if ok:
                        create_estimate_media(nid, sk, f.name, document_type='OTHER', created_by=user_id)
            st.success(f"✅ Rev {nv} saved with {len(items)} line items!")
            _wiz_cleanup()
            _invalidate_estimates()
            _invalidate_dashboard()
            _load_projects.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Save failed: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# FRAGMENT: Active Estimate
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment
def _frag_active_estimate(pid, _can_view_costs):
    est = get_active_estimate(pid)
    if not est:
        st.info("No active estimate. Go to **📝 New Estimate** tab to create one."); return
    gng = est.get('go_no_go_result','')
    h1, h2 = st.columns([4,1])
    h1.markdown(f"### Rev {est['estimate_version']} — {est.get('estimate_label','')}")
    if gng == 'GO': h2.success("✅ GO")
    elif gng == 'CONDITIONAL': h2.warning("⚠️ COND")
    elif gng == 'NO_GO': h2.error("❌ NO-GO")

    if _can_view_costs:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Sales", fmt_vnd(est.get('sales_value'))); m2.metric("COGS", fmt_vnd(est.get('total_cogs')))
        m3.metric("GP", fmt_vnd(est.get('estimated_gp'))); m4.metric("GP%", fmt_percent(est.get('estimated_gp_percent')))
    else:
        m1, m2 = st.columns(2)
        m1.metric("Sales Value", fmt_vnd(est.get('sales_value'))); m2.metric("Result", gng or '—')
        st.caption("💡 Chi tiết vendor cost / GP chỉ hiển thị cho PM, SA, và Admin.")

    # Sub-tabs
    st1, st2, st3 = st.tabs(["📋 Line Items", "📊 COGS Breakdown", "🔗 Contract Alignment"])
    with st1:
        li_df = get_estimate_line_items(est['id'])
        if li_df.empty: st.info("No line items."); return
        st.caption(f"**{len(li_df)} line items**")
        disp = li_df.copy()
        if _can_view_costs:
            disp['cost_total'] = disp['amount_cost_vnd'].apply(lambda v: f"{v:,.0f}" if v and str(v) not in ('','nan','None') else '—')
            disp['sell_total'] = disp['amount_sell_vnd'].apply(lambda v: f"{v:,.0f}" if v and str(v) not in ('','nan','None','0','0.0') else '—')
            st.dataframe(disp, width="stretch", hide_index=True,
                column_config={'cogs_category':st.column_config.TextColumn('Cat',width=35),
                    'item_description':st.column_config.TextColumn('Product'),
                    'brand_name':st.column_config.TextColumn('Brand',width=80),
                    'vendor_name':st.column_config.TextColumn('Vendor'),
                    'quantity':st.column_config.NumberColumn('Qty',format="%.1f",width=55),
                    'unit_cost':st.column_config.NumberColumn('Cost',format="%.2f"),
                    'cost_currency':st.column_config.TextColumn('CCY',width=40),
                    'cost_total':st.column_config.TextColumn('Cost VND'),
                    'sell_total':st.column_config.TextColumn('Sell VND'),
                    'costbook_number':st.column_config.TextColumn('Costbook'),
                    'id':None,'product_id':None,'pt_code':None,'costbook_detail_id':None,
                    'quotation_detail_id':None,'unit_sell':None,'sell_currency':None,
                    'sell_exchange_rate':None,'cost_exchange_rate':None,'uom':None,
                    'view_order':None,'amount_cost_vnd':None,'amount_sell_vnd':None,
                    'notes':None,'vendor_quote_ref':None})
        else:
            st.dataframe(disp, width="stretch", hide_index=True,
                column_config={'cogs_category':st.column_config.TextColumn('Cat',width=35),
                    'item_description':st.column_config.TextColumn('Product'),
                    'brand_name':st.column_config.TextColumn('Brand',width=80),
                    'quantity':st.column_config.NumberColumn('Qty',format="%.1f",width=55),
                    'uom':st.column_config.TextColumn('UOM',width=50),
                    'id':None,'product_id':None,'pt_code':None,'costbook_detail_id':None,
                    'quotation_detail_id':None,'unit_cost':None,'unit_sell':None,
                    'cost_currency':None,'sell_currency':None,'cost_exchange_rate':None,
                    'sell_exchange_rate':None,'vendor_name':None,'vendor_quote_ref':None,
                    'costbook_number':None,'view_order':None,'amount_cost_vnd':None,
                    'amount_sell_vnd':None,'notes':None})
        # Attachments
        ea = get_estimate_medias(est['id'])
        if ea:
            st.divider(); st.caption(f"**📎 Attachments ({len(ea)})**")
            s3 = _get_s3()
            for a in ea:
                url = s3.get_presigned_url(a['s3_key'], expiration=600) if s3 else None
                cl = st.columns([4,1])
                cl[0].markdown(f"📄 **{a['filename']}**" + (f" — {a['description']}" if a.get('description') else ""))
                if url: cl[1].markdown(f"[⬇️ Download]({url})")

    with st2:
        if not _can_view_costs: st.info("COGS details visible to PM, SA, Admin only."); return
        fm = {'A':'a_equipment_cost','B':'b_logistics_import','C':'c_custom_fabrication',
              'D':'d_direct_labor','E':'e_travel_site_oh','F':'f_warranty_reserve'}
        tc = float(est.get('total_cogs',0) or 0)
        rows = [{'Item':COGS_LABELS[k],'Amount':f"{float(est.get(f,0) or 0):,.0f}",
                 '%':f"{float(est.get(f,0) or 0)/tc*100:.1f}%" if tc > 0 else '—'} for k,f in fm.items()]
        rows.append({'Item':'**TOTAL**','Amount':f"{tc:,.0f}",'%':''})
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        if est.get('assessment_notes'): st.info(f"📝 {est['assessment_notes']}")
        st.caption(f"α={est.get('alpha_rate','—')} | β={est.get('beta_rate','—')} | γ={est.get('gamma_rate','—')} | "
                   f"D: {est.get('d_man_days','—')}d × {fmt_vnd(est.get('d_man_day_rate'))} × {est.get('d_team_size','—')}")

    with st3:
        if not _can_view_costs: st.info("Contract alignment visible to PM, SA, Admin only."); return
        try:
            from utils.il_project.queries import get_contract_alignment
            al = get_contract_alignment(pid)
            if not al or (al['contract_before_vat'] == 0 and al['estimate_sales'] == 0):
                st.info("No contract/estimate data."); return
            a1, a2 = st.columns(2)
            _cbv=al['contract_before_vat']; _es=al['estimate_sales']
            _mt=abs(_cbv-_es)/_cbv*100 if _cbv>0 and _es>0 else None
            a1.markdown(f"**Contract (Before VAT):** {fmt_vnd(_cbv)}")
            if _mt is not None:
                a1.markdown(f"**Estimate Sales:** {fmt_vnd(_es)} {'✅ Match' if _mt<1 else f'⚠️ {_mt:.1f}% diff'}")
            else: a1.markdown(f"**Estimate Sales:** {fmt_vnd(_es)}")
            a2.markdown(f"**Contract (After VAT):** {fmt_vnd(al['contract_after_vat'])}")
            if al['milestone_count']>0:
                _mi = "✅" if abs(al['milestone_pct']-100)<1 else "⚠️"
                a2.markdown(f"**Milestones:** {fmt_vnd(al['milestone_billing_total'])} ({al['milestone_count']}, {al['milestone_pct']}%) {_mi}")
            else: a2.markdown("**Milestones:** None")
            st.markdown("---")
            p1, p2, p3 = st.columns(3)
            p1.metric("Estimate COGS", fmt_vnd(al['estimate_cogs']))
            p2.metric("PR Total", fmt_vnd(al['pr_all_total']),
                delta=f"{al['pr_pct_of_estimate']}% of est" if al['pr_pct_of_estimate']>0 else None, delta_color="off")
            ov=al['cogs_overrun_pct']
            if ov is not None:
                p3.metric("Actual COGS", fmt_vnd(al['cogs_actual_total']),
                    delta=f"{ov:+.1f}% vs est", delta_color="inverse" if ov>5 else "off")
            else: p3.metric("Actual COGS", fmt_vnd(al['cogs_actual_total']) if al['cogs_actual_total']>0 else "—")
        except Exception as e: logger.debug(f"Contract alignment: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# FRAGMENT: History
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment
def _frag_history(pid, _can_view_costs, _can_activate):
    all_est = get_estimates(pid)
    if not all_est: st.info("No estimates."); return
    if _can_view_costs:
        hist = [{'':'✅' if e.get('is_active') else '','Rev':e['estimate_version'],
            'Label':e.get('estimate_label',''),'Type':e.get('estimate_type',''),
            'COGS':f"{float(e.get('total_cogs',0) or 0):,.0f}",
            'Sales':f"{float(e.get('sales_value',0) or 0):,.0f}",
            'GP%':fmt_percent(e.get('estimated_gp_percent')),'Result':e.get('go_no_go_result','—'),
            'α':e.get('alpha_rate',''),'β':e.get('beta_rate',''),'γ':e.get('gamma_rate',''),
            'Created':e.get('created_date')} for e in all_est]
    else:
        hist = [{'':'✅' if e.get('is_active') else '','Rev':e['estimate_version'],
            'Label':e.get('estimate_label',''),'Type':e.get('estimate_type',''),
            'Result':e.get('go_no_go_result','—'),'Created':e.get('created_date')} for e in all_est]
    st.dataframe(pd.DataFrame(hist), width="stretch", hide_index=True,
        column_config={'':st.column_config.TextColumn('',width=30),'Rev':st.column_config.NumberColumn('Rev',width=50),
            'α':st.column_config.NumberColumn('α',format="%.4f",width=70),
            'β':st.column_config.NumberColumn('β',format="%.4f",width=70),
            'γ':st.column_config.NumberColumn('γ',format="%.4f",width=70)})
    if _can_activate and len(all_est) > 1:
        st.divider()
        rv = [f"Rev {e['estimate_version']} — {e.get('estimate_label','')}" for e in all_est]
        se = all_est[rv.index(st.selectbox("Activate version", rv))]
        if st.button("🔄 Activate Selected", type="primary"):
            if activate_estimate(pid, se['id'], user_id):
                st.success(f"Rev {se['estimate_version']} activated!")
                _invalidate_estimates(); _invalidate_dashboard(); _load_projects.clear(); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# NEW ESTIMATE TAB — button opens wizard dialog
# ══════════════════════════════════════════════════════════════════════════════
def _render_new_estimate_tab(pid, proj, pt, active_est, _can_create, _can_view_costs):
    if not _can_create:
        st.info("⛔ Bạn không có quyền tạo estimate. Chỉ PM, SA/Senior, hoặc Admin.")
        st.caption("Chuyển sang tab **✅ Active Estimate** để xem.")
        return

    st.markdown(f"**Project:** `{proj['project_code']}` — {proj['project_name']}")

    if active_est:
        from utils.il_project.helpers import go_no_go_badge
        gng = active_est.get('go_no_go_result', '')
        _badge = go_no_go_badge(gng)
        st.info(
            f"📋 Current active: **Rev {active_est['estimate_version']}** — "
            f"{active_est.get('estimate_label', '')} | "
            f"GP: {fmt_percent(active_est.get('estimated_gp_percent'))} | "
            f"{_badge}"
        )
        st.caption("Creating a new revision will build on the active estimate's data (items + coefficients).")

    st.divider()
    if st.button("➕ Create New Estimate Revision", type="primary", use_container_width=True):
        _wiz_init(active_est, pid)
        st.session_state['_est_open_create'] = True
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# MAIN LAYOUT
# ══════════════════════════════════════════════════════════════════════════════

if is_all_projects:
    _render_dashboard()
else:
    if not project: st.error("Project not found."); st.stop()
    pt = type_map.get(project.get('project_type_id', 0), {})

    if not ctx.can('estimate.view', project_id):
        st.warning("⛔ Bạn không có quyền xem Estimate của dự án này."); st.stop()

    _can_view_costs = ctx.can('estimate.view_costs', project_id)
    _can_create     = ctx.can('estimate.create', project_id)
    _can_activate   = ctx.can('estimate.activate', project_id)
    active_est      = get_active_estimate(project_id)

    _render_context_banner(project, active_est)
    st.divider()

    tab_active, tab_new, tab_history = st.tabs(["✅ Active Estimate", "📝 New Estimate", "🗂 History"])

    with tab_active:
        _frag_active_estimate(project_id, _can_view_costs)
    with tab_new:
        _render_new_estimate_tab(project_id, project, pt, active_est, _can_create, _can_view_costs)
    with tab_history:
        _frag_history(project_id, _can_view_costs, _can_activate)

    # ── Dialog trigger (use get, not pop — dialog survives st.rerun in wizard steps) ──
    if st.session_state.get('_est_open_create') and project_id:
        _dialog_create_estimate(project_id, project, pt, active_est)