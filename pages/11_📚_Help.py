# pages/IL_99_📚_Help.py
"""
IL Project Management — Hướng dẫn sử dụng, Training Guide & Q&A tra cứu nhanh.
Standalone page, không cần DB connection.

CẤU TRÚC TÀI LIỆU:
────────────────────
  Tab 1 — Tham chiếu nhanh     : Bảng trạng thái, công thức, hệ số — tra cứu tức thì
  Tab 2 — SOP từng nghiệp vụ   : Hướng dẫn step-by-step, nhóm theo module
  Tab 3 — Q&A tình huống        : 43 câu hỏi thực tế, nhóm theo chủ đề
  Tab 4 — Sơ đồ tổng quan      : Roadmap workflow, module map

TỔ CHỨC DỮ LIỆU:
────────────────────
  MODULES          — Registry tất cả modules + mô tả
  STATUS_TABLES    — Bảng trạng thái & lifecycle (nhóm theo module)
  FORMULAS         — Công thức COGS A→F, Go/No-Go, coefficients
  SOP_REGISTRY     — SOP nhóm theo module, mỗi SOP có steps + tips
  QA_REGISTRY      — Q&A nhóm theo chủ đề, mỗi câu có situation + steps + note/warning
"""

import streamlit as st
import pandas as pd

st.set_page_config(page_title="IL Help & Q&A", page_icon="📚", layout="wide")


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 1: MODULE REGISTRY                                                ║
# ║  Danh sách tất cả modules trong hệ thống IL, dùng làm index               ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

MODULES = {
    "IL_1": {"icon": "📁", "name": "Projects",          "desc": "Tạo, quản lý thông tin dự án, vòng đời trạng thái"},
    "IL_2": {"icon": "📊", "name": "Estimate GP",       "desc": "Lập dự toán COGS, tính GP%, Go/No-Go, line items & attachments"},
    "IL_3": {"icon": "💰", "name": "Cost Tracking",     "desc": "Ghi Labor Logs, Expenses, approve, overview tổng hợp"},
    "IL_4": {"icon": "📈", "name": "COGS Dashboard",    "desc": "Sync COGS Actual, Variance Analysis, Finalize, Benchmark"},
    "IL_5": {"icon": "🛒", "name": "Purchase Request",  "desc": "Tạo PR, phê duyệt multi-level, tạo PO, email workflow"},
    "IL_6": {"icon": "📋", "name": "WBS",               "desc": "Phases, Tasks, completion cascade, engineer workflow"},
    "IL_7": {"icon": "👥", "name": "Team Management",   "desc": "Team Roster, workload allocation, daily rates"},
    "IL_8": {"icon": "🔧", "name": "Issues & Risks",    "desc": "Issues, Risk Register, Change Orders"},
    "IL_9": {"icon": "📊", "name": "Progress & Quality", "desc": "Progress Reports, Quality Checklists (FAT/SAT)"},
}


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 2: STATUS & LIFECYCLE TABLES                                      ║
# ║  Bảng trạng thái nhóm theo module — dùng cho tab Tham chiếu nhanh         ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

STATUS_TABLES = {
    # ── IL_1: Project Lifecycle ────────────────────────────────────────────
    "project_lifecycle": {
        "title": "Vòng đời dự án",
        "module": "IL_1",
        "columns": ["Trạng thái", "Icon", "Ý nghĩa", "Hành động tiếp theo"],
        "col_widths": {"Trạng thái": 140, "Icon": 50, "Ý nghĩa": 260, "Hành động tiếp theo": 260},
        "rows": [
            ("DRAFT",         "⚪", "Mới tạo, chưa estimate",        "Tạo Estimate đầu tiên"),
            ("ESTIMATING",    "🔵", "Đang lập dự toán COGS",         "Hoàn thiện Estimate, tính GP%"),
            ("PROPOSAL_SENT", "📤", "Đã gửi báo giá",               "Chờ phản hồi, cập nhật nếu cần"),
            ("GO",            "🟢", "Quyết định GO",                 "Chuyển sang CONTRACTED"),
            ("CONDITIONAL",   "🟡", "GO có điều kiện",               "Xem xét điều chỉnh giá / scope"),
            ("NO_GO",         "🔴", "Không tiếp tục",                "Phân bổ pre-sales sang SGA"),
            ("CONTRACTED",    "🟢", "Đã ký hợp đồng",               "Bắt đầu ghi Labor Logs"),
            ("IN_PROGRESS",   "🔵", "Đang triển khai",               "Cập nhật Labor + Expense hàng tuần"),
            ("COMMISSIONING", "🔵", "Chạy thử / nghiệm thu",        "Hoàn tất labor commissioning"),
            ("COMPLETED",     "✅", "Hoàn thành",                    "Sync COGS Actual, lập Variance"),
            ("WARRANTY",      "🛡️", "Trong bảo hành",                "Ghi labor/expense phase WARRANTY"),
            ("CLOSED",        "⬛", "Đã đóng hoàn toàn",             "Tạo Benchmark"),
            ("CANCELLED",     "❌", "Đã hủy",                       "Lưu hồ sơ"),
        ],
    },
    # ── IL_1: Project Types ────────────────────────────────────────────────
    "project_types": {
        "title": "Loại dự án (Project Type)",
        "module": "IL_1",
        "note": "Mỗi loại có default hệ số α/β/γ riêng. Hệ số dùng trong Estimate (A→F formula) — có thể override khi lập estimate.",
        "columns": ["Code", "Tên", "Mô tả", "α", "β", "γ"],
        "rows": [
            ("AMR-L", "AMR Transport (10+ units)",       "Dự án AMR lớn (≥10 robot)",             "0.06", "0.40", "0.04"),
            ("AMR-S", "AMR Transport (5-6 units)",       "Dự án AMR nhỏ (5–6 robot)",             "0.06", "0.40", "0.04"),
            ("CVR",   "Conveyor / Transfer System",      "Hệ thống băng tải, chuyển giao",        "0.06", "0.40", "0.04"),
            ("SMF",   "Smart Factory (Integrated)",      "Nhà máy thông minh tích hợp",           "0.06", "0.40", "0.04"),
            ("VIS",   "Vision System (FMR/Camera)",      "Hệ thống vision, camera",               "0.06", "0.40", "0.04"),
            ("WMS",   "Warehouse Automation (ASRS+AMR)", "Tự động hóa kho (ASRS + AMR)",          "0.06", "0.40", "0.04"),
            ("SPR",   "Spare Parts Supply",              "Bán linh kiện thay thế",                "0.08", "0.30", "0.02"),
            ("SVC",   "Service Deployment",              "Dịch vụ triển khai (không bán SP)",     "0.03", "0.50", "0.02"),
        ],
        "new_types": ["SPR", "SVC"],
    },
    # ── IL_5: Purchase Request Lifecycle ───────────────────────────────────
    "pr_lifecycle": {
        "title": "Vòng đời Purchase Request",
        "module": "IL_5",
        "note": "PR workflow: DRAFT → PENDING_APPROVAL → APPROVED → PO_CREATED. Có thể Cancel từ DRAFT/REVISION/PENDING.",
        "columns": ["Trạng thái", "Icon", "Ý nghĩa", "Hành động tiếp theo"],
        "col_widths": {"Trạng thái": 180, "Icon": 50, "Ý nghĩa": 280, "Hành động tiếp theo": 320},
        "rows": [
            ("DRAFT",              "⚪", "PR mới tạo, đang soạn items",           "Thêm items → Submit for Approval"),
            ("PENDING_APPROVAL",   "🔵", "Đang chờ approver phê duyệt",          "Approver: Approve / Reject / Revision. Creator: Remind / Cancel"),
            ("APPROVED",           "✅", "Đã phê duyệt (final level)",            "Tạo Purchase Order (PO)"),
            ("REJECTED",           "🔴", "Bị từ chối",                            "Tạo PR mới hoặc liên hệ approver"),
            ("REVISION_REQUESTED", "🟡", "Approver yêu cầu chỉnh sửa",          "Edit PR → Submit lại"),
            ("PO_CREATED",         "🟢", "PO đã được tạo từ PR",                 "Gửi PO cho vendor"),
            ("CANCELLED",          "⬛", "Đã hủy (bởi creator/PM)",              "Tạo PR mới nếu cần"),
        ],
    },
    # ── IL_6: Task Status ──────────────────────────────────────────────────
    "task_status": {
        "title": "Task Status (WBS)",
        "module": "IL_6",
        "columns": ["Trạng thái", "Icon", "Ý nghĩa", "Hành động"],
        "col_widths": {"Trạng thái": 120, "Icon": 50, "Ý nghĩa": 260, "Hành động": 300},
        "rows": [
            ("NOT_STARTED", "⚪", "Task mới tạo, chưa bắt đầu",    "Chờ assignee bắt đầu làm"),
            ("IN_PROGRESS", "🔵", "Đang thực hiện",                 "Cập nhật % và hours thường xuyên"),
            ("COMPLETED",   "✅", "Đã hoàn thành",                  "PM nhận email. Phase % tự cập nhật"),
            ("ON_HOLD",     "⏸️", "Tạm dừng",                       "Ghi lý do trong comment"),
            ("BLOCKED",     "🔴", "Bị chặn, cần PM xử lý",         "PM nhận email 🔴. Ghi blocker reason"),
            ("CANCELLED",   "❌", "Đã hủy",                         "Không tính vào completion %"),
        ],
    },
    # ── IL_6: Phase Status ─────────────────────────────────────────────────
    "phase_status": {
        "title": "Phase Status (WBS)",
        "module": "IL_6",
        "columns": ["Trạng thái", "Icon", "Ý nghĩa", "Hành động"],
        "rows": [
            ("NOT_STARTED", "⚪", "Chưa bắt đầu",                          "PM tạo tasks cho phase này"),
            ("IN_PROGRESS", "🔵", "Đang triển khai (có task đang làm)",     "Completion % tự tính từ tasks"),
            ("COMPLETED",   "✅", "Tất cả tasks xong",                      "Chuyển sang phase tiếp theo"),
            ("ON_HOLD",     "⏸️", "Tạm dừng phase",                         "Ảnh hưởng timeline dự án"),
            ("CANCELLED",   "❌", "Hủy phase",                              "Tasks con cũng bị soft-delete"),
        ],
    },
    # ── IL_8: Issue Severity ───────────────────────────────────────────────
    "issue_severity": {
        "title": "Issue Severity",
        "module": "IL_8",
        "columns": ["Mức", "Icon", "Ý nghĩa", "Action"],
        "rows": [
            ("LOW",      "🟢", "Ảnh hưởng nhỏ, không ảnh hưởng tiến độ",  "Giải quyết khi có thời gian"),
            ("MEDIUM",   "🟡", "Ảnh hưởng vừa, cần xử lý trong tuần",    "Assign người chịu trách nhiệm"),
            ("HIGH",     "🟠", "Ảnh hưởng lớn, có thể delay schedule",    "Escalate lên PM ngay"),
            ("CRITICAL", "🔴", "Ảnh hưởng nghiêm trọng, block tiến độ",   "PM + stakeholder xử lý khẩn cấp"),
        ],
    },
    # ── IL_8: Risk Score ───────────────────────────────────────────────────
    "risk_score": {
        "title": "Risk Score Matrix",
        "module": "IL_8",
        "columns": ["Score", "Icon", "Mức rủi ro", "Action"],
        "rows": [
            ("1–4",   "🟢", "Low Risk — chấp nhận được",   "Monitor, không cần action ngay"),
            ("5–9",   "🟡", "Medium Risk — cần theo dõi",  "Lập mitigation plan"),
            ("10–15", "🟠", "High Risk — cần xử lý sớm",  "Owner thực hiện mitigation ngay"),
            ("16–25", "🔴", "Critical Risk — nguy cơ cao", "Escalate, contingency plan ready"),
        ],
    },
    # ── IL_8: Change Order ─────────────────────────────────────────────────
    "change_order_status": {
        "title": "Change Order Status",
        "module": "IL_8",
        "columns": ["Trạng thái", "Icon", "Ý nghĩa", "Hành động"],
        "col_widths": {"Trạng thái": 120, "Icon": 50},
        "rows": [
            ("DRAFT",     "⚪", "Đang soạn CO",             "Điền đầy đủ → Submit"),
            ("SUBMITTED", "🔵", "Đã submit, chờ duyệt",    "Management review"),
            ("APPROVED",  "✅", "Nội bộ đã duyệt",          "Chờ customer confirm"),
            ("REJECTED",  "🔴", "Bị từ chối",               "Xem lại scope/cost"),
            ("CANCELLED", "⬛", "Đã hủy",                   "Lưu hồ sơ"),
        ],
    },
}


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 3: EMAIL NOTIFICATION TABLES                                      ║
# ║  Ma trận email tự động — ai nhận gì khi nào                               ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

EMAIL_TABLES = {
    "pr_emails": {
        "title": "Email Notification — PR Workflow",
        "module": "IL_5",
        "note": "Tất cả email có nút 'Open in ERP' → deep link trực tiếp đến PR. User có thể CC thêm người từ employee list.",
        "columns": ["Trigger", "Icon", "Gửi đến", "CC tự động / Ghi chú"],
        "col_widths": {"Trigger": 180, "Icon": 50, "Gửi đến": 220, "CC tự động / Ghi chú": 400},
        "rows": [
            ("PR Submitted",       "📤", "Gửi đến approver (Level 1)",   "Auto-CC: requester. User có thể thêm CC từ employee list"),
            ("PR Approved",        "✅", "Gửi đến requester",            "Auto-CC PM (khi final). Nếu multi-level: email tiếp đến next approver"),
            ("PR Rejected",        "🔴", "Gửi đến requester",            "Auto-CC PM nếu PM ≠ requester"),
            ("Revision Requested", "🟡", "Gửi đến requester",            "Auto-CC PM nếu PM ≠ requester"),
            ("PO Created",         "🟢", "Gửi đến requester",            "Auto-CC PM. User có thể CC finance team"),
            ("PR Cancelled",       "⬛", "Gửi đến requester",            "Auto-CC PM + pending approver (nếu đang PENDING)"),
            ("Reminder",           "📧", "Gửi đến approver hiện tại",    "Auto-CC requester. Nhấn 📧 Remind trong My PRs hoặc View dialog"),
        ],
    },
    "wbs_emails": {
        "title": "Email Notification — WBS Workflow",
        "module": "IL_6",
        "note": "Email tự động gửi khi có sự kiện quan trọng trong WBS workflow.",
        "columns": ["Trigger", "Icon", "Gửi đến", "Chi tiết"],
        "col_widths": {"Trigger": 150, "Icon": 50, "Gửi đến": 220, "Chi tiết": 400},
        "rows": [
            ("Task Assigned",  "📋", "Gửi đến assignee (engineer)", "Auto-CC PM. Khi tạo mới hoặc reassign"),
            ("Member Added",   "👥", "Gửi đến member mới",          "Khi add vào project team"),
            ("Task BLOCKED",   "🔴", "Gửi đến PM",                  "Kèm blocker reason. PM cần action"),
            ("Task COMPLETED", "✅", "Gửi đến PM",                  "Kèm phase % và project % completion"),
        ],
    },
}


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 4: FORMULAS & COEFFICIENTS                                        ║
# ║  Công thức COGS A→F, Go/No-Go, tỷ giá, budget thresholds                  ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

