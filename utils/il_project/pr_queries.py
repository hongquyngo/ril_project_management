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

import re

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# UOM CONVERSION HELPER
# ══════════════════════════════════════════════════════════════════════

def _parse_conversion_factor(conversion_str: str) -> Optional[float]:
    """
    Parse costbook/PO conversion string → numeric factor.
    Factor means: 1 buying unit = factor × standard units.

    Supported formats:
        "10"        → 10.0
        "1:10"      → 10.0
        "1:100"     → 100.0
        "0.5"       → 0.5
        "1 Box = 10 Pcs" → 10.0  (extracts RHS number)
        None / ""   → None (no conversion = same UOM)

    Returns None if unparseable (caller treats as 1:1).
    """
    if not conversion_str:
        return None
    s = str(conversion_str).strip()
    if not s:
        return None

    # Try simple number: "10", "0.5"
    try:
        v = float(s)
        if v > 0:
            return v
    except ValueError:
        pass

    # Try ratio: "1:10", "1:100"
    m = re.match(r'^(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)$', s)
    if m:
        left, right = float(m.group(1)), float(m.group(2))
        if left > 0:
            return right / left
        return None

    # Try "X unit = Y unit": extract the numbers
    m = re.search(r'=\s*(\d+(?:\.\d+)?)', s)
    if m:
        v = float(m.group(1))
        if v > 0:
            return v

    logger.debug(f"Could not parse conversion: '{conversion_str}'")
    return None


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


