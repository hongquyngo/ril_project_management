# utils/il_project/queries.py
"""
Database layer for IL Project Management.
All SQL queries in one place — pages never write raw SQL.

Conventions:
  - *_df()  → returns pd.DataFrame  (for st.dataframe)
  - others  → return dict / list / id
  - created_by / modified_by = str(user_id) from session
"""

import logging
from typing import Dict, List, Optional, Any
import pandas as pd
from sqlalchemy import text
from ..db import execute_query, execute_query_df, execute_update, get_transaction
from .wbs_helpers import log_perf

logger = logging.getLogger(__name__)


# ── Permission check helper ──────────────────────────────────────────────────
def _check_perm(action: str, project_id, employee_id, is_admin=False):
    """
    Backend permission guard. Raises PermissionDenied if not allowed.
    Only runs if employee_id is provided (backward compat).
    """
    if employee_id is None:
        return  # Skip check (backward compat — caller didn't pass employee_id)
    from .permissions import require_permission
    require_permission(action, project_id, employee_id, is_admin)


def _get_entity_project_id(table: str, entity_id: int) -> int:
    """Look up project_id from entity table. Used by approve functions."""
    rows = execute_query(
        f"SELECT project_id FROM {table} WHERE id = :id AND delete_flag = 0 LIMIT 1",
        {'id': entity_id},
    )
    if not rows:
        raise ValueError(f"{table} record {entity_id} not found")
    return rows[0]['project_id']


# ══════════════════════════════════════════════════════════════════════════════
# LOOKUPS
# ══════════════════════════════════════════════════════════════════════════════

def get_project_types() -> List[Dict]:
    return execute_query("""
        SELECT id, name, code, description,
               default_alpha, default_beta, default_gamma,
               gp_go_threshold, gp_conditional_threshold,
               man_days_benchmark
        FROM il_project_types
        WHERE delete_flag = 0
        ORDER BY name
    """)


def get_employees() -> List[Dict]:
    """All active employees — for PM / sales / worker dropdowns."""
    return execute_query("""
        SELECT id,
               CONCAT(first_name, ' ', last_name) AS full_name
        FROM employees
        WHERE delete_flag = 0
        ORDER BY first_name, last_name
    """)


def get_companies() -> List[Dict]:
    return execute_query("""
        SELECT id, english_name AS name, company_code
        FROM companies
        WHERE delete_flag = 0
        ORDER BY english_name
    """)


def get_currencies() -> List[Dict]:
    return execute_query("""
        SELECT id, code, name
        FROM currencies
        WHERE delete_flag = 0
        ORDER BY code
    """)


def generate_project_code(user_id: int) -> str:
    """
    Generate next unique project code: IL-YYYY-{user_id}-NNN
    e.g. IL-2025-3-001
    Finds the highest NNN for current year + user_id and increments.
    """
    from datetime import date
    year = date.today().year
    prefix = f'IL-{year}-{user_id:03d}-'
    rows = execute_query("""
        SELECT project_code
        FROM il_projects
        WHERE project_code LIKE :pattern
        ORDER BY project_code DESC
        LIMIT 1
    """, {'pattern': f'{prefix}%'})

    if rows:
        try:
            last_seq = int(rows[0]['project_code'].split('-')[-1])
        except (ValueError, IndexError):
            last_seq = 0
    else:
        last_seq = 0

    return f"{prefix}{last_seq + 1:03d}"


# ══════════════════════════════════════════════════════════════════════════════
# PROJECTS
# ══════════════════════════════════════════════════════════════════════════════

@log_perf
def get_projects_df(
    status: Optional[str] = None,
    type_id: Optional[int] = None,
    pm_id: Optional[int] = None,
    search: Optional[str] = None,
) -> pd.DataFrame:
    sql = """
        SELECT
            project_id, project_code, contract_number, project_name,
            project_type, customer_name, status, go_no_go_decision,
            billing_type, location, site_distance_category,
            effective_contract_value, currency_code,
            estimated_gp_percent, estimated_cogs, go_no_go_result,
            actual_gp_percent, actual_cogs, is_finalized,
            pm_name, sales_name,
            estimated_start_date, estimated_end_date,
            actual_start_date, actual_end_date,
            warranty_type, warranty_end_date,
            created_date, modified_date
        FROM v_il_project_overview
        WHERE 1=1
    """
    params: Dict = {}
    if status:
        sql += " AND status = :status"
        params['status'] = status
    if type_id:
        sql += " AND project_id IN (SELECT id FROM il_projects WHERE project_type_id = :type_id AND delete_flag=0)"
        params['type_id'] = type_id
    if pm_id:
        sql += " AND project_id IN (SELECT id FROM il_projects WHERE pm_employee_id = :pm_id AND delete_flag=0)"
        params['pm_id'] = pm_id
    if search:
        sql += " AND (project_code LIKE :s OR project_name LIKE :s OR customer_name LIKE :s)"
        params['s'] = f"%{search}%"
    sql += " ORDER BY created_date DESC"
    return execute_query_df(sql, params)


def get_project(project_id: int) -> Optional[Dict]:
    rows = execute_query("""
        SELECT p.*,
               pt.name AS type_name, pt.code AS type_code,
               pt.default_alpha, pt.default_beta, pt.default_gamma,
               pt.gp_go_threshold, pt.gp_conditional_threshold,
               c.english_name AS customer_name,
               cur.code AS currency_code,
               CONCAT(pm.first_name,' ',pm.last_name) AS pm_name,
               CONCAT(s.first_name,' ',s.last_name)   AS sales_name
        FROM il_projects p
        LEFT JOIN il_project_types pt ON p.project_type_id = pt.id
        LEFT JOIN companies         c  ON p.customer_id     = c.id
        LEFT JOIN currencies       cur ON p.currency_id     = cur.id
        LEFT JOIN employees        pm  ON p.pm_employee_id  = pm.id
        LEFT JOIN employees         s  ON p.sales_employee_id = s.id
        WHERE p.id = :id AND p.delete_flag = 0
    """, {'id': project_id})
    return rows[0] if rows else None


