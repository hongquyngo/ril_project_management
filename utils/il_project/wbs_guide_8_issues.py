# utils/il_project/wbs_guide_8_issues.py
"""
User Guide content for Issues & Risks page (Page 8).
Bilingual VI/EN. Role-aware sections, FAQ, workflows, context tips.
"""

from typing import Dict, List
from .wbs_guide_common import _t

_SECTIONS: Dict[str, List[Dict]] = {
    'pm': [
        {
            'icon': '📊', 'tags': ['dashboard', 'kpi', 'overview', 'tổng quan'],
            'title_vi': 'KPI Banner — Tổng quan nhanh',
            'title_en': 'KPI Banner — Quick Overview',
            'content_vi': """
**5 chỉ số luôn hiện ở đầu trang:**

| KPI | Ý nghĩa | Hành động |
|-----|---------|-----------|
| **Open Issues** | Issue chưa giải quyết | Nếu tăng → review nguyên nhân |
| **Overdue Issues** | Issue quá hạn | Follow-up assignee hoặc escalate |
| **High Risks** | Risk có score ≥ 10/25 | Review mitigation plan |
| **Pending COs** | CO chờ duyệt | Duyệt hoặc reject |
| **Approved Impact** | Tổng chi phí CO đã duyệt | So sánh với budget |

**Action Required** (expandable): liệt kê cụ thể từng item cần xử lý.
""",
            'content_en': """
**5 KPIs always visible:** Open Issues, Overdue Issues, High Risks, Pending COs, Approved Impact.
**Action Required** expander lists specific items needing attention.
""",
        },
        {
            'icon': '🔧', 'tags': ['issue', 'manage', 'severity', 'quản lý', 'vấn đề'],
            'title_vi': 'Quản lý Issues',
            'title_en': 'Managing Issues',
            'content_vi': """
**Issue = vấn đề cụ thể cần giải quyết** (technical, commercial, logistics...).

**Tạo issue:** ➕ Report Issue → điền Title, Category, Severity, Assign To, Due Date.

**Severity guide:**
| Mức | Khi nào dùng |
|-----|-------------|
| 🔴 CRITICAL | Ảnh hưởng milestone, cần xử lý trong 24h |
| 🟠 HIGH | Ảnh hưởng tiến độ, xử lý trong 1 tuần |
| 🟡 MEDIUM | Cần xử lý nhưng không gấp |
| 🟢 LOW | Nice-to-fix, có thể hoãn |

**Quick filters:** ⏰ Overdue | 🔴 Critical | 🙋 Mine | 📋 Open only

**Cột Age:** hiện số ngày kể từ khi báo cáo — issue "già" cần ưu tiên.

**Cột Due:** 🔴 = quá hạn, ⚠️ = hôm nay, 🟡 = sắp hạn — giống pattern WBS tasks.

**Workflow:** OPEN → IN_PROGRESS → RESOLVED → CLOSED (hoặc ESCALATED).
""",
            'content_en': """
**Issue = specific problem needing resolution.** Create via ➕ Report Issue.
**Severity:** 🔴 CRITICAL (24h) > 🟠 HIGH (1 week) > 🟡 MEDIUM > 🟢 LOW.
**Quick filters:** Overdue, Critical, Mine, Open only.
**Age column:** days since reported. **Due column:** 🔴 overdue, ⚠️ today, 🟡 soon.
""",
        },
        {
            'icon': '⚠️', 'tags': ['risk', 'heatmap', 'matrix', 'score', 'rủi ro', 'ma trận'],
            'title_vi': 'Quản lý Risks & Heatmap',
            'title_en': 'Managing Risks & Heatmap',
            'content_vi': """
**Risk = rủi ro tiềm ẩn có thể xảy ra** (khác với Issue = đã xảy ra).

**Risk Score = Probability × Impact** (1-25):
| Score | Mức | Hành động |
|-------|-----|-----------|
| 16-25 | 🔴 Critical | Mitigation bắt buộc, review hàng tuần |
| 10-15 | 🟠 High | Mitigation plan, review 2 tuần |
| 5-9 | 🟡 Medium | Monitor, có contingency plan |
| 1-4 | 🟢 Low | Accept, review hàng tháng |

**Risk Heatmap (ma trận 5×5):**
- Trục dọc: Probability (RARE → ALMOST_CERTAIN)
- Trục ngang: Impact (NEGLIGIBLE → SEVERE)
- Số trong ô = số risk ở mức đó
- Màu = mức nguy hiểm

**Review Date:** Mỗi risk có ngày review tiếp theo. Hiện ⏰ nếu quá hạn review.

**Status flow:** IDENTIFIED → MITIGATING → ACCEPTED / CLOSED / OCCURRED.
""",
            'content_en': """
**Risk = potential future problem.** Score = Probability × Impact (1-25).
**Heatmap** shows 5×5 matrix with color-coded severity.
**Review Date** shows ⏰ when overdue. Status: IDENTIFIED → MITIGATING → ACCEPTED/CLOSED/OCCURRED.
""",
        },
        {
            'icon': '📝', 'tags': ['change order', 'co', 'contract', 'impact', 'thay đổi', 'hợp đồng'],
            'title_vi': 'Change Orders & Net Impact',
            'title_en': 'Change Orders & Net Impact',
            'content_vi': """
**Change Order (CO) = yêu cầu thay đổi scope/schedule/cost.**

**Net Impact Summary** (đầu tab):
```
Hợp đồng gốc:     5,000,000,000 ₫
├ CO đã duyệt:   +  450,000,000 ₫ (3 COs, +15 ngày)
├ CO chờ duyệt:  +  120,000,000 ₫ (2 COs)
└ Tổng điều chỉnh: 5,570,000,000 ₫
```

**Status flow:** DRAFT → SUBMITTED → APPROVED / REJECTED / CANCELLED.

**Approval:** Chỉ PM approve. Set Approved By + status = APPROVED → auto-notify requester.

**Customer Approval:** Checkbox riêng cho xác nhận từ khách hàng + reference number.

**Lưu ý:** Chi phí CO chỉ PM thấy. Lead thấy title + status nhưng không thấy số tiền.
""",
            'content_en': """
**CO = scope/schedule/cost change request.** Net Impact shows original → approved delta → revised total.
**Flow:** DRAFT → SUBMITTED → APPROVED/REJECTED. Only PM approves. Cost details PM-only.
""",
        },
    ],

    'engineer': [
        {
            'icon': '🔧', 'tags': ['report', 'issue', 'blocker', 'báo cáo'],
            'title_vi': 'Báo cáo & Theo dõi Issues',
            'title_en': 'Reporting & Tracking Issues',
            'content_vi': """
**Bạn có thể:**
- ✅ Báo cáo issue mới (➕ Report Issue)
- ✅ Xem và sửa issue gán cho bạn hoặc bạn tạo
- ✅ Đính kèm file vào issue
- ❌ Không thể xóa issue hoặc xem tab Risks/COs

**Khi nào nên tạo Issue?**
- Phát hiện lỗi kỹ thuật trong quá trình làm việc
- Thiếu vật tư / thiết bị
- Vấn đề giao tiếp với vendor / khách hàng
- Bất kỳ vấn đề nào block tiến độ

**Quick filter 🙋 Mine:** chỉ hiện issue gán cho bạn hoặc bạn báo cáo.

**Tips:**
- Set severity đúng mức → PM ưu tiên xử lý
- Mô tả impact rõ ràng → giúp PM đánh giá
- Cập nhật status khi issue được giải quyết
""",
            'content_en': """
**You can:** report issues, edit own/assigned issues, attach files.
**Cannot:** delete issues, access Risks/COs tabs.
Use 🙋 Mine filter to see only your issues. Set severity accurately for PM prioritization.
""",
        },
    ],

    'general': [
        {
            'icon': '🔐', 'tags': ['permission', 'role', 'access', 'quyền', 'phân quyền'],
            'title_vi': 'Phân quyền trang Issues & Risks',
            'title_en': 'Issues & Risks Permissions',
            'content_vi': """
| Thao tác | PM | SA/Senior | Engineer | Sales | Subcontractor |
|----------|:--:|:---------:|:--------:|:-----:|:-------------:|
| Xem Issues | ✅ | ✅ | ✅ | ✅ | ❌ |
| Tạo Issue | ✅ | ✅ | ✅ | ❌ | ❌ |
| Sửa Issue (mọi) | ✅ | ❌ | ❌ | ❌ | ❌ |
| Sửa Issue (mình) | ✅ | ✅ | ✅ | ❌ | ❌ |
| Xóa Issue | ✅ | ❌ | ❌ | ❌ | ❌ |
| Tab Risks | ✅ | ✅ | ❌ | ❌ | ❌ |
| Tạo Risk | ✅ | ✅ | ❌ | ❌ | ❌ |
| Tab Change Orders | ✅ | ✅ | ❌ | ❌ | ❌ |
| Tạo/Approve CO | ✅ | ❌ | ❌ | ❌ | ❌ |
| Xem chi phí CO | ✅ | ❌ | ❌ | ❌ | ❌ |

**Sales** chỉ xem issue (read-only). **Subcontractor** không truy cập trang này.
""",
            'content_en': """
| Action | PM | SA/Senior | Engineer | Sales | Subcontractor |
|--------|:--:|:---------:|:--------:|:-----:|:-------------:|
| View Issues | ✅ | ✅ | ✅ | ✅ | ❌ |
| Create Issue | ✅ | ✅ | ✅ | ❌ | ❌ |
| Risks tab | ✅ | ✅ | ❌ | ❌ | ❌ |
| COs tab | ✅ | ✅ (no cost) | ❌ | ❌ | ❌ |
| Create/Approve CO | ✅ | ❌ | ❌ | ❌ | ❌ |
""",
        },
    ],
}

