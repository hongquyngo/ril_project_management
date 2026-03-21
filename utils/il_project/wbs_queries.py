# utils/il_project/wbs_queries.py
"""
Database layer for WBS (Work Breakdown Structure) management.
Covers: Phases, Tasks, Checklists, Comments, Task Media, Project Members.

Follows same conventions as queries.py:
  - *_df()  → returns pd.DataFrame  (for st.dataframe)
  - others  → return dict / list / id
  - created_by / modified_by = str(user_id) from session
  - All queries use parameterized :named placeholders
  - Soft delete via delete_flag, optimistic locking via version
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
# PHASES
# ══════════════════════════════════════════════════════════════════════════════

def get_phases_df(project_id: int) -> pd.DataFrame:
    """All phases for a project, ordered by sequence."""
    return execute_query_df("""
        SELECT
            ph.id, ph.phase_code, ph.phase_name, ph.sequence_no,
            ph.planned_start, ph.planned_end,
            ph.actual_start, ph.actual_end,
            ph.status, ph.weight_percent, ph.completion_percent,
            ph.notes,
            COUNT(t.id) AS task_count,
            SUM(CASE WHEN t.status = 'COMPLETED' THEN 1 ELSE 0 END) AS tasks_done
        FROM il_project_phases ph
        LEFT JOIN il_project_tasks t
            ON t.phase_id = ph.id AND t.delete_flag = 0
        WHERE ph.project_id = :pid AND ph.delete_flag = 0
        GROUP BY ph.id
        ORDER BY ph.sequence_no
    """, {'pid': project_id})


def get_phase(phase_id: int) -> Optional[Dict]:
    rows = execute_query("""
        SELECT * FROM il_project_phases
        WHERE id = :id AND delete_flag = 0
    """, {'id': phase_id})
    return rows[0] if rows else None


def create_phase(data: Dict, created_by: str) -> int:
    sql = """
        INSERT INTO il_project_phases (
            project_id, phase_code, phase_name, sequence_no,
            planned_start, planned_end,
            status, weight_percent, notes,
            created_by, modified_by, created_date, modified_date
        ) VALUES (
            :project_id, :phase_code, :phase_name, :sequence_no,
            :planned_start, :planned_end,
            :status, :weight_percent, :notes,
            :created_by, :created_by, NOW(), NOW()
        )
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), {**data, 'created_by': created_by})
        conn.commit()
        return result.lastrowid


def update_phase(phase_id: int, data: Dict, modified_by: str) -> bool:
    sql = """
        UPDATE il_project_phases SET
            phase_code = :phase_code, phase_name = :phase_name,
            sequence_no = :sequence_no,
            planned_start = :planned_start, planned_end = :planned_end,
            actual_start = :actual_start, actual_end = :actual_end,
            status = :status, weight_percent = :weight_percent,
            completion_percent = :completion_percent,
            notes = :notes,
            modified_by = :modified_by, modified_date = NOW(),
            version = version + 1
        WHERE id = :id AND delete_flag = 0
    """
    rows = execute_update(sql, {**data, 'id': phase_id, 'modified_by': modified_by})
    return rows > 0


