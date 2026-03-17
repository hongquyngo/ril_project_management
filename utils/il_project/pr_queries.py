# utils/il_project/pr_queries.py
"""
Database layer for IL Purchase Request module.
All PR-related SQL queries — pages never write raw SQL.

Conventions match queries.py:
  - *_df()  → returns pd.DataFrame
  - others  → return dict / list / id
  - created_by / modified_by = str(user_id) from session
"""

import logging
from typing import Dict, List, Optional
from datetime import date, datetime
import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)


def _get_engine():
    from ..db import get_db_engine
    return get_db_engine()


def _execute_query(sql, params=None):
    from ..db import execute_query
    return execute_query(sql, params or {})


def _execute_query_df(sql, params=None):
    from ..db import execute_query_df
    return execute_query_df(sql, params or {})


def _execute_update(sql, params=None):
    from ..db import execute_update
    return execute_update(sql, params or {})


def _get_transaction():
    from ..db import get_transaction
    return get_transaction()


# ══════════════════════════════════════════════════════════════════════
# PR NUMBER GENERATION
# ══════════════════════════════════════════════════════════════════════

def generate_pr_number() -> str:
    """Generate next PR number: PR-IL-YYYYMMDD-NNN"""
    today = date.today()
    prefix = f"PR-IL-{today.strftime('%Y%m%d')}-"
    rows = _execute_query("""
        SELECT pr_number FROM il_purchase_requests
        WHERE pr_number LIKE :pattern
        ORDER BY pr_number DESC LIMIT 1
    """, {'pattern': f'{prefix}%'})
    if rows:
        try:
            last_seq = int(rows[0]['pr_number'].split('-')[-1])
        except (ValueError, IndexError):
            last_seq = 0
    else:
        last_seq = 0
    return f"{prefix}{last_seq + 1:03d}"


# ══════════════════════════════════════════════════════════════════════
# PR CRUD
# ══════════════════════════════════════════════════════════════════════

def get_pr_list_df(
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    requester_id: Optional[int] = None,
    approver_id: Optional[int] = None,
) -> pd.DataFrame:
    """Get PR list from overview view. Optionally filter."""
    sql = "SELECT * FROM v_il_pr_overview WHERE 1=1"
    params: Dict = {}
    if project_id:
        sql += " AND project_id = :pid"
        params['pid'] = project_id
    if status:
        sql += " AND status = :status"
        params['status'] = status
    if requester_id:
        sql += " AND requester_id = :req"
        params['req'] = requester_id
    sql += " ORDER BY created_date DESC"
    return _execute_query_df(sql, params)


def get_pending_for_approver(approver_employee_id: int) -> pd.DataFrame:
    """Get PRs pending approval for a specific approver."""
    return _execute_query_df("""
        SELECT * FROM v_il_pr_pending
        WHERE approver_id = :aid
        ORDER BY 
            FIELD(priority, 'URGENT', 'HIGH', 'NORMAL', 'LOW'),
            submitted_date ASC
    """, {'aid': approver_employee_id})


def get_pr(pr_id: int) -> Optional[Dict]:
    """Get single PR with full details."""
    rows = _execute_query("""
        SELECT 
            pr.*,
            p.project_code, p.project_name, p.status AS project_status,
            CONCAT(req.first_name, ' ', req.last_name) AS requester_name,
            req.email AS requester_email,
            v.english_name AS vendor_name,
            cur.code AS currency_code,
            po.po_number
        FROM il_purchase_requests pr
        JOIN il_projects p          ON pr.project_id   = p.id
        JOIN employees req          ON pr.requester_id  = req.id
        LEFT JOIN companies v       ON pr.vendor_id     = v.id
        LEFT JOIN currencies cur    ON pr.currency_id   = cur.id
        LEFT JOIN purchase_orders po ON pr.po_id        = po.id
        WHERE pr.id = :id AND pr.delete_flag = 0
    """, {'id': pr_id})
    return rows[0] if rows else None


def get_pr_items_df(pr_id: int) -> pd.DataFrame:
    """Get line items for a PR."""
    return _execute_query_df("""
        SELECT
            pri.id, pri.cogs_category, pri.product_id,
            pri.item_description, pri.brand_name, pri.pt_code,
            pri.vendor_id, pri.vendor_name, pri.vendor_quote_ref,
            pri.quantity, pri.uom, pri.unit_cost,
            cur.code AS currency_code, pri.exchange_rate,
            pri.amount_vnd,
            pri.costbook_detail_id, pri.estimate_line_item_id,
            pri.specifications, pri.notes, pri.view_order
        FROM il_purchase_request_items pri
        LEFT JOIN currencies cur ON pri.currency_id = cur.id
        WHERE pri.pr_id = :prid AND pri.delete_flag = 0
        ORDER BY pri.cogs_category, pri.view_order, pri.id
    """, {'prid': pr_id})


