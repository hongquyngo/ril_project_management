# utils/il_project/team_guide.py
"""
User Guide content for Team page (Page 7).
Bilingual VI/EN. Role-aware sections, FAQ, workflows, context tips.
"""

from typing import Dict, List
from .wbs_guide_common import _t

# ══════════════════════════════════════════════════════════════════════════════
# TEAM PAGE (Page 7) — Separate content set
# ══════════════════════════════════════════════════════════════════════════════

_TEAM_SECTIONS: Dict[str, List[Dict]] = {
    'pm': [
        {
            'icon': '📋',
            'tags': ['roster', 'team', 'member', 'add', 'thành viên', 'danh sách'],
            'title_vi': 'Quản lý Team Roster',
            'title_en': 'Managing Team Roster',
            'content_vi': """
**Thêm thành viên:**
1. Click **➕ Add Member** → chọn Employee, Role, Allocation %
2. Set **Daily Rate** (VND/ngày) → dùng tính chi phí
3. Thành viên mới nhận email thông báo tự động

**Bảng Roster enriched (thông tin bổ sung):**
| Cột | Ý nghĩa |
|-----|---------|
| **Tasks** | Số task active (đã done) trên project này |
| **Overdue** | ⏰ số task quá hạn của member |
| **Avg %** | Trung bình completion % các task |
| **Hours** | Actual / Estimated hours |
| **Rate** | Daily rate (chỉ PM thấy) |

**Sửa / Xóa:**
- Chọn member → **✏️ Edit** để đổi role, allocation, rate
- **🗑 Remove** có confirm dialog (tránh xóa nhầm)
- Remove = soft-delete, không mất dữ liệu

**⚠️ Team Alerts (đầu trang):**
- ⏰ Member có task quá hạn
- 💤 Member idle (0 task active) → cân nhắc gán việc
- ⚪ Member inactive vẫn trên roster → cân nhắc remove
- 🔴 Thiếu PM → cần assign role PM
""",
            'content_en': """
**Adding members:** ➕ Add Member → select Employee, Role, Allocation %, Daily Rate.
Auto-email sent to new member.

**Enriched roster columns:** Tasks (active/done), Overdue count, Avg completion %, Hours (actual/est), Rate (PM only).

**Team Alerts:** ⏰ members with overdue tasks, 💤 idle (0 tasks), ⚪ inactive on roster, 🔴 no PM.
""",
        },
        {
            'icon': '📊',
            'tags': ['workload', 'matrix', 'allocation', 'over', 'phân bổ', 'quá tải'],
            'title_vi': 'Workload Matrix — Phân bổ nguồn lực',
            'title_en': 'Workload Matrix — Resource Allocation',
            'content_vi': """
**Ma trận phân bổ** hiện tất cả member × tất cả dự án đang active:

```
Tên       │ Role │ DỰ ÁN A │ DỰ ÁN B │ TỔNG  │ Status
Quý       │ PM   │  100%   │    —    │ 100%  │ 🟢 OK
Hiệp      │ Eng  │  100%   │   50%  │ 150%  │ 🔴 Over
```

**Ý nghĩa status:**
| Status | Tổng Allocation | Hành động |
|--------|----------------|-----------|
| 🟢 OK | ≤ 80% | Bình thường, có thể nhận thêm việc |
| 🟡 Near | 81–100% | Gần tới hạn, cân nhắc khi gán thêm |
| 🔴 Over | > 100% | Quá tải! Cần giảm allocation hoặc điều chỉnh lịch |

**Khi có member 🔴 Over-allocated:**
1. Xem họ đang ở những project nào
2. Giảm allocation % trên project ít ưu tiên
3. Hoặc điều chỉnh timeline để không overlap
4. Hoặc reassign một số task cho người khác
""",
            'content_en': """
**Matrix view** shows all members × all active projects with allocation %.

**Status:** 🟢 OK (≤80%) | 🟡 Near (81-100%) | 🔴 Over (>100%)

**When over-allocated:** Reduce allocation on lower-priority projects, adjust timelines, or reassign tasks.
""",
        },
        {
            'icon': '💰',
            'tags': ['cost', 'budget', 'rate', 'monthly', 'chi phí', 'ngân sách'],
            'title_vi': 'Chi phí Team (Cost Summary)',
            'title_en': 'Cost Summary',
            'content_vi': """
**Tab Cost Summary** hiện ước tính chi phí team theo role:

**Công thức:**
```
Chi phí/tháng = Daily Rate × (Allocation% / 100) × 22 ngày làm việc
```

**Ví dụ:**
| Role | Members | Avg Rate | Alloc | Est./tháng |
|------|---------|----------|-------|------------|
| PM | 1 | 2.0M | 100% | 44.0M |
| Engineer | 2 | 1.2M | 180% | 47.5M |

**So sánh với contract:**
- Hệ thống tự tính "team cost covers X months of contract value"
- Nếu X quá nhỏ → chi phí team quá cao so với doanh thu
- Cân nhắc: giảm allocation, thay đổi team composition

**Lưu ý:** Chỉ PM thấy tab này. Daily rate là thông tin nhạy cảm.
""",
            'content_en': """
**Formula:** Monthly cost = Daily Rate × Allocation% × 22 working days.
Compares total team cost against contract value. PM-only tab — rates are sensitive data.
""",
        },
    ],

    'lead': [
        {
            'icon': '👁️',
            'tags': ['view', 'roster', 'workload', 'xem', 'phân bổ'],
            'title_vi': 'Xem Team & Workload của bạn',
            'title_en': 'Viewing Team & Your Workload',
            'content_vi': """
**Với role Lead (SA / Senior Engineer), bạn có thể:**
- ✅ Xem danh sách team (tên, role, allocation, task count)
- ✅ Xem Workload Matrix (phân bổ tất cả member)
- ✅ Xem workload chi tiết của chính mình
- ❌ Không thấy daily rate, email, notes
- ❌ Không thể Add/Edit/Remove member

**Workload Matrix:**
- Kiểm tra allocation của bạn trên tất cả dự án
- Nếu bạn thấy tổng > 100% → báo PM để điều chỉnh

**Cần thay đổi team?** Liên hệ PM.
""",
            'content_en': """
**As Lead (SA/Senior), you can:** view roster (no rates/emails), view workload matrix, view own workload.
**Cannot:** add/edit/remove members, view rates.
Contact PM for team changes.
""",
        },
    ],

    'member': [
        {
            'icon': '👁️',
            'tags': ['view', 'team', 'xem'],
            'title_vi': 'Xem thông tin Team',
            'title_en': 'Viewing Team Info',
            'content_vi': """
**Với role Member (Engineer/FAE), bạn có thể:**
- ✅ Xem danh sách team (tên, role, allocation)
- ❌ Không thấy daily rate, email, chi tiết workload người khác
- ❌ Không thể thay đổi team

**Cần xem workload của mình?**
Chọn tên mình trong bảng → click **📊 Workload**.

**Cần thay đổi?** Liên hệ PM.
""",
            'content_en': """
**As Member, you can:** view roster (name, role, allocation only).
**Cannot:** see rates/emails, modify team. Select yourself → 📊 Workload to see own allocation.
""",
        },
    ],

    'general': [
        {
            'icon': '🔐',
            'tags': ['role', 'permission', 'access', 'quyền', 'phân quyền'],
            'title_vi': 'Phân quyền trên trang Team',
            'title_en': 'Team Page Permissions',
            'content_vi': """
| Thao tác | PM | SA/Senior | Engineer | Sales | Subcontractor |
|----------|:--:|:---------:|:--------:|:-----:|:-------------:|
| Xem roster | ✅ | ✅ | ✅ | ❌ | ❌ |
| Xem email, rate | ✅ | ❌ | ❌ | ❌ | ❌ |
| Xem task count, overdue | ✅ | ✅ | ❌ | ❌ | ❌ |
| Workload Matrix | ✅ | ✅ | ❌ | ❌ | ❌ |
| Cost Summary | ✅ | ❌ | ❌ | ❌ | ❌ |
| Add/Edit/Remove | ✅ | ❌ | ❌ | ❌ | ❌ |
| Xem workload bất kỳ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Xem workload mình | ✅ | ✅ | ✅ | ❌ | ❌ |

**Sales** và **Subcontractor** không truy cập được trang này.
""",
            'content_en': """
| Action | PM | SA/Senior | Engineer | Sales | Subcontractor |
|--------|:--:|:---------:|:--------:|:-----:|:-------------:|
| View roster | ✅ | ✅ | ✅ | ❌ | ❌ |
| View rates/emails | ✅ | ❌ | ❌ | ❌ | ❌ |
| Workload Matrix | ✅ | ✅ | ❌ | ❌ | ❌ |
| Cost Summary | ✅ | ❌ | ❌ | ❌ | ❌ |
| Add/Edit/Remove | ✅ | ❌ | ❌ | ❌ | ❌ |

Sales and Subcontractor cannot access this page.
""",
        },
        {
            'icon': '📊',
            'tags': ['allocation', 'percent', 'meaning', 'phân bổ', 'ý nghĩa'],
            'title_vi': 'Ý nghĩa Allocation %',
            'title_en': 'Allocation % Explained',
            'content_vi': """
**Allocation %** = phần trăm thời gian member dành cho dự án này.

| Giá trị | Ý nghĩa |
|---------|---------|
| **100%** | Full-time trên dự án |
| **50%** | Nửa thời gian (chia sẻ với dự án khác) |
| **150%** | Tăng ca / sprint ngắn hạn |
| **0%** | Không hoạt động (nên set inactive hoặc remove) |

**Tổng allocation của 1 người:**
- ≤ 100%: bình thường
- 101–130%: chấp nhận được ngắn hạn
- > 130%: rủi ro burnout, chất lượng giảm

**Best practice:**
- Set đúng allocation khi add member
- Review Workload Matrix định kỳ (2 tuần/lần)
- Điều chỉnh khi dự án mới bắt đầu hoặc kết thúc
""",
            'content_en': """
**Allocation %** = percentage of time a member dedicates to this project.
100% = full-time, 50% = shared, >100% = overtime/short sprint.

**Total across projects:** ≤100% normal, 101-130% acceptable short-term, >130% burnout risk.
Review workload matrix every 2 weeks.
""",
        },
    ],
}


