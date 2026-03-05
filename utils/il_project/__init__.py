# utils/il_project/__init__.py
"""
Intralogistics Project Management — Shared Utilities
"""

from .queries import (
    # Lookups
    get_project_types,
    get_employees,
    get_companies,
    get_currencies,
    generate_project_code,
    # Projects
    get_projects_df,
    get_project,
    create_project,
    update_project,
    soft_delete_project,
    # Estimates
    get_estimates,
    get_active_estimate,
    create_estimate,
    update_estimate,
    activate_estimate,
    # Labor Logs
    get_labor_logs_df,
    create_labor_log,
    update_labor_log,
    approve_labor_log,
    soft_delete_labor_log,
    # Expenses
    get_expenses_df,
    create_expense,
    update_expense,
    approve_expense,
    soft_delete_expense,
    update_expense_attachment,
    update_labor_attachment,
    # Pre-sales
    get_presales_costs_df,
    create_presales_cost,
    bulk_update_presales_allocation,
    # COGS Actual
    get_cogs_actual,
    sync_cogs_actual,
    update_cogs_actual_fields,
    finalize_cogs_actual,
    # Milestones
    get_milestones_df,
    create_milestone,
    update_milestone,
    # Variance
    get_variance_df,
    upsert_variance_row,
    # Benchmarks
    get_benchmarks_df,
    create_benchmark,
)

from .helpers import (
    calculate_estimate,
    get_go_no_go,
    fmt_vnd,
    fmt_percent,
    pct_change,
    COGS_LABELS,
    PHASE_LABELS,
    STATUS_COLORS,
)

from .s3_il import ILProjectS3Manager

__all__ = [
    'get_project_types', 'get_employees', 'get_companies', 'get_currencies', 'generate_project_code',
    'get_projects_df', 'get_project', 'create_project', 'update_project', 'soft_delete_project',
    'get_estimates', 'get_active_estimate', 'create_estimate', 'update_estimate', 'activate_estimate',
    'get_labor_logs_df', 'create_labor_log', 'update_labor_log', 'approve_labor_log', 'soft_delete_labor_log',
    'get_expenses_df', 'create_expense', 'update_expense', 'approve_expense', 'soft_delete_expense',
    'update_expense_attachment', 'update_labor_attachment',
    'get_presales_costs_df', 'create_presales_cost', 'bulk_update_presales_allocation',
    'get_cogs_actual', 'sync_cogs_actual', 'update_cogs_actual_fields', 'finalize_cogs_actual',
    'get_milestones_df', 'create_milestone', 'update_milestone',
    'get_variance_df', 'upsert_variance_row',
    'get_benchmarks_df', 'create_benchmark',
    'calculate_estimate', 'get_go_no_go', 'fmt_vnd', 'fmt_percent', 'pct_change',
    'COGS_LABELS', 'PHASE_LABELS', 'STATUS_COLORS',
    'ILProjectS3Manager',
]