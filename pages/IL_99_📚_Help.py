# pages/IL_99_📚_Help.py
"""
IL Project Management — Hướng dẫn sử dụng & Q&A tra cứu nhanh.
Standalone page, không cần DB connection.
"""

import streamlit as st

st.set_page_config(page_title="IL Help & Q&A", page_icon="📚", layout="wide")

# ══════════════════════════════════════════════════════════════════════════════
# DATA — SOP SECTIONS & Q&A
# ══════════════════════════════════════════════════════════════════════════════

QUICK_REF = {
    "🗂️ Vòng đời & Trạng thái": [
        ("DRAFT", "⚪", "Mới tạo, chưa estimate", "Tạo Estimate đầu tiên"),
        ("ESTIMATING", "🔵", "Đang lập dự toán COGS", "Hoàn thiện Estimate, tính GP%"),
        ("PROPOSAL_SENT", "📤", "Đã gửi báo giá", "Chờ phản hồi, cập nhật nếu cần"),
        ("GO", "🟢", "Quyết định GO", "Chuyển sang CONTRACTED"),
        ("CONDITIONAL", "🟡", "GO có điều kiện", "Xem xét điều chỉnh giá / scope"),
        ("NO_GO", "🔴", "Không tiếp tục", "Phân bổ pre-sales sang SGA"),
        ("CONTRACTED", "🟢", "Đã ký hợp đồng", "Bắt đầu ghi Labor Logs"),
        ("IN_PROGRESS", "🔵", "Đang triển khai", "Cập nhật Labor + Expense hàng tuần"),
        ("COMMISSIONING", "🔵", "Chạy thử / nghiệm thu", "Hoàn tất labor commissioning"),
        ("COMPLETED", "✅", "Hoàn thành", "Sync COGS Actual, lập Variance"),
        ("WARRANTY", "🛡️", "Trong bảo hành", "Ghi labor/expense phase WARRANTY"),
        ("CLOSED", "⬛", "Đã đóng hoàn toàn", "Tạo Benchmark"),
        ("CANCELLED", "❌", "Đã hủy", "Lưu hồ sơ"),
    ],
    "💰 Công thức COGS A→F": [
        # (code, name, formula_estimate, source_actual, desc)
        ("A", "Equipment Cost",    "Nhập thủ công",              "Nhập thủ công từ invoice supplier",           "Chi phí thiết bị, máy móc"),
        ("B", "Logistics & Import","B = A × α",                  "Nhập thủ công từ invoice forwarder",          "Vận chuyển, nhập khẩu, thuế"),
        ("C", "Custom Fabrication","Nhập thủ công",              "Nhập thủ công từ PO subcontractor",           "Gia công, chế tạo tùy chỉnh"),
        ("D", "Direct Labor",      "D = Man-days × Rate × Team", "Tự động: Labor Logs APPROVED (phase ≠ PRE_SALES, hoặc PRE_SALES + allocation=COGS)", "Nhân công trực tiếp"),
        ("E", "Travel & Site OH",  "E = D × β",                  "Tự động: Expenses APPROVED (phase ≠ PRE_SALES và ≠ WARRANTY) + Pre-sales costs SPECIAL/COGS (category hợp lệ)", "Đi lại, chi phí hiện trường"),
        ("F", "Warranty Reserve",  "F = (A + C) × γ",            "Nhập thủ công: provision / actual_used / released. F_net = provision − released", "Dự phòng bảo hành"),
    ],
}

