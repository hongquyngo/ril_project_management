# utils/il_project/execution_queries.py
"""
Database layer for IL Project Execution Tracking:
  - Issues, Risks, Change Orders, Progress Reports, Quality Checklists
  - Shared media CRUD via junction → medias (Pattern A)

Attachment pattern:
  1. Upload file to S3 → get s3_key
  2. INSERT into medias(name, path) → get media_id
  3. INSERT into il_{entity}_medias(entity_id, media_id)
  Multi-file per entity. Consistent with all 25 junction tables in rozitek.
"""

import logging
from typing import Dict, List, Optional
import pandas as pd
from sqlalchemy import text
from ..db import execute_query, execute_query_df, execute_update, get_transaction

logger = logging.getLogger(__name__)


def _get_engine():
    from ..db import get_db_engine
    return get_db_engine()


# ══════════════════════════════════════════════════════════════════════════════
# SHARED MEDIA CRUD (Pattern A: junction → medias)
# ══════════════════════════════════════════════════════════════════════════════

def _create_media_record(name: str, path: str, created_by: str) -> int:
    """Insert into central medias table. Returns media_id."""
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO medias (name, path, created_by, created_date)
            VALUES (:name, :path, :created_by, NOW())
        """), {'name': name, 'path': path, 'created_by': created_by})
        conn.commit()
        return result.lastrowid


# ── Config per entity type ────────────────────────────────────────────────────

_MEDIA_CONFIG = {
    'task':              {'table': 'il_task_media',               'fk': 'task_id'},
    'issue':             {'table': 'il_issue_medias',             'fk': 'issue_id'},
    'risk':              {'table': 'il_risk_medias',              'fk': 'risk_id'},
    'change_order':      {'table': 'il_change_order_medias',      'fk': 'change_order_id'},
    'progress_report':   {'table': 'il_progress_report_medias',   'fk': 'report_id'},
    'quality_checklist': {'table': 'il_quality_checklist_medias', 'fk': 'checklist_id'},
}


def get_entity_medias(entity_type: str, entity_id: int) -> List[Dict]:
    """Get all media attachments for an entity."""
    cfg = _MEDIA_CONFIG.get(entity_type)
    if not cfg:
        return []
    return execute_query(f"""
        SELECT jt.id AS junction_id, jt.description, jt.created_date, jt.created_by,
               m.id AS media_id, m.name AS file_name, m.path AS s3_key
        FROM {cfg['table']} jt
        JOIN medias m ON jt.media_id = m.id
        WHERE jt.{cfg['fk']} = :eid AND jt.delete_flag = 0
        ORDER BY jt.created_date DESC
    """, {'eid': entity_id})


def link_media(entity_type: str, entity_id: int, media_id: int,
               description: str = None, created_by: str = None) -> int:
    """Link a media record to an entity via junction table."""
    cfg = _MEDIA_CONFIG.get(entity_type)
    if not cfg:
        raise ValueError(f"Unknown entity_type: {entity_type}")
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(f"""
            INSERT INTO {cfg['table']} ({cfg['fk']}, media_id, description, created_by, created_date)
            VALUES (:eid, :mid, :desc, :cb, NOW())
        """), {'eid': entity_id, 'mid': media_id, 'desc': description, 'cb': created_by})
        conn.commit()
        return result.lastrowid


def unlink_media(entity_type: str, junction_id: int) -> bool:
    """Soft-delete a junction record (does not delete the media record)."""
    cfg = _MEDIA_CONFIG.get(entity_type)
    if not cfg:
        return False
    return execute_update(
        f"UPDATE {cfg['table']} SET delete_flag=1 WHERE id=:id",
        {'id': junction_id}
    ) > 0


def upload_and_attach(
    entity_type: str,
    entity_id: int,
    project_id: int,
    file_content: bytes,
    filename: str,
    description: str = None,
    created_by: str = None,
) -> bool:
    """
    Full flow: S3 upload → medias record → junction link.
    Non-blocking: returns False on failure.
    """
    try:
        from .s3_il import ILProjectS3Manager
        s3 = ILProjectS3Manager()

        from datetime import datetime
        ts = int(datetime.now().timestamp() * 1000)
        safe = filename.replace(" ", "_")
        subfolder = {
            'task': 'tasks', 'issue': 'issues', 'risk': 'risks',
            'change_order': 'change_orders',
            'progress_report': 'progress_reports', 'quality_checklist': 'quality_checklists',
        }.get(entity_type, entity_type)
        s3_key = f"il-project-file/{project_id}/{subfolder}/{entity_id}/{ts}_{safe}"

        ok, result = s3.upload_file(file_content, s3_key, s3._content_type(filename))
        if not ok:
            logger.error(f"S3 upload failed for {entity_type} {entity_id}: {result}")
            return False

        media_id = _create_media_record(filename, s3_key, created_by or '')
        link_media(entity_type, entity_id, media_id, description, created_by)
        logger.info(f"Attached {filename} to {entity_type} #{entity_id} (media_id={media_id})")
        return True

    except Exception as e:
        logger.error(f"upload_and_attach failed: {e}")
        return False


def get_attachment_url(s3_key: str) -> Optional[str]:
    """Get presigned download URL for an S3 key."""
    if not s3_key:
        return None
    try:
        from .s3_il import ILProjectS3Manager
        s3 = ILProjectS3Manager()
        return s3.get_presigned_url(s3_key)
    except Exception as e:
        logger.error(f"get_attachment_url failed: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# ISSUES
# ══════════════════════════════════════════════════════════════════════════════

def get_issues_df(
    project_id: int,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    category: Optional[str] = None,
    assigned_to: Optional[int] = None,
) -> pd.DataFrame:
    sql = """
        SELECT
            i.id, i.issue_code, i.title, i.category, i.severity, i.status,
            CONCAT(rp.first_name,' ',rp.last_name) AS reported_by_name,
            CONCAT(asg.first_name,' ',asg.last_name) AS assigned_to_name,
            i.reported_date, i.due_date, i.resolved_date,
            i.impact_description, i.related_task_id,
            t.task_name AS related_task_name,
            (SELECT COUNT(*) FROM il_issue_medias im
             WHERE im.issue_id = i.id AND im.delete_flag = 0) AS file_count
        FROM il_project_issues i
        LEFT JOIN employees rp  ON i.reported_by  = rp.id
        LEFT JOIN employees asg ON i.assigned_to  = asg.id
        LEFT JOIN il_project_tasks t ON i.related_task_id = t.id
        WHERE i.project_id = :pid AND i.delete_flag = 0
    """
    params: Dict = {'pid': project_id}
    if status:
        sql += " AND i.status = :status"
        params['status'] = status
    if severity:
        sql += " AND i.severity = :severity"
        params['severity'] = severity
    if category:
        sql += " AND i.category = :category"
        params['category'] = category
    if assigned_to:
        sql += " AND i.assigned_to = :assigned_to"
        params['assigned_to'] = assigned_to
    sql += " ORDER BY FIELD(i.severity,'CRITICAL','HIGH','MEDIUM','LOW'), i.created_date DESC"
    return execute_query_df(sql, params)


def get_issue(issue_id: int) -> Optional[Dict]:
    rows = execute_query("""
        SELECT i.*,
               CONCAT(rp.first_name,' ',rp.last_name) AS reported_by_name,
               CONCAT(asg.first_name,' ',asg.last_name) AS assigned_to_name,
               t.task_name AS related_task_name
        FROM il_project_issues i
        LEFT JOIN employees rp  ON i.reported_by  = rp.id
        LEFT JOIN employees asg ON i.assigned_to  = asg.id
        LEFT JOIN il_project_tasks t ON i.related_task_id = t.id
        WHERE i.id = :id AND i.delete_flag = 0
    """, {'id': issue_id})
    return rows[0] if rows else None


def generate_issue_code(project_id: int) -> str:
    rows = execute_query(
        "SELECT COUNT(*) AS cnt FROM il_project_issues WHERE project_id = :pid AND delete_flag = 0",
        {'pid': project_id},
    )
    return f"ISS-{(rows[0]['cnt'] if rows else 0) + 1:03d}"


def create_issue(data: Dict, created_by: str) -> int:
    sql = """
        INSERT INTO il_project_issues (
            project_id, issue_code, title, description,
            category, severity, status,
            reported_by, assigned_to, reported_date, due_date,
            impact_description, related_task_id,
            created_by, modified_by, created_date, modified_date
        ) VALUES (
            :project_id, :issue_code, :title, :description,
            :category, :severity, :status,
            :reported_by, :assigned_to, :reported_date, :due_date,
            :impact_description, :related_task_id,
            :created_by, :created_by, NOW(), NOW()
        )
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), {**data, 'created_by': created_by})
        conn.commit()
        return result.lastrowid


