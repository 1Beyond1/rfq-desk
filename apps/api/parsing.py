"""Local-only extraction. Documents are data, never executable instructions."""
from io import BytesIO
from email import policy
from email.parser import BytesParser
from pathlib import Path
import hashlib
import csv
from io import StringIO
import re

from bs4 import BeautifulSoup
import openpyxl
import pdfplumber

ALIASES = {
    'rfq': ['rfqno', 'rfqnumber', 'rfq', '询价号', '询价单号', '询价编号', '询单号'], 'part': ['partnumber', 'partno', 'partnum', 'part', 'pn', '件号', '零件号', '零件编号', '部件号', '料号', '物料号', 'mpn'],
    'description': ['description', 'desc', '描述', '品名', '名称', '零件名称'], 'quantity': ['quantity', 'qty', '数量', '需求数量', '询价数量'],
    'unit': ['unitofmeasure', 'uom', 'um', 'unit', '单位', '计量单位'], 'condition': ['件状条件', '件状', '件况', '件状要求', 'condition', 'cond', 'cd'],
    'due': ['duedate', '截止日期', '截止时间', '回复期限'], 'requirements': ['询价产品要求', '特殊要求', 'requirements'],
    'priority': ['优先级', 'priority'],
}

def key(v):
    return re.sub(r'[\s.\-_/():：]+', '', str(v or '')).lower()

def decode(part):
    raw = part.get_payload(decode=True) or b''
    charset = part.get_content_charset() or 'utf-8'
    # Some official MIME headers say GB2312 but contain GBK characters.
    if charset.lower() in ('gb2312', 'gbk'): charset = 'gb18030'
    try: return raw.decode(charset)
    except (UnicodeError, LookupError):
        for enc in ('utf-8', 'gb18030'):
            try: return raw.decode(enc)
            except UnicodeError: pass
    return raw.decode('utf-8', errors='replace')

def parse_file(name, data, context=''):
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
            content = decode(body)
            soup = BeautifulSoup(content, 'html.parser')
            fragments.append({'location': 'MIME body', 'text': soup.get_text(' ', strip=True)})
            tables = soup.find_all('table')
            for i, t in enumerate(tables, 1):
                table([[c.get_text(' ', strip=True) for c in tr.find_all(['td','th'])] for tr in t.find_all('tr')], f'MIME HTML table {i}', fallback)
            if not tables:
                table([line.split('\t') for line in content.splitlines()], 'MIME text', fallback)
        for i, part in enumerate(message.iter_attachments(), 1):
            filename = part.get_filename() or f'attachment-{i}'
            if Path(filename).suffix.lower() in ('.xlsx', '.pdf', '.eml', '.csv'):
                result = parse_file(name + ' > ' + filename, part.get_payload(decode=True), str(message['Subject']))
                rows.extend(result['rows']); warnings.extend(result['warnings']); fragments.extend(result['fragments'])
            else: warnings.append(f'未解析附件：{filename}')
    elif suffix == '.csv':
        try: text = data.decode('utf-8-sig')
        except UnicodeDecodeError: text = data.decode('gb18030')
        table(csv.reader(StringIO(text, newline='')), 'CSV', fallback)
    elif suffix == '.xlsx':
        book = openpyxl.load_workbook(BytesIO(data), data_only=False)
        for sheet in book:
            records = []
            for row in sheet:
                values = []
                for cell in row:
                    v = cell.value
                    if cell.data_type == 'f':
                        warnings.append(f'{sheet.title}!{cell.coordinate} 公式未执行'); v = ''
                    if isinstance(v, int) and re.fullmatch(r'0+', cell.number_format or ''):
                        v = str(v).zfill(len(cell.number_format))
                    values.append(v)
                records.append(values)
            table(records, f'sheet {sheet.title}', fallback)
    elif suffix == '.pdf':
        with pdfplumber.open(BytesIO(data)) as pdf:
            document_text = '\n'.join(p.extract_text() or '' for p in pdf.pages)
            header_rfq = re.search(r'RFQ[- _]?\d+',document_text,re.I)
            pdf_rfq = header_rfq.group(0) if header_rfq else fallback
            deadline = re.search(r'Respond by:\s*(\d{2}-[A-Za-z]{3}-\d{4})',document_text)
            due = ''
            if deadline:
                from datetime import datetime
                due = datetime.strptime(deadline.group(1),'%d-%b-%Y').date().isoformat()
            for i, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ''
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
