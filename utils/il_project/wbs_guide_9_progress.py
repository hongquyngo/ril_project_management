# utils/il_project/wbs_guide_9_progress.py
"""
User Guide content for Progress & Quality page (Page 9).
Bilingual VI/EN. Role-aware sections, FAQ, workflows, context tips.
"""

from typing import Dict, List
from .wbs_guide_common import _t

_SECTIONS: Dict[str, List[Dict]] = {
    'pm': [
        {
            'icon': '📊', 'tags': ['report', 'progress', 'rag', 'báo cáo', 'tiến độ'],
            'title_vi': 'Progress Reports — Báo cáo tiến độ',
            'title_en': 'Progress Reports',
            'content_vi': """
**Progress Report** ghi nhận tình trạng dự án theo định kỳ.

**Tạo report:** ➕ New Report → chọn Type (Weekly/Monthly/Milestone...), set RAG status, điền narrative.

**RAG Status (Overall):**
| Trạng thái | Icon | Ý nghĩa |
|-----------|------|---------|
| ON_TRACK | 🟢 | Đúng tiến độ, không vấn đề |
| AHEAD | 🔵 | Sớm hơn kế hoạch |
| AT_RISK | 🟡 | Có rủi ro trễ — cần theo dõi sát |
| DELAYED | 🔴 | Đã trễ — cần hành động |
| CRITICAL | 🔴 | Nguy cơ nghiêm trọng — cần escalate |

**Các status phụ:**
- **Schedule:** ON_TRACK / AT_RISK / DELAYED / AHEAD
- **Cost:** UNDER_BUDGET / ON_BUDGET / OVER_BUDGET
- **Quality:** SATISFACTORY / NEEDS_IMPROVEMENT / UNSATISFACTORY

**Narrative gồm 4 phần:**
1. **Executive Summary** — tổng quan ngắn gọn
2. **Accomplishments** — đã làm được gì trong kỳ
3. **Planned Next** — kế hoạch kỳ tiếp
4. **Blockers** — vấn đề cần giải quyết

**Report Status:** DRAFT → SUBMITTED → REVIEWED (set reviewer khi edit).
""",
            'content_en': """
**Progress Report** captures project status periodically.
**RAG:** 🟢 ON_TRACK | 🔵 AHEAD | 🟡 AT_RISK | 🔴 DELAYED/CRITICAL.
**Narrative:** Executive Summary, Accomplishments, Planned Next, Blockers.
**Flow:** DRAFT → SUBMITTED → REVIEWED.
""",
        },
        {
            'icon': '✅', 'tags': ['quality', 'qc', 'fat', 'sat', 'inspection', 'chất lượng', 'kiểm tra'],
            'title_vi': 'Quality Checklists — Kiểm tra chất lượng',
            'title_en': 'Quality Checklists',
            'content_vi': """
**Quality Checklist** quản lý các đợt kiểm tra chất lượng (FAT, SAT, Commissioning...).

**Loại QC:**
| Type | Mô tả |
|------|-------|
| FAT | Factory Acceptance Test — test tại nhà máy |
| SAT | Site Acceptance Test — test tại site |
| INSPECTION | Kiểm tra định kỳ |
| COMMISSIONING | Nghiệm thu đưa vào vận hành |
| HANDOVER | Bàn giao cho khách hàng |
| SAFETY | Kiểm tra an toàn |

**Status flow:** PLANNED → IN_PROGRESS → PASSED / FAILED / CONDITIONAL → CANCELLED

**Kết quả:**
- **Total Items** / **Passed** / **Failed** → tính **Pass Rate** tự động
- **FAILED:** cần ghi Remarks + Next Action + Retest Date
- **CONDITIONAL:** đạt có điều kiện, cần follow-up

**Customer Sign-off:**
- Sau khi PASSED, tick "Customer Signed Off" + nhập người ký
- KPI hiện bao nhiêu QC passed nhưng chưa có customer sign

**Quick filters:** ⚪ Planned | 🔴 Failed | ⏳ No Cust. Sign | 🙋 My Inspections
""",
            'content_en': """
**QC types:** FAT, SAT, INSPECTION, COMMISSIONING, HANDOVER, SAFETY.
**Flow:** PLANNED → IN_PROGRESS → PASSED/FAILED/CONDITIONAL.
**Results:** Total/Passed/Failed → auto Pass Rate. Customer Sign-off after PASSED.
**Filters:** Planned, Failed, No Customer Sign, My Inspections.
""",
        },
    ],

    'engineer': [
        {
            'icon': '✅', 'tags': ['inspect', 'quality', 'update', 'kiểm tra', 'cập nhật'],
            'title_vi': 'Cập nhật kết quả Quality Checklist',
            'title_en': 'Updating Quality Checklist Results',
            'content_vi': """
**Nếu bạn là Inspector của một QC:**
- Bạn thấy QC trong filter **🙋 My Inspections**
- Bạn có thể **✏️ Edit** để cập nhật kết quả

**Quy trình:**
1. Trước khi kiểm tra: QC ở trạng thái PLANNED
2. Bắt đầu kiểm tra: set IN_PROGRESS
3. Nhập kết quả: Total Items, Passed, Failed
4. Set status: PASSED / FAILED / CONDITIONAL
5. Nếu FAILED: điền Remarks, Next Action, Retest Date
6. Đính kèm ảnh/tài liệu kiểm tra

**Bạn KHÔNG thể:**
- Tạo QC mới (PM/Lead tạo)
- Xóa QC
- Tạo Progress Report
""",
            'content_en': """
**As Inspector:** Edit QC to update results (Total/Passed/Failed), set status, attach evidence.
**Cannot:** Create/delete QC or create Progress Reports.
""",
        },
    ],

    'general': [
        {
            'icon': '🔐', 'tags': ['permission', 'role', 'quyền'],
            'title_vi': 'Phân quyền trang Progress & Quality',
            'title_en': 'Page Permissions',
            'content_vi': """
| Thao tác | PM | SA/Senior | Engineer | Sales | Subcontractor |
|----------|:--:|:---------:|:--------:|:-----:|:-------------:|
| Xem Reports | ✅ | ✅ | ✅ | ✅ | ❌ |
| Tạo Report | ✅ | ✅ | ❌ | ❌ | ❌ |
| Sửa Report (mọi) | ✅ | ❌ | ❌ | ❌ | ❌ |
| Sửa Report (mình tạo) | ✅ | ✅ | ❌ | ❌ | ❌ |
| Xem QC | ✅ | ✅ | ✅ | ✅ | ❌ |
| Tạo QC | ✅ | ✅ | ❌ | ❌ | ❌ |
| Sửa QC (mọi) | ✅ | ❌ | ❌ | ❌ | ❌ |
| Sửa QC (inspector) | ✅ | ✅ | ✅ | ❌ | ❌ |
| Xóa QC | ✅ | ❌ | ❌ | ❌ | ❌ |

**Subcontractor** không truy cập được trang này.
""",
            'content_en': """
| Action | PM | SA/Senior | Engineer | Sales | Subcontractor |
|--------|:--:|:---------:|:--------:|:-----:|:-------------:|
| View | ✅ | ✅ | ✅ | ✅ | ❌ |
| Create Report/QC | ✅ | ✅ | ❌ | ❌ | ❌ |
| Edit own | ✅ | ✅ | Inspector only | ❌ | ❌ |
| Delete QC | ✅ | ❌ | ❌ | ❌ | ❌ |
""",
        },
    ],
}