def soft_delete_phase(phase_id: int, modified_by: str) -> bool:
    """Soft-delete phase. Also soft-deletes all child tasks."""
    try:
        with get_transaction() as conn:
            conn.execute(text("""
                UPDATE il_project_tasks
                SET delete_flag = 1, modified_by = :m, modified_date = NOW()
                WHERE phase_id = :pid AND delete_flag = 0
            """), {'pid': phase_id, 'm': modified_by})
            conn.execute(text("""
                UPDATE il_project_phases
                SET delete_flag = 1, modified_by = :m, modified_date = NOW()
                WHERE id = :pid
            """), {'pid': phase_id, 'm': modified_by})
        return True
    except Exception as e:
        logger.error(f"soft_delete_phase failed: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# TASKS
# ══════════════════════════════════════════════════════════════════════════════

def get_tasks_df(
    project_id: int,
    phase_id: Optional[int] = None,
    assignee_id: Optional[int] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
) -> pd.DataFrame:
    """Tasks for a project with optional filters."""
    sql = """
        SELECT
            t.id, t.project_id, t.phase_id, t.parent_task_id,
            t.wbs_code, t.task_name, t.description,
            t.assignee_id,
            CONCAT(e.first_name, ' ', e.last_name) AS assignee_name,
            t.priority, t.status,
            t.planned_start, t.planned_end,
            t.actual_start, t.actual_end,
            t.estimated_hours, t.actual_hours,
            t.completion_percent,
            t.dependency_task_id, t.dependency_type,
            ph.phase_name, ph.phase_code,
            (SELECT COUNT(*) FROM il_task_checklists c
             WHERE c.task_id = t.id AND c.delete_flag = 0) AS checklist_total,
            (SELECT COUNT(*) FROM il_task_checklists c
             WHERE c.task_id = t.id AND c.is_completed = 1 AND c.delete_flag = 0) AS checklist_done,
            (SELECT COUNT(*) FROM il_task_comments tc
             WHERE tc.task_id = t.id AND tc.delete_flag = 0) AS comment_count
        FROM il_project_tasks t
        LEFT JOIN employees e ON t.assignee_id = e.id
        LEFT JOIN il_project_phases ph ON t.phase_id = ph.id
        WHERE t.project_id = :pid AND t.delete_flag = 0
    """
    params: Dict = {'pid': project_id}
    if phase_id:
        sql += " AND t.phase_id = :phase_id"
        params['phase_id'] = phase_id
    if assignee_id:
        sql += " AND t.assignee_id = :assignee_id"
        params['assignee_id'] = assignee_id
    if status:
        sql += " AND t.status = :status"
        params['status'] = status
    if priority:
        sql += " AND t.priority = :priority"
        params['priority'] = priority
    sql += " ORDER BY ph.sequence_no, t.wbs_code, t.planned_start"
    return execute_query_df(sql, params)


def get_my_tasks_df(employee_id: int) -> pd.DataFrame:
    """All active tasks assigned to an employee across all projects."""
    return execute_query_df("""
        SELECT
            t.id, t.task_name, t.wbs_code,
            t.priority, t.status, t.completion_percent,
            t.planned_end, t.actual_start,
            t.estimated_hours, t.actual_hours,
            p.project_code, p.project_name,
            ph.phase_name
        FROM il_project_tasks t
        JOIN il_projects p ON t.project_id = p.id
        LEFT JOIN il_project_phases ph ON t.phase_id = ph.id
        WHERE t.assignee_id = :eid
          AND t.status NOT IN ('COMPLETED', 'CANCELLED')
          AND t.delete_flag = 0
          AND p.delete_flag = 0
        ORDER BY
            FIELD(t.priority, 'CRITICAL', 'HIGH', 'NORMAL', 'LOW'),
            t.planned_end ASC
    """, {'eid': employee_id})


def get_task(task_id: int) -> Optional[Dict]:
    rows = execute_query("""
        SELECT t.*,
               CONCAT(e.first_name, ' ', e.last_name) AS assignee_name,
               ph.phase_name, ph.phase_code,
               dep.task_name AS dependency_task_name
        FROM il_project_tasks t
        LEFT JOIN employees e ON t.assignee_id = e.id
        LEFT JOIN il_project_phases ph ON t.phase_id = ph.id
        LEFT JOIN il_project_tasks dep ON t.dependency_task_id = dep.id
        WHERE t.id = :id AND t.delete_flag = 0
    """, {'id': task_id})
    return rows[0] if rows else None


def create_task(data: Dict, created_by: str) -> int:
    sql = """
        INSERT INTO il_project_tasks (
            project_id, phase_id, parent_task_id, wbs_code,
            task_name, description, assignee_id,
            priority, status,
            planned_start, planned_end,
            estimated_hours,
            dependency_task_id, dependency_type,
            created_by, modified_by, created_date, modified_date
        ) VALUES (
            :project_id, :phase_id, :parent_task_id, :wbs_code,
            :task_name, :description, :assignee_id,
            :priority, 'NOT_STARTED',
            :planned_start, :planned_end,
            :estimated_hours,
            :dependency_task_id, :dependency_type,
            :created_by, :created_by, NOW(), NOW()
        )
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), {**data, 'created_by': created_by})
        conn.commit()
        return result.lastrowid


def update_task(task_id: int, data: Dict, modified_by: str) -> bool:
    """Full task update (PM edit)."""
    sql = """
        UPDATE il_project_tasks SET
            phase_id = :phase_id, parent_task_id = :parent_task_id,
            wbs_code = :wbs_code, task_name = :task_name,
            description = :description, assignee_id = :assignee_id,
            priority = :priority, status = :status,
            planned_start = :planned_start, planned_end = :planned_end,
            actual_start = :actual_start, actual_end = :actual_end,
            estimated_hours = :estimated_hours, actual_hours = :actual_hours,
            completion_percent = :completion_percent,
            dependency_task_id = :dependency_task_id, dependency_type = :dependency_type,
            modified_by = :modified_by, modified_date = NOW(),
            version = version + 1
        WHERE id = :id AND delete_flag = 0
    """
    rows = execute_update(sql, {**data, 'id': task_id, 'modified_by': modified_by})
    return rows > 0


def quick_update_task(
    task_id: int,
    status: str,
    completion_percent: float,
    actual_hours: Optional[float],
    modified_by: str,
) -> bool:
    """
    Engineer fast-update: only status, %, hours.
    Also auto-logs status change via log_status_change().
    """
    # Read old values for audit log
    old = get_task(task_id)
    if not old:
        return False

    sql = """
        UPDATE il_project_tasks SET
            status = :status,
            completion_percent = :pct,
            actual_hours = COALESCE(:hours, actual_hours),
            actual_start = CASE
                WHEN actual_start IS NULL AND :status != 'NOT_STARTED' THEN CURDATE()
                ELSE actual_start
            END,
            actual_end = CASE
                WHEN :status = 'COMPLETED' AND actual_end IS NULL THEN CURDATE()
                ELSE actual_end
            END,
            modified_by = :m, modified_date = NOW(),
            version = version + 1
        WHERE id = :id AND delete_flag = 0
    """
    rows = execute_update(sql, {
        'id': task_id, 'status': status, 'pct': completion_percent,
        'hours': actual_hours, 'm': modified_by,
    })

    if rows > 0:
        # Auto-log status change
        if old['status'] != status:
            log_status_change(task_id, old['status'], status, modified_by)
        if float(old.get('completion_percent') or 0) != completion_percent:
            _log_comment(task_id, modified_by, 'PROGRESS_UPDATE',
                         f"{old.get('completion_percent', 0)}%", f"{completion_percent}%",
                         f"Progress updated to {completion_percent}%")
    return rows > 0


def soft_delete_task(task_id: int, modified_by: str) -> bool:
    rows = execute_update(
        "UPDATE il_project_tasks SET delete_flag=1, modified_by=:m, modified_date=NOW() WHERE id=:id",
        {'id': task_id, 'm': modified_by}
    )
    return rows > 0


# ══════════════════════════════════════════════════════════════════════════════
# CHECKLISTS
# ══════════════════════════════════════════════════════════════════════════════

def get_checklists(task_id: int) -> List[Dict]:
    return execute_query("""
        SELECT cl.id, cl.sequence_no, cl.item_name,
               cl.is_completed, cl.completed_by, cl.completed_date, cl.notes,
               CONCAT(e.first_name, ' ', e.last_name) AS completed_by_name
        FROM il_task_checklists cl
        LEFT JOIN employees e ON cl.completed_by = e.id
        WHERE cl.task_id = :tid AND cl.delete_flag = 0
        ORDER BY cl.sequence_no, cl.id
    """, {'tid': task_id})


def create_checklist_item(data: Dict, created_by: str) -> int:
    sql = """
        INSERT INTO il_task_checklists (
            task_id, sequence_no, item_name, notes,
            created_by, created_date, modified_date
        ) VALUES (
            :task_id, :sequence_no, :item_name, :notes,
            :created_by, NOW(), NOW()
        )
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), {**data, 'created_by': created_by})
        conn.commit()
        return result.lastrowid


