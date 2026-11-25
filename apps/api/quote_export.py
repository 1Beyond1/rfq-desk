"""Formatted Excel (.xlsx) quotation export and deterministic bilingual quote reply emails."""
from decimal import Decimal
import io
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

_ILLEGAL_XML_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')
_MAX_EXCEL_CELL = 32767


def _safe_cell(v):
    s = '' if v is None else str(v)
    s = _ILLEGAL_XML_RE.sub('', s)
    if s.startswith(('\t', '\r', '\n')) or s.lstrip().startswith(('=', '+', '-', '@')):
        s = "'" + s
    return s[:_MAX_EXCEL_CELL]


def _clean_inline(v):
    s = '' if v is None else str(v)
    s = _ILLEGAL_XML_RE.sub('', s)
    return re.sub(r'[\r\n]+', ' ', s).strip()


def _is_synthetic(data):
    if data.get('synthetic'):
        return True
    if data.get('label') == '合成演示报价':
        return True
    return any((r.get('price') or {}).get('kind') == 'synthetic' for r in data.get('rows', []))


def _currency_totals(rows):
    totals = {}
    for r in rows:
        cur = r['price']['currency']
        totals[cur] = totals.get(cur, Decimal(0)) + Decimal(str(r['total']))
    return sorted(totals.items())


def _display_width(value):
    s = '' if value is None else str(value)
    width = 0
    for ch in s:
        width += 2 if ord(ch) > 127 else 1
    return width


def _autofit_columns(ws, min_width=10, max_width=44, start_row=1):
    widths = {}
    for row in ws.iter_rows(min_row=start_row):
        for cell in row:
            if cell.value is None:
                continue
            col_idx = cell.column
            w = _display_width(cell.value) + 3
            if w > widths.get(col_idx, min_width):
                widths[col_idx] = min(w, max_width)
    for col_idx, w in widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = max(min_width, w)


_KIND_LABELS = {
    'synthetic': '合成演示 (synthetic)',
    'manual': '人工录入 (manual)',
    'authorized': '授权价表 (authorized)',
}


