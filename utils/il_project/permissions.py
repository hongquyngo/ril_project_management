# utils/il_project/permissions.py
"""
Role-Based Access Control (RBAC) for IL Project Management.

Central permission module — all pages import from here.
Pattern: same as WBS module (role matrix per project).

Design:
  - 5 project-level roles: ADMIN > PM > SA > SALES > ENGINEER
  - Permission matrix: {action: {allowed_roles}}
  - get_project_role() queries DB for PM/Sales of specific project
  - can() checks if user's role is in the allowed set
  - Admin = PM trên tất cả dự án (override)

Usage in pages:
    from utils.il_project.permissions import can, get_project_role

    # Check permission (project-scoped)
    if can('estimate.create', project_id=pid, employee_id=eid, is_admin=is_admin):
        show_create_button()

    # Check permission (global scope — no project_id)
    if can('project.create', employee_id=eid, is_admin=is_admin, user_role=user_role):
        show_new_project_button()

    # Backend guard (raises PermissionDenied)
    require_permission('cost.approve', project_id=pid, employee_id=eid, is_admin=is_admin)

Ownership checks:
  Some actions have both "any" and "own" variants:
    - cost.edit_any  → PM can edit any PENDING entry in their project
    - cost.edit_own  → Engineer can edit only their own PENDING entry
  The `can()` function checks role-based permission.
  Ownership (entry.created_by == user_id) is checked by the CALLER.

  Example:
    can_edit = (
        can('cost.edit_any', pid, eid, is_admin)
        or (can('cost.edit_own', pid, eid, is_admin) and log['created_by'] == user_id)
    )
"""

import logging
from typing import Dict, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# ROLE CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

ADMIN    = 'ADMIN'
PM       = 'PM'
SA       = 'SA'         # SA/Senior Engineer — global 'manager' role, not PM of this project
SALES    = 'SALES'
ENGINEER = 'ENGINEER'   # Default — any authenticated employee

ALL_ROLES = {ADMIN, PM, SA, SALES, ENGINEER}

# Numeric rank for comparison (higher = more privileged)
ROLE_RANK: Dict[str, int] = {
    ADMIN:    100,
    PM:        80,
    SA:        60,
    SALES:     40,
    ENGINEER:  20,
}


# ══════════════════════════════════════════════════════════════════════════════
# PERMISSION MATRIX
#
# Format: { 'page.action': {set of roles that can perform it} }
#
# Conventions:
#   - ADMIN is always included (admin = PM on all projects)
#   - PM means "PM of THIS project" (determined by get_project_role)
#   - SA means global 'manager' role but NOT PM of this specific project
#   - Actions ending in _own: caller must ALSO verify entry ownership
#   - Actions ending in _any: role alone is sufficient (within project scope)
# ══════════════════════════════════════════════════════════════════════════════

PERMISSIONS: Dict[str, Set[str]] = {

    # ── IL_1: Projects ────────────────────────────────────────────────────────
    'project.view_list':       {ADMIN, PM, SA, SALES, ENGINEER},  # filtered per role in Phase 2
    'project.view_detail':     {ADMIN, PM, SA, SALES, ENGINEER},  # filtered per role in Phase 2
    'project.create':          {ADMIN, PM, SA},
    'project.edit':            {ADMIN, PM},           # PM of that project
    'project.delete':          {ADMIN},               # Admin only (soft delete)
    'project.milestones':      {ADMIN, PM},           # Add/edit milestones

    # ── IL_2: Estimate GP ─────────────────────────────────────────────────────
    'estimate.view':           {ADMIN, PM, SA, SALES},   # Sales: summary only (GP result)
    'estimate.view_costs':     {ADMIN, PM, SA},           # Vendor cost, GP% detail — sensitive
    'estimate.create':         {ADMIN, PM, SA},
    'estimate.edit':           {ADMIN, PM, SA},
    'estimate.activate':       {ADMIN, PM},
    'estimate.upload':         {ADMIN, PM, SA},

    # ── IL_3: Cost Tracking ───────────────────────────────────────────────────
    'cost.view_overview':      {ADMIN, SA},               # Cross-project dashboard
    'cost.view_project':       {ADMIN, PM, SA, ENGINEER}, # Per-project labor/expenses
    'cost.create_labor':       {ADMIN, PM, SA, ENGINEER},
    'cost.create_expense':     {ADMIN, PM, SA, ENGINEER},
    'cost.edit_own':           {ADMIN, PM, SA, ENGINEER}, # Caller checks entry ownership
    'cost.edit_any':           {ADMIN, PM},               # Edit any PENDING in project
    'cost.approve':            {ADMIN, PM},               # PM of THAT project, not global
    'cost.bulk_approve':       {ADMIN, PM},
    'cost.presales_decide':    {ADMIN, PM},               # WIN/LOSE allocation

    # ── IL_4: COGS Dashboard ──────────────────────────────────────────────────
    'cogs.view_portfolio':     {ADMIN, SA},               # All-projects overview
    'cogs.view_actual':        {ADMIN, PM, SA},
    'cogs.sync':               {ADMIN, PM},
    'cogs.manual_entry':       {ADMIN, PM},
    'cogs.finalize':           {ADMIN},                   # Irreversible — admin only
    'cogs.variance_view':      {ADMIN, PM, SA},
    'cogs.variance_generate':  {ADMIN, PM},
    'cogs.benchmark_add':      {ADMIN, PM, SA},

    # ── IL_5: Purchase Request ────────────────────────────────────────────────
    'pr.view_list':            {ADMIN, PM, SA, ENGINEER}, # Engineer: own PRs only
    'pr.view_detail':          {ADMIN, PM, SA, ENGINEER}, # Engineer: own PRs only
    'pr.create':               {ADMIN, PM},
    'pr.edit_draft':           {ADMIN, PM, ENGINEER},     # Engineer: own PR + DRAFT only
    'pr.submit':               {ADMIN, PM},
    'pr.create_po':            {ADMIN, PM},
    'pr.cancel':               {ADMIN, PM, ENGINEER},     # Engineer: own PR only
    'pr.reduce':               {ADMIN, PM},
}