_TEAM_FAQ: List[Dict] = [
    {
        'q_vi': "Tại sao tôi không thấy Daily Rate?",
        'a_vi': "Daily Rate là thông tin nhạy cảm, chỉ PM mới thấy. Nếu bạn cần biết rate cho mục đích lập budget, liên hệ PM.",
        'q_en': "Why can't I see Daily Rate?",
        'a_en': "Daily Rate is sensitive data, visible to PM only. Contact PM for budget-related inquiries.",
        'roles': ['engineer', 'lead'],
        'tags': ['rate', 'cost', 'hidden', 'lương', 'ẩn'],
    },
    {
        'q_vi': "Tại sao tôi không thể Add/Remove member?",
        'a_vi': "Chỉ PM mới có quyền thay đổi team composition. Liên hệ PM nếu cần thêm hoặc bớt thành viên.",
        'q_en': "Why can't I add or remove members?",
        'a_en': "Only PM can modify team composition. Contact PM for team changes.",
        'roles': ['engineer', 'lead'],
        'tags': ['add', 'remove', 'permission', 'quyền', 'thêm', 'xóa'],
    },
    {
        'q_vi': "Over-allocated nghĩa là gì?",
        'a_vi': "Tổng allocation % của 1 người trên tất cả dự án > 100%. Nghĩa là họ đang bị gán nhiều hơn thời gian full-time. Cần giảm allocation hoặc điều chỉnh lịch.",
        'q_en': "What does over-allocated mean?",
        'a_en': "Total allocation across all projects > 100%. The person is assigned more than full-time capacity. Reduce allocation or adjust schedules.",
        'roles': ['pm', 'lead'],
        'tags': ['over', 'allocation', 'quá tải', 'phân bổ'],
    },
    {
        'q_vi': "Xóa member thì task của họ sao?",
        'a_vi': "Remove member chỉ xóa khỏi team roster (soft-delete). Task vẫn giữ nguyên assignee. PM nên reassign task trước khi remove member.",
        'q_en': "What happens to tasks when a member is removed?",
        'a_en': "Removing a member only removes them from the roster (soft-delete). Tasks keep their assignee. PM should reassign tasks before removing.",
        'roles': ['pm'],
        'tags': ['remove', 'task', 'xóa', 'gán'],
    },
    {
        'q_vi': "Chi phí/tháng tính như thế nào?",
        'a_vi': "**Daily Rate × (Allocation% / 100) × 22 ngày**. VD: Rate 1.2M, Allocation 100% → 1.2M × 1.0 × 22 = 26.4M/tháng.",
        'q_en': "How is monthly cost calculated?",
        'a_en': "**Daily Rate × (Allocation% / 100) × 22 days**. E.g. Rate 1.2M, 100% → 1.2M × 1.0 × 22 = 26.4M/month.",
        'roles': ['pm'],
        'tags': ['cost', 'calculate', 'monthly', 'chi phí', 'tính'],
    },
    {
        'q_vi': "Tại sao Subcontractor không vào được trang Team?",
        'a_vi': "Subcontractor bị giới hạn quyền xem — không thấy team structure, rate, allocation. Họ chỉ thấy task được gán trên trang WBS.",
        'q_en': "Why can't Subcontractors access Team page?",
        'a_en': "Subcontractors have restricted access — no visibility into team structure, rates, or allocation. They only see assigned tasks on WBS page.",
        'roles': ['pm'],
        'tags': ['subcontractor', 'restricted', 'access', 'bảo mật'],
    },
]