_FAQ: List[Dict] = [
    {
        'q_vi': "RAG status là gì?",
        'a_vi': "RAG = Red/Amber/Green — hệ thống đánh giá tình trạng dự án. 🟢 = tốt, 🟡 = cần chú ý, 🔴 = có vấn đề. Dùng trong Progress Report để tóm tắt overall health.",
        'q_en': "What is RAG status?",
        'a_en': "RAG = Red/Amber/Green traffic light system. 🟢 = good, 🟡 = needs attention, 🔴 = problem. Used in Progress Reports for overall health summary.",
        'roles': ['pm', 'engineer'],
        'tags': ['rag', 'status', 'color'],
    },
    {
        'q_vi': "Khi nào tạo Progress Report?",
        'a_vi': "Tùy loại: **WEEKLY** = mỗi tuần (cho dự án ngắn/quan trọng). **MONTHLY** = mỗi tháng (chuẩn). **MILESTONE** = khi đạt milestone quan trọng. **AD_HOC** = khi có sự kiện đặc biệt.",
        'q_en': "When to create a Progress Report?",
        'a_en': "Depends on type: WEEKLY (short/critical projects), MONTHLY (standard), MILESTONE (key milestone reached), AD_HOC (special events).",
        'roles': ['pm'],
        'tags': ['report', 'frequency', 'tần suất', 'khi nào'],
    },
    {
        'q_vi': "CONDITIONAL status của QC nghĩa là gì?",
        'a_vi': "CONDITIONAL = đạt có điều kiện. Một số item passed nhưng có lưu ý cần follow-up. Ghi rõ trong Remarks và set Next Action + Retest Date nếu cần.",
        'q_en': "What does QC CONDITIONAL status mean?",
        'a_en': "CONDITIONAL = passed with conditions. Some items need follow-up. Document in Remarks, set Next Action + Retest Date.",
        'roles': ['pm', 'engineer'],
        'tags': ['conditional', 'qc', 'status', 'điều kiện'],
    },
    {
        'q_vi': "Pass Rate tính thế nào?",
        'a_vi': "**Pass Rate = Passed / Total Items × 100%**. VD: 45 passed / 50 total = 90%. Tự động tính khi nhập kết quả.",
        'q_en': "How is Pass Rate calculated?",
        'a_en': "**Pass Rate = Passed / Total × 100%**. E.g. 45/50 = 90%. Auto-calculated when results entered.",
        'roles': ['pm', 'engineer'],
        'tags': ['pass rate', 'calculate', 'tính'],
    },
    {
        'q_vi': "Customer Sign-off khác gì nội bộ?",
        'a_vi': "QC status (PASSED/FAILED) là đánh giá nội bộ của team. **Customer Signed Off** là xác nhận từ khách hàng rằng họ chấp nhận kết quả. Cả hai đều cần cho handover.",
        'q_en': "What's the difference between QC status and Customer Sign-off?",
        'a_en': "QC status is internal team assessment. Customer Sign-off is client's acceptance confirmation. Both needed for handover.",
        'roles': ['pm'],
        'tags': ['customer', 'sign-off', 'ký', 'nghiệm thu'],
    },
]

