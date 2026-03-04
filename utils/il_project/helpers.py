# utils/il_project/helpers.py
"""
Pure business logic for IL Project Management.
No DB calls, no Streamlit imports — safe to unit-test.
"""

from typing import Dict, Optional

# ── Display labels ─────────────────────────────────────────────────────────────

COGS_LABELS: Dict[str, str] = {
    'A': 'A. Equipment Purchase',
    'B': 'B. Logistics & Import',
    'C': 'C. Custom Fabrication',
    'D': 'D. Direct Labor',
    'E': 'E. Travel & Site OH',
    'F': 'F. Warranty Reserve',
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
    'DRAFT':          '⚪',
    'ESTIMATING':     '🔵',
    'PROPOSAL_SENT':  '🔵',
    'GO':             '🟢',
    'CONDITIONAL':    '🟡',
    'NO_GO':          '🔴',
    'CONTRACTED':     '🟢',
    'IN_PROGRESS':    '🟢',
    'COMMISSIONING':  '🟣',
    'COMPLETED':      '✅',
    'WARRANTY':       '🟡',
    'CLOSED':         '⚫',
    'CANCELLED':      '🔴',
}

EXPENSE_CATEGORIES = [
    'AIRFARE', 'HOTEL', 'MEAL', 'LOCAL_TRANSPORT', 'EQUIPMENT_TRANSPORT',
    'DEMO_TRANSPORT', 'SITE_RENTAL', 'COMMUNICATION', 'VISA', 'INSURANCE',
    'CONSUMABLES', 'OTHER',
]

PRESALES_CATEGORIES_L1 = ['SITE_VISIT', 'PROPOSAL_WRITING', 'MEETING', 'TRAVEL_STANDARD']
PRESALES_CATEGORIES_L2 = [
    'POC_EXECUTION', 'WIFI_SURVEY', 'ENGINEERING_STUDY',
    'DEMO_TRANSPORT', 'TRAVEL_SPECIAL', 'CUSTOM_SAMPLE', 'OTHER',
]

EMPLOYEE_LEVELS = [
    'JUNIOR_ENGINEER', 'ENGINEER', 'SENIOR_ENGINEER',
    'PROJECT_MANAGER', 'SOLUTION_ARCHITECT', 'OTHER',
]

# Default day rates by level (VND) — used as hints in UI
DEFAULT_RATES_BY_LEVEL: Dict[str, float] = {
    'JUNIOR_ENGINEER':    900_000,
    'ENGINEER':         1_200_000,
    'SENIOR_ENGINEER':  1_700_000,
    'PROJECT_MANAGER':  2_100_000,
    'SOLUTION_ARCHITECT': 2_400_000,
    'OTHER':            1_000_000,
}

# ── A→F Formula ────────────────────────────────────────────────────────────────

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
    # Manual overrides (None = use formula)
    b_override: Optional[float] = None,
    d_override: Optional[float] = None,
    e_override: Optional[float] = None,
    f_override: Optional[float] = None,
) -> Dict:
    """
    Calculate full COGS estimate using A→F formula.

    Returns dict with all line items, totals, GP, and Go/No-Go.
    """
    a = float(a_equipment or 0)
    c = float(c_fabrication or 0)
    rate = float(man_day_rate or 0)
    days = int(man_days or 0)
    team = float(team_size or 1)

    b = float(b_override) if b_override is not None else a * float(alpha)
    d = float(d_override) if d_override is not None else days * rate * team
    e = float(e_override) if e_override is not None else d * float(beta)
    f = float(f_override) if f_override is not None else (a + c) * float(gamma)

    total_cogs = a + b + c + d + e + f
    sales = float(sales_value or 0)
    gp = sales - total_cogs
    gp_pct = (gp / sales * 100) if sales > 0 else 0.0

    return {
        'a': a, 'b': b, 'c': c, 'd': d, 'e': e, 'f': f,
        'total_cogs': total_cogs,
        'sales': sales,
        'gp': gp,
        'gp_percent': round(gp_pct, 2),
        'b_from_formula': a * float(alpha),
        'd_from_formula': days * rate * team,
        'e_from_formula': d * float(beta),
        'f_from_formula': (a + c) * float(gamma),
    }


def get_go_no_go(gp_percent: float, go_threshold: float = 25.0, conditional_threshold: float = 18.0) -> str:
    """Return 'GO', 'CONDITIONAL', or 'NO_GO' based on GP%."""
    if gp_percent >= go_threshold:
        return 'GO'
    elif gp_percent >= conditional_threshold:
        return 'CONDITIONAL'
    return 'NO_GO'


def go_no_go_badge(decision: str) -> str:
    icons = {'GO': '✅ GO', 'CONDITIONAL': '⚠️ CONDITIONAL', 'NO_GO': '❌ NO-GO'}
    return icons.get(decision, '—')


# ── Formatting ─────────────────────────────────────────────────────────────────

def fmt_vnd(amount: Optional[float], show_unit: bool = True) -> str:
    """Format amount as VND string: 1,234,567,890 ₫"""
    if amount is None:
        return '—'
    try:
        s = f"{float(amount):,.0f}"
        return f"{s} ₫" if show_unit else s
    except (TypeError, ValueError):
        return '—'


def fmt_percent(value: Optional[float], decimals: int = 1) -> str:
    if value is None:
        return '—'
    try:
        return f"{float(value):.{decimals}f}%"
    except (TypeError, ValueError):
        return '—'


def pct_change(estimated: float, actual: float) -> Optional[float]:
    """Return variance % (positive = over-budget)."""
    if not estimated:
        return None
    return round((actual - estimated) / estimated * 100, 2)


def impact_color(variance_pct: Optional[float]) -> str:
    if variance_pct is None:
        return '⚪'
    if variance_pct < -5:
        return '🟢'
    if variance_pct <= 5:
        return '🟡'
    return '🔴'