def update_issue(issue_id: int, data: Dict, modified_by: str) -> bool:
    sql = """
        UPDATE il_project_issues SET
            title = :title, description = :description,
            category = :category, severity = :severity, status = :status,
            assigned_to = :assigned_to, due_date = :due_date,
            resolved_date = :resolved_date, resolution = :resolution,
            impact_description = :impact_description, related_task_id = :related_task_id,
            modified_by = :modified_by, modified_date = NOW(),
            version = version + 1
        WHERE id = :id AND delete_flag = 0
    """
    return execute_update(sql, {**data, 'id': issue_id, 'modified_by': modified_by}) > 0


def soft_delete_issue(issue_id: int, modified_by: str) -> bool:
    return execute_update(
        "UPDATE il_project_issues SET delete_flag=1, modified_by=:m, modified_date=NOW() WHERE id=:id",
        {'id': issue_id, 'm': modified_by}
    ) > 0


# ══════════════════════════════════════════════════════════════════════════════
# RISKS
# ══════════════════════════════════════════════════════════════════════════════

PROBABILITY_VALUES = {'RARE': 1, 'UNLIKELY': 2, 'POSSIBLE': 3, 'LIKELY': 4, 'ALMOST_CERTAIN': 5}
IMPACT_VALUES = {'NEGLIGIBLE': 1, 'MINOR': 2, 'MODERATE': 3, 'MAJOR': 4, 'SEVERE': 5}