_TEAM_WORKFLOWS: List[Dict] = [
    {
        'icon': '👥', 'role': 'pm',
        'tags': ['onboard', 'add', 'member', 'new', 'thêm', 'mới'],
        'title_vi': 'Thêm thành viên mới vào dự án',
        'title_en': 'Onboard a New Team Member',
        'steps_vi': [
            "Mở trang **👥 Team** → tab **📋 Team Roster**",
            "Click **➕ Add Member**",
            "Chọn Employee từ danh sách",
            "Set **Role** phù hợp (Engineer, FAE, SA...)",
            "Set **Allocation %** (100% = full-time)",
            "Set **Daily Rate** (tự động fill theo role)",
            "Thêm CC nếu muốn notify thêm người → Submit",
            "Member nhận email thông báo với chi tiết dự án",
            "Quay lại **📋 WBS** → gán task cho member mới",
        ],
        'steps_en': [
            "Open **👥 Team** → **📋 Team Roster** tab",
            "Click **➕ Add Member**",
            "Select Employee from list",
            "Set **Role** (Engineer, FAE, SA...)",
            "Set **Allocation %** (100% = full-time)",
            "Set **Daily Rate** (auto-fills by role)",
            "Add CC if needed → Submit",
            "Member receives email with project details",
            "Go to **📋 WBS** → assign tasks to new member",
        ],
    },
    {
        'icon': '📊', 'role': 'pm',
        'tags': ['review', 'workload', 'rebalance', 'kiểm tra', 'cân bằng'],
        'title_vi': 'Review & Cân bằng Workload (2 tuần/lần)',
        'title_en': 'Review & Rebalance Workload (biweekly)',
        'steps_vi': [
            "Mở **👥 Team** → tab **📊 Workload Matrix**",
            "Kiểm tra cột TOTAL: ai > 100%?",
            "Với member 🔴 Over: xem họ ở những project nào",
            "Quyết định: giảm allocation project nào, hoặc reassign task",
            "Quay lại tab **📋 Roster** → ✏️ Edit → điều chỉnh Allocation %",
            "Kiểm tra tab **💰 Cost** → chi phí team có trong budget?",
            "Ghi nhận thay đổi trong Progress Report (page 9)",
        ],
        'steps_en': [
            "Open **👥 Team** → **📊 Workload Matrix** tab",
            "Check TOTAL column: anyone > 100%?",
            "For 🔴 Over members: check which projects",
            "Decide: reduce allocation or reassign tasks",
            "Go to **📋 Roster** → ✏️ Edit → adjust Allocation %",
            "Check **💰 Cost** tab → team cost within budget?",
            "Log changes in Progress Report (page 9)",
        ],
    },
]