# ══════════════════════════════════════════════════════════════════════════════
# ROLE RESOLUTION
# ══════════════════════════════════════════════════════════════════════════════

def _query_project_role(project_id: int, employee_id: int) -> Optional[str]:
    """
    Query DB for the employee's relationship to a specific project.

    Returns:
        'PM'    if pm_employee_id = employee_id
        'SALES' if sales_employee_id = employee_id
        None    if no direct relationship
    """
    try:
        from ..db import execute_query
        rows = execute_query("""
            SELECT pm_employee_id, sales_employee_id
            FROM il_projects
            WHERE id = :pid AND delete_flag = 0
            LIMIT 1
        """, {'pid': project_id})

        if not rows:
            return None

        row = rows[0]
        if row.get('pm_employee_id') == employee_id:
            return PM
        if row.get('sales_employee_id') == employee_id:
            return SALES
        return None

    except Exception as e:
        logger.error(f"_query_project_role failed (project={project_id}, emp={employee_id}): {e}")
        return None


# In-process cache: (project_id, employee_id) → role string
# Cleared per Streamlit rerun (module-level dict persists within a single run)
_role_cache: Dict[Tuple[int, int], str] = {}


def clear_role_cache():
    """Clear the role cache. Call when project assignments change."""
    _role_cache.clear()


def get_project_role(
    project_id: Optional[int],
    employee_id: int,
    is_admin: bool = False,
    user_role: str = '',
) -> str:
    """
    Determine the user's effective role on a specific project.

    Resolution order (first match wins):
      1. is_admin=True  →  ADMIN
      2. PM of project  →  PM     (from il_projects.pm_employee_id)
      3. Sales of project → SALES (from il_projects.sales_employee_id)
      4. user_role='manager' or 'admin'  →  SA  (senior, but not PM of this project)
      5. Default  →  ENGINEER

    Args:
        project_id:   Specific project (None for global-scope actions)
        employee_id:  employees.id of the current user
        is_admin:     True if user has Keycloak admin role
        user_role:    From st.session_state['user_role'] — 'admin', 'manager', etc.

    Returns:
        One of: ADMIN, PM, SA, SALES, ENGINEER
    """
    # 1. Admin override
    if is_admin:
        return ADMIN

    # Global scope (no project) — use session role only
    if project_id is None:
        if user_role in ('admin',):
            return ADMIN
        if user_role in ('manager',):
            return SA
        return ENGINEER

    # 2–3. Check project-specific role (PM / Sales)
    cache_key = (project_id, employee_id)
    if cache_key not in _role_cache:
        db_role = _query_project_role(project_id, employee_id)
        if db_role:
            _role_cache[cache_key] = db_role
        elif user_role in ('manager',):
            _role_cache[cache_key] = SA
        else:
            _role_cache[cache_key] = ENGINEER

    return _role_cache[cache_key]


# ══════════════════════════════════════════════════════════════════════════════
# PERMISSION CHECK — Main API
# ══════════════════════════════════════════════════════════════════════════════