def toggle_checklist_item(item_id: int, employee_id: int, is_completed: bool) -> bool:
    """Toggle checklist item. Sets completed_by and date when completing."""
    sql = """
        UPDATE il_task_checklists SET
            is_completed = :done,
            completed_by = CASE WHEN :done = 1 THEN :eid ELSE NULL END,
            completed_date = CASE WHEN :done = 1 THEN NOW() ELSE NULL END,
            modified_date = NOW(),
            version = version + 1
        WHERE id = :id AND delete_flag = 0
    """
    rows = execute_update(sql, {'id': item_id, 'done': 1 if is_completed else 0, 'eid': employee_id})
    return rows > 0


def delete_checklist_item(item_id: int) -> bool:
    rows = execute_update(
        "UPDATE il_task_checklists SET delete_flag=1, modified_date=NOW() WHERE id=:id",
        {'id': item_id}
    )
    return rows > 0


# ══════════════════════════════════════════════════════════════════════════════
# COMMENTS / ACTIVITY LOG
# ══════════════════════════════════════════════════════════════════════════════

def get_task_comments(task_id: int) -> List[Dict]:
    """All comments/activity for a task, newest first."""
    return execute_query("""
        SELECT tc.id, tc.content, tc.comment_type,
               tc.old_value, tc.new_value,
               tc.created_date,
               CONCAT(e.first_name, ' ', e.last_name) AS author_name
        FROM il_task_comments tc
        LEFT JOIN employees e ON tc.author_id = e.id
        WHERE tc.task_id = :tid AND tc.delete_flag = 0
        ORDER BY tc.created_date DESC
    """, {'tid': task_id})