def create_project(data: Dict, created_by: str) -> int:
    sql = """
        INSERT INTO il_projects (
            project_code, contract_number, project_name, project_type_id,
            customer_id, end_customer_name,
            contract_value, amended_contract_value, currency_id, exchange_rate, billing_type,
            status, go_no_go_decision, decision_date, decision_notes,
            location, site_distance_category, environment_category, import_category,
            estimated_start_date, estimated_end_date,
            warranty_months, warranty_type,
            pm_employee_id, sales_employee_id,
            created_by, modified_by
        ) VALUES (
            :project_code, :contract_number, :project_name, :project_type_id,
            :customer_id, :end_customer_name,
            :contract_value, :amended_contract_value, :currency_id, :exchange_rate, :billing_type,
            :status, :go_no_go_decision, :decision_date, :decision_notes,
            :location, :site_distance_category, :environment_category, :import_category,
            :estimated_start_date, :estimated_end_date,
            :warranty_months, :warranty_type,
            :pm_employee_id, :sales_employee_id,
            :created_by, :created_by
        )
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), {**data, 'created_by': created_by})
        conn.commit()
        return result.lastrowid


def update_project(project_id: int, data: Dict, modified_by: str) -> bool:
    sql = """
        UPDATE il_projects SET
            project_code = :project_code,
            contract_number = :contract_number,
            project_name = :project_name,
            project_type_id = :project_type_id,
            customer_id = :customer_id,
            end_customer_name = :end_customer_name,
            contract_value = :contract_value,
            amended_contract_value = :amended_contract_value,
            currency_id = :currency_id,
            exchange_rate = :exchange_rate,
            billing_type = :billing_type,
            status = :status,
            go_no_go_decision = :go_no_go_decision,
            decision_date = :decision_date,
            decision_notes = :decision_notes,
            location = :location,
            site_distance_category = :site_distance_category,
            environment_category = :environment_category,
            import_category = :import_category,
            estimated_start_date = :estimated_start_date,
            estimated_end_date = :estimated_end_date,
            actual_start_date = :actual_start_date,
            actual_end_date = :actual_end_date,
            warranty_months = :warranty_months,
            warranty_end_date = :warranty_end_date,
            warranty_type = :warranty_type,
            pm_employee_id = :pm_employee_id,
            sales_employee_id = :sales_employee_id,
            modified_by = :modified_by,
            version = version + 1
        WHERE id = :id AND delete_flag = 0
    """
    rows = execute_update(sql, {**data, 'id': project_id, 'modified_by': modified_by})
    return rows > 0


def soft_delete_project(project_id: int, modified_by: str) -> bool:
    rows = execute_update(
        "UPDATE il_projects SET delete_flag=1, modified_by=:m, version=version+1 WHERE id=:id",
        {'id': project_id, 'm': modified_by}
    )
    return rows > 0


# ══════════════════════════════════════════════════════════════════════════════
# ESTIMATES
# ══════════════════════════════════════════════════════════════════════════════

@log_perf
def get_estimates(project_id: int) -> List[Dict]:
    return execute_query("""
        SELECT id, estimate_version, estimate_label, estimate_type, is_active,
               a_equipment_cost, alpha_rate, b_logistics_import, b_override,
               c_custom_fabrication,
               d_man_days, d_man_day_rate, d_team_size, d_direct_labor, d_override,
               beta_rate, e_travel_site_oh, e_override,
               gamma_rate, f_warranty_reserve, f_override,
               total_cogs, sales_value, estimated_gp, estimated_gp_percent,
               go_no_go_result, assessment_notes,
               created_date, modified_date
        FROM il_project_cogs_estimate
        WHERE project_id = :pid AND delete_flag = 0
        ORDER BY estimate_version DESC
    """, {'pid': project_id})


def get_active_estimate(project_id: int) -> Optional[Dict]:
    rows = execute_query("""
        SELECT * FROM il_project_cogs_estimate
        WHERE project_id = :pid AND is_active = 1 AND delete_flag = 0
        LIMIT 1
    """, {'pid': project_id})
    return rows[0] if rows else None


def create_estimate(data: Dict, created_by: str,
                    caller_employee_id: int = None, caller_is_admin: bool = False) -> int:
    """
    Insert new estimate. Caller must call activate_estimate() in same
    transaction if this should be the active one.
    """
    _check_perm('estimate.create', data.get('project_id'), caller_employee_id, caller_is_admin)
    sql = """
        INSERT INTO il_project_cogs_estimate (
            project_id, estimate_version, estimate_label, estimate_type, is_active,
            a_equipment_cost, a_equipment_notes,
            alpha_rate, b_logistics_import, b_override,
            c_custom_fabrication, c_fabrication_notes,
            d_man_days, d_man_day_rate, d_team_size, d_direct_labor, d_override,
            beta_rate, e_travel_site_oh, e_override,
            gamma_rate, f_warranty_reserve, f_override,
            total_cogs, sales_value, estimated_gp, estimated_gp_percent,
            go_no_go_result, assessment_notes,
            created_by, modified_by
        ) VALUES (
            :project_id, :estimate_version, :estimate_label, :estimate_type, 0,
            :a_equipment_cost, :a_equipment_notes,
            :alpha_rate, :b_logistics_import, :b_override,
            :c_custom_fabrication, :c_fabrication_notes,
            :d_man_days, :d_man_day_rate, :d_team_size, :d_direct_labor, :d_override,
            :beta_rate, :e_travel_site_oh, :e_override,
            :gamma_rate, :f_warranty_reserve, :f_override,
            :total_cogs, :sales_value, :estimated_gp, :estimated_gp_percent,
            :go_no_go_result, :assessment_notes,
            :created_by, :created_by
        )
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), {**data, 'created_by': created_by})
        conn.commit()
        return result.lastrowid


def activate_estimate(project_id: int, estimate_id: int, modified_by: str,
                      caller_employee_id: int = None, caller_is_admin: bool = False) -> bool:
    """
    Atomically deactivate all other estimates → activate the target.
    App-layer replacement for the removed trigger.
    """
    _check_perm('estimate.activate', project_id, caller_employee_id, caller_is_admin)
    try:
        with get_transaction() as conn:
            conn.execute(text("""
                UPDATE il_project_cogs_estimate
                SET is_active = 0, modified_by = :m
                WHERE project_id = :pid AND is_active = 1 AND delete_flag = 0
            """), {'pid': project_id, 'm': modified_by})

            conn.execute(text("""
                UPDATE il_project_cogs_estimate
                SET is_active = 1, modified_by = :m
                WHERE id = :id
            """), {'id': estimate_id, 'm': modified_by})

            # Sync GP% snapshot onto project
            conn.execute(text("""
                UPDATE il_projects p
                JOIN il_project_cogs_estimate e ON e.id = :id
                SET p.estimated_gp_percent = e.estimated_gp_percent,
                    p.modified_by = :m,
                    p.version = p.version + 1
                WHERE p.id = :pid
            """), {'id': estimate_id, 'pid': project_id, 'm': modified_by})
        return True
    except Exception as e:
        logger.error(f"activate_estimate failed: {e}")
        return False


def update_estimate(estimate_id: int, data: Dict, modified_by: str) -> bool:
    sql = """
        UPDATE il_project_cogs_estimate SET
            estimate_label = :estimate_label, estimate_type = :estimate_type,
            a_equipment_cost = :a_equipment_cost, a_equipment_notes = :a_equipment_notes,
            alpha_rate = :alpha_rate, b_logistics_import = :b_logistics_import, b_override = :b_override,
            c_custom_fabrication = :c_custom_fabrication, c_fabrication_notes = :c_fabrication_notes,
            d_man_days = :d_man_days, d_man_day_rate = :d_man_day_rate, d_team_size = :d_team_size,
            d_direct_labor = :d_direct_labor, d_override = :d_override,
            beta_rate = :beta_rate, e_travel_site_oh = :e_travel_site_oh, e_override = :e_override,
            gamma_rate = :gamma_rate, f_warranty_reserve = :f_warranty_reserve, f_override = :f_override,
            total_cogs = :total_cogs, sales_value = :sales_value,
            estimated_gp = :estimated_gp, estimated_gp_percent = :estimated_gp_percent,
            go_no_go_result = :go_no_go_result, assessment_notes = :assessment_notes,
            modified_by = :modified_by, version = version + 1
        WHERE id = :id AND delete_flag = 0
    """
    rows = execute_update(sql, {**data, 'id': estimate_id, 'modified_by': modified_by})
    return rows > 0


