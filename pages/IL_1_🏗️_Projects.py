# pages/IL_1_🏗️_Projects.py
"""
IL Projects — Master list + Create / Edit
"""

import streamlit as st
import pandas as pd
from datetime import date
import logging

from utils.auth import AuthManager
from utils.il_project import (
    get_projects_df, get_project, create_project, update_project, soft_delete_project,
    get_project_types, get_employees, get_companies, get_currencies, get_milestones_df,
    create_milestone, update_milestone, generate_project_code,
    fmt_vnd, fmt_percent, STATUS_COLORS,
)

logger = logging.getLogger(__name__)
auth = AuthManager()

st.set_page_config(page_title="IL Projects", page_icon="🏗️", layout="wide")


# ══════════════════════════════════════════════════════════════════════════════
# Helper — must be defined before page body calls it
# ══════════════════════════════════════════════════════════════════════════════

def _render_milestones_tab(project_id: int, uid: str, currs: list):
    ms_df = get_milestones_df(project_id)
    if not ms_df.empty:
        st.dataframe(
            ms_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                'sequence_no':     st.column_config.NumberColumn('#', width=40),
                'milestone_name':  st.column_config.TextColumn('Milestone'),
                'milestone_type':  st.column_config.TextColumn('Type'),
                'billing_percent': st.column_config.NumberColumn('Billing%', format="%.1f%%"),
                'billing_amount':  st.column_config.NumberColumn('Amount', format="%.0f"),
                'planned_date':    st.column_config.DateColumn('Planned'),
                'actual_date':     st.column_config.DateColumn('Actual'),
                'status':          st.column_config.TextColumn('Status'),
            }
        )
    else:
        st.info("No milestones yet.")

    with st.expander("➕ Add Milestone"):
        with st.form(f"ms_form_{project_id}"):
            mc1, mc2, mc3 = st.columns(3)
            ms_seq   = mc1.number_input("Sequence #", min_value=1, value=len(ms_df)+1)
            ms_name  = mc2.text_input("Milestone Name *")
            ms_types = ['DELIVERY','PAYMENT','ACCEPTANCE','HANDOVER','WARRANTY_START','OTHER']
            ms_type  = mc3.selectbox("Type", ms_types)
            md1, md2, md3 = st.columns(3)
            ms_bpct  = md1.number_input("Billing % (0=none)", min_value=0.0, max_value=100.0, value=0.0)
            ms_bamt  = md2.number_input("Billing Amount (0=none)", min_value=0.0, value=0.0, format="%.0f")
            ms_plan  = md3.date_input("Planned Date")
            ms_stat_opts = ['PENDING','IN_PROGRESS','COMPLETED','INVOICED','PAID','OVERDUE']
            ms_stat  = st.selectbox("Status", ms_stat_opts)
            ms_notes = st.text_input("Completion Notes")
            cur_opts2 = [c['code'] for c in currs]
            ms_cur   = st.selectbox("Currency", cur_opts2)
            ms_cur_id= currs[cur_opts2.index(ms_cur)]['id']

            if st.form_submit_button("Add Milestone", type="primary"):
                if not ms_name:
                    st.error("Name required.")
                elif ms_bpct > 0 and ms_bamt > 0:
                    st.error("Set either Billing % OR Amount, not both.")
                else:
                    create_milestone({
                        'project_id': project_id,
                        'sequence_no': ms_seq,
                        'milestone_name': ms_name,
                        'milestone_type': ms_type,
                        'billing_percent': ms_bpct if ms_bpct > 0 else None,
                        'billing_amount': ms_bamt if ms_bamt > 0 else None,
                        'currency_id': ms_cur_id,
                        'planned_date': ms_plan,
                        'actual_date': None,
                        'status': ms_stat,
                        'completion_notes': ms_notes or None,
                    }, uid)
                    st.success("Milestone added!")
                    st.rerun()

# ── Auth ───────────────────────────────────────────────────────────────────────
auth.require_auth()
user_id    = str(auth.get_user_id())
user_role  = st.session_state.get('user_role', '')
is_admin   = auth.is_admin()

