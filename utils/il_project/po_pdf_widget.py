# utils/il_project/po_pdf_widget.py
"""
Reusable PO PDF Download widget for Streamlit pages.

Fixes consolidated from IL_5 audit:
  Bug 1: PDF regenerated on EVERY rerun (selectbox change, scroll, any widget)
         → Fixed: @st.cache_data wrapper — only regenerates when params change
  Bug 2: Inconsistent titles ("📦 Purchase Order" vs "📄 Download PO")
         → Fixed: single render function, consistent layout
  Bug 3: Inconsistent selectbox label_visibility (collapsed vs visible)
         → Fixed: always show labels (Language / Orientation)
  Bug 4: Inconsistent error handling (.error vs .warning)
         → Fixed: always .warning() for non-critical PDF failure
  Bug 5: State key pattern inconsistency (po_pdf_lang vs po_done_lang)
         → Fixed: unified prefix `_po_pdf_{context}_{po_id}`
  Bug 6: _cleanup_po_dialog doesn't clean PDF selectbox keys
         → Fixed: cleanup function updated + dedicated cleanup
  Bug 7: Stale _po_created state if dialog closed via X button
         → Fixed: guard against stale po_id
  Bug 8: Multi-PO not accessible — PR with partial POs only shows first PO
         → Fixed: collect all distinct PO IDs from items, render PDF for each

Usage:
    from utils.il_project.po_pdf_widget import render_po_pdf_download, cleanup_pdf_state

    # Single PO download
    render_po_pdf_download(po_id=123, po_number="PO20260318-123-5", context="view_42")

    # Multi-PO from PR items (auto-detects all POs)
    render_po_pdf_downloads_for_pr(pr_id=42, pr_data=pr, items_df=items_df)

    # Cleanup
    cleanup_pdf_state(pr_id=42)
"""

import streamlit as st
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# CACHED PDF GENERATION — avoids regenerating on every rerun
# ══════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300, show_spinner="Generating PDF...")
def _cached_generate_pdf(po_id: int, language: str, orientation: str) -> Dict:
    """
    Cached wrapper around generate_po_pdf.
    Same po_id + language + orientation = cached result (5 min TTL).
    Only regenerates when params actually change.
    """
    from utils.il_project.po_pdf import generate_po_pdf
    return generate_po_pdf(po_id, language=language, orientation=orientation)


# ══════════════════════════════════════════════════════════════════════
# SINGLE PO PDF DOWNLOAD — reusable widget
# ══════════════════════════════════════════════════════════════════════

def render_po_pdf_download(
    po_id: int,
    po_number: str = "",
    context: str = "default",
    show_title: bool = True,
    compact: bool = False,
):
    """
    Render a standardized PO PDF download section.

    Args:
        po_id:      Purchase Order ID
        po_number:  PO number string (for display)
        context:    Unique key context to avoid widget key conflicts
                    e.g. "view_42", "created_42", "list_99"
        show_title: Show "📦 Purchase Order: PO-XXX" header
        compact:    If True, use collapsed labels (for inline/table use)
    """
    from utils.il_project.po_pdf import VALID_LANGUAGES, LANGUAGE_DISPLAY

    if not po_id:
        return

    key_prefix = f"_po_pdf_{context}"

    # Title
    if show_title:
        if po_number:
            st.markdown(f"**📦 Purchase Order: `{po_number}`**")
        else:
            st.markdown(f"**📦 Purchase Order #{po_id}**")

    # Controls + Download button
    c_lang, c_orient, c_btn = st.columns([2, 1, 1])

    label_vis = "collapsed" if compact else "visible"

    lang = c_lang.selectbox(
        "Language",
        options=VALID_LANGUAGES,
        format_func=lambda x: LANGUAGE_DISPLAY.get(x, x),
        key=f"{key_prefix}_lang_{po_id}",
        label_visibility=label_vis,
    )

    orient = c_orient.selectbox(
        "Orientation",
        options=['portrait', 'landscape'],
        format_func=lambda x: '📐 Portrait' if x == 'portrait' else '📐 Landscape',
        key=f"{key_prefix}_orient_{po_id}",
        label_visibility=label_vis,
    )

    # Generate PDF (cached — won't regenerate unless params change)
    result = _cached_generate_pdf(po_id, language=lang, orientation=orient)

    if result.get('success'):
        c_btn.download_button(
            "📥 Download PDF",
            data=result['pdf_bytes'],
            file_name=result['filename'],
            mime='application/pdf',
            use_container_width=True,
            key=f"{key_prefix}_dl_{po_id}",
        )
    else:
        c_btn.warning("⚠️ PDF failed")
        err_msg = result.get('message', '')
        if err_msg:
            logger.warning(f"PO PDF failed for PO {po_id}: {err_msg}")


# ══════════════════════════════════════════════════════════════════════
# MULTI-PO PDF DOWNLOAD — for PR with partial POs
# ══════════════════════════════════════════════════════════════════════