_TEAM_CONTEXT_TIPS = {
    'vi': {
        'no_members':  "💡 **Bắt đầu:** Thêm thành viên vào dự án bằng nút ➕ Add Member.",
        'over_alloc':  "🔴 **Cần xử lý:** {n} thành viên bị over-allocated (>100%) — xem Workload Matrix.",
        'idle':        "💤 **Lưu ý:** {n} thành viên chưa có task nào — cân nhắc gán việc.",
        'has_overdue': "⏰ **Cần xử lý:** {n} thành viên có task quá hạn.",
    },
    'en': {
        'no_members':  "💡 **Getting started:** Add team members using ➕ Add Member.",
        'over_alloc':  "🔴 **Action needed:** {n} member(s) over-allocated (>100%) — check Workload Matrix.",
        'idle':        "💤 **Note:** {n} member(s) have no tasks — consider assigning work.",
        'has_overdue': "⏰ **Action needed:** {n} member(s) have overdue tasks.",
    },
}


def get_team_context_tips(enriched_df, perms: dict, lang: str = 'vi') -> List[str]:
    """Context-aware tips for Team page."""
    tips = []
    t = _TEAM_CONTEXT_TIPS.get(lang, _TEAM_CONTEXT_TIPS['en'])

    if perms.get('tier') != 'manager':
        return tips

    if enriched_df.empty:
        tips.append(t['no_members'])
        return tips

    import pandas as pd

    active = enriched_df
    if 'is_active' in enriched_df.columns:
        active = enriched_df[enriched_df['is_active'] == 1]

    if active.empty:
        tips.append(t['no_members'])
        return tips

    # Idle members
    if 'task_count' in active.columns:
        n_idle = int((active['task_count'] == 0).sum())
        if n_idle > 0:
            tips.append(t['idle'].format(n=n_idle))

    # Members with overdue
    if 'overdue_count' in active.columns:
        n_overdue = int((active['overdue_count'] > 0).sum())
        if n_overdue > 0:
            tips.append(t['has_overdue'].format(n=n_overdue))

    return tips


