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
    # Pre-sales
    get_presales_costs_df,
    create_presales_cost,
    bulk_update_presales_allocation,
    # COGS Actual
    get_cogs_actual,
    get_all_cogs_summary_df,
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
    # Products & Costbook lookup
    search_products,
    get_costbook_for_product,
    get_quotation_for_product,
    # Estimate line items
    get_estimate_line_items,
    create_estimate_line_item,
    delete_estimate_line_item,
    get_costbook_products_for_import,
    get_active_costbooks,
    # Estimate attachments (Pattern A: junction → medias)
    create_estimate_media,
    get_estimate_medias,
    delete_estimate_media,
    # Estimate line item attachments (Pattern A)
    create_line_item_media,
    get_line_item_medias,
    delete_line_item_media,
    # Expense attachments (Pattern A — junction table existed in DDL)
    create_expense_media,
    get_expense_medias,
    delete_expense_media,
    # Labor log attachments (Pattern A — junction table existed in DDL)
    create_labor_media,
    get_labor_medias,
    delete_labor_media,
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

from .currency import (
    get_rate,
    get_rate_to_vnd,
    convert_to_vnd,
    fmt_rate,
    rate_status,
    get_currency_list,
    RateResult,
    clear_cache as clear_rate_cache,
)

from .email_notify import (
    notify_pr_submitted,
    notify_pr_approved,
    notify_pr_rejected,
    notify_pr_revision_requested,
    notify_po_created,
    notify_pr_cancelled,
    notify_pr_reminder,
    build_pr_deep_link,
)

from .po_pdf import (
    generate_po_pdf,
    VALID_LANGUAGES,
    LANGUAGE_DISPLAY,
)

from .pr_queries import (
    # PR Number
    generate_pr_number,
    # PR CRUD
    get_pr_list_df,
    get_pending_for_approver,
    get_pr,
    get_pr_items_df,
    create_pr,
    update_pr,
    create_pr_item,
    delete_pr_item,
    recalc_pr_totals,
    reduce_pr_item,
    cancel_pr,
    # Approval Workflow
    get_approval_chain,
    determine_max_level,
    get_current_approver,
    submit_pr,
    approve_pr,
    reject_pr,
    request_revision,
    get_pr_approval_history,
    # Import from Estimate
    get_importable_estimate_items,
    # PO Creation
    create_po_from_pr,
    # PO Readiness (new)
    resolve_product_ids,
    validate_po_readiness,
    link_product_to_pr_item,
    search_products_for_linking,
    get_pr_costbook_status,
    get_costbook_warnings_batch,
    # PO Enrichment (new)
    get_payment_terms,
    get_trade_terms,
    get_contacts_for_company,
    get_company_address,
    get_po_enrichment_data,
    # Permission Checks
    is_project_pm,
    is_approver_for_pr,
    get_project_pm_email,
    # Budget Comparison
    get_budget_vs_pr,
)

# ── WBS Management (Phases, Tasks, Checklists, Comments, Media, Members) ────
from .wbs_queries import (
    # Bootstrap & Client-side helpers
    bootstrap_wbs_data,
    filter_tasks_client,
    derive_my_tasks_client,
    # Phases
    get_phases_df,
    get_phase,
    create_phase,
    update_phase,
    soft_delete_phase,
    # Tasks
    get_tasks_df,
    get_my_tasks_df,
    get_task,
    create_task,
    update_task,
    quick_update_task,
    soft_delete_task,
    generate_wbs_code,
    # Checklists
    get_checklists,
    create_checklist_item,
    toggle_checklist_item,
    delete_checklist_item,
    # Comments
    get_task_comments,
    create_comment,
    log_status_change,
    # Task Media
    get_task_media,
    attach_media_to_task,
    detach_media,
    # Project Members
    get_project_members_df,
    get_member,
    create_member,
    update_member,
    remove_member,
    get_member_workload,
    # Completion aggregation
    sync_phase_completion,
    sync_project_completion,
    sync_completion_up,
)

from .wbs_helpers import (
    TASK_STATUS_OPTIONS,
    TASK_STATUS_ICONS,
    PHASE_STATUS_OPTIONS,
    PRIORITY_OPTIONS,
    PRIORITY_ICONS,
    MEMBER_ROLES,
    MEMBER_ROLE_LABELS,
    DEPENDENCY_TYPES,
    DEPENDENCY_LABELS,
    DEFAULT_PHASE_TEMPLATES,
    fmt_status,
    fmt_priority,
    fmt_completion,
    fmt_hours,
    comment_type_icon,
    # Performance helpers
    log_perf,
    invalidate_wbs_cache,
    invalidate_execution_cache,
    invalidate_progress_cache,
    render_attachments,
)

