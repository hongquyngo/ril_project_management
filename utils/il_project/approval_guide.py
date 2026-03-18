# utils/il_project/approval_guide.py
"""
Floating User Guide for Approval Config page (IL_98).

Renders a wide popover (st.popover) with structured help content
covering all 4 tabs: Authorities, Types, Notifications, History.

Usage in page:
    from utils.il_project.approval_guide import render_approval_guide
    render_approval_guide()   # call once, renders the floating button
"""

import streamlit as st


def render_approval_guide():
    """
    Render the floating ❓ User Guide popover.
    Call once at the top or bottom of the page.
    Uses st.popover for non-intrusive, on-demand help.
    """

    # ── Floating container: fixed bottom-right ───────────────────
    # Streamlit doesn't have native fixed positioning, so we use
    # custom CSS to float the popover trigger button.
    st.markdown("""
    <style>
    /* Float the guide button container to bottom-right */
    div[data-testid="stPopover"] {
        position: relative;
    }
    div.guide-float-anchor {
        position: fixed;
        bottom: 24px;
        right: 24px;
        z-index: 999;
    }

    /* Make popover panel wide */
    div[data-testid="stPopoverBody"] {
        width: 720px !important;
        max-width: 90vw !important;
        max-height: 80vh !important;
        overflow-y: auto !important;
    }
    </style>
    """, unsafe_allow_html=True)

    with st.popover("❓ User Guide", use_container_width=False):
        _render_guide_content()


def _render_guide_content():
    """Render the full guide content inside the popover."""

    st.markdown("## 🔐 Approval Configuration — User Guide")
    st.caption("Tài liệu hướng dẫn sử dụng trang quản lý quyền phê duyệt. Chọn mục bên dưới.")

    # ── Quick Navigation ─────────────────────────────────────────
    guide_section = st.radio(
        "Section",
        [
            "🏠 Overview",
            "👥 Approval Authorities",
            "📋 Approval Types",
            "📧 Notifications",
            "📜 Approval History",
            "💡 FAQ & Tips",
        ],
        horizontal=True,
        key="_guide_nav",
        label_visibility="collapsed",
    )

    st.divider()

    if guide_section == "🏠 Overview":
        _section_overview()
    elif guide_section == "👥 Approval Authorities":
        _section_authorities()
    elif guide_section == "📋 Approval Types":
        _section_types()
    elif guide_section == "📧 Notifications":
        _section_notifications()
    elif guide_section == "📜 Approval History":
        _section_history()
    elif guide_section == "💡 FAQ & Tips":
        _section_faq()


# ══════════════════════════════════════════════════════════════════════
# GUIDE SECTIONS
# ══════════════════════════════════════════════════════════════════════

def _section_overview():
    st.markdown("""
### 🏠 Tổng quan

Trang **Approval Configuration** quản lý toàn bộ hệ thống phê duyệt,
bao gồm:

| Tab | Chức năng |
|-----|-----------|
| **👥 Authorities** | Ai được phê duyệt gì, level nào, giới hạn bao nhiêu |
| **📋 Types** | Các loại phê duyệt (Purchase Request, v.v.) |
| **📧 Notifications** | Gửi email thông báo tổng hợp cho Finance/Approver |
| **📜 History** | Lịch sử phê duyệt (read-only) |

---

#### 🔗 Luồng phê duyệt Purchase Request (ví dụ)

```
PM tạo PR → Submit → L1 Approver (≤500M) → L2 Approver (No limit) → Approved → Tạo PO
```

- **Level 1**: GM phê duyệt PR ≤ 500M ₫
- **Level 2**: CEO phê duyệt mọi giá trị (unlimited)
- Nếu PR = 300M ₫ → chỉ cần L1
- Nếu PR = 800M ₫ → cần cả L1 và L2

---

#### 📧 Thông báo tự động

Mỗi khi thêm/sửa/xóa authority, hệ thống **tự động gửi email** cho:
- Approver bị ảnh hưởng (TO)
- Admin đang thao tác + tất cả approver cùng type (CC)
- Finance team nếu type liên quan payment (CC)

Khi gửi Summary thủ công, sender + tất cả approver trong scope được
**bắt buộc CC** — không thể bỏ.

---

#### 🔑 Quyền truy cập
Chỉ **Admin** mới được truy cập trang này.
""")