def create_pr(data: Dict, created_by: str) -> int:
    """
    Create PR header. Returns new PR id.
    Nullable FK columns (vendor_id, vendor_contact_id, estimate_id) are
    excluded from INSERT when None to avoid FK constraint issues.
    """
    # ── Build dynamic INSERT — only include non-None FK columns ──
    base_cols = [
        'pr_number', 'project_id', 'requester_id',
        'currency_id', 'exchange_rate',
        'priority', 'pr_type', 'cogs_category',
        'required_date', 'justification',
    ]
    base_vals = [
        ':pr_number', ':project_id', ':requester_id',
        ':currency_id', ':exchange_rate',
        ':priority', ':pr_type', ':cogs_category',
        ':required_date', ':justification',
    ]

    # Optional FK columns — only include when value is not None
    optional_fks = [
        ('estimate_id',       data.get('estimate_id')),
        ('vendor_id',         data.get('vendor_id')),
        ('vendor_contact_id', data.get('vendor_contact_id')),
    ]
    params = {k: data.get(k) for k in [
        'pr_number', 'project_id', 'requester_id',
        'currency_id', 'exchange_rate',
        'priority', 'pr_type', 'cogs_category',
        'required_date', 'justification',
    ]}
    for col, val in optional_fks:
        if val is not None:
            base_cols.append(col)
            base_vals.append(f':{col}')
            params[col] = val

    # Always add status + audit
    base_cols += ['status', 'created_by', 'modified_by']
    base_vals += ["'DRAFT'", ':created_by', ':created_by']
    params['created_by'] = created_by

    sql = f"""
        INSERT INTO il_purchase_requests ({', '.join(base_cols)})
        VALUES ({', '.join(base_vals)})
    """
    logger.debug(f"create_pr SQL: {sql}")
    logger.debug(f"create_pr params: {params}")

    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        conn.commit()
        return result.lastrowid


def update_pr(pr_id: int, data: Dict, modified_by: str) -> bool:
    """Update PR header (only DRAFT or REVISION_REQUESTED).
    Nullable FK columns set to NULL explicitly when value is None.
    """
    # Build SET clauses — handle nullable FKs carefully
    set_parts = []
    params: Dict = {'id': pr_id, 'modified_by': modified_by}

    # Non-FK fields (always included)
    for col in ['priority', 'pr_type', 'cogs_category', 'required_date',
                'justification', 'currency_id', 'exchange_rate']:
        set_parts.append(f"{col} = :{col}")
        params[col] = data.get(col)

    # Nullable FK fields — use NULL literal when None to avoid FK lookup
    for col in ['vendor_id', 'vendor_contact_id']:
        val = data.get(col)
        if val is not None:
            set_parts.append(f"{col} = :{col}")
            params[col] = val
        else:
            set_parts.append(f"{col} = NULL")

    set_parts.append("modified_by = :modified_by")
    set_parts.append("version = version + 1")

    sql = f"""
        UPDATE il_purchase_requests SET
            {', '.join(set_parts)}
        WHERE id = :id AND delete_flag = 0
          AND status IN ('DRAFT', 'REVISION_REQUESTED')
    """
    rows = _execute_update(sql, params)
    return rows > 0


def create_pr_item(data: Dict, created_by: str) -> int:
    """Add line item to PR.
    Nullable FK columns excluded from INSERT when None.
    """
    # Required columns (always included)
    base_cols = [
        'pr_id', 'item_description', 'brand_name', 'pt_code',
        'vendor_name', 'vendor_quote_ref',
        'quantity', 'uom', 'unit_cost', 'exchange_rate',
        'cogs_category', 'specifications', 'notes', 'view_order',
    ]
    params = {col: data.get(col) for col in base_cols}

    # Optional FK columns — only include when not None
    optional_fks = ['estimate_line_item_id', 'costbook_detail_id',
                    'product_id', 'vendor_id', 'currency_id']
    for col in optional_fks:
        val = data.get(col)
        if val is not None:
            base_cols.append(col)
            params[col] = val

    # Audit
    base_cols.append('created_by')
    params['created_by'] = created_by

    col_str = ', '.join(base_cols)
    val_str = ', '.join(f':{c}' for c in base_cols)

    sql = f"INSERT INTO il_purchase_request_items ({col_str}) VALUES ({val_str})"

    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        conn.commit()
        return result.lastrowid


def delete_pr_item(item_id: int) -> bool:
    rows = _execute_update(
        "UPDATE il_purchase_request_items SET delete_flag=1 WHERE id=:id",
        {'id': item_id}
    )
    return rows > 0


def recalc_pr_totals(pr_id: int) -> bool:
    """Recalculate total_amount and total_amount_vnd from items."""
    rows = _execute_update("""
        UPDATE il_purchase_requests pr SET
            total_amount = (
                SELECT COALESCE(SUM(quantity * unit_cost), 0)
                FROM il_purchase_request_items
                WHERE pr_id = :id AND delete_flag = 0
            ),
            total_amount_vnd = (
                SELECT COALESCE(SUM(amount_vnd), 0)
                FROM il_purchase_request_items
                WHERE pr_id = :id AND delete_flag = 0
            ),
            version = version + 1
        WHERE pr.id = :id AND pr.delete_flag = 0
    """, {'id': pr_id})
    return rows > 0