COGS_FORMULA = {
    "title": "Công thức COGS A→F",
    "note": "Mỗi khoản có 2 context: **Estimate** (nhập tay khi lập dự toán) và **COGS Actual** (nguồn dữ liệu thực tế khi Sync).",
    "items": [
        # (code, name, formula_estimate, source_actual, desc)
        ("A", "Equipment Cost",     "Nhập thủ công",                "Nhập thủ công từ invoice supplier",                                                                                            "Chi phí thiết bị, máy móc"),
        ("B", "Logistics & Import", "B = A × α",                    "Nhập thủ công từ invoice forwarder",                                                                                           "Vận chuyển, nhập khẩu, thuế"),
        ("C", "Custom Fabrication", "Nhập thủ công",                "Nhập thủ công từ PO subcontractor",                                                                                            "Gia công, chế tạo tùy chỉnh"),
        ("D", "Direct Labor",       "D = Man-days × Rate × Team",   "Tự động: Labor Logs APPROVED (phase ≠ PRE_SALES, hoặc PRE_SALES + allocation=COGS)",                                          "Nhân công trực tiếp"),
        ("E", "Travel & Site OH",   "E = D × β",                    "Tự động: Expenses APPROVED (phase ≠ PRE_SALES và ≠ WARRANTY) + Pre-sales costs SPECIAL/COGS (category hợp lệ)",                "Đi lại, chi phí hiện trường"),
        ("F", "Warranty Reserve",   "F = (A + C) × γ",              "Nhập thủ công: provision / actual_used / released. F_net = provision − released",                                              "Dự phòng bảo hành"),
    ],
    "summary_formulas": [
        ("Total COGS", "A + B + C + D + E + F"),
        ("GP",         "Doanh thu − COGS"),
        ("GP%",        "GP / Doanh thu × 100"),
    ],
}

GO_NOGO_THRESHOLDS = {
    "title": "Ngưỡng Go / No-Go",
    "items": [
        # (label, icon, condition, color)
        ("GO",          "✅", "GP% ≥ 25%",         "success"),
        ("CONDITIONAL", "⚠️", "GP% từ 18% đến 25%", "warning"),
        ("NO-GO",       "❌", "GP% < 18%",          "error"),
    ],
}

# Sync D & E chi tiết — dùng cho SOP tips
SYNC_RULES = {
    "D_rules": {
        "D-direct":   "Phase ≠ PRE_SALES → vào D-direct",
        "D-presales": "Phase = PRE_SALES + allocation COGS → vào D-presales",
    },
    "E_rules": {
        "E-travel":   "Phase ≠ PRE_SALES và ≠ WARRANTY → vào E-travel",
        "E-presales": "Pre-sales costs Layer 2 allocation COGS → vào E-presales",
    },
    "E_presales_included":  ["DEMO_TRANSPORT", "TRAVEL_SPECIAL", "POC_EXECUTION", "WIFI_SURVEY", "ENGINEERING_STUDY", "CUSTOM_SAMPLE", "OTHER"],
    "E_presales_excluded":  ["PROTOTYPE", "CUSTOM_DEMO"],
}

BUDGET_THRESHOLDS = [
    # (label, icon, meaning)
    ("< 90%",    "🟢", "Còn dư ngân sách"),
    ("90–100%",  "🟡", "Gần hết ngân sách"),
    ("> 100%",   "🔴", "Vượt ngân sách!"),
]

EXCHANGE_RATE_ICONS = [
    ("✅ Live API / DB",  "success", "Tỷ giá đáng tin cậy"),
    ("⚠️ Fallback",       "warning", "Nhập thủ công từ ngân hàng"),
    ("💡 Lệch > 1%",     "info",    "Cân nhắc cập nhật"),
    ("ℹ️ VND",            "info",    "Không cần quy đổi"),
]

RISK_MATRIX_TABLE = (
    "**Risk Score = Probability × Impact (1–25)**\n\n"
    "| | Negligible (1) | Minor (2) | Moderate (3) | Major (4) | Severe (5) |\n"
    "|---|---|---|---|---|---|\n"
    "| Rare (1) | 1 | 2 | 3 | 4 | 5 |\n"
    "| Unlikely (2) | 2 | 4 | 6 | 8 | 10 |\n"
    "| Possible (3) | 3 | 6 | **9** | **12** | **15** |\n"
    "| Likely (4) | 4 | 8 | **12** | **16** | **20** |\n"
    "| Almost Certain (5) | 5 | 10 | **15** | **20** | **25** |"
)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 5: SOP REGISTRY                                                   ║
# ║  Nhóm theo module → dễ tìm, dễ training                                   ║
# ║  Mỗi SOP: module, steps[(num, action, tip)], tips (optional info boxes)    ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