def reduce_pr_item(item_id: int, new_quantity: float, new_unit_cost: float,
                   modified_by: str) -> Dict:
    """
    Reduce quantity and/or unit_cost of a PR item on an APPROVED PR.
    Only allows values <= original. Used for post-approval scope reduction.

    Returns: {success, message, old_qty, old_cost, new_qty, new_cost}
    """
    try:
        rows = _execute_query("""
            SELECT pri.id, pri.quantity, pri.unit_cost, pri.exchange_rate,
                   pr.status, pr.id AS pr_id
            FROM il_purchase_request_items pri
            JOIN il_purchase_requests pr ON pri.pr_id = pr.id
            WHERE pri.id = :iid AND pri.delete_flag = 0 AND pr.delete_flag = 0
        """, {'iid': item_id})

        if not rows:
            return {'success': False, 'message': 'Item not found'}

        item = rows[0]
        if item['status'] != 'APPROVED':
            return {'success': False, 'message': f"PR status is {item['status']} — reduce only allowed on APPROVED"}

        old_qty = float(item['quantity'])
        old_cost = float(item['unit_cost'])

        if new_quantity > old_qty:
            return {'success': False,
                    'message': f'Quantity {new_quantity} exceeds original {old_qty} — only reduction allowed'}
        if new_unit_cost > old_cost:
            return {'success': False,
                    'message': f'Unit cost {new_unit_cost} exceeds original {old_cost} — only reduction allowed'}
        if new_quantity <= 0:
            return {'success': False, 'message': 'Quantity must be > 0. Use Cancel PR to remove entirely.'}

        _execute_update("""
            UPDATE il_purchase_request_items
            SET quantity = :qty, unit_cost = :cost, modified_date = NOW()
            WHERE id = :iid
        """, {'qty': new_quantity, 'cost': new_unit_cost, 'iid': item_id})

        # Recalc PR totals
        recalc_pr_totals(item['pr_id'])

        return {
            'success': True,
            'message': f'Item updated: qty {old_qty}→{new_quantity}, cost {old_cost}→{new_unit_cost}',
            'old_qty': old_qty, 'old_cost': old_cost,
            'new_qty': new_quantity, 'new_cost': new_unit_cost,
        }
    except Exception as e:
        logger.error(f"reduce_pr_item failed: {e}")
        return {'success': False, 'message': str(e)}


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
    """Cancel PR. Allowed from DRAFT, REVISION_REQUESTED, PENDING_APPROVAL, or APPROVED."""
    rows = _execute_update("""
        UPDATE il_purchase_requests
        SET status = 'CANCELLED', modified_by = :m, version = version + 1
        WHERE id = :id AND delete_flag = 0
          AND status IN ('DRAFT', 'REVISION_REQUESTED', 'PENDING_APPROVAL', 'APPROVED')
          AND po_id IS NULL
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


def reject_pr(pr_id: int, approver_employee_id: int, reason: str) -> Dict:
    """
    Reject PR. Only the authorized approver at current level can reject.
    Returns: {success, message}
    """
    try:
        with _get_transaction() as conn:
            pr = conn.execute(text("""
                SELECT pr_number, current_approval_level, status
                FROM il_purchase_requests WHERE id=:id AND delete_flag=0
            """), {'id': pr_id}).fetchone()
            if not pr:
                return {'success': False, 'message': 'PR not found'}
            if pr.status != 'PENDING_APPROVAL':
                return {'success': False, 'message': f'Cannot reject PR in status {pr.status}'}

            # Verify approver is authorized for current level
            at_id = conn.execute(text(
                "SELECT id FROM approval_types WHERE code='IL_PURCHASE_REQUEST' LIMIT 1"
            )).fetchone()
            if not at_id:
                return {'success': False, 'message': 'Approval type not configured'}

            auth = conn.execute(text("""
                SELECT aa.id FROM approval_authorities aa
                WHERE aa.approval_type_id = :atid
                  AND aa.employee_id = :emp
                  AND aa.approval_level = :lvl
                  AND aa.is_active = 1 AND aa.delete_flag = 0
                  AND aa.valid_from <= NOW()
                  AND (aa.valid_to IS NULL OR aa.valid_to >= NOW())
                LIMIT 1
            """), {
                'atid': at_id.id, 'emp': approver_employee_id,
                'lvl': pr.current_approval_level,
            }).fetchone()

            if not auth:
                return {'success': False,
                        'message': f'Not authorized to reject at level {pr.current_approval_level}'}

            conn.execute(text("""
                UPDATE il_purchase_requests SET
                    status = 'REJECTED',
                    rejection_reason = :reason,
                    modified_by = :m, version = version + 1
                WHERE id = :id AND status = 'PENDING_APPROVAL'
            """), {'id': pr_id, 'reason': reason, 'm': str(approver_employee_id)})

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
        return {'success': True, 'message': 'PR rejected.'}
    except Exception as e:
        logger.error(f"reject_pr failed: {e}")
        return {'success': False, 'message': str(e)}


def request_revision(pr_id: int, approver_employee_id: int, notes: str) -> Dict:
    """
    Request revision — only authorized approver can send back to PM.
    Returns: {success, message}
    """
    try:
        with _get_transaction() as conn:
            pr = conn.execute(text("""
                SELECT pr_number, current_approval_level, status
                FROM il_purchase_requests WHERE id=:id AND delete_flag=0
            """), {'id': pr_id}).fetchone()
            if not pr:
                return {'success': False, 'message': 'PR not found'}
            if pr.status != 'PENDING_APPROVAL':
                return {'success': False, 'message': f'Cannot request revision for PR in status {pr.status}'}

            # Verify approver is authorized for current level
            at_id = conn.execute(text(
                "SELECT id FROM approval_types WHERE code='IL_PURCHASE_REQUEST' LIMIT 1"
            )).fetchone()
            if not at_id:
                return {'success': False, 'message': 'Approval type not configured'}

            auth = conn.execute(text("""
                SELECT aa.id FROM approval_authorities aa
                WHERE aa.approval_type_id = :atid
                  AND aa.employee_id = :emp
                  AND aa.approval_level = :lvl
                  AND aa.is_active = 1 AND aa.delete_flag = 0
                  AND aa.valid_from <= NOW()
                  AND (aa.valid_to IS NULL OR aa.valid_to >= NOW())
                LIMIT 1
            """), {
                'atid': at_id.id, 'emp': approver_employee_id,
                'lvl': pr.current_approval_level,
            }).fetchone()

            if not auth:
                return {'success': False,
                        'message': f'Not authorized to request revision at level {pr.current_approval_level}'}

            conn.execute(text("""
                UPDATE il_purchase_requests SET
                    status = 'REVISION_REQUESTED',
                    revision_notes = :notes,
                    current_approval_level = 0,
                    modified_by = :m, version = version + 1
                WHERE id = :id AND status = 'PENDING_APPROVAL'
            """), {'id': pr_id, 'notes': notes, 'm': str(approver_employee_id)})

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
        return {'success': True, 'message': 'Revision requested — PR sent back to PM.'}
    except Exception as e:
        logger.error(f"request_revision failed: {e}")
        return {'success': False, 'message': str(e)}


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
# PO READINESS — Resolve product_id + Pre-validate before PO creation
# ══════════════════════════════════════════════════════════════════════

def resolve_product_ids(pr_id: int) -> Dict:
    """
    Attempt to resolve NULL product_id on PR items from linked sources.

    Resolution chain per item:
      1. product_id already set                   → skip
      2. costbook_detail_id → costbook_details.product_id
      3. estimate_line_item_id → il_estimate_line_items.product_id

    Returns:
        {
            'resolved_count': int,      # items that were NULL and got resolved
            'still_missing': int,       # items still without product_id
            'total_items': int,
            'details': [                # per-item status
                {'item_id': ..., 'description': ..., 'status': 'ok'|'resolved'|'missing',
                 'resolved_from': 'costbook'|'estimate'|None},
            ],
        }
    """
    items = _execute_query("""
        SELECT
            pri.id, pri.item_description, pri.product_id,
            pri.costbook_detail_id, pri.estimate_line_item_id
        FROM il_purchase_request_items pri
        WHERE pri.pr_id = :prid AND pri.delete_flag = 0
        ORDER BY pri.view_order, pri.id
    """, {'prid': pr_id})

    resolved_count = 0
    still_missing = 0
    details = []

    for item in items:
        item_id = item['id']
        desc = item.get('item_description', '')

        # Already has product_id
        if item.get('product_id'):
            details.append({
                'item_id': item_id, 'description': desc,
                'status': 'ok', 'resolved_from': None,
                'product_id': item['product_id'],
            })
            continue

        resolved_pid = None
        resolved_from = None

        # Try costbook_detail_id → costbook_details.product_id
        if not resolved_pid and item.get('costbook_detail_id'):
            rows = _execute_query("""
                SELECT product_id FROM costbook_details
                WHERE id = :cid AND delete_flag = 0 AND product_id IS NOT NULL
                LIMIT 1
            """, {'cid': item['costbook_detail_id']})
            if rows and rows[0].get('product_id'):
                resolved_pid = rows[0]['product_id']
                resolved_from = 'costbook'

        # Try estimate_line_item_id → il_estimate_line_items.product_id
        if not resolved_pid and item.get('estimate_line_item_id'):
            rows = _execute_query("""
                SELECT product_id FROM il_estimate_line_items
                WHERE id = :eid AND delete_flag = 0 AND product_id IS NOT NULL
                LIMIT 1
            """, {'eid': item['estimate_line_item_id']})
            if rows and rows[0].get('product_id'):
                resolved_pid = rows[0]['product_id']
                resolved_from = 'estimate'

        if resolved_pid:
            # Update the PR item with resolved product_id + pt_code
            try:
                _execute_update("""
                    UPDATE il_purchase_request_items
                    SET product_id = :pid,
                        pt_code = (SELECT pt_code FROM products WHERE id = :pid)
                    WHERE id = :item_id
                """, {'pid': resolved_pid, 'item_id': item_id})
                resolved_count += 1
                details.append({
                    'item_id': item_id, 'description': desc,
                    'status': 'resolved', 'resolved_from': resolved_from,
                    'product_id': resolved_pid,
                })
            except Exception as e:
                logger.warning(f"resolve_product_ids: could not update item {item_id}: {e}")
                still_missing += 1
                details.append({
                    'item_id': item_id, 'description': desc,
                    'status': 'missing', 'resolved_from': None,
                    'product_id': None,
                })
        else:
            still_missing += 1
            details.append({
                'item_id': item_id, 'description': desc,
                'status': 'missing', 'resolved_from': None,
                'product_id': None,
            })

    return {
        'resolved_count': resolved_count,
        'still_missing': still_missing,
        'total_items': len(items),
        'details': details,
    }


def link_product_to_pr_item(item_id: int, product_id: int) -> bool:
    """
    Manually link a product to a PR item.
    Called from UI when user selects a product for an unlinked item.
    Also updates pt_code from the product.
    """
    try:
        rows = _execute_update("""
            UPDATE il_purchase_request_items
            SET product_id = :pid,
                pt_code = (SELECT pt_code FROM products WHERE id = :pid)
            WHERE id = :item_id AND delete_flag = 0
        """, {'pid': product_id, 'item_id': item_id})
        return rows > 0
    except Exception as e:
        logger.error(f"link_product_to_pr_item failed: {e}")
        return False


def search_products_for_linking(keyword: str, limit: int = 20) -> list:
    """
    Search products table for linking to PR items.
    Returns: [{id, pt_code, name, brand_name, uom}, ...]
    """
    try:
        from ..db import get_db_engine
        engine = get_db_engine()
        safe_limit = int(limit)
        kw = f'%{keyword}%'
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT
                    p.id,
                    p.pt_code,
                    p.name,
                    COALESCE(b.brand_name, '') AS brand_name,
                    p.uom
                FROM products p
                LEFT JOIN brands b ON p.brand_id = b.id
                WHERE p.delete_flag = 0
                  AND (p.name LIKE :kw OR p.pt_code LIKE :kw)
                ORDER BY p.name
                LIMIT {safe_limit}
            """), {'kw': kw}).fetchall()
            return [dict(r._mapping) for r in rows]
    except Exception as e:
        logger.error(f"search_products_for_linking failed: {e}")
        return []