def render_quote_xlsx(data):
    """Render an approved export_data() payload into a formatted two-sheet .xlsx workbook."""
    rows = data.get('rows', [])
    synthetic = _is_synthetic(data)
    actors = ', '.join(sorted({r['approval']['actor'] for r in rows if r.get('approval')}))
    approval_date = rows[0]['approval']['date'] if rows and rows[0].get('approval') else ''
    totals = _currency_totals(rows)

    wb = Workbook()
    ws1 = wb.active
    ws1.title = '正式报价单'

    thin_side = Side(style='thin', color='D0CCE6')
    header_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=Side(style='medium', color='5B4BDB'))
    cell_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    title_fill = PatternFill(start_color='3F34A8', end_color='3F34A8', fill_type='solid')
    meta_label_fill = PatternFill(start_color='F3F1FF', end_color='F3F1FF', fill_type='solid')
    header_fill = PatternFill(start_color='ECE9FF', end_color='ECE9FF', fill_type='solid')
    total_fill = PatternFill(start_color='F8F7FF', end_color='F8F7FF', fill_type='solid')
    warn_fill = PatternFill(start_color='FFF7E6', end_color='FFF7E6', fill_type='solid')

    title_font = Font(name='Microsoft YaHei', size=14, bold=True, color='FFFFFF')
    meta_label_font = Font(name='Microsoft YaHei', size=10, bold=True, color='3F34A8')
    meta_val_font = Font(name='Microsoft YaHei', size=10, color='1F1D3A')
    header_font = Font(name='Microsoft YaHei', size=10, bold=True, color='3F34A8')
    body_font = Font(name='Microsoft YaHei', size=10, color='1F1D3A')
    total_font = Font(name='Microsoft YaHei', size=10, bold=True, color='1F1D3A')
    note_font = Font(name='Microsoft YaHei', size=9, color='5A5775')
    warn_font = Font(name='Microsoft YaHei', size=9, bold=True, color='8A5300')

    # Title row (Row 1)
    title_text = '合成演示报价单 · 询报价响应' if synthetic else '正式报价响应 · 询报价单'
    ws1.merge_cells('A1:K1')
    tcell = ws1['A1']
    tcell.value = _safe_cell(title_text)
    tcell.font = title_font
    tcell.fill = title_fill
    tcell.alignment = Alignment(horizontal='left', vertical='center', indent=1)
    ws1.row_dimensions[1].height = 30

    # Metadata block (Rows 2-3)
    meta_rows = [
        [
            ('工单号', str(data.get('case_id', ''))),
            ('工作版本', f"r{data.get('revision', '')}"),
            ('价表版本', f"v{data.get('price_version', 0)}"),
        ],
        [
            ('批准人', actors),
            ('批准日期', approval_date),
            ('报价类型', '合成演示报价单' if synthetic else '正式报价响应'),
        ],
    ]
    for r_idx, pairs in enumerate(meta_rows, start=2):
        ws1.row_dimensions[r_idx].height = 20
        col = 1
        for label, val in pairs:
            lc = ws1.cell(row=r_idx, column=col, value=_safe_cell(label))
            lc.font = meta_label_font
            lc.fill = meta_label_fill
            lc.border = cell_border
            lc.alignment = Alignment(horizontal='left', vertical='center')

            vc = ws1.cell(row=r_idx, column=col + 1, value=_safe_cell(val))
            vc.font = meta_val_font
            vc.border = cell_border
            vc.alignment = Alignment(horizontal='left', vertical='center')
            if label == '工单号':
                vc.number_format = '@'
            col += 2

    # Row 4 spacer
    ws1.row_dimensions[4].height = 8

    # Table headers (Row 5)
    headers1 = ['询价号', '件号', '描述', '数量', '单位', '件状', '币种', '单价', '小计', '交期', '特殊要求']
    header_row = 5
    ws1.row_dimensions[header_row].height = 24
    for col_idx, h in enumerate(headers1, start=1):
        c = ws1.cell(row=header_row, column=col_idx, value=h)
        c.font = header_font
        c.fill = header_fill
        c.border = header_border
        c.alignment = Alignment(horizontal='right' if h in ('数量', '单价', '小计') else 'left', vertical='center')

    # Data rows (Row 6+)
    cur_row = header_row + 1
    for r in rows:
        p = r['price']
        vals = [
            r.get('rfq', ''),
            r.get('part', ''),
            r.get('description', ''),
            r.get('quantity', ''),
            r.get('unit', ''),
            r.get('condition', ''),
            p.get('currency', ''),
            p.get('amount', ''),
            r.get('total', ''),
            p.get('lead_time', ''),
            r.get('requirements', ''),
        ]
        ws1.row_dimensions[cur_row].height = 20
        for col_idx, raw_val in enumerate(vals, start=1):
            cell = ws1.cell(row=cur_row, column=col_idx, value=_safe_cell(raw_val))
            cell.font = body_font
            cell.border = cell_border
            if col_idx in (1, 2):
                # Strict text format to protect leading zeros in RFQ No. and Part Number
                cell.number_format = '@'
                cell.alignment = Alignment(horizontal='left', vertical='center')
            elif col_idx in (4, 8, 9):
                cell.number_format = '@'
                cell.alignment = Alignment(horizontal='right', vertical='center')
            else:
                cell.alignment = Alignment(horizontal='left', vertical='center')
        cur_row += 1

    # Blank row before currency totals
    cur_row += 1
    ws1.cell(row=cur_row, column=1, value='按币种合计（不同币种分列，绝不折汇）').font = meta_label_font
    cur_row += 1
    for currency, subtotal in totals:
        ws1.row_dimensions[cur_row].height = 20
        label_cell = ws1.cell(row=cur_row, column=7, value=_safe_cell(currency))
        label_cell.font = total_font
        label_cell.fill = total_fill
        label_cell.border = cell_border
        label_cell.alignment = Alignment(horizontal='left', vertical='center')

        desc_cell = ws1.cell(row=cur_row, column=8, value=_safe_cell(f'合计 ({currency})'))
        desc_cell.font = total_font
        desc_cell.fill = total_fill
        desc_cell.border = cell_border
        desc_cell.alignment = Alignment(horizontal='right', vertical='center')

        val_cell = ws1.cell(row=cur_row, column=9, value=_safe_cell(str(subtotal)))
        val_cell.font = total_font
        val_cell.fill = total_fill
        val_cell.border = cell_border
        val_cell.number_format = '@'
        val_cell.alignment = Alignment(horizontal='right', vertical='center')
        cur_row += 1

    # Disclaimer rows
    cur_row += 1
    disclaimers = [
        '条款说明：报价有效期、税费、运费及质保条款未提供，均待双方进一步确认。以上价源有效期仅用于本次核价，不推断为报价有效期承诺。不同币种不折汇。',
        '版本快照声明：本文件为所列批准版本的静态快照，导出后不可自动撤回；后续任何字段、原件或价表变更均须重新批准。',
    ]
    if synthetic:
        disclaimers.insert(0, '合成演示声明：本报价单包含合成演示数据，仅供流程演示与核验，不构成真实商业报价承诺。')
    for idx, line in enumerate(disclaimers):
        ws1.merge_cells(start_row=cur_row, start_column=1, end_row=cur_row, end_column=11)
        dc = ws1.cell(row=cur_row, column=1, value=_safe_cell(line))
        if synthetic and idx == 0:
            dc.font = warn_font
            dc.fill = warn_fill
        else:
            dc.font = note_font
        dc.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
        ws1.row_dimensions[cur_row].height = 22
        cur_row += 1

    _autofit_columns(ws1, min_width=10, max_width=40, start_row=header_row)
    ws1.column_dimensions['A'].width = max(ws1.column_dimensions['A'].width or 14, 14)
    ws1.column_dimensions['B'].width = max(ws1.column_dimensions['B'].width or 16, 16)
    ws1.column_dimensions['C'].width = max(ws1.column_dimensions['C'].width or 22, 22)
    ws1.column_dimensions['K'].width = max(ws1.column_dimensions['K'].width or 22, 22)

    # Sheet 2: 原件与价格溯源
    ws2 = wb.create_sheet('原件与价格溯源')
    headers2 = ['询价号', '件号', '原件文件名与定位', '价格依据', '有效期', '交期', '来源类型']
    ws2.row_dimensions[1].height = 24
    for col_idx, h in enumerate(headers2, start=1):
        c = ws2.cell(row=1, column=col_idx, value=h)
        c.font = header_font
        c.fill = header_fill
        c.border = header_border
        c.alignment = Alignment(horizontal='left', vertical='center')

    for r_idx, r in enumerate(rows, start=2):
        p = r['price']
        sources_text = ' | '.join(
            f"{s.get('file', '')} {s.get('location', '')}".strip()
            for s in r.get('sources', [])
        )
        ev = p.get('evidence')
        price_basis = p.get('source', '') + (f" · {ev['file']} / {ev['location']}" if ev else '')
        validity = f"{p.get('valid_from', '')} ~ {p.get('valid_until', '')}"
        kind_label = _KIND_LABELS.get(p.get('kind', ''), p.get('kind', ''))
        vals = [
            r.get('rfq', ''),
            r.get('part', ''),
            sources_text,
            price_basis,
            validity,
            p.get('lead_time', ''),
            kind_label,
        ]
        ws2.row_dimensions[r_idx].height = 20
        for col_idx, raw_val in enumerate(vals, start=1):
            cell = ws2.cell(row=r_idx, column=col_idx, value=_safe_cell(raw_val))
            cell.font = body_font
            cell.border = cell_border
            if col_idx in (1, 2):
                cell.number_format = '@'
            cell.alignment = Alignment(horizontal='left', vertical='center')

    _autofit_columns(ws2, min_width=12, max_width=48, start_row=1)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def render_quote_email(data, lang='zh'):
    """Deterministically generate a bilingual customer quote reply email from approved export_data()."""
    if lang not in ('zh', 'en'):
        raise ValueError('邮件语言仅支持 zh 或 en')
    rows = data.get('rows', [])
    synthetic = _is_synthetic(data)
    totals = _currency_totals(rows)
    actors = ', '.join(sorted({_clean_inline(r['approval']['actor']) for r in rows if r.get('approval')}))
    approval_date = _clean_inline(rows[0]['approval']['date']) if rows and rows[0].get('approval') else ''
    rfqs = sorted({_clean_inline(r['rfq']) for r in rows if r.get('rfq')})
    rfq_label = ', '.join(rfqs) if rfqs else _clean_inline(data.get('case_id', ''))
    rev = data['revision']
    pv = data.get('price_version', 0)

    if lang == 'zh':
        prefix = '【合成演示】' if synthetic else ''
        subject = _clean_inline(f"{prefix}报价回复 - {rfq_label}（版本 r{rev}）")
        lines = []
        if synthetic:
            lines.append('【合成演示提示】本报价邮件基于合成演示数据生成，仅供流程验证与演示，不构成正式商业报价承诺。')
            lines.append('')
        lines.append('您好，')
        lines.append('')
        lines.append(f"感谢贵方询价。以下为经核验并批准的报价明细（工单 {_clean_inline(data['case_id'])}，工作版本 r{rev}，价表版本 v{pv}，批准日期 {approval_date}）：")
        lines.append('')
        for i, r in enumerate(rows, start=1):
            p = r['price']
            desc_val = _clean_inline(r.get('description', ''))
            desc = f"（{desc_val}）" if desc_val else ''
            lines.append(
                f"{i}. 询价号 {_clean_inline(r['rfq'])} | 件号 {_clean_inline(r['part'])}{desc} | 数量 {_clean_inline(r['quantity'])} {_clean_inline(r['unit'])} | 件状 {_clean_inline(r['condition'])} | "
                f"单价 {_clean_inline(p['currency'])} {_clean_inline(p['amount'])} | 小计 {_clean_inline(p['currency'])} {_clean_inline(r['total'])} | 交期 {_clean_inline(p['lead_time'])}"
            )
        lines.append('')
        lines.append('按币种合计（不同币种分列，不自动折汇）：')
        for cur, sub in totals:
            lines.append(f"- {_clean_inline(cur)} {sub}")
        lines.append('')
        lines.append('商务条款说明：')
        lines.append('- 报价有效期、税费、运费及质保条款：暂未提供，均待双方最终确认。')
        lines.append('- 价表所载有效期仅用于本次核价依据核验，不推断为正式报价有效期承诺。')
        lines.append('')
        lines.append(f'批准人：{actors}')
        lines.append('如需进一步核对明细或确认交付条款，请直接回复本邮件。')
        body = '\n'.join(lines)
    else:
        prefix = '[SYNTHETIC DEMO] ' if synthetic else ''
        subject = _clean_inline(f"{prefix}Quotation Reply - {rfq_label} (Rev r{rev})")
        lines = []
        if synthetic:
            lines.append('[SYNTHETIC DEMO NOTICE] This quotation email uses synthetic demonstration data only and does not constitute a binding commercial offer.')
            lines.append('')
        lines.append('Dear Customer,')
        lines.append('')
        lines.append(
            f"Thank you for your RFQ. Please find our verified and approved quotation below "
            f"(Case {_clean_inline(data['case_id'])}, Revision r{rev}, Price List v{pv}, Approved {approval_date}):"
        )
        lines.append('')
        for i, r in enumerate(rows, start=1):
            p = r['price']
            desc_val = _clean_inline(r.get('description', ''))
            desc = f" ({desc_val})" if desc_val else ''
            lines.append(
                f"{i}. RFQ {_clean_inline(r['rfq'])} | P/N {_clean_inline(r['part'])}{desc} | Qty {_clean_inline(r['quantity'])} {_clean_inline(r['unit'])} | Cond {_clean_inline(r['condition'])} | "
                f"Unit Price {_clean_inline(p['currency'])} {_clean_inline(p['amount'])} | Subtotal {_clean_inline(p['currency'])} {_clean_inline(r['total'])} | Lead Time {_clean_inline(p['lead_time'])}"
            )
        lines.append('')
        lines.append('Totals by Currency (listed separately; no cross-currency conversion):')
        for cur, sub in totals:
            lines.append(f"- {_clean_inline(cur)} {sub}")
        lines.append('')
        lines.append('Commercial Terms Notice:')
        lines.append('- Quote validity period, taxes, freight/shipping, and warranty terms are not provided and remain subject to confirmation.')
        lines.append('- Price-source validity dates are used strictly for internal verification and do not imply a quotation validity commitment.')
        lines.append('')
        lines.append(f'Approved by: {actors}')
        lines.append('Please reply directly if you need any clarification or wish to confirm delivery terms.')
        body = '\n'.join(lines)

    return {
        'subject': subject,
        'body': body,
        'lang': lang,
        'revision': rev,
        'synthetic': synthetic,
    }