# ══════════════════════════════════════════════════════════════════════════════
# LABOR LOGS
# ══════════════════════════════════════════════════════════════════════════════

@log_perf
def get_labor_logs_df(
    project_id: Optional[int] = None,
    phase: Optional[str] = None,
    approval_status: Optional[str] = None,
    date_from=None,
    date_to=None,
) -> pd.DataFrame:
    sql = """
        SELECT
            ll.id, ll.project_id, p.project_code,
            ll.work_date, ll.phase,
            COALESCE(CONCAT(e.first_name,' ',e.last_name), ll.subcontractor_name) AS worker,
            ll.employee_level, ll.is_on_site,
            ll.man_days, ll.daily_rate, ll.amount,
            ll.description, ll.approval_status, ll.presales_allocation,
            CONCAT(ap.first_name,' ',ap.last_name) AS approved_by_name,
            ll.approved_date
        FROM il_project_labor_logs ll
        LEFT JOIN employees e  ON ll.employee_id  = e.id
        LEFT JOIN employees ap ON ll.approved_by  = ap.id
        LEFT JOIN il_projects p ON ll.project_id = p.id
        WHERE ll.delete_flag = 0
    """
    params: Dict = {}
    if project_id:
        sql += " AND ll.project_id = :pid"
        params['pid'] = project_id
    if phase:
        sql += " AND ll.phase = :phase"
        params['phase'] = phase
    if approval_status:
        sql += " AND ll.approval_status = :as_"
        params['as_'] = approval_status
    if date_from:
        sql += " AND ll.work_date >= :date_from"
        params['date_from'] = date_from
    if date_to:
        sql += " AND ll.work_date <= :date_to"
        params['date_to'] = date_to
    sql += " ORDER BY ll.work_date DESC, ll.created_date DESC"
    return execute_query_df(sql, params)


def create_labor_log(data: Dict, created_by: str) -> int:
    sql = """
        INSERT INTO il_project_labor_logs (
            project_id, employee_id, employee_level,
            subcontractor_name, subcontractor_company,
            work_date, man_days, daily_rate, phase,
            description, is_on_site, presales_allocation,
            approval_status, created_by
        ) VALUES (
            :project_id, :employee_id, :employee_level,
            :subcontractor_name, :subcontractor_company,
            :work_date, :man_days, :daily_rate, :phase,
            :description, :is_on_site, :presales_allocation,
            'PENDING', :created_by
        )
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), {**data, 'created_by': created_by})
        conn.commit()
        return result.lastrowid


def update_labor_log(log_id: int, data: Dict, modified_by: str) -> bool:
    sql = """
        UPDATE il_project_labor_logs SET
            work_date = :work_date, man_days = :man_days, daily_rate = :daily_rate,
            phase = :phase, description = :description, is_on_site = :is_on_site,
            employee_level = :employee_level, presales_allocation = :presales_allocation,
            version = version + 1
        WHERE id = :id AND delete_flag = 0 AND approval_status = 'PENDING'
    """
    rows = execute_update(sql, {**data, 'id': log_id})
    return rows > 0


def approve_labor_log(log_id: int, approved_by: int, status: str = 'APPROVED') -> bool:
    """Approve labor log. Backend-enforced: only PM of project or Admin."""
    # Permission guard: approved_by IS employee_id
    pid = _get_entity_project_id('il_project_labor_logs', log_id)
    _check_perm('cost.approve', pid, approved_by)
    rows = execute_update("""
        UPDATE il_project_labor_logs
        SET approval_status = :status, approved_by = :by, approved_date = NOW()
        WHERE id = :id AND delete_flag = 0
    """, {'id': log_id, 'by': approved_by, 'status': status})
    return rows > 0


def soft_delete_labor_log(log_id: int, modified_by: str) -> bool:
    rows = execute_update(
        "UPDATE il_project_labor_logs SET delete_flag=1 WHERE id=:id AND approval_status='PENDING'",
        {'id': log_id}
    )
    return rows > 0


# ══════════════════════════════════════════════════════════════════════════════
# EXPENSES
# ══════════════════════════════════════════════════════════════════════════════

@log_perf
def get_expenses_df(
    project_id: Optional[int] = None,
    phase: Optional[str] = None,
    approval_status: Optional[str] = None,
    date_from=None,
    date_to=None,
) -> pd.DataFrame:
    sql = """
        SELECT
            ex.id, ex.project_id, p.project_code,
            ex.expense_date, ex.category, ex.phase,
            CONCAT(e.first_name,' ',e.last_name) AS employee_name,
            ex.amount, cur.code AS currency, ex.exchange_rate, ex.amount_vnd,
            ex.description, ex.vendor_name, ex.receipt_number,
            ex.approval_status,
            CONCAT(ap.first_name,' ',ap.last_name) AS approved_by_name
        FROM il_project_expenses ex
        LEFT JOIN employees  e  ON ex.employee_id  = e.id
        LEFT JOIN employees  ap ON ex.approved_by  = ap.id
        LEFT JOIN currencies cur ON ex.currency_id = cur.id
        LEFT JOIN il_projects p  ON ex.project_id  = p.id
        WHERE ex.delete_flag = 0
    """
    params: Dict = {}
    if project_id:
        sql += " AND ex.project_id = :pid"
        params['pid'] = project_id
    if phase:
        sql += " AND ex.phase = :phase"
        params['phase'] = phase
    if approval_status:
        sql += " AND ex.approval_status = :as_"
        params['as_'] = approval_status
    if date_from:
        sql += " AND ex.expense_date >= :date_from"
        params['date_from'] = date_from
    if date_to:
        sql += " AND ex.expense_date <= :date_to"
        params['date_to'] = date_to
    sql += " ORDER BY ex.expense_date DESC"
    return execute_query_df(sql, params)


def create_expense(data: Dict, created_by: str) -> int:
    sql = """
        INSERT INTO il_project_expenses (
            project_id, employee_id, expense_date, category, phase,
            amount, currency_id, exchange_rate,
            description, vendor_name, receipt_number,
            approval_status, created_by
        ) VALUES (
            :project_id, :employee_id, :expense_date, :category, :phase,
            :amount, :currency_id, :exchange_rate,
            :description, :vendor_name, :receipt_number,
            'PENDING', :created_by
        )
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), {**data, 'created_by': created_by})
        conn.commit()
        return result.lastrowid


def approve_expense(expense_id: int, approved_by: int, status: str = 'APPROVED') -> bool:
    """Approve expense. Backend-enforced: only PM of project or Admin."""
    pid = _get_entity_project_id('il_project_expenses', expense_id)
    _check_perm('cost.approve', pid, approved_by)
    rows = execute_update("""
        UPDATE il_project_expenses
        SET approval_status = :status, approved_by = :by, approved_date = NOW()
        WHERE id = :id AND delete_flag = 0
    """, {'id': expense_id, 'by': approved_by, 'status': status})
    return rows > 0