_FAQ: List[Dict] = [
    {
        'q_vi': "Issue vs Risk khác nhau thế nào?",
        'a_vi': "**Issue** = vấn đề ĐÃ xảy ra, cần giải quyết cụ thể. **Risk** = vấn đề CÓ THỂ xảy ra, cần phòng ngừa. VD: 'Cable tray giao trễ 2 tuần' = Issue. 'Vendor có thể giao trễ do thiếu nguyên liệu' = Risk.",
        'q_en': "What's the difference between Issue and Risk?",
        'a_en': "**Issue** = problem that HAS occurred. **Risk** = problem that MIGHT occur. E.g. 'Cable tray delivered 2 weeks late' = Issue. 'Vendor might delay due to material shortage' = Risk.",
        'roles': ['pm', 'engineer'],
        'tags': ['issue', 'risk', 'difference', 'khác nhau'],
    },
    {
        'q_vi': "Risk Score tính thế nào?",
        'a_vi': "**Score = Probability × Impact**. Cả hai đều 1-5. VD: LIKELY(4) × MAJOR(4) = 16 (🔴 Critical). POSSIBLE(3) × MINOR(2) = 6 (🟡 Medium).",
        'q_en': "How is Risk Score calculated?",
        'a_en': "**Score = Probability × Impact**. Both 1-5. E.g. LIKELY(4) × MAJOR(4) = 16 (🔴). POSSIBLE(3) × MINOR(2) = 6 (🟡).",
        'roles': ['pm', 'lead'],
        'tags': ['risk', 'score', 'calculate', 'tính'],
    },
    {
        'q_vi': "Tại sao tôi không thấy tab Risks / Change Orders?",
        'a_vi': "Tab Risks và COs chỉ hiện cho PM và Lead (SA/Senior Engineer). Engineer chỉ thấy tab Issues.",
        'q_en': "Why can't I see Risks / Change Orders tabs?",
        'a_en': "Risks and COs tabs are only visible to PM and Lead (SA/Senior). Engineers only see Issues tab.",
        'roles': ['engineer'],
        'tags': ['tab', 'hidden', 'ẩn', 'quyền'],
    },
    {
        'q_vi': "CO approved nhưng chưa có Customer Approval?",
        'a_vi': "Internal approval (PM) và Customer approval là 2 bước riêng. PM approve trước → thực hiện → sau đó khách ký xác nhận → tick Customer Approved + nhập Reference.",
        'q_en': "CO approved but no Customer Approval yet?",
        'a_en': "Internal (PM) and Customer approval are separate. PM approves first → execute → customer signs later → tick Customer Approved + enter Reference.",
        'roles': ['pm'],
        'tags': ['co', 'approve', 'customer', 'duyệt'],
    },
    {
        'q_vi': "Heatmap đọc như thế nào?",
        'a_vi': "Trục dọc = Probability (dưới thấp, trên cao). Trục ngang = Impact (trái nhẹ, phải nặng). Số = số risk ở ô đó. Góc trên-phải = nguy hiểm nhất (🔴). Góc dưới-trái = an toàn nhất (🟢).",
        'q_en': "How to read the Risk Heatmap?",
        'a_en': "Vertical = Probability (low bottom, high top). Horizontal = Impact (low left, high right). Number = risk count. Top-right = most dangerous (🔴). Bottom-left = safest (🟢).",
        'roles': ['pm', 'lead'],
        'tags': ['heatmap', 'read', 'đọc', 'matrix'],
    },
]

