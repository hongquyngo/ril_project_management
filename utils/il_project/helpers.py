# utils/il_project/helpers.py
"""
Helper constants and functions for IL Project module.

Includes:
- calculate_estimate(): A→F COGS formula
- get_go_no_go(): Go/No-Go threshold logic
- fmt_vnd(), fmt_percent(), pct_change(): formatting helpers
- COGS_LABELS, PHASE_LABELS, STATUS_COLORS: display constants
- EXPENSE_CATEGORIES: dynamic from DB ENUM (fallback to hardcoded)
- get_vendor_companies(): vendors from companies table
- impact_color(), go_no_go_badge(): UI helpers
"""

import re
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# DISPLAY CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

COGS_LABELS: Dict[str, str] = {
    'A': 'A — Equipment Cost',
    'B': 'B — Logistics & Import',
    'C': 'C — Custom Fabrication',
    'D': 'D — Direct Labor',
    'E': 'E — Travel & Site OH',
    'F': 'F — Warranty Reserve',
}

PHASE_LABELS: Dict[str, str] = {
    'PRE_SALES':      'Pre-Sales',
    'DESIGN':         'Design',
    'IMPLEMENTATION': 'Implementation',
    'COMMISSIONING':  'Commissioning',
    'FAT':            'FAT',
    'TRAINING':       'Training',
    'WARRANTY':       'Warranty',
    'SUPPORT':        'Support',
}

STATUS_COLORS: Dict[str, str] = {
    'DRAFT':           '⚪',
    'ESTIMATING':      '🔵',
    'PROPOSAL_SENT':   '📤',
    'GO':              '🟢',
    'CONDITIONAL':     '🟡',
    'NO_GO':           '🔴',
    'CONTRACTED':      '🟢',
    'IN_PROGRESS':     '🔵',
    'COMMISSIONING':   '🔵',
    'COMPLETED':       '✅',
    'WARRANTY':        '🛡️',
    'CLOSED':          '⬛',
    'CANCELLED':       '❌',
}

PRESALES_CATEGORIES_L1: List[str] = [
    'SITE_VISIT', 'PROPOSAL_WRITING', 'MEETING',
    'TRAVEL_STANDARD', 'OTHER',
]

PRESALES_CATEGORIES_L2: List[str] = [
    'POC_EXECUTION', 'WIFI_SURVEY', 'ENGINEERING_STUDY',
    'DEMO_TRANSPORT', 'TRAVEL_SPECIAL', 'CUSTOM_SAMPLE', 'OTHER',
]

EMPLOYEE_LEVELS: List[str] = [
    'JUNIOR_ENGINEER', 'ENGINEER', 'SENIOR_ENGINEER',
    'PROJECT_MANAGER', 'SOLUTION_ARCHITECT', 'OTHER',
]

DEFAULT_RATES_BY_LEVEL: Dict[str, float] = {
    'JUNIOR_ENGINEER':     1_000_000,
    'ENGINEER':            1_200_000,
    'SENIOR_ENGINEER':     1_500_000,
    'PROJECT_MANAGER':     2_100_000,
    'SOLUTION_ARCHITECT':  2_500_000,
    'OTHER':               1_200_000,
}


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMIC ENUM LOADER — EXPENSE_CATEGORIES
# ══════════════════════════════════════════════════════════════════════════════

def _parse_enum_values(column_type: str) -> List[str]:
    """Parse MySQL ENUM string → list of values.
    Input:  "enum('A','B','C')"
    Output: ['A', 'B', 'C']
    """
    return re.findall(r"'([^']+)'", column_type)


def get_enum_values(table_name: str, column_name: str) -> List[str]:
    """
    Đọc ENUM values từ INFORMATION_SCHEMA.
    Tự động sync với DB — không cần sửa code khi thêm/bớt category.
    """
    try:
        from utils.db import execute_query
        rows = execute_query(
            """
            SELECT COLUMN_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME   = :table_name
              AND COLUMN_NAME  = :column_name
            LIMIT 1
            """,
            {"table_name": table_name, "column_name": column_name},
        )
        if rows:
            return _parse_enum_values(rows[0]["COLUMN_TYPE"])
    except Exception as e:
        logger.warning(f"Could not load ENUM from DB ({table_name}.{column_name}): {e}")
    return []


# Fallback nếu DB không khả dụng (local dev, offline)
_EXPENSE_CATEGORIES_FALLBACK: List[str] = [
    'AIRFARE', 'HOTEL', 'MEAL', 'LOCAL_TRANSPORT',
    'EQUIPMENT_TRANSPORT', 'DEMO_TRANSPORT',
    'SITE_RENTAL', 'COMMUNICATION', 'VISA', 'INSURANCE',
    'CONSUMABLES', 'INSTALLATION_SERVICE', 'OTHER',
]


def get_expense_categories() -> List[str]:
    """
    Lấy expense categories từ DB ENUM.
    Fallback sang hardcoded list nếu DB lỗi.
    """
    values = get_enum_values("il_project_expenses", "category")
    if values:
        return values
    logger.warning("Using fallback EXPENSE_CATEGORIES (DB unavailable)")
    return _EXPENSE_CATEGORIES_FALLBACK


# Module-level: load 1 lần per process
EXPENSE_CATEGORIES: List[str] = get_expense_categories()