def _section_authorities():
    st.markdown("""
### 👥 Approval Authorities

Đây là tab chính — quản lý **ai** được phê duyệt **cái gì**, ở **level nào**,
với **giới hạn bao nhiêu**.

---

#### ➕ Thêm mới Authority

1. Click **➕ New Authority**
2. Chọn **Approval Type** (ví dụ: IL_PURCHASE_REQUEST)
3. Chọn **Approver** (từ danh sách employee)
4. Đặt **Level** (1 = approve trước, 2 = approve sau)
5. Đặt **Approval Limit** (giới hạn VND) hoặc bỏ tick = unlimited
6. Chọn **Company Scope** (thường để "All companies")
7. Đặt **Effective From / To** (thời hạn hiệu lực)
8. Click **💾 Create**

> **📧 Tự động thông báo**: Sau khi tạo thành công, hệ thống **tự động gửi email**
> cho approver mới, tất cả approver cùng type, admin (sender), và Finance team
> (nếu liên quan). Không cần thao tác thêm.

---

#### ✏️ Sửa Authority

1. Click vào dòng trong bảng
2. Click **✏️ Edit**
3. Sửa thông tin → **💾 Save**

> **📧 Tự động thông báo**: Email sẽ tự gửi cho người bị thay đổi
> và tất cả approver liên quan. Email bao gồm bảng so sánh
> trước/sau (What Changed).

---

#### 🗑 Xóa Authority

Trong dialog Edit → click **🗑 Delete** → authority sẽ bị soft-delete.
Email thông báo xóa cũng được gửi tự động.

---

#### 📊 Bộ lọc

| Filter | Mô tả |
|--------|-------|
| **Type** | Lọc theo loại phê duyệt |
| **Status** | Active Only / Inactive Only / All |

---

#### 🔢 Level & Approval Limit — Cách hoạt động

| Trường hợp | Level cần | Giải thích |
|-------------|-----------|------------|
| PR = 200M, L1 limit = 500M | L1 only | 200M < 500M → L1 đủ |
| PR = 700M, L1 limit = 500M, L2 = unlimited | L1 + L2 | 700M > 500M → cần L2 |
| PR = 50M, L1 limit = 500M | L1 only | Nhỏ hơn ngưỡng |

---

#### 📧 Ai nhận email khi CRUD?

| Người nhận | Vai trò | Slot |
|------------|---------|------|
| Approver bị ảnh hưởng | Người trực tiếp liên quan | **TO** |
| Admin đang thao tác | Lưu bản ghi (audit trail) | CC |
| Tất cả approver cùng type | Cập nhật workflow chung | CC |
| Finance preset | Nếu type liên quan payment | CC |

> Email gửi **không chặn** thao tác: nếu gửi email thất bại,
> CRUD vẫn thành công. Banner thông báo kết quả sẽ hiện ở đầu tab.
""")


def _section_types():
    st.markdown("""
### 📋 Approval Types

Quản lý các **loại phê duyệt** trong hệ thống.

---

#### Loại hiện có

| Code | Mô tả |
|------|-------|
| `IL_PURCHASE_REQUEST` | Phê duyệt Purchase Request từ IL Project |
| `APPROVAL_CONFIG_NOTIFY` | Log gửi email thông báo (tự động tạo) |

---

#### ➕ Thêm mới Type

1. Click **➕ New Type**
2. Nhập **Code** (UPPER_SNAKE_CASE, ví dụ: `VENDOR_APPROVAL`)
3. Nhập **Name** (tên hiển thị, ví dụ: "Vendor Approval")
4. Nhập **Description** (mô tả)
5. Tick **Active**
6. Click **💾 Create**

> **Lưu ý**: Code phải unique và không thể sửa sau khi tạo.

---

#### ⚠️ Không thể xóa Type nếu còn Authority

Nếu có authority nào đang reference type này, bạn cần xóa/deactivate
authority trước, hoặc set type thành **Inactive**.
""")