def cancel_pr(pr_id: int, modified_by: str) -> bool:
    """Cancel PR. Allowed from DRAFT, REVISION_REQUESTED, or PENDING_APPROVAL."""
    rows = _execute_update("""
        UPDATE il_purchase_requests
        SET status = 'CANCELLED', modified_by = :m, version = version + 1
        WHERE id = :id AND delete_flag = 0
          AND status IN ('DRAFT', 'REVISION_REQUESTED', 'PENDING_APPROVAL')
    """, {'id': pr_id, 'm': modified_by})
    return rows > 0


# ══════════════════════════════════════════════════════════════════════
# APPROVAL WORKFLOW
# ══════════════════════════════════════════════════════════════════════

def get_approval_chain(total_amount_vnd: float) -> List[Dict]:
    """
    Get the approval chain for IL_PURCHASE_REQUEST based on amount.
    Returns list of {level, employee_id, employee_name, email, max_amount}
    ordered by approval_level ASC.
    """
    rows = _execute_query("""
        SELECT
            aa.approval_level AS level,
            aa.employee_id,
            CONCAT(e.first_name, ' ', e.last_name) AS employee_name,
            e.email,
            aa.max_amount
        FROM approval_authorities aa
        JOIN approval_types at2 ON aa.approval_type_id = at2.id
        JOIN employees e ON aa.employee_id = e.id
        WHERE at2.code = 'IL_PURCHASE_REQUEST'
          AND at2.delete_flag = 0
          AND aa.is_active = 1
          AND aa.delete_flag = 0
          AND aa.valid_from <= NOW()
          AND (aa.valid_to IS NULL OR aa.valid_to >= NOW())
        ORDER BY aa.approval_level ASC
    """)
    return rows


def determine_max_level(total_amount_vnd: float, chain: List[Dict]) -> int:
    """
    Determine how many approval levels are needed for a given amount.
    Logic: find the lowest level whose max_amount covers the total.
    If no level covers it, use the highest level (unlimited).
    """
    if not chain:
        return 1
    for entry in chain:
        max_amt = entry.get('max_amount')
        if max_amt is not None and float(max_amt) >= total_amount_vnd:
            return entry['level']
    # No level fully covers → need all levels up to highest
    return max(e['level'] for e in chain)


def get_current_approver(pr_id: int) -> Optional[Dict]:
    """Get the current approver for a PR based on its current_approval_level."""
    rows = _execute_query("""
        SELECT
            aa.employee_id AS approver_id,
            CONCAT(e.first_name, ' ', e.last_name) AS approver_name,
            e.email AS approver_email,
            aa.approval_level,
            aa.max_amount
        FROM il_purchase_requests pr
        JOIN approval_types at2 ON at2.code = 'IL_PURCHASE_REQUEST' AND at2.delete_flag = 0
        JOIN approval_authorities aa
            ON aa.approval_type_id = at2.id
           AND aa.approval_level = pr.current_approval_level
           AND aa.is_active = 1
           AND aa.delete_flag = 0
           AND aa.valid_from <= NOW()
           AND (aa.valid_to IS NULL OR aa.valid_to >= NOW())
        JOIN employees e ON aa.employee_id = e.id
        WHERE pr.id = :prid AND pr.delete_flag = 0
        LIMIT 1
    """, {'prid': pr_id})
    return rows[0] if rows else None