# ── Lookups (cached) ───────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load_lookups():
    types      = get_project_types()
    employees  = get_employees()
    companies  = get_companies()
    currencies = get_currencies()
    return types, employees, companies, currencies

proj_types, employees, companies, currencies = _load_lookups()

type_map     = {t['id']: f"[{t['code']}] {t['name']}" for t in proj_types}
emp_map      = {e['id']: e['full_name'] for e in employees}
company_map  = {c['id']: c['name'] for c in companies}
currency_map = {c['id']: c['code'] for c in currencies}

# ── Page header ────────────────────────────────────────────────────────────────
st.title("🏗️ IL Projects")

# ── Sidebar filters ────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filters")
    f_search = st.text_input("Search", placeholder="code / name / customer")
    f_status = st.selectbox("Status", ["All", "DRAFT", "ESTIMATING", "PROPOSAL_SENT",
                                        "GO", "CONDITIONAL", "NO_GO", "CONTRACTED",
                                        "IN_PROGRESS", "COMMISSIONING", "COMPLETED",
                                        "WARRANTY", "CLOSED", "CANCELLED"])
    f_type   = st.selectbox("Project Type", ["All"] + [f"[{t['code']}] {t['name']}" for t in proj_types])
    f_pm     = st.selectbox("PM", ["All"] + [e['full_name'] for e in employees])

    st.divider()
    if st.button("➕ New Project", use_container_width=True, type="primary"):
        st.session_state.il_edit_mode   = "create"
        st.session_state.il_selected_id = None

# ── Resolve filter values ──────────────────────────────────────────────────────
status_filter  = None if f_status == "All" else f_status
type_filter_id = None
if f_type != "All":
    code = f_type.split("]")[0][1:]
    hit = next((t for t in proj_types if t['code'] == code), None)
    type_filter_id = hit['id'] if hit else None
pm_filter_id = None
if f_pm != "All":
    hit = next((e for e in employees if e['full_name'] == f_pm), None)
    pm_filter_id = hit['id'] if hit else None

# ── Load project list ──────────────────────────────────────────────────────────
df = get_projects_df(
    status=status_filter,
    type_id=type_filter_id,
    pm_id=pm_filter_id,
    search=f_search or None,
)

# ── Summary KPIs ───────────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Projects", len(df))
col2.metric("In Progress", len(df[df['status'] == 'IN_PROGRESS']) if not df.empty else 0)
col3.metric("Avg Est. GP%",
    f"{df['estimated_gp_percent'].mean():.1f}%" if not df.empty and df['estimated_gp_percent'].notna().any() else "—")
col4.metric("Avg Actual GP%",
    f"{df['actual_gp_percent'].mean():.1f}%" if not df.empty and df['actual_gp_percent'].notna().any() else "—")

st.divider()

# ── Project table ──────────────────────────────────────────────────────────────
if df.empty:
    st.info("No projects found. Create one using the sidebar.")
else:
    display_df = df[[
        'project_code', 'project_name', 'project_type', 'customer_name',
        'status', 'pm_name',
        'effective_contract_value', 'currency_code',
        'estimated_gp_percent', 'actual_gp_percent',
        'estimated_start_date', 'estimated_end_date',
    ]].copy()

    # Status icon
    display_df.insert(0, '●', display_df['status'].map(lambda s: STATUS_COLORS.get(s, '⚪')))

    event = st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            '●':                        st.column_config.TextColumn('', width=30),
            'project_code':             st.column_config.TextColumn('Code'),
            'project_name':             st.column_config.TextColumn('Project Name'),
            'project_type':             st.column_config.TextColumn('Type'),
            'customer_name':            st.column_config.TextColumn('Customer'),
            'status':                   st.column_config.TextColumn('Status'),
            'pm_name':                  st.column_config.TextColumn('PM'),
            'effective_contract_value': st.column_config.NumberColumn('Contract Value', format="%.0f"),
            'currency_code':            st.column_config.TextColumn('CCY', width=50),
            'estimated_gp_percent':     st.column_config.NumberColumn('Est. GP%', format="%.1f%%"),
            'actual_gp_percent':        st.column_config.NumberColumn('Act. GP%', format="%.1f%%"),
            'estimated_start_date':     st.column_config.DateColumn('Start'),
            'estimated_end_date':       st.column_config.DateColumn('End'),
        }
    )

    # Row click → open detail
    sel = event.selection.rows
    if sel:
        pid = int(df.iloc[sel[0]]['project_id'])
        if st.session_state.get('il_selected_id') != pid:
            st.session_state.il_selected_id = pid
            st.session_state.il_edit_mode   = "view"