def validate_po_readiness(pr_id: int) -> Dict:
    """
    Validate that a PR is ready for PO creation.
    Checks all requirements that legacy ERP needs.

    Returns:
        {
            'ready': bool,              # True if PO can be created
            'blockers': [...],          # Critical issues — must fix
            'warnings': [...],          # Non-critical — PO possible but incomplete
            'items_without_product': [  # Items needing product link
                {'item_id': ..., 'description': ..., 'costbook_detail_id': ...},
            ],
        }
    """
    pr = _execute_query("""
        SELECT pr.*, cur.code AS ccy_code
        FROM il_purchase_requests pr
        LEFT JOIN currencies cur ON pr.currency_id = cur.id
        WHERE pr.id = :id AND pr.delete_flag = 0
    """, {'id': pr_id})
    if not pr:
        return {'ready': False, 'blockers': ['PR not found'], 'warnings': [], 'items_without_product': []}
    pr = pr[0]

    blockers = []
    warnings = []

    # Status check
    if pr.get('status') != 'APPROVED':
        blockers.append(f"PR status is {pr.get('status')} — must be APPROVED")

    # Already has PO
    if pr.get('po_id'):
        blockers.append(f"PO already created (po_id={pr['po_id']})")

    # Vendor check
    if not pr.get('vendor_id'):
        blockers.append("No vendor selected — legacy ERP requires seller_company_id")

    # Currency check
    if not pr.get('currency_id'):
        blockers.append("No currency set on PR")

    # Items check
    items = _execute_query("""
        SELECT
            pri.id AS item_id,
            pri.item_description,
            pri.product_id,
            pri.costbook_detail_id,
            pri.estimate_line_item_id,
            pri.quantity,
            pri.unit_cost,
            pri.currency_id AS item_currency_id
        FROM il_purchase_request_items pri
        WHERE pri.pr_id = :prid AND pri.delete_flag = 0
        ORDER BY pri.view_order, pri.id
    """, {'prid': pr_id})

    if not items:
        blockers.append("PR has no line items")

    items_without_product = []
    for it in items:
        if not it.get('product_id'):
            items_without_product.append({
                'item_id': it['item_id'],
                'description': it.get('item_description', ''),
                'costbook_detail_id': it.get('costbook_detail_id'),
                'estimate_line_item_id': it.get('estimate_line_item_id'),
            })

    if items_without_product:
        blockers.append(
            f"{len(items_without_product)} item(s) missing product_id — "
            f"legacy ERP requires product link for every PO line item"
        )

    # Warnings (non-blocking but good to flag)
    if not pr.get('exchange_rate') or float(pr.get('exchange_rate', 0)) <= 0:
        warnings.append("Exchange rate is 0 or missing")

    total_vnd = float(pr.get('total_amount_vnd', 0) or 0)
    if total_vnd <= 0:
        warnings.append("Total amount VND is 0")

    return {
        'ready': len(blockers) == 0,
        'blockers': blockers,
        'warnings': warnings,
        'items_without_product': items_without_product,
    }


