"""Local-only extraction. Documents are data, never executable instructions."""
from io import BytesIO, StringIO
from email import policy
from email.parser import BytesParser
from pathlib import Path
import csv
import hashlib
import math
import re
import zipfile
import zlib

from bs4 import BeautifulSoup
import openpyxl
import pdfplumber

XLSX_MAX_ENTRIES = 200
XLSX_MAX_UNCOMPRESSED = 30 * 1024 * 1024
XLSX_MAX_SHEETS = 30
XLSX_MAX_ROWS = 5000
XLSX_MAX_COLS = 100
PDF_MAX_PAGES = 100
EML_MAX_DEPTH = 3
EML_MAX_ATTACHMENTS = 30
EML_MAX_BYTES = 25 * 1024 * 1024

ALIASES = {
    'rfq': ['rfqno', 'rfqnumber', 'rfq', 'inquiryno', 'inquirynumber', 'quoteid', '询价号', '询价单号', '询价编号', '询单号', '询价单'],
    'part': ['partnumber', 'partno', 'partnum', 'part', 'pn', 'sku', 'itemcode', 'itemno', 'productcode', 'model', 'modelno', '件号', '零件号', '零件编号', '部件号', '料号', '物料号', '物料编码', '商品编码', '产品编码', '产品编号', '型号', '规格型号', 'mpn'],
    'description': ['description', 'desc', 'itemname', 'productname', 'spec', 'specification', '描述', '品名', '名称', '零件名称', '商品名称', '产品名称', '物料名称', '规格'],
    'quantity': ['quantity', 'qty', '数量', '需求数量', '询价数量'],
    'unit': ['unitofmeasure', 'uom', 'um', 'unit', '单位', '计量单位'],
    'condition': ['件状条件', '件状', '件况', '件状要求', '品相', '成色', '新旧程度', '物料状态', '产品状态', '交货状态', 'condition', 'cond', 'cd'],
    'due': ['duedate', 'deadline', 'requiredby', 'deliverydate', '截止日期', '截止时间', '回复期限', '期望交期', '要求交期'],
    'requirements': ['询价产品要求', '特殊要求', '技术要求', '规格要求', '产品要求', 'requirements'],
    'priority': ['优先级', 'priority'],
}

def key(v):
    return re.sub(r'[\s.\-_/():：]+', '', str(v or '')).lower()

def decode_text(data):
    if b'\x00' in data:
        raise ValueError('文本文件包含非法二进制字节')
    for enc in ('utf-8-sig', 'gb18030'):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError('文本编码无法识别，请使用 UTF-8 或 GB18030 编码')

def decode(part):
    raw = part.get_payload(decode=True) or b''
    charset = (part.get_content_charset() or 'utf-8').strip()
    # Some official MIME headers say GB2312 but contain GBK characters.
    if charset.lower() in ('gb2312', 'gbk'): charset = 'gb18030'
    for enc in (charset, 'utf-8', 'gb18030'):
        try: return raw.decode(enc)
        except (UnicodeError, LookupError): continue
    return raw.decode('utf-8', errors='replace')

def extract_part_bytes(part):
    raw = part.get_payload(decode=True)
    if raw is not None:
        return raw
    payload = part.get_payload()
    if isinstance(payload, list) and payload:
        return b'\n'.join(p.as_bytes() if hasattr(p, 'as_bytes') else str(p).encode('utf-8') for p in payload)
    if hasattr(payload, 'as_bytes'):
        return payload.as_bytes()
    if isinstance(payload, str):
        return payload.encode('utf-8')
    return part.as_bytes()