_WORKFLOWS: List[Dict] = [
    {
        'icon': '📊', 'role': 'pm',
        'tags': ['report', 'create', 'weekly', 'tạo', 'báo cáo'],
        'title_vi': 'Tạo & Submit Progress Report',
        'title_en': 'Create & Submit Progress Report',
        'steps_vi': [
            "Mở **📊 Progress & Quality** → tab **📊 Progress Reports**",
            "Click **➕ New Report**",
            "Chọn Type (WEEKLY/MONTHLY) + Report Date + Period",
            "Set **Overall RAG**: 🟢/🟡/🔴 dựa trên tình hình thực tế",
            "Set Schedule / Cost / Quality status",
            "Điền 4 phần narrative: Summary, Accomplishments, Planned, Blockers",
            "Submit → Report ở trạng thái DRAFT",
            "Khi sẵn sàng: Edit → set status = SUBMITTED",
            "Sau khi PM review: set status = REVIEWED + set Reviewed By",
        ],
        'steps_en': [
            "Open **📊 Progress & Quality** → **📊 Progress Reports** tab",
            "Click **➕ New Report**",
            "Select Type, Report Date, Period",
            "Set Overall RAG based on actual status",
            "Set Schedule / Cost / Quality indicators",
            "Fill narrative: Summary, Accomplishments, Planned, Blockers",
            "Submit → starts as DRAFT",
            "When ready: Edit → set SUBMITTED",
            "After review: set REVIEWED + Reviewed By",
        ],
    },
    {
        'icon': '✅', 'role': 'pm',
        'tags': ['quality', 'qc', 'fat', 'inspection', 'kiểm tra'],
        'title_vi': 'Quy trình Quality Checklist (FAT/SAT)',
        'title_en': 'Quality Checklist Process (FAT/SAT)',
        'steps_vi': [
            "PM/Lead tạo QC: **➕ New Checklist** → chọn Type, Inspector, Date, Location",
            "Link với Milestone nếu có",
            "QC ở trạng thái **PLANNED**",
            "Inspector thực hiện kiểm tra → Edit QC → set **IN_PROGRESS**",
            "Nhập kết quả: Total Items, Passed, Failed",
            "Set status: **PASSED** / **FAILED** / **CONDITIONAL**",
            "Nếu FAILED: nhập Remarks + Next Action + Retest Date",
            "Đính kèm ảnh, biên bản kiểm tra",
            "PM review kết quả → set **Customer Sign-off** khi khách ký",
        ],
        'steps_en': [
            "PM/Lead creates QC: ➕ New Checklist → Type, Inspector, Date, Location",
            "Link to Milestone if applicable",
            "QC starts as PLANNED",
            "Inspector performs check → Edit → set IN_PROGRESS",
            "Enter results: Total, Passed, Failed",
            "Set status: PASSED / FAILED / CONDITIONAL",
            "If FAILED: Remarks + Next Action + Retest Date",
            "Attach photos, inspection reports",
            "PM reviews → set Customer Sign-off when client signs",
        ],
    },
]