def can(
    action: str,
    project_id: Optional[int] = None,
    employee_id: Optional[int] = None,
    is_admin: bool = False,
    user_role: str = '',
) -> bool:
    """
    Check if the current user can perform an action.

    This is the primary permission check used by all IL pages.

    Args:
        action:       Permission key, e.g. 'estimate.create', 'cost.approve'
        project_id:   Project scope (None for global actions like 'project.create')
        employee_id:  employees.id of the current user
        is_admin:     From auth.is_admin()
        user_role:    From st.session_state['user_role']

    Returns:
        True if the action is allowed.

    Note:
        For actions with _own suffix (cost.edit_own, pr.edit_draft for ENGINEER),
        the caller MUST also verify entry ownership separately.
        This function only checks role-based permission.

    Example:
        # Simple check
        if can('estimate.create', project_id=42, employee_id=7, is_admin=False):
            st.button("New Estimate")

        # With ownership check
        can_edit = (
            can('cost.edit_any', pid, eid, is_admin=ia)
            or (can('cost.edit_own', pid, eid, is_admin=ia) and log['created_by'] == uid)
        )
    """
    # Validate action exists
    allowed_roles = PERMISSIONS.get(action)
    if allowed_roles is None:
        logger.warning(f"Unknown permission action: '{action}'")
        return False

    # Admin shortcut — always allowed
    if is_admin:
        return True

    # Determine role
    if employee_id is None:
        logger.warning(f"can() called without employee_id for action '{action}'")
        return False

    role = get_project_role(project_id, employee_id, is_admin, user_role)
    return role in allowed_roles


def require_permission(
    action: str,
    project_id: Optional[int] = None,
    employee_id: Optional[int] = None,
    is_admin: bool = False,
    user_role: str = '',
) -> None:
    """
    Assert that the user has permission. Raises PermissionDenied if not.

    Use in backend functions (queries.py, pr_queries.py) to enforce
    server-side permission checks.

    Example:
        def approve_labor_log(log_id, approved_by, project_id, is_admin=False):
            require_permission('cost.approve', project_id, approved_by, is_admin)
            # ... proceed with approval
    """
    if not can(action, project_id, employee_id, is_admin, user_role):
        role = get_project_role(project_id, employee_id, is_admin, user_role)
        raise PermissionDenied(
            f"Permission denied: '{action}' requires "
            f"{PERMISSIONS.get(action, set())} but user has role '{role}' "
            f"(employee={employee_id}, project={project_id})"
        )


class PermissionDenied(Exception):
    """Raised when a user lacks permission for an action."""
    pass


# ══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE HELPERS — for common page-level patterns
# ══════════════════════════════════════════════════════════════════════════════

def is_pm_of_project(project_id: int, employee_id: int, is_admin: bool = False) -> bool:
    """
    Check if user is PM of a specific project (or Admin).
    Replaces the scattered `is_pm = user_role in ('admin', 'manager')` pattern.

    This is the CORRECT project-scoped PM check.
    The old global `is_pm` pattern was wrong — it allowed any manager
    to approve costs on projects they don't manage.
    """
    if is_admin:
        return True
    role = get_project_role(project_id, employee_id, is_admin=False)
    return role == PM


def get_role_display(role: str) -> str:
    """Human-readable role name for UI display."""
    return {
        ADMIN:    '🔑 Admin',
        PM:       '📋 Project Manager',
        SA:       '👔 SA / Senior',
        SALES:    '💼 Sales',
        ENGINEER: '🔧 Engineer',
    }.get(role, role)


def get_role_badge(role: str) -> str:
    """Short badge for inline display."""
    return {
        ADMIN:    '🔑 ADMIN',
        PM:       '📋 PM',
        SA:       '👔 SA',
        SALES:    '💼 SALES',
        ENGINEER: '🔧 ENG',
    }.get(role, role)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONTEXT — bundles session state for convenience
# ══════════════════════════════════════════════════════════════════════════════

class PermissionContext:
    """
    Bundles user identity for permission checks.
    Create once at page top, reuse throughout.

    Eliminates repetitive parameter passing:
        # Before (verbose):
        if can('cost.approve', pid, emp_id, is_admin, user_role): ...

        # After (clean):
        ctx = PermissionContext(emp_id, is_admin, user_role)
        if ctx.can('cost.approve', pid): ...

    Usage:
        from utils.il_project.permissions import PermissionContext

        ctx = PermissionContext(
            employee_id=st.session_state.get('employee_id'),
            is_admin=auth.is_admin(),
            user_role=st.session_state.get('user_role', ''),
        )

        # Project-scoped check
        if ctx.can('estimate.create', project_id):
            st.button("New Estimate")

        # Global check
        if ctx.can('project.create'):
            st.button("New Project")

        # Get role for display
        role = ctx.role(project_id)
        st.caption(f"Your role: {get_role_display(role)}")
    """

    __slots__ = ('employee_id', 'is_admin', 'user_role')

    def __init__(self, employee_id: int, is_admin: bool = False, user_role: str = ''):
        self.employee_id = employee_id
        self.is_admin    = is_admin
        self.user_role   = user_role

    def role(self, project_id: Optional[int] = None) -> str:
        """Get user's role on a project."""
        return get_project_role(project_id, self.employee_id, self.is_admin, self.user_role)

    def can(self, action: str, project_id: Optional[int] = None) -> bool:
        """Check permission."""
        return can(action, project_id, self.employee_id, self.is_admin, self.user_role)

    def require(self, action: str, project_id: Optional[int] = None) -> None:
        """Assert permission (raises PermissionDenied)."""
        return require_permission(action, project_id, self.employee_id, self.is_admin, self.user_role)

    def __repr__(self) -> str:
        return (
            f"PermissionContext(employee_id={self.employee_id}, "
            f"is_admin={self.is_admin}, user_role='{self.user_role}')"
        )