def validate_xlsx(data):
    try:
        zf = zipfile.ZipFile(BytesIO(data))
    except (zipfile.BadZipFile, OSError) as e:
        raise ValueError('XLSX文件格式无效') from e
    with zf:
        infos = zf.infolist()
        if len(infos) > XLSX_MAX_ENTRIES:
            raise ValueError(f'XLSX压缩包条目过多（上限{XLSX_MAX_ENTRIES}）')
        total = 0
        for info in infos:
            if info.file_size > XLSX_MAX_UNCOMPRESSED or total + info.file_size > XLSX_MAX_UNCOMPRESSED:
                raise ValueError('XLSX解压体积超限（上限30MB）')
            is_xml = info.filename.lower().endswith(('.xml', '.rels'))
            tail = b''
            try:
                with zf.open(info, 'r') as entry:
                    while True:
                        chunk = entry.read(65536)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > XLSX_MAX_UNCOMPRESSED:
                            raise ValueError('XLSX解压体积超限（上限30MB）')
                        if is_xml:
                            buf = (tail + chunk).upper()
                            flat = buf.replace(b'\x00', b'')
                            if b'<!DOCTYPE' in buf or b'<!ENTITY' in buf or b'<!DOCTYPE' in flat or b'<!ENTITY' in flat:
                                raise ValueError('XLSX包含禁止的XML实体声明')
                            tail = chunk[-32:]
            except (zipfile.BadZipFile, zlib.error, RuntimeError, OSError) as e:
                raise ValueError('XLSX压缩内容损坏或受保护') from e

def format_excel_cell(cell):
    if cell.data_type == 'f':
        return ''
    v = cell.value
    if isinstance(v, float) and math.isfinite(v) and v.is_integer():
        v = int(v)
    fmt = (cell.number_format or '').split(';', 1)[0].strip()
    if isinstance(v, int) and not isinstance(v, bool) and re.fullmatch(r'0+', fmt):
        return str(v).zfill(len(fmt))
    return v