SOP_STEPS = {
    "📝 Tạo dự án mới": [
        ("1", "Nhấn ➕ New Project ở sidebar", "Project Code tự sinh: IL-YYYY-UserID-NNN"),
        ("2", "Tab Basic: điền Project Name, Type, Customer, Status = DRAFT", "Project Name là trường bắt buộc duy nhất"),
        ("3", "Tab Financial: điền Contract Value, Currency, Exchange Rate", "Hệ thống tự fetch tỷ giá — xác nhận trước khi lưu"),
        ("4", "Tab Timeline: điền Est. Start / End", "Actual dates để trống, điền sau khi có thực tế"),
        ("5", "Tab Team: chọn PM và Sales", "Bắt buộc có PM"),
        ("6", "Nhấn 💾 Create → tạo Estimate ngay sau đó", "Không có Estimate = không có baseline Variance"),
    ],
    "🔢 Ghi Labor Log": [
        ("1", "Vào module Labor Logs của dự án", ""),
        ("2", "Điền Work Date, Phase đúng giai đoạn thực tế", "KHÔNG dùng PRE_SALES cho công việc sau khi ký hợp đồng"),
        ("3", "Chọn Worker (nội bộ) hoặc nhập subcontractor_name", ""),
        ("4", "Nhập Man-days (0.5 = nửa ngày, tối đa 3.0 mỗi entry), Daily Rate, tick Is On-site", "Cần ghi > 3 ngày: tạo nhiều entry (VD: 3 + 2). Daily Rate tự gợi ý theo Level chọn ở trên"),
        ("5", "Nếu Phase = PRE_SALES: chọn Presales Allocation (COGS/SGA)", "Dự án GO → COGS | NO_GO → SGA"),
        ("6", "Đính kèm timesheet / email xác nhận", ""),
        ("7", "Submit → Manager Approve → log vào COGS khi sync", "Log PENDING không được tính vào COGS"),
    ],
    "💳 Ghi Expense": [
        ("1", "Vào module Expenses của dự án", ""),
        ("2", "Điền Expense Date, Category đúng loại, Phase đúng giai đoạn", ""),
        ("3", "Nhập Amount và Currency. Exchange Rate tự fetch — kiểm tra lại", "Nếu ⚠️ fallback rate: nhập tỷ giá từ ngân hàng"),
        ("4", "Điền Vendor Name và Receipt Number", ""),
        ("5", "Upload scan hóa đơn / receipt vào Attachment", "Finance thường yêu cầu chứng từ trước khi approve"),
        ("6", "Submit → Finance Approve → expense vào COGS khi sync", "Expense WARRANTY không vào khoản E"),
    ],
    "🔄 Sync COGS Actual": [
        ("1", "Đảm bảo tất cả Labor Logs & Expenses đã được Approve", "Log/Expense PENDING bị bỏ qua hoàn toàn"),
        ("2", "Nhập thủ công A, B, C (nếu đã có hóa đơn từ supplier/forwarder)", "B bao gồm: freight + thuế nhập khẩu + phí thông quan"),
        ("3", "Nhấn 🔄 Sync COGS Actual", "D và E tự tổng hợp từ approved records"),
        ("4", "Kiểm tra actual_gp_percent so với estimated_gp_percent", "Lệch >5%: phân tích nguyên nhân ngay"),
        ("5", "KHÔNG Finalize cho đến khi dự án 100% kết thúc", "Finalize = khóa vĩnh viễn"),
    ],
    "✅ Đóng dự án & Benchmark": [
        ("1", "Đảm bảo tất cả Labor Logs & Expenses cuối cùng đã Approve", ""),
        ("2", "Nhập đủ A, B, C, F vào COGS Actual", "F: điền f_warranty_actual_used sau khi hết thời gian bảo hành"),
        ("3", "Sync COGS Actual lần cuối", ""),
        ("4", "Điền Variance: root_cause và corrective_action cho khoản lệch >5%", ""),
        ("5", "Finalize COGS Actual", "Không thể hoàn tác sau bước này"),
        ("6", "Chuyển Status dự án → CLOSED", ""),
        ("7", "Tạo Benchmark: điền hệ số thực tế α/β/γ và lessons learned", "Benchmark giúp cải thiện estimate cho dự án tương lai"),
    ],
}