def calc_risk_score(probability: str, impact: str) -> int:
    return PROBABILITY_VALUES.get(probability, 3) * IMPACT_VALUES.get(impact, 3)


def get_risks_df(project_id: int, status: Optional[str] = None) -> pd.DataFrame:
    sql = """
        SELECT
            r.id, r.risk_code, r.title, r.category,
            r.probability, r.impact, r.risk_score, r.status,
            CONCAT(e.first_name,' ',e.last_name) AS owner_name,
            r.identified_date, r.review_date,
            (SELECT COUNT(*) FROM il_risk_medias rm
             WHERE rm.risk_id = r.id AND rm.delete_flag = 0) AS file_count
        FROM il_project_risks r
        LEFT JOIN employees e ON r.owner_id = e.id
        WHERE r.project_id = :pid AND r.delete_flag = 0
    """
    params: Dict = {'pid': project_id}
    if status:
        sql += " AND r.status = :status"
        params['status'] = status
    sql += " ORDER BY r.risk_score DESC, r.created_date DESC"
    return execute_query_df(sql, params)


def get_risk(risk_id: int) -> Optional[Dict]:
    rows = execute_query("""
        SELECT r.*, CONCAT(e.first_name,' ',e.last_name) AS owner_name
        FROM il_project_risks r
        LEFT JOIN employees e ON r.owner_id = e.id
        WHERE r.id = :id AND r.delete_flag = 0
    """, {'id': risk_id})
    return rows[0] if rows else None


