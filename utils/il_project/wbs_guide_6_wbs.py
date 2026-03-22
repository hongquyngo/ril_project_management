# utils/il_project/wbs_guide.py
"""
User Guide content for WBS page (Page 6).
Bilingual VI/EN. Role-aware sections, FAQ, workflows, context tips.
"""

from typing import Dict, List
from .wbs_guide_common import _t

# ══════════════════════════════════════════════════════════════════════════════
# GUIDE SECTIONS
# ══════════════════════════════════════════════════════════════════════════════

_SECTIONS: Dict[str, List[Dict]] = {

    # ── PM GUIDE ─────────────────────────────────────────────────────────────
    'pm': [
        {
            'icon': '📊',
            'tags': ['dashboard', 'kpi', 'overview', 'daily', 'tổng quan', 'chỉ số'],
            'title_vi': 'Dashboard — Trung tâm điều hành',
            'title_en': 'Dashboard — Your Command Center',
            'content_vi': """
**Dòng KPI** (luôn hiện ở đầu trang):
| Chỉ số | Ý nghĩa | Hành động khi đỏ |
|--------|---------|-------------------|
| **Overall %** | % hoàn thành dự án (có trọng số) | Kiểm tra weight % các phase |
| **Tasks Done** | Hoàn thành / Tổng | Tìm phase nào đang nghẽn |
| **Overdue** | Quá hạn, chưa hoàn thành | Follow-up hoặc chuyển người |
| **Blocked** | Trạng thái = BLOCKED | Đọc lý do block, gỡ block hoặc escalate |
| **Due This Week** | Đến hạn trong 7 ngày | Đảm bảo assignee đang on track |

**Panel "Action Required":**
- Sắp xếp theo mức độ: 🔴 Critical → 🟠 High → 🔵 Medium
- Mỗi item có nút inline: View, Quick Update, Edit
- Task bị Blocked luôn hiện đầu tiên — cần xử lý ngay
- Task quá hạn tiếp theo — follow-up với assignee
- Task chưa assign — cần gán người

**Phase Progress:**
- Mỗi phase hiện thanh tiến độ + số task quá hạn
- Click vào tab Phases để quản lý chi tiết
""",
            'content_en': """
**KPI Row** (always visible at page top):
| Metric | Meaning | Action when red |
|--------|---------|-----------------|
| **Overall %** | Weighted project completion | Review phase weights if inaccurate |
| **Tasks Done** | Completed / Total active | Check if bottleneck in specific phase |
| **Overdue** | Past due date, not completed | Follow up or reassign |
| **Blocked** | Status = BLOCKED | Review blocker reason, unblock or escalate |
| **Due This Week** | Due within 7 days, not done | Ensure assignees are on track |

**Action Required Panel:**
- Sorted by severity: 🔴 Critical → 🟠 High → 🔵 Medium
- Each item has inline buttons: View, Quick Update, Edit
- Blocked tasks always appear first — they need immediate attention
- Overdue tasks next — follow up with assignees
- Unassigned tasks — assign to team members

**Phase Progress Strip:**
- Shows each phase with completion bar + overdue count
- Click through to Phases tab for full CRUD
""",
        },
        {
            'icon': '🔷',
            'tags': ['phase', 'create', 'template', 'weight', 'setup', 'giai đoạn', 'tạo'],
            'title_vi': 'Quản lý Phase (Giai đoạn)',
            'title_en': 'Phase Management',
            'content_vi': """
**Thiết lập phase:**
1. **Load Template** → tạo 7 phase chuẩn cho dự án IL trong 1 click
2. Hoặc **Add Phase** thủ công với code, tên, ngày tùy chỉnh

**Các trường quan trọng:**
- **Weight %** — quyết định phase này đóng góp bao nhiêu vào tổng % dự án
  - Nếu tổng weight = 100% → tính trung bình có trọng số
  - Nếu không set weight → tính trung bình đơn giản
- **Completion %** — tự động tính từ task con (theo est. hours)
  - Có thể override thủ công trong Edit Phase

**Chuỗi tính % hoàn thành:**
```
Task % (nhập thủ công hoặc qua Quick Update)
  ↓ trung bình có trọng số theo estimated_hours
Phase %
  ↓ trung bình có trọng số theo weight_percent
Project overall_completion_percent
```

**Khuyến nghị:** Set weight_percent phản ánh đúng phân bổ công việc.
Ví dụ: Implementation 35%, Commissioning 20%, Design 15%...
""",
            'content_en': """
**Setting up phases:**
1. **Load Template** → creates 7 standard IL project phases in one click
2. Or **Add Phase** manually with custom code, name, dates

**Key fields:**
- **Weight %** — determines how this phase contributes to overall project %
  - If all phases have weights summing to 100%, completion is weighted average
  - If no weights set, simple average of all phases is used
- **Completion %** — auto-calculated from child tasks (weighted by est. hours)

**Completion sync chain:**
```
Task % → Phase % (weighted avg by est. hours) → Project % (weighted by phase weight)
```

**Best practice:** Set weight_percent to reflect real effort distribution.
""",
        },
        {
            'icon': '📋',
            'tags': ['task', 'create', 'assign', 'reassign', 'priority', 'wbs', 'tạo', 'gán', 'ưu tiên'],
            'title_vi': 'Quản lý Task — Tạo & Gán việc',
            'title_en': 'Task Management — Create & Assign',
            'content_vi': """
**Tạo task:**
1. Vào tab **All Tasks** → ➕ Add Task
2. Bắt buộc: Task Name, Phase
3. WBS Code tự tạo dạng `[phase_seq].[task_seq]` (có thể sửa)
4. Gán cho member → email thông báo tự động

**Gán / Chuyển người:**
- Set Assignee trong dialog Create hoặc Edit
- Nếu đổi từ người này sang người khác → email reassignment gửi tự động
- Người được gán nhận email có Action Required

**Hệ thống ưu tiên:**
| Ưu tiên | Khi nào dùng |
|---------|-------------|
| 🔴 **CRITICAL** | Block milestone, cần xử lý ngay |
| 🟠 **HIGH** | Quan trọng, ảnh hưởng tiến độ |
| 🔵 **NORMAL** | Công việc tiêu chuẩn |
| 🟢 **LOW** | Có thể hoãn |

**Bộ lọc nhanh** (phía trên bảng task):
- ⏰ Overdue — quá hạn
- 🔴 Blocked — trạng thái BLOCKED
- 🙋 Mine — gán cho bạn
- 🔴 Crit/High — ưu tiên CRITICAL hoặc HIGH
- ❓ Unassigned — chưa gán người (chỉ PM thấy)
""",
            'content_en': """
**Creating tasks:**
1. Go to **All Tasks** tab → ➕ Add Task
2. Required: Task Name, Phase
3. WBS Code auto-generates as `[phase_seq].[task_seq]` (editable)
4. Assign to team member → auto-email notification sent

**Priority system:** 🔴 CRITICAL > 🟠 HIGH > 🔵 NORMAL > 🟢 LOW

**Quick filters** above task table: Overdue, Blocked, Mine, Crit/High, Unassigned (PM only)
""",
        },
        {
            'icon': '🔍',
            'tags': ['overdue', 'blocked', 'monitor', 'follow-up', 'daily', 'theo dõi', 'quá hạn'],
            'title_vi': 'Theo dõi & Follow-up hàng ngày',
            'title_en': 'Monitoring & Follow-up',
            'content_vi': """
**Thói quen hàng ngày (5 phút):**
1. Mở Dashboard → xem Action Required
2. Xử lý 🔴 Blocked trước: đọc lý do → comment hoặc gỡ block
3. Xử lý ⏰ Overdue: nhắc assignee hoặc reassign
4. Kiểm tra Due This Week: đảm bảo tất cả on track

**Xử lý task BLOCKED:**
- Engineer set BLOCKED → bạn nhận email ngay
- Lý do block hiện trong Action Required
- Lựa chọn: Comment hướng dẫn → giải quyết → set lại IN_PROGRESS
- Hoặc reassign cho người khác có thể gỡ block
- Hoặc escalate → comment ghi nhận escalation

**Xử lý task quá hạn:**
- Cột Due hiện "🔴 5d late" v.v.
- Quick Update → điều chỉnh hoặc kiểm tra tiến độ thực
- Nếu quá hạn liên tục → xem lại ước tính, thêm resource, hoặc thu hẹp scope

**Theo dõi completion:**
- Phase progress bar đứng yên = có vấn đề tiềm ẩn
- So sánh estimated vs actual hours → phát hiện scope creep
""",
            'content_en': """
**Daily routine (5 min):**
1. Open Dashboard → scan Action Required
2. Handle 🔴 Blocked first → unblock or escalate
3. Handle ⏰ Overdue → follow up or reassign
4. Check Due This Week → ensure on track

**Handling BLOCKED:** Review reason → Comment/unblock → or reassign/escalate
**Handling overdue:** Check real progress → adjust dates or add resources
""",
        },
        {
            'icon': '📧',
            'tags': ['email', 'notification', 'cc', 'thông báo'],
            'title_vi': 'Email thông báo tự động',
            'title_en': 'Email Notifications',
            'content_vi': """
**Email tự động gửi khi:**

| Sự kiện | Gửi đến (TO) | CC |
|---------|-------------|----|
| Task được gán/chuyển | Assignee | PM + người thực hiện |
| Task bị BLOCKED | PM | Assignee + người thực hiện |
| Task COMPLETED | PM | Assignee + người thực hiện |
| Issue mới | Người được gán | PM + người báo cáo |
| Change Order đổi status | Người yêu cầu | PM + người duyệt |

**CC Selector:**
- Trong dialog Create/Edit, mở "📧 Notification CC"
- Thêm member hoặc email bên ngoài
- Họ nhận thông báo cho hành động cụ thể đó

**Deep links:**
- Mỗi email có nút "View in App" → mở đúng trang WBS

**Lưu ý:**
- Email chỉ gửi khi ENABLE_EMAIL_NOTIFICATIONS = true
- Người thực hiện (performer) luôn được CC tự động
""",
            'content_en': """
**Auto-sent emails:**

| Trigger | TO | CC |
|---------|----|----|
| Task assigned/reassigned | Assignee | PM + performer |
| Task BLOCKED | PM | Assignee + performer |
| Task COMPLETED | PM | Assignee + performer |
| Issue created | Assigned person | PM + reporter |
| CO status changed | Requester | PM + approver |

**CC Selector:** Expand "📧 Notification CC" in dialogs to add extra recipients.
**Deep links:** Every email has "View in App" button → opens exact page.
""",
        },
    ],

    # ── ENGINEER GUIDE ───────────────────────────────────────────────────────
    'engineer': [
        {
            'icon': '🙋',
            'tags': ['my-tasks', 'home', 'priority', 'focus', 'daily', 'công việc', 'ưu tiên'],
            'title_vi': 'My Tasks — Trang chính của bạn',
            'title_en': 'My Tasks — Your Home Base',
            'content_vi': """
**My Tasks** là tab mặc định — hiển thị tất cả task đang hoạt động gán cho bạn
trên mọi dự án, sắp xếp theo độ ưu tiên.

**Đọc bảng task:**

| Cột | Ý nghĩa |
|-----|---------|
| **!** | Ưu tiên: 🔴 Critical, 🟠 High, 🔵 Normal, 🟢 Low |
| **Project** | Thuộc dự án nào |
| **Status** | Trạng thái hiện tại |
| **%** | Phần trăm hoàn thành + màu chỉ thị |
| **Due** | 🔴 = quá hạn, ⚠️ = hôm nay, 🟡 = ≤3 ngày, 📅 = ≤7 ngày |

**Thứ tự ưu tiên mỗi ngày:**
1. 🔴 Task bị Blocked — cập nhật PM hoặc giải quyết
2. ⏰ Task quá hạn — cập nhật tiến độ hoặc báo blocker
3. 🆕 Task NOT_STARTED — chuyển sang IN_PROGRESS
4. 📋 Task đến hạn tuần này — đảm bảo on track

**Chế độ xem:**
- **📊 Grouped** — card nhóm theo ưu tiên, có nút action trực tiếp
- **📋 Table** — bảng phẳng, chọn row rồi click action
""",
            'content_en': """
**My Tasks** is your default tab — shows all active tasks assigned to you across all projects, sorted by priority.

| Column | Meaning |
|--------|---------|
| **!** | Priority: 🔴 Critical, 🟠 High, 🔵 Normal, 🟢 Low |
| **Due** | 🔴 = overdue, ⚠️ = today, 🟡 = ≤3d, 📅 = ≤7d |

**Focus order:** Blocked → Overdue → Not Started → Due this week

**View modes:** 📊 Grouped (cards by priority) or 📋 Table (flat dataframe)
""",
        },
        {
            'icon': '⚡',
            'tags': ['quick-update', 'status', 'progress', 'hours', 'blocked', 'cập nhật', 'tiến độ', 'giờ'],
            'title_vi': 'Quick Update — Thao tác chính của bạn',
            'title_en': 'Quick Update — Your Main Action',
            'content_vi': """
**Cách Quick Update:**
1. Chọn task (click vào row hoặc nút ⚡ trên card)
2. Cập nhật 3 trường:

| Trường | Nhập gì |
|--------|---------|
| **Status** | Trạng thái hiện tại (xem flow bên dưới) |
| **Completion %** | Ước tính thành thật bao nhiêu % đã xong |
| **Actual Hours** | Tổng số giờ đã bỏ ra tính đến hiện tại |

**Luồng trạng thái:**
```
⚪ NOT_STARTED → 🔵 IN_PROGRESS → ✅ COMPLETED
                       │
                       ├→ 🔴 BLOCKED (bắt buộc nhập lý do!)
                       │     └→ 🔵 IN_PROGRESS (khi đã gỡ block)
                       │
                       └→ ⏸️ ON_HOLD
                             └→ 🔵 IN_PROGRESS (khi resume)
```

**Khi BLOCKED:**
- BẮT BUỘC nhập lý do block — lý do được gửi email cho PM ngay
- Viết cụ thể: "Chờ cable tray giao hàng, ETA 5/4"
- PM nhận thông báo ngay và thấy trong Dashboard

**Hướng dẫn Completion %:**
| Tình huống | % |
|-----------|---|
| Vừa bắt đầu đọc yêu cầu | 5–10% |
| Xong thiết kế/kế hoạch, bắt đầu triển khai | 20–30% |
| Triển khai được nửa | 50% |
| Xong triển khai, cần test/review | 70–80% |
| Xong test, chờ nghiệm thu | 90–95% |
| Mọi thứ đã giao và nghiệm thu | 100% |
""",
            'content_en': """
**How to Quick Update:**
1. Select task → ⚡ Quick Update
2. Update: **Status**, **Completion %**, **Actual Hours**

**Status flow:** NOT_STARTED → IN_PROGRESS → COMPLETED / BLOCKED / ON_HOLD

**When BLOCKED:** You MUST enter a reason → PM gets notified immediately.

**Completion % guidelines:** 5-10% started → 50% halfway → 80% testing → 100% delivered
""",
        },
        {
            'icon': '✅',
            'tags': ['checklist', 'comments', 'blocker', 'communication', 'giao tiếp', 'bình luận', 'file'],
            'title_vi': 'Checklist, Comments & Files',
            'title_en': 'Checklist, Comments & Files',
            'content_vi': """
**Checklist** (trong Task Details → tab ✅ Checklist):
- Toggle (bật/tắt) từng item khi hoàn thành công việc con
- PM theo dõi tiến độ checklist (hiện dạng "3/5" trong bảng task)
- Phù hợp cho task có nhiều deliverable hoặc bước

**Comments** (trong Task Details → tab 💬 Comments):
- Dùng để: cập nhật, hỏi, trao đổi
- **Type = BLOCKER**: PM được alert — dùng khi bạn bị kẹt
- **Type = COMMENT**: giao tiếp thông thường

**Tự động log:**
- Thay đổi status được tự động ghi (VD: "IN_PROGRESS → BLOCKED")
- Cập nhật % được ghi (VD: "Progress updated to 75%")
- Tạo audit trail — bạn không cần log thủ công

**Files** (trong Task Details → tab 📎 Files):
- Đính kèm deliverable, ảnh, tài liệu
- Hỗ trợ: PDF, PNG, JPG, XLSX, DOCX
""",
            'content_en': """
**Checklist:** Toggle items as you complete sub-tasks. PM monitors progress.
**Comments:** Use BLOCKER type to alert PM. Status changes are auto-logged.
**Files:** Attach deliverables (PDF, PNG, JPG, XLSX, DOCX).
""",
        },
        {
            'icon': '💡',
            'tags': ['tips', 'best-practices', 'efficiency', 'mẹo', 'hiệu quả'],
            'title_vi': 'Mẹo làm việc hiệu quả',
            'title_en': 'Tips for Efficiency',
            'content_vi': """
**Mỗi ngày (2 phút):**
1. Mở My Tasks → kiểm tra 🔴 và ⏰
2. Quick Update các task đã làm trong ngày
3. Flag BLOCKED ngay lập tức — đừng chờ

**Mỗi tuần (5 phút):**
1. Xem lại tất cả task — cần thay đổi status nào?
2. Cập nhật completion % cho đúng thực tế
3. Log actual hours cho tuần

**Nên làm:**
- Set **IN_PROGRESS** ngay khi bắt đầu → PM thấy bạn đang active
- Cập nhật % từng bước 5–10% → Dashboard chính xác
- Dùng comment type **BLOCKER** → nổi bật trong timeline
- Đính kèm ảnh/tài liệu vào task → single source of truth

**KHÔNG nên:**
- Để task NOT_STARTED nhiều ngày sau khi đã bắt đầu làm
- Set 50% rồi để nguyên nhiều tuần
- Tự giải quyết blocker quá lâu — flag sớm để PM hỗ trợ
""",
            'content_en': """
**Daily (2 min):** Check My Tasks → Quick Update → Flag BLOCKED immediately
**Weekly (5 min):** Review all tasks → Update % → Log hours

**Do:** Set IN_PROGRESS when you start · Update % regularly · Flag BLOCKED early
**Don't:** Leave NOT_STARTED for days · Set 50% and forget · Solve blockers alone
""",
        },
    ],

    # ── VIEWER GUIDE ─────────────────────────────────────────────────────────
    'viewer': [
        {
            'icon': '👁️',
            'tags': ['access', 'read-only', 'overview', 'quyền', 'xem'],
            'title_vi': 'Bạn có thể xem & làm gì',
            'title_en': 'What You Can See & Do',
            'content_vi': """
**Quyền của bạn là chỉ xem (read-only).** Cụ thể:
- ✅ Xem Dashboard với KPI và tổng quan dự án
- ✅ Duyệt tất cả task, trạng thái và tiến độ
- ✅ Xem chi tiết task: checklist, comments
- ✅ Đăng comment trên task (để giao tiếp với team)
- ✅ Xem My Tasks nếu có task được gán cho bạn

**Bạn KHÔNG thể:**
- ❌ Tạo, sửa, xóa phase hoặc task
- ❌ Thay đổi trạng thái, ưu tiên, assignee
- ❌ Toggle checklist items
- ❌ Quản lý team

**Cần thêm quyền?** Liên hệ PM để được thêm vào team với role phù hợp.
""",
            'content_en': """
**Read-only access.** You can: view Dashboard, browse tasks, post comments.
Cannot: create/edit/delete tasks or phases, change status, manage team.
Contact PM for more access.
""",
        },
    ],

    # ── GENERAL (ALL ROLES) ──────────────────────────────────────────────────
    'general': [
        {
            'icon': '🏗️',
            'tags': ['wbs', 'code', 'structure', 'hierarchy', 'cấu trúc', 'mã'],
            'title_vi': 'Cấu trúc WBS',
            'title_en': 'WBS Structure',
            'content_vi': """
**WBS = Work Breakdown Structure** — tổ chức công việc theo cấp bậc.

**Phân cấp:** Dự án → Phase (Giai đoạn) → Task (Công việc) → Subtask

**Định dạng WBS Code:** `[sequence_phase].[sequence_task]`
- Phase 2, Task 3 → **2.3**
- Phase 3, Task 1, Subtask 2 → **3.1.2**

**Các phase chuẩn cho dự án IL (template):**

| # | Phase | Trọng số | Mô tả |
|---|-------|----------|-------|
| 1 | Pre-Sales / Site Survey | 5% | Khảo sát ban đầu |
| 2 | Design & Engineering | 15% | Thiết kế kỹ thuật |
| 3 | Procurement | 10% | Đặt mua vật tư |
| 4 | Implementation | 35% | Lắp đặt & cấu hình |
| 5 | Commissioning & FAT | 20% | Kiểm tra & nghiệm thu |
| 6 | Training & Handover | 10% | Đào tạo & bàn giao |
| 7 | Warranty Support | 5% | Hỗ trợ bảo hành |
""",
            'content_en': """
**WBS = Work Breakdown Structure** — hierarchical task organization.
**Hierarchy:** Project → Phases → Tasks → Subtasks
**WBS Code:** `[phase_seq].[task_seq]` → e.g. "2.3"

Standard IL phases: Pre-Sales (5%) → Design (15%) → Procurement (10%) → Implementation (35%) → Commissioning (20%) → Training (10%) → Warranty (5%)
""",
        },
        {
            'icon': '🔄',
            'tags': ['status', 'flow', 'icon', 'lifecycle', 'trạng thái', 'biểu tượng'],
            'title_vi': 'Trạng thái & Biểu tượng',
            'title_en': 'Status Flow & Icons',
            'content_vi': """
**Luồng trạng thái Task:**
```
⚪ NOT_STARTED → 🔵 IN_PROGRESS → ✅ COMPLETED
                       ├→ 🔴 BLOCKED → 🔵 IN_PROGRESS
                       ├→ ⏸️ ON_HOLD → 🔵 IN_PROGRESS
                       └→ ❌ CANCELLED
```

**Biểu tượng ngày hết hạn:**
| Biểu tượng | Ý nghĩa |
|------------|---------|
| 🔴 **5d late** | Quá hạn N ngày |
| ⚠️ **Today** | Hết hạn hôm nay |
| 🟡 **2d left** | Còn ≤3 ngày |
| 📅 **5d** | Còn ≤7 ngày |

**Biểu tượng ưu tiên:**
🔴 CRITICAL > 🟠 HIGH > 🔵 NORMAL > 🟢 LOW

**Biểu tượng hoàn thành:**
⚪ 0% · 🟠 1–49% · 🟡 50–74% · 🟢 75–99% · ✅ 100%
""",
            'content_en': """
**Status flow:** NOT_STARTED → IN_PROGRESS → COMPLETED / BLOCKED / ON_HOLD / CANCELLED
**Due icons:** 🔴 overdue · ⚠️ today · 🟡 ≤3d · 📅 ≤7d
**Priority:** 🔴 CRITICAL > 🟠 HIGH > 🔵 NORMAL > 🟢 LOW
**Completion:** ⚪ 0% · 🟠 1–49% · 🟡 50–74% · 🟢 75–99% · ✅ 100%
""",
        },
        {
            'icon': '📊',
            'tags': ['completion', 'sync', 'percentage', 'calculation', 'weight', 'tính toán', 'phần trăm'],
            'title_vi': 'Cách tính % Hoàn thành',
            'title_en': 'Completion % Calculation',
            'content_vi': """
**Chuỗi tự động đồng bộ (chạy sau mỗi lần update task):**

**Bước 1: Task → Phase**
```
Phase % = Σ(task.% × task.estimated_hours) / Σ(task.estimated_hours)
```
- Nếu không có task nào set estimated_hours → tính trung bình đơn giản

**Bước 2: Phase → Project**
```
Project % = Σ(phase.% × phase.weight_%) / Σ(phase.weight_%)
```
- Nếu không có phase nào set weight_% → tính trung bình đơn giản

**Ví dụ:**
| Task | Giờ ước tính | Hoàn thành |
|------|-------------|------------|
| Task A | 10h | 100% |
| Task B | 20h | 50% |
| Task C | 10h | 0% |

Phase % = (10×100 + 20×50 + 10×0) / (10+20+10) = 2000/40 = **50%**
""",
            'content_en': """
**Auto-sync:** Task % → Phase % (weighted by est. hours) → Project % (weighted by phase weight)
**Example:** Tasks at 100%/50%/0% with hours 10/20/10 → Phase = (1000+1000+0)/40 = **50%**
""",
        },
        {
            'icon': '🔐',
            'tags': ['role', 'permission', 'access', 'security', 'quyền', 'phân quyền', 'bảo mật'],
            'title_vi': 'Phân quyền theo Role',
            'title_en': 'Role Permissions',
            'content_vi': """
**Quyền truy cập phụ thuộc vào role trong dự án:**

| Khả năng | PM | SA/Senior | Engineer/FAE | Sales | Subcontractor |
|----------|:--:|:---------:|:------------:|:-----:|:-------------:|
| Dashboard | ✅ | ✅ | — | ✅ | — |
| My Tasks | ✅ | ✅ | ✅ | ✅ | ✅ |
| All Tasks (xem) | ✅ | ✅ | ✅ | ✅ | — |
| Phases tab | ✅ | ✅ | — | — | — |
| Team tab | ✅ | ✅ | — | — | — |
| Tạo phase | ✅ | — | — | — | — |
| Tạo task | ✅ | ✅ | — | — | — |
| Sửa mọi task | ✅ | — | — | — | — |
| Sửa task của mình | ✅ | ✅ | ✅ | — | — |
| Quick Update task mình | ✅ | ✅ | ✅ | — | ✅ |
| Xóa task/phase | ✅ | — | — | — | — |
| Gán task | ✅ | ✅ | — | — | — |
| Comment | ✅ | ✅ | ✅ | ✅ | ✅ |
| Upload file | ✅ | ✅ | ✅ | — | ✅ |

**Admin** có quyền PM trên tất cả dự án.

> ⚠️ **Quan trọng: Phải là member của dự án mới có quyền!**
>
> Quyền trên bảng này chỉ áp dụng khi bạn **đã được thêm vào Team** của dự án
> (trang 👥 Team → ➕ Add Member). Nếu chưa được thêm, dù được assign task,
> bạn vẫn chỉ là **Guest (read-only)** — không thể Quick Update, thêm checklist,
> hay sửa task.
>
> **PM lưu ý:** Khi assign task cho ai, đảm bảo họ đã có trong Team với role
> phù hợp (Engineer, Site Engineer, FAE...). Nếu không, họ sẽ không thao tác
> được trên task.
""",
            'content_en': """
| Capability | PM | SA/Senior | Engineer/FAE | Sales | Subcontractor |
|------------|:--:|:---------:|:------------:|:-----:|:-------------:|
| Dashboard | ✅ | ✅ | — | ✅ | — |
| Create phase | ✅ | — | — | — | — |
| Create task | ✅ | ✅ | — | — | — |
| Edit any task | ✅ | — | — | — | — |
| Edit own task | ✅ | ✅ | ✅ | — | — |
| Quick Update own | ✅ | ✅ | ✅ | — | ✅ |
| Delete | ✅ | — | — | — | — |
| Comments | ✅ | ✅ | ✅ | ✅ | ✅ |

**Admin** gets PM-level access on all projects.

> ⚠️ **Important: You must be a project Team member to have permissions!**
>
> The permissions above only apply if you have been **added to the project Team**
> (👥 Team page → ➕ Add Member). If you are not a Team member — even if you are
> assigned a task — you are treated as a **Guest (read-only)** and cannot
> Quick Update, add checklist items, or edit tasks.
>
> **PM note:** When assigning tasks, ensure the person is already in the Team
> with an appropriate role (Engineer, Site Engineer, FAE...). Otherwise they
> won't be able to interact with their tasks.
""",
        },
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# FAQ
# ══════════════════════════════════════════════════════════════════════════════

_FAQ: List[Dict] = [
    {
        'q_vi': "Tại sao tôi không thấy tab Phases?",
        'a_vi': "Tab Phases chỉ hiện cho PM, Solution Architect và Senior Engineer. Các role khác không cần quản lý phase.",
        'q_en': "Why can't I see the Phases tab?",
        'a_en': "Phases tab is only visible to PM, SA, and Senior Engineer roles.",
        'roles': ['engineer', 'viewer', 'restricted'],
        'tags': ['phases', 'access', 'tab', 'visible', 'tab', 'quyền'],
    },
    {
        'q_vi': "Tại sao tôi không thể sửa hoặc xóa task?",
        'a_vi': "Quyền sửa phụ thuộc role: PM sửa mọi task, Lead/Engineer chỉ sửa task gán cho mình. Sales và Viewer là read-only.",
        'q_en': "Why can't I edit or delete tasks?",
        'a_en': "Edit access depends on role: PM edits any task, Lead/Engineer only own tasks. Sales/Viewer are read-only.",
        'roles': ['engineer', 'viewer'],
        'tags': ['edit', 'permission', 'access', 'sửa', 'quyền'],
    },
    {
        'q_vi': "Làm sao báo cáo blocker?",
        'a_vi': "Dùng **⚡ Quick Update** → set status thành **BLOCKED** → nhập lý do block. PM sẽ nhận email tự động. Hoặc post comment với type **BLOCKER**.",
        'q_en': "How do I report a blocker?",
        'a_en': "Use **⚡ Quick Update** → set BLOCKED → enter reason. PM gets notified. Or post a BLOCKER comment.",
        'roles': ['engineer', 'restricted'],
        'tags': ['blocked', 'blocker', 'report', 'báo cáo', 'kẹt'],
    },
    {
        'q_vi': "Tại sao Overall % không khớp với kỳ vọng?",
        'a_vi': "Overall % là trung bình có trọng số: Task % → Phase % (theo est. hours) → Project % (theo weight %). Kiểm tra **weight_%** của phase và **estimated_hours** của task.",
        'q_en': "Why is the overall % not matching expectations?",
        'a_en': "Overall % is weighted: Task % → Phase % (by hours) → Project % (by weight). Check phase weights and task estimated hours.",
        'roles': ['pm'],
        'tags': ['completion', 'percentage', 'weight', 'phần trăm', 'trọng số'],
    },
    {
        'q_vi': "Ai nhận email thông báo?",
        'a_vi': "Task gán → Assignee. Task blocked/completed → PM. Issue → Người được gán. Performer luôn CC. Thêm CC qua CC Selector trong dialog.",
        'q_en': "Who receives email notifications?",
        'a_en': "Task assigned → Assignee. Blocked/completed → PM. Issue → Assigned. Performer always CC'd. Add more via CC Selector.",
        'roles': ['pm', 'engineer'],
        'tags': ['email', 'notification', 'cc', 'thông báo'],
    },
    {
        'q_vi': "Làm sao xem task của dự án khác?",
        'a_vi': "Tab **My Tasks** hiện task trên TẤT CẢ dự án. Để xem task dự án khác, chuyển project ở sidebar.",
        'q_en': "How to see tasks from other projects?",
        'a_en': "**My Tasks** shows tasks across ALL projects. Switch project in sidebar for another project's tasks.",
        'roles': ['engineer', 'pm'],
        'tags': ['project', 'switch', 'cross-project', 'dự án'],
    },
    {
        'q_vi': "Xóa phase thì task bên trong sao?",
        'a_vi': "Xóa phase sẽ soft-delete tất cả task con. Dữ liệu không mất vĩnh viễn (delete_flag) nhưng không hiện trên UI. Chỉ PM mới xóa được.",
        'q_en': "What happens when I delete a phase?",
        'a_en': "Deleting a phase soft-deletes all child tasks. Data is not permanently lost. PM only.",
        'roles': ['pm'],
        'tags': ['delete', 'phase', 'xóa', 'giai đoạn'],
    },
    {
        'q_vi': "Đính kèm file vào task như thế nào?",
        'a_vi': "Mở task (👁️ View) → tab **📎 Files** → upload. Hỗ trợ: PDF, PNG, JPG, XLSX, DOCX.",
        'q_en': "How to attach files to a task?",
        'a_en': "Open task (👁️ View) → **📎 Files** tab → upload. Supports: PDF, PNG, JPG, XLSX, DOCX.",
        'roles': ['engineer', 'pm'],
        'tags': ['file', 'attach', 'upload', 'đính kèm', 'tải lên'],
    },
    {
        'q_vi': "Các màu ngày hết hạn nghĩa là gì?",
        'a_vi': "🔴 = quá hạn, ⚠️ = hôm nay, 🟡 = còn ≤3 ngày, 📅 = còn ≤7 ngày. Task đã hoàn thành/hủy không hiện.",
        'q_en': "What do the due date colors mean?",
        'a_en': "🔴 = overdue, ⚠️ = today, 🟡 = ≤3d, 📅 = ≤7d. Completed/cancelled don't show.",
        'roles': ['engineer', 'pm', 'viewer'],
        'tags': ['due', 'date', 'overdue', 'color', 'ngày', 'hạn', 'màu'],
    },
    {
        'q_vi': "Subcontractor có thấy hết task dự án không?",
        'a_vi': "Không. Subcontractor chỉ thấy **My Tasks** (task gán cho họ). Không thấy task list, phases, team, dashboard. Đây là giới hạn bảo mật.",
        'q_en': "Can a Subcontractor see all project tasks?",
        'a_en': "No. Subcontractors only see My Tasks (assigned to them). No full list, phases, team, or dashboard. Security restriction.",
        'roles': ['pm'],
        'tags': ['subcontractor', 'restricted', 'access', 'bảo mật'],
    },
    {
        'q_vi': "Tại sao tôi không thêm được checklist item / không Quick Update được?",
        'a_vi': """Có 2 nguyên nhân phổ biến:

1. **Chưa được thêm vào Team dự án.** Dù bạn được assign task, quyền thao tác phụ thuộc vào việc bạn có trong danh sách Team (👥 Team) hay không. Nếu chưa → bạn là Guest (read-only).
   → **Giải pháp:** Nhờ PM thêm bạn vào Team với role phù hợp (ví dụ: Site Engineer, Engineer, FAE).

2. **Role không đủ quyền.** Nếu role là **Sales** hoặc **Other**, bạn chỉ có quyền xem, không Quick Update hay thêm checklist — kể cả trên task gán cho mình.
   → **Giải pháp:** Nhờ PM đổi role sang Engineer/Site Engineer/FAE.""",
        'q_en': "Why can't I add checklist items or Quick Update my task?",
        'a_en': """Two common causes:

1. **Not added to the project Team.** Even if assigned a task, your permissions depend on being in the Team roster (👥 Team page). If not → you're a Guest (read-only).
   → **Fix:** Ask PM to add you as a Team member with an appropriate role (e.g., Site Engineer, Engineer, FAE).

2. **Role has insufficient permissions.** If your role is **Sales** or **Other**, you can only view — no Quick Update or checklist editing, even on your own tasks.
   → **Fix:** Ask PM to change your role to Engineer/Site Engineer/FAE.""",
        'roles': ['pm', 'engineer', 'viewer', 'restricted'],
        'tags': ['checklist', 'quick-update', 'permission', 'cannot', 'quyền', 'không được', 'thêm', 'cập nhật', 'member', 'team'],
    },
    {
        'q_vi': "Assign task cho người chưa trong Team thì sao?",
        'a_vi': """Hệ thống cho phép assign task cho bất kỳ employee nào, **nhưng** nếu người đó chưa được thêm vào Team dự án, họ sẽ:
- Không Quick Update được task
- Không thêm/toggle checklist item được
- Không sửa task được
- Chỉ xem được (Guest, read-only)

**Quy trình đúng:** Luôn **thêm vào Team trước** (👥 Team → ➕ Add Member → chọn role), **rồi mới assign task**. Như vậy hệ thống phân quyền sẽ hoạt động đúng và người đó nhận đầy đủ quyền.""",
        'q_en': "What happens if I assign a task to someone not in the Team?",
        'a_en': """The system allows assigning tasks to any employee, **but** if they are not in the project Team, they will:
- Not be able to Quick Update the task
- Not be able to add/toggle checklist items
- Not be able to edit the task
- Only have read-only (Guest) access

**Correct workflow:** Always **add to Team first** (👥 Team → ➕ Add Member → select role), **then assign tasks**. This ensures proper permissions.""",
        'roles': ['pm'],
        'tags': ['assign', 'team', 'member', 'permission', 'gán', 'quyền', 'thêm member'],
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOWS
# ══════════════════════════════════════════════════════════════════════════════

_WORKFLOWS: List[Dict] = [
    {
        'icon': '🆕', 'role': 'pm',
        'tags': ['setup', 'new', 'project', 'phase', 'template', 'thiết lập', 'mới'],
        'title_vi': 'Thiết lập WBS cho dự án mới',
        'title_en': 'Set Up a New Project WBS',
        'steps_vi': [
            "Mở trang WBS → chọn dự án ở sidebar",
            "Vào tab **🔷 Phases**",
            "Click **📦 Load Template** để tạo 7 phase chuẩn",
            "Sửa từng phase: set **Planned Start/End** và **Weight %**",
            "Vào tab **📋 All Tasks** → **➕ Add Task** cho từng phase",
            "Gán task cho member → họ nhận email thông báo",
            "Xem **📊 Dashboard** → xác nhận mọi thứ đúng",
        ],
        'steps_en': [
            "Open WBS page → select project in sidebar",
            "Go to **🔷 Phases** tab",
            "Click **📦 Load Template** to create standard phases",
            "Edit each phase: set **Planned Start/End** and **Weight %**",
            "Go to **📋 All Tasks** → **➕ Add Task** for each phase",
            "Assign tasks to members → they get email notifications",
            "Review **📊 Dashboard** → confirm all looks correct",
        ],
    },
    {
        'icon': '☀️', 'role': 'pm',
        'tags': ['daily', 'routine', 'check-in', 'monitor', 'hàng ngày', 'kiểm tra'],
        'title_vi': 'Check-in hàng ngày (PM)',
        'title_en': 'Daily PM Check-in',
        'steps_vi': [
            "Mở WBS → tab **📊 Dashboard**",
            "Kiểm tra KPI: Overdue hoặc Blocked tăng?",
            "Xem **🎯 Action Required** — xử lý từ trên xuống",
            "🔴 Blocked: click View → đọc lý do → Comment hoặc Edit",
            "⏰ Overdue: click Quick Update → kiểm tra thực trạng với assignee",
            "Lướt **Phase Progress** — phase nào đang đứng yên?",
            "Xong! ~5 phút",
        ],
        'steps_en': [
            "Open WBS → **📊 Dashboard** tab",
            "Check KPI row: any increase in Overdue or Blocked?",
            "Review **🎯 Action Required** — handle top items",
            "🔴 Blocked: click View → read reason → Comment or Edit",
            "⏰ Overdue: click Quick Update → check with assignee",
            "Glance at **Phase Progress** — any phase stuck?",
            "Done! ~5 minutes",
        ],
    },
    {
        'icon': '🔧', 'role': 'engineer',
        'tags': ['daily', 'workflow', 'update', 'engineer', 'hàng ngày', 'kỹ sư'],
        'title_vi': 'Quy trình hàng ngày (Kỹ sư)',
        'title_en': 'Engineer Daily Workflow',
        'steps_vi': [
            "Mở WBS → tab **🙋 My Tasks** (tab mặc định của bạn)",
            "Kiểm tra action items ở đầu trang — có 🔴 hoặc ⏰?",
            "Với mỗi task đã làm hôm nay:",
            "  → Chọn task → **⚡ Quick Update**",
            "  → Cập nhật Status, Completion %, Actual Hours",
            "Nếu bị kẹt → set BLOCKED + nhập lý do (PM được thông báo)",
            "Nếu xong → set COMPLETED (PM được thông báo)",
            "Xong! ~2 phút",
        ],
        'steps_en': [
            "Open WBS → **🙋 My Tasks** (your default tab)",
            "Check action items at top — any 🔴 or ⏰?",
            "For each task you worked on today:",
            "  → Select task → **⚡ Quick Update**",
            "  → Update Status, Completion %, Actual Hours",
            "If stuck → set BLOCKED + enter reason (PM notified)",
            "If done → set COMPLETED (PM notified)",
            "Done! ~2 minutes",
        ],
    },
    {
        'icon': '🔴', 'role': 'pm',
        'tags': ['blocked', 'resolve', 'unblock', 'gỡ block', 'xử lý'],
        'title_vi': 'Xử lý task bị Blocked (PM)',
        'title_en': 'Handle a Blocked Task (PM)',
        'steps_vi': [
            "Bạn nhận email: 🔴 [BLOCKED] task notification",
            "Click **View in App** trong email (hoặc tìm trên Dashboard)",
            "Đọc lý do block trong Action Required panel",
            "Click **👁️ View** → xem Comments để hiểu context",
            "Cách A: Comment hướng dẫn giải quyết",
            "Cách B: **✏️ Edit** → đổi assignee nếu người khác có thể gỡ block",
            "Cách C: Escalate bên ngoài → Comment ghi nhận escalation",
            "Khi giải quyết xong: assignee set status lại IN_PROGRESS",
        ],
        'steps_en': [
            "You receive email: 🔴 [BLOCKED] notification",
            "Click **View in App** (or find in Dashboard)",
            "Read blocker reason in Action Required panel",
            "Click **👁️ View** → check Comments for context",
            "Option A: Comment with resolution instructions",
            "Option B: **✏️ Edit** → reassign if someone else can unblock",
            "Option C: Escalate externally → Comment to document",
            "Once resolved: assignee sets status back to IN_PROGRESS",
        ],
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# CONTEXT TIPS
# ══════════════════════════════════════════════════════════════════════════════

_CONTEXT_TIPS = {
    'vi': {
        'no_phases':   "💡 **Bắt đầu:** Load template phase để thiết lập WBS nhanh.",
        'blocked':     "⚡ **Cần xử lý:** Bạn có {n} task bị blocked — xem Dashboard → Action Required.",
        'overdue':     "⏰ **Cần xử lý:** {n} task quá hạn — follow-up với assignee.",
        'unassigned':  "❓ **Cần xử lý:** {n} task chưa gán người — gán trong tab All Tasks.",
        'near_done':   "🎯 **Tip:** Dự án >80% — nên tạo Progress Report (page 9).",
        'my_blocked':  "🔴 Bạn có task bị blocked. Cập nhật PM qua Quick Update.",
        'my_overdue':  "⏰ Bạn có task quá hạn. Cập nhật tiến độ hoặc báo blocker.",
    },
    'en': {
        'no_phases':   "💡 **Getting started:** Load a phase template to set up WBS quickly.",
        'blocked':     "⚡ **Now:** You have {n} blocked task(s) — check Dashboard → Action Required.",
        'overdue':     "⏰ **Now:** {n} task(s) overdue — follow up with assignees.",
        'unassigned':  "❓ **Now:** {n} task(s) have no assignee — assign in All Tasks tab.",
        'near_done':   "🎯 **Tip:** Project >80% — consider creating a Progress Report (page 9).",
        'my_blocked':  "🔴 You have blocked tasks. Update PM via Quick Update.",
        'my_overdue':  "⏰ You have overdue tasks. Update progress or flag blockers.",
    },
}


def get_context_tips(kpis: dict, perms: dict, has_phases: bool, lang: str = 'vi') -> List[str]:
    """Generate context-aware tips based on project state."""
    tips = []
    t = _CONTEXT_TIPS.get(lang, _CONTEXT_TIPS['en'])

    if perms.get('tier') == 'manager':
        if not has_phases:
            tips.append(t['no_phases'])
        if kpis.get('blocked', 0) > 0:
            tips.append(t['blocked'].format(n=kpis['blocked']))
        if kpis.get('overdue', 0) > 0:
            tips.append(t['overdue'].format(n=kpis['overdue']))
        if kpis.get('unassigned', 0) > 0:
            tips.append(t['unassigned'].format(n=kpis['unassigned']))
        if kpis.get('overall_pct', 0) > 80:
            tips.append(t['near_done'])

    elif perms.get('tier') in ('member', 'restricted', 'lead'):
        if kpis.get('blocked', 0) > 0:
            tips.append(t['my_blocked'])
        if kpis.get('overdue', 0) > 0:
            tips.append(t['my_overdue'])

    return tips


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def get_guide_sections_for_role(tier: str, lang: str = 'vi') -> List[Dict]:
    """Get guide sections with translated title/content for a role tier."""
    role_key_map = {
        'manager': 'pm', 'lead': 'pm',
        'member': 'engineer', 'restricted': 'engineer',
        'viewer': 'viewer',
    }
    role_key = role_key_map.get(tier, 'viewer')

    raw = list(_SECTIONS.get(role_key, []))
    raw.extend(_SECTIONS.get('general', []))

    return [
        {
            'icon': s['icon'],
            'tags': s['tags'],
            'title': _t(s, 'title', lang),
            'content': _t(s, 'content', lang),
        }
        for s in raw
    ]


def get_faq_for_role(tier: str, lang: str = 'vi') -> List[Dict]:
    """Get FAQ items translated for a role tier."""
    role_key_map = {
        'manager': 'pm', 'lead': 'pm',
        'member': 'engineer', 'restricted': 'engineer',
        'viewer': 'viewer',
    }
    role_key = role_key_map.get(tier, 'viewer')

    return [
        {
            'q': _t(item, 'q', lang),
            'a': _t(item, 'a', lang),
            'tags': item.get('tags', []),
        }
        for item in _FAQ
        if not item.get('roles') or role_key in item['roles']
    ]


def get_workflows_for_role(tier: str, lang: str = 'vi') -> List[Dict]:
    """Get workflow guides translated for a role tier."""
    role_key_map = {
        'manager': 'pm', 'lead': 'pm',
        'member': 'engineer', 'restricted': 'engineer',
        'viewer': 'viewer',
    }
    role_key = role_key_map.get(tier, 'viewer')

    return [
        {
            'icon': w['icon'],
            'title': _t(w, 'title', lang),
            'steps': w.get(f'steps_{lang}', w.get('steps_en', [])),
            'tags': w.get('tags', []),
        }
        for w in _WORKFLOWS
        if w.get('role') == role_key
    ]