SOP_REGISTRY = [
    # ┌─────────────────────────────────────────────────────────────────────┐
    # │  MODULE: IL_1 — Projects                                           │
    # └─────────────────────────────────────────────────────────────────────┘
    {
        "key": "create_project",
        "label": "📝 Tạo dự án mới",
        "module": "IL_1",
        "steps": [
            ("1", "Nhấn ➕ New Project ở sidebar",                                          "Project Code tự sinh: IL-YYYY-UserID-NNN"),
            ("2", "Tab Basic: điền Project Name, Type, Customer, Status = DRAFT",            "Project Name là trường bắt buộc duy nhất. Type mới: SPR (Spare Parts), SVC (Service Deployment)"),
            ("3", "Tab Financial: điền Contract Value, Currency, Exchange Rate",              "Hệ thống tự fetch tỷ giá — xác nhận trước khi lưu"),
            ("4", "Tab Timeline: điền Est. Start / End",                                     "Actual dates để trống, điền sau khi có thực tế"),
            ("5", "Tab Team: chọn PM và Sales",                                              "Bắt buộc có PM"),
            ("6", "Nhấn 💾 Create → tạo Estimate ngay sau đó",                               "Không có Estimate = không có baseline Variance"),
            ("7", "Xem/Sửa: tick chọn dự án trong bảng → nhấn 👁️ View hoặc ✏️ Edit ở action bar bên dưới", "Nhấn ✖ Deselect để bỏ chọn dòng"),
        ],
        "tips": [
            ("info",    "**Sau khi tạo xong:** Vào module IL Estimates để tạo Estimate đầu tiên ngay. Không có Estimate = không có baseline để Variance Analysis sau này."),
            ("success", "**Project Types mới:** [SPR] Spare Parts Supply (bán linh kiện) | [SVC] Service Deployment (bán dịch vụ triển khai, không bán sản phẩm)"),
        ],
    },

    # ┌─────────────────────────────────────────────────────────────────────┐
    # │  MODULE: IL_2 — Estimate GP                                        │
    # └─────────────────────────────────────────────────────────────────────┘
    {
        "key": "estimate_gp",
        "label": "📊 Lập Estimate GP",
        "module": "IL_2",
        "steps": [
            ("1",  "Vào Estimate GP → Sidebar chọn Project",                                 "Sidebar hiện: Type, Customer, Distance, Environment + hệ số mặc định α/β/γ"),
            ("2",  "Tab New Estimate → chọn Label và Type (QUICK / DETAILED)",               "Tick '📋 Pre-fill from active estimate' nếu muốn copy toàn bộ từ Rev trước (kể cả line items)"),
            ("3",  "Thêm line items — 3 cách:",                                              ""),
            ("4",  "  🔍 Add Product (A/C): Search product từ catalog → chọn Costbook entry (giá mua vendor) → optional chọn Quotation (giá bán KH) → nhập Qty", "Hệ thống auto-fill: cost, vendor name, quote ref, currency, exchange rate"),
            ("5",  "  📦 Import Costbook: chọn costbook → import tất cả products 1 lần",     "Tiện cho dự án có nhiều items từ cùng vendor. Điều chỉnh Qty sau"),
            ("6",  "  ✏️ Manual item: nhập tay cho NCC ngoài catalog (rack, trolley...)",     "Dùng khi vendor chưa có trong hệ thống hoặc item đặc biệt"),
            ("7",  "📎 Đính kèm per line item: upload báo giá vendor cho từng hạng mục",     "Trong dialog Add Product có file uploader. File lưu S3 + link với line item"),
            ("8",  "📎 Estimate Attachments: upload scope, BOQ, proposal cho toàn estimate",  "Section riêng bên dưới line items. Hỗ trợ nhiều files cùng lúc"),
            ("9",  "Phần Coefficients: điều chỉnh α/β/γ, D (labor), overrides nếu cần",     "A và C tự tính từ line items (hoặc override). Sales tự sum từ quotation sell prices (hoặc override)"),
            ("10", "Kiểm tra Live Preview bên phải: COGS breakdown, GP%, Go/No-Go",          "Preview cập nhật real-time. Hiện nguồn A (items/override)"),
            ("11", "Nhấn 💾 Save & Activate",                                                 "Estimate + line items + attachments lưu cùng lúc. Rev mới tự activated"),
        ],
        "tips": [
            ("info",    "**3 cách thêm line items:**\n- 🔍 **Add Product**: search catalog → chọn Costbook (cost) + Quotation (sell)\n- 📦 **Import Costbook**: import tất cả products từ 1 costbook\n- ✏️ **Manual**: nhập tay cho NCC ngoài catalog\n\nA và C **auto-sum** từ line items. Sales auto-sum từ quotation sell prices."),
            ("success", "**Traceability & Attachments:**\n- Mỗi item link: product_id → costbook → vendor\n- 📎 Per item: attach báo giá vendor\n- 📎 Per estimate: attach scope, BOQ, proposal\n- Active tab: xem line items + download attachments\n- History: so sánh α/β/γ giữa revisions"),
        ],
    },

    # ┌─────────────────────────────────────────────────────────────────────┐
    # │  MODULE: IL_3 — Cost Tracking                                      │
    # └─────────────────────────────────────────────────────────────────────┘
    {
        "key": "labor_log",
        "label": "🔢 Ghi Labor Log",
        "module": "IL_3",
        "steps": [
            ("1", "Vào Cost Tracking → Sidebar chọn Project cụ thể (không chọn 'All Projects')", "Nút ➕ Log Labor xuất hiện ở sidebar khi đã chọn project"),
            ("2", "Nhấn ➕ Log Labor ở sidebar → popup dialog",                              "Có thể lọc Phase / Approval / Date Range ở sidebar trước khi xem"),
            ("3", "Điền Work Date, Phase đúng giai đoạn thực tế",                            "KHÔNG dùng PRE_SALES cho công việc sau khi ký hợp đồng"),
            ("4", "Chọn Worker (nội bộ) hoặc nhập subcontractor_name",                       ""),
            ("5", "Nhập Man-days (0.5 = nửa ngày, tối đa 3.0 mỗi entry), Daily Rate, tick Is On-site", "Cần ghi > 3 ngày: tạo nhiều entry (VD: 3 + 2). Daily Rate tự gợi ý theo Level"),
            ("6", "Nếu Phase = PRE_SALES: chọn Presales Allocation (COGS/SGA)",              "Dự án GO → COGS | NO_GO → SGA"),
            ("7", "Đính kèm timesheet / email xác nhận",                                     ""),
            ("8", "Submit → chờ Manager Approve",                                             "Log PENDING không được tính vào COGS. PM approve từng entry hoặc Approve All"),
        ],
        "tips": [
            ("info",    "**Sửa / Xóa entry:** Tick chọn entry trong bảng → nhấn ✏️ Edit ở action bar bên dưới. Chỉ entry PENDING mới sửa/xóa được."),
            ("warning", "**Approve:** PM tick chọn entry → nhấn ✅ Approve, hoặc dùng nút ✅ Approve All Pending ở cuối bảng."),
        ],
    },
    {
        "key": "expense",
        "label": "💳 Ghi Expense",
        "module": "IL_3",
        "steps": [
            ("1", "Vào Cost Tracking → Sidebar chọn Project cụ thể",       "Nút ➕ Add Expense xuất hiện ở sidebar"),
            ("2", "Nhấn ➕ Add Expense → chọn Currency trước (ngoài form)", "Tỷ giá auto-fetch khi đổi currency"),
            ("3", "Điền Expense Date, Category đúng loại, Phase đúng giai đoạn", ""),
            ("4", "Nhập Amount. Exchange Rate tự fetch — kiểm tra lại",     "Nếu ⚠️ fallback rate: nhập tỷ giá từ ngân hàng"),
            ("5", "Điền Vendor Name và Receipt Number",                      "Vendor chọn từ danh sách hoặc nhập thủ công"),
            ("6", "Upload scan hóa đơn / receipt vào Attachment",            "Finance thường yêu cầu chứng từ trước khi approve"),
            ("7", "Submit → chờ Finance Approve → expense vào COGS khi sync", "Expense WARRANTY không vào khoản E"),
        ],
        "tips": [
            ("info", "**Currency chọn ngoài form** để hệ thống fetch tỷ giá trước khi điền amount. Sau khi chọn currency, tỷ giá tự điền vào form."),
        ],
    },
    {
        "key": "cost_overview",
        "label": "📊 Xem Overview tất cả dự án",
        "module": "IL_3",
        "steps": [
            ("1", "Vào Cost Tracking → Sidebar để Project = 'All Projects' (mặc định)", "Hiện dashboard tổng hợp tất cả dự án"),
            ("2", "Xem KPI: tổng Man-Days, Labor Cost, Expenses, Pending Items",         "Chỉ tính records APPROVED cho cost KPIs"),
            ("3", "Bảng Per-Project Summary: so sánh chi phí giữa các dự án",            "Chỉ hiện dự án có data (bỏ qua dự án chưa phát sinh)"),
            ("4", "PM: xem Pending Approvals — approve hàng loạt từ 1 chỗ",              "Không cần vào từng dự án để approve"),
            ("5", "Dùng Date Range filter để xem cost theo tháng / quý",                  "Tick 'Filter by date range' ở sidebar"),
        ],
        "tips": [
            ("success", "**KPIs tổng hợp**\n- Man-Days (Approved)\n- Labor Cost (Approved)\n- Expenses (Approved)\n- Pending Items"),
            ("info",    "**Sidebar filters**\n- Project: All / specific\n- Date Range: from → to\n- Phase: All / specific\n- Approval: All / PENDING / APPROVED"),
        ],
    },

    # ┌─────────────────────────────────────────────────────────────────────┐
    # │  MODULE: IL_4 — COGS Dashboard                                     │
    # └─────────────────────────────────────────────────────────────────────┘
    {
        "key": "sync_cogs",
        "label": "🔄 Sync COGS Actual",
        "module": "IL_4",
        "steps": [
            ("1", "Vào COGS Dashboard → Sidebar chọn Project cụ thể",        "Mặc định 'All Projects' hiện portfolio overview — chọn project để vào chi tiết"),
            ("2", "Đảm bảo tất cả Labor Logs & Expenses đã được Approve",    "Log/Expense PENDING bị bỏ qua hoàn toàn"),
            ("3", "Nhập thủ công A, B, C: nhấn ✏️ Manual Entry (A/B/C/F)",   "B bao gồm: freight + thuế nhập khẩu + phí thông quan"),
            ("4", "Nhấn 🔄 Sync from Timesheets & Expenses",                  "D và E tự tổng hợp từ approved records. A/B/C/F giữ nguyên"),
            ("5", "Kiểm tra **Budget progress bar**: Actual / Estimated COGS", "⚠️ >90%: cảnh báo vàng | 🔴 >100%: over budget"),
            ("6", "Xem GP comparison: Est GP% vs Act GP% (có delta)",         "Lệch >5%: cần phân tích nguyên nhân"),
            ("7", "KHÔNG Finalize cho đến khi dự án 100% kết thúc",           "Finalize = khóa vĩnh viễn, không thể hoàn tác"),
        ],
        "tips": [
            ("warning", "**D (tự động)** = Tổng Labor Logs APPROVED\n- Phase ≠ PRE_SALES: vào D-direct\n- Phase = PRE_SALES + allocation COGS: vào D-presales"),
            ("warning", "**E (tự động)** = Tổng Expenses APPROVED\n- Phase ≠ PRE_SALES và ≠ WARRANTY: vào E-travel\n- Pre-sales costs Layer 2 allocation COGS: vào E-presales"),
            ("info",    "**⚠️ E-presales chỉ tính các category:** DEMO_TRANSPORT, TRAVEL_SPECIAL, POC_EXECUTION, WIFI_SURVEY, ENGINEERING_STUDY, CUSTOM_SAMPLE, OTHER.\n\nCác category **PROTOTYPE** và **CUSTOM_DEMO** (dù là SPECIAL/COGS) **không** được đưa vào E-presales khi Sync."),
        ],
    },
    {
        "key": "close_benchmark",
        "label": "✅ Đóng dự án & Benchmark",
        "module": "IL_4",
        "steps": [
            ("1", "Đảm bảo tất cả Labor Logs & Expenses cuối cùng đã Approve", "Vào Cost Tracking → All Projects → Pending Approvals để kiểm tra"),
            ("2", "Nhập đủ A, B, C, F vào COGS Actual",                         "F: điền f_warranty_actual_used sau khi hết thời gian bảo hành"),
            ("3", "Sync COGS Actual lần cuối",                                   "Kiểm tra budget bar = final consumption %"),
            ("4", "Tab Variance: nhấn ⚡ Generate All Variance",                  "Auto-tạo 7 rows (A–F + TOTAL) từ Estimate vs Actual"),
            ("5", "Bổ sung Root Cause + Corrective Action cho khoản lệch >5%",  "Hệ thống highlight categories cần nhập Root Cause"),
            ("6", "Finalize COGS Actual",                                         "Không thể hoàn tác sau bước này"),
            ("7", "Chuyển Status dự án → CLOSED",                                ""),
            ("8", "Tab Benchmarks: nhấn ➕ Add → hệ thống auto-fill α/β/γ + man-days + GP%", "Chỉ cần nhập Lessons Learned, Key Risks, Recommendations"),
        ],
        "tips": [
            ("success", "**Thứ tự các bước QUAN TRỌNG:** Approve hết → Sync COGS → **⚡ Generate All Variance** → Điền Root Cause → **Finalize** → Close → **Benchmark (auto-fill)**. Không thể đảo thứ tự sau bước Finalize."),
            ("info",    "**⚡ Generate All Variance**\n\n1 click tạo 7 rows (A–F + TOTAL).\nAuto-fill Estimated & Actual từ data.\nChỉ cần bổ sung Root Cause cho khoản lệch >5%."),
            ("info",    "**📚 Auto-fill Benchmark**\n\nNhấn ➕ Add → hệ thống tự điền:\n- α/β/γ Used (từ Estimate)\n- α/β/γ Actual (tính từ COGS Actual)\n- Man-days Est/Act, GP% Est/Act\n\nChỉ cần nhập Lessons Learned."),
        ],
    },

    # ┌─────────────────────────────────────────────────────────────────────┐
    # │  MODULE: IL_5 — Purchase Request                                   │
    # └─────────────────────────────────────────────────────────────────────┘
    {
        "key": "create_pr",
        "label": "🛒 Tạo & Submit Purchase Request",
        "module": "IL_5",
        "steps": [
            ("1", "Sidebar: chọn Project → nhấn ➕ New PR",                                "Chỉ PM hoặc Admin mới thấy nút New PR"),
            ("2", "Step ① Setup: chọn Type (EQUIPMENT/FABRICATION/SERVICE/MIXED)",          "COGS Category tự set theo type. Currency + tỷ giá auto-fetch"),
            ("3", "Chọn Vendor, Priority, Required Date, Justification",                    "Vendor chọn từ danh sách hoặc '(Select later)'"),
            ("4", "Step ② Items: nhấn 📋 Import from Estimate hoặc ➕ Add Manual Item",     "Import chỉ hiện items chưa có trong PR khác. Manual item: nhập description, qty, cost"),
            ("5", "Chọn item trong bảng → ✏️ Edit hoặc 🗑 Remove",                          "Có thể mix import + manual items"),
            ("6", "Step ③ Review: kiểm tra Summary, Budget Impact, Approval Chain",         "Budget comparison hiện: Estimated vs Previous PRs vs This PR → warnings nếu over budget"),
            ("7", "📧 CC thêm (optional): chọn nhân viên để CC email",                      "Multiselect từ employee list"),
            ("8", "Nhấn ✅ Create & Submit for Approval",                                    "Hoặc 💾 Save as Draft để submit sau"),
        ],
        "tips": [
            ("info",    "**Wizard 3 bước:**\n- ① **Setup**: Type, Currency, Vendor, Priority\n- ② **Items**: Import Estimate / Add Manual\n- ③ **Review**: Budget Impact + Approval Chain\n\n📧 CC thêm người trước khi Submit."),
            ("success", "**Budget Impact (Step ③):**\n- So sánh Estimated vs Previous PRs vs This PR\n- 🟢 < 85% | 🟡 85–100% | 🔴 Over budget\n- Cảnh báo nhưng **không block** submit\n- Approver cũng thấy budget khi approve"),
        ],
    },
    {
        "key": "approve_pr",
        "label": "✅ Phê duyệt PR (Approver)",
        "module": "IL_5",
        "steps": [
            ("1", "Nhận email thông báo → click Open in ERP",                          "Link direct đến PR trên hệ thống. Hoặc vào IL5 → tab Pending Approval"),
            ("2", "Xem chi tiết: items, budget comparison, justification",              "Budget table hiện Estimated vs PR Committed by COGS A–F"),
            ("3", "Chọn action: ✅ Approve / ❌ Reject / 🔄 Request Revision",          "Reject và Revision bắt buộc nhập comments"),
            ("4", "📧 CC thêm (optional): chọn nhân viên để CC email",                  ""),
            ("5", "Multi-level: sau Level 1 approve → auto email đến Level 2",          "Số levels phụ thuộc vào tổng tiền (cấu hình trong Approval Config)"),
        ],
        "tips": [
            ("info",    "**3 actions:**\n- ✅ **Approve**: chuyển level tiếp hoặc final\n- ❌ **Reject**: requester tạo PR mới\n- 🔄 **Revision**: requester edit + resubmit"),
            ("success", "**Email deep link:**\n- Click 'Open in ERP' → direct đến Approval dialog\n- Nếu chưa login → inline login → auto mở dialog\n- Multi-level: email tự gửi next approver"),
            ("warning", "**Reject vs Revision:** Reject = đóng vĩnh viễn, cần tạo PR mới. Revision = gửi lại cho requester sửa + submit lại."),
        ],
    },
    {
        "key": "create_po",
        "label": "🛒 Tạo PO từ PR đã Approved",
        "module": "IL_5",
        "steps": [
            ("1", "Vào View PR → nhấn 🛒 Create PO",             "Hoặc từ My PRs tab: chọn PR APPROVED → 🛒 Create PO"),
            ("2", "Dialog confirm: kiểm tra vendor, total amount", "📧 CC thêm: chọn finance team hoặc người liên quan"),
            ("3", "Nhấn 🛒 Yes, Create PO",                       "PO tự sinh: PO{YYYYMMDD}-{id}{vendor_id}"),
            ("4", "PO link ngược vào PR → status chuyển PO_CREATED", "Email thông báo gửi requester + CC PM + CC thêm"),
        ],
        "tips": [
            ("info",    "**PO tự động tạo** trong bảng purchase_orders + product_purchase_orders. PO number format: PO{YYYYMMDD}-{id}{vendor_id}. Link ngược vào il_project_documents."),
            ("success", "**Sau khi tạo PO**: PR status → PO_CREATED. Email gửi requester + CC PM. Tiếp theo: gửi PO cho vendor qua kênh bên ngoài (email/portal)."),
        ],
    },

    # ┌─────────────────────────────────────────────────────────────────────┐
    # │  MODULE: IL_6 — WBS                                                │
    # └─────────────────────────────────────────────────────────────────────┘
    {
        "key": "setup_wbs",
        "label": "📋 Setup WBS (Phases & Tasks)",
        "module": "IL_6",
        "steps": [
            ("1", "Vào IL_6 WBS → Sidebar chọn Project",                                    "Project phải ở status CONTRACTED hoặc IN_PROGRESS"),
            ("2", "Tab Phases → nhấn 📦 Load Template",                                      "Tạo 7 phases chuẩn (Pre-Sales → Warranty) với weight % sẵn"),
            ("3", "Hoặc ➕ Add Phase thủ công: nhập Code, Name, Planned Start/End, Weight %", "Tổng Weight % nên = 100% để completion % chính xác"),
            ("4", "Tab Tasks → nhấn ➕ Add Task: chọn Phase, đặt tên, assign engineer",      "WBS code tự sinh: 3.1, 3.2, 3.2.1 (theo phase + parent task)"),
            ("5", "Set Priority (LOW → CRITICAL), Planned Start/End, Estimated Hours",       "Engineer sẽ thấy task trong 'My Tasks' ngay sau khi assign"),
            ("6", "📧 Email tự động gửi đến engineer khi assign",                             "Có deep link 'Open in ERP' trong email"),
            ("7", "Thêm Checklist items cho task (VD: commissioning có 20 items cần tick)",   "Tab Checklist trong Task Detail dialog"),
            ("8", "Đính kèm file: tab Files trong Task Detail → upload drawings, specs",     "Multi-file, lưu S3 qua medias table"),
        ],
        "tips": [
            ("info",    "**Phase Template (7 phases chuẩn):**\n1. Pre-Sales (5%)\n2. Design (15%)\n3. Procurement (10%)\n4. Implementation (35%)\n5. Commissioning (20%)\n6. Training (10%)\n7. Warranty (5%)\n\nWeight % = mức đóng góp vào overall completion."),
            ("success", "**WBS Code tự sinh:**\nPhase seq 3 → tasks: 3.1, 3.2\nSub-task: 3.2.1, 3.2.2\n\n**Assign → email:**\nEngineer nhận email ngay khi được assign task.\nEmail có deep link 'Open in ERP'."),
            ("warning", "**Dependency:** Task có thể link 'Finish-to-Start' với task khác (field dependency_task_id). Hiện tại chỉ lưu thông tin — chưa có Gantt chart enforce. PM tự kiểm tra thứ tự."),
        ],
    },
    {
        "key": "update_progress",
        "label": "⚡ Cập nhật tiến độ (Engineer)",
        "module": "IL_6",
        "steps": [
            ("1", "Login → vào IL_6 WBS → tab 🙋 My Tasks",             "Hiện tất cả task across projects, sort theo priority + deadline"),
            ("2", "Chọn task → nhấn ⚡ Quick Update",                     "Dialog nhỏ gọn: chỉ Status, %, Hours"),
            ("3", "Kéo slider Completion % (bước 5%)",                    "Hệ thống auto-log progress vào activity feed"),
            ("4", "Nếu bị BLOCKED: chọn status BLOCKED + nhập Blocker Reason", "PM nhận email 🔴 ngay lập tức. Blocker ghi vào comment"),
            ("5", "Khi xong: chọn COMPLETED (100%)",                     "PM nhận email ✅ kèm phase % và project % completion"),
            ("6", "Completion % tự động cascade: task → phase → project", "PM mở dashboard thấy overall % cập nhật"),
            ("7", "Tick checklist items khi hoàn thành từng bước nhỏ",   "Trong Task Detail → tab ✅ Checklist"),
            ("8", "Ghi comment nếu cần trao đổi với PM",                 "Task Detail → tab 💬 Comments"),
        ],
        "tips": [
            ("info",    "**My Tasks sort theo:**\n1. Priority: CRITICAL → HIGH → NORMAL → LOW\n2. Deadline: gần nhất lên trước\n\nChỉ hiện tasks NOT_STARTED, IN_PROGRESS, ON_HOLD, BLOCKED."),
            ("success", "**Completion Cascade:**\nTask 80% → Phase auto-recalc → Project auto-recalc\n\n**Auto-log:**\n• Status change → 🔄 logged\n• Progress update → 📊 logged\n• BLOCKED + reason → 🚧 logged as BLOCKER comment"),
        ],
    },

    # ┌─────────────────────────────────────────────────────────────────────┐
    # │  MODULE: IL_7 — Team                                               │
    # └─────────────────────────────────────────────────────────────────────┘
    {
        "key": "manage_team",
        "label": "👥 Quản lý Team (IL_7)",
        "module": "IL_7",
        "steps": [
            ("1", "Vào IL_7 Team → Sidebar chọn Project",                                ""),
            ("2", "Tab Team Roster → nhấn ➕ Add Member",                                 "Chọn Employee, Role, Allocation %, Daily Rate"),
            ("3", "📧 Member nhận email thông báo khi được add vào project",               "Kèm: project name, role, PM name"),
            ("4", "Edit member: chọn dòng → ✏️ Edit (đổi role, allocation, rate)",         ""),
            ("5", "Tab Workload: chọn bất kỳ employee → xem allocation across projects",  "🔴 Over 100% = over-allocated. 🟡 >80% = gần full"),
            ("6", "Daily Rate dùng cho budget calculation kết hợp labor logs",             "Rate tự gợi ý theo Role (từ DEFAULT_RATES_BY_LEVEL)"),
        ],
        "tips": [
            ("info",    "**Roles:**\nPROJECT_MANAGER, SOLUTION_ARCHITECT,\nSENIOR_ENGINEER, ENGINEER, SITE_ENGINEER,\nFAE, SALES, SUBCONTRACTOR, OTHER\n\n1 employee có thể có nhiều roles khác nhau trên cùng project."),
            ("success", "**Daily Rate mặc định theo level:**\n• Junior Engineer: 1,000,000 ₫\n• Engineer: 1,200,000 ₫\n• Senior Engineer: 1,500,000 ₫\n• PM: 2,100,000 ₫\n• Solution Architect: 2,500,000 ₫\n\nTự gợi ý khi chọn Role, có thể override."),
        ],
    },

    # ┌─────────────────────────────────────────────────────────────────────┐
    # │  MODULE: IL_8 — Issues, Risks, Change Orders                       │
    # └─────────────────────────────────────────────────────────────────────┘
    {
        "key": "log_issue",
        "label": "🔧 Log Issue (IL_8)",
        "module": "IL_8",
        "steps": [
            ("1", "Vào IL_8 Issues → Tab 🔧 Issues → nhấn ➕ Report Issue", "Bất kỳ ai trong team đều có thể report"),
            ("2", "Điền Title, Category (TECHNICAL/COMMERCIAL/...), Severity", "CRITICAL → PM cần xử lý khẩn cấp"),
            ("3", "Assign người chịu trách nhiệm resolve + Due Date",       ""),
            ("4", "Link tới task liên quan (optional)",                       "Giúp trace issue ảnh hưởng task nào"),
            ("5", "Sau khi tạo → View dialog → đính kèm ảnh / tài liệu",   "Multi-file, lưu qua medias table"),
            ("6", "Workflow: OPEN → IN_PROGRESS → RESOLVED (ghi Resolution) → CLOSED", ""),
        ],
        "tips": [
            ("info",    "**Issue workflow:** OPEN → IN_PROGRESS → RESOLVED → CLOSED\n\nCó thể ESCALATED nếu không giải quyết được ở cấp engineer."),
            ("warning", "**Severity ảnh hưởng thứ tự hiển thị:** CRITICAL → HIGH → MEDIUM → LOW. Issues CRITICAL luôn hiện đầu tiên trong bảng."),
        ],
    },
    {
        "key": "risk_register",
        "label": "⚠️ Risk Register (IL_8)",
        "module": "IL_8",
        "steps": [
            ("1", "Tab ⚠️ Risks → nhấn ➕ Add Risk",                          "PM tạo khi planning hoặc phát hiện rủi ro mới"),
            ("2", "Chọn Probability (RARE → ALMOST_CERTAIN) × Impact (NEGLIGIBLE → SEVERE)", "Risk Score tự tính: 1–25"),
            ("3", "Nhập Mitigation Plan (giảm xác suất/ảnh hưởng) + Contingency Plan (plan B)", ""),
            ("4", "Assign Risk Owner + set Review Date",                       "Owner chịu trách nhiệm thực hiện mitigation"),
            ("5", "Đính kèm risk analysis document nếu có",                    ""),
            ("6", "Review định kỳ: cập nhật probability/impact/status",        "Status OCCURRED → tạo Issue tương ứng"),
        ],
        "tips": [
            ("info",    RISK_MATRIX_TABLE),
            ("warning", "**Status OCCURRED** = risk đã xảy ra → nên tạo Issue tương ứng để track resolution."),
        ],
    },
    {
        "key": "change_order",
        "label": "📝 Change Order (IL_8)",
        "module": "IL_8",
        "steps": [
            ("1", "Tab 📝 Change Orders → nhấn ➕ New Change Order",    "Khi scope/cost/schedule thay đổi"),
            ("2", "Chọn Type: SCOPE / SCHEDULE / COST / SCOPE_AND_COST", ""),
            ("3", "Nhập Original Value, Revised Value → Cost Impact tự tính", "Schedule Impact: +/- days"),
            ("4", "Workflow: DRAFT → SUBMITTED → APPROVED (nội bộ) → Customer Confirm", ""),
            ("5", "Khi APPROVED + Customer Confirm → cập nhật amended_contract_value trên project", "KPIs CO Impact hiện ở đầu tab"),
            ("6", "Đính kèm customer approval email / signed CO",       ""),
        ],
        "tips": [
            ("info",    "**Cost Impact** = Revised − Original\n\nPositive (+) = scope tăng → giá tăng\nNegative (−) = scope giảm → giá giảm\n\nKPI hiện tổng Approved + Pending impact."),
            ("success", "**Sau khi CO APPROVED + Customer Confirm:**\n1. Edit project → Amended Contract Value\n2. Tạo Estimate revision mới\n3. Cập nhật tasks/phases nếu scope thay đổi\n4. COGS Dashboard → Sync lại"),
        ],
    },

    # ┌─────────────────────────────────────────────────────────────────────┐
    # │  MODULE: IL_9 — Progress & Quality                                 │
    # └─────────────────────────────────────────────────────────────────────┘
    {
        "key": "progress_report",
        "label": "📊 Progress Report (IL_9)",
        "module": "IL_9",
        "steps": [
            ("1", "Vào IL_9 Progress → Tab 📊 Progress Reports → nhấn ➕ New Report", "PM viết hàng tuần/tháng"),
            ("2", "Chọn Type (WEEKLY/MONTHLY), Date, Reporting Period",               ""),
            ("3", "Set RAG status: ON_TRACK 🟢 / AT_RISK 🟡 / DELAYED 🔴",           "Có thể set riêng cho Schedule, Cost, Quality"),
            ("4", "Nhập Completion % — có thể lấy từ project overall %",               "Hệ thống pre-fill từ il_projects.overall_completion_percent"),
            ("5", "Viết narrative: Summary, Accomplishments, Planned Next, Blockers",  ""),
            ("6", "Đính kèm report PDF/presentation nếu cần",                         ""),
            ("7", "Status: DRAFT → SUBMITTED → REVIEWED (by leadership)",              ""),
        ],
        "tips": [
            ("info",    "**RAG Status (3 cấp):**\n\n🟢 ON_TRACK — mọi thứ đúng kế hoạch\n🟡 AT_RISK — có nguy cơ delay\n🔴 DELAYED — đã chậm so với plan\n🔵 AHEAD — đi trước kế hoạch\n🔴 CRITICAL — nghiêm trọng, cần escalate"),
            ("success", "**Narrative sections:**\n\n• **Summary**: tóm tắt 1–2 câu\n• **Accomplishments**: tuần/tháng này làm được gì\n• **Planned Next**: kế hoạch kỳ tới\n• **Blockers**: vấn đề đang chặn\n\nCompletion % pre-fill từ project data."),
        ],
    },
    {
        "key": "quality_checklist",
        "label": "✅ Quality Checklist (IL_9)",
        "module": "IL_9",
        "steps": [
            ("1", "Tab ✅ Quality Checklists → nhấn ➕ New Checklist",       "Loại: FAT / SAT / INSPECTION / COMMISSIONING / HANDOVER"),
            ("2", "Link tới Milestone (optional) → tracking payment release", ""),
            ("3", "Set Inspector (nội bộ), Customer Witness (nhập tên)",      ""),
            ("4", "Sau khi inspection: điền Total Items, Passed, Failed → Pass Rate tự tính", ""),
            ("5", "Status: PLANNED → IN_PROGRESS → PASSED/FAILED/CONDITIONAL", "FAILED: set Retest Date + Next Action"),
            ("6", "Sign-off: chọn Signed Off By + tick Customer Signed Off", "Chỉ PASSED + Customer Signed → milestone có thể chuyển PAID"),
            ("7", "Đính kèm test report, sign-off sheet, photos",            "Multi-file"),
        ],
        "tips": [
            ("info",    "**Checklist Types:**\n\n• **FAT** — Factory Acceptance Test\n• **SAT** — Site Acceptance Test\n• **INSPECTION** — Quality inspection\n• **COMMISSIONING** — System commissioning\n• **HANDOVER** — Project handover\n• **SAFETY** — Safety inspection"),
            ("success", "**Pass → Payment flow:**\n\nQuality PASSED + Customer Signed Off\n→ Milestone status = COMPLETED\n→ Invoice → Milestone PAID\n\nFAILED → set Retest Date + Next Action\n→ Fix → Retest → PASSED"),
        ],
    },
]

