# utils/il_project/po_pdf.py
"""
Purchase Order PDF Generator for IL Project Management.

Generates professional PO documents from approved Purchase Orders.
Supports English, Vietnamese, and Bilingual layouts.

Design: on-demand generation from DB data — no S3 storage needed.
All PO data lives in the database, so PDF can be regenerated anytime.

Public API:
    generate_po_pdf(po_id, language)  → Dict with pdf_bytes

Usage in Streamlit:
    result = generate_po_pdf(po_id, language='en')
    if result['success']:
        st.download_button("📄 Download PO", result['pdf_bytes'],
                           file_name=result['filename'], mime='application/pdf')
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
# FONT REGISTRATION
# ══════════════════════════════════════════════════════════════════════

_FONT_REGISTERED = False

# Resolve project root: po_pdf.py is at utils/il_project/po_pdf.py
# Project root = 2 levels up from this file's parent
from pathlib import Path as _Path
_PROJECT_ROOT = _Path(__file__).resolve().parent.parent.parent

_FONT_PATHS = {
    'DejaVu':      str(_PROJECT_ROOT / 'fonts' / 'DejaVuSans.ttf'),
    'DejaVu-Bold': str(_PROJECT_ROOT / 'fonts' / 'DejaVuSans-Bold.ttf'),
}

# System fallback if project fonts/ missing
_FONT_PATHS_SYSTEM = {
    'DejaVu':      '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    'DejaVu-Bold': '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
}

# Fallback if DejaVu not found anywhere
_FALLBACK_FONT = 'Helvetica'
_FALLBACK_FONT_BOLD = 'Helvetica-Bold'


def _register_fonts() -> Tuple[str, str]:
    """Register Unicode fonts (DejaVu Sans). Returns (regular, bold) font names.
    Resolution: project fonts/ → system fonts → Helvetica fallback.
    """
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return 'DejaVu', 'DejaVu-Bold'

    import os
    # Try project fonts first, then system
    for source, paths in [('project', _FONT_PATHS), ('system', _FONT_PATHS_SYSTEM)]:
        if os.path.isfile(paths['DejaVu']) and os.path.isfile(paths['DejaVu-Bold']):
            try:
                pdfmetrics.registerFont(TTFont('DejaVu', paths['DejaVu']))
                pdfmetrics.registerFont(TTFont('DejaVu-Bold', paths['DejaVu-Bold']))
                _FONT_REGISTERED = True
                logger.debug(f"Fonts registered from {source}: {paths['DejaVu']}")
                return 'DejaVu', 'DejaVu-Bold'
            except Exception as e:
                logger.warning(f"Font registration failed ({source}): {e}")
                continue

    logger.warning("DejaVu fonts not found — using Helvetica (no Vietnamese support).")
    return _FALLBACK_FONT, _FALLBACK_FONT_BOLD


# ══════════════════════════════════════════════════════════════════════
# LANGUAGE LABELS
# ══════════════════════════════════════════════════════════════════════

_LABELS = {
    'en': {
        'title':            'PURCHASE ORDER',
        'po_number':        'PO Number',
        'po_date':          'PO Date',
        'po_type':          'PO Type',
        'currency':         'Currency',
        'exchange_rate':    'USD Exchange Rate',
        'payment_terms':    'Payment Terms',
        'trade_terms':      'Trade Terms (Incoterms)',
        'external_ref':     'External Ref',
        'seller':           'SELLER',
        'buyer':            'BUYER',
        'company':          'Company',
        'address':          'Address',
        'contact':          'Contact',
        'phone':            'Phone',
        'email':            'Email',
        'tax_number':       'Tax Number',
        'ship_to':          'Ship To',
        'bill_to':          'Bill To',
        'line_items':       'ORDER ITEMS',
        'col_no':           '#',
        'col_pt_code':      'PT Code',
        'col_description':  'Description',
        'col_brand':        'Brand',
        'col_qty':          'Qty',
        'col_uom':          'UOM',
        'col_unit_cost':    'Unit Price',
        'col_amount':       'Amount',
        'col_vat':          'VAT %',
        'subtotal':         'Subtotal',
        'vat_total':        'VAT Total',
        'grand_total':      'Grand Total',
        'notes':            'Important Notes',
        'signature':        'Authorized Signature',
        'buyer_sign':       'Buyer',
        'seller_sign':      'Seller',
        'page':             'Page',
        'generated':        'Generated',
        'dual_uom_note':    'Buy UOM / Std UOM shown where different',
    },
    'vi': {
        'title':            'ĐƠN ĐẶT HÀNG',
        'po_number':        'Số PO',
        'po_date':          'Ngày PO',
        'po_type':          'Loại PO',
        'currency':         'Tiền tệ',
        'exchange_rate':    'Tỷ giá USD',
        'payment_terms':    'Điều khoản thanh toán',
        'trade_terms':      'Điều khoản thương mại (Incoterms)',
        'external_ref':     'Mã tham chiếu',
        'seller':           'BÊN BÁN',
        'buyer':            'BÊN MUA',
        'company':          'Công ty',
        'address':          'Địa chỉ',
        'contact':          'Liên hệ',
        'phone':            'Điện thoại',
        'email':            'Email',
        'tax_number':       'Mã số thuế',
        'ship_to':          'Giao hàng đến',
        'bill_to':          'Hóa đơn gửi đến',
        'line_items':       'DANH MỤC HÀNG HÓA',
        'col_no':           'STT',
        'col_pt_code':      'Mã SP',
        'col_description':  'Mô tả',
        'col_brand':        'Thương hiệu',
        'col_qty':          'SL',
        'col_uom':          'ĐVT',
        'col_unit_cost':    'Đơn giá',
        'col_amount':       'Thành tiền',
        'col_vat':          'VAT %',
        'subtotal':         'Tạm tính',
        'vat_total':        'Tổng VAT',
        'grand_total':      'Tổng cộng',
        'notes':            'Ghi chú quan trọng',
        'signature':        'Chữ ký xác nhận',
        'buyer_sign':       'Bên mua',
        'seller_sign':      'Bên bán',
        'page':             'Trang',
        'generated':        'Ngày tạo',
        'dual_uom_note':    'ĐVT mua / ĐVT chuẩn hiển thị khi khác nhau',
    },
}


def _get_labels(language: str) -> Dict[str, str]:
    """Get label set. Bilingual = 'en' primary with 'vi' in parentheses."""
    if language == 'vi':
        return _LABELS['vi']
    if language == 'bilingual':
        en = _LABELS['en']
        vi = _LABELS['vi']
        return {k: f"{en[k]} / {vi[k]}" if k not in ('col_no',) else en[k]
                for k in en}
    return _LABELS['en']


# ══════════════════════════════════════════════════════════════════════
# DATA QUERY
# ══════════════════════════════════════════════════════════════════════

def _get_po_full_data(po_id: int) -> Optional[Dict]:
    """
    Query complete PO data for PDF rendering.
    Returns dict with: header, seller, buyer, items, contacts, notes.
    """
    try:
        from ..db import execute_query

        # ── PO Header + Companies + Terms ──
        header_rows = execute_query("""
            SELECT
                po.id, po.po_number, po.po_date, po.po_type,
                po.purchase_order_type, po.po_note, po.external_ref_number,
                po.usd_exchange_rate, po.ship_to, po.bill_to,

                -- Currency
                cur.code AS currency_code, cur.name AS currency_name,

                -- Seller company
                sc.id AS seller_id,
                COALESCE(sc.english_name, sc.local_name) AS seller_name,
                sc.company_code AS seller_code,
                sc.tax_number AS seller_tax,
                sc.street AS seller_street,
                ss.name AS seller_state,
                sco.name AS seller_country,
                sc.zip_code AS seller_zip,

                -- Buyer company
                bc.id AS buyer_id,
                COALESCE(bc.english_name, bc.local_name) AS buyer_name,
                bc.company_code AS buyer_code,
                bc.tax_number AS buyer_tax,
                bc.street AS buyer_street,
                bs.name AS buyer_state,
                bco.name AS buyer_country,
                bc.zip_code AS buyer_zip,

                -- Terms
                pt.name AS payment_term_name,
                pt.description AS payment_term_desc,
                tt.name AS trade_term_name,
                tt.description AS trade_term_desc,

                -- Contacts
                CONCAT(COALESCE(selc.first_name,''), ' ', COALESCE(selc.last_name,''))
                    AS seller_contact_name,
                selc.email AS seller_contact_email,
                selc.phone AS seller_contact_phone,

                CONCAT(COALESCE(buyc.first_name,''), ' ', COALESCE(buyc.last_name,''))
                    AS buyer_contact_name,
                buyc.email AS buyer_contact_email,
                buyc.phone AS buyer_contact_phone,

                -- Notes
                n.notes AS important_notes_text,

                -- Logo (from medias table via companies.logo_id)
                buyer_logo.path AS buyer_logo_path,
                seller_logo.path AS seller_logo_path

            FROM purchase_orders po
            LEFT JOIN currencies cur  ON po.currency_id = cur.id
            LEFT JOIN companies sc    ON po.seller_company_id = sc.id
            LEFT JOIN states ss       ON sc.state_province_id = ss.id
            LEFT JOIN countries sco   ON sc.country_id = sco.id
            LEFT JOIN companies bc    ON po.buyer_company_id = bc.id
            LEFT JOIN states bs       ON bc.state_province_id = bs.id
            LEFT JOIN countries bco   ON bc.country_id = bco.id
            LEFT JOIN payment_terms pt ON po.payment_term_id = pt.id
            LEFT JOIN trade_terms tt   ON po.trade_term_id = tt.id
            LEFT JOIN contacts selc   ON po.seller_contact_id = selc.id
            LEFT JOIN contacts buyc   ON po.buyer_contact_id = buyc.id
            LEFT JOIN notes n         ON po.notes_id = n.id
            LEFT JOIN medias buyer_logo  ON bc.logo_id = buyer_logo.id
            LEFT JOIN medias seller_logo ON sc.logo_id = seller_logo.id
            WHERE po.id = :po_id
            LIMIT 1
        """, {'po_id': po_id})

        if not header_rows:
            return None
        header = dict(header_rows[0])

        # ── PO Line Items ──
        items = execute_query("""
            SELECT
                ppo.id,
                ppo.product_id,
                ppo.product_pn AS pt_code,
                p.name AS product_name,
                COALESCE(b.brand_name, '') AS brand_name,
                ppo.purchase_quantity AS buy_qty,
                ppo.purchase_unit_cost AS buy_cost,
                ppo.purchaseuom AS buy_uom,
                ppo.quantity AS std_qty,
                ppo.unit_cost AS std_cost,
                ppo.product_uom AS std_uom,
                ppo.conversion,
                ppo.vat_gst AS vat,
                ppo.minimum_order_quantity AS moq,
                ppo.standard_pack_quantity AS spq,
                cur.code AS item_currency_code
            FROM product_purchase_orders ppo
            LEFT JOIN products p     ON ppo.product_id = p.id
            LEFT JOIN brands b       ON p.brand_id = b.id
            LEFT JOIN currencies cur ON ppo.product_currency_id = cur.id
            WHERE ppo.purchase_order_id = :po_id
              AND ppo.delete_flag = 0
            ORDER BY ppo.id
        """, {'po_id': po_id})

        # ── Find project_id from PR link ──
        pr_link = execute_query("""
            SELECT pr.project_id, pr.pr_number
            FROM il_purchase_requests pr
            WHERE pr.po_id = :po_id AND pr.delete_flag = 0
            LIMIT 1
        """, {'po_id': po_id})
        project_id = pr_link[0]['project_id'] if pr_link else None
        pr_number = pr_link[0]['pr_number'] if pr_link else None

        return {
            'header': header,
            'items': [dict(it) for it in items],
            'project_id': project_id,
            'pr_number': pr_number,
        }

    except Exception as e:
        logger.error(f"_get_po_full_data({po_id}) failed: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════
# LOGO FROM S3
# ══════════════════════════════════════════════════════════════════════

def _download_logo(s3_path: Optional[str]) -> Optional[bytes]:
    """
    Download company logo from S3 using medias.path.

    Args:
        s3_path: The `path` column from medias table
                 (e.g. 'company-logo/1735796413734-Vertical.png')

    Returns:
        Image bytes, or None if unavailable.
    """
    if not s3_path:
        return None
    try:
        from .s3_il import ILProjectS3Manager
        s3 = ILProjectS3Manager()
        img_bytes = s3.download_file(s3_path)
        if img_bytes and len(img_bytes) > 100:  # sanity check
            logger.debug(f"Logo downloaded: {s3_path} ({len(img_bytes):,} bytes)")
            return img_bytes
        logger.debug(f"Logo download empty or too small: {s3_path}")
        return None
    except Exception as e:
        logger.warning(f"Logo download failed ({s3_path}): {e}")
        return None


def _make_logo_image(logo_bytes: Optional[bytes], max_height: float = 18 * mm,
                     max_width: float = 50 * mm):
    """
    Create a ReportLab Image from logo bytes, scaled to fit within bounds.

    Returns:
        reportlab.platypus.Image or None
    """
    if not logo_bytes:
        return None
    try:
        from reportlab.platypus import Image as RLImage
        from PIL import Image as PILImage

        img_buf = io.BytesIO(logo_bytes)
        pil_img = PILImage.open(img_buf)
        orig_w, orig_h = pil_img.size

        # Scale to fit within max bounds, preserving aspect ratio
        ratio = min(max_width / orig_w, max_height / orig_h, 1.0)
        draw_w = orig_w * ratio
        draw_h = orig_h * ratio

        img_buf.seek(0)
        rl_img = RLImage(img_buf, width=draw_w, height=draw_h)
        return rl_img

    except ImportError:
        # PIL not available — try reportlab Image directly (no scaling)
        try:
            from reportlab.platypus import Image as RLImage
            img_buf = io.BytesIO(logo_bytes)
            return RLImage(img_buf, width=max_width, height=max_height)
        except Exception:
            return None
    except Exception as e:
        logger.warning(f"Could not create logo image: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════
# NUMBER FORMATTING
# ══════════════════════════════════════════════════════════════════════

def _fmt_number(value, decimals: int = 2) -> str:
    """Format number with thousand separators."""
    if value is None:
        return '—'
    try:
        v = float(value)
        if v == 0:
            return '—'
        return f"{v:,.{decimals}f}"
    except (TypeError, ValueError):
        return '—'


def _fmt_qty(value) -> str:
    """Format quantity: no trailing zeros."""
    if value is None:
        return '—'
    try:
        v = float(value)
        if v == int(v):
            return f"{int(v):,}"
        return f"{v:,.2f}"
    except (TypeError, ValueError):
        return '—'


def _safe_str(value, default: str = '—') -> str:
    """Convert to string, return default for None/empty."""
    if value is None:
        return default
    s = str(value).strip()
    return s if s else default


# ══════════════════════════════════════════════════════════════════════
# PDF STYLES
# ══════════════════════════════════════════════════════════════════════

# Color palette — professional blue theme
_COLOR_PRIMARY   = colors.HexColor('#1e3a5f')   # Dark navy
_COLOR_ACCENT    = colors.HexColor('#2563eb')   # Blue
_COLOR_HEADER_BG = colors.HexColor('#f0f4f8')   # Light blue-gray
_COLOR_ROW_ALT   = colors.HexColor('#f9fafb')   # Zebra stripe
_COLOR_BORDER    = colors.HexColor('#d1d5db')   # Gray border
_COLOR_TEXT       = colors.HexColor('#1f2937')   # Dark text
_COLOR_LIGHT     = colors.HexColor('#6b7280')   # Light text


def _build_styles(font: str, font_bold: str) -> Dict[str, ParagraphStyle]:
    """Build all paragraph styles for the PO PDF."""
    return {
        'title': ParagraphStyle(
            'POTitle', fontName=font_bold, fontSize=16,
            textColor=_COLOR_PRIMARY, alignment=TA_CENTER,
            spaceAfter=2 * mm,
        ),
        'subtitle': ParagraphStyle(
            'POSubtitle', fontName=font, fontSize=9,
            textColor=_COLOR_LIGHT, alignment=TA_CENTER,
            spaceAfter=4 * mm,
        ),
        'section_header': ParagraphStyle(
            'SectionHeader', fontName=font_bold, fontSize=10,
            textColor=_COLOR_PRIMARY, spaceBefore=4 * mm, spaceAfter=2 * mm,
        ),
        'label': ParagraphStyle(
            'Label', fontName=font_bold, fontSize=8,
            textColor=_COLOR_LIGHT,
        ),
        'value': ParagraphStyle(
            'Value', fontName=font, fontSize=8.5,
            textColor=_COLOR_TEXT,
        ),
        'value_bold': ParagraphStyle(
            'ValueBold', fontName=font_bold, fontSize=8.5,
            textColor=_COLOR_TEXT,
        ),
        'cell': ParagraphStyle(
            'Cell', fontName=font, fontSize=7.5,
            textColor=_COLOR_TEXT, leading=10,
        ),
        'cell_bold': ParagraphStyle(
            'CellBold', fontName=font_bold, fontSize=7.5,
            textColor=_COLOR_TEXT, leading=10,
        ),
        'cell_right': ParagraphStyle(
            'CellRight', fontName=font, fontSize=7.5,
            textColor=_COLOR_TEXT, alignment=TA_RIGHT, leading=10,
        ),
        'cell_center': ParagraphStyle(
            'CellCenter', fontName=font, fontSize=7.5,
            textColor=_COLOR_TEXT, alignment=TA_CENTER, leading=10,
        ),
        'total_label': ParagraphStyle(
            'TotalLabel', fontName=font_bold, fontSize=8.5,
            textColor=_COLOR_PRIMARY, alignment=TA_RIGHT,
        ),
        'total_value': ParagraphStyle(
            'TotalValue', fontName=font_bold, fontSize=9,
            textColor=_COLOR_PRIMARY, alignment=TA_RIGHT,
        ),
        'grand_total': ParagraphStyle(
            'GrandTotal', fontName=font_bold, fontSize=11,
            textColor=_COLOR_PRIMARY, alignment=TA_RIGHT,
        ),
        'notes': ParagraphStyle(
            'Notes', fontName=font, fontSize=8,
            textColor=_COLOR_TEXT, leading=11,
        ),
        'footer': ParagraphStyle(
            'Footer', fontName=font, fontSize=7,
            textColor=_COLOR_LIGHT, alignment=TA_CENTER,
        ),
        'sign_label': ParagraphStyle(
            'SignLabel', fontName=font_bold, fontSize=8,
            textColor=_COLOR_PRIMARY, alignment=TA_CENTER,
        ),
        'sign_line': ParagraphStyle(
            'SignLine', fontName=font, fontSize=8,
            textColor=_COLOR_LIGHT, alignment=TA_CENTER,
        ),
    }


# ══════════════════════════════════════════════════════════════════════
# PDF BUILDER
# ══════════════════════════════════════════════════════════════════════

def _build_address(street, state, zip_code, country) -> str:
    """Build address string from parts."""
    parts = [p for p in [
        _safe_str(street, ''),
        _safe_str(state, ''),
        _safe_str(zip_code, ''),
        _safe_str(country, ''),
    ] if p]
    return ', '.join(parts) if parts else '—'


def _build_po_pdf(data: Dict, language: str = 'en') -> bytes:
    """
    Build PDF bytes from PO data dict.

    Args:
        data: from _get_po_full_data()
        language: 'en' | 'vi' | 'bilingual'

    Returns:
        PDF file content as bytes.
    """
    font, font_bold = _register_fonts()
    styles = _build_styles(font, font_bold)
    labels = _get_labels(language)

    header = data['header']
    items = data['items']
    ccy = _safe_str(header.get('currency_code'), 'USD')

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=20 * mm,
    )

    story: List = []
    page_width = A4[0] - 30 * mm   # usable width

    # ── Header with Logo ──────────────────────────────────────────
    po_num = _safe_str(header.get('po_number'))
    po_date = header.get('po_date')
    date_str = po_date.strftime('%d/%m/%Y') if hasattr(po_date, 'strftime') else str(po_date or '')

    # Try to load buyer company logo from S3
    buyer_logo_img = _make_logo_image(
        _download_logo(header.get('buyer_logo_path')),
        max_height=20 * mm, max_width=55 * mm,
    )

    if buyer_logo_img:
        # Layout: [Logo (left) | Title + PO info (right)]
        title_block = [
            Paragraph(labels['title'], styles['title']),
            Paragraph(
                f"{labels['po_number']}: <b>{po_num}</b> &nbsp;&nbsp;|&nbsp;&nbsp; "
                f"{labels['po_date']}: <b>{date_str}</b>",
                styles['subtitle'],
            ),
        ]
        logo_w = 58 * mm
        title_w = page_width - logo_w
        header_banner = Table(
            [[[buyer_logo_img], title_block]],
            colWidths=[logo_w, title_w],
        )
        header_banner.setStyle(TableStyle([
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN',         (0, 0), (0, 0), 'LEFT'),
            ('ALIGN',         (1, 0), (1, 0), 'CENTER'),
            ('TOPPADDING',    (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('LEFTPADDING',   (0, 0), (0, 0), 0),
            ('RIGHTPADDING',  (1, 0), (1, 0), 0),
        ]))
        story.append(header_banner)
    else:
        # Fallback: centered title (no logo available)
        story.append(Paragraph(labels['title'], styles['title']))
        story.append(Paragraph(
            f"{labels['po_number']}: <b>{po_num}</b> &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"{labels['po_date']}: <b>{date_str}</b>",
            styles['subtitle'],
        ))

    story.append(HRFlowable(
        width="100%", thickness=1, color=_COLOR_PRIMARY,
        spaceAfter=4 * mm,
    ))

    # ── PO Header Info (2-column) ──────────────────────────────────
    po_type = _safe_str(header.get('purchase_order_type', ''))
    po_type_display = po_type.replace('_', ' ').title() if po_type != '—' else '—'

    header_data = [
        [
            Paragraph(f"<b>{labels['po_type']}:</b> {po_type_display}", styles['value']),
            Paragraph(f"<b>{labels['currency']}:</b> {ccy}", styles['value']),
        ],
        [
            Paragraph(
                f"<b>{labels['payment_terms']}:</b> "
                f"{_safe_str(header.get('payment_term_name'))}",
                styles['value'],
            ),
            Paragraph(
                f"<b>{labels['exchange_rate']}:</b> "
                f"{_fmt_number(header.get('usd_exchange_rate'), 4)}",
                styles['value'],
            ),
        ],
        [
            Paragraph(
                f"<b>{labels['trade_terms']}:</b> "
                f"{_safe_str(header.get('trade_term_name'))}",
                styles['value'],
            ),
            Paragraph(
                f"<b>{labels['external_ref']}:</b> "
                f"{_safe_str(header.get('external_ref_number'))}",
                styles['value'],
            ),
        ],
    ]

    half_w = page_width / 2
    header_table = Table(header_data, colWidths=[half_w, half_w])
    header_table.setStyle(TableStyle([
        ('VALIGN',   (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 4 * mm))

    # ── Seller / Buyer (2-column boxes) ────────────────────────────
    def _company_block(side: str) -> List:
        """Build company info as list of Paragraphs for table cell."""
        prefix = 'seller' if side == 'seller' else 'buyer'
        block_label = labels[prefix]
        name    = _safe_str(header.get(f'{prefix}_name'))
        tax     = _safe_str(header.get(f'{prefix}_tax'))
        address = _build_address(
            header.get(f'{prefix}_street'),
            header.get(f'{prefix}_state'),
            header.get(f'{prefix}_zip'),
            header.get(f'{prefix}_country'),
        )
        contact = _safe_str(header.get(f'{prefix}_contact_name'))
        email   = _safe_str(header.get(f'{prefix}_contact_email'))
        phone   = _safe_str(header.get(f'{prefix}_contact_phone'))

        return [
            Paragraph(f"<b>{block_label}</b>", styles['section_header']),
            Paragraph(f"<b>{name}</b>", styles['value_bold']),
            Paragraph(f"{labels['address']}: {address}", styles['value']),
            Paragraph(f"{labels['tax_number']}: {tax}", styles['value']),
            Spacer(1, 1.5 * mm),
            Paragraph(f"{labels['contact']}: {contact}", styles['value']),
            Paragraph(f"{labels['email']}: {email}", styles['value']),
            Paragraph(f"{labels['phone']}: {phone}", styles['value']),
        ]

    # Ship-to / Bill-to (below buyer)
    ship_to = _safe_str(header.get('ship_to'))
    bill_to = _safe_str(header.get('bill_to'))

    seller_block = _company_block('seller')
    buyer_block = _company_block('buyer')
    if ship_to != '—':
        buyer_block.append(Spacer(1, 1.5 * mm))
        buyer_block.append(Paragraph(f"{labels['ship_to']}: {ship_to}", styles['value']))
    if bill_to != '—':
        buyer_block.append(Paragraph(f"{labels['bill_to']}: {bill_to}", styles['value']))

    box_w = page_width / 2 - 2 * mm
    company_table = Table(
        [[seller_block, buyer_block]],
        colWidths=[box_w, box_w],
    )
    company_table.setStyle(TableStyle([
        ('VALIGN',     (0, 0), (-1, -1), 'TOP'),
        ('BOX',        (0, 0), (0, 0), 0.5, _COLOR_BORDER),
        ('BOX',        (1, 0), (1, 0), 0.5, _COLOR_BORDER),
        ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#fafbfc')),
        ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#fafbfc')),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING',   (0, 0), (-1, -1), 6),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
    ]))
    story.append(company_table)
    story.append(Spacer(1, 5 * mm))

    # ── Line Items Section ─────────────────────────────────────────
    story.append(Paragraph(f"■ {labels['line_items']}", styles['section_header']))

    # Detect if any item has dual UOM
    has_dual_uom = any(
        it.get('buy_uom') and it.get('std_uom')
        and str(it.get('buy_uom', '')).strip() != str(it.get('std_uom', '')).strip()
        for it in items
    )

    # Table header row
    col_headers = [
        Paragraph(f"<b>{labels['col_no']}</b>", styles['cell_center']),
        Paragraph(f"<b>{labels['col_pt_code']}</b>", styles['cell_bold']),
        Paragraph(f"<b>{labels['col_description']}</b>", styles['cell_bold']),
        Paragraph(f"<b>{labels['col_brand']}</b>", styles['cell_bold']),
        Paragraph(f"<b>{labels['col_qty']}</b>", styles['cell_center']),
        Paragraph(f"<b>{labels['col_uom']}</b>", styles['cell_center']),
        Paragraph(f"<b>{labels['col_unit_cost']}</b>", styles['cell_right']),
        Paragraph(f"<b>{labels['col_amount']}</b>", styles['cell_right']),
        Paragraph(f"<b>{labels['col_vat']}</b>", styles['cell_center']),
    ]

    # Column widths (total ≈ page_width)
    col_widths = [
        12 * mm,    # #
        28 * mm,    # PT Code
        55 * mm,    # Description
        24 * mm,    # Brand
        18 * mm,    # Qty
        18 * mm,    # UOM
        28 * mm,    # Unit Price
        32 * mm,    # Amount
        15 * mm,    # VAT
    ]
    # Scale to fit page width
    total_w = sum(col_widths)
    scale = page_width / total_w
    col_widths = [w * scale for w in col_widths]

    # Build rows
    table_data = [col_headers]
    subtotal = 0.0
    vat_total = 0.0

    for idx, it in enumerate(items, 1):
        buy_qty  = float(it.get('buy_qty') or it.get('std_qty') or 0)
        buy_cost = float(it.get('buy_cost') or it.get('std_cost') or 0)
        amount   = buy_qty * buy_cost
        vat_pct  = float(it.get('vat') or 0)
        vat_amt  = amount * vat_pct / 100

        subtotal  += amount
        vat_total += vat_amt

        # UOM display
        buy_uom = _safe_str(it.get('buy_uom'), '')
        std_uom = _safe_str(it.get('std_uom'), '')
        if has_dual_uom and buy_uom and std_uom and buy_uom != std_uom:
            uom_display = f"{buy_uom}/{std_uom}"
        else:
            uom_display = buy_uom or std_uom or '—'

        row = [
            Paragraph(str(idx), styles['cell_center']),
            Paragraph(_safe_str(it.get('pt_code')), styles['cell']),
            Paragraph(_safe_str(it.get('product_name')), styles['cell']),
            Paragraph(_safe_str(it.get('brand_name')), styles['cell']),
            Paragraph(_fmt_qty(buy_qty), styles['cell_right']),
            Paragraph(uom_display, styles['cell_center']),
            Paragraph(_fmt_number(buy_cost), styles['cell_right']),
            Paragraph(_fmt_number(amount), styles['cell_right']),
            Paragraph(f"{vat_pct:.0f}%" if vat_pct else '—', styles['cell_center']),
        ]
        table_data.append(row)

    grand_total = subtotal + vat_total

    # Build table
    items_table = Table(table_data, colWidths=col_widths, repeatRows=1)

    # Table styling
    table_style_cmds = [
        # Header row
        ('BACKGROUND',    (0, 0), (-1, 0), _COLOR_PRIMARY),
        ('TEXTCOLOR',     (0, 0), (-1, 0), colors.white),
        ('FONTSIZE',      (0, 0), (-1, 0), 8),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING',   (0, 0), (-1, -1), 3),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
        # Grid
        ('GRID',          (0, 0), (-1, 0), 0.5, _COLOR_PRIMARY),
        ('LINEBELOW',     (0, -1), (-1, -1), 0.5, _COLOR_BORDER),
        ('LINEAFTER',     (0, 0), (-2, -1), 0.25, _COLOR_BORDER),
    ]

    # Zebra stripes for data rows
    for i in range(1, len(table_data)):
        if i % 2 == 0:
            table_style_cmds.append(('BACKGROUND', (0, i), (-1, i), _COLOR_ROW_ALT))
        # Thin bottom border per row
        table_style_cmds.append(('LINEBELOW', (0, i), (-1, i), 0.25, _COLOR_BORDER))

    items_table.setStyle(TableStyle(table_style_cmds))
    story.append(items_table)

    if has_dual_uom:
        story.append(Paragraph(
            f"<i>* {labels['dual_uom_note']}</i>",
            styles['footer'],
        ))

    story.append(Spacer(1, 4 * mm))

    # ── Totals ─────────────────────────────────────────────────────
    totals_data = [
        [
            '',
            Paragraph(f"{labels['subtotal']}:", styles['total_label']),
            Paragraph(f"{ccy} {_fmt_number(subtotal)}", styles['total_value']),
        ],
    ]
    if vat_total > 0:
        totals_data.append([
            '',
            Paragraph(f"{labels['vat_total']}:", styles['total_label']),
            Paragraph(f"{ccy} {_fmt_number(vat_total)}", styles['total_value']),
        ])
    totals_data.append([
        '',
        Paragraph(f"{labels['grand_total']}:", styles['total_label']),
        Paragraph(f"<b>{ccy} {_fmt_number(grand_total)}</b>", styles['grand_total']),
    ])

    totals_table = Table(
        totals_data,
        colWidths=[page_width * 0.5, page_width * 0.25, page_width * 0.25],
    )
    totals_table.setStyle(TableStyle([
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LINEABOVE',     (1, -1), (-1, -1), 1, _COLOR_PRIMARY),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 5 * mm))

    # ── Important Notes ────────────────────────────────────────────
    notes_text = _safe_str(header.get('important_notes_text'))
    po_note_text = _safe_str(header.get('po_note'))
    combined_notes = []
    if notes_text != '—':
        combined_notes.append(notes_text)
    if po_note_text != '—' and po_note_text != notes_text:
        combined_notes.append(po_note_text)

    if combined_notes:
        story.append(Paragraph(f"■ {labels['notes']}", styles['section_header']))
        for note in combined_notes:
            story.append(Paragraph(note, styles['notes']))
        story.append(Spacer(1, 4 * mm))

    # ── Signature Block ────────────────────────────────────────────
    story.append(HRFlowable(
        width="100%", thickness=0.5, color=_COLOR_BORDER,
        spaceAfter=4 * mm, spaceBefore=4 * mm,
    ))

    sig_data = [[
        [
            Paragraph(labels['buyer_sign'], styles['sign_label']),
            Spacer(1, 20 * mm),
            Paragraph('_' * 30, styles['sign_line']),
            Paragraph(
                _safe_str(header.get('buyer_contact_name'), labels['signature']),
                styles['sign_line'],
            ),
        ],
        [
            Paragraph(labels['seller_sign'], styles['sign_label']),
            Spacer(1, 20 * mm),
            Paragraph('_' * 30, styles['sign_line']),
            Paragraph(
                _safe_str(header.get('seller_contact_name'), labels['signature']),
                styles['sign_line'],
            ),
        ],
    ]]

    sig_table = Table(sig_data, colWidths=[page_width / 2, page_width / 2])
    sig_table.setStyle(TableStyle([
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
    ]))
    story.append(sig_table)

    # ── Footer ─────────────────────────────────────────────────────
    story.append(Spacer(1, 6 * mm))
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    story.append(Paragraph(
        f"{labels['generated']}: {now_str} &nbsp;|&nbsp; "
        f"Rozitek Intralogistic Solution — ERP System",
        styles['footer'],
    ))

    # ── Build ──────────────────────────────────────────────────────
    doc.build(story)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════

def generate_po_pdf(
    po_id: int,
    language: str = 'en',
) -> Dict:
    """
    Generate a PO PDF on-the-fly from DB data.

    No S3 storage — all data lives in DB, so PDF can be regenerated anytime.
    Caller uses pdf_bytes for st.download_button() or email attachment.

    Args:
        po_id:     Purchase Order ID
        language:  'en' | 'vi' | 'bilingual'

    Returns:
        {
            'success':   bool,
            'pdf_bytes': bytes | None,
            'po_number': str,
            'filename':  str,            # suggested filename
            'message':   str,
        }
    """
    if language not in ('en', 'vi', 'bilingual'):
        language = 'en'

    data = _get_po_full_data(po_id)
    if not data:
        return {
            'success': False, 'pdf_bytes': None,
            'po_number': '', 'filename': '',
            'message': f'PO {po_id} not found or query failed',
        }

    po_number = data['header'].get('po_number', f'PO-{po_id}')
    safe_name = po_number.replace('/', '_').replace(' ', '_')

    try:
        pdf_bytes = _build_po_pdf(data, language)
    except Exception as e:
        logger.error(f"generate_po_pdf: build failed for PO {po_id}: {e}")
        return {
            'success': False, 'pdf_bytes': None,
            'po_number': po_number, 'filename': f'{safe_name}.pdf',
            'message': f'PDF generation failed: {e}',
        }

    logger.info(f"PO PDF generated: {po_number} ({len(pdf_bytes):,} bytes, lang={language})")
    return {
        'success': True,
        'pdf_bytes': pdf_bytes,
        'po_number': po_number,
        'filename': f'{safe_name}.pdf',
        'message': f'PDF generated for {po_number}',
    }