# ══════════════════════════════════════════════════════════════════════════════
# VENDOR COMPANIES — dynamic from companies table
# ══════════════════════════════════════════════════════════════════════════════

def get_vendor_companies() -> List[Dict]:
    """
    Lấy danh sách companies có type = 'Vendor' từ DB.

    Returns:
        List of dicts: [{'id': 1, 'name': 'ABC Corp', 'code': 'ABC', 'tax_number': '...'}, ...]
    """
    try:
        from utils.db import execute_query
        rows = execute_query(
            """
            SELECT
                c.id,
                COALESCE(c.english_name, c.local_name, c.company_code) AS name,
                c.company_code AS code,
                c.tax_number
            FROM companies c
            JOIN companies_company_types cct ON cct.companies_id = c.id
            JOIN company_types ct            ON ct.id = cct.company_type_id
            WHERE ct.name      = 'Vendor'
              AND ct.delete_flag  = 0
              AND c.delete_flag   = 0
            ORDER BY name
            """,
            {},
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Could not load vendor companies: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════════
# ESTIMATE CALCULATION — A→F Formula
# ══════════════════════════════════════════════════════════════════════════════

def calculate_estimate(
    a_equipment: float,
    alpha: float,
    c_fabrication: float,
    man_days: int,
    man_day_rate: float,
    team_size: float,
    beta: float,
    gamma: float,
    sales_value: float,
    b_override: Optional[float] = None,
    d_override: Optional[float] = None,
    e_override: Optional[float] = None,
    f_override: Optional[float] = None,
) -> Dict[str, float]:
    """
    Calculate COGS estimate using A→F formula.

    Formula:
        B = A × α                   (Logistics & Import)
        D = man_days × rate × team  (Direct Labor)
        E = D × β                   (Travel & Site OH)
        F = (A + C) × γ             (Warranty Reserve)
        Total COGS = A + B + C + D + E + F
        GP = Sales - Total COGS
        GP% = GP / Sales × 100

    Any component can be overridden with a manual value.

    Returns:
        dict with keys: a, b, c, d, e, f, total_cogs, sales, gp, gp_percent
    """
    a = float(a_equipment or 0)
    c = float(c_fabrication or 0)

    b = float(b_override) if b_override is not None else round(a * alpha, 0)
    d = float(d_override) if d_override is not None else round(man_days * man_day_rate * team_size, 0)
    e = float(e_override) if e_override is not None else round(d * beta, 0)
    f = float(f_override) if f_override is not None else round((a + c) * gamma, 0)

    total_cogs = a + b + c + d + e + f
    sales      = float(sales_value or 0)
    gp         = sales - total_cogs
    gp_percent = (gp / sales * 100) if sales > 0 else 0.0

    return {
        'a':          a,
        'b':          b,
        'c':          c,
        'd':          d,
        'e':          e,
        'f':          f,
        'total_cogs': total_cogs,
        'sales':      sales,
        'gp':         gp,
        'gp_percent': gp_percent,
    }


# ══════════════════════════════════════════════════════════════════════════════
# GO / NO-GO LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def get_go_no_go(gp_percent: float, go_threshold: float, conditional_threshold: float) -> str:
    """
    Determine Go/No-Go result based on GP%.

    Args:
        gp_percent:            Calculated GP%
        go_threshold:          Minimum GP% for GO  (e.g. 25.0)
        conditional_threshold: Minimum GP% for CONDITIONAL (e.g. 18.0)

    Returns:
        'GO' | 'CONDITIONAL' | 'NO_GO'
    """
    if gp_percent >= go_threshold:
        return 'GO'
    if gp_percent >= conditional_threshold:
        return 'CONDITIONAL'
    return 'NO_GO'


# ══════════════════════════════════════════════════════════════════════════════
# FORMATTING HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def fmt_vnd(value) -> str:
    """Format number as VND string. Returns '—' for None/zero."""
    if value is None:
        return '—'
    try:
        v = float(value)
        if v == 0:
            return '—'
        return f"{v:,.0f} ₫"
    except (TypeError, ValueError):
        return '—'


def fmt_percent(value) -> str:
    """Format number as percentage string. Returns '—' for None."""
    if value is None:
        return '—'
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return '—'


def pct_change(base: float, actual: float) -> Optional[float]:
    """
    Calculate percentage change from base to actual.

    Returns:
        Float percentage, or None if base is 0.
        Positive = actual > base (cost overrun = unfavorable).
    """
    if not base:
        return None
    return round((actual - base) / abs(base) * 100, 2)


# ══════════════════════════════════════════════════════════════════════════════
# UI HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def impact_color(var_pct) -> str:
    """Return color emoji based on variance %.
    Positive var_pct = actual > estimate = unfavorable (cost overrun).
    """
    if var_pct is None:
        return '⚪'
    if var_pct > 5:
        return '🔴'   # unfavorable — over budget
    if var_pct < -5:
        return '🟢'   # favorable   — under budget
    return '🟡'        # neutral


def go_no_go_badge(result: str) -> str:
    """Return display badge for Go/No-Go result."""
    mapping = {
        'GO':          '✅ GO',
        'CONDITIONAL': '⚠️ CONDITIONAL',
        'NO_GO':       '❌ NO-GO',
    }
    return mapping.get(result, result or '—')