def get_team_guide_sections(tier: str, lang: str = 'vi') -> List[Dict]:
    """Get Team page guide sections for a role tier."""
    role_key_map = {
        'manager': 'pm', 'lead': 'lead',
        'member': 'member', 'restricted': 'member',
        'viewer': 'member',
    }
    role_key = role_key_map.get(tier, 'member')

    raw = list(_TEAM_SECTIONS.get(role_key, []))
    raw.extend(_TEAM_SECTIONS.get('general', []))

    return [
        {'icon': s['icon'], 'tags': s['tags'],
         'title': _t(s, 'title', lang), 'content': _t(s, 'content', lang)}
        for s in raw
    ]


def get_team_faq(tier: str, lang: str = 'vi') -> List[Dict]:
    """Get Team page FAQ for a role tier."""
    role_key_map = {
        'manager': 'pm', 'lead': 'lead',
        'member': 'engineer', 'restricted': 'engineer',
        'viewer': 'engineer',
    }
    role_key = role_key_map.get(tier, 'engineer')

    return [
        {'q': _t(item, 'q', lang), 'a': _t(item, 'a', lang), 'tags': item.get('tags', [])}
        for item in _TEAM_FAQ
        if not item.get('roles') or role_key in item['roles']
    ]


def get_team_workflows(tier: str, lang: str = 'vi') -> List[Dict]:
    """Get Team page workflows for a role tier."""
    role_key_map = {'manager': 'pm', 'lead': 'pm'}
    role_key = role_key_map.get(tier)
    if not role_key:
        return []

    return [
        {'icon': w['icon'], 'title': _t(w, 'title', lang),
         'steps': w.get(f'steps_{lang}', w.get('steps_en', [])), 'tags': w.get('tags', [])}
        for w in _TEAM_WORKFLOWS
        if w.get('role') == role_key
    ]