def soft_delete_expense(expense_id: int, modified_by: str) -> bool:
    rows = execute_update(
        "UPDATE il_project_expenses SET delete_flag=1 WHERE id=:id AND approval_status='PENDING'",
        {'id': expense_id}
    )
    return rows > 0


def update_expense(expense_id: int, data: Dict, modified_by: str) -> bool:
    """Update a PENDING expense (pre-approval edit)."""
    sql = """
        UPDATE il_project_expenses SET
            expense_date = :expense_date, category = :category, phase = :phase,
            employee_id = :employee_id,
            amount = :amount, currency_id = :currency_id, exchange_rate = :exchange_rate,
            description = :description, vendor_name = :vendor_name, receipt_number = :receipt_number,
            version = version + 1
        WHERE id = :id AND delete_flag = 0 AND approval_status = 'PENDING'
    """
    rows = execute_update(sql, {**data, 'id': expense_id})
    return rows > 0



# ══════════════════════════════════════════════════════════════════════════════
# PRE-SALES COSTS
# ══════════════════════════════════════════════════════════════════════════════

@log_perf
def get_presales_costs_df(project_id: int) -> pd.DataFrame:
    return execute_query_df("""
        SELECT
            ps.id, ps.cost_layer, ps.category,
            COALESCE(CONCAT(e.first_name,' ',e.last_name), ps.subcontractor_name) AS worker,
            ps.amount, cur.code AS currency, ps.exchange_rate, ps.amount_vnd,
            ps.man_days, ps.allocation, ps.allocation_date, ps.description
        FROM il_project_presales_costs ps
        LEFT JOIN employees  e   ON ps.employee_id  = e.id
        LEFT JOIN currencies cur ON ps.currency_id  = cur.id
        WHERE ps.project_id = :pid AND ps.delete_flag = 0
        ORDER BY ps.cost_layer, ps.created_date
    """, {'pid': project_id})


def create_presales_cost(data: Dict, created_by: str) -> int:
    sql = """
        INSERT INTO il_project_presales_costs (
            project_id, employee_id, subcontractor_name,
            cost_layer, category, amount, currency_id, exchange_rate,
            allocation, man_days, description, created_by
        ) VALUES (
            :project_id, :employee_id, :subcontractor_name,
            :cost_layer, :category, :amount, :currency_id, :exchange_rate,
            :allocation, :man_days, :description, :created_by
        )
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), {**data, 'created_by': created_by})
        conn.commit()
        return result.lastrowid


def bulk_update_presales_allocation(project_id: int, allocation: str, modified_by: str, layer: str = 'SPECIAL') -> int:
    """Set allocation (SGA/COGS) for all Layer-2 costs when win/lose decision made."""
    rows = execute_update("""
        UPDATE il_project_presales_costs
        SET allocation = :alloc, allocation_date = CURDATE(), version = version + 1
        WHERE project_id = :pid AND cost_layer = :layer AND delete_flag = 0
    """, {'pid': project_id, 'alloc': allocation, 'layer': layer})
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# MILESTONES
# ══════════════════════════════════════════════════════════════════════════════

def get_milestones_df(project_id: int) -> pd.DataFrame:
    return execute_query_df("""
        SELECT id, sequence_no, milestone_name, milestone_type,
               billing_percent, billing_amount, planned_date, actual_date,
               status, completion_notes
        FROM il_project_milestones
        WHERE project_id = :pid AND delete_flag = 0
        ORDER BY COALESCE(sequence_no, 999), planned_date
    """, {'pid': project_id})


def create_milestone(data: Dict, created_by: str) -> int:
    sql = """
        INSERT INTO il_project_milestones (
            project_id, sequence_no, milestone_name, milestone_type,
            billing_percent, billing_amount, currency_id,
            planned_date, actual_date, status, completion_notes,
            created_by, modified_by
        ) VALUES (
            :project_id, :sequence_no, :milestone_name, :milestone_type,
            :billing_percent, :billing_amount, :currency_id,
            :planned_date, :actual_date, :status, :completion_notes,
            :created_by, :created_by
        )
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), {**data, 'created_by': created_by})
        conn.commit()
        return result.lastrowid


def update_milestone(milestone_id: int, data: Dict, modified_by: str) -> bool:
    sql = """
        UPDATE il_project_milestones SET
            sequence_no = :sequence_no, milestone_name = :milestone_name,
            milestone_type = :milestone_type,
            billing_percent = :billing_percent, billing_amount = :billing_amount,
            planned_date = :planned_date, actual_date = :actual_date,
            status = :status, completion_notes = :completion_notes,
            modified_by = :modified_by, version = version + 1
        WHERE id = :id AND delete_flag = 0
    """
    rows = execute_update(sql, {**data, 'id': milestone_id, 'modified_by': modified_by})
    return rows > 0


# ══════════════════════════════════════════════════════════════════════════════
# COGS ACTUAL — Sync + Manual override
# ══════════════════════════════════════════════════════════════════════════════

def get_cogs_actual(project_id: int) -> Optional[Dict]:
    rows = execute_query(
        "SELECT * FROM il_project_cogs_actual WHERE project_id = :pid AND delete_flag = 0",
        {'pid': project_id}
    )
    return rows[0] if rows else None


@log_perf
def get_all_cogs_summary_df() -> pd.DataFrame:
    """Cross-project COGS summary: estimate vs actual with GP% for portfolio view."""
    return execute_query_df("""
        SELECT
            p.id AS project_id, p.project_code, p.project_name,
            p.status, pt.code AS type_code,
            e.total_cogs     AS est_cogs,
            e.sales_value    AS est_sales,
            e.estimated_gp_percent AS est_gp_pct,
            a.total_cogs     AS act_cogs,
            a.sales_value    AS act_sales,
            a.actual_gp_percent AS act_gp_pct,
            a.last_sync_date,
            a.is_finalized
        FROM il_projects p
        LEFT JOIN il_project_types pt ON p.project_type_id = pt.id
        LEFT JOIN il_project_cogs_estimate e
            ON e.project_id = p.id AND e.is_active = 1 AND e.delete_flag = 0
        LEFT JOIN il_project_cogs_actual a
            ON a.project_id = p.id AND a.delete_flag = 0
        WHERE p.delete_flag = 0
        ORDER BY p.project_code DESC
    """)


