# utils/il_project/wbs_helpers.py
"""
Constants and display helpers for WBS module.
Follows same pattern as helpers.py.
"""

from typing import Dict, List

# ══════════════════════════════════════════════════════════════════════════════
# DISPLAY CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

TASK_STATUS_OPTIONS: List[str] = [
    'NOT_STARTED', 'IN_PROGRESS', 'COMPLETED', 'ON_HOLD', 'BLOCKED', 'CANCELLED',
]

TASK_STATUS_ICONS: Dict[str, str] = {
    'NOT_STARTED': '⚪',
    'IN_PROGRESS': '🔵',
    'COMPLETED':   '✅',
    'ON_HOLD':     '⏸️',
    'BLOCKED':     '🔴',
    'CANCELLED':   '❌',
}

PHASE_STATUS_OPTIONS: List[str] = [
    'NOT_STARTED', 'IN_PROGRESS', 'COMPLETED', 'ON_HOLD', 'CANCELLED',
]

PRIORITY_OPTIONS: List[str] = ['LOW', 'NORMAL', 'HIGH', 'CRITICAL']

PRIORITY_ICONS: Dict[str, str] = {
    'LOW':      '🟢',
    'NORMAL':   '🔵',
    'HIGH':     '🟠',
    'CRITICAL': '🔴',
}

MEMBER_ROLES: List[str] = [
    'PROJECT_MANAGER', 'SOLUTION_ARCHITECT', 'ENGINEER', 'SENIOR_ENGINEER',
    'SITE_ENGINEER', 'FAE', 'SALES', 'SUBCONTRACTOR', 'OTHER',
]

MEMBER_ROLE_LABELS: Dict[str, str] = {
    'PROJECT_MANAGER':    'Project Manager',
    'SOLUTION_ARCHITECT': 'Solution Architect',
    'ENGINEER':           'Engineer',
    'SENIOR_ENGINEER':    'Senior Engineer',
    'SITE_ENGINEER':      'Site Engineer',
    'FAE':                'FAE',
    'SALES':              'Sales',
    'SUBCONTRACTOR':      'Subcontractor',
    'OTHER':              'Other',
}

DEPENDENCY_TYPES: List[str] = ['FS', 'FF', 'SS', 'SF']

DEPENDENCY_LABELS: Dict[str, str] = {
    'FS': 'Finish → Start',
    'FF': 'Finish → Finish',
    'SS': 'Start → Start',
    'SF': 'Start → Finish',
}

# Standard phase templates for quick setup
DEFAULT_PHASE_TEMPLATES: List[Dict] = [
    {'code': 'PRESALES',       'name': 'Pre-Sales / Site Survey',     'weight': 5},
    {'code': 'DESIGN',         'name': 'Design & Engineering',        'weight': 15},
    {'code': 'PROCUREMENT',    'name': 'Procurement',                 'weight': 10},
    {'code': 'IMPLEMENTATION', 'name': 'Implementation / Installation', 'weight': 35},
    {'code': 'COMMISSIONING',  'name': 'Commissioning & FAT',         'weight': 20},
    {'code': 'TRAINING',       'name': 'Training & Handover',         'weight': 10},
    {'code': 'WARRANTY',       'name': 'Warranty Support',            'weight': 5},
]


# ══════════════════════════════════════════════════════════════════════════════
# FORMATTING HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def fmt_status(status: str) -> str:
    """Format task/phase status with icon."""
    icon = TASK_STATUS_ICONS.get(status, '⚪')
    return f"{icon} {status}"


def fmt_priority(priority: str) -> str:
    """Format priority with icon."""
    icon = PRIORITY_ICONS.get(priority, '🔵')
    return f"{icon} {priority}"


def fmt_completion(pct) -> str:
    """Format completion percentage with progress indicator."""
    if pct is None:
        return '—'
    try:
        p = float(pct)
        if p >= 100:
            return '✅ 100%'
        if p >= 75:
            return f'🟢 {p:.0f}%'
        if p >= 50:
            return f'🟡 {p:.0f}%'
        if p > 0:
            return f'🟠 {p:.0f}%'
        return '⚪ 0%'
    except (TypeError, ValueError):
        return '—'


def fmt_hours(hours) -> str:
    """Format hours with 1 decimal."""
    if hours is None:
        return '—'
    try:
        return f"{float(hours):.1f}h"
    except (TypeError, ValueError):
        return '—'


def comment_type_icon(ctype: str) -> str:
    """Icon for comment type."""
    return {
        'COMMENT':         '💬',
        'STATUS_CHANGE':   '🔄',
        'PROGRESS_UPDATE': '📊',
        'BLOCKER':         '🚧',
    }.get(ctype, '💬')
