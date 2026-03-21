# utils/il_project/wbs_helpers.py
"""
Constants, display helpers, shared UI components, and performance utilities
for WBS module.

v2.0 — Performance optimization:
  - Added log_perf() decorator for query timing
  - Added render_attachments() shared UI component (DRY across pages 8/9)
  - Added cache invalidation helpers (targeted, not global clear)
"""

import time
import functools
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# PERFORMANCE LOGGING
# ══════════════════════════════════════════════════════════════════════════════

def log_perf(func):
    """Decorator: log execution time and row count for DB functions."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        result = func(*args, **kwargs)
        ms = (time.perf_counter() - t0) * 1000
        # Detect row count from result type
        if hasattr(result, '__len__'):
            rows = len(result)
        elif result is None:
            rows = 0
        else:
            rows = '?'
        logger.info(f"[PERF] {func.__name__}: {ms:.0f}ms ({rows} rows)")
        return result
    return wrapper


# ══════════════════════════════════════════════════════════════════════════════
# CACHE INVALIDATION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def invalidate_wbs_cache(project_id: int):
    """
    Increment version counter for WBS bootstrap cache.
    Next call to _cached_wbs_data(project_id, _v=new_version) → cache miss → fresh data.
    Also invalidates My Tasks cache for all employees.
    """
    import streamlit as st
    k = f'_wbs_v_{project_id}'
    st.session_state[k] = st.session_state.get(k, 0) + 1
    # Also bump My Tasks version (cross-project)
    st.session_state['_mytasks_v'] = st.session_state.get('_mytasks_v', 0) + 1


def invalidate_execution_cache(project_id: int):
    """Increment version counter for Execution (Issues/Risks/CO) bootstrap cache."""
    import streamlit as st
    k = f'_exec_v_{project_id}'
    st.session_state[k] = st.session_state.get(k, 0) + 1


def invalidate_progress_cache(project_id: int):
    """Increment version counter for Progress/Quality bootstrap cache."""
    import streamlit as st
    k = f'_prog_v_{project_id}'
    st.session_state[k] = st.session_state.get(k, 0) + 1


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


# ══════════════════════════════════════════════════════════════════════════════
# SHARED UI COMPONENT — Attachments (Pattern A: junction → medias)
# ══════════════════════════════════════════════════════════════════════════════

def render_attachments(entity_type: str, entity_id: int, project_id: int, user_id: str):
    """
    Shared attachment list + upload widget.
    Call inside View dialog, OUTSIDE st.form.

    Used by: Issues (page 8), Risks, Change Orders, Progress Reports,
    Quality Checklists (page 9), and Tasks (page 6 files tab).

    Requires: streamlit, wbs_execution_queries
    """
    import streamlit as st
    from .wbs_execution_queries import (
        get_entity_medias, upload_and_attach, unlink_media, get_attachment_url,
    )

    files = get_entity_medias(entity_type, entity_id)

    if files:
        st.markdown(f"**📎 Attachments ({len(files)})**")
        for f in files:
            fc1, fc2 = st.columns([5, 1])
            url = get_attachment_url(f['s3_key'])
            label = f['file_name'] or 'file'
            desc = f" — {f['description']}" if f.get('description') else ''
            if url:
                fc1.markdown(f"📄 [{label}]({url}){desc}")
            else:
                fc1.caption(f"📄 {label}{desc}")
            if fc2.button("🗑", key=f"_rm_{entity_type}_{f['junction_id']}"):
                unlink_media(entity_type, f['junction_id'])
                st.rerun()
    else:
        st.caption("No files attached.")

    uploaded = st.file_uploader(
        "Attach file", type=['pdf', 'png', 'jpg', 'jpeg', 'xlsx', 'docx'],
        key=f"_upload_{entity_type}_{entity_id}",
    )
    if uploaded:
        desc = st.text_input("Description (optional)", key=f"_desc_{entity_type}_{entity_id}")
        if st.button("📤 Upload", key=f"_do_upload_{entity_type}_{entity_id}"):
            ok = upload_and_attach(
                entity_type, entity_id, project_id,
                uploaded.getvalue(), uploaded.name,
                description=desc.strip() or None, created_by=user_id,
            )
            if ok:
                st.success(f"✅ Attached: {uploaded.name}")
                st.rerun()
            else:
                st.error("Upload failed.")