def parse_file(name, data, context='', _depth=0, _state=None):
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError('文件内容无效')
    data = bytes(data)
    if _depth > EML_MAX_DEPTH:
        raise ValueError(f'EML嵌套深度超限（最多{EML_MAX_DEPTH}层）')
    if _state is None:
        _state = {'attachments': 0, 'bytes': len(data)}
    rows, warnings, fragments = [], [], []
    digest = hashlib.sha256(data).hexdigest()
    suffix = Path(name).suffix.lower()
    def table(records, location, fallback=''):
        mapping = None
        for n, values in enumerate(records, 1):
            values = [str(v if v is not None else '').strip() for v in values]
            candidate = {f: i for f, aliases in ALIASES.items() for i, v in enumerate(values) if key(v) in aliases}
            if 'part' in candidate and 'quantity' in candidate:
                mapping = candidate; continue
            if not mapping: continue
            fields = {f: values[i] if i < len(values) else '' for f, i in mapping.items()}
            if not any(values): continue
            if not fields.get('rfq'): fields['rfq'] = fallback
            evidence = { 'file': name, 'sha256': digest, 'location': f'{location} / row {n}', 'raw': values }
            rows.append({'fields': fields, 'source': evidence, 'raw_fields': dict(fields)})
    fallback_match = re.search(r'RFQ[- _]?\d+', context + ' ' + name, re.I)
    fallback = fallback_match.group(0) if fallback_match else ''
    if suffix == '.eml':
        message = BytesParser(policy=policy.default).parsebytes(data)
        body = message.get_body(preferencelist=('html', 'plain'))
        if body:
            body_raw = body.get_payload(decode=True) or b''
            if len(body_raw) > EML_MAX_BYTES:
                raise ValueError('EML正文解码大小超限（上限25MB）')
            content = decode(body)
            soup = BeautifulSoup(content, 'html.parser')
            fragments.append({'location': 'MIME body', 'text': soup.get_text(' ', strip=True)})
            tables = soup.find_all('table')
            for i, t in enumerate(tables, 1):
                table([[c.get_text(' ', strip=True) for c in tr.find_all(['td','th'])] for tr in t.find_all('tr')], f'MIME HTML table {i}', fallback)
            if not tables:
                table([line.split('\t') for line in content.splitlines()], 'MIME text', fallback)
        for i, part in enumerate(message.iter_attachments(), 1):
            _state['attachments'] += 1
            if _state['attachments'] > EML_MAX_ATTACHMENTS:
                raise ValueError(f'EML附件数量超限（上限{EML_MAX_ATTACHMENTS}个）')
            filename = part.get_filename() or f'attachment-{i}'
            att_bytes = extract_part_bytes(part)
            _state['bytes'] += len(att_bytes)
            if _state['bytes'] > EML_MAX_BYTES:
                raise ValueError('EML解码后总大小超限（上限25MB）')
            if Path(filename).suffix.lower() in ('.xlsx', '.pdf', '.eml', '.csv'):
                result = parse_file(name + ' > ' + filename, att_bytes, str(message['Subject'] or ''), _depth + 1, _state)
                rows.extend(result['rows']); warnings.extend(result['warnings']); fragments.extend(result['fragments'])
            else: warnings.append(f'未解析附件：{filename}')
    elif suffix == '.csv':
        text = decode_text(data)
        table(csv.reader(StringIO(text, newline='')), 'CSV', fallback)
    elif suffix == '.xlsx':
        validate_xlsx(data)
        book = openpyxl.load_workbook(BytesIO(data), read_only=True, data_only=True)
        try:
            if len(book.sheetnames) > XLSX_MAX_SHEETS:
                raise ValueError(f'XLSX工作表数量超限（上限{XLSX_MAX_SHEETS}个）')
            for sheet in book.worksheets:
                sheet.reset_dimensions()
                records = []
                for r_idx, row in enumerate(sheet.iter_rows(), 1):
                    if r_idx > XLSX_MAX_ROWS:
                        raise ValueError(f'XLSX单表行数超限（上限{XLSX_MAX_ROWS}行）')
                    if len(row) > XLSX_MAX_COLS:
                        raise ValueError(f'XLSX单表列数超限（上限{XLSX_MAX_COLS}列）')
                    values = []
                    for cell in row:
                        if cell.data_type == 'f':
                            warnings.append(f'{sheet.title}!{cell.coordinate} 公式未执行')
                            values.append('')
                        else:
                            values.append(format_excel_cell(cell))
                    records.append(values)
                table(records, f'sheet {sheet.title}', fallback)
        finally:
            book.close()
    elif suffix == '.pdf':
        with pdfplumber.open(BytesIO(data)) as pdf:
            if len(pdf.pages) > PDF_MAX_PAGES:
                raise ValueError(f'PDF页数超限（上限{PDF_MAX_PAGES}页）')
            page_texts = [p.extract_text() or '' for p in pdf.pages]
            document_text = '\n'.join(page_texts)
            header_rfq = re.search(r'RFQ[- _]?\d+',document_text,re.I)
            pdf_rfq = header_rfq.group(0) if header_rfq else fallback
            deadline = re.search(r'Respond by:\s*(\d{2}-[A-Za-z]{3}-\d{4})',document_text)
            due = ''
            if deadline:
                from datetime import datetime
                try: due = datetime.strptime(deadline.group(1),'%d-%b-%Y').date().isoformat()
                except ValueError: due = ''
            for i, (page, text) in enumerate(zip(pdf.pages, page_texts), 1):
                fragments.append({'location': f'page {i}', 'text': text})
                before = len(rows)
                for t in page.extract_tables(): table(t, f'page {i}', fallback)
                # Textual quote forms: PN/description/qty extraction has an explicit limited grammar.
                if len(rows) == before:
                    lines=text.splitlines()
                    for n, line in enumerate(lines, 1):
                        form = re.match(r'^(\d{4})\s+(\S+)\s+(\d+(?:\.\d+)?)\s+(Each|EA|IN|FT)\s*$',line)
                        if form:
                            item,part,qty,unit=form.groups()
                            f={'rfq':pdf_rfq,'part':part,'quantity':qty,'unit':unit,'description':lines[n] if n<len(lines) else '', 'due':due}
                            # Each is preserved verbatim; no unconfirmed conversion to EA.
                            rows.append({'fields':f,'raw_fields':dict(f),'source':{'file':name,'sha256':digest,'location':f'page {i} / item {item} / line {n}','raw':lines[n-1:n+2]}})
                            continue
                        match = re.match(r'^([A-Z0-9][A-Z0-9./-]*-\d[A-Z0-9./-]*)\s+(.+?)\s+(\d+(?:\.\d+)?)\s+(EA|IN|FT|PC|PCS)\b', line)
                        if match:
                            f = dict(zip(['part','description','quantity','unit'], match.groups())); f['rfq'] = fallback
                            rows.append({'fields':f, 'raw_fields':dict(f), 'source':{'file':name,'sha256':digest,'location':f'page {i} / line {n}','raw':line}})
                if not text: warnings.append(f'page {i} 无可提取文本；需 OCR/人工录入')
    else: raise ValueError('仅支持 EML、CSV、XLSX、文本型 PDF')
    if not rows: warnings.append(f'{name} 未识别询价行，需查看原文并人工核验；未视为成功提取')
    return {'rows':rows, 'warnings':warnings, 'fragments':fragments}