def create_comment(task_id: int, author_id: int, content: str, comment_type: str = 'COMMENT') -> int:
    """Add a human comment to a task."""
    return _log_comment(task_id, str(author_id), comment_type, None, None, content)


def log_status_change(task_id: int, old_status: str, new_status: str, user_id: str) -> int:
    """Auto-log when task status changes."""
    return _log_comment(
        task_id, user_id, 'STATUS_CHANGE',
        old_status, new_status,
        f"Status changed: {old_status} → {new_status}"
    )


def _log_comment(
    task_id: int, user_id: str, comment_type: str,
    old_value: Optional[str], new_value: Optional[str],
    content: str,
) -> int:
    """Internal: insert comment/activity log entry."""
    sql = """
        INSERT INTO il_task_comments (
            task_id, author_id, content, comment_type,
            old_value, new_value,
            created_by, created_date, modified_date
        ) VALUES (
            :task_id, :author_id, :content, :comment_type,
            :old_value, :new_value,
            :created_by, NOW(), NOW()
        )
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), {
            'task_id': task_id, 'author_id': int(user_id),
            'content': content, 'comment_type': comment_type,
            'old_value': old_value, 'new_value': new_value,
            'created_by': user_id,
        })
        conn.commit()
        return result.lastrowid


# ══════════════════════════════════════════════════════════════════════════════
# TASK MEDIA (attachments)
# ══════════════════════════════════════════════════════════════════════════════

def get_task_media(task_id: int) -> List[Dict]:
    return execute_query("""
        SELECT tm.id, tm.media_id, tm.description, tm.created_date,
               m.name AS file_name, m.path AS file_path,
               CONCAT(e.first_name, ' ', e.last_name) AS uploaded_by
        FROM il_task_media tm
        JOIN medias m ON tm.media_id = m.id
        LEFT JOIN employees e ON tm.created_by = e.id
        WHERE tm.task_id = :tid AND tm.delete_flag = 0
        ORDER BY tm.created_date DESC
    """, {'tid': task_id})


def attach_media_to_task(task_id: int, media_id: int, description: str, created_by: str) -> int:
    sql = """
        INSERT INTO il_task_media (
            task_id, media_id, description,
            created_by, created_date, modified_date
        ) VALUES (
            :task_id, :media_id, :description,
            :created_by, NOW(), NOW()
        )
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), {
            'task_id': task_id, 'media_id': media_id,
            'description': description, 'created_by': created_by,
        })
        conn.commit()
        return result.lastrowid