# Build lookup: key → index, label → SOP
SOP_BY_KEY   = {s["key"]: s for s in SOP_REGISTRY}
SOP_BY_LABEL = {s["label"]: s for s in SOP_REGISTRY}

# Group SOPs by module for navigation
SOP_BY_MODULE = {}
for sop in SOP_REGISTRY:
    SOP_BY_MODULE.setdefault(sop["module"], []).append(sop)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 6: Q&A REGISTRY                                                   ║
# ║  Nhóm theo CHỦ ĐỀ (không flat) — dễ tra cứu, dễ training                  ║
# ║  Thứ tự: theo luồng công việc thực tế                                      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

QA_GROUPS = [
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # GROUP 1: Cost Tracking — Labor & Expense (IL_3)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {
        "group": "💰 Cost Tracking — Labor & Expense",
        "icon": "💰",
        "module": "IL_3",
        "items": [
            {
                "id": "Q1", "tags": ["labor", "expense", "công trình"],
                "question": "Kỹ sư đi công trình 3 ngày liên tục, phát sinh nhiều loại chi phí, ghi thế nào?",
                "situation": "Kỹ sư A đi Hà Nội 3 ngày: lắp đặt thiết bị, ở khách sạn, đi máy bay.",
                "sop": [
                    "Tạo **1 Labor Log**: phase = IMPLEMENTATION, man_days = 3, is_on_site = ✅, đính kèm timesheet.",
                    "Tạo **3 Expense riêng biệt**: (1) AIRFARE — vé đi về, (2) HOTEL — 2 đêm, (3) MEAL — ăn uống 3 ngày.",
                    "Lý do tách expense: mỗi loại có chứng từ và category riêng, phục vụ phân tích chi phí.",
                ],
                "note": "", "warning": "",
            },
            {
                "id": "Q2", "tags": ["expense", "tiền mặt", "chứng từ"],
                "question": "Mua vật tư tiêu hao bằng tiền mặt tại công trình, không có hóa đơn VAT, ghi được không?",
                "situation": "Kỹ sư mua dây cáp, vít tại chợ công trình bằng tiền mặt, chỉ có phiếu thu tay.",
                "sop": [
                    "**Ghi được** — tạo Expense với Category = CONSUMABLES, phase tương ứng.",
                    "**Attachment**: chụp ảnh phiếu thu tiền mặt, hoặc biên bản mua hàng có chữ ký kỹ sư + xác nhận PM.",
                    "**Receipt Number**: đánh số nội bộ (VD: CASH-2025-001).",
                    "**Vendor Name**: tên cửa hàng hoặc địa điểm mua.",
                ],
                "note": "",
                "warning": "Finance có thể từ chối approve nếu không có chứng từ. PM nên thỏa thuận quy trình mua hàng tiền mặt trước khi dự án bắt đầu.",
            },
            {
                "id": "Q3", "tags": ["subcontractor", "ngoại tệ", "labor"],
                "question": "Thuê subcontractor nước ngoài, thanh toán bằng USD, ghi thế nào?",
                "situation": "Thuê công ty Nhật chuyên điều chỉnh robot, contract USD 5,000 lumpsum.",
                "sop": [
                    "**Nếu theo ngày công**: tạo Labor Log, điền subcontractor_name = tên công ty, man_days theo hợp đồng, daily_rate = rate đã quy đổi VND.",
                    "**Nếu thanh toán lumpsum**: tạo Expense, Category = INSTALLATION_LABOR, Amount = 5000, Currency = USD. Hệ thống tự tính Amount VND.",
                    "**Kiểm tra exchange rate**: nếu ⚠️ fallback, nhập tỷ giá thực tế từ sao kê chuyển khoản.",
                    "**Attachment**: đính kèm invoice subcontractor và chứng từ chuyển khoản.",
                ],
                "note": "Ưu tiên dùng Expense (lumpsum) khi không thể tách theo ngày công cụ thể.",
                "warning": "",
            },
            {
                "id": "Q5", "tags": ["pre-sales", "labor", "phase"],
                "question": "Kỹ sư vừa làm pre-sales vừa tham gia implementation trong cùng tháng, ghi thế nào?",
                "situation": "Tuần 1-2: khảo sát pre-sales (trước ký HĐ). Tuần 3-4: lắp đặt thiết bị (sau ký HĐ).",
                "sop": [
                    "Tách thành **2 Labor Log riêng biệt**:",
                    "**Log 1**: phase = PRE_SALES, man_days = số ngày khảo sát, presales_allocation = COGS (vì dự án đã GO).",
                    "**Log 2**: phase = IMPLEMENTATION, man_days = số ngày lắp đặt, is_on_site = ✅.",
                    "Nếu cùng 1 ngày làm 2 việc: mỗi log dùng man_days = 0.5.",
                ],
                "note": "PRE_SALES allocation COGS → vào D-presales khi sync. IMPLEMENTATION → vào D-direct. Hai khoản được theo dõi riêng.\n\n**Lưu ý với Pre-sales Costs (không phải Labor Log):** chỉ các category DEMO_TRANSPORT, TRAVEL_SPECIAL, POC_EXECUTION, WIFI_SURVEY, ENGINEERING_STUDY, CUSTOM_SAMPLE, OTHER mới được tổng hợp vào E-presales khi Sync. PROTOTYPE và CUSTOM_DEMO không được đưa vào COGS Actual.",
                "warning": "",
            },
            {
                "id": "Q6", "tags": ["FAT", "nước ngoài", "ngoại tệ", "expense"],
                "question": "FAT tại nhà máy khách hàng ở Hàn Quốc, chi phí bằng KRW, ghi thế nào?",
                "situation": "2 kỹ sư bay sang Seoul 5 ngày FAT. Chi phí bằng KRW: vé máy bay, khách sạn, ăn uống, visa.",
                "sop": [
                    "**Labor Log**: phase = FAT, is_on_site = ✅ (nước ngoài vẫn tính on-site), man_days = 5 × 2 kỹ sư.",
                    "**Expenses bằng KRW**: chọn Currency = KRW, hệ thống fetch tỷ giá KRW/VND.",
                    "Nếu ⚠️ fallback rate: nhập tỷ giá thực tế từ sao kê thẻ/chuyển khoản ngân hàng.",
                    "**VISA**: tạo Expense riêng, Category = VISA, phase = FAT.",
                    "**INSURANCE**: tạo Expense riêng, Category = INSURANCE.",
                ],
                "note": "Tỷ giá nên là tỷ giá thực tế ngày thanh toán (trên sao kê ngân hàng), không phải tỷ giá niêm yết.",
                "warning": "",
            },
            {
                "id": "Q7", "tags": ["warranty", "bảo hành", "expense", "labor"],
                "question": "Dự án đã COMPLETED, khách hàng gọi bảo hành, chi phí xử lý ghi vào đâu?",
                "situation": "3 tháng sau khi bàn giao, encoder hỏng. Gửi kỹ sư đến sửa 2 ngày + thay linh kiện.",
                "sop": [
                    "**Chuyển status dự án → WARRANTY** (Edit dự án).",
                    "**Labor Log**: phase = WARRANTY, man_days = 2, is_on_site = ✅.",
                    "**Expense**: Category = EQUIPMENT_TRANSPORT (gửi linh kiện), phase = WARRANTY.",
                    "Expenses phase WARRANTY được tách ra khỏi khoản E — theo dõi riêng để đối chiếu với F.",
                    "**Cập nhật COGS Actual thủ công**: f_warranty_actual_used = tổng chi phí bảo hành đã dùng.",
                ],
                "note": "**f_warranty_actual_used chỉ để theo dõi**, không tham gia tính total_cogs. Công thức tính F_net = f_warranty_provision − f_warranty_released. Muốn GP% phản ánh chi phí bảo hành thực tế: cập nhật f_warranty_released (phần dự phòng đã giải phóng) và Sync lại.",
                "warning": "",
            },
            {
                "id": "Q8", "tags": ["sai sót", "sửa", "approve", "labor"],
                "question": "Kỹ sư nhập sai man_days (5 ngày thay vì 3 ngày), đã bị approve rồi, xử lý thế nào?",
                "situation": "Labor log đã APPROVED với man_days = 5, thực tế chỉ có 3 ngày.",
                "sop": [
                    "**Phương án duy nhất qua UI**: Tạo Labor Log mới với man_days = **-2** (âm để bù trừ), description = `Điều chỉnh sai sót log #[ID]`, cùng phase và work_date với log gốc.",
                    "Log bù trừ cũng cần được **Approve** để có hiệu lực trong Sync COGS.",
                    "**Nếu có quyền Admin DB**: Reject log gốc về PENDING → sửa man_days = 3 → submit lại để Approve. Đây là cách sạch hơn nhưng cần truy cập trực tiếp DB.",
                ],
                "note": "",
                "warning": "Hệ thống chỉ cho sửa/xóa khi approval_status = PENDING. Sau APPROVED, UI bị khóa để đảm bảo audit trail. Chức năng Reject qua UI hiện chưa có — chỉ Admin DB mới thực hiện được.",
            },
            {
                "id": "Q15", "tags": ["overview", "dashboard", "approve", "cost tracking"],
                "question": "Làm sao xem tổng chi phí tất cả dự án và approve nhanh từ 1 chỗ?",
                "situation": "PM quản lý 7 dự án, muốn xem tổng hợp cost và approve pending entries mà không vào từng dự án.",
                "sop": [
                    "**Vào Cost Tracking** → để Project = **'All Projects'** ở sidebar (mặc định).",
                    "**Dashboard hiển thị**: tổng Man-Days, Labor Cost, Expenses (approved) và số Pending Items.",
                    "**Bảng Per-Project Summary**: so sánh labor/expense giữa các dự án.",
                    "**Pending Approvals** (PM only): 2 tab Labor/Expenses — xem tất cả entries cần approve across projects.",
                    "**Approve All**: nhấn nút để approve hàng loạt. Hoặc vào từng project để approve từng entry.",
                ],
                "note": "Dùng Date Range filter để xem cost theo tháng. Phase filter để chỉ xem ví dụ IMPLEMENTATION.",
                "warning": "",
            },
        ],
    },

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # GROUP 2: Project & Contract (IL_1 / IL_4)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {
        "group": "📁 Project & Contract",
        "icon": "📁",
        "module": "IL_1",
        "items": [
            {
                "id": "Q4", "tags": ["hợp đồng", "amended", "tỷ giá"],
                "question": "Hợp đồng được ký phụ lục tăng giá, cập nhật thế nào?",
                "situation": "Scope tăng thêm 1 tầng kho, ký phụ lục +200 triệu VND.",
                "sop": [
                    "**Edit dự án → tab Financial**: nhập giá trị phụ lục vào ô **Amended Value**. KHÔNG thay đổi Contract Value gốc.",
                    "Hệ thống dùng COALESCE(amended_contract_value, contract_value) → Amended được ưu tiên.",
                    "**Sync COGS Actual lại**: sales_value tự cập nhật theo Amended Value, GP% tính lại.",
                    "**Tạo thêm Estimate V2**: cập nhật scope mới, activate để baseline Variance chính xác hơn.",
                ],
                "note": "Contract Value gốc được giữ nguyên để lưu lịch sử đàm phán.",
                "warning": "",
            },
            {
                "id": "Q11", "tags": ["kéo dài", "delay", "scope", "labor"],
                "question": "Dự án bị kéo dài 6 tháng so với kế hoạch, tốn thêm nhiều công lao động, cần làm gì?",
                "situation": "Dự án 12 tháng thực tế thành 18 tháng do khách hàng thay đổi thiết kế liên tục.",
                "sop": [
                    "**Tiếp tục ghi Labor Logs đầy đủ** — tất cả công lao động thêm ghi bình thường.",
                    "**Tạo Estimate V2**: cập nhật man_days theo thực tế, activate để GP% estimate sát hơn.",
                    "**Cập nhật Timeline**: sửa estimated_end_date trong dự án.",
                    "**Nếu scope tăng do lỗi KH**: đàm phán Amended Contract, cập nhật Amended Value sau khi ký phụ lục.",
                    "**Variance sau kết thúc**: khoản D sẽ lệch dương lớn — điền root_cause rõ ràng (delay do KH / nhà thầu phụ / thiết kế thay đổi).",
                ],
                "note": "Root cause chính xác trong Variance → Benchmark chất lượng → estimate tốt hơn cho dự án tương lai.",
                "warning": "",
            },
            {
                "id": "Q12", "tags": ["pre-sales", "NO-GO", "SGA", "allocation"],
                "question": "Dự án vừa có kết quả NO-GO, chi phí pre-sales đã ghi trước đó xử lý thế nào?",
                "situation": "Đã ghi 5 Labor Logs và 3 Pre-sales Costs (Layer 2) trong giai đoạn estimate.",
                "sop": [
                    "**Labor Logs phase PRE_SALES**: cập nhật presales_allocation = **SGA** cho từng log (hoặc liên hệ PM/Admin để bulk update).",
                    "**Pre-sales Costs Layer 2**: dùng chức năng **Bulk Update Allocation** → chọn SGA → toàn bộ Layer 2 được cập nhật một lần.",
                    "**Layer 1**: luôn là SGA, không cần thay đổi.",
                    "**Chuyển Status dự án → NO_GO**.",
                ],
                "note": "Layer 1 (standard pre-sales) luôn vào SGA bất kể kết quả. Chỉ Layer 2 (special) mới cần quyết định.",
                "warning": "",
            },
            {
                "id": "Q13", "tags": ["spare-part", "SPR", "project type"],
                "question": "Dự án bán spare part cho khách hàng, chọn Project Type nào? COGS tính thế nào?",
                "situation": "Khách hàng đặt mua bộ encoder thay thế + yêu cầu kỹ sư đến lắp 1 ngày.",
                "sop": [
                    "**Project Type**: chọn **[SPR] Spare Parts Supply**.",
                    "**A — Equipment Cost**: giá mua linh kiện từ hãng (CIF/FOB).",
                    "**B — Logistics**: α mặc định = 0.08 (nhập khẩu). Override nếu mua nội địa.",
                    "**D — Labor**: nếu có kỹ sư lắp, ghi Labor Log bình thường (man_days = 1).",
                    "**Estimate**: nhập A, sales value, man_days nếu có. B/E/F tính tự động.",
                ],
                "note": "SPR thường có A cao (mua hàng), D thấp (ít labor). GP% chủ yếu phụ thuộc vào markup trên A.",
                "warning": "",
            },
            {
                "id": "Q14", "tags": ["service", "SVC", "project type", "man-day"],
                "question": "Hãng thuê mình cung cấp đội kỹ sư triển khai, không bán sản phẩm, dùng project type nào?",
                "situation": "Partner Nhật thuê 3 kỹ sư deploy hệ thống 2 tháng, thanh toán T&M theo man-day.",
                "sop": [
                    "**Project Type**: chọn **[SVC] Service Deployment**.",
                    "**A — Equipment**: bằng 0 hoặc rất nhỏ (chỉ tools/consumables nếu có).",
                    "**D — Labor**: là chi phí chính. Ghi Labor Log đầy đủ mỗi ngày/tuần.",
                    "**E — Travel**: β mặc định = 0.50 (kỹ sư đi site nhiều). Ghi Expense cho mỗi chuyến.",
                    "**Billing Type**: nên chọn TIME_MATERIAL nếu thanh toán theo man-day, hoặc LUMP_SUM nếu fixed price.",
                ],
                "note": "SVC có D chiếm tỷ trọng lớn nhất trong COGS. Theo dõi man-days thực tế vs estimate rất quan trọng.",
                "warning": "",
            },
        ],
    },

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # GROUP 3: COGS & Variance (IL_4)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {
        "group": "📈 COGS, Variance & Benchmark",
        "icon": "📈",
        "module": "IL_4",
        "items": [
            {
                "id": "Q9", "tags": ["invoice", "nhập khẩu", "COGS actual", "A", "B"],
                "question": "Nhận invoice thiết bị từ supplier nước ngoài, muốn ghi A và B vào COGS Actual, làm thế nào?",
                "situation": "Nhận invoice CIF từ nhà cung cấp Nhật. Forwarder chưa có invoice hoàn chỉnh.",
                "sop": [
                    "**A — Equipment Cost**: nhập giá trị thiết bị theo invoice supplier (EXW hoặc FOB). Ghi chú: số invoice, ngày, tên nhà cung cấp.",
                    "**B — Logistics & Import**: nhập SAU KHI có invoice forwarder đầy đủ (freight + insurance + customs duty + port charges + trucking).",
                    "Nếu chưa có invoice B: **để B trống**, sync với B = 0. Khi có invoice B, cập nhật và sync lại.",
                ],
                "note": "Mỗi lần sync là một lần overwrite D và E nhưng giữ nguyên A, B, C, F đã nhập.",
                "warning": "",
            },
            {
                "id": "Q10", "tags": ["milestone", "thanh toán", "overdue"],
                "question": "Milestone thanh toán đã đến hạn nhưng khách hàng chưa trả, cập nhật thế nào?",
                "situation": "Milestone 'Nghiệm thu kỹ thuật' planned date 30/6 đã qua, khách hàng chưa chốt.",
                "sop": [
                    "**Edit milestone**: chuyển status → **OVERDUE**.",
                    "**Completion Notes**: ghi lý do và ngày liên hệ cuối (VD: *Email 02/7: KH yêu cầu hoãn đến 15/7, đính kèm*).",
                    "**Khi nhận thanh toán**: điền actual_date và chuyển status → **PAID**.",
                ],
                "note": "Hệ thống không tự gửi nhắc nhở — PM cần chủ động theo dõi và escalate lên Sales/Director khi cần.",
                "warning": "",
            },
            {
                "id": "Q17", "tags": ["COGS", "portfolio", "dashboard", "overview"],
                "question": "Làm sao xem tổng quan sức khỏe COGS tất cả dự án cùng lúc?",
                "situation": "Director muốn biết dự án nào đang over budget, dự án nào chưa sync, GP% portfolio đang bao nhiêu.",
                "sop": [
                    "**Vào COGS Dashboard** → để Project = **'All Projects'** (mặc định).",
                    "**4 KPIs**: Avg Est GP%, Avg Act GP%, Projects Synced, Not Synced.",
                    "**Bảng Portfolio Health**: mỗi dự án 1 dòng — Est COGS, Act COGS, Variance%, Budget%, GP%, Finalized.",
                    "**Health indicator**: 🟢 variance ≤5%, 🟡 5–10%, 🔴 >10%, ⚪ chưa có data.",
                    "**Filter Status** ở sidebar: chỉ xem IN_PROGRESS, COMPLETED, hoặc All.",
                ],
                "note": "Dự án 🔴 (variance >10%) cần kiểm tra nguyên nhân ngay — vào project đó → tab Variance.",
                "warning": "",
            },
            {
                "id": "Q18", "tags": ["variance", "generate", "COGS", "root cause"],
                "question": "Dự án vừa COMPLETED, cần làm Variance Analysis nhưng có 7 khoản phải nhập, có cách nhanh hơn không?",
                "situation": "Dự án xong, đã Sync COGS, cần điền Variance cho A–F + TOTAL trước khi Finalize.",
                "sop": [
                    "**Tab Variance → nhấn ⚡ Generate All Variance**.",
                    "Hệ thống tự tạo/cập nhật **7 rows** (A, B, C, D, E, F, TOTAL) từ Estimate vs COGS Actual.",
                    "Estimated Amount, Actual Amount, Variance%, Impact — tất cả auto-fill.",
                    "**Bổ sung Root Cause + Corrective Action** cho khoản có variance >5% (hệ thống highlight bằng ⚠️).",
                    "Tick chọn dòng → nhấn ✏️ Edit Variance để nhập Root Cause.",
                ],
                "note": "Nếu đã Generate trước đó, nhấn lại sẽ **cập nhật** (upsert) — không tạo trùng. An toàn nhấn nhiều lần.",
                "warning": "",
            },
            {
                "id": "Q19", "tags": ["benchmark", "auto-fill", "hệ số", "α", "β", "γ"],
                "question": "Tạo Benchmark cho dự án vừa đóng, phải nhập nhiều hệ số α/β/γ quá, có cách tự điền không?",
                "situation": "Dự án CLOSED, cần tạo Benchmark để lưu trữ kinh nghiệm cho dự án tương lai.",
                "sop": [
                    "**Tab Benchmarks → nhấn ➕ Add** — hệ thống **auto-fill** toàn bộ.",
                    "**Project Type + Source Project**: tự chọn theo project hiện tại.",
                    "**α/β/γ Used**: lấy từ Estimate (alpha_rate, beta_rate, gamma_rate).",
                    "**α/β/γ Actual**: tính từ COGS Actual (B/A, E/D, F/(A+C)).",
                    "**Man-Days Est/Act, GP% Est/Act**: lấy từ Estimate + COGS Actual.",
                    "**Chỉ cần nhập**: Lessons Learned, Key Risk Factors, Recommendations.",
                ],
                "note": "Hệ số Recommended mặc định = Actual (người dùng có thể chỉnh). Benchmark giúp cải thiện default coefficients cho dự án tương lai cùng type.",
                "warning": "",
            },
            {
                "id": "Q20", "tags": ["budget", "over budget", "progress", "COGS"],
                "question": "Làm sao biết dự án đang tiêu bao nhiêu % ngân sách COGS?",
                "situation": "Dự án đang IN_PROGRESS, muốn biết chi phí thực tế đã dùng bao nhiêu so với estimate.",
                "sop": [
                    "**Vào COGS Dashboard → chọn project → tab Actual COGS**.",
                    "**Budget progress bar** hiện ngay trên bảng: Actual COGS / Estimated COGS × 100%.",
                    "🟢 < 90%: còn dư | ⚠️ 90–100%: gần hết | 🔴 > 100%: over budget.",
                    "**Xem nhanh nhiều dự án**: để Project = 'All Projects' → cột Budget% trong bảng portfolio.",
                ],
                "note": "Budget bar chỉ hiện khi có cả Estimate (active) VÀ COGS Actual đã Sync. Chưa Sync = chưa có data actual.",
                "warning": "",
            },
        ],
    },

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # GROUP 4: Estimate & Line Items (IL_2)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {
        "group": "📊 Estimate & Line Items",
        "icon": "📊",
        "module": "IL_2",
        "items": [
            {
                "id": "Q21", "tags": ["estimate", "product", "costbook", "báo giá", "A", "C"],
                "question": "Nhận báo giá từ NCC, muốn nhập chi tiết từng item vào Estimate với giá gốc từ Costbook, làm sao?",
                "situation": "Hikrobot gửi costbook mới: AMR Q2 @$15,200, Charging @$2,800. Muốn thêm vào Estimate với traceability.",
                "sop": [
                    "**Vào Estimate GP → tab New Estimate → nhấn 🔍 Equipment (A) hoặc 🔧 Fabrication (C)**.",
                    "**Search product**: gõ tên hoặc mã (VD: 'AMR', 'Q2', 'charging'). Hệ thống tìm trong 336 products.",
                    "**Chọn Costbook entry**: hệ thống hiện danh sách costbooks có product này (Active ưu tiên). Auto-fill: cost price, currency, vendor name, quote ref.",
                    "**Optional — chọn Quotation**: nếu đã có báo giá bán cho KH, selling price tự điền. Lọc theo customer của project.",
                    "**Nhập Qty** → hệ thống tính: Cost total, Sell total, Item GP%.",
                    "**📎 Attach vendor quote** (optional): upload PDF báo giá cho hạng mục này.",
                    "Nhấn ✅ Add to Estimate → item xuất hiện trong bảng line items.",
                ],
                "note": "Mỗi line item lưu traceability: product_id, costbook_detail_id, vendor, quote ref. Khi xem Active Estimate, có thể trace nguồn giá từng item.",
                "warning": "",
            },
            {
                "id": "Q22", "tags": ["estimate", "pre-fill", "revision", "scope change", "line items"],
                "question": "Khách hàng thay đổi scope, cần tạo Estimate V2 dựa trên V1. Có cách nào nhanh hơn nhập lại từ đầu?",
                "situation": "Estimate V1 đã GO, nhưng khách hàng thêm 10 trolley. Cần revision mới mà không mất data V1.",
                "sop": [
                    "**Tab New Estimate → tick '📋 Pre-fill from Rev X'**.",
                    "Tất cả tự động copy: coefficients, overrides, assessment notes + **toàn bộ line items** từ Rev trước.",
                    "**Sửa line items**: thêm items mới (🔍 Add Product), xóa items cũ (select → 🗑 Remove), đổi Qty.",
                    "**Coefficients**: điều chỉnh nếu scope change ảnh hưởng α/β/γ hoặc man-days.",
                    "Label = 'Rev 2 — scope change +10 trolley'. Ghi lý do vào Assessment Notes.",
                    "Nhấn 💾 Save & Activate → Rev 2 + line items mới tự activated.",
                ],
                "note": "Rev 1 vẫn lưu trong History (kể cả line items). Có thể activate lại Rev cũ bất cứ lúc nào. History hiện α/β/γ để so sánh giữa revisions.",
                "warning": "",
            },
            {
                "id": "Q23", "tags": ["estimate", "attachment", "báo giá", "chứng từ", "S3"],
                "question": "Muốn lưu file báo giá từ supplier/NCC cùng với Estimate, upload ở đâu?",
                "situation": "Có PDF báo giá thiết bị từ Hikrobot, báo giá rack từ Hải Long, scope doc. Muốn lưu kèm Estimate.",
                "sop": [
                    "**Có 2 cấp attachment:**",
                    "**① Per line item** — trong dialog 🔍 Add Product: file uploader cho báo giá vendor cụ thể của hạng mục đó. VD: PDF báo giá Hải Long cho 32 rack.",
                    "**② Per estimate** — phần **📎 Estimate Attachments** (bên dưới line items, trước Coefficients form): upload scope, BOQ, technical proposal. Nhiều files cùng lúc.",
                    "Khi Save & Activate, tất cả files upload lên **S3** và link với estimate/line item.",
                    "**Xem lại**: tab Active Estimate hiện danh sách attachments + download links (hết hạn sau 10 phút).",
                ],
                "note": "Line item attachments hiện icon 📎 trong bảng. Estimate attachments hiện ở cuối tab Active Estimate với nút Download.",
                "warning": "",
            },
            {
                "id": "Q24", "tags": ["estimate", "SPR", "SVC", "quick", "costbook"],
                "question": "Dự án Spare Parts (SPR) chỉ mua hàng gửi cho KH, dùng Estimate thế nào?",
                "situation": "Bán 5 bộ encoder cho khách. Costbook có giá mua $2,000/bộ. Quotation bán $3,200/bộ.",
                "sop": [
                    "**Chọn Type = QUICK**.",
                    "**🔍 Add Product (A)**: search encoder → chọn Costbook ($2,000) → chọn Quotation ($3,200) → Qty = 5.",
                    "Hệ thống auto-fill: A = 5 × $2,000 = $10,000 | Sales = 5 × $3,200 = $16,000.",
                    "**Coefficients**: α = 0.08 (nhập khẩu), D = 0, E = 0, F nhỏ.",
                    "GP tính tự động. Không cần điền C, D, E nếu không phát sinh.",
                    "**SVC (service)**: A = 0, không cần line items. Chỉ nhập D (man-days × rate) trong Coefficients.",
                ],
                "note": "Khi dùng product catalog + costbook, A và Sales tự tính từ line items. Override chỉ cần khi muốn nhập thủ công.",
                "warning": "",
            },
            {
                "id": "Q25", "tags": ["estimate", "costbook", "import", "bulk"],
                "question": "Dự án mới cần estimate nhanh từ costbook đã có sẵn, có cách import hàng loạt không?",
                "situation": "Costbook CB2026-31124 từ Hikrobot có 5 sản phẩm (AMR, charging, controller...). Muốn import tất cả vào estimate 1 lần.",
                "sop": [
                    "**Tab New Estimate → nhấn 📦 Import Costbook**.",
                    "Hệ thống hiện danh sách costbooks (Active ưu tiên, kèm vendor + số items).",
                    "**Chọn costbook** → preview tất cả products + giá.",
                    "**Nhập exchange rate** (nếu currency khác VND).",
                    "Nhấn **📦 Import X items** → tất cả products thêm vào line items với Qty = 1.",
                    "**Điều chỉnh**: đổi Qty cho từng item, xóa item không cần, thêm item manual.",
                    "Service products (is_service = 1) tự chuyển category thành SERVICE.",
                ],
                "note": "Import không trùng lặp — mỗi lần import thêm mới. Nhấn 🗑 Clear trước nếu muốn thay thế hoàn toàn. Sau import, vẫn có thể thêm items từ costbook/catalog khác.",
                "warning": "",
            },
        ],
    },

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # GROUP 5: Purchase Request (IL_5)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {
        "group": "🛒 Purchase Request & PO",
        "icon": "🛒",
        "module": "IL_5",
        "items": [
            {
                "id": "Q26", "tags": ["PR", "purchase request", "tạo", "submit"],
                "question": "Tạo Purchase Request (PR) mua thiết bị từ Estimate, quy trình thế nào?",
                "situation": "Dự án IN_PROGRESS, Estimate đã active có 10 items thiết bị. PM muốn tạo PR để mua hàng.",
                "sop": [
                    "**Sidebar**: chọn Project → nhấn ➕ **New PR**.",
                    "**Step ① Setup**: chọn Type = EQUIPMENT → COGS auto = A. Chọn Currency, Vendor, Priority, Required Date.",
                    "Tỷ giá auto-fetch (✅ Live / ⚠️ Fallback) — kiểm tra trước khi Next.",
                    "**Step ② Items**: nhấn 📋 **Import from Estimate** → hệ thống hiện items category A chưa có trong PR khác → chọn Import.",
                    "Có thể thêm ➕ **Add Manual Item** cho hạng mục ngoài Estimate.",
                    "**Step ③ Review**: kiểm tra Budget Impact (Estimated vs Previous PRs vs This PR). Approval Chain preview.",
                    "Nhấn ✅ **Create & Submit for Approval** → email tự gửi đến approver Level 1.",
                ],
                "note": "Type → COGS mapping: EQUIPMENT = A, FABRICATION = C, SERVICE = D, MIXED = multiple. Import chỉ hiện items phù hợp với COGS category đã chọn.",
                "warning": "",
            },
            {
                "id": "Q27", "tags": ["PR", "approval", "multi-level", "phê duyệt"],
                "question": "PR cần bao nhiêu cấp phê duyệt? Approver nhận thông báo thế nào?",
                "situation": "PR tổng giá trị 500 triệu VND, approval chain có 3 levels.",
                "sop": [
                    "**Số levels tự động xác định** từ tổng tiền VND + cấu hình trong Approval Config (IL_PURCHASE_REQUEST).",
                    "**Level thấp nhất có max_amount ≥ tổng VND** = số levels cần. VD: L1 max 200M, L2 max 500M → PR 500M cần **2 levels**.",
                    "**Submit** → email đến **L1 approver** (CC requester).",
                    "L1 approve → email đến **requester** (thông báo) + email đến **L2 approver** (yêu cầu approve).",
                    "L2 approve (final) → email đến **requester** + **CC PM** (để PM biết có thể tạo PO).",
                    "**Approver click 'Open in ERP'** trong email → direct đến PR dialog (login nếu chưa login).",
                ],
                "note": "Approval chain cấu hình ở trang IL 98 — Approval Config. Mỗi level gắn với 1 employee + max_amount + valid period.",
                "warning": "",
            },
            {
                "id": "Q28", "tags": ["PR", "reminder", "nhắc nhở", "pending"],
                "question": "PR đang chờ duyệt lâu quá, làm sao nhắc approver?",
                "situation": "PR đã submit 5 ngày, approver chưa phản hồi. PM muốn nhắc.",
                "sop": [
                    "**Cách 1 — My PRs tab**: chọn PR đang PENDING_APPROVAL → nhấn 📧 **Remind** ở action bar.",
                    "**Cách 2 — View dialog**: mở View PR → nhấn 📧 **Remind Approver**.",
                    "Hệ thống gửi email đến approver hiện tại với subject **[PR Reminder]** + số ngày pending.",
                    "Email kèm: urgency banner (🔴 >7 ngày, 🟡 >3 ngày), budget comparison, deep link.",
                ],
                "note": "Không có rate-limit — PM tự quyết khi nào nhắc. Tránh spam. Age indicator trên bảng: 🟡 >3d, 🔴 >7d.",
                "warning": "",
            },
            {
                "id": "Q29", "tags": ["PR", "revision", "chỉnh sửa", "reject"],
                "question": "Approver yêu cầu chỉnh sửa PR, requester xử lý thế nào?",
                "situation": "Approver request revision: 'Thiếu quotation cho item rack, bổ sung vendor quote ref.'",
                "sop": [
                    "Requester nhận email **[PR Revision]** → click Open in ERP → mở Edit dialog.",
                    "**Revision feedback** hiện banner vàng ở đầu dialog.",
                    "**Edit**: sửa items, thêm vendor_quote_ref, đổi vendor, thêm/xóa items.",
                    "**Header**: có thể đổi Priority, COGS Category, Required Date, Justification.",
                    "Nhấn **📤 Submit for Approval** → PR resubmit, approval level reset về 1.",
                ],
                "note": "PR bị Reject không thể edit — cần tạo PR mới. Revision Requested có thể edit và resubmit.",
                "warning": "",
            },
            {
                "id": "Q30", "tags": ["PR", "cancel", "hủy", "pending"],
                "question": "Muốn hủy PR đang PENDING_APPROVAL (chưa cần mua nữa), có được không?",
                "situation": "Scope thay đổi, không cần mua thiết bị đã tạo PR. PR đang chờ Level 1 approve.",
                "sop": [
                    "**Có thể hủy** — PR status DRAFT, REVISION_REQUESTED, hoặc PENDING_APPROVAL đều cancel được.",
                    "**Vào View PR** → nhấn **🗑 Cancel PR** → confirm dialog.",
                    "Hệ thống gửi email đến requester + CC PM + **CC pending approver** (để approver biết PR đã rút).",
                ],
                "note": "Cancel là vĩnh viễn, không thể hoàn tác. Tạo PR mới nếu cần mua lại.",
                "warning": "PR đã APPROVED hoặc PO_CREATED không thể cancel.",
            },
            {
                "id": "Q31", "tags": ["PR", "CC", "email", "thêm người"],
                "question": "Muốn CC thêm người (finance, director) vào email thông báo PR, làm thế nào?",
                "situation": "Submit PR mua thiết bị lớn, muốn CC director và kế toán trưởng.",
                "sop": [
                    "Tại mỗi action point (Submit, Approve, Reject, Revision, Create PO, Cancel) có widget **📧 CC thêm**.",
                    "Nhấn vào multiselect → chọn nhân viên từ danh sách (query từ employees table, chỉ hiện người có email).",
                    "Email tự động gửi TO đến người chính + CC danh sách đã chọn.",
                    "**Auto-CC** (không cần chọn): requester luôn CC khi submit, PM luôn CC khi approved/rejected/revision.",
                ],
                "note": "CC chỉ áp dụng cho lần gửi đó — không lưu cho lần sau. Chọn lại mỗi lần nếu cần.",
                "warning": "",
            },
            {
                "id": "Q32", "tags": ["PR", "budget", "over budget", "estimate"],
                "question": "PR vượt budget Estimate, hệ thống có cảnh báo không?",
                "situation": "Estimate category A = 1.5 tỷ. Đã có PR trước 800 triệu. PR mới thêm 900 triệu → tổng 1.7 tỷ > budget.",
                "sop": [
                    "**Có cảnh báo** — Step ③ Review trong wizard hiện bảng Budget Impact:",
                    "Bảng so sánh: Estimated | Previous PRs | ⭐ This PR | New Total | Remaining | Used %.",
                    "**🔴 Over budget**: banner đỏ + thông báo số tiền vượt.",
                    "**🟡 >85%**: banner vàng cảnh báo gần giới hạn.",
                    "**Vẫn cho submit** — cảnh báo nhưng không block. Approver sẽ thấy budget context khi approve.",
                ],
                "note": "Budget comparison cũng hiện trong View dialog và Approval dialog — approver thấy đầy đủ context để quyết định.",
                "warning": "",
            },
            {
                "id": "Q33", "tags": ["PR", "deep link", "email", "login"],
                "question": "Click link trong email nhưng chưa login, có bị mất link không?",
                "situation": "Approver nhận email PR, click 'Open in ERP', session đã hết hạn.",
                "sop": [
                    "**Không mất** — hệ thống lưu deep link trước khi kiểm tra login.",
                    "Trang login inline hiện ngay (không redirect về trang chủ).",
                    "Sau khi login → tự động mở đúng dialog (View / Approve / Edit tùy action trong link).",
                ],
                "note": "Deep link format: ...?pr_id=123&action=approve. Actions: view, approve, edit.",
                "warning": "",
            },
        ],
    },

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # GROUP 6: WBS — Phases, Tasks, Progress (IL_6 / IL_7 / IL_8 / IL_9)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {
        "group": "📋 WBS — Phases, Tasks & Execution",
        "icon": "📋",
        "module": "IL_6",
        "items": [
            {
                "id": "Q34", "tags": ["WBS", "phase", "template", "setup"],
                "question": "Dự án mới ký xong, bắt đầu setup WBS thế nào cho nhanh?",
                "situation": "Dự án AMR vừa CONTRACTED, PM cần setup phase + tasks cho team bắt đầu làm.",
                "sop": [
                    "**Vào IL_6 WBS** → chọn project → tab Phases → nhấn **📦 Load Template**.",
                    "Hệ thống tạo 7 phases chuẩn: Pre-Sales (5%), Design (15%), Procurement (10%), Implementation (35%), Commissioning (20%), Training (10%), Warranty (5%).",
                    "**Sửa Planned Start/End** cho từng phase theo timeline dự án.",
                    "**Tab Tasks → ➕ Add Task**: tạo tasks cho phase Implementation trước (thường lớn nhất).",
                    "Assign engineer cho mỗi task → engineer nhận email + thấy trong My Tasks.",
                ],
                "note": "Weight % của phases ảnh hưởng project completion calculation. Tổng nên = 100%.",
                "warning": "",
            },
            {
                "id": "Q35", "tags": ["WBS", "task", "engineer", "update"],
                "question": "Engineer update tiến độ task hàng ngày, cách nào nhanh nhất?",
                "situation": "Kỹ sư đang lắp đặt thiết bị, cuối ngày cần cập nhật progress.",
                "sop": [
                    "**Cách nhanh nhất**: IL_6 → tab 🙋 My Tasks → chọn task → nhấn **⚡ Quick Update**.",
                    "Kéo slider **%** (bước 5%) + chọn **Status** + nhập **Actual Hours**.",
                    "Nhấn 💾 Update — xong. Completion cascade tự chạy (task → phase → project).",
                    "**Nếu cần ghi chi tiết**: vào 👁️ View → tab 💬 Comments → ghi note.",
                    "**Nếu bị chặn**: chọn BLOCKED + nhập Blocker Reason → PM nhận email tự động.",
                ],
                "note": "Quick Update auto-log: mỗi lần đổi status hoặc % → ghi activity log (ai, lúc nào, từ → thành).",
                "warning": "",
            },
            {
                "id": "Q36", "tags": ["WBS", "blocked", "PM", "escalate"],
                "question": "Task bị BLOCKED, PM cần làm gì?",
                "situation": "Engineer báo BLOCKED: 'Chờ cable tray từ nhà thầu phụ, chưa giao theo cam kết'.",
                "sop": [
                    "PM nhận email 🔴 BLOCKED kèm blocker reason.",
                    "**Vào IL_6 → tab Tasks** → tìm task BLOCKED (icon 🔴, filter status=BLOCKED).",
                    "**View task → tab Comments**: đọc context engineer ghi. Ghi thêm comment nếu cần trao đổi.",
                    "**Tạo Issue**: vào IL_8 → Report Issue → link tới task bị block. Category = LOGISTICS/VENDOR.",
                    "**Resolve**: khi unblock → engineer đổi status IN_PROGRESS. Issue đổi RESOLVED → CLOSED.",
                ],
                "note": "Task BLOCKED không tự unblock — engineer phải chủ động đổi status khi hết chặn.",
                "warning": "",
            },
            {
                "id": "Q37", "tags": ["WBS", "completion", "cascade", "dashboard"],
                "question": "Project overall % tính thế nào? Có chính xác không?",
                "situation": "PM muốn hiểu cách tính completion % để báo cáo leadership.",
                "sop": [
                    "**Task level**: engineer nhập trực tiếp (slider 0–100%).",
                    "**Phase level**: weighted average tasks. Weight = estimated_hours. Nếu không set hours → simple average.",
                    "**Project level**: weighted average phases. Weight = weight_percent. Nếu không set weight → simple average.",
                    "**Cascade tự động**: mỗi khi task update → phase % tính lại → project % tính lại → lưu vào il_projects.",
                    "**Muốn chính xác**: set estimated_hours cho mỗi task + weight_percent cho mỗi phase.",
                ],
                "note": "Project overall % hiện trên project header trong IL_6. Cũng hiện trong Progress Reports (IL_9).",
                "warning": "Nếu không set weights/hours, tất cả tasks/phases có trọng số bằng nhau — kết quả kém chính xác.",
            },
            {
                "id": "Q38", "tags": ["WBS", "team", "allocation", "workload"],
                "question": "Muốn biết engineer nào đang quá tải (assign quá nhiều dự án), xem ở đâu?",
                "situation": "PM cần assign thêm người cho dự án mới nhưng muốn check ai còn capacity.",
                "sop": [
                    "**Vào IL_7 Team** → tab **📊 Workload Overview**.",
                    "Chọn employee từ dropdown → nhấn 🔍 Load Workload.",
                    "Hệ thống hiện: tất cả projects đang IN_PROGRESS + allocation % mỗi project.",
                    "**Total Allocation**: 🟢 < 80% (available) | 🟡 80–100% (near full) | 🔴 > 100% (over-allocated).",
                    "**Hoặc**: từ Team Roster → chọn member → nhấn 📊 Workload (shortcut).",
                ],
                "note": "Allocation % do PM nhập khi add member. Không tự tính từ labor logs — PM cần update thủ công khi scope thay đổi.",
                "warning": "",
            },
            {
                "id": "Q39", "tags": ["WBS", "issue", "risk", "trace"],
                "question": "Dự án có nhiều issues phát sinh, làm sao theo dõi tổng thể?",
                "situation": "Dự án IN_PROGRESS 3 tháng, đã có 8 issues với severity khác nhau.",
                "sop": [
                    "**Vào IL_8 → Tab Issues**: KPIs hiện Total, Open, Critical, Resolved.",
                    "Bảng sort theo severity (CRITICAL đầu tiên) → dễ thấy vấn đề nào cần xử lý trước.",
                    "**Filter** sidebar: Status, Severity, Category, Assigned To.",
                    "**View issue**: xem mô tả, impact, resolution, attachments.",
                    "**Link đến Risk**: nếu issue từ risk đã xảy ra (OCCURRED), trace ngược từ Risk Register.",
                ],
                "note": "Issue count hiện trong bảng (cột 📎 file_count). View dialog hiện danh sách files đính kèm.",
                "warning": "",
            },
            {
                "id": "Q40", "tags": ["WBS", "change order", "scope", "contract"],
                "question": "Khách hàng yêu cầu thêm scope, cần làm Change Order. Quy trình?",
                "situation": "KH yêu cầu thêm 2 robot vào dự án AMR. Cần điều chỉnh giá và timeline.",
                "sop": [
                    "**IL_8 → Tab Change Orders → ➕ New Change Order**.",
                    "Type = SCOPE_AND_COST. Nhập Original Value (HĐ hiện tại), Revised Value (+ thêm robot).",
                    "Schedule Impact: +30 days (thêm time để procurement + install).",
                    "**DRAFT → SUBMITTED**: gửi management duyệt nội bộ.",
                    "**APPROVED**: gửi KH confirm. Đính kèm email approval / signed amendment.",
                    "**Customer Confirm**: tick Customer Approved + nhập Customer Ref (PO/email ref).",
                    "**Cập nhật project**: edit project → Amended Contract Value += cost_impact.",
                    "**Tạo Estimate V2**: thêm robot vào line items, recalculate GP%.",
                ],
                "note": "CO Impact Summary hiện tổng approved + pending ở đầu tab. Useful cho negotiation.",
                "warning": "",
            },
            {
                "id": "Q41", "tags": ["WBS", "quality", "FAT", "SAT", "customer"],
                "question": "Dự án đến giai đoạn nghiệm thu FAT, ghi nhận kết quả ở đâu?",
                "situation": "Chạy FAT conveyor line 1: 50 test items, 47 pass, 3 fail. KH witness: Mr. Tanaka.",
                "sop": [
                    "**IL_9 → Tab Quality → ➕ New Checklist**: Type = FAT, Name = 'FAT — Conveyor Line 1'.",
                    "Link Milestone (nếu có): chọn milestone 'FAT Completion'.",
                    "Inspector = engineer chạy test, Customer Witness = 'Mr. Tanaka'.",
                    "**Sau test**: Edit checklist → Total = 50, Passed = 47, Failed = 3 → Pass Rate = 94%.",
                    "**Status = CONDITIONAL** (vì có 3 failed items).",
                    "**Next Action**: 'Fix encoder alignment + retest by 15/4'. Set Retest Date.",
                    "**Đính kèm**: test report PDF + photos.",
                    "**Sau retest**: update Passed = 50, Status = PASSED, Customer Signed Off = ✅.",
                ],
                "note": "Milestone ACCEPTANCE chỉ nên chuyển COMPLETED sau khi Quality Checklist PASSED + Customer Signed.",
                "warning": "",
            },
            {
                "id": "Q42", "tags": ["WBS", "progress", "report", "leadership"],
                "question": "Leadership yêu cầu weekly report cho tất cả dự án đang chạy. Tạo ở đâu?",
                "situation": "PM cần submit progress report mỗi thứ 6 cho director.",
                "sop": [
                    "**IL_9 → Tab Progress Reports → ➕ New Report**: Type = WEEKLY.",
                    "**RAG status**: chọn ON_TRACK / AT_RISK / DELAYED — hiện icon 🟢🟡🔴 trên dashboard.",
                    "**Completion %**: pre-fill từ project overall_completion_percent. Adjust nếu cần.",
                    "**Narrative**: điền Summary, Accomplishments (tuần này), Planned (tuần sau), Blockers.",
                    "**Status**: DRAFT → SUBMITTED (PM hoàn thành) → REVIEWED (Director đọc xong).",
                    "**Đính kèm**: export slide/PDF nếu có presentation riêng.",
                ],
                "note": "Schedule/Cost/Quality status set riêng → trên bảng hiện 3 cột RAG cho quick scan.",
                "warning": "",
            },
            {
                "id": "Q43", "tags": ["WBS", "attachment", "file", "multi"],
                "question": "Muốn đính kèm nhiều file cho 1 issue/task/checklist, có được không?",
                "situation": "Issue cần attach 3 files: ảnh hiện trường, email vendor, bản vẽ sửa đổi.",
                "sop": [
                    "**Có** — tất cả entity (task, issue, risk, CO, report, quality) hỗ trợ **multi-file**.",
                    "Mở View dialog → phần 📎 Attachments (cuối dialog, ngoài form).",
                    "Upload từng file: chọn file → nhập description (optional) → nhấn 📤 Upload.",
                    "Mỗi file lưu riêng: S3 + medias table + junction link. Download qua presigned URL.",
                    "**Xóa file**: nhấn 🗑 bên cạnh file → soft-delete junction (file vẫn còn trên S3).",
                ],
                "note": "File types: PDF, PNG, JPG, XLSX, DOCX. Max per file phụ thuộc S3 config.",
                "warning": "",
            },
        ],
    },

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # GROUP 7: UI & General Tips
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {
        "group": "🖥️ UI & Thao tác chung",
        "icon": "🖥️",
        "module": "general",
        "items": [
            {
                "id": "Q16", "tags": ["UI", "deselect", "action bar", "table"],
                "question": "Đã tick chọn 1 dòng trong bảng nhưng không tìm được cách bỏ chọn?",
                "situation": "Chọn nhầm dòng labor log, muốn bỏ chọn để chọn dòng khác.",
                "sop": [
                    "**Cách 1**: Nhấn nút **✖ Deselect** ở action bar bên dưới bảng.",
                    "**Cách 2**: Tick vào dòng khác để thay đổi selection.",
                    "**Action bar** hiện ra khi có dòng được chọn: gồm các nút Edit / Approve / Deselect.",
                ],
                "note": "Pattern áp dụng cho cả trang Projects, Labor Logs, Expenses, và Variance.",
                "warning": "",
            },
        ],
    },
]