def _section_notifications():
    st.markdown("""
### 📧 Notifications

Gửi email thông báo approval authority cho các bên liên quan,
**đặc biệt Finance team** cần biết ai có quyền approve để verify thanh toán.

---

#### Hai loại thông báo

| Loại | Khi nào | Cách gửi |
|------|---------|----------|
| **Summary** | Admin muốn gửi bảng tổng hợp toàn bộ authorities | Thủ công — tab Notifications |
| **Change Alert** | Sau mỗi Create/Edit/Delete authority | **Tự động** — không cần thao tác |

---

#### 🔒 Required CC — Người nhận bắt buộc

Khi gửi Summary email, hệ thống **tự động thêm CC bắt buộc**:

| Người | Lý do |
|-------|-------|
| **Admin đang gửi** | Audit trail — lưu bản ghi đã gửi |
| **Tất cả Active Approvers** trong scope | Là người liên quan trực tiếp |

Required CC **không thể xóa** — hiển thị trong ô "🔒 Required CC" (khóa).
Bạn chỉ có thể **thêm** người nhận, không bỏ được người bắt buộc.

---

#### 📬 Chọn thêm người nhận

**Cách 1 — Quick Presets** (nhanh nhất):
- Click nút preset sẵn: **📊 Finance Team**, **👥 All Approvers**, **📋 PMs**
- Preset AUTO sẽ tự resolve email tại thời điểm gửi

**Cách 2 — Chọn từ employee list**:
- **TO**: Multiselect chọn nhân viên nhận chính
- **Additional CC**: Thêm CC ngoài danh sách bắt buộc

**Cách 3 — Nhập email thủ công**:
- Dùng cho group email: `finance-group@prostech.vn`
- Hoặc email ngoài hệ thống

> **Kết hợp cả 3 cách**: Preset + Employee select + Manual email
> được gộp lại, tự loại trùng.

---

#### ⚙️ Options

| Option | Mô tả |
|--------|-------|
| **Include effective period** | Hiển thị cột Effective From / To |
| **Include recent changes** | Kèm bảng thay đổi 30 ngày gần nhất |
| **Note to recipients** | Ghi chú từ admin — hiển thị dưới dạng "Remarks" |

---

#### 👁 Preview trước khi gửi

Click **👁 Preview Email** để xem nội dung chính xác mà người nhận sẽ thấy.

Email bao gồm:
- Lời chào trang trọng: *"To whom it may concern..."*
- Bảng authority theo từng type (Level, Approver, Position, Approval Limit)
- Approval Workflow summary (L1 → L2 → L3)
- Finance Department notice (nếu type liên quan payment)
- Closing: *"Should you have any questions..."*

Preview hiện đúng recipient bar:
- **TO** (xanh) — người nhận chính
- **CC** (xanh đậm + label "required") — CC bắt buộc
- **CC** (xám) — CC thêm

---

#### 🔧 Quản lý Presets

Expand **"Manage Notification Presets"** để:

| Hành động | Mô tả |
|-----------|-------|
| **➕ New Preset** | Tạo nhóm người nhận mới |
| **✏️ Edit** | Sửa preset (thêm/bớt email, đổi type) |
| **🗑 Delete** | Xóa preset |

**Loại preset:**

| Type | Hoạt động |
|------|-----------|
| `MANUAL` | Bạn chọn employee + nhập email cố định |
| `AUTO_APPROVERS` | Tự query tất cả approver active tại thời điểm gửi |
| `AUTO_PMS` | Tự query tất cả Project Manager tại thời điểm gửi |

---

#### 📜 Notification Log

Expand **"Notification Send Log"** để xem lịch sử gửi email:
ai gửi, gửi cho ai, khi nào, loại gì.
""")


def _section_history():
    st.markdown("""
### 📜 Approval History

Tab read-only — hiển thị **lịch sử phê duyệt** từ tất cả modules.

---

#### Status icons

| Icon | Nghĩa |
|------|-------|
| ✅ | APPROVED — đã phê duyệt |
| ❌ | REJECTED — từ chối |
| 📤 | SUBMITTED — đã gửi đi chờ approve |
| 🔄 | REVISION_REQUESTED — yêu cầu sửa lại |
| 🔵 | PENDING — đang chờ |
| 📧 | SENT — notification đã gửi (từ tab Notifications) |

---

#### Dữ liệu hiển thị

| Cột | Mô tả |
|-----|-------|
| **Type** | Loại phê duyệt (IL_PURCHASE_REQUEST, ...) |
| **Reference** | Mã tham chiếu (PR number, PO number, ...) |
| **Approver** | Người phê duyệt |
| **Decision** | Quyết định (APPROVED, REJECTED, ...) |
| **Level** | Level phê duyệt |
| **Date** | Thời gian |
| **Comments** | Ghi chú |

> **Lưu ý**: Tab này chỉ đọc. Không có chức năng sửa/xóa.
""")