# ══════════════════════════════════════════════════════════════════════════════
# CREATE / EDIT / VIEW PANEL
# ══════════════════════════════════════════════════════════════════════════════

mode = st.session_state.get('il_edit_mode')
if not mode:
    st.stop()

st.divider()

# ── View / Edit header ─────────────────────────────────────────────────────────
if mode == "view":
    pid  = st.session_state.get('il_selected_id')
    proj = get_project(pid) if pid else None
    if not proj:
        st.warning("Project not found.")
        st.stop()

    hcol1, hcol2, hcol3 = st.columns([4, 1, 1])
    hcol1.subheader(f"{STATUS_COLORS.get(proj['status'],'⚪')} {proj['project_code']} — {proj['project_name']}")
    if hcol2.button("✏️ Edit", use_container_width=True):
        st.session_state.il_edit_mode = "edit"
        st.rerun()
    if is_admin and hcol3.button("🗑 Delete", use_container_width=True):
        if soft_delete_project(pid, user_id):
            st.success("Project deleted.")
            st.cache_data.clear()
            for k in ['il_edit_mode','il_selected_id']:
                st.session_state.pop(k, None)
            st.rerun()

    # Quick stats
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Status", proj['status'])
    m2.metric("Contract Value", fmt_vnd(proj.get('contract_value')))
    m3.metric("Est. GP%", fmt_percent(proj.get('estimated_gp_percent')))
    m4.metric("Actual GP%", fmt_percent(proj.get('actual_gp_percent')))

    # Detail tabs
    tab_info, tab_milestones = st.tabs(["📋 Info", "🎯 Milestones"])

    with tab_info:
        c1, c2 = st.columns(2)
        c1.markdown(f"**Customer:** {proj.get('customer_name') or proj.get('end_customer_name') or '—'}")
        c1.markdown(f"**Type:** {proj.get('type_name','—')}")
        c1.markdown(f"**Location:** {proj.get('location','—')} ({proj.get('site_distance_category','—')})")
        c1.markdown(f"**PM:** {proj.get('pm_name','—')}")
        c1.markdown(f"**Sales:** {proj.get('sales_name','—')}")
        c2.markdown(f"**Billing Type:** {proj.get('billing_type','—')}")
        c2.markdown(f"**Import Category:** {proj.get('import_category','—')}")
        c2.markdown(f"**Environment:** {proj.get('environment_category','—')}")
        c2.markdown(f"**Warranty:** {proj.get('warranty_months','—')} months ({proj.get('warranty_type','—')})")
        if proj.get('decision_notes'):
            st.markdown(f"**Decision Notes:** {proj['decision_notes']}")

    with tab_milestones:
        _render_milestones_tab(pid, user_id, currencies)

    st.stop()

# ── Create / Edit form ─────────────────────────────────────────────────────────
is_create = (mode == "create")
pid       = st.session_state.get('il_selected_id')
proj      = (get_project(pid) if pid else None) or {}

st.subheader("➕ New Project" if is_create else "✏️ Edit Project")