def sync_cogs_actual(project_id: int, modified_by: str,
                     caller_employee_id: int = None, caller_is_admin: bool = False) -> Dict:
    """
    Aggregate from detail tables → upsert il_project_cogs_actual.
    Returns the computed values dict.
    """
    _check_perm('cogs.sync', project_id, caller_employee_id, caller_is_admin)
    try:
        with get_transaction() as conn:
            # D: direct labor (non-PRE_SALES, APPROVED)
            r = conn.execute(text("""
                SELECT COALESCE(SUM(amount),0) AS total_cost,
                       COALESCE(SUM(man_days),0) AS total_days
                FROM il_project_labor_logs
                WHERE project_id = :pid AND delete_flag = 0
                  AND approval_status = 'APPROVED'
                  AND phase != 'PRE_SALES'
            """), {'pid': project_id}).fetchone()
            d_labor = float(r.total_cost)
            d_days = float(r.total_days)

            # D presales: PRE_SALES labor allocated to COGS
            r2 = conn.execute(text("""
                SELECT COALESCE(SUM(amount),0) AS total_cost,
                       COALESCE(SUM(man_days),0) AS total_days
                FROM il_project_labor_logs
                WHERE project_id = :pid AND delete_flag = 0
                  AND approval_status = 'APPROVED'
                  AND phase = 'PRE_SALES'
                  AND presales_allocation = 'COGS'
            """), {'pid': project_id}).fetchone()
            d_presales = float(r2.total_cost)
            d_presales_days = float(r2.total_days)

            total_d_cost = d_labor + d_presales
            total_d_days = d_days + d_presales_days
            d_actual_rate = (total_d_cost / total_d_days) if total_d_days > 0 else None

            # E: travel & expenses (non-PRE_SALES phases, APPROVED, not WARRANTY)
            r3 = conn.execute(text("""
                SELECT COALESCE(SUM(amount_vnd),0) AS total
                FROM il_project_expenses
                WHERE project_id = :pid AND delete_flag = 0
                  AND approval_status = 'APPROVED'
                  AND phase NOT IN ('PRE_SALES','WARRANTY')
            """), {'pid': project_id}).fetchone()
            e_travel = float(r3.total)

            # E presales: special pre-sales travel allocated to COGS
            r4 = conn.execute(text("""
                SELECT COALESCE(SUM(amount_vnd),0) AS total
                FROM il_project_presales_costs
                WHERE project_id = :pid AND delete_flag = 0
                  AND cost_layer = 'SPECIAL'
                  AND allocation = 'COGS'
                  AND category IN ('DEMO_TRANSPORT','TRAVEL_SPECIAL','POC_EXECUTION',
                                   'WIFI_SURVEY','ENGINEERING_STUDY','CUSTOM_SAMPLE','OTHER')
            """), {'pid': project_id}).fetchone()
            e_presales = float(r4.total)

            # Get contract value for sales_value
            r5 = conn.execute(text("""
                SELECT COALESCE(amended_contract_value, contract_value, 0) AS cv,
                       currency_id
                FROM il_projects WHERE id = :pid
            """), {'pid': project_id}).fetchone()
            sales_val = float(r5.cv) if r5 else 0

            # Upsert il_project_cogs_actual
            # Note: A, B, C, F are manually entered (not auto-computed here)
            existing = conn.execute(text(
                "SELECT id, a_equipment_cost, b_logistics_import, c_custom_fabrication, "
                "f_warranty_provision, f_warranty_actual_used, f_warranty_released "
                "FROM il_project_cogs_actual WHERE project_id = :pid AND delete_flag = 0"
            ), {'pid': project_id}).fetchone()

            if existing:
                a = float(existing.a_equipment_cost or 0)
                b = float(existing.b_logistics_import or 0)
                c = float(existing.c_custom_fabrication or 0)
                f_prov = float(existing.f_warranty_provision or 0)
                f_used = float(existing.f_warranty_actual_used or 0)
                f_rel  = float(existing.f_warranty_released or 0)
                f_net  = f_prov - f_rel

                total_cogs = a + b + c + total_d_cost + e_travel + e_presales + f_net
                actual_gp  = sales_val - total_cogs
                gp_pct     = (actual_gp / sales_val * 100) if sales_val > 0 else 0

                conn.execute(text("""
                    UPDATE il_project_cogs_actual SET
                        d_direct_labor    = :d_labor,
                        d_presales_labor  = :d_presales,
                        d_total_man_days  = :d_days,
                        d_actual_rate     = :d_rate,
                        e_travel_site_oh  = :e_travel,
                        e_presales_travel = :e_presales,
                        total_cogs        = :total,
                        sales_value       = :sales,
                        actual_gp         = :gp,
                        actual_gp_percent = :gp_pct,
                        last_sync_date    = NOW(),
                        modified_by       = :m,
                        version           = version + 1
                    WHERE project_id = :pid AND delete_flag = 0
                """), {
                    'pid': project_id, 'm': modified_by,
                    'd_labor': d_labor, 'd_presales': d_presales,
                    'd_days': total_d_days, 'd_rate': d_actual_rate,
                    'e_travel': e_travel, 'e_presales': e_presales,
                    'total': total_cogs, 'sales': sales_val,
                    'gp': actual_gp, 'gp_pct': round(gp_pct, 2),
                })
            else:
                # New record: A=B=C=F=0 (manually entered later),
                # so total_cogs = D + E only for initial sync.
                total_cogs_init = total_d_cost + e_travel + e_presales
                actual_gp_init  = sales_val - total_cogs_init
                gp_pct_init     = (actual_gp_init / sales_val * 100) if sales_val > 0 else 0

                conn.execute(text("""
                    INSERT INTO il_project_cogs_actual (
                        project_id,
                        d_direct_labor, d_presales_labor, d_total_man_days, d_actual_rate,
                        e_travel_site_oh, e_presales_travel,
                        total_cogs, sales_value, actual_gp, actual_gp_percent,
                        last_sync_date, created_by, modified_by
                    ) VALUES (
                        :pid,
                        :d_labor, :d_presales, :d_days, :d_rate,
                        :e_travel, :e_presales,
                        :total, :sales, :gp, :gp_pct,
                        NOW(), :m, :m
                    )
                """), {
                    'pid': project_id, 'm': modified_by,
                    'd_labor': d_labor, 'd_presales': d_presales,
                    'd_days': total_d_days, 'd_rate': d_actual_rate,
                    'e_travel': e_travel, 'e_presales': e_presales,
                    'total': total_cogs_init, 'sales': sales_val,
                    'gp': actual_gp_init, 'gp_pct': round(gp_pct_init, 2),
                })

            # Sync actual_gp_percent to il_projects
            conn.execute(text("""
                UPDATE il_projects p
                JOIN il_project_cogs_actual a ON a.project_id = p.id
                SET p.actual_gp_percent = a.actual_gp_percent, p.modified_by = :m
                WHERE p.id = :pid
            """), {'pid': project_id, 'm': modified_by})

        return get_cogs_actual(project_id) or {}
    except Exception as e:
        logger.error(f"sync_cogs_actual failed for project {project_id}: {e}")
        raise