def generate_risk_code(project_id: int) -> str:
    rows = execute_query(
        "SELECT COUNT(*) AS cnt FROM il_project_risks WHERE project_id = :pid AND delete_flag = 0",
        {'pid': project_id},
    )
    return f"RSK-{(rows[0]['cnt'] if rows else 0) + 1:03d}"


def create_risk(data: Dict, created_by: str) -> int:
    data['risk_score'] = calc_risk_score(data.get('probability', 'POSSIBLE'), data.get('impact', 'MODERATE'))
    sql = """
        INSERT INTO il_project_risks (
            project_id, risk_code, title, description,
            category, probability, impact, risk_score, status,
            mitigation_plan, contingency_plan,
            owner_id, identified_date, review_date,
            created_by, modified_by, created_date, modified_date
        ) VALUES (
            :project_id, :risk_code, :title, :description,
            :category, :probability, :impact, :risk_score, :status,
            :mitigation_plan, :contingency_plan,
            :owner_id, :identified_date, :review_date,
            :created_by, :created_by, NOW(), NOW()
        )
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), {**data, 'created_by': created_by})
        conn.commit()
        return result.lastrowid


def update_risk(risk_id: int, data: Dict, modified_by: str) -> bool:
    data['risk_score'] = calc_risk_score(data.get('probability', 'POSSIBLE'), data.get('impact', 'MODERATE'))
    sql = """
        UPDATE il_project_risks SET
            title = :title, description = :description,
            category = :category, probability = :probability,
            impact = :impact, risk_score = :risk_score, status = :status,
            mitigation_plan = :mitigation_plan, contingency_plan = :contingency_plan,
            owner_id = :owner_id, review_date = :review_date,
            modified_by = :modified_by, modified_date = NOW(),
            version = version + 1
        WHERE id = :id AND delete_flag = 0
    """
    return execute_update(sql, {**data, 'id': risk_id, 'modified_by': modified_by}) > 0


def soft_delete_risk(risk_id: int, modified_by: str) -> bool:
    return execute_update(
        "UPDATE il_project_risks SET delete_flag=1, modified_by=:m, modified_date=NOW() WHERE id=:id",
        {'id': risk_id, 'm': modified_by}
    ) > 0


def get_risk_matrix_summary(project_id: int) -> List[Dict]:
    return execute_query("""
        SELECT probability, impact, COUNT(*) AS cnt
        FROM il_project_risks
        WHERE project_id = :pid AND delete_flag = 0 AND status NOT IN ('CLOSED')
        GROUP BY probability, impact
    """, {'pid': project_id})


# ══════════════════════════════════════════════════════════════════════════════
# CHANGE ORDERS
# ══════════════════════════════════════════════════════════════════════════════

def get_change_orders_df(project_id: int, status: Optional[str] = None) -> pd.DataFrame:
    sql = """
        SELECT
            co.id, co.co_number, co.title, co.change_type, co.status,
            co.cost_impact, cur.code AS currency_code,
            co.schedule_impact_days,
            CONCAT(req.first_name,' ',req.last_name) AS requested_by_name,
            CONCAT(apr.first_name,' ',apr.last_name) AS approved_by_name,
            co.requested_date, co.approved_date, co.customer_approval,
            (SELECT COUNT(*) FROM il_change_order_medias cm
             WHERE cm.change_order_id = co.id AND cm.delete_flag = 0) AS file_count
        FROM il_change_orders co
        LEFT JOIN currencies cur ON co.currency_id = cur.id
        LEFT JOIN employees req  ON co.requested_by = req.id
        LEFT JOIN employees apr  ON co.approved_by  = apr.id
        WHERE co.project_id = :pid AND co.delete_flag = 0
    """
    params: Dict = {'pid': project_id}
    if status:
        sql += " AND co.status = :status"
        params['status'] = status
    sql += " ORDER BY co.created_date DESC"
    return execute_query_df(sql, params)


def get_change_order(co_id: int) -> Optional[Dict]:
    rows = execute_query("""
        SELECT co.*,
               cur.code AS currency_code,
               CONCAT(req.first_name,' ',req.last_name) AS requested_by_name,
               CONCAT(apr.first_name,' ',apr.last_name) AS approved_by_name
        FROM il_change_orders co
        LEFT JOIN currencies cur ON co.currency_id = cur.id
        LEFT JOIN employees req  ON co.requested_by = req.id
        LEFT JOIN employees apr  ON co.approved_by  = apr.id
        WHERE co.id = :id AND co.delete_flag = 0
    """, {'id': co_id})
    return rows[0] if rows else None


def generate_co_number(project_id: int) -> str:
    rows = execute_query(
        "SELECT COUNT(*) AS cnt FROM il_change_orders WHERE project_id = :pid AND delete_flag = 0",
        {'pid': project_id},
    )
    return f"CO-{(rows[0]['cnt'] if rows else 0) + 1:03d}"


def create_change_order(data: Dict, created_by: str) -> int:
    sql = """
        INSERT INTO il_change_orders (
            project_id, co_number, title, description,
            change_type, reason,
            original_value, revised_value, cost_impact, currency_id,
            schedule_impact_days,
            status, requested_by, requested_date,
            customer_approval, customer_approval_ref,
            created_by, modified_by, created_date, modified_date
        ) VALUES (
            :project_id, :co_number, :title, :description,
            :change_type, :reason,
            :original_value, :revised_value, :cost_impact, :currency_id,
            :schedule_impact_days,
            :status, :requested_by, :requested_date,
            0, :customer_approval_ref,
            :created_by, :created_by, NOW(), NOW()
        )
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), {**data, 'created_by': created_by})
        conn.commit()
        return result.lastrowid