# ══════════════════════════════════════════════════════════════════════════════
# PERMISSION MATRIX DISPLAY — for Help page / debugging
# ══════════════════════════════════════════════════════════════════════════════

def get_permission_matrix() -> list:
    """
    Return the permission matrix as a list of dicts for display.
    Suitable for pd.DataFrame() → st.dataframe().

    Returns:
        [{'action': 'project.create', 'ADMIN': '✅', 'PM': '✅', ...}, ...]
    """
    display_roles = [ADMIN, PM, SA, SALES, ENGINEER]
    rows = []
    for action in sorted(PERMISSIONS.keys()):
        allowed = PERMISSIONS[action]
        row = {'Khả năng': action}
        for role in display_roles:
            row[role] = '✅' if role in allowed else '—'
        rows.append(row)
    return rows


def get_permission_matrix_by_page() -> Dict[str, list]:
    """
    Return permission matrix grouped by page prefix.

    Returns:
        {
            'project': [{'action': 'view_list', 'ADMIN': '✅', ...}, ...],
            'estimate': [...],
            ...
        }
    """
    display_roles = [ADMIN, PM, SA, SALES, ENGINEER]
    pages: Dict[str, list] = {}

    for action in sorted(PERMISSIONS.keys()):
        prefix, _, short = action.partition('.')
        allowed = PERMISSIONS[action]
        row = {'Khả năng': short}
        for role in display_roles:
            row[role] = '✅' if role in allowed else '—'
        pages.setdefault(prefix, []).append(row)

    return pages


# ══════════════════════════════════════════════════════════════════════════════
# ACTION LABELS — Vietnamese display names for permission matrix UI
# ══════════════════════════════════════════════════════════════════════════════

ACTION_LABELS: Dict[str, str] = {
    # Projects
    'project.view_list':       'Xem danh sách dự án',
    'project.view_detail':     'Xem chi tiết dự án',
    'project.create':          'Tạo dự án mới',
    'project.edit':            'Sửa dự án',
    'project.delete':          'Xóa dự án',
    'project.milestones':      'Quản lý milestones',

    # Estimates
    'estimate.view':           'Xem estimate (tổng quan)',
    'estimate.view_costs':     'Xem vendor cost / GP%',
    'estimate.create':         'Tạo estimate mới',
    'estimate.edit':           'Sửa estimate',
    'estimate.activate':       'Activate estimate',
    'estimate.upload':         'Upload tài liệu',

    # Cost Tracking
    'cost.view_overview':      'Xem tổng quan (All Projects)',
    'cost.view_project':       'Xem labor/expenses dự án',
    'cost.create_labor':       'Tạo labor log',
    'cost.create_expense':     'Tạo expense',
    'cost.edit_own':           'Sửa entry của mình (PENDING)',
    'cost.edit_any':           'Sửa mọi entry (PENDING)',
    'cost.approve':            'Phê duyệt labor/expense',
    'cost.bulk_approve':       'Phê duyệt hàng loạt',
    'cost.presales_decide':    'Phân bổ pre-sales (WIN/LOSE)',

    # COGS Dashboard
    'cogs.view_portfolio':     'Xem portfolio (All Projects)',
    'cogs.view_actual':        'Xem Actual COGS',
    'cogs.sync':               'Sync COGS từ timesheets',
    'cogs.manual_entry':       'Nhập thủ công (A/B/C/F)',
    'cogs.finalize':           'Finalize COGS (không thể undo)',
    'cogs.variance_view':      'Xem Variance Analysis',
    'cogs.variance_generate':  'Generate All Variance',
    'cogs.benchmark_add':      'Thêm benchmark',

    # Purchase Request
    'pr.view_list':            'Xem danh sách PR',
    'pr.view_detail':          'Xem chi tiết PR',
    'pr.create':               'Tạo Purchase Request',
    'pr.edit_draft':           'Sửa PR (DRAFT)',
    'pr.submit':               'Submit PR',
    'pr.create_po':            'Tạo Purchase Order',
    'pr.cancel':               'Hủy PR',
    'pr.reduce':               'Giảm scope PR (approved)',
}