from .wbs_notify import (
    notify_task_assigned,
    notify_member_added,
    notify_task_blocked,
    notify_task_completed,
    notify_on_task_status_change,
    notify_on_task_assign,
    build_wbs_deep_link,
    build_team_deep_link,
)

# ── Execution Tracking (Issues, Risks, Change Orders, Progress, Quality) ────
from .wbs_execution_queries import (
    # Bootstrap
    bootstrap_execution_data,
    bootstrap_progress_data,
    # Issues
    get_issues_df, get_issue, generate_issue_code,
    create_issue, update_issue, soft_delete_issue,
    # Risks
    get_risks_df, get_risk, generate_risk_code, calc_risk_score,
    create_risk, update_risk, soft_delete_risk, get_risk_matrix_summary,
    # Change Orders
    get_change_orders_df, get_change_order, generate_co_number,
    create_change_order, update_change_order, get_co_impact_summary,
    # Progress Reports
    get_progress_reports_df, get_progress_report, generate_report_number,
    create_progress_report, update_progress_report,
    # Quality Checklists
    get_quality_checklists_df, get_quality_checklist,
    create_quality_checklist, update_quality_checklist, soft_delete_quality_checklist,
    # Attachments (Pattern A: junction → medias)
    get_entity_medias, link_media, unlink_media,
    upload_and_attach, get_attachment_url,
)