QA_DATA = [
    {
        "id": "Q1",
        "tags": ["labor", "expense", "công trình"],
        "question": "Kỹ sư đi công trình 3 ngày liên tục, phát sinh nhiều loại chi phí, ghi thế nào?",
        "situation": "Kỹ sư A đi Hà Nội 3 ngày: lắp đặt thiết bị, ở khách sạn, đi máy bay.",
        "sop": [
            "Tạo **1 Labor Log**: phase = IMPLEMENTATION, man_days = 3, is_on_site = ✅, đính kèm timesheet.",
            "Tạo **3 Expense riêng biệt**: (1) AIRFARE — vé đi về, (2) HOTEL — 2 đêm, (3) MEAL — ăn uống 3 ngày.",
            "Lý do tách expense: mỗi loại có chứng từ và category riêng, phục vụ phân tích chi phí.",
        ],
        "note": "",
        "warning": "",
    },
    {
        "id": "Q2",
        "tags": ["expense", "tiền mặt", "chứng từ"],
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
        "id": "Q3",
        "tags": ["subcontractor", "ngoại tệ", "labor"],
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
        "id": "Q4",
        "tags": ["hợp đồng", "amended", "tỷ giá"],
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
        "id": "Q5",
        "tags": ["pre-sales", "labor", "phase"],
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
        "id": "Q6",
        "tags": ["FAT", "nước ngoài", "ngoại tệ", "expense"],
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
        "id": "Q7",
        "tags": ["warranty", "bảo hành", "expense", "labor"],
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
        "id": "Q8",
        "tags": ["sai sót", "sửa", "approve", "labor"],
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
        "id": "Q9",
        "tags": ["invoice", "nhập khẩu", "COGS actual", "A", "B"],
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
        "id": "Q10",
        "tags": ["milestone", "thanh toán", "overdue"],
        "question": "Milestone thanh toán đã đến hạn nhưng khách hàng chưa trả, cập nhật thế nào?",
        "situation": "Milestone 'Nghiệm thu kỹ thuật' planned date 30/6 đã qua, khách hàng chưa chốt.",
        "sop": [
            "**Edit milestone**: chuyển status → **OVERDUE**.",
            "**Completion Notes**: ghi lý do và ngày liên hệ cuối (VD: *Email 02/7: KH yêu cầu hoãn đến 15/7, đính kèm*) .",
            "**Khi nhận thanh toán**: điền actual_date và chuyển status → **PAID**.",
        ],
        "note": "Hệ thống không tự gửi nhắc nhở — PM cần chủ động theo dõi và escalate lên Sales/Director khi cần.",
        "warning": "",
    },
    {
        "id": "Q11",
        "tags": ["kéo dài", "delay", "scope", "labor"],
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
        "id": "Q12",
        "tags": ["pre-sales", "NO-GO", "SGA", "allocation"],
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
]

# Tags list for filter
ALL_TAGS = sorted({tag for qa in QA_DATA for tag in qa["tags"]})

# ══════════════════════════════════════════════════════════════════════════════
# PAGE LAYOUT
# ══════════════════════════════════════════════════════════════════════════════

st.title("📚 IL Project — Hướng dẫn & Q&A")

tab_quickref, tab_sop, tab_qa = st.tabs([
    "📋 Tham chiếu nhanh",
    "📝 SOP từng nghiệp vụ",
    "❓ Hỏi & Đáp tình huống thực tế",
])


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — QUICK REFERENCE
# ─────────────────────────────────────────────────────────────────────────────
with tab_quickref:
    st.subheader("Vòng đời & Trạng thái dự án")
    status_rows = QUICK_REF["🗂️ Vòng đời & Trạng thái"]
    import pandas as pd
    df_status = pd.DataFrame(status_rows, columns=["Trạng thái", "Icon", "Ý nghĩa", "Hành động tiếp theo"])
    st.dataframe(df_status, use_container_width=True, hide_index=True,
                 column_config={
                     "Trạng thái": st.column_config.TextColumn(width=140),
                     "Icon": st.column_config.TextColumn(width=50),
                     "Ý nghĩa": st.column_config.TextColumn(width=260),
                     "Hành động tiếp theo": st.column_config.TextColumn(width=260),
                 })

    st.divider()
    st.subheader("Công thức COGS A→F")
    st.caption("Mỗi khoản có 2 context: **Estimate** (nhập tay khi lập dự toán) và **COGS Actual** (nguồn dữ liệu thực tế khi Sync).")

    cogs_rows = QUICK_REF["💰 Công thức COGS A→F"]

    for code, name, formula_est, source_actual, desc in cogs_rows:
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
    ca, cb, cc = st.columns(3)
    ca.info("**Total COGS** = A + B + C + D + E + F")
    cb.success("**GP** = Doanh thu − COGS")
    cc.warning("**GP%** = GP / Doanh thu × 100")

    st.divider()
    st.subheader("Kết quả Go / No-Go")
    g1, g2, g3 = st.columns(3)
    g1.success("✅ **GO**\n\nGP% ≥ ngưỡng GO\n*(mặc định ≥ 25%)*")
    g2.warning("⚠️ **CONDITIONAL**\n\nGP% giữa 2 ngưỡng\n*(mặc định 18–25%)*")
    g3.error("❌ **NO-GO**\n\nGP% < ngưỡng CONDITIONAL\n*(mặc định < 18%)*")

    st.divider()
    st.subheader("Biểu tượng tỷ giá")
    rc1, rc2, rc3, rc4 = st.columns(4)
    rc1.success("✅ **Live API / DB**\nTỷ giá đáng tin cậy")
    rc2.warning("⚠️ **Fallback**\nNhập thủ công từ ngân hàng")
    rc3.info("💡 **Lệch > 1%**\nCân nhắc cập nhật")
    rc4.info("ℹ️ **VND**\nKhông cần quy đổi")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — SOP
# ─────────────────────────────────────────────────────────────────────────────
with tab_sop:
    sop_choice = st.radio(
        "Chọn nghiệp vụ:",
        list(SOP_STEPS.keys()),
        horizontal=True,
        label_visibility="collapsed",
    )

    st.markdown(f"### {sop_choice}")
    steps = SOP_STEPS[sop_choice]

    for step_num, step_desc, step_note in steps:
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

    # Special blocks per SOP
    if sop_choice == "📝 Tạo dự án mới":
        st.divider()
        st.info("**Sau khi tạo xong:** Vào module IL Estimates để tạo Estimate đầu tiên ngay. Không có Estimate = không có baseline để Variance Analysis sau này.")

    elif sop_choice == "🔄 Sync COGS Actual":
        st.divider()
        col_a, col_b = st.columns(2)
        col_a.warning("**D (tự động)** = Tổng Labor Logs APPROVED\n- Phase ≠ PRE_SALES: vào D-direct\n- Phase = PRE_SALES + allocation COGS: vào D-presales")
        col_b.warning("**E (tự động)** = Tổng Expenses APPROVED\n- Phase ≠ PRE_SALES và ≠ WARRANTY: vào E-travel\n- Pre-sales costs Layer 2 allocation COGS: vào E-presales")
        st.info("**⚠️ E-presales chỉ tính các category:** DEMO_TRANSPORT, TRAVEL_SPECIAL, POC_EXECUTION, WIFI_SURVEY, ENGINEERING_STUDY, CUSTOM_SAMPLE, OTHER.\n\nCác category **PROTOTYPE** và **CUSTOM_DEMO** (dù là SPECIAL/COGS) **không** được đưa vào E-presales khi Sync.")

    elif sop_choice == "✅ Đóng dự án & Benchmark":
        st.divider()
        st.success("**Thứ tự các bước QUAN TRỌNG:** Approve hết → Sync COGS → Điền Variance → **Finalize** → Close → Benchmark. Không thể đảo thứ tự sau bước Finalize.")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — Q&A
# ─────────────────────────────────────────────────────────────────────────────
with tab_qa:
    st.markdown("Tra cứu nhanh cách xử lý các tình huống thực tế. Dùng ô tìm kiếm hoặc lọc theo chủ đề.")

    col_search, col_tag = st.columns([3, 2])
    with col_search:
        search_text = st.text_input("🔍 Tìm kiếm", placeholder="VD: subcontractor, bảo hành, sai sót...",
                                    label_visibility="collapsed")
    with col_tag:
        tag_filter = st.multiselect("Lọc theo chủ đề", ALL_TAGS, placeholder="Tất cả chủ đề",
                                    label_visibility="collapsed")

    # Filter
    filtered = QA_DATA
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

    st.caption(f"Hiển thị {len(filtered)} / {len(QA_DATA)} tình huống")
    st.divider()

    if not filtered:
        st.info("Không tìm thấy tình huống phù hợp. Thử từ khóa khác.")
    else:
        for qa in filtered:
            # Tag pills
            tag_html = " ".join(
                f'<span style="background:#EEF4FB;color:#1F4E79;padding:2px 8px;'
                f'border-radius:10px;font-size:11px;margin-right:4px">{t}</span>'
                for t in qa["tags"]
            )
            with st.expander(f"**{qa['id']}** — {qa['question']}"):
                st.markdown(tag_html, unsafe_allow_html=True)
                st.markdown(" ")

                # Situation
                st.markdown(
                    f'<div style="background:#F8F9FA;border-left:3px solid #6c757d;'
                    f'padding:8px 14px;border-radius:4px;font-size:14px;color:#555;margin-bottom:12px">'
                    f'📌 <em>{qa["situation"]}</em></div>',
                    unsafe_allow_html=True,
                )

                # SOP steps
                st.markdown("**Cách thực hiện:**")
                for i, step in enumerate(qa["sop"], 1):
                    st.markdown(f"{i}. {step}")

                # Note
                if qa["note"]:
                    st.info(f"💡 {qa['note']}")

                # Warning
                if qa["warning"]:
                    st.warning(f"⚠️ {qa['warning']}")

    st.divider()
    st.caption("Không tìm thấy tình huống bạn cần? Liên hệ Admin hoặc PM để được hỗ trợ.")