# ══════════════════════════════════════════════════════════════════════
# CREATE PO FROM APPROVED PR
# ══════════════════════════════════════════════════════════════════════

def create_po_from_pr(pr_id: int, buyer_company_id: int, created_by_keycloak: str,
                      po_settings: Optional[Dict] = None) -> Dict:
    """
    Create a PO in purchase_orders + product_purchase_orders from an approved PR.

    Enriches PO data from multiple sources to match purchase_order_full_view:
      - PO header: costbook → payment_term, trade_term, contacts, countries
                   vendor company → seller info, from_country
                   buyer company → ship_to, bill_to, to_country
      - PO items:  costbook_details → MOQ, SPQ, UOM, conversion, VAT
                   products → pt_code, uom

    Pre-condition: call validate_po_readiness() first.

    Args:
        pr_id: IL purchase request ID
        buyer_company_id: Prostech/Rozitek company ID
        created_by_keycloak: keycloak_id of the creator (must match employees.keycloak_id)
        po_settings: Optional dict from Confirm PO dialog with overrides:
            {
                # PO header overrides
                'payment_term_id': int|None,
                'trade_term_id': int|None,
                'ship_to_contact_id': int|None,
                'bill_to_contact_id': int|None,
                'ship_to': str|None,          # shipping address text
                'bill_to': str|None,           # billing address text
                'vat_gst': float|None,         # header-level VAT %
                'po_notes': str|None,          # → notes table
                'purchase_order_type': str|None, # REGULAR_ORDER|SAMPLE_ORDER|MIXED_ORDER
                # Per-item overrides: {item_id: {etd, eta, stock_owner_id}}
                'item_settings': {
                    <item_id>: {
                        'etd': datetime|None,
                        'eta': datetime|None,
                        'stock_owner_id': int|None,
                    }, ...
                },
            }

    Returns: {success, po_id, po_number, message}
    """
    po_settings = po_settings or {}
    try:
        with _get_transaction() as conn:
            # ── 1. Validate PR ─────────────────────────────────────
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
            if not pr.vendor_id:
                return {'success': False, 'message': 'PR has no vendor — cannot create PO'}

            # ── 2. Get PR items + product + costbook enrichment ────
            items = conn.execute(text("""
                SELECT
                    pri.*,
                    cur.code AS item_ccy_code,
                    p.pt_code AS product_pt_code,
                    p.uom AS product_uom,
                    p.package_size AS product_package_size,
                    p.hs_code AS product_hs_code,
                    -- Costbook detail enrichment
                    cd.minimum_order_quantity AS cb_moq,
                    cd.standard_pack_quantity AS cb_spq,
                    cd.purchase_uom AS cb_purchase_uom,
                    cd.product_uom AS cb_product_uom,
                    cd.conversion AS cb_conversion,
                    cd.vat AS cb_vat,
                    cd.costbook_id AS cb_costbook_id,
                    cd.package_size AS cb_package_size,
                    cd.hs_code AS cb_hs_code,
                    cd.lead_time_number AS cb_lead_time_number,
                    cd.lead_time_min AS cb_lead_time_min,
                    cd.lead_time_max AS cb_lead_time_max,
                    cd.lead_time_uom AS cb_lead_time_uom,
                    cd.price_type AS cb_price_type,
                    cd.shipping_mode_id AS cb_shipping_mode_id,
                    sm.code AS cb_shipping_mode_code
                FROM il_purchase_request_items pri
                LEFT JOIN currencies cur ON pri.currency_id = cur.id
                LEFT JOIN products p ON pri.product_id = p.id
                LEFT JOIN costbook_details cd ON pri.costbook_detail_id = cd.id
                LEFT JOIN shipping_modes sm ON cd.shipping_mode_id = sm.id
                WHERE pri.pr_id = :prid AND pri.delete_flag = 0
                ORDER BY pri.view_order, pri.id
            """), {'prid': pr_id}).fetchall()

            if not items:
                return {'success': False, 'message': 'PR has no line items'}

            missing_product = [it for it in items if not it.product_id]
            if missing_product:
                descs = ', '.join((it.item_description or '')[:30] for it in missing_product[:3])
                return {
                    'success': False,
                    'message': f'{len(missing_product)} item(s) missing product link: {descs}...'
                }

            # ── 3. Lookup costbook header for PO enrichment ────────
            #    Find dominant costbook (most items linked to same costbook)
            cb_ids = [it.cb_costbook_id for it in items if it.cb_costbook_id]
            cb_header = None
            if cb_ids:
                # Most frequent costbook_id
                from collections import Counter
                dominant_cb_id = Counter(cb_ids).most_common(1)[0][0]
                cb_header = conn.execute(text("""
                    SELECT
                        cb.payment_term_id,
                        cb.trade_term_id,
                        cb.vendor_contact_id AS seller_contact_id,
                        cb.buyer_contact_id,
                        cb.from_country_id,
                        cb.to_country_id,
                        cb.important_notes_id
                    FROM costbooks cb
                    WHERE cb.id = :cbid AND cb.delete_flag = 0
                """), {'cbid': dominant_cb_id}).fetchone()

            # ── 4. Lookup buyer/vendor company for ship-to/bill-to ─
            buyer_info = conn.execute(text("""
                SELECT id, country_id, state_province_id
                FROM companies WHERE id = :bid
            """), {'bid': buyer_company_id}).fetchone()

            vendor_info = conn.execute(text("""
                SELECT id, country_id, state_province_id
                FROM companies WHERE id = :vid
            """), {'vid': pr.vendor_id}).fetchone()

            # ── 5. Insert PO header (fully enriched) ───────────────
            today_str = datetime.now().strftime('%Y%m%d')
            seller_id = pr.vendor_id

            # Determine purchase_order_type from costbook price_types
            _po_order_type = po_settings.get('purchase_order_type')
            if not _po_order_type:
                price_types = set(
                    it.cb_price_type for it in items
                    if hasattr(it, 'cb_price_type') and it.cb_price_type
                )
                if len(price_types) == 0:
                    _po_order_type = 'REGULAR_ORDER'
                elif len(price_types) == 1:
                    pt = price_types.pop()
                    _po_order_type = 'SAMPLE_ORDER' if pt == 'SAMPLE' else 'REGULAR_ORDER'
                else:
                    _po_order_type = 'MIXED_ORDER'

            # Create notes record if PO notes provided
            _notes_id = None
            _po_notes_text = po_settings.get('po_notes', '').strip()
            if _po_notes_text:
                _notes_result = conn.execute(text("""
                    INSERT INTO notes (name, notes, creator, created_date, delete_flag, version)
                    VALUES ('PO Note', :notes, :creator, NOW(), b'0', 0)
                """), {'notes': _po_notes_text, 'creator': created_by_keycloak})
                _notes_id = _notes_result.lastrowid
            elif cb_header and getattr(cb_header, 'important_notes_id', None):
                _notes_id = cb_header.important_notes_id

            # Build params — merging costbook defaults with UI overrides
            _item_settings = po_settings.get('item_settings', {})

            po_params = {
                'po_num': '__TEMP__',
                'po_order_type': _po_order_type,
                'buyer': buyer_company_id,
                'seller': seller_id,
                'cur': pr.currency_id,
                'rate': float(pr.exchange_rate or 1),
                'note': po_settings.get('po_note_text')
                        or f'Auto-created from PR {pr.pr_number}',
                'ext_ref': pr.pr_number,
                'by': created_by_keycloak,
                # Ship-to & bill-to default to buyer company
                'ship_to_company': buyer_company_id,
                'bill_to_company': buyer_company_id,
                # Countries from costbook or vendor/buyer
                'from_country': (cb_header.from_country_id if cb_header and cb_header.from_country_id
                                 else (vendor_info.country_id if vendor_info else None)),
                'to_country': (cb_header.to_country_id if cb_header and cb_header.to_country_id
                               else (buyer_info.country_id if buyer_info else None)),
                'from_state': (vendor_info.state_province_id if vendor_info else None),
                'to_state': (buyer_info.state_province_id if buyer_info else None),
                # Contacts — UI override > costbook default
                'seller_contact': (po_settings.get('seller_contact_id')
                                   or (cb_header.seller_contact_id if cb_header else None)),
                'buyer_contact': (po_settings.get('buyer_contact_id')
                                  or (cb_header.buyer_contact_id if cb_header else None)),
                # Ship-to / bill-to contacts — from UI
                'ship_to_contact': po_settings.get('ship_to_contact_id'),
                'bill_to_contact': po_settings.get('bill_to_contact_id'),
                # Terms — UI override > costbook default
                'payment_term': (po_settings.get('payment_term_id')
                                 or (cb_header.payment_term_id if cb_header else None)),
                'trade_term': (po_settings.get('trade_term_id')
                               or (cb_header.trade_term_id if cb_header else None)),
                # New fields
                'vat_gst': po_settings.get('vat_gst'),
                'notes_id': _notes_id,
                'ship_to': po_settings.get('ship_to'),
                'bill_to': po_settings.get('bill_to'),
            }

            po_result = conn.execute(text("""
                INSERT INTO purchase_orders (
                    po_date, po_number, po_type, purchase_order_type,
                    buyer_company_id, seller_company_id,
                    buyer_contact_id, seller_contact_id,
                    ship_to_company_id, bill_to_company_id,
                    ship_to_contact_id, bill_to_contact_id,
                    currency_id, usd_exchange_rate,
                    payment_term_id, trade_term_id,
                    from_country_id, to_country_id,
                    from_state_province_id, to_state_province_id,
                    vat_gst, notes_id,
                    ship_to, bill_to,
                    po_note, external_ref_number,
                    created_by, created_date,
                    updated_by, updated_date,
                    delete_flag, version
                ) VALUES (
                    NOW(), :po_num, 'INTERNAL', :po_order_type,
                    :buyer, :seller,
                    :buyer_contact, :seller_contact,
                    :ship_to_company, :bill_to_company,
                    :ship_to_contact, :bill_to_contact,
                    :cur, :rate,
                    :payment_term, :trade_term,
                    :from_country, :to_country,
                    :from_state, :to_state,
                    :vat_gst, :notes_id,
                    :ship_to, :bill_to,
                    :note, :ext_ref,
                    :by, NOW(),
                    :by, NOW(),
                    b'0', 0
                )
            """), po_params)
            po_id = po_result.lastrowid

            # Update PO number: PO{date}-{po_id}-{seller_id}
            po_number = f"PO{today_str}-{po_id}-{seller_id}"
            conn.execute(text(
                "UPDATE purchase_orders SET po_number = :num WHERE id = :id"
            ), {'num': po_number, 'id': po_id})

            # ── 6. Insert PO line items (enriched from costbook) ───
            for item in items:
                buy_cost = float(item.unit_cost or 0)   # buying UOM cost (from PR)
                buy_qty = float(item.quantity or 0)      # buying UOM qty (from PR)
                rate = float(item.exchange_rate or 1)
                cur_id = item.currency_id or pr.currency_id

                pt_code = item.product_pt_code or item.pt_code or ''
                std_uom = item.product_uom or item.uom or ''
                buy_uom = item.cb_purchase_uom or std_uom
                conversion = item.cb_conversion or None
                moq = float(item.cb_moq) if item.cb_moq else None
                spq = float(item.cb_spq) if item.cb_spq else None
                vat = float(item.cb_vat) if item.cb_vat else None
                customer_code = item.vendor_quote_ref or None

                # ── Dual UOM: convert buying → standard ────────────
                # View expects: quantity = standard, purchase_quantity = buying
                # unit_cost = standard, purchase_unit_cost = buying
                # Factor: 1 buying unit = factor × standard units
                conv_factor = _parse_conversion_factor(conversion)
                if conv_factor and conv_factor != 1.0 and buy_uom != std_uom:
                    std_qty = round(buy_qty * conv_factor, 4)
                    std_cost = round(buy_cost / conv_factor, 4) if conv_factor > 0 else buy_cost
                else:
                    # Same UOM or no conversion — buying = standard
                    std_qty = buy_qty
                    std_cost = buy_cost

                # Per-item settings from UI (ETD, ETA, stock_owner)
                _isettings = _item_settings.get(str(item.id), _item_settings.get(item.id, {}))
                _etd = _isettings.get('etd')
                _eta = _isettings.get('eta')
                _stock_owner = _isettings.get('stock_owner_id')

                # Price type from costbook
                _price_type = 'ALL'
                if hasattr(item, 'cb_price_type') and item.cb_price_type:
                    _price_type = item.cb_price_type  # STANDARD, SPECIAL, SAMPLE

                conn.execute(text("""
                    INSERT INTO product_purchase_orders (
                        purchase_order_id, product_id, product_costbook_id,
                        quantity, unit_cost, original_unit_cost,
                        purchase_quantity, purchase_unit_cost, original_purchase_unit_cost,
                        exchange_rate, distributor_buy_price,
                        product_currency_id, product_pn,
                        purchaseuom, product_uom, conversion,
                        minimum_order_quantity, standard_pack_quantity,
                        vat_gst, customer_code,
                        etd, eta, stock_owner_id,
                        purchase_order_price_type,
                        created_date, delete_flag, version
                    ) VALUES (
                        :po_id, :prod_id, :costbook_id,
                        :std_qty, :std_cost, :std_cost,
                        :buy_qty, :buy_cost, :buy_cost,
                        :rate, :buy_cost,
                        :cur_id, :pn,
                        :buy_uom, :std_uom, :conversion,
                        :moq, :spq,
                        :vat, :cust_code,
                        :etd, :eta, :stock_owner,
                        :price_type,
                        NOW(), b'0', 0
                    )
                """), {
                    'po_id': po_id,
                    'prod_id': item.product_id,
                    'costbook_id': item.costbook_detail_id,
                    'std_qty': std_qty,
                    'std_cost': std_cost,
                    'buy_qty': buy_qty,
                    'buy_cost': buy_cost,
                    'rate': rate,
                    'cur_id': cur_id,
                    'pn': pt_code,
                    'buy_uom': buy_uom,
                    'std_uom': std_uom,
                    'conversion': conversion,
                    'moq': moq,
                    'spq': spq,
                    'vat': vat,
                    'cust_code': customer_code,
                    'etd': _etd,
                    'eta': _eta,
                    'stock_owner': _stock_owner,
                    'price_type': _price_type,
                })

            # ── 7. Update PR → link to PO ──────────────────────────
            conn.execute(text("""
                UPDATE il_purchase_requests SET
                    status = 'PO_CREATED',
                    po_id = :po_id,
                    modified_by = :m,
                    version = version + 1
                WHERE id = :id
            """), {'id': pr_id, 'po_id': po_id, 'm': created_by_keycloak})

            # ── 8. Link PO to il_project_documents ─────────────────
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

        logger.info(f"PO created: {po_number} (id={po_id}) from PR {pr.pr_number}")
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
# PO CREATION HELPERS — Lookups & Enrichment for Confirm PO dialog
# ══════════════════════════════════════════════════════════════════════

