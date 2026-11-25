"""Canonical local material units and literal span validation. No model or pricing logic."""
from email import policy
from email.parser import BytesParser
from pathlib import Path
import csv,hashlib,io,json
import openpyxl
from bs4 import BeautifulSoup
import pdfplumber
from io import BytesIO
from .parsing import (
    EML_MAX_ATTACHMENTS, EML_MAX_BYTES, EML_MAX_DEPTH, PDF_MAX_PAGES,
    XLSX_MAX_COLS, XLSX_MAX_ROWS, XLSX_MAX_SHEETS,
    decode, decode_text, extract_part_bytes, format_excel_cell, validate_xlsx,
)

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def material_file(name,data):
    sha=hashlib.sha256(data).hexdigest();units=[]
    def lines(text,prefix):
        for n,line in enumerate(text.splitlines(),1):
            if line.strip():units.append({'file':name,'sha256':sha,'location':f'{prefix} / line {n}','text':line})
    def rows(records,prefix):
        for n,values in enumerate(records,1):
            cells=[str(v if v is not None else '').strip() for v in values]
            if any(cells):units.append({'file':name,'sha256':sha,'location':f'{prefix} / row {n}','text':'\t'.join(cells)})
    suffix=Path(name).suffix.lower()
    if suffix=='.eml':
        msg=BytesParser(policy=policy.default).parsebytes(data);body=msg.get_body(preferencelist=('plain','html'))
        if body:
            body_raw=body.get_payload(decode=True) or b''
            if len(body_raw)>EML_MAX_BYTES:raise ValueError('EML正文解码大小超限（上限25MB）')
            text=decode(body)
            if body.get_content_type()=='text/html':text=BeautifulSoup(text,'html.parser').get_text('\n',strip=True)
            lines(text,'MIME body')
    elif suffix=='.txt':lines(decode_text(data),'text')
    elif suffix=='.pdf':
        with pdfplumber.open(BytesIO(data)) as pdf:
            if len(pdf.pages)>PDF_MAX_PAGES:raise ValueError(f'PDF页数超限（上限{PDF_MAX_PAGES}页）')
            for i,page in enumerate(pdf.pages,1):lines(page.extract_text() or '',f'page {i}')
    # Table rows keep the parser's location names, so a row cited here is the same row the table parser reports.
    elif suffix=='.csv':
        text=decode_text(data)
        rows(csv.reader(io.StringIO(text,newline='')),'CSV')
    elif suffix=='.xlsx':
        validate_xlsx(data)
        book=openpyxl.load_workbook(BytesIO(data),read_only=True,data_only=True)
        try:
            if len(book.sheetnames)>XLSX_MAX_SHEETS:raise ValueError(f'XLSX工作表数量超限（上限{XLSX_MAX_SHEETS}个）')
            for sheet in book.worksheets:
                sheet.reset_dimensions()
                records=[]
                for r_idx,row in enumerate(sheet.iter_rows(),1):
                    if r_idx>XLSX_MAX_ROWS:raise ValueError(f'XLSX单表行数超限（上限{XLSX_MAX_ROWS}行）')
                    if len(row)>XLSX_MAX_COLS:raise ValueError(f'XLSX单表列数超限（上限{XLSX_MAX_COLS}列）')
                    records.append([table_value(c) for c in row])
                rows(records,f'sheet {sheet.title}')
        finally:
            book.close()
    return {'file':name,'sha256':sha,'units':units,'supported':suffix in ('.eml','.txt','.pdf','.csv','.xlsx')}

def table_value(cell):
    return format_excel_cell(cell)