with st.form("il_project_form", clear_on_submit=False):
    st.markdown("**Basic Information**")
    fc1, fc2, fc3 = st.columns(3)

    # Project code: auto-generated for new, read-only for edit
    if is_create:
        auto_code = generate_project_code(auth.get_user_id())
        fc1.text_input("Project Code", value=auto_code, disabled=True,
                       help="Auto-generated: IL-YYYY-{user_id}-NNN")
        project_code = auto_code
    else:
        fc1.text_input("Project Code", value=proj.get('project_code', ''), disabled=True,
                       help="System-generated, read-only")
        project_code = proj.get('project_code', '')

    contract_num = fc2.text_input("Contract Number", value=proj.get('contract_number') or '',
                                   help="Số hợp đồng chính thức từ khách hàng. Có thể khác Project Code. Ví dụ: HĐ-2025-FOXCONN-001")
    project_name = fc3.text_input("Project Name *", value=proj.get('project_name',''),
                                   help="Tên dự án đầy đủ, mô tả rõ scope. Ví dụ: AMR Transport System — Foxconn Bắc Giang Line 3")

    ft1, ft2, ft3 = st.columns(3)
    type_options  = [f"[{t['code']}] {t['name']}" for t in proj_types]
    current_type  = type_map.get(proj.get('project_type_id',''))
    type_idx      = type_options.index(current_type) if current_type in type_options else 0
    type_sel      = ft1.selectbox("Project Type", type_options, index=type_idx,
                                   help="Loại dự án intralogistics. Ảnh hưởng đến hệ số α/β/γ mặc định và benchmark man-days.")
    type_id_sel   = proj_types[[t['code'] for t in proj_types].index(type_sel.split("]")[0][1:])]['id']

    billing_types = ['LUMP_SUM','MILESTONE','TIME_MATERIAL','MIXED']
    billing_idx   = billing_types.index(proj['billing_type']) if proj.get('billing_type') in billing_types else 0
    billing_sel   = ft2.selectbox("Billing Type", billing_types, index=billing_idx,
                                   help="LUMP_SUM: thanh toán 1 lần hoặc theo % cố định.\nMILESTONE: thanh toán theo từng mốc nghiệm thu.\nTIME_MATERIAL: tính theo man-days + vật tư thực tế.\nMIXED: kết hợp nhiều hình thức.")

    statuses   = ['DRAFT','ESTIMATING','PROPOSAL_SENT','GO','CONDITIONAL','NO_GO',
                  'CONTRACTED','IN_PROGRESS','COMMISSIONING','COMPLETED','WARRANTY','CLOSED','CANCELLED']
    status_idx = statuses.index(proj['status']) if proj.get('status') in statuses else 0
    status_sel = ft3.selectbox("Status", statuses, index=status_idx,
                                help="DRAFT: mới tạo, chưa estimate.\nESTIMATING: đang tính COGS/GP.\nPROPOSAL_SENT: đã gửi đề xuất.\nGO/CONDITIONAL/NO_GO: kết quả Go/No-Go.\nCONTRACTED: đã ký HĐ.\nIN_PROGRESS: đang triển khai.\nCOMMISSIONING: đang chạy thử.\nCOMPLETED: đã bàn giao.\nWARRANTY: trong bảo hành.\nCLOSED: đã đóng sổ.")

    st.markdown("**Customer**")
    cc1, cc2 = st.columns([2,2])
    company_opts  = ["(Not in system)"] + [c['name'] for c in companies]
    company_idx   = next((i+1 for i,c in enumerate(companies) if c['id']==proj.get('customer_id')), 0)
    company_sel   = cc1.selectbox("Customer (Companies)", company_opts, index=company_idx,
                                   help="Chọn từ danh sách công ty đã có trong hệ thống.\nNếu chưa có, chọn '(Not in system)' và điền tên bên dưới.")
    customer_id   = companies[company_opts.index(company_sel)-1]['id'] if company_sel != "(Not in system)" else None
    end_cust_name = cc2.text_input("Customer Name (free text)", value=proj.get('end_customer_name') or '',
                                    help="Điền tên khách hàng nếu chưa có trong hệ thống, hoặc tên end-customer khác với bên ký HĐ.")

    st.markdown("**Financial**")
    fm1, fm2, fm3, fm4 = st.columns(4)
    contract_val  = fm1.number_input("Contract Value", value=float(proj.get('contract_value') or 0), min_value=0.0, format="%.0f",
                                      help="Giá trị hợp đồng ban đầu (theo đồng tiền HĐ). Chưa bao gồm amendment/variation order.")
    amended_val   = fm2.number_input("Amended Value (0=none)", value=float(proj.get('amended_contract_value') or 0), min_value=0.0, format="%.0f",
                                      help="Giá trị sau khi có Variation Order / Amendment. Để 0 nếu không có thay đổi.\nHệ thống sẽ dùng giá trị này cho tính toán GP thực tế.")
    cur_opts      = [c['code'] for c in currencies]
    cur_idx       = next((i for i,c in enumerate(currencies) if c['id']==proj.get('currency_id')), 0)
    cur_sel       = fm3.selectbox("Currency", cur_opts, index=cur_idx,
                                   help="Đồng tiền trong hợp đồng với khách hàng.")
    currency_id   = currencies[cur_opts.index(cur_sel)]['id']
    exc_rate      = fm4.number_input("Exchange Rate", value=float(proj.get('exchange_rate') or 1.0), format="%.4f",
                                      help="Tỷ giá quy đổi sang VND tại thời điểm ký HĐ.\nVí dụ: USD → VND = 25,000. VND = 1.")

    st.markdown("**Location & Environment**")
    fl1, fl2, fl3, fl4 = st.columns(4)
    location      = fl1.text_input("Location", value=proj.get('location') or '',
                                    help="Địa chỉ / tỉnh thành triển khai dự án. Ví dụ: KCN Vân Trung, Bắc Giang")
    dist_opts     = ['LOCAL','NEARBY','FAR','OVERSEAS']
    dist_idx      = dist_opts.index(proj['site_distance_category']) if proj.get('site_distance_category') in dist_opts else 1
    dist_sel      = fl2.selectbox("Distance", dist_opts, index=dist_idx,
                                   help="LOCAL: nội thành Hà Nội (di chuyển trong ngày).\nNEARBY: < 100km, ví dụ Hà Nam, Hưng Yên.\nFAR: > 100km, ví dụ Hải Phòng, Bình Dương.\nOVERSEAS: ngoài Việt Nam.\n→ Ảnh hưởng đến hệ số β (Travel & Site OH).")
    env_opts      = ['CLEAN','NORMAL','HARSH']
    env_idx       = env_opts.index(proj['environment_category']) if proj.get('environment_category') in env_opts else 1
    env_sel       = fl3.selectbox("Environment", env_opts, index=env_idx,
                                   help="CLEAN: văn phòng, cleanroom, ít rủi ro hỏng hóc.\nNORMAL: nhà máy thông thường.\nHARSH: môi trường bụi, ẩm, hóa chất, nhiệt độ cao.\n→ Ảnh hưởng đến hệ số γ (Warranty Reserve).")
    imp_opts      = ['DOMESTIC','IMPORTED','MIXED']
    imp_idx       = imp_opts.index(proj['import_category']) if proj.get('import_category') in imp_opts else 1
    imp_sel       = fl4.selectbox("Import Category", imp_opts, index=imp_idx,
                                   help="DOMESTIC: thiết bị mua trong nước, không có chi phí nhập khẩu.\nIMPORTED: nhập khẩu hoàn toàn (freight + insurance + thuế NK + customs).\nMIXED: vừa mua nội địa vừa nhập khẩu.\n→ Ảnh hưởng đến hệ số α (Logistics & Import).")

    st.markdown("**Timeline**")
    fd1, fd2, fd3, fd4 = st.columns(4)
    est_start = fd1.date_input("Est. Start", value=proj.get('estimated_start_date') or None,
                                help="Ngày dự kiến bắt đầu triển khai (sau khi ký HĐ).")
    est_end   = fd2.date_input("Est. End",   value=proj.get('estimated_end_date') or None,
                                help="Ngày dự kiến bàn giao hệ thống (trước bảo hành).")
    act_start = fd3.date_input("Act. Start", value=proj.get('actual_start_date') or None,
                                help="Ngày thực tế bắt đầu. Cập nhật khi dự án chính thức khởi động.")
    act_end   = fd4.date_input("Act. End",   value=proj.get('actual_end_date') or None,
                                help="Ngày thực tế bàn giao / nghiệm thu xong. Cập nhật khi hoàn thành.")

    st.markdown("**Team & Warranty**")
    fw1, fw2, fw3, fw4 = st.columns(4)
    emp_opts    = [e['full_name'] for e in employees]
    pm_idx      = next((i for i,e in enumerate(employees) if e['id']==proj.get('pm_employee_id')), 0)
    pm_sel      = fw1.selectbox("Project Manager", emp_opts, index=pm_idx,
                                 help="PM chịu trách nhiệm triển khai và báo cáo tiến độ dự án.")
    sales_idx   = next((i for i,e in enumerate(employees) if e['id']==proj.get('sales_employee_id')), 0)
    sales_sel   = fw2.selectbox("Sales", emp_opts, index=sales_idx,
                                 help="Sales phụ trách deal này — dùng để tính commission và track pre-sales cost.")
    war_months  = fw3.number_input("Warranty (months)", value=int(proj.get('warranty_months') or 12), min_value=0,
                                    help="Thời gian bảo hành tính bằng tháng kể từ ngày nghiệm thu.\nThông thường: AMR 12 tháng, WMS 12-24 tháng.")
    war_types   = ['PARTS_ONLY','LABOR_INCLUDED','FULL_SERVICE']
    war_type_idx= war_types.index(proj['warranty_type']) if proj.get('warranty_type') in war_types else 0
    war_type_sel= fw4.selectbox("Warranty Type", war_types, index=war_type_idx,
                                 help="PARTS_ONLY: chỉ bao gồm linh kiện thay thế.\nLABOR_INCLUDED: linh kiện + công kỹ thuật đến site.\nFULL_SERVICE: toàn diện, bao gồm cả phòng ngừa định kỳ.\n→ Ảnh hưởng đến chi phí dự phòng bảo hành (F).")

    decision_notes = st.text_area("Decision Notes", value=proj.get('decision_notes') or '', height=80,
                                   help="Ghi chú về quyết định Go/No-Go, điều kiện đặc biệt, hoặc lý do điều chỉnh scope/giá.")

    sub_col1, sub_col2 = st.columns([1,3])
    submitted = sub_col1.form_submit_button("💾 Save", type="primary", use_container_width=True)
    if sub_col2.form_submit_button("✖ Cancel", use_container_width=True):
        st.session_state.il_edit_mode = "view" if pid else None
        st.rerun()

