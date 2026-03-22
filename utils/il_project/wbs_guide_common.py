# utils/il_project/guide_common.py
"""
Shared utilities for bilingual User Guide across all pages.

Provides:
  - _t()           — pick field by language with fallback
  - search_guide() — search sections + FAQ by keyword/tags
  - render_guide_dialog_content() — shared dialog UI pattern
  - DEFAULT_LANG   — 'vi'
"""

from typing import Dict, List


DEFAULT_LANG = 'vi'


def _t(item: dict, field: str, lang: str) -> str:
    """Get translated field. Falls back to English if Vietnamese missing."""
    val = item.get(f'{field}_{lang}')
    if val:
        return val
    return item.get(f'{field}_en', item.get(f'{field}_vi', ''))


def search_guide(query: str, sections: List[Dict], faq: List[Dict]) -> dict:
    """Search guide content by query string (works across both languages via tags)."""
    if not query or len(query) < 2:
        return {'sections': sections, 'faq': faq}

    q = query.lower()
    matched_sections = [
        s for s in sections
        if q in s.get('title', '').lower()
        or q in s.get('content', '').lower()
        or any(q in t for t in s.get('tags', []))
    ]
    matched_faq = [
        f for f in faq
        if q in f.get('q', '').lower()
        or q in f.get('a', '').lower()
        or any(q in t for t in f.get('tags', []))
    ]
    return {'sections': matched_sections, 'faq': matched_faq}


def render_guide_dialog_content(
    sections: List[Dict],
    faq_items: List[Dict],
    workflows: List[Dict],
    context_tips: List[str],
    lang: str = 'vi',
    search_q: str = '',
):
    """
    Shared dialog body renderer. Call INSIDE @st.dialog.
    Handles: context tips, search filtering, tabs (Guide/Workflows/FAQ).
    """
    import streamlit as st

    # Context tips
    for tip in context_tips:
        st.info(tip)
    if context_tips:
        st.divider()

    # Search filter
    if search_q and len(search_q) >= 2:
        result = search_guide(search_q, sections, faq_items)
        sections = result['sections']
        faq_items = result['faq']
        q_lower = search_q.lower()
        workflows = [w for w in workflows if q_lower in w['title'].lower()
                     or any(q_lower in s.lower() for s in w.get('steps', []))
                     or any(q_lower in t for t in w.get('tags', []))]

        if not sections and not faq_items and not workflows:
            msg = f"Không tìm thấy '{search_q}'." if lang == 'vi' else f"No results for '{search_q}'."
            st.warning(msg)
            return

    # Tab labels
    lbl_guide = "📖 Hướng dẫn" if lang == 'vi' else "📖 Guide"
    lbl_wf    = "🔄 Quy trình"  if lang == 'vi' else "🔄 Workflows"
    lbl_faq   = "❓ Hỏi đáp"    if lang == 'vi' else "❓ FAQ"

    tab_labels = [lbl_guide]
    if workflows:
        tab_labels.append(lbl_wf)
    if faq_items:
        tab_labels.append(lbl_faq)

    guide_tabs = st.tabs(tab_labels)

    # Guide sections
    with guide_tabs[0]:
        if not sections:
            st.caption("Không có nội dung khớp." if lang == 'vi' else "No matching content.")
        else:
            for s in sections:
                with st.expander(f"{s['icon']} {s['title']}", expanded=bool(search_q)):
                    st.markdown(s['content'])

    # Workflows
    if workflows and lbl_wf in tab_labels:
        with guide_tabs[tab_labels.index(lbl_wf)]:
            for wf in workflows:
                with st.expander(f"{wf['icon']} {wf['title']}", expanded=bool(search_q)):
                    step_num = 0
                    for step in wf['steps']:
                        if step.startswith("  "):
                            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;{step.strip()}")
                        else:
                            step_num += 1
                            st.markdown(f"**{step_num}.** {step}")

    # FAQ
    if faq_items and lbl_faq in tab_labels:
        with guide_tabs[tab_labels.index(lbl_faq)]:
            for item in faq_items:
                with st.expander(f"❓ {item['q']}", expanded=bool(search_q)):
                    st.markdown(item['a'])