def get_payment_terms() -> List[Dict]:
    """Payment terms for PO header selector."""
    return _execute_query("""
        SELECT id, name, description
        FROM payment_terms
        WHERE delete_flag = 0
        ORDER BY name
    """)


def get_trade_terms() -> List[Dict]:
    """Trade terms (Incoterms) for PO header selector."""
    return _execute_query("""
        SELECT id, name, description
        FROM trade_terms
        WHERE delete_flag = 0
        ORDER BY name
    """)


def get_contacts_for_company(company_id: int) -> List[Dict]:
    """Contacts belonging to a company — for ship-to/bill-to contact selectors."""
    return _execute_query("""
        SELECT
            c.id,
            CONCAT(COALESCE(c.first_name,''), ' ', COALESCE(c.last_name,'')) AS full_name,
            c.email,
            c.phone,
            p.name AS position
        FROM contacts c
        LEFT JOIN positions p ON c.position_id = p.id
        WHERE c.company_id = :cid AND c.delete_flag = 0
        ORDER BY c.first_name, c.last_name
    """, {'cid': company_id})


def get_company_address(company_id: int) -> str:
    """Build address string from company record. Returns '—' if not found."""
    try:
        rows = _execute_query("""
            SELECT
                c.english_name,
                c.street,
                c.zip_code,
                s.name AS state_name,
                co.name AS country_name
            FROM companies c
            LEFT JOIN states s     ON c.state_province_id = s.id
            LEFT JOIN countries co ON c.country_id = co.id
            WHERE c.id = :cid
            LIMIT 1
        """, {'cid': company_id})
        if not rows:
            return '—'
        r = rows[0]
        parts = [p for p in [
            r.get('street'),
            r.get('state_name'),
            r.get('zip_code'),
            r.get('country_name'),
        ] if p]
        return ', '.join(parts) if parts else '—'
    except Exception:
        return '—'