_WORKFLOWS: List[Dict] = [
    {
        'icon': '🔧', 'role': 'pm',
        'tags': ['issue', 'resolve', 'workflow', 'giải quyết'],
        'title_vi': 'Xử lý Issue từ A-Z',
        'title_en': 'Resolve an Issue End-to-End',
        'steps_vi': [
            "Issue được báo cáo → hiện trong Action Required nếu Critical/Overdue",
            "Xem chi tiết → đánh giá severity, impact",
            "Assign cho người phù hợp (nếu chưa assign)",
            "Set due date hợp lý",
            "Follow-up: kiểm tra qua filter ⏰ Overdue",
            "Khi giải quyết xong → assignee set RESOLVED + nhập Resolution",
            "PM review → set CLOSED",
        ],
        'steps_en': [
            "Issue reported → appears in Action Required if Critical/Overdue",
            "Review details → assess severity, impact",
            "Assign to appropriate person",
            "Set reasonable due date",
            "Follow up via ⏰ Overdue filter",
            "When resolved → assignee sets RESOLVED + enters Resolution",
            "PM reviews → sets CLOSED",
        ],
    },
    {
        'icon': '⚠️', 'role': 'pm',
        'tags': ['risk', 'review', 'weekly', 'hàng tuần'],
        'title_vi': 'Review Risk Register (hàng tuần)',
        'title_en': 'Weekly Risk Register Review',
        'steps_vi': [
            "Mở tab **⚠️ Risks** → xem Heatmap",
            "Focus vào ô 🔴 và 🟠 → risk nào đang ở mức nguy hiểm?",
            "Kiểm tra cột Review → risk nào ⏰ quá hạn review?",
            "Với mỗi risk cần review: click View → đánh giá lại Probability/Impact",
            "Cập nhật mitigation plan nếu cần",
            "Set review date mới → 1-2 tuần tới",
            "Nếu risk đã xảy ra → set OCCURRED → tạo Issue tương ứng",
        ],
        'steps_en': [
            "Open **⚠️ Risks** tab → check Heatmap",
            "Focus on 🔴 and 🟠 cells → which risks are critical?",
            "Check Review column → any ⏰ overdue?",
            "For each: View → re-assess Probability/Impact",
            "Update mitigation plan if needed",
            "Set new review date → 1-2 weeks",
            "If occurred → set OCCURRED → create corresponding Issue",
        ],
    },
]