def detach_media(tm_id: int) -> bool:
    rows = execute_update(
        "UPDATE il_task_media SET delete_flag=1, modified_date=NOW() WHERE id=:id",
        {'id': tm_id}
    )
    return rows > 0


# ══════════════════════════════════════════════════════════════════════════════
# PROJECT MEMBERS
# ══════════════════════════════════════════════════════════════════════════════

def get_project_members_df(project_id: int) -> pd.DataFrame:
    return execute_query_df("""
        SELECT
            pm.id, pm.employee_id,
            CONCAT(e.first_name, ' ', e.last_name) AS member_name,
            e.email,
            pm.role, pm.allocation_percent, pm.daily_rate,
            pm.start_date, pm.end_date,
            pm.is_active, pm.notes
        FROM il_project_members pm
        JOIN employees e ON pm.employee_id = e.id
        WHERE pm.project_id = :pid AND pm.delete_flag = 0
        ORDER BY FIELD(pm.role, 'PROJECT_MANAGER','SOLUTION_ARCHITECT',
                        'SENIOR_ENGINEER','ENGINEER','SITE_ENGINEER',
                        'FAE','SALES','SUBCONTRACTOR','OTHER'),
                 e.first_name
    """, {'pid': project_id})


def get_member(member_id: int) -> Optional[Dict]:
    rows = execute_query("""
        SELECT pm.*, CONCAT(e.first_name, ' ', e.last_name) AS member_name
        FROM il_project_members pm
        JOIN employees e ON pm.employee_id = e.id
        WHERE pm.id = :id AND pm.delete_flag = 0
    """, {'id': member_id})
    return rows[0] if rows else None


def create_member(data: Dict, created_by: str) -> int:
    sql = """
        INSERT INTO il_project_members (
            project_id, employee_id, role,
            allocation_percent, daily_rate,
            start_date, end_date, is_active, notes,
            created_by, created_date, modified_date
        ) VALUES (
            :project_id, :employee_id, :role,
            :allocation_percent, :daily_rate,
            :start_date, :end_date, 1, :notes,
            :created_by, NOW(), NOW()
        )
    """
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), {**data, 'created_by': created_by})
        conn.commit()
        return result.lastrowid


def update_member(member_id: int, data: Dict, modified_by: str) -> bool:
    sql = """
        UPDATE il_project_members SET
            role = :role, allocation_percent = :allocation_percent,
            daily_rate = :daily_rate,
            start_date = :start_date, end_date = :end_date,
            is_active = :is_active, notes = :notes,
            modified_date = NOW(), version = version + 1
        WHERE id = :id AND delete_flag = 0
    """
    rows = execute_update(sql, {**data, 'id': member_id, 'modified_by': modified_by})
    return rows > 0


def remove_member(member_id: int, modified_by: str) -> bool:
    rows = execute_update(
        "UPDATE il_project_members SET delete_flag=1, modified_date=NOW() WHERE id=:id",
        {'id': member_id}
    )
    return rows > 0


def get_member_workload(employee_id: int) -> List[Dict]:
    """All active project allocations for an employee."""
    return execute_query("""
        SELECT pm.project_id, p.project_code, p.project_name,
               pm.role, pm.allocation_percent, pm.daily_rate
        FROM il_project_members pm
        JOIN il_projects p ON pm.project_id = p.id
        WHERE pm.employee_id = :eid
          AND pm.is_active = 1
          AND pm.delete_flag = 0
          AND p.delete_flag = 0
          AND p.status IN ('IN_PROGRESS', 'COMMISSIONING', 'CONTRACTED')
        ORDER BY p.project_code
    """, {'eid': employee_id})