def submit_pr(pr_id: int, modified_by: str) -> Dict:
    """
    Submit PR for approval.
    1. Recalc totals
    2. Determine approval chain & max level needed
    3. Set status = PENDING_APPROVAL, current_level = 1
    4. Log to approval_history
    Returns: {success, message, approver_name, approver_email}
    """
    try:
        with _get_transaction() as conn:
            # Get PR
            pr_row = conn.execute(text("""
                SELECT id, total_amount_vnd, status, project_id
                FROM il_purchase_requests
                WHERE id = :id AND delete_flag = 0
            """), {'id': pr_id}).fetchone()

            if not pr_row:
                return {'success': False, 'message': 'PR not found'}
            if pr_row.status not in ('DRAFT', 'REVISION_REQUESTED'):
                return {'success': False, 'message': f'Cannot submit PR in status {pr_row.status}'}

            # Recalc totals
            totals = conn.execute(text("""
                SELECT COALESCE(SUM(quantity * unit_cost), 0) AS total_amt,
                       COALESCE(SUM(amount_vnd), 0) AS total_vnd
                FROM il_purchase_request_items
                WHERE pr_id = :id AND delete_flag = 0
            """), {'id': pr_id}).fetchone()

            total_vnd = float(totals.total_vnd)
            if total_vnd <= 0:
                return {'success': False, 'message': 'PR has no items or zero amount'}

            conn.execute(text("""
                UPDATE il_purchase_requests
                SET total_amount = :amt, total_amount_vnd = :vnd
                WHERE id = :id
            """), {'id': pr_id, 'amt': float(totals.total_amt), 'vnd': total_vnd})

            # Get approval chain
            chain_rows = conn.execute(text("""
                SELECT aa.approval_level AS level, aa.employee_id, aa.max_amount,
                       CONCAT(e.first_name, ' ', e.last_name) AS employee_name,
                       e.email
                FROM approval_authorities aa
                JOIN approval_types at2 ON aa.approval_type_id = at2.id
                JOIN employees e ON aa.employee_id = e.id
                WHERE at2.code = 'IL_PURCHASE_REQUEST'
                  AND at2.delete_flag = 0 AND aa.is_active = 1 AND aa.delete_flag = 0
                  AND aa.valid_from <= NOW()
                  AND (aa.valid_to IS NULL OR aa.valid_to >= NOW())
                ORDER BY aa.approval_level ASC
            """)).fetchall()

            if not chain_rows:
                return {'success': False, 'message': 'No approval authorities configured for IL_PURCHASE_REQUEST'}

            # Determine max level needed
            max_level = 1
            for row in chain_rows:
                max_amt = row.max_amount
                if max_amt is not None and float(max_amt) >= total_vnd:
                    max_level = row.level
                    break
                max_level = row.level

            # First approver
            first_approver = chain_rows[0]

            # Update PR
            conn.execute(text("""
                UPDATE il_purchase_requests SET
                    status = 'PENDING_APPROVAL',
                    current_approval_level = 1,
                    max_approval_level = :max_lvl,
                    submitted_date = NOW(),
                    rejection_reason = NULL,
                    revision_notes = NULL,
                    modified_by = :m,
                    version = version + 1
                WHERE id = :id
            """), {'id': pr_id, 'max_lvl': max_level, 'm': modified_by})

            # Log to approval_history
            at_id = conn.execute(text(
                "SELECT id FROM approval_types WHERE code = 'IL_PURCHASE_REQUEST' LIMIT 1"
            )).fetchone()

            pr_num = conn.execute(text(
                "SELECT pr_number FROM il_purchase_requests WHERE id = :id"
            ), {'id': pr_id}).fetchone()

            conn.execute(text("""
                INSERT INTO approval_history
                    (approval_type_id, entity_id, entity_reference, approver_id,
                     approval_status, approval_level, comments, created_by)
                VALUES
                    (:atid, :eid, :ref, :approver, 'SUBMITTED', 1,
                     'PR submitted for approval', :by)
            """), {
                'atid': at_id.id, 'eid': pr_id, 'ref': pr_num.pr_number,
                'approver': first_approver.employee_id, 'by': modified_by,
            })

        return {
            'success': True,
            'message': f'PR submitted. Pending Level {1}/{max_level} approval.',
            'approver_name': first_approver.employee_name,
            'approver_email': first_approver.email,
            'max_level': max_level,
        }
    except Exception as e:
        logger.error(f"submit_pr failed: {e}")
        return {'success': False, 'message': str(e)}


def approve_pr(pr_id: int, approver_employee_id: int, comments: str = '') -> Dict:
    """
    Approve PR at current level.
    If more levels needed → advance to next level.
    If final level → set APPROVED.
    Returns: {success, message, next_approver_name?, next_approver_email?, final}
    """
    try:
        with _get_transaction() as conn:
            pr_row = conn.execute(text("""
                SELECT id, pr_number, status, current_approval_level, max_approval_level,
                       total_amount_vnd, requester_id
                FROM il_purchase_requests
                WHERE id = :id AND delete_flag = 0
            """), {'id': pr_id}).fetchone()

            if not pr_row or pr_row.status != 'PENDING_APPROVAL':
                return {'success': False, 'message': 'PR not found or not pending approval'}

            cur_level = pr_row.current_approval_level
            max_level = pr_row.max_approval_level
            is_final = (cur_level >= max_level)

            at_id = conn.execute(text(
                "SELECT id FROM approval_types WHERE code = 'IL_PURCHASE_REQUEST' LIMIT 1"
            )).fetchone()

            # Verify approver is authorized for current level
            auth = conn.execute(text("""
                SELECT aa.id FROM approval_authorities aa
                WHERE aa.approval_type_id = :atid
                  AND aa.employee_id = :emp
                  AND aa.approval_level = :lvl
                  AND aa.is_active = 1 AND aa.delete_flag = 0
                  AND aa.valid_from <= NOW()
                  AND (aa.valid_to IS NULL OR aa.valid_to >= NOW())
                LIMIT 1
            """), {'atid': at_id.id, 'emp': approver_employee_id, 'lvl': cur_level}).fetchone()

            if not auth:
                return {'success': False, 'message': f'Not authorized to approve at level {cur_level}'}

            # Log approval
            conn.execute(text("""
                INSERT INTO approval_history
                    (approval_type_id, entity_id, entity_reference, approver_id,
                     approval_status, approval_level, comments, created_by)
                VALUES
                    (:atid, :eid, :ref, :approver, 'APPROVED', :lvl, :comments, :by)
            """), {
                'atid': at_id.id, 'eid': pr_id, 'ref': pr_row.pr_number,
                'approver': approver_employee_id, 'lvl': cur_level,
                'comments': comments or f'Approved at level {cur_level}',
                'by': str(approver_employee_id),
            })

            result = {'success': True, 'final': is_final}

            if is_final:
                # Final approval
                conn.execute(text("""
                    UPDATE il_purchase_requests SET
                        status = 'APPROVED',
                        approved_date = NOW(),
                        modified_by = :m,
                        version = version + 1
                    WHERE id = :id
                """), {'id': pr_id, 'm': str(approver_employee_id)})
                result['message'] = 'PR approved (final).'
            else:
                # Advance to next level
                next_level = cur_level + 1
                conn.execute(text("""
                    UPDATE il_purchase_requests SET
                        current_approval_level = :nlvl,
                        modified_by = :m,
                        version = version + 1
                    WHERE id = :id
                """), {'id': pr_id, 'nlvl': next_level, 'm': str(approver_employee_id)})

                # Find next approver
                next_approver = conn.execute(text("""
                    SELECT aa.employee_id,
                           CONCAT(e.first_name, ' ', e.last_name) AS name,
                           e.email
                    FROM approval_authorities aa
                    JOIN approval_types at2 ON aa.approval_type_id = at2.id
                    JOIN employees e ON aa.employee_id = e.id
                    WHERE at2.code = 'IL_PURCHASE_REQUEST'
                      AND aa.approval_level = :lvl
                      AND aa.is_active = 1 AND aa.delete_flag = 0
                    LIMIT 1
                """), {'lvl': next_level}).fetchone()

                result['message'] = f'Approved at level {cur_level}. Advancing to level {next_level}.'
                if next_approver:
                    result['next_approver_name'] = next_approver.name
                    result['next_approver_email'] = next_approver.email

        return result
    except Exception as e:
        logger.error(f"approve_pr failed: {e}")
        return {'success': False, 'message': str(e)}