_CONTEXT_TIPS = {
    'vi': {
        'critical':   "🔴 **Cần xử lý:** {n} issue CRITICAL chưa giải quyết.",
        'overdue':    "⏰ **Cần xử lý:** {n} issue quá hạn.",
        'high_risk':  "⚠️ **Lưu ý:** {n} risk có score ≥ 10 (High/Critical).",
        'pending_co': "📝 **Cần duyệt:** {n} Change Order chờ approval.",
    },
    'en': {
        'critical':   "🔴 **Action needed:** {n} CRITICAL issue(s) unresolved.",
        'overdue':    "⏰ **Action needed:** {n} overdue issue(s).",
        'high_risk':  "⚠️ **Note:** {n} risk(s) with score ≥ 10 (High/Critical).",
        'pending_co': "📝 **Needs approval:** {n} Change Order(s) pending.",
    },
}


def get_issues_context_tips(kpis: dict, perms: dict, lang: str = 'vi') -> List[str]:
    tips = []
    t = _CONTEXT_TIPS.get(lang, _CONTEXT_TIPS['en'])
    if perms.get('tier') in ('manager', 'lead'):
        if kpis.get('critical_issues', 0) > 0:
            tips.append(t['critical'].format(n=kpis['critical_issues']))
        if kpis.get('overdue_issues', 0) > 0:
            tips.append(t['overdue'].format(n=kpis['overdue_issues']))
        if kpis.get('high_risks', 0) > 0:
            tips.append(t['high_risk'].format(n=kpis['high_risks']))
        if kpis.get('pending_co', 0) > 0:
            tips.append(t['pending_co'].format(n=kpis['pending_co']))
    return tips


def get_issues_guide_sections(tier: str, lang: str = 'vi') -> List[Dict]:
    key_map = {'manager': 'pm', 'lead': 'pm', 'member': 'engineer',
               'restricted': 'engineer', 'viewer': 'engineer'}
    role_key = key_map.get(tier, 'engineer')
    raw = list(_SECTIONS.get(role_key, []))
    raw.extend(_SECTIONS.get('general', []))
    return [{'icon': s['icon'], 'tags': s['tags'],
             'title': _t(s, 'title', lang), 'content': _t(s, 'content', lang)} for s in raw]


def get_issues_faq(tier: str, lang: str = 'vi') -> List[Dict]:
    key_map = {'manager': 'pm', 'lead': 'lead', 'member': 'engineer',
               'restricted': 'engineer', 'viewer': 'engineer'}
    role_key = key_map.get(tier, 'engineer')
    return [{'q': _t(i, 'q', lang), 'a': _t(i, 'a', lang), 'tags': i.get('tags', [])}
            for i in _FAQ if not i.get('roles') or role_key in i['roles']]


def get_issues_workflows(tier: str, lang: str = 'vi') -> List[Dict]:
    key_map = {'manager': 'pm', 'lead': 'pm'}
    role_key = key_map.get(tier)
    if not role_key:
        return []
    return [{'icon': w['icon'], 'title': _t(w, 'title', lang),
             'steps': w.get(f'steps_{lang}', w.get('steps_en', [])), 'tags': w.get('tags', [])}
            for w in _WORKFLOWS if w.get('role') == role_key]