def _section_faq():
    st.markdown("""
### 💡 FAQ & Tips

---

**Q: Làm sao để Finance team biết ai được approve PR?**

Vào tab **📧 Notifications** → chọn preset **Finance Team** (hoặc nhập email)
→ click **📧 Send Notification**. Email sẽ chứa bảng tổng hợp tất cả
authorities hiện tại kèm Approval Workflow.

> Hệ thống sẽ **tự thêm CC** cho tất cả approver và admin (sender).
> Bạn không cần thêm họ thủ công.

---

**Q: Tôi vừa thay đổi approval limit của approver, cần làm gì?**

Không cần làm gì thêm. Sau khi Save, hệ thống **tự động gửi email**
cho approver bị thay đổi, tất cả approver cùng type, admin (bạn),
và Finance team (nếu type liên quan payment).

Banner kết quả sẽ hiện ở đầu tab Authorities:
- ✅ Xanh = gửi thành công, kèm danh sách TO/CC
- ⚠️ Vàng = gửi thất bại, nhưng thay đổi vẫn được lưu

---

**Q: Muốn thêm level 3 (Board approval) cho PR > 1 tỷ, làm sao?**

1. Tab **👥 Authorities** → **➕ New Authority**
2. Type: `IL_PURCHASE_REQUEST`
3. Approver: chọn Board member
4. Level: **3**
5. Approval Limit: bỏ tick (unlimited) hoặc set giá trị cụ thể
6. **💾 Create** → Email tự gửi cho tất cả approver + Finance

---

**Q: Approver đi nghỉ phép, muốn tạm dừng?**

Cách 1: **Edit** authority → bỏ tick **Active** → Save
Cách 2: **Edit** authority → set **Effective To** = ngày hết phép

> **Lưu ý**: Nếu deactivate approver duy nhất ở 1 level,
> PR sẽ không thể submit (hệ thống báo "No approval authorities configured").
> Email thông báo sẽ tự gửi cho các bên liên quan.

---

**Q: Có thể có 2 approver cùng level không?**

Không — mỗi employee chỉ có 1 authority per type + level.
Nếu cần 2 người có thể approve ở cùng level, tạo 2 authority records
với 2 employee khác nhau ở cùng level.

---

**Q: Tôi có thể bỏ người nào đó khỏi CC khi gửi Summary không?**

Không bỏ được **Required CC** (sender + all active approvers).
Bạn chỉ có thể **thêm** người nhận TO/CC bổ sung.
Điều này đảm bảo tất cả người liên quan luôn nhận được thông báo.

---

**Q: Preset "All Approvers" lấy email từ đâu?**

Từ `approval_authorities` table — query tất cả employee có `is_active = 1`
tại thời điểm gửi. Nếu bạn vừa thêm approver mới, preset sẽ tự include
người đó mà không cần edit preset.

---

**Q: Email gửi đi hiển thị gì?**

- Lời chào: *"To whom it may concern..."*
- Bảng authority theo type (Level, Approver, Position, Approval Limit, Status)
- Approval Workflow: `L1: Tin (≤500M ₫) → L2: Quy (No limit)`
- Finance Department notice (chỉ hiện nếu type liên quan purchase/payment)
- Admin remarks (nếu có)
- Closing: *"Should you have any questions..."*
- Footer: *Rozitek Intralogistic Solution*

---

**Q: Email thông báo thay đổi (Change Alert) khác gì Summary?**

| | Summary | Change Alert |
|-|---------|-------------|
| **Khi nào** | Admin gửi thủ công | Tự động sau CRUD |
| **Nội dung** | Toàn bộ authorities hiện tại | Chi tiết 1 thay đổi cụ thể |
| **Bảng so sánh** | Không | Có (Before → After) |
| **Subject** | `[Notice] Approval Authority — ...` | `[Notice] Approval Authority Updated — ...` |

---

#### ⌨️ Thao tác nhanh

| Action | Cách nhanh |
|--------|-----------|
| Tìm authority | Dùng **Filter by Type** + **Status** |
| Edit nhanh | Click dòng → **✏️ Edit** |
| Gửi summary | Tab Notifications → Preset → **📧 Send** |
| Xem ai nhận email | Kiểm tra banner sau CRUD hoặc Preview trước khi Send |
""")