def reject_pr(pr_id: int, approver_employee_id: int, reason: str) -> bool:
    """Reject PR. Sets REJECTED status."""
    try:
        with _get_transaction() as conn:
            pr = conn.execute(text(
                "SELECT pr_number, current_approval_level FROM il_purchase_requests WHERE id=:id AND delete_flag=0"
            ), {'id': pr_id}).fetchone()
            if not pr:
                return False

            conn.execute(text("""
                UPDATE il_purchase_requests SET
                    status = 'REJECTED',
                    rejection_reason = :reason,
                    modified_by = :m, version = version + 1
                WHERE id = :id AND status = 'PENDING_APPROVAL'
            """), {'id': pr_id, 'reason': reason, 'm': str(approver_employee_id)})

            at_id = conn.execute(text(
                "SELECT id FROM approval_types WHERE code='IL_PURCHASE_REQUEST' LIMIT 1"
            )).fetchone()
            conn.execute(text("""
                INSERT INTO approval_history
                    (approval_type_id, entity_id, entity_reference, approver_id,
                     approval_status, approval_level, comments, created_by)
                VALUES (:atid, :eid, :ref, :approver, 'REJECTED', :lvl, :reason, :by)
            """), {
                'atid': at_id.id, 'eid': pr_id, 'ref': pr.pr_number,
                'approver': approver_employee_id, 'lvl': pr.current_approval_level,
                'reason': reason, 'by': str(approver_employee_id),
            })
        return True
    except Exception as e:
        logger.error(f"reject_pr failed: {e}")
        return False