def update_cogs_actual_fields(project_id: int, data: Dict, modified_by: str,
                              caller_employee_id: int = None, caller_is_admin: bool = False) -> bool:
    """Manual override of A, B, C, F fields."""
    _check_perm('cogs.manual_entry', project_id, caller_employee_id, caller_is_admin)
    sql = """
        UPDATE il_project_cogs_actual SET
            a_equipment_cost = :a_equipment_cost, a_notes = :a_notes,
            b_logistics_import = :b_logistics_import, b_notes = :b_notes,
            c_custom_fabrication = :c_custom_fabrication, c_notes = :c_notes,
            f_warranty_provision = :f_warranty_provision,
            f_warranty_actual_used = :f_warranty_actual_used,
            f_warranty_released = :f_warranty_released, f_notes = :f_notes,
            modified_by = :modified_by, version = version + 1
        WHERE project_id = :pid AND delete_flag = 0
    """
    rows = execute_update(sql, {**data, 'pid': project_id, 'modified_by': modified_by})
    return rows > 0


def finalize_cogs_actual(project_id: int, finalized_by: str,
                         caller_employee_id: int = None, caller_is_admin: bool = False) -> bool:
    """Finalize COGS. Irreversible — Admin only (backend-enforced)."""
    _check_perm('cogs.finalize', project_id, caller_employee_id, caller_is_admin)
    rows = execute_update("""
        UPDATE il_project_cogs_actual
        SET is_finalized = 1, finalized_date = NOW(), finalized_by = :by,
            modified_by = :by, version = version + 1
        WHERE project_id = :pid AND delete_flag = 0
    """, {'pid': project_id, 'by': finalized_by})
    return rows > 0


# ══════════════════════════════════════════════════════════════════════════════
# VARIANCE
# ══════════════════════════════════════════════════════════════════════════════

@log_perf
def get_variance_df(project_id: int) -> pd.DataFrame:
    return execute_query_df("""
        SELECT cogs_category, estimated_amount, actual_amount,
               variance_amount, variance_percent, impact_assessment,
               coefficient_used, coefficient_actual, coefficient_recommended,
               root_cause, corrective_action
        FROM il_project_variance
        WHERE project_id = :pid AND delete_flag = 0
        ORDER BY FIELD(cogs_category,'A','B','C','D','E','F','PRESALES','TOTAL')
    """, {'pid': project_id})


def upsert_variance_row(
    project_id: int, category: str,
    estimated: float, actual: float,
    root_cause: str, corrective_action: str,
    impact: Optional[str],
    coeff_used: Optional[float], coeff_actual: Optional[float], coeff_rec: Optional[float],
    modified_by: str
) -> bool:
    try:
        with get_transaction() as conn:
            conn.execute(text("""
                INSERT INTO il_project_variance (
                    project_id, cogs_category,
                    estimated_amount, actual_amount,
                    root_cause, corrective_action, impact_assessment,
                    coefficient_used, coefficient_actual, coefficient_recommended,
                    created_by, modified_by
                ) VALUES (
                    :pid, :cat,
                    :est, :act,
                    :rc, :ca, :impact,
                    :cu, :cact, :crec,
                    :m, :m
                )
                ON DUPLICATE KEY UPDATE
                    estimated_amount = :est, actual_amount = :act,
                    root_cause = :rc, corrective_action = :ca,
                    impact_assessment = :impact,
                    coefficient_used = :cu, coefficient_actual = :cact,
                    coefficient_recommended = :crec,
                    modified_by = :m, version = version + 1
            """), {
                'pid': project_id, 'cat': category,
                'est': estimated, 'act': actual,
                'rc': root_cause, 'ca': corrective_action,
                'impact': impact,
                'cu': coeff_used, 'cact': coeff_actual, 'crec': coeff_rec,
                'm': modified_by,
            })
        return True
    except Exception as e:
        logger.error(f"upsert_variance_row failed: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# BENCHMARKS
# ══════════════════════════════════════════════════════════════════════════════

@log_perf
def get_benchmarks_df(type_id: Optional[int] = None) -> pd.DataFrame:
    sql = """
        SELECT b.id, pt.name AS project_type, pt.code AS type_code,
               p.project_code AS source_project,
               b.benchmark_date,
               b.alpha_used, b.alpha_actual, b.alpha_recommended,
               b.beta_used,  b.beta_actual,  b.beta_recommended,
               b.gamma_used, b.gamma_actual, b.gamma_recommended,
               b.man_days_estimated, b.man_days_actual,
               b.gp_estimated_percent, b.gp_actual_percent,
               b.lessons_learned
        FROM il_benchmarks b
        JOIN il_project_types pt ON b.project_type_id = pt.id
        LEFT JOIN il_projects  p  ON b.source_project_id = p.id
        WHERE b.delete_flag = 0
    """
    params: Dict = {}
    if type_id:
        sql += " AND b.project_type_id = :tid"
        params['tid'] = type_id
    sql += " ORDER BY b.benchmark_date DESC"
    return execute_query_df(sql, params)


def create_benchmark(data: Dict, created_by: str) -> int:
    sql = """
        INSERT INTO il_benchmarks (
            project_type_id, source_project_id, benchmark_date,
            alpha_used, alpha_actual, alpha_recommended,
            beta_used,  beta_actual,  beta_recommended,
            gamma_used, gamma_actual, gamma_recommended,
            man_days_estimated, man_days_actual, man_days_by_phase,
            gp_estimated_percent, gp_actual_percent,
            lessons_learned, key_risk_factors, recommendations,
            created_by, modified_by
        ) VALUES (
            :project_type_id, :source_project_id, :benchmark_date,
            :alpha_used, :alpha_actual, :alpha_recommended,
            :beta_used,  :beta_actual,  :beta_recommended,
            :gamma_used, :gamma_actual, :gamma_recommended,
            :man_days_estimated, :man_days_actual, :man_days_by_phase,
            :gp_estimated_percent, :gp_actual_percent,
            :lessons_learned, :key_risk_factors, :recommendations,
            :created_by, :created_by
        )
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), {**data, 'created_by': created_by})
        conn.commit()
        return result.lastrowid


# ── Internal helper ────────────────────────────────────────────────────────────

def _get_engine():
    from ..db import get_db_engine
    return get_db_engine()


# ══════════════════════════════════════════════════════════════════════════════
# PRODUCTS & COSTBOOK LOOKUP — for Estimate line items
# ══════════════════════════════════════════════════════════════════════════════

def search_products(search: str = '', is_service: Optional[bool] = None, limit: int = 50) -> List[Dict]:
    """Search products by name or pt_code. For Estimate GP product picker."""
    sql = """
        SELECT p.id, p.name, p.pt_code, p.uom, p.package_size,
               p.is_service, b.brand_name
        FROM products p
        LEFT JOIN brands b ON p.brand_id = b.id
        WHERE p.delete_flag = 0
    """
    params: Dict = {}
    if search:
        sql += " AND (p.name LIKE :s OR p.pt_code LIKE :s)"
        params['s'] = f"%{search}%"
    if is_service is not None:
        sql += " AND p.is_service = :svc"
        params['svc'] = 1 if is_service else 0
    sql += " ORDER BY p.name LIMIT :lim"
    params['lim'] = limit
    return execute_query(sql, params)


def get_costbook_for_product(product_id: int) -> List[Dict]:
    """
    Find costbook entries (vendor cost) for a product.
    Returns active + recently expired, sorted by date DESC.
    """
    return execute_query("""
        SELECT
            cd.id AS costbook_detail_id,
            cb.costbook_number, cb.vendor_quote_number,
            v.english_name AS vendor_name,
            cd.unit_price, cd.purchase_unit_price,
            cur.code AS currency_code, cur.id AS currency_id,
            cb.costbook_date, cb.valid_to,
            CASE
                WHEN cb.valid_to IS NULL THEN 'No Expiry'
                WHEN cb.valid_to >= CURDATE() THEN 'Active'
                ELSE 'Expired'
            END AS status
        FROM costbook_details cd
        JOIN costbooks cb ON cd.costbook_id = cb.id AND cb.delete_flag = 0 AND cb.is_approved = 1
        JOIN products p ON cd.product_id = p.id
        LEFT JOIN companies v ON cb.vendor_id = v.id
        LEFT JOIN currencies cur ON cd.product_currency_id = cur.id
        WHERE cd.product_id = :pid AND cd.delete_flag = 0 AND cd.is_active = 1
        ORDER BY
            CASE WHEN cb.valid_to IS NULL OR cb.valid_to >= CURDATE() THEN 0 ELSE 1 END,
            cb.costbook_date DESC
        LIMIT 10
    """, {'pid': product_id})


def get_quotation_for_product(product_id: int, customer_id: Optional[int] = None) -> List[Dict]:
    """
    Find quotation entries (selling price) for a product.
    Optionally filter by customer (buyer_id = project's customer).
    """
    sql = """
        SELECT
            qd.id AS quotation_detail_id,
            q.quotation_number,
            buyer.english_name AS customer_name,
            qd.selling_unit_price, qd.quantity,
            cur.code AS currency_code, cur.id AS currency_id,
            q.quotation_date, q.valid_to,
            CASE
                WHEN q.valid_to IS NULL THEN 'No Expiry'
                WHEN q.valid_to >= CURDATE() THEN 'Active'
                ELSE 'Expired'
            END AS status
        FROM quotation_details qd
        JOIN quotations q ON qd.quotation_id = q.id AND q.delete_flag = 0 AND q.is_approved = 1
        LEFT JOIN companies buyer ON q.buyer_id = buyer.id
        LEFT JOIN currencies cur ON q.currency_id = cur.id
        WHERE qd.product_id = :pid AND qd.delete_flag = 0
    """
    params: Dict = {'pid': product_id}
    if customer_id:
        sql += " AND q.buyer_id = :cid"
        params['cid'] = customer_id
    sql += " ORDER BY q.quotation_date DESC LIMIT 10"
    return execute_query(sql, params)


# ══════════════════════════════════════════════════════════════════════════════
# ESTIMATE LINE ITEMS — CRUD
# ══════════════════════════════════════════════════════════════════════════════

@log_perf
def get_estimate_line_items(estimate_id: int) -> pd.DataFrame:
    return execute_query_df("""
        SELECT
            li.id, li.cogs_category, li.product_id,
            li.item_description, li.brand_name, li.pt_code,
            li.costbook_detail_id, li.vendor_name, li.vendor_quote_ref, li.costbook_number,
            li.unit_cost, cc.code AS cost_currency, li.cost_exchange_rate,
            li.quotation_detail_id,
            li.unit_sell, sc.code AS sell_currency, li.sell_exchange_rate,
            li.quantity, li.uom,
            li.amount_cost_vnd, li.amount_sell_vnd,
            li.notes, li.view_order
        FROM il_estimate_line_items li
        LEFT JOIN currencies cc ON li.cost_currency_id = cc.id
        LEFT JOIN currencies sc ON li.sell_currency_id = sc.id
        WHERE li.estimate_id = :eid AND li.delete_flag = 0
        ORDER BY li.cogs_category, li.view_order, li.id
    """, {'eid': estimate_id})


def create_estimate_line_item(data: Dict, created_by: str) -> int:
    sql = """
        INSERT INTO il_estimate_line_items (
            estimate_id, cogs_category, product_id,
            item_description, brand_name, pt_code,
            costbook_detail_id, vendor_name, vendor_quote_ref, costbook_number,
            unit_cost, cost_currency_id, cost_exchange_rate,
            quotation_detail_id, unit_sell, sell_currency_id, sell_exchange_rate,
            quantity, uom, notes, view_order, created_by
        ) VALUES (
            :estimate_id, :cogs_category, :product_id,
            :item_description, :brand_name, :pt_code,
            :costbook_detail_id, :vendor_name, :vendor_quote_ref, :costbook_number,
            :unit_cost, :cost_currency_id, :cost_exchange_rate,
            :quotation_detail_id, :unit_sell, :sell_currency_id, :sell_exchange_rate,
            :quantity, :uom, :notes, :view_order, :created_by
        )
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), {**data, 'created_by': created_by})
        conn.commit()
        return result.lastrowid