# ── Flatten Q&A for search + tag filter ────────────────────────────────
QA_ALL = []
for grp in QA_GROUPS:
    for item in grp["items"]:
        item["_group"] = grp["group"]
        QA_ALL.append(item)

ALL_TAGS    = sorted({tag for qa in QA_ALL for tag in qa["tags"]})
ALL_GROUPS  = [g["group"] for g in QA_GROUPS]


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 7: UI — RENDERING                                                 ║
# ║  Tất cả logic hiển thị Streamlit nằm ở đây                                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# ── Helper: render status table from STATUS_TABLES ─────────────────────
def render_status_table(key: str):
    """Render a status/lifecycle table from STATUS_TABLES."""
    tbl = STATUS_TABLES[key]
    if "note" in tbl:
        st.caption(tbl["note"])
    df = pd.DataFrame(tbl["rows"], columns=tbl["columns"])
    col_config = {}
    if "col_widths" in tbl:
        for col, w in tbl["col_widths"].items():
            col_config[col] = st.column_config.TextColumn(width=w)
    st.dataframe(df, use_container_width=True, hide_index=True, column_config=col_config or None)


def render_email_table(key: str):
    """Render an email notification table from EMAIL_TABLES."""
    tbl = EMAIL_TABLES[key]
    if "note" in tbl:
        st.caption(tbl["note"])
    df = pd.DataFrame(tbl["rows"], columns=tbl["columns"])
    col_config = {}
    if "col_widths" in tbl:
        for col, w in tbl["col_widths"].items():
            col_config[col] = st.column_config.TextColumn(width=w)
    st.dataframe(df, use_container_width=True, hide_index=True, column_config=col_config or None)