def update_change_order(co_id: int, data: Dict, modified_by: str) -> bool:
    sql = """
        UPDATE il_change_orders SET
            title = :title, description = :description,
            change_type = :change_type, reason = :reason,
            original_value = :original_value, revised_value = :revised_value,
            cost_impact = :cost_impact, currency_id = :currency_id,
            schedule_impact_days = :schedule_impact_days,
            status = :status,
            approved_by = :approved_by, approved_date = :approved_date,
            customer_approval = :customer_approval,
            customer_approval_ref = :customer_approval_ref,
            modified_by = :modified_by, modified_date = NOW(),
            version = version + 1
        WHERE id = :id AND delete_flag = 0
    """
    return execute_update(sql, {**data, 'id': co_id, 'modified_by': modified_by}) > 0


def get_co_impact_summary(project_id: int) -> Dict:
    rows = execute_query("""
        SELECT
            SUM(CASE WHEN status = 'APPROVED' THEN cost_impact ELSE 0 END) AS approved_impact,
            SUM(CASE WHEN status = 'SUBMITTED' THEN cost_impact ELSE 0 END) AS pending_impact,
            SUM(CASE WHEN status = 'APPROVED' THEN schedule_impact_days ELSE 0 END) AS approved_days,
            COUNT(*) AS total_cos
        FROM il_change_orders WHERE project_id = :pid AND delete_flag = 0
    """, {'pid': project_id})
    return rows[0] if rows else {}


# ══════════════════════════════════════════════════════════════════════════════
# PROGRESS REPORTS
# ══════════════════════════════════════════════════════════════════════════════

def get_progress_reports_df(project_id: int) -> pd.DataFrame:
    return execute_query_df("""
        SELECT
            pr.id, pr.report_number, pr.report_type, pr.report_date,
            pr.overall_status, pr.overall_completion_percent,
            pr.schedule_status, pr.cost_status, pr.quality_status,
            pr.status,
            CONCAT(p.first_name,' ',p.last_name) AS prepared_by_name,
            CONCAT(r.first_name,' ',r.last_name) AS reviewed_by_name,
            (SELECT COUNT(*) FROM il_progress_report_medias rm
             WHERE rm.report_id = pr.id AND rm.delete_flag = 0) AS file_count
        FROM il_progress_reports pr
        LEFT JOIN employees p ON pr.prepared_by = p.id
        LEFT JOIN employees r ON pr.reviewed_by = r.id
        WHERE pr.project_id = :pid AND pr.delete_flag = 0
        ORDER BY pr.report_date DESC
    """, {'pid': project_id})