def material_files(name,data,_depth=0,_state=None):
    """The file and, for a mail, its attachments as files of their own: a model reading the mail must also see its Excel and PDF."""
    if _depth>EML_MAX_DEPTH:raise ValueError(f'EML嵌套深度超限（最多{EML_MAX_DEPTH}层）')
    if _state is None:_state={'attachments':0,'bytes':len(data)}
    out=[material_file(name,data)]
    if Path(name).suffix.lower()=='.eml':
        msg=BytesParser(policy=policy.default).parsebytes(data)
        for i,part in enumerate(msg.iter_attachments(),1):
            _state['attachments']+=1
            if _state['attachments']>EML_MAX_ATTACHMENTS:raise ValueError(f'EML附件数量超限（上限{EML_MAX_ATTACHMENTS}个）')
            filename=part.get_filename() or f'attachment-{i}'
            raw=extract_part_bytes(part)
            _state['bytes']+=len(raw)
            if _state['bytes']>EML_MAX_BYTES:raise ValueError('EML解码后总大小超限（上限25MB）')
            suffix=Path(filename).suffix.lower()
            if suffix=='.eml':
                for item in material_files(name+' > '+filename,raw,_depth+1,_state):
                    out.append({**item,'container_file':name})
            elif suffix in ('.xlsx','.pdf','.csv','.txt'):
                out.append({**material_file(name+' > '+filename,raw),'container_file':name})
    return out

def read_materials(folder, include_source_rows=False):
    files=[]
    for path in sorted(Path(folder).glob('*')):
        if path.is_file():files.extend(material_files(path.name,path.read_bytes()))
    # Attachments are part of their mail, so only the uploaded files define the snapshot.
    snapshot=digest([{k:f[k] for k in ('file','sha256')} for f in files if not f.get('container_file')])
    mappings=[];errors=[]
    if include_source_rows:
        # Navigation only: the semantic extraction input/snapshot remains unchanged.
        # Re-parse original structure, never infer a position from an equal field value.
        from .parsing import parse_file
        by_file={(f['file'],f['sha256']):f for f in files}
        for path in sorted(Path(folder).glob('*')):
            if not path.is_file() or path.suffix.lower() not in ('.eml','.xlsx','.pdf','.csv'):continue
            try:parsed=parse_file(path.name,path.read_bytes())
            except Exception:
                errors.append({'file':path.name,'code':'source_structure_unavailable'})
                continue
            for row in parsed['rows']:
                source=row['source'];key=(source['file'],source['sha256'])
                if key not in by_file:
                    by_file[key]={'file':key[0],'sha256':key[1],'units':[],'supported':True,'container_file':path.name}
                    files.append(by_file[key])
                f=by_file[key];location=source['location']
                unit_id=digest([*key,location])
                unit=next((u for u in f['units'] if u['location']==location),None)
                if unit is None:
                    raw=source.get('raw',[])
                    unit={'file':key[0],'sha256':key[1],'location':location,'text':'\t'.join(str(v) for v in raw),
                          'kind':'source_row','unit_id':unit_id}
                    f['units'].append(unit)
                else:unit['unit_id']=unit_id
                ref={'file':key[0],'sha256':key[1],'location':location,'unit_id':unit_id}
                if ref not in mappings:mappings.append(ref)
        for f in files:
            for u in f['units']:u.setdefault('unit_id',digest([u['file'],u['sha256'],u['location']]))
    return {'files':files,'snapshot':snapshot,**({'source_locations':mappings,'source_mapping_errors':errors} if include_source_rows else {})}

def validate_span(value,citation,materials,field=None):
    if not isinstance(value,str) or not isinstance(citation,dict):raise ValueError('字段值及证据类型无效')
    keys={'file','sha256','location','start','end','quote'}
    if set(citation)-keys-{'kind','field'} or not keys.issubset(citation):raise ValueError('片段引用结构无效')
    if any(not isinstance(citation[k],str) for k in ('file','sha256','location','quote')):raise ValueError('引用标识须为字符串')
    if type(citation['start']) is not int or type(citation['end']) is not int:raise ValueError('片段位置须为整数')
    matches=[u for f in materials['files'] for u in f['units'] if all(citation[k]==u[k] for k in ('file','sha256','location'))]
    if len(matches)!=1:raise ValueError('引用不在允许文件/页/行或文件hash已变化')
    text=matches[0]['text'];a,b=citation['start'],citation['end']
    if not 0<=a<b<=len(text) or text[a:b]!=citation['quote'] or value!=citation['quote']:raise ValueError('原文片段不支持该字段值')
    return {**citation,'kind':'literal_span','field':field}
