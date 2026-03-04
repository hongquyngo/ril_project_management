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

logger = logging.getLogger(__name__)


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


def generate_project_code() -> str:
    """
    Generate next unique project code: IL-YYYY-NNN
    Finds the highest NNN for current year and increments.
    """
    from datetime import date
    year = date.today().year
    rows = execute_query("""
        SELECT project_code
        FROM il_projects
        WHERE project_code LIKE :pattern
        ORDER BY project_code DESC
        LIMIT 1
    """, {'pattern': f'IL-{year}-%'})

    if rows:
        try:
            last_seq = int(rows[0]['project_code'].split('-')[-1])
        except (ValueError, IndexError):
            last_seq = 0
    else:
        last_seq = 0

    return f"IL-{year}-{last_seq + 1:03d}"


# ══════════════════════════════════════════════════════════════════════════════
# PROJECTS
# ══════════════════════════════════════════════════════════════════════════════

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


def create_estimate(data: Dict, created_by: str) -> int:
    """
    Insert new estimate. Caller must call activate_estimate() in same
    transaction if this should be the active one.
    """
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


def activate_estimate(project_id: int, estimate_id: int, modified_by: str) -> bool:
    """
    Atomically deactivate all other estimates → activate the target.
    App-layer replacement for the removed trigger.
    """
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

def get_labor_logs_df(
    project_id: int,
    phase: Optional[str] = None,
    approval_status: Optional[str] = None,
) -> pd.DataFrame:
    sql = """
        SELECT
            ll.id, ll.work_date, ll.phase,
            COALESCE(CONCAT(e.first_name,' ',e.last_name), ll.subcontractor_name) AS worker,
            ll.employee_level, ll.is_on_site,
            ll.man_days, ll.daily_rate, ll.amount,
            ll.description, ll.approval_status, ll.presales_allocation,
            CONCAT(ap.first_name,' ',ap.last_name) AS approved_by_name,
            ll.approved_date
        FROM il_project_labor_logs ll
        LEFT JOIN employees e  ON ll.employee_id  = e.id
        LEFT JOIN employees ap ON ll.approved_by  = ap.id
        WHERE ll.project_id = :pid AND ll.delete_flag = 0
    """
    params: Dict = {'pid': project_id}
    if phase:
        sql += " AND ll.phase = :phase"
        params['phase'] = phase
    if approval_status:
        sql += " AND ll.approval_status = :as_"
        params['as_'] = approval_status
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
            modified_by = :modified_by, version = version + 1
        WHERE id = :id AND delete_flag = 0 AND approval_status = 'PENDING'
    """
    rows = execute_update(sql, {**data, 'id': log_id, 'modified_by': modified_by})
    return rows > 0


def approve_labor_log(log_id: int, approved_by: int, status: str = 'APPROVED') -> bool:
    rows = execute_update("""
        UPDATE il_project_labor_logs
        SET approval_status = :status, approved_by = :by, approved_date = NOW()
        WHERE id = :id AND delete_flag = 0
    """, {'id': log_id, 'by': approved_by, 'status': status})
    return rows > 0


def soft_delete_labor_log(log_id: int, modified_by: str) -> bool:
    rows = execute_update(
        "UPDATE il_project_labor_logs SET delete_flag=1, modified_by=:m WHERE id=:id AND approval_status='PENDING'",
        {'id': log_id, 'm': modified_by}
    )
    return rows > 0


# ══════════════════════════════════════════════════════════════════════════════
# EXPENSES
# ══════════════════════════════════════════════════════════════════════════════

def get_expenses_df(
    project_id: int,
    phase: Optional[str] = None,
    approval_status: Optional[str] = None,
) -> pd.DataFrame:
    sql = """
        SELECT
            ex.id, ex.expense_date, ex.category, ex.phase,
            CONCAT(e.first_name,' ',e.last_name) AS employee_name,
            ex.amount, cur.code AS currency, ex.exchange_rate, ex.amount_vnd,
            ex.description, ex.vendor_name, ex.receipt_number,
            ex.approval_status,
            CONCAT(ap.first_name,' ',ap.last_name) AS approved_by_name
        FROM il_project_expenses ex
        LEFT JOIN employees  e  ON ex.employee_id  = e.id
        LEFT JOIN employees  ap ON ex.approved_by  = ap.id
        LEFT JOIN currencies cur ON ex.currency_id = cur.id
        WHERE ex.project_id = :pid AND ex.delete_flag = 0
    """
    params: Dict = {'pid': project_id}
    if phase:
        sql += " AND ex.phase = :phase"
        params['phase'] = phase
    if approval_status:
        sql += " AND ex.approval_status = :as_"
        params['as_'] = approval_status
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
    rows = execute_update("""
        UPDATE il_project_expenses
        SET approval_status = :status, approved_by = :by, approved_date = NOW()
        WHERE id = :id AND delete_flag = 0
    """, {'id': expense_id, 'by': approved_by, 'status': status})
    return rows > 0


def soft_delete_expense(expense_id: int, modified_by: str) -> bool:
    rows = execute_update(
        "UPDATE il_project_expenses SET delete_flag=1, modified_by=:m WHERE id=:id AND approval_status='PENDING'",
        {'id': expense_id, 'm': modified_by}
    )
    return rows > 0


# ══════════════════════════════════════════════════════════════════════════════
# PRE-SALES COSTS
# ══════════════════════════════════════════════════════════════════════════════

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
        SET allocation = :alloc, allocation_date = CURDATE(), modified_by = :m, version = version + 1
        WHERE project_id = :pid AND cost_layer = :layer AND delete_flag = 0
    """, {'pid': project_id, 'alloc': allocation, 'm': modified_by, 'layer': layer})
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


def sync_cogs_actual(project_id: int, modified_by: str) -> Dict:
    """
    Aggregate from detail tables → upsert il_project_cogs_actual.
    Returns the computed values dict.
    """
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
                    'total': 0, 'sales': sales_val, 'gp': 0, 'gp_pct': 0,
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


def update_cogs_actual_fields(project_id: int, data: Dict, modified_by: str) -> bool:
    """Manual override of A, B, C, F fields."""
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


def finalize_cogs_actual(project_id: int, finalized_by: str) -> bool:
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