_CONTEXT_TIPS = {
    'vi': {
        'qc_failed':  "🔴 **Lưu ý:** {n} QC checklist bị FAILED — cần review và lên kế hoạch retest.",
        'upcoming':   "📅 **Sắp tới:** {n} đợt kiểm tra trong 14 ngày tới.",
        'draft':      "📝 **Nhắc nhở:** {n} report đang DRAFT — submit khi sẵn sàng.",
        'no_sign':    "⏳ **Pending:** {n} QC passed nhưng chưa có customer sign-off.",
    },
    'en': {
        'qc_failed':  "🔴 **Note:** {n} QC checklist(s) FAILED — review and plan retest.",
        'upcoming':   "📅 **Coming up:** {n} inspection(s) in the next 14 days.",
        'draft':      "📝 **Reminder:** {n} report(s) in DRAFT — submit when ready.",
        'no_sign':    "⏳ **Pending:** {n} QC passed but awaiting customer sign-off.",
    },
}


def get_progress_context_tips(kpis: dict, perms: dict, lang: str = 'vi') -> List[str]:
    tips = []
    t = _CONTEXT_TIPS.get(lang, _CONTEXT_TIPS['en'])
    if perms.get('tier') in ('manager', 'lead'):
        if kpis.get('qc_failed', 0) > 0:
            tips.append(t['qc_failed'].format(n=kpis['qc_failed']))
        if kpis.get('upcoming_insp', 0) > 0:
            tips.append(t['upcoming'].format(n=kpis['upcoming_insp']))
        if kpis.get('rpt_draft', 0) > 0:
            tips.append(t['draft'].format(n=kpis['rpt_draft']))
        if kpis.get('qc_no_sign', 0) > 0:
            tips.append(t['no_sign'].format(n=kpis['qc_no_sign']))
    return tips


def get_progress_guide_sections(tier: str, lang: str = 'vi') -> List[Dict]:
    key_map = {'manager': 'pm', 'lead': 'pm', 'member': 'engineer',
               'restricted': 'engineer', 'viewer': 'engineer'}
    role_key = key_map.get(tier, 'engineer')
    raw = list(_SECTIONS.get(role_key, []))
    raw.extend(_SECTIONS.get('general', []))
    return [{'icon': s['icon'], 'tags': s['tags'],
             'title': _t(s, 'title', lang), 'content': _t(s, 'content', lang)} for s in raw]


def get_progress_faq(tier: str, lang: str = 'vi') -> List[Dict]:
    key_map = {'manager': 'pm', 'lead': 'pm', 'member': 'engineer',
               'restricted': 'engineer', 'viewer': 'engineer'}
    role_key = key_map.get(tier, 'engineer')
    return [{'q': _t(i, 'q', lang), 'a': _t(i, 'a', lang), 'tags': i.get('tags', [])}
            for i in _FAQ if not i.get('roles') or role_key in i['roles']]


def get_progress_workflows(tier: str, lang: str = 'vi') -> List[Dict]:
    key_map = {'manager': 'pm', 'lead': 'pm'}
    role_key = key_map.get(tier)
    if not role_key:
        return []
    return [{'icon': w['icon'], 'title': _t(w, 'title', lang),
             'steps': w.get(f'steps_{lang}', w.get('steps_en', [])), 'tags': w.get('tags', [])}
            for w in _WORKFLOWS if w.get('role') == role_key]
