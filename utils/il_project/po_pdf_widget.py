# utils/il_project/po_pdf_widget.py
"""
Reusable PO PDF Download widget for Streamlit pages.

Core principle: LAZY generation — PDF is NEVER generated until user clicks.
  - Dialog open → shows selectors + "📄 Generate PDF" button (no PDF built yet)
  - User clicks Generate → builds PDF → stores in session_state → shows Download
  - User changes language/orientation → stored PDF cleared → back to Generate
  - Avoids: auto-generation on open, re-generation on rerun, form/page flicker

Fixes from IL_5 audit:
  Bug 1: PDF auto-generated on dialog open → FIXED: lazy, click-to-generate
  Bug 2: Inconsistent titles → FIXED: single render function
  Bug 3: Inconsistent label_visibility → FIXED: always show labels
  Bug 4: Inconsistent error handling → FIXED: always .warning()
  Bug 5: State key pattern inconsistency → FIXED: unified prefix
  Bug 6: Cleanup missing PDF keys → FIXED: dedicated cleanup
  Bug 7: Stale _po_created state → FIXED: guard check
  Bug 8: Multi-PO shows only first → FIXED: scans all items for distinct po_ids

Usage:
    from utils.il_project.po_pdf_widget import render_po_pdf_download, cleanup_pdf_state

    render_po_pdf_download(po_id=123, po_number="PO20260318-123-5", context="view_42")
    render_po_pdf_downloads_for_pr(pr_id=42, pr_data=pr, items_df=items_df)
    cleanup_pdf_state(pr_id=42)
"""

import streamlit as st
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# SINGLE PO PDF DOWNLOAD — lazy widget (click to generate)
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

    Two-step flow:
      Step 1: Language + Orientation selectors + "📄 Generate PDF" button
      Step 2: After click → PDF built → shows "📥 Download PDF" button

    Changing language/orientation after generation → clears cached PDF → back to Step 1.

    Args:
        po_id:      Purchase Order ID
        po_number:  PO number string (for display)
        context:    Unique key context to avoid widget key conflicts
        show_title: Show "📦 Purchase Order: PO-XXX" header
        compact:    If True, use collapsed labels (for inline/table use)
    """
    from utils.il_project.po_pdf import VALID_LANGUAGES, LANGUAGE_DISPLAY

    if not po_id:
        return

    key_prefix = f"_po_pdf_{context}"
    state_key = f"{key_prefix}_result_{po_id}"
    params_key = f"{key_prefix}_params_{po_id}"

    # Title
    if show_title:
        if po_number:
            st.markdown(f"**📦 Purchase Order: `{po_number}`**")
        else:
            st.markdown(f"**📦 Purchase Order #{po_id}**")

    # ── Selectors ─────────────────────────────────────────────────
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
        options=['landscape', 'portrait'],
        format_func=lambda x: '📐 Landscape' if x == 'landscape' else '📐 Portrait',
        key=f"{key_prefix}_orient_{po_id}",
        label_visibility=label_vis,
    )

    # ── Check if params changed since last generation ─────────────
    current_params = (po_id, lang, orient)
    stored_params = st.session_state.get(params_key)
    stored_result = st.session_state.get(state_key)

    # Invalidate cached PDF if user changed language or orientation
    if stored_result and stored_params != current_params:
        st.session_state.pop(state_key, None)
        st.session_state.pop(params_key, None)
        stored_result = None

    # ── Step 1 or Step 2 ──────────────────────────────────────────
    if stored_result and stored_result.get('success'):
        # Step 2: PDF ready → show Download button
        c_btn.download_button(
            "📥 Download PDF",
            data=stored_result['pdf_bytes'],
            file_name=stored_result['filename'],
            mime='application/pdf',
            use_container_width=True,
            key=f"{key_prefix}_dl_{po_id}",
        )
    elif stored_result and not stored_result.get('success'):
        # Generation was attempted but failed
        c_btn.warning("⚠️ PDF failed")
        err = stored_result.get('message', '')
        if err:
            st.caption(f"Error: {err}")
    else:
        # Step 1: No PDF yet → show Generate button
        if c_btn.button(
            "📄 Generate PDF",
            use_container_width=True,
            key=f"{key_prefix}_gen_{po_id}",
        ):
            _do_generate(po_id, lang, orient, state_key, params_key)
            # NOTE: Do NOT call st.rerun() here!
            # This widget runs inside @st.dialog which behaves like a fragment.
            # st.rerun() = full-app rerun → dialog trigger (pop'd) is gone → dialog closes.
            # Instead, render download inline immediately after generation.
            result = st.session_state.get(state_key)
            if result and result.get('success'):
                st.download_button(
                    "📥 Download PDF",
                    data=result['pdf_bytes'],
                    file_name=result['filename'],
                    mime='application/pdf',
                    use_container_width=True,
                    key=f"{key_prefix}_dl_immediate_{po_id}",
                )
            elif result:
                st.warning(f"⚠️ PDF generation failed: {result.get('message', '')}")


def _do_generate(
    po_id: int,
    language: str,
    orientation: str,
    state_key: str,
    params_key: str,
):
    """
    Generate PDF and store result in session_state.
    Called only when user clicks "📄 Generate PDF".
    """
    try:
        from utils.il_project.po_pdf import generate_po_pdf
        result = generate_po_pdf(po_id, language=language, orientation=orientation)
        st.session_state[state_key] = result
        st.session_state[params_key] = (po_id, language, orientation)
        if result.get('success'):
            logger.info(f"PDF generated on-demand: PO {po_id}, lang={language}")
        else:
            logger.warning(f"PDF generation failed: PO {po_id}: {result.get('message', '')}")
    except Exception as e:
        logger.error(f"PDF generation error: PO {po_id}: {e}")
        st.session_state[state_key] = {
            'success': False, 'pdf_bytes': None,
            'message': str(e), 'filename': '', 'po_number': '',
        }
        st.session_state[params_key] = (po_id, language, orientation)


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
    3. Renders a lazy download widget for each PO
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
        po_id, po_number = next(iter(po_set.items()))
        render_po_pdf_download(
            po_id=po_id,
            po_number=po_number,
            context=f"{context}_{pr_id}",
            show_title=True,
        )
    else:
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

    PDF is NOT auto-generated — user clicks "📄 Generate PDF" when ready.

    Returns True if panel was rendered (PO just created), False otherwise.
    """
    state_key = f'_po_created_{pr_id}'
    po_result = st.session_state.get(state_key)
    if not po_result:
        return False

    # Guard: verify PO result has po_id (stale state protection)
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

    # PDF download (lazy — user clicks Generate)
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
        # Note: no st.cache_data.clear() needed — fragments re-fetch their own data on rerun
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
      - _po_pdf_*_{pr_id}*    (widget keys: selectors, results, params)
      - _po_created_{pr_id}    (PO creation result)
      - po_pdf_lang_*          (legacy keys from old code)
      - po_pdf_orient_*        (legacy keys)
      - po_done_lang_*         (legacy keys)
      - po_done_orient_*       (legacy keys)
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