def render_po_pdf_downloads_for_pr(
    pr_id: int,
    pr_data: dict,
    items_df=None,
    context: str = "view",
):
    """
    Render PDF download for ALL POs linked to a PR.

    Handles the multi-PO case: when a PR has partial POs,
    items may reference different po_ids. This function:
    1. Collects all distinct (po_id, po_number) from items
    2. Falls back to pr.po_id if no items have po_id
    3. Renders a download widget for each PO

    Args:
        pr_id:    PR ID (for state key scoping)
        pr_data:  PR dict (from get_pr)
        items_df: PR items DataFrame (from get_pr_items_df) — optional
        context:  Key prefix context
    """
    # Collect all distinct POs from items
    po_set = {}  # {po_id: po_number}

    if items_df is not None and not items_df.empty:
        for _, row in items_df.iterrows():
            item_po_id = row.get('po_id')
            item_po_num = row.get('po_number')
            if item_po_id and str(item_po_id) not in ('', 'nan', 'None', '0'):
                po_id_int = int(item_po_id)
                if po_id_int not in po_set:
                    po_num_str = str(item_po_num) if item_po_num and str(item_po_num) not in ('', 'nan', 'None') else ''
                    po_set[po_id_int] = po_num_str

    # Fallback: use header-level po_id if no items have PO
    if not po_set and pr_data.get('po_id'):
        header_po_id = int(pr_data['po_id'])
        header_po_num = pr_data.get('po_number', '')
        po_set[header_po_id] = str(header_po_num) if header_po_num else ''

    if not po_set:
        return  # No POs linked

    st.divider()

    if len(po_set) == 1:
        # Single PO — simple layout
        po_id, po_number = next(iter(po_set.items()))
        render_po_pdf_download(
            po_id=po_id,
            po_number=po_number,
            context=f"{context}_{pr_id}",
            show_title=True,
        )
    else:
        # Multiple POs — show each with a label
        st.markdown(f"**📦 Purchase Orders ({len(po_set)})**")
        for i, (po_id, po_number) in enumerate(sorted(po_set.items())):
            label = po_number or f"PO #{po_id}"
            with st.container(border=True):
                st.caption(f"**{i+1}.** `{label}`")
                render_po_pdf_download(
                    po_id=po_id,
                    po_number=po_number,
                    context=f"{context}_{pr_id}_{i}",
                    show_title=False,
                    compact=True,
                )


# ══════════════════════════════════════════════════════════════════════
# POST-CREATION PDF — for "just created PO" success panel
# ══════════════════════════════════════════════════════════════════════

def render_po_created_success(pr_id: int) -> bool:
    """
    Render the PO creation success panel with PDF download.
    Reads from st.session_state[f'_po_created_{pr_id}'].

    Returns True if panel was rendered (PO just created), False otherwise.
    Used to guard subsequent UI (e.g. don't show "Create PO" button while success panel is up).
    """
    state_key = f'_po_created_{pr_id}'
    po_result = st.session_state.get(state_key)
    if not po_result:
        return False

    # Guard: verify PO actually exists (stale state protection)
    po_id = po_result.get('po_id')
    if not po_id:
        st.session_state.pop(state_key, None)
        return False

    # Success message
    from utils.il_project import fmt_vnd
    msg = f"✅ {po_result.get('message', 'PO created')}"
    excluded_count = po_result.get('excluded_count', 0)
    if excluded_count > 0:
        excluded_vnd = po_result.get('excluded_amount_vnd', 0)
        msg += (f"\n\n⚠️ {excluded_count} item(s) excluded (no costbook) — "
                f"{fmt_vnd(excluded_vnd)} not in PO.")
        if not po_result.get('all_items_covered'):
            msg += " PR remains APPROVED — bạn có thể tạo PO thêm cho các item còn lại."
    st.success(msg)

    # PDF download
    st.divider()
    render_po_pdf_download(
        po_id=po_id,
        po_number=po_result.get('po_number', ''),
        context=f"created_{pr_id}",
        show_title=True,
    )

    # Done button
    st.divider()
    if st.button("✅ Done — Close", type="primary", use_container_width=True,
                  key=f"_po_done_{pr_id}"):
        st.session_state.pop(state_key, None)
        cleanup_pdf_state(pr_id)
        st.cache_data.clear()
        st.rerun()

    return True


# ══════════════════════════════════════════════════════════════════════
# STATE CLEANUP
# ══════════════════════════════════════════════════════════════════════

def cleanup_pdf_state(pr_id: int):
    """
    Remove all PO PDF-related session_state keys for a PR.
    Call when closing PO dialog or navigating away.

    Cleans:
      - _po_pdf_*_{pr_id}*    (widget keys from render_po_pdf_download)
      - _po_created_{pr_id}    (PO creation result)
      - po_pdf_lang_*          (legacy keys from old code)
      - po_pdf_orient_*        (legacy keys from old code)
      - po_done_lang_*         (legacy keys from old code)
      - po_done_orient_*       (legacy keys from old code)
    """
    pr_id_str = str(pr_id)
    keys_to_remove = []
    for k in st.session_state:
        # New unified keys
        if k.startswith('_po_pdf_') and pr_id_str in k:
            keys_to_remove.append(k)
        # PO created result
        if k == f'_po_created_{pr_id}':
            keys_to_remove.append(k)
        # Legacy keys (backward compat cleanup)
        if k.startswith(('po_pdf_lang_', 'po_pdf_orient_',
                         'po_done_lang_', 'po_done_orient_')) and pr_id_str in k:
            keys_to_remove.append(k)

    for k in keys_to_remove:
        del st.session_state[k]