def create_po_note(note_text: str, creator: str) -> Optional[int]:
    """Insert into notes table, return id. Used for PO important notes."""
    if not note_text or not note_text.strip():
        return None
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("""
                INSERT INTO notes (name, notes, creator, created_date, delete_flag, version)
                VALUES ('PO Note', :notes, :creator, NOW(), b'0', 0)
            """), {'notes': note_text.strip(), 'creator': creator})
            conn.commit()
            return result.lastrowid
    except Exception as e:
        logger.error(f"create_po_note failed: {e}")
        return None


def get_po_enrichment_data(pr_id: int) -> Dict:
    """
    Fetch enrichment data for the PO creation dialog UI.
    Returns costbook defaults + per-item lead time/shipping info.

    Used by _dialog_confirm_po() to pre-fill PO Header Settings
    and Shipping & Delivery sections.

    Returns:
        {
            'costbook_defaults': {    # from dominant costbook header
                'payment_term_id', 'payment_term_name',
                'trade_term_id', 'trade_term_name',
                'seller_contact_id', 'seller_contact_name',
                'buyer_contact_id', 'buyer_contact_name',
                'important_notes_id', 'important_notes_text',
            },
            'items': [                # per-item enrichment
                {
                    'item_id', 'item_description', 'pt_code',
                    'cb_package_size', 'product_package_size',
                    'cb_hs_code', 'product_hs_code',
                    'cb_lead_time_number', 'cb_lead_time_min', 'cb_lead_time_max',
                    'cb_lead_time_uom',
                    'cb_shipping_mode_code', 'cb_shipping_mode_name',
                    'cb_price_type', 'cb_vat',
                },
            ],
            'dominant_vat': float|None,   # most common VAT across items
            'all_vats_same': bool,
        }
    """
    items = _execute_query("""
        SELECT
            pri.id AS item_id,
            pri.item_description,
            pri.pt_code,
            pri.costbook_detail_id,
            -- Costbook detail enrichment
            cd.package_size AS cb_package_size,
            cd.hs_code AS cb_hs_code,
            cd.lead_time_number AS cb_lead_time_number,
            cd.lead_time_min AS cb_lead_time_min,
            cd.lead_time_max AS cb_lead_time_max,
            cd.lead_time_uom AS cb_lead_time_uom,
            cd.price_type AS cb_price_type,
            cd.vat AS cb_vat,
            cd.costbook_id AS cb_costbook_id,
            cd.shipping_mode_id AS cb_shipping_mode_id,
            sm.code AS cb_shipping_mode_code,
            sm.name AS cb_shipping_mode_name,
            -- Product enrichment
            p.package_size AS product_package_size,
            p.hs_code AS product_hs_code
        FROM il_purchase_request_items pri
        LEFT JOIN costbook_details cd ON pri.costbook_detail_id = cd.id
        LEFT JOIN shipping_modes sm   ON cd.shipping_mode_id = sm.id
        LEFT JOIN products p          ON pri.product_id = p.id
        WHERE pri.pr_id = :prid AND pri.delete_flag = 0
        ORDER BY pri.view_order, pri.id
    """, {'prid': pr_id})

    # Find dominant costbook for header defaults
    cb_ids = [it.get('cb_costbook_id') for it in items if it.get('cb_costbook_id')]
    costbook_defaults = {}
    if cb_ids:
        from collections import Counter
        dominant_cb_id = Counter(cb_ids).most_common(1)[0][0]
        cb_rows = _execute_query("""
            SELECT
                cb.payment_term_id,
                pt.name AS payment_term_name,
                cb.trade_term_id,
                tt.name AS trade_term_name,
                cb.vendor_contact_id AS seller_contact_id,
                CONCAT(COALESCE(sc.first_name,''), ' ', COALESCE(sc.last_name,'')) AS seller_contact_name,
                cb.buyer_contact_id,
                CONCAT(COALESCE(bc.first_name,''), ' ', COALESCE(bc.last_name,'')) AS buyer_contact_name,
                cb.important_notes_id,
                n.notes AS important_notes_text
            FROM costbooks cb
            LEFT JOIN payment_terms pt ON cb.payment_term_id = pt.id
            LEFT JOIN trade_terms tt   ON cb.trade_term_id = tt.id
            LEFT JOIN contacts sc      ON cb.vendor_contact_id = sc.id
            LEFT JOIN contacts bc      ON cb.buyer_contact_id = bc.id
            LEFT JOIN notes n          ON cb.important_notes_id = n.id
            WHERE cb.id = :cbid AND cb.delete_flag = 0
        """, {'cbid': dominant_cb_id})
        if cb_rows:
            costbook_defaults = dict(cb_rows[0])

    # Determine dominant VAT
    vats = [float(it['cb_vat']) for it in items if it.get('cb_vat') is not None]
    dominant_vat = None
    all_vats_same = False
    if vats:
        dominant_vat = max(set(vats), key=vats.count)
        all_vats_same = len(set(vats)) == 1

    return {
        'costbook_defaults': costbook_defaults,
        'items': [dict(it) for it in items],
        'dominant_vat': dominant_vat,
        'all_vats_same': all_vats_same,
    }


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