def get_progress_report(report_id: int) -> Optional[Dict]:
    rows = execute_query("""
        SELECT pr.*,
               CONCAT(p.first_name,' ',p.last_name) AS prepared_by_name,
               CONCAT(r.first_name,' ',r.last_name) AS reviewed_by_name
        FROM il_progress_reports pr
        LEFT JOIN employees p ON pr.prepared_by = p.id
        LEFT JOIN employees r ON pr.reviewed_by = r.id
        WHERE pr.id = :id AND pr.delete_flag = 0
    """, {'id': report_id})
    return rows[0] if rows else None


def generate_report_number(project_id: int) -> str:
    rows = execute_query(
        "SELECT COUNT(*) AS cnt FROM il_progress_reports WHERE project_id = :pid AND delete_flag = 0",
        {'pid': project_id},
    )
    return f"RPT-{(rows[0]['cnt'] if rows else 0) + 1:03d}"


def create_progress_report(data: Dict, created_by: str) -> int:
    sql = """
        INSERT INTO il_progress_reports (
            project_id, report_number, report_type, report_date,
            reporting_period_from, reporting_period_to,
            overall_status, overall_completion_percent,
            schedule_status, cost_status, quality_status,
            summary, accomplishments, planned_next_period, blockers,
            planned_completion_percent,
            actual_cost_to_date, budget_at_completion,
            prepared_by, status,
            created_by, modified_by, created_date, modified_date
        ) VALUES (
            :project_id, :report_number, :report_type, :report_date,
            :reporting_period_from, :reporting_period_to,
            :overall_status, :overall_completion_percent,
            :schedule_status, :cost_status, :quality_status,
            :summary, :accomplishments, :planned_next_period, :blockers,
            :planned_completion_percent,
            :actual_cost_to_date, :budget_at_completion,
            :prepared_by, 'DRAFT',
            :created_by, :created_by, NOW(), NOW()
        )
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), {**data, 'created_by': created_by})
        conn.commit()
        return result.lastrowid


def update_progress_report(report_id: int, data: Dict, modified_by: str) -> bool:
    sql = """
        UPDATE il_progress_reports SET
            report_type = :report_type, report_date = :report_date,
            reporting_period_from = :reporting_period_from,
            reporting_period_to = :reporting_period_to,
            overall_status = :overall_status,
            overall_completion_percent = :overall_completion_percent,
            schedule_status = :schedule_status, cost_status = :cost_status,
            quality_status = :quality_status,
            summary = :summary, accomplishments = :accomplishments,
            planned_next_period = :planned_next_period, blockers = :blockers,
            planned_completion_percent = :planned_completion_percent,
            actual_cost_to_date = :actual_cost_to_date,
            budget_at_completion = :budget_at_completion,
            reviewed_by = :reviewed_by, status = :status,
            modified_by = :modified_by, modified_date = NOW(),
            version = version + 1
        WHERE id = :id AND delete_flag = 0
    """
    return execute_update(sql, {**data, 'id': report_id, 'modified_by': modified_by}) > 0


# ══════════════════════════════════════════════════════════════════════════════
# QUALITY CHECKLISTS
# ══════════════════════════════════════════════════════════════════════════════

def get_quality_checklists_df(project_id: int, checklist_type: Optional[str] = None) -> pd.DataFrame:
    sql = """
        SELECT
            qc.id, qc.checklist_type, qc.checklist_name, qc.status,
            qc.inspection_date, qc.location, qc.customer_witness,
            qc.total_items, qc.passed_items, qc.failed_items, qc.pass_rate,
            qc.retest_date, qc.customer_signed_off,
            CONCAT(ins.first_name,' ',ins.last_name) AS inspector_name,
            CONCAT(so.first_name,' ',so.last_name) AS signed_off_by_name,
            m.milestone_name,
            (SELECT COUNT(*) FROM il_quality_checklist_medias qm
             WHERE qm.checklist_id = qc.id AND qm.delete_flag = 0) AS file_count
        FROM il_quality_checklists qc
        LEFT JOIN employees ins ON qc.inspector_id    = ins.id
        LEFT JOIN employees so  ON qc.signed_off_by   = so.id
        LEFT JOIN il_project_milestones m ON qc.milestone_id = m.id
        WHERE qc.project_id = :pid AND qc.delete_flag = 0
    """
    params: Dict = {'pid': project_id}
    if checklist_type:
        sql += " AND qc.checklist_type = :ctype"
        params['ctype'] = checklist_type
    sql += " ORDER BY qc.inspection_date DESC, qc.created_date DESC"
    return execute_query_df(sql, params)


def get_quality_checklist(qc_id: int) -> Optional[Dict]:
    rows = execute_query("""
        SELECT qc.*,
               CONCAT(ins.first_name,' ',ins.last_name) AS inspector_name,
               CONCAT(so.first_name,' ',so.last_name)  AS signed_off_by_name,
               m.milestone_name
        FROM il_quality_checklists qc
        LEFT JOIN employees ins ON qc.inspector_id  = ins.id
        LEFT JOIN employees so  ON qc.signed_off_by = so.id
        LEFT JOIN il_project_milestones m ON qc.milestone_id = m.id
        WHERE qc.id = :id AND qc.delete_flag = 0
    """, {'id': qc_id})
    return rows[0] if rows else None


def create_quality_checklist(data: Dict, created_by: str) -> int:
    sql = """
        INSERT INTO il_quality_checklists (
            project_id, milestone_id, checklist_type, checklist_name,
            description, inspection_date, location,
            inspector_id, customer_witness, status,
            total_items, passed_items, failed_items, pass_rate,
            remarks, next_action, retest_date,
            created_by, modified_by, created_date, modified_date
        ) VALUES (
            :project_id, :milestone_id, :checklist_type, :checklist_name,
            :description, :inspection_date, :location,
            :inspector_id, :customer_witness, :status,
            :total_items, :passed_items, :failed_items, :pass_rate,
            :remarks, :next_action, :retest_date,
            :created_by, :created_by, NOW(), NOW()
        )
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), {**data, 'created_by': created_by})
        conn.commit()
        return result.lastrowid


def update_quality_checklist(qc_id: int, data: Dict, modified_by: str) -> bool:
    sql = """
        UPDATE il_quality_checklists SET
            checklist_type = :checklist_type, checklist_name = :checklist_name,
            description = :description,
            inspection_date = :inspection_date, location = :location,
            inspector_id = :inspector_id, customer_witness = :customer_witness,
            status = :status,
            total_items = :total_items, passed_items = :passed_items,
            failed_items = :failed_items, pass_rate = :pass_rate,
            remarks = :remarks, next_action = :next_action, retest_date = :retest_date,
            signed_off_by = :signed_off_by, signed_off_date = :signed_off_date,
            customer_signed_off = :customer_signed_off,
            modified_by = :modified_by, modified_date = NOW(),
            version = version + 1
        WHERE id = :id AND delete_flag = 0
    """
    return execute_update(sql, {**data, 'id': qc_id, 'modified_by': modified_by}) > 0


def soft_delete_quality_checklist(qc_id: int, modified_by: str) -> bool:
    return execute_update(
        "UPDATE il_quality_checklists SET delete_flag=1, modified_by=:m, modified_date=NOW() WHERE id=:id",
        {'id': qc_id, 'm': modified_by}
    ) > 0