__all__ = [
    # ── Lookups ──
    'get_project_types', 'get_employees', 'get_companies', 'get_currencies', 'generate_project_code',
    # ── Projects ──
    'get_projects_df', 'get_project', 'create_project', 'update_project', 'soft_delete_project',
    # ── Estimates ──
    'get_estimates', 'get_active_estimate', 'create_estimate', 'update_estimate', 'activate_estimate',
    # ── Labor Logs ──
    'get_labor_logs_df', 'create_labor_log', 'update_labor_log', 'approve_labor_log', 'soft_delete_labor_log',
    # ── Expenses ──
    'get_expenses_df', 'create_expense', 'update_expense', 'approve_expense', 'soft_delete_expense',
    # ── Pre-sales ──
    'get_presales_costs_df', 'create_presales_cost', 'bulk_update_presales_allocation',
    # ── COGS Actual ──
    'get_cogs_actual', 'get_all_cogs_summary_df', 'sync_cogs_actual', 'update_cogs_actual_fields', 'finalize_cogs_actual',
    # ── Milestones ──
    'get_milestones_df', 'create_milestone', 'update_milestone',
    # ── Variance ──
    'get_variance_df', 'upsert_variance_row',
    # ── Benchmarks ──
    'get_benchmarks_df', 'create_benchmark',
    # ── Products & Costbook ──
    'search_products', 'get_costbook_for_product', 'get_quotation_for_product',
    # ── Estimate Line Items ──
    'get_estimate_line_items', 'create_estimate_line_item', 'delete_estimate_line_item',
    'get_costbook_products_for_import', 'get_active_costbooks',
    # ── Attachments (Pattern A: junction → medias) ──
    'create_estimate_media', 'get_estimate_medias', 'delete_estimate_media',
    'create_line_item_media', 'get_line_item_medias', 'delete_line_item_media',
    'create_expense_media', 'get_expense_medias', 'delete_expense_media',
    'create_labor_media', 'get_labor_medias', 'delete_labor_media',
    # ── Helpers ──
    'calculate_estimate', 'get_go_no_go', 'fmt_vnd', 'fmt_percent', 'pct_change',
    'COGS_LABELS', 'PHASE_LABELS', 'STATUS_COLORS',
    # ── S3 ──
    'ILProjectS3Manager',
    # ── Currency ──
    'get_rate', 'get_rate_to_vnd', 'convert_to_vnd',
    'fmt_rate', 'rate_status', 'get_currency_list',
    'RateResult', 'clear_rate_cache',
    # ── Email Notifications ──
    'notify_pr_submitted', 'notify_pr_approved', 'notify_pr_rejected',
    'notify_pr_revision_requested', 'notify_po_created',
    'notify_pr_cancelled',
    'notify_pr_reminder',
    'build_pr_deep_link',
    # ── PO PDF ──
    'generate_po_pdf', 'VALID_LANGUAGES', 'LANGUAGE_DISPLAY',
    # ── Purchase Request ──
    'generate_pr_number',
    'get_pr_list_df', 'get_pending_for_approver', 'get_pr', 'get_pr_items_df',
    'create_pr', 'update_pr', 'create_pr_item', 'delete_pr_item', 'recalc_pr_totals',
    'reduce_pr_item', 'cancel_pr',
    'get_approval_chain', 'determine_max_level', 'get_current_approver',
    'submit_pr', 'approve_pr', 'reject_pr', 'request_revision', 'get_pr_approval_history',
    'get_importable_estimate_items',
    'create_po_from_pr',
    'resolve_product_ids', 'validate_po_readiness',
    'link_product_to_pr_item', 'search_products_for_linking',
    'get_pr_costbook_status',
    'get_costbook_warnings_batch',
    'get_payment_terms', 'get_trade_terms',
    'get_contacts_for_company', 'get_company_address',
    'get_po_enrichment_data',
    'is_project_pm', 'is_approver_for_pr',
    'get_project_pm_email',
    'get_budget_vs_pr',
    # ── WBS Phases ──
    'get_phases_df', 'get_phase', 'create_phase', 'update_phase', 'soft_delete_phase',
    # ── WBS Tasks ──
    'get_tasks_df', 'get_my_tasks_df', 'get_task',
    'create_task', 'update_task', 'quick_update_task', 'soft_delete_task',
    'generate_wbs_code',
    # ── WBS Bootstrap & Helpers ──
    'bootstrap_wbs_data', 'filter_tasks_client', 'derive_my_tasks_client',
    # ── Checklists ──
    'get_checklists', 'create_checklist_item', 'toggle_checklist_item', 'delete_checklist_item',
    # ── Comments ──
    'get_task_comments', 'create_comment', 'log_status_change',
    # ── Task Media ──
    'get_task_media', 'attach_media_to_task', 'detach_media',
    # ── Project Members ──
    'get_project_members_df', 'get_member', 'create_member', 'update_member',
    'remove_member', 'get_member_workload',
    # ── Completion ──
    'sync_phase_completion', 'sync_project_completion', 'sync_completion_up',
    # ── WBS Helpers ──
    'TASK_STATUS_OPTIONS', 'TASK_STATUS_ICONS', 'PHASE_STATUS_OPTIONS',
    'PRIORITY_OPTIONS', 'PRIORITY_ICONS', 'MEMBER_ROLES', 'MEMBER_ROLE_LABELS',
    'DEPENDENCY_TYPES', 'DEPENDENCY_LABELS', 'DEFAULT_PHASE_TEMPLATES',
    'fmt_status', 'fmt_priority', 'fmt_completion', 'fmt_hours', 'comment_type_icon',
    'log_perf', 'invalidate_wbs_cache', 'invalidate_execution_cache',
    'invalidate_progress_cache', 'render_attachments',
    # ── WBS Email Notifications ──
    'notify_task_assigned', 'notify_member_added',
    'notify_task_blocked', 'notify_task_completed',
    'notify_on_task_status_change', 'notify_on_task_assign',
    'build_wbs_deep_link', 'build_team_deep_link',
    # ── Issues ──
    'get_issues_df', 'get_issue', 'generate_issue_code',
    'create_issue', 'update_issue', 'soft_delete_issue',
    # ── Execution Bootstrap ──
    'bootstrap_execution_data', 'bootstrap_progress_data',
    # ── Risks ──
    'get_risks_df', 'get_risk', 'generate_risk_code', 'calc_risk_score',
    'create_risk', 'update_risk', 'soft_delete_risk', 'get_risk_matrix_summary',
    # ── Change Orders ──
    'get_change_orders_df', 'get_change_order', 'generate_co_number',
    'create_change_order', 'update_change_order', 'get_co_impact_summary',
    # ── Progress Reports ──
    'get_progress_reports_df', 'get_progress_report', 'generate_report_number',
    'create_progress_report', 'update_progress_report',
    # ── Quality Checklists ──
    'get_quality_checklists_df', 'get_quality_checklist',
    'create_quality_checklist', 'update_quality_checklist', 'soft_delete_quality_checklist',
    # ── Attachments (Pattern A) ──
    'get_entity_medias', 'link_media', 'unlink_media',
    'upload_and_attach', 'get_attachment_url',
]