if submitted:
    if not project_name:
        st.error("Project Name is required.")
        st.stop()

    pm_id    = employees[emp_opts.index(pm_sel)]['id']
    sales_id = employees[emp_opts.index(sales_sel)]['id']

    data = {
        'project_code': project_code.strip(),
        'contract_number': contract_num.strip() or None,
        'project_name': project_name.strip(),
        'project_type_id': type_id_sel,
        'customer_id': customer_id,
        'end_customer_name': end_cust_name.strip() or None,
        'contract_value': contract_val or None,
        'amended_contract_value': amended_val if amended_val > 0 else None,
        'currency_id': currency_id,
        'exchange_rate': exc_rate,
        'billing_type': billing_sel,
        'status': status_sel,
        'go_no_go_decision': None,
        'decision_date': None,
        'decision_notes': decision_notes.strip() or None,
        'location': location.strip() or None,
        'site_distance_category': dist_sel,
        'environment_category': env_sel,
        'import_category': imp_sel,
        'estimated_start_date': est_start,
        'estimated_end_date': est_end,
        'actual_start_date': act_start,
        'actual_end_date': act_end,
        'warranty_months': war_months,
        'warranty_end_date': None,
        'warranty_type': war_type_sel,
        'pm_employee_id': pm_id,
        'sales_employee_id': sales_id,
    }

    try:
        if is_create:
            new_id = create_project(data, user_id)
            st.success(f"✅ Project created! ID: {new_id}")
            st.session_state.il_selected_id = new_id
            st.session_state.il_edit_mode   = "view"
        else:
            update_project(pid, data, user_id)
            st.success("✅ Project updated!")
            st.session_state.il_edit_mode = "view"
        st.cache_data.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Save failed: {e}")