def delete_estimate_line_item(item_id: int) -> bool:
    rows = execute_update(
        "UPDATE il_estimate_line_items SET delete_flag=1 WHERE id=:id",
        {'id': item_id}
    )
    return rows > 0


def get_costbook_products_for_import(costbook_id: int) -> List[Dict]:
    """Get all products from a costbook for bulk import into estimate."""
    return execute_query("""
        SELECT
            cd.id AS costbook_detail_id,
            cd.product_id, p.name AS product_name, p.pt_code, p.uom, p.is_service,
            b.brand_name,
            cd.unit_price, cd.purchase_unit_price,
            cur.code AS currency_code, cur.id AS currency_id,
            cb.costbook_number, cb.vendor_quote_number,
            v.english_name AS vendor_name
        FROM costbook_details cd
        JOIN costbooks cb ON cd.costbook_id = cb.id
        JOIN products p ON cd.product_id = p.id
        LEFT JOIN brands b ON p.brand_id = b.id
        LEFT JOIN currencies cur ON cd.product_currency_id = cur.id
        LEFT JOIN companies v ON cb.vendor_id = v.id
        WHERE cd.costbook_id = :cbid AND cd.delete_flag = 0 AND cd.is_active = 1
        ORDER BY cd.view_order, cd.id
    """, {'cbid': costbook_id})


def get_active_costbooks() -> List[Dict]:
    """Get list of active/valid costbooks for import dropdown."""
    return execute_query("""
        SELECT
            cb.id, cb.costbook_number, cb.vendor_quote_number,
            v.english_name AS vendor_name,
            cb.costbook_date, cb.valid_to,
            COUNT(cd.id) AS line_count,
            CASE
                WHEN cb.valid_to IS NULL THEN 'No Expiry'
                WHEN cb.valid_to >= CURDATE() THEN 'Active'
                ELSE 'Expired'
            END AS status
        FROM costbooks cb
        JOIN costbook_details cd ON cb.id = cd.costbook_id AND cd.delete_flag = 0 AND cd.is_active = 1
        LEFT JOIN companies v ON cb.vendor_id = v.id
        WHERE cb.delete_flag = 0 AND cb.is_approved = 1
        GROUP BY cb.id
        ORDER BY
            CASE WHEN cb.valid_to IS NULL OR cb.valid_to >= CURDATE() THEN 0 ELSE 1 END,
            cb.costbook_date DESC
        LIMIT 50
    """)