def request_revision(pr_id: int, approver_employee_id: int, notes: str) -> bool:
    """Request revision — sends back to PM for editing."""
    try:
        with _get_transaction() as conn:
            pr = conn.execute(text(
                "SELECT pr_number, current_approval_level FROM il_purchase_requests WHERE id=:id AND delete_flag=0"
            ), {'id': pr_id}).fetchone()
            if not pr:
                return False

            conn.execute(text("""
                UPDATE il_purchase_requests SET
                    status = 'REVISION_REQUESTED',
                    revision_notes = :notes,
                    current_approval_level = 0,
                    modified_by = :m, version = version + 1
                WHERE id = :id AND status = 'PENDING_APPROVAL'
            """), {'id': pr_id, 'notes': notes, 'm': str(approver_employee_id)})

            at_id = conn.execute(text(
                "SELECT id FROM approval_types WHERE code='IL_PURCHASE_REQUEST' LIMIT 1"
            )).fetchone()
            conn.execute(text("""
                INSERT INTO approval_history
                    (approval_type_id, entity_id, entity_reference, approver_id,
                     approval_status, approval_level, comments, created_by)
                VALUES (:atid, :eid, :ref, :approver, 'REVISION_REQUESTED', :lvl, :notes, :by)
            """), {
                'atid': at_id.id, 'eid': pr_id, 'ref': pr.pr_number,
                'approver': approver_employee_id, 'lvl': pr.current_approval_level,
                'notes': notes, 'by': str(approver_employee_id),
            })
        return True
    except Exception as e:
        logger.error(f"request_revision failed: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════
# APPROVAL HISTORY
# ══════════════════════════════════════════════════════════════════════

def get_pr_approval_history(pr_id: int) -> List[Dict]:
    """Get approval history for a PR."""
    return _execute_query("""
        SELECT
            ah.approval_level,
            ah.approval_status,
            ah.approval_date,
            CONCAT(e.first_name, ' ', e.last_name) AS approver_name,
            ah.comments
        FROM approval_history ah
        JOIN approval_types at2 ON ah.approval_type_id = at2.id
        JOIN employees e ON ah.approver_id = e.id
        WHERE at2.code = 'IL_PURCHASE_REQUEST'
          AND ah.entity_id = :prid
          AND ah.delete_flag = 0
        ORDER BY ah.created_date ASC
    """, {'prid': pr_id})


# ══════════════════════════════════════════════════════════════════════
# BUDGET vs PR — Estimate / PR Comparison by COGS Category
# ══════════════════════════════════════════════════════════════════════

# Estimate field → COGS category mapping
_EST_FIELD_MAP = {
    'A': 'a_equipment_cost',
    'B': 'b_logistics_import',
    'C': 'c_custom_fabrication',
    'D': 'd_direct_labor',
    'E': 'e_travel_site_oh',
    'F': 'f_warranty_reserve',
}

_COGS_LABELS = {
    'A': 'A — Equipment',
    'B': 'B — Logistics & Import',
    'C': 'C — Fabrication',
    'D': 'D — Direct Labor',
    'E': 'E — Travel & Site OH',
    'F': 'F — Warranty Reserve',
}


def get_budget_vs_pr(project_id: int) -> Dict:
    """
    Compare Estimate budget (A→F) vs PR committed amounts by COGS category.

    Returns:
        {
            'has_data': bool,
            'estimate_version': int,
            'categories': [
                {
                    'category': 'A',
                    'label': 'A — Equipment',
                    'estimated': float,
                    'pr_committed': float,
                    'remaining': float,
                    'pct_used': float,       # 0–100+
                    'pr_count': int,         # number of PRs touching this category
                    'status': 'ok'|'warning'|'over',
                    'prs': [                 # drill-down: individual PRs
                        {'pr_number': ..., 'vendor': ..., 'amount_vnd': ..., 'status': ...,
                         'items': [{'desc': ..., 'qty': ..., 'cost': ..., 'vnd': ...}]},
                    ],
                },
                ...
            ],
            'total_estimated': float,
            'total_committed': float,
            'total_remaining': float,
            'total_pct_used': float,
        }
    """
    # ── Get active estimate ──
    from .queries import get_active_estimate
    est = get_active_estimate(project_id)
    if not est:
        return {'has_data': False, 'categories': [], 'estimate_version': 0,
                'total_estimated': 0, 'total_committed': 0, 'total_remaining': 0, 'total_pct_used': 0}

    # ── Get all active PR items for this project, grouped ──
    pr_items_raw = _execute_query("""
        SELECT
            pr.id AS pr_id,
            pr.pr_number,
            pr.status AS pr_status,
            pr.vendor_id,
            COALESCE(v.english_name, '') AS vendor_name,
            pri.id AS item_id,
            pri.cogs_category,
            pri.item_description,
            pri.quantity,
            pri.unit_cost,
            COALESCE(cur.code, 'VND') AS currency_code,
            pri.exchange_rate,
            pri.amount_vnd
        FROM il_purchase_request_items pri
        JOIN il_purchase_requests pr ON pri.pr_id = pr.id
        LEFT JOIN companies v        ON pr.vendor_id = v.id
        LEFT JOIN currencies cur     ON pri.currency_id = cur.id
        WHERE pr.project_id = :pid
          AND pr.delete_flag = 0
          AND pri.delete_flag = 0
          AND pr.status NOT IN ('CANCELLED', 'REJECTED')
        ORDER BY pri.cogs_category, pr.pr_number, pri.view_order
    """, {'pid': project_id})

    # ── Organize items by category → by PR ──
    # Structure: {category: {pr_id: {'pr_number': ..., 'items': [...], 'total': ...}}}
    cat_pr_map: Dict[str, Dict[int, Dict]] = {}
    for row in pr_items_raw:
        cat = row.get('cogs_category', 'A') or 'A'
        # Normalize: SERVICE items → map to nearest (or keep separate)
        pr_id = row['pr_id']

        if cat not in cat_pr_map:
            cat_pr_map[cat] = {}
        if pr_id not in cat_pr_map[cat]:
            cat_pr_map[cat][pr_id] = {
                'pr_number': row['pr_number'],
                'vendor': row.get('vendor_name', ''),
                'status': row['pr_status'],
                'items': [],
                'total_vnd': 0,
            }
        item_vnd = float(row.get('amount_vnd', 0) or 0)
        cat_pr_map[cat][pr_id]['items'].append({
            'desc': (row.get('item_description', '') or '')[:50],
            'qty': float(row.get('quantity', 0) or 0),
            'cost': float(row.get('unit_cost', 0) or 0),
            'ccy': row.get('currency_code', 'VND'),
            'vnd': item_vnd,
        })
        cat_pr_map[cat][pr_id]['total_vnd'] += item_vnd

    # ── Build category comparison rows ──
    categories = []
    total_est = 0.0
    total_committed = 0.0

    for cat_key in ['A', 'B', 'C', 'D', 'E', 'F']:
        est_field = _EST_FIELD_MAP[cat_key]
        est_val = float(est.get(est_field, 0) or 0)
        total_est += est_val

        # Sum committed from PRs
        pr_data = cat_pr_map.get(cat_key, {})
        committed = sum(p['total_vnd'] for p in pr_data.values())
        total_committed += committed

        remaining = est_val - committed
        pct_used = (committed / est_val * 100) if est_val > 0 else (100.0 if committed > 0 else 0)

        # Status
        if est_val <= 0 and committed <= 0:
            status = 'empty'
        elif pct_used > 100:
            status = 'over'
        elif pct_used > 85:
            status = 'warning'
        else:
            status = 'ok'

        # Drill-down: flatten PR data
        prs_drill = []
        for pid, pdata in pr_data.items():
            prs_drill.append({
                'pr_number': pdata['pr_number'],
                'vendor': pdata['vendor'],
                'amount_vnd': pdata['total_vnd'],
                'status': pdata['status'],
                'items': pdata['items'],
            })

        categories.append({
            'category': cat_key,
            'label': _COGS_LABELS[cat_key],
            'estimated': est_val,
            'pr_committed': committed,
            'remaining': remaining,
            'pct_used': pct_used,
            'pr_count': len(pr_data),
            'status': status,
            'prs': prs_drill,
        })

    # Handle SERVICE items (not in A–F but may appear in PRs)
    if 'SERVICE' in cat_pr_map:
        svc_data = cat_pr_map['SERVICE']
        svc_committed = sum(p['total_vnd'] for p in svc_data.values())
        total_committed += svc_committed
        prs_drill = [{'pr_number': p['pr_number'], 'vendor': p['vendor'],
                       'amount_vnd': p['total_vnd'], 'status': p['status'],
                       'items': p['items']} for p in svc_data.values()]
        categories.append({
            'category': 'SVC',
            'label': 'Service Items',
            'estimated': 0,
            'pr_committed': svc_committed,
            'remaining': -svc_committed,
            'pct_used': 100.0 if svc_committed > 0 else 0,
            'pr_count': len(svc_data),
            'status': 'info',
            'prs': prs_drill,
        })

    total_remaining = total_est - total_committed
    total_pct = (total_committed / total_est * 100) if total_est > 0 else 0

    return {
        'has_data': True,
        'estimate_version': est.get('estimate_version', 0),
        'categories': categories,
        'total_estimated': total_est,
        'total_committed': total_committed,
        'total_remaining': total_remaining,
        'total_pct_used': total_pct,
    }


# ══════════════════════════════════════════════════════════════════════
# IMPORT FROM ESTIMATE
# ══════════════════════════════════════════════════════════════════════

def get_importable_estimate_items(estimate_id: int) -> List[Dict]:
    """
    Get estimate line items that can be imported into a PR.
    Excludes items already imported into an active (non-cancelled) PR.
    """
    return _execute_query("""
        SELECT
            li.id AS estimate_line_item_id,
            li.cogs_category, li.product_id,
            li.item_description, li.brand_name, li.pt_code,
            li.vendor_name, li.vendor_quote_ref, li.costbook_number,
            li.costbook_detail_id,
            li.unit_cost, cc.code AS cost_currency_code, cc.id AS cost_currency_id,
            li.cost_exchange_rate,
            li.quantity, li.uom,
            li.amount_cost_vnd,
            -- Check if already in a PR
            (SELECT COUNT(*) FROM il_purchase_request_items pri
             JOIN il_purchase_requests pr ON pri.pr_id = pr.id
             WHERE pri.estimate_line_item_id = li.id
               AND pri.delete_flag = 0
               AND pr.delete_flag = 0
               AND pr.status NOT IN ('CANCELLED', 'REJECTED')
            ) AS already_in_pr
        FROM il_estimate_line_items li
        LEFT JOIN currencies cc ON li.cost_currency_id = cc.id
        WHERE li.estimate_id = :eid AND li.delete_flag = 0
        ORDER BY li.cogs_category, li.view_order, li.id
    """, {'eid': estimate_id})


# ══════════════════════════════════════════════════════════════════════
# CREATE PO FROM APPROVED PR
# ══════════════════════════════════════════════════════════════════════

def create_po_from_pr(pr_id: int, buyer_company_id: int, created_by_keycloak: str) -> Dict:
    """
    Create a PO in purchase_orders + product_purchase_orders from an approved PR.
    Uses the same schema as ERP platform.
    
    Args:
        pr_id: IL purchase request ID
        buyer_company_id: Prostech/Rozitek company ID (typically 1)
        created_by_keycloak: keycloak_id of the creator
    
    Returns: {success, po_id, po_number, message}
    """
    try:
        with _get_transaction() as conn:
            # Validate PR
            pr = conn.execute(text("""
                SELECT pr.*, cur.code AS ccy_code
                FROM il_purchase_requests pr
                LEFT JOIN currencies cur ON pr.currency_id = cur.id
                WHERE pr.id = :id AND pr.delete_flag = 0 AND pr.status = 'APPROVED'
            """), {'id': pr_id}).fetchone()

            if not pr:
                return {'success': False, 'message': 'PR not found or not in APPROVED status'}
            if pr.po_id:
                return {'success': False, 'message': f'PO already created: {pr.po_id}'}

            # Generate PO number: PO{YYYYMMDD}-{id}{seller_id}
            today_str = datetime.now().strftime('%Y%m%d')
            seller_id = pr.vendor_id or 0

            # Insert PO header
            po_result = conn.execute(text("""
                INSERT INTO purchase_orders (
                    po_date, po_number, po_type,
                    buyer_company_id, seller_company_id,
                    currency_id, usd_exchange_rate,
                    po_note, created_by, created_date,
                    delete_flag, version
                ) VALUES (
                    NOW(), :po_num, 'INTERNAL',
                    :buyer, :seller,
                    :cur, :rate,
                    :note, :by, NOW(),
                    0, 0
                )
            """), {
                'po_num': f'__TEMP__',  # Will update with actual ID
                'buyer': buyer_company_id,
                'seller': pr.vendor_id,
                'cur': pr.currency_id,
                'rate': float(pr.exchange_rate or 1),
                'note': f'Auto-created from PR {pr.pr_number}',
                'by': created_by_keycloak,
            })
            po_id = po_result.lastrowid

            # Update PO number with actual ID
            po_number = f"PO{today_str}-{po_id}{seller_id}"
            conn.execute(text(
                "UPDATE purchase_orders SET po_number = :num WHERE id = :id"
            ), {'num': po_number, 'id': po_id})

            # Get PR items
            items = conn.execute(text("""
                SELECT * FROM il_purchase_request_items
                WHERE pr_id = :prid AND delete_flag = 0
                ORDER BY view_order, id
            """), {'prid': pr_id}).fetchall()

            # Insert PO line items
            for item in items:
                conn.execute(text("""
                    INSERT INTO product_purchase_orders (
                        purchase_order_id, product_id,
                        quantity, unit_cost, original_unit_cost,
                        exchange_rate, distributor_buy_price,
                        product_currency_id, product_pn,
                        purchase_quantity, purchase_unit_cost, original_purchase_unit_cost,
                        created_date, delete_flag, version
                    ) VALUES (
                        :po_id, :prod_id,
                        :qty, :cost, :cost,
                        :rate, :cost,
                        :cur_id, :pn,
                        :qty, :cost, :cost,
                        NOW(), 0, 0
                    )
                """), {
                    'po_id': po_id,
                    'prod_id': item.product_id,
                    'qty': float(item.quantity),
                    'cost': float(item.unit_cost),
                    'rate': float(item.exchange_rate),
                    'cur_id': item.currency_id,
                    'pn': item.pt_code or '',
                })

            # Update PR → link to PO
            conn.execute(text("""
                UPDATE il_purchase_requests SET
                    status = 'PO_CREATED',
                    po_id = :po_id,
                    modified_by = :m,
                    version = version + 1
                WHERE id = :id
            """), {'id': pr_id, 'po_id': po_id, 'm': created_by_keycloak})

            # Link PO to il_project_documents
            conn.execute(text("""
                INSERT INTO il_project_documents (
                    project_id, document_type, document_id, document_number,
                    cogs_category, amount, currency_id, exchange_rate,
                    description, created_by
                ) VALUES (
                    :proj_id, 'PURCHASE_ORDER', :po_id, :po_num,
                    :cogs, :amt, :cur, :rate,
                    :desc, :by
                )
            """), {
                'proj_id': pr.project_id, 'po_id': po_id, 'po_num': po_number,
                'cogs': pr.cogs_category or 'A',
                'amt': float(pr.total_amount or 0),
                'cur': pr.currency_id, 'rate': float(pr.exchange_rate or 1),
                'desc': f'PO from PR {pr.pr_number}',
                'by': created_by_keycloak,
            })

        return {
            'success': True,
            'po_id': po_id,
            'po_number': po_number,
            'message': f'PO {po_number} created successfully',
        }
    except Exception as e:
        logger.error(f"create_po_from_pr failed: {e}")
        return {'success': False, 'message': str(e)}


# ══════════════════════════════════════════════════════════════════════
# PROJECT HELPERS
# ══════════════════════════════════════════════════════════════════════

def get_project_pm_email(project_id: int) -> Optional[str]:
    """Get PM's email for a project. Used for CC notifications."""
    rows = _execute_query("""
        SELECT e.email
        FROM il_projects p
        JOIN employees e ON p.pm_employee_id = e.id
        WHERE p.id = :pid AND p.delete_flag = 0
        LIMIT 1
    """, {'pid': project_id})
    return rows[0]['email'] if rows else None


# ══════════════════════════════════════════════════════════════════════
# PERMISSION CHECK
# ══════════════════════════════════════════════════════════════════════

def is_project_pm(project_id: int, employee_id: int) -> bool:
    """Check if employee is the PM of this project."""
    rows = _execute_query("""
        SELECT 1 FROM il_projects
        WHERE id = :pid AND pm_employee_id = :eid AND delete_flag = 0
        LIMIT 1
    """, {'pid': project_id, 'eid': employee_id})
    return len(rows) > 0


def is_approver_for_pr(pr_id: int, employee_id: int) -> bool:
    """Check if employee is the current approver for this PR."""
    rows = _execute_query("""
        SELECT 1 FROM v_il_pr_pending
        WHERE pr_id = :prid AND approver_id = :eid
        LIMIT 1
    """, {'prid': pr_id, 'eid': employee_id})
    return len(rows) > 0