# ══════════════════════════════════════════════════════════════════════════════
# COMPLETION AGGREGATION
# ══════════════════════════════════════════════════════════════════════════════

def sync_phase_completion(phase_id: int, modified_by: str) -> None:
    """
    Recalculate phase completion_percent from child tasks.
    Formula: AVG(task.completion_percent) weighted by estimated_hours.
    Falls back to simple AVG if no hours set.
    """
    rows = execute_query("""
        SELECT completion_percent, COALESCE(estimated_hours, 1) AS weight
        FROM il_project_tasks
        WHERE phase_id = :pid AND delete_flag = 0
    """, {'pid': phase_id})

    if not rows:
        return

    total_w = sum(r['weight'] for r in rows)
    if total_w > 0:
        pct = sum(r['completion_percent'] * r['weight'] for r in rows) / total_w
    else:
        pct = sum(r['completion_percent'] for r in rows) / len(rows)

    execute_update("""
        UPDATE il_project_phases
        SET completion_percent = :pct, modified_by = :m, modified_date = NOW()
        WHERE id = :pid AND delete_flag = 0
    """, {'pid': phase_id, 'pct': round(pct, 2), 'm': modified_by})


def sync_project_completion(project_id: int, modified_by: str) -> None:
    """
    Recalculate project overall_completion_percent from phases.
    Formula: SUM(phase.completion_percent × phase.weight_percent) / 100.
    Falls back to simple AVG if no weights set.
    """
    rows = execute_query("""
        SELECT completion_percent, COALESCE(weight_percent, 0) AS weight
        FROM il_project_phases
        WHERE project_id = :pid AND delete_flag = 0
    """, {'pid': project_id})

    if not rows:
        return

    total_w = sum(r['weight'] for r in rows)
    if total_w > 0:
        pct = sum(r['completion_percent'] * r['weight'] for r in rows) / total_w
    else:
        pct = sum(r['completion_percent'] for r in rows) / len(rows)

    execute_update("""
        UPDATE il_projects
        SET overall_completion_percent = :pct, modified_by = :m, version = version + 1
        WHERE id = :pid AND delete_flag = 0
    """, {'pid': project_id, 'pct': round(pct, 2), 'm': modified_by})


def sync_completion_up(task_id: int, modified_by: str) -> None:
    """
    After a task update, bubble completion % up:
    task → phase → project.
    """
    task = get_task(task_id)
    if not task:
        return
    if task.get('phase_id'):
        sync_phase_completion(task['phase_id'], modified_by)
    sync_project_completion(task['project_id'], modified_by)


# ══════════════════════════════════════════════════════════════════════════════
# WBS CODE GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def generate_wbs_code(phase_id: int, parent_task_id: Optional[int] = None) -> str:
    """
    Auto-generate WBS code for a new task.
    Phase sequence 3, no parent → "3.1", "3.2", ...
    Phase sequence 3, parent wbs "3.2" → "3.2.1", "3.2.2", ...
    """
    phase = get_phase(phase_id)
    if not phase:
        return "0.1"

    prefix = str(phase['sequence_no'])

    if parent_task_id:
        parent = get_task(parent_task_id)
        if parent and parent.get('wbs_code'):
            prefix = parent['wbs_code']

    # Find max sibling
    rows = execute_query("""
        SELECT wbs_code FROM il_project_tasks
        WHERE phase_id = :pid
          AND COALESCE(parent_task_id, 0) = :parent
          AND delete_flag = 0
        ORDER BY wbs_code DESC
        LIMIT 1
    """, {'pid': phase_id, 'parent': parent_task_id or 0})

    if rows and rows[0]['wbs_code']:
        try:
            last_part = int(rows[0]['wbs_code'].split('.')[-1])
        except (ValueError, IndexError):
            last_part = 0
    else:
        last_part = 0

    return f"{prefix}.{last_part + 1}"