def render_project_type_cards():
    """Render project type cards with highlight for new types."""
    tbl = STATUS_TABLES["project_types"]
    st.caption(tbl["note"])
    for code, name, desc, alpha, beta, gamma in tbl["rows"]:
        is_new = code in tbl.get("new_types", [])
        highlight = "border-left:4px solid #28A745;" if is_new else "border-left:4px solid #2E75B6;"
        new_badge = (' <span style="background:#28A745;color:white;padding:1px 6px;'
                     'border-radius:3px;font-size:10px;margin-left:6px">MỚI</span>') if is_new else ''
        st.markdown(f"""
        <div style="background:#F8F9FA;{highlight}
                    padding:8px 14px;margin-bottom:4px;border-radius:4px;">
            <span style="font-size:15px;font-weight:700;color:#1F4E79">[{code}]</span>
            <span style="font-weight:600">{name}</span>{new_badge}
            <span style="font-size:12px;color:#555;margin-left:8px">{desc}</span>
            <br><span style="font-size:11px;color:#888">α={alpha} &nbsp;|&nbsp; β={beta} &nbsp;|&nbsp; γ={gamma}</span>
        </div>
        """, unsafe_allow_html=True)


def render_cogs_formula():
    """Render COGS A→F formula cards."""
    st.caption(COGS_FORMULA["note"])
    for code, name, formula_est, source_actual, desc in COGS_FORMULA["items"]:
        st.markdown(f"""
        <div style="background:#EEF4FB;border-left:4px solid #2E75B6;
                    padding:8px 14px;margin-bottom:6px;border-radius:4px;">
            <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;">
                <span style="font-size:18px;font-weight:700;color:#1F4E79;min-width:20px">{code}</span>
                <span style="font-weight:600">{name}</span>
                <span style="font-size:12px;color:#555;flex:1">{desc}</span>
            </div>
            <div style="display:flex;gap:16px;margin-top:6px;flex-wrap:wrap;">
                <span style="font-size:12px"><b>Estimate:</b>
                    <code style="background:#DEF;padding:1px 6px;border-radius:3px">{formula_est}</code>
                </span>
                <span style="font-size:12px;color:#444"><b>Actual nguồn:</b> {source_actual}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.divider()
    cols = st.columns(len(COGS_FORMULA["summary_formulas"]))
    types = ["info", "success", "warning"]
    for i, (label, formula) in enumerate(COGS_FORMULA["summary_formulas"]):
        getattr(cols[i], types[i])(f"**{label}** = {formula}")


def render_sop(sop: dict):
    """Render an SOP with steps + tip boxes."""
    for step_num, step_desc, step_note in sop["steps"]:
        col_num, col_content = st.columns([0.6, 9.4])
        with col_num:
            st.markdown(
                f'<div style="background:#1F4E79;color:white;border-radius:50%;'
                f'width:32px;height:32px;display:flex;align-items:center;'
                f'justify-content:center;font-weight:700;font-size:14px;margin-top:4px">'
                f'{step_num}</div>',
                unsafe_allow_html=True,
            )
        with col_content:
            st.markdown(f"**{step_desc}**")
            if step_note:
                st.caption(f"💡 {step_note}")

    # Tip boxes
    if sop.get("tips"):
        st.divider()
        # Render in 2 columns if ≥ 2 tips, otherwise single
        tips = sop["tips"]
        if len(tips) >= 2:
            cols = st.columns(min(len(tips), 2))
            for i, (tip_type, tip_text) in enumerate(tips):
                with cols[i % 2]:
                    getattr(st, tip_type)(tip_text)
        else:
            for tip_type, tip_text in tips:
                getattr(st, tip_type)(tip_text)


def render_qa(qa: dict):
    """Render a single Q&A item inside an expander."""
    tag_html = " ".join(
        f'<span style="background:#EEF4FB;color:#1F4E79;padding:2px 8px;'
        f'border-radius:10px;font-size:11px;margin-right:4px">{t}</span>'
        for t in qa["tags"]
    )
    with st.expander(f"**{qa['id']}** — {qa['question']}"):
        st.markdown(tag_html, unsafe_allow_html=True)
        st.markdown(" ")

        if qa["situation"]:
            st.markdown(
                f'<div style="background:#F8F9FA;border-left:3px solid #6c757d;'
                f'padding:8px 14px;border-radius:4px;font-size:14px;color:#555;margin-bottom:12px">'
                f'📌 <em>{qa["situation"]}</em></div>',
                unsafe_allow_html=True,
            )

        st.markdown("**Cách thực hiện:**")
        for i, step in enumerate(qa["sop"], 1):
            st.markdown(f"{i}. {step}")

        if qa["note"]:
            st.info(f"💡 {qa['note']}")
        if qa["warning"]:
            st.warning(f"⚠️ {qa['warning']}")


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 8: PAGE LAYOUT                                                    ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

st.title("📚 IL Project — Hướng dẫn & Q&A")

tab_quickref, tab_sop, tab_qa, tab_map = st.tabs([
    "📋 Tham chiếu nhanh",
    "📝 SOP từng nghiệp vụ",
    "❓ Q&A tình huống thực tế",
    "🗺️ Sơ đồ tổng quan",
])


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — QUICK REFERENCE
# ─────────────────────────────────────────────────────────────────────────────
with tab_quickref:
    st.subheader("Vòng đời & Trạng thái dự án")
    render_status_table("project_lifecycle")

    st.divider()
    st.subheader("Loại dự án (Project Type)")
    render_project_type_cards()

    st.divider()
    st.subheader("Công thức COGS A→F")
    render_cogs_formula()

    st.divider()
    st.subheader("Kết quả Go / No-Go")
    cols = st.columns(3)
    for i, (label, icon, condition, method) in enumerate(GO_NOGO_THRESHOLDS["items"]):
        getattr(cols[i], method)(f"{icon} **{label}**\n\n{condition}")

    st.divider()
    st.subheader("🛒 Vòng đời Purchase Request")
    render_status_table("pr_lifecycle")

    st.divider()
    st.subheader("📧 Email Notification — PR Workflow")
    render_email_table("pr_emails")

    st.divider()
    st.subheader("Biểu tượng tỷ giá")
    rate_cols = st.columns(4)
    for i, (label, method, desc) in enumerate(EXCHANGE_RATE_ICONS):
        getattr(rate_cols[i], method)(f"**{label}**\n{desc}")

    st.divider()
    st.subheader("Thao tác bảng dữ liệu")
    st.caption("Pattern chung cho tất cả các trang: Projects, Cost Tracking (Labor / Expenses)")
    ui1, ui2, ui3 = st.columns(3)
    ui1.info("**Chọn dòng**\n\nTick checkbox bên trái → Action bar xuất hiện bên dưới bảng")
    ui2.success("**Action bar**\n\n👁️ View / ✏️ Edit / ✅ Approve / ✖ Deselect — tùy context")
    ui3.warning("**Bỏ chọn**\n\nNhấn **✖ Deselect** hoặc tick dòng khác")

    # ── WBS Module Quick Ref ──
    st.divider()
    st.subheader("📋 WBS Module — Trạng thái Task & Phase")
    st.caption("Module WBS (IL_6 → IL_9) quản lý tiến độ triển khai: Phases → Tasks → Issues → Risks → Change Orders → Progress Reports → Quality.")
    render_status_table("task_status")

    st.divider()
    st.subheader("🔧 Issue Severity & ⚠️ Risk Score")
    sc1, sc2 = st.columns(2)
    with sc1:
        render_status_table("issue_severity")
    with sc2:
        render_status_table("risk_score")

    st.divider()
    st.subheader("📝 Change Order & 📧 WBS Email")
    render_status_table("change_order_status")
    render_email_table("wbs_emails")

    st.divider()
    st.subheader("🔄 Completion Cascade")
    st.caption("Khi engineer update task % → hệ thống tự tính lại phase % → project % (weighted average).")
    cc1, cc2, cc3 = st.columns(3)
    cc1.info("**Task %**\n\nEngineer nhập trực tiếp\n(slider 0–100%)")
    cc2.success("**Phase %**\n\nWeighted AVG(tasks)\nWeight = estimated_hours")
    cc3.warning("**Project %**\n\nWeighted AVG(phases)\nWeight = weight_percent")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — SOP (grouped by module)
# ─────────────────────────────────────────────────────────────────────────────
with tab_sop:
    # Build module → SOPs for grouped display
    sop_labels = [s["label"] for s in SOP_REGISTRY]
    sop_choice = st.radio("Chọn nghiệp vụ:", sop_labels, horizontal=True, label_visibility="collapsed")

    sop = SOP_BY_LABEL[sop_choice]
    module = MODULES.get(sop["module"], {})
    module_badge = f'{module.get("icon", "")} {sop["module"]} — {module.get("name", "")}' if module else ""

    st.markdown(f"### {sop_choice}")
    if module_badge:
        st.caption(f"Module: {module_badge}")

    render_sop(sop)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — Q&A (grouped by topic)
# ─────────────────────────────────────────────────────────────────────────────
with tab_qa:
    st.markdown("Tra cứu nhanh cách xử lý các tình huống thực tế. Dùng ô tìm kiếm, lọc theo chủ đề, hoặc duyệt theo nhóm.")

    col_search, col_tag, col_group = st.columns([3, 2, 2])
    with col_search:
        search_text = st.text_input("🔍 Tìm kiếm", placeholder="VD: subcontractor, bảo hành, sai sót...",
                                    label_visibility="collapsed")
    with col_tag:
        tag_filter = st.multiselect("Lọc theo tag", ALL_TAGS, placeholder="Tất cả tags",
                                    label_visibility="collapsed")
    with col_group:
        group_filter = st.multiselect("Lọc theo nhóm", ALL_GROUPS, placeholder="Tất cả nhóm",
                                      label_visibility="collapsed")

    # Filter
    filtered = QA_ALL
    if search_text:
        q = search_text.lower()
        filtered = [
            qa for qa in filtered
            if q in qa["question"].lower()
            or q in qa["situation"].lower()
            or any(q in t for t in qa["tags"])
            or any(q in s.lower() for s in qa["sop"])
        ]
    if tag_filter:
        filtered = [qa for qa in filtered if any(t in qa["tags"] for t in tag_filter)]
    if group_filter:
        filtered = [qa for qa in filtered if qa["_group"] in group_filter]

    st.caption(f"Hiển thị {len(filtered)} / {len(QA_ALL)} tình huống")
    st.divider()

    if not filtered:
        st.info("Không tìm thấy tình huống phù hợp. Thử từ khóa khác.")
    else:
        # Group filtered results by group for display
        current_group = None
        for qa in filtered:
            if qa["_group"] != current_group:
                current_group = qa["_group"]
                st.markdown(f"#### {current_group}")
            render_qa(qa)

    st.divider()
    st.caption("Không tìm thấy tình huống bạn cần? Liên hệ Admin hoặc PM để được hỗ trợ.")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 4 — MODULE MAP (Sơ đồ tổng quan)
# ─────────────────────────────────────────────────────────────────────────────
with tab_map:
    st.subheader("🗺️ Bản đồ Module & Luồng công việc")
    st.caption("Tổng quan tất cả modules trong hệ thống IL và mối liên hệ giữa chúng.")

    for mod_id, mod in MODULES.items():
        sops_in_module = SOP_BY_MODULE.get(mod_id, [])
        qa_count = sum(1 for qa in QA_ALL if qa.get("_group", "").endswith(mod.get("name", "___")))

        sop_list = ", ".join(s["label"] for s in sops_in_module) if sops_in_module else "—"
        st.markdown(f"""
        <div style="background:#F8F9FA;border-left:4px solid #2E75B6;
                    padding:10px 16px;margin-bottom:6px;border-radius:4px;">
            <span style="font-size:16px;font-weight:700;color:#1F4E79">{mod['icon']} {mod_id}</span>
            <span style="font-weight:600;margin-left:8px">{mod['name']}</span>
            <br><span style="font-size:12px;color:#555">{mod['desc']}</span>
            <br><span style="font-size:11px;color:#888">SOPs: {sop_list}</span>
        </div>
        """, unsafe_allow_html=True)

    st.divider()
    st.subheader("📐 Luồng công việc chính")

    st.info(
        "**Luồng Pre-Sales → Close:**\n\n"
        "① Tạo Project (IL_1) → ② Lập Estimate (IL_2) → ③ Go/No-Go → ④ Ký hợp đồng\n"
        "→ ⑤ Setup WBS (IL_6) + Team (IL_7) → ⑥ Triển khai: Labor + Expense (IL_3)\n"
        "→ ⑦ Sync COGS (IL_4) → ⑧ Track Issues/Risks (IL_8) + Progress (IL_9)\n"
        "→ ⑨ Nghiệm thu FAT/SAT (IL_9) → ⑩ Variance + Finalize + Benchmark (IL_4)"
    )
    st.success(
        "**Luồng Mua hàng (PR/PO):**\n\n"
        "Estimate → ➕ New PR (IL_5) → Submit → Multi-level Approve → 🛒 Create PO → Gửi vendor"
    )
    st.warning(
        "**Luồng Change Order:**\n\n"
        "Scope change → ➕ New CO (IL_8) → Internal Approve → Customer Confirm\n"
        "→ Update Amended Value → New Estimate Rev → Sync COGS lại"
    )