# ══════════════════════════════════════════════════════════════════════════════
# MEDIA HELPERS — Pattern A (shared across all IL entities)
# ══════════════════════════════════════════════════════════════════════════════

def _create_media(s3_key: str, filename: str, created_by: str) -> int:
    """
    Insert into medias table. Returns media_id.
    medias.path = S3 key, medias.name = original filename.
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO medias (name, path, created_by, created_date, version)
            VALUES (:name, :path, :created_by, NOW(), 0)
        """), {'name': filename, 'path': s3_key, 'created_by': created_by})
        conn.commit()
        return result.lastrowid


# ══════════════════════════════════════════════════════════════════════════════
# ESTIMATE MEDIAS — Pattern A (replaces il_estimate_attachments)
# ══════════════════════════════════════════════════════════════════════════════

def create_estimate_media(
    estimate_id: int, s3_key: str, filename: str,
    document_type: str = 'OTHER', description: Optional[str] = None,
    created_by: str = None,
) -> int:
    """Attach file to estimate via medias + il_estimate_medias junction."""
    media_id = _create_media(s3_key, filename, created_by)
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO il_estimate_medias
                (estimate_id, media_id, document_type, description,
                 delete_flag, created_by, created_date)
            VALUES (:eid, :mid, :dtype, :desc, 0, :by, NOW())
        """), {
            'eid': estimate_id, 'mid': media_id,
            'dtype': document_type, 'desc': description, 'by': created_by,
        })
        conn.commit()
        return result.lastrowid


def get_estimate_medias(estimate_id: int) -> List[Dict]:
    """List all attachments for an estimate."""
    return execute_query("""
        SELECT
            em.id AS junction_id, em.media_id,
            m.path AS s3_key, m.name AS filename,
            em.document_type, em.description,
            em.created_by, em.created_date
        FROM il_estimate_medias em
        JOIN medias m ON em.media_id = m.id
        WHERE em.estimate_id = :eid AND em.delete_flag = 0
        ORDER BY em.created_date DESC
    """, {'eid': estimate_id})


def delete_estimate_media(junction_id: int) -> bool:
    """Soft-delete estimate attachment."""
    rows = execute_update(
        "UPDATE il_estimate_medias SET delete_flag=1 WHERE id=:id",
        {'id': junction_id}
    )
    return rows > 0


# ══════════════════════════════════════════════════════════════════════════════
# ESTIMATE LINE ITEM MEDIAS — Pattern A (replaces inline columns)
# ══════════════════════════════════════════════════════════════════════════════

def create_line_item_media(
    line_item_id: int, s3_key: str, filename: str,
    created_by: str = None,
) -> int:
    """Attach file to estimate line item. Supports multi-file per item."""
    media_id = _create_media(s3_key, filename, created_by)
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO il_estimate_line_item_medias
                (line_item_id, media_id, delete_flag, created_by, created_date)
            VALUES (:lid, :mid, 0, :by, NOW())
        """), {'lid': line_item_id, 'mid': media_id, 'by': created_by})
        conn.commit()
        return result.lastrowid


def get_line_item_medias(estimate_id: int) -> List[Dict]:
    """Get all attachments for all line items of an estimate."""
    return execute_query("""
        SELECT
            lm.id AS junction_id, lm.line_item_id,
            m.path AS s3_key, m.name AS filename,
            lm.created_by, lm.created_date
        FROM il_estimate_line_item_medias lm
        JOIN medias m ON lm.media_id = m.id
        WHERE lm.line_item_id IN (
            SELECT id FROM il_estimate_line_items
            WHERE estimate_id = :eid AND delete_flag = 0
        )
        AND lm.delete_flag = 0
        ORDER BY lm.line_item_id, lm.created_date
    """, {'eid': estimate_id})


def delete_line_item_media(junction_id: int) -> bool:
    """Soft-delete line item attachment."""
    rows = execute_update(
        "UPDATE il_estimate_line_item_medias SET delete_flag=1 WHERE id=:id",
        {'id': junction_id}
    )
    return rows > 0


# ══════════════════════════════════════════════════════════════════════════════
# EXPENSE MEDIAS — Pattern A (junction table already existed in DDL)
# ══════════════════════════════════════════════════════════════════════════════

def create_expense_media(
    expense_id: int, s3_key: str, filename: str,
    created_by: str = None,
) -> int:
    """Attach file to expense via il_project_expense_medias."""
    media_id = _create_media(s3_key, filename, created_by)
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO il_project_expense_medias
                (expense_id, media_id, delete_flag, created_by, created_date)
            VALUES (:eid, :mid, 0, :by, NOW())
        """), {'eid': expense_id, 'mid': media_id, 'by': created_by})
        conn.commit()
        return result.lastrowid


def get_expense_medias(expense_id: int) -> List[Dict]:
    """Get all attachments for an expense."""
    return execute_query("""
        SELECT
            em.id AS junction_id, em.media_id,
            m.path AS s3_key, m.name AS filename,
            em.created_by, em.created_date
        FROM il_project_expense_medias em
        JOIN medias m ON em.media_id = m.id
        WHERE em.expense_id = :eid AND em.delete_flag = 0
        ORDER BY em.created_date
    """, {'eid': expense_id})


def delete_expense_media(junction_id: int) -> bool:
    """Soft-delete expense attachment."""
    rows = execute_update(
        "UPDATE il_project_expense_medias SET delete_flag=1 WHERE id=:id",
        {'id': junction_id}
    )
    return rows > 0


# ══════════════════════════════════════════════════════════════════════════════
# LABOR LOG MEDIAS — Pattern A (junction table already existed in DDL)
# ══════════════════════════════════════════════════════════════════════════════

def create_labor_media(
    labor_log_id: int, s3_key: str, filename: str,
    created_by: str = None,
) -> int:
    """Attach file to labor log via il_project_labor_log_medias."""
    media_id = _create_media(s3_key, filename, created_by)
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO il_project_labor_log_medias
                (labor_log_id, media_id, delete_flag, created_by, created_date)
            VALUES (:lid, :mid, 0, :by, NOW())
        """), {'lid': labor_log_id, 'mid': media_id, 'by': created_by})
        conn.commit()
        return result.lastrowid


def get_labor_medias(labor_log_id: int) -> List[Dict]:
    """Get all attachments for a labor log."""
    return execute_query("""
        SELECT
            lm.id AS junction_id, lm.media_id,
            m.path AS s3_key, m.name AS filename,
            lm.created_by, lm.created_date
        FROM il_project_labor_log_medias lm
        JOIN medias m ON lm.media_id = m.id
        WHERE lm.labor_log_id = :lid AND lm.delete_flag = 0
        ORDER BY lm.created_date
    """, {'lid': labor_log_id})


def delete_labor_media(junction_id: int) -> bool:
    """Soft-delete labor log attachment."""
    rows = execute_update(
        "UPDATE il_project_labor_log_medias SET delete_flag=1 WHERE id=:id",
        {'id': junction_id}
    )
    return rows > 0