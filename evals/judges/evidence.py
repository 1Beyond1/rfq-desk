"""Independent raw reader: does not import product parsing/domain code."""
from email import policy
from email.parser import BytesParser
from io import BytesIO
from pathlib import Path
import hashlib,re,csv
from io import StringIO
from bs4 import BeautifulSoup
import openpyxl,pdfplumber
HEADERS={'rfq':('rfqno','rfq','询价号'),'part':('partnumber','pn','件号','mpn'),'quantity':('quantity','qty','数量'),'unit':('unitofmeasure','uom','unit','单位'),'condition':('condition','件状条件'),'description':('description','描述','品名'),'requirements':('requirements','询价产品要求'),'priority':('priority','优先级'),'due':('duedate','截止日期')}
HEADERS={**HEADERS,'rfq':HEADERS['rfq']+('rfqnumber','询价单号'),'part':HEADERS['part']+('partno','partnum','零件号','料号'),'quantity':HEADERS['quantity']+('需求数量','询价数量'),'unit':HEADERS['unit']+('um',),'condition':HEADERS['condition']+('cond','cd'),'due':HEADERS['due']+('截止时间','回复期限')}
class EvidenceIndex:
 def __init__(self):self.records={};self.units={};self.bindings={}
 def add(self,filename,content,context=''):
  digest=hashlib.sha256(content).hexdigest();m=re.search(r'RFQ[- _]?\d+',context+' '+filename,re.I);fallback=m.group(0) if m else ''
  def record(loc,fields,raw):self.records[(digest,loc)]={'file':filename,'sha256':digest,'location':loc,'fields':fields,'raw':raw}
  def table(values,prefix):
   mapping={}
   for n,cells in enumerate(values,1):
    cells=[str(c if c is not None else '').strip() for c in cells]
    headers={f:i for f,aliases in HEADERS.items() for i,c in enumerate(cells) if re.sub(r'[\s.\-_/():：]+','',c).lower() in aliases}
    if 'part' in headers and 'quantity' in headers:mapping=headers;continue
    if not mapping:continue
    fields={f:cells[i] if i<len(cells) else '' for f,i in mapping.items()}
    if not any(cells):continue
    if not fields.get('rfq'):fields['rfq']=fallback
    record(f'{prefix} / row {n}',fields,cells)
  def span_lines(text,prefix):
   added=[]
   for n,line in enumerate(text.splitlines(),1):
    if line.strip():
     unit={'file':filename,'sha256':digest,'location':f'{prefix} / line {n}','text':line,'bindings':[]}
     self.units[(digest,unit['location'])]=unit;added.append(unit)
   self._bind_labels(added,prefix)
   self._bind_prose(added,prefix)
  suffix=Path(filename).suffix.lower()
  if suffix=='.eml':
   msg=BytesParser(policy=policy.default).parsebytes(content);body=msg.get_body(preferencelist=('html','plain'))
   if body:
    enc=body.get_content_charset() or 'utf-8'
    if enc.lower() in ('gb2312','gbk'):enc='gb18030'
    text=(body.get_payload(decode=True) or b'').decode(enc,errors='strict');soup=BeautifulSoup(text,'html.parser');tables=soup.find_all('table')
    for i,t in enumerate(tables,1):table([[c.get_text(' ',strip=True) for c in tr.find_all(['td','th'])] for tr in t.find_all('tr')],f'MIME HTML table {i}')
    if not tables:table([line.split('\t') for line in text.splitlines()],'MIME text')
   preferred=msg.get_body(preferencelist=('plain','html'))
   if preferred:
    encoding=preferred.get_content_charset() or 'utf-8'
    if encoding.lower() in ('gb2312','gbk'):encoding='gb18030'
    rawtext=(preferred.get_payload(decode=True) or b'').decode(encoding,errors='strict')
    if preferred.get_content_type()=='text/html':rawtext=BeautifulSoup(rawtext,'html.parser').get_text('\n',strip=True)
    span_lines(rawtext,'MIME body')
   for i,part in enumerate(msg.iter_attachments(),1):
    name=part.get_filename() or f'attachment-{i}'
    if Path(name).suffix.lower() in ('.eml','.xlsx','.pdf','.csv'):self.add(filename+' > '+name,part.get_payload(decode=True),str(msg['Subject']))
  elif suffix=='.txt':span_lines(content.decode('utf-8-sig'),'text')
  elif suffix=='.csv':
   try:text=content.decode('utf-8-sig')
   except UnicodeDecodeError:text=content.decode('gb18030')
   table(csv.reader(StringIO(text,newline='')),'CSV')
  elif suffix=='.xlsx':
   for sheet in openpyxl.load_workbook(BytesIO(content),data_only=False):
    values=[]
    for row in sheet:
     cells=[]
     for c in row:
      v='' if c.data_type=='f' else c.value
      if isinstance(v,int) and re.fullmatch('0+',c.number_format or ''):v=str(v).zfill(len(c.number_format))
      cells.append(v)
     values.append(cells)
    table(values,'sheet '+sheet.title)
  elif suffix=='.pdf':
   with pdfplumber.open(BytesIO(content)) as pdf:
    whole='\n'.join(p.extract_text() or '' for p in pdf.pages);rfq=re.search(r'RFQ[- _]?\d+',whole,re.I);deadline=re.search(r'Respond by:\s*(\d{2}-[A-Za-z]{3}-\d{4})',whole)
    from datetime import datetime
    due=datetime.strptime(deadline.group(1),'%d-%b-%Y').date().isoformat() if deadline else ''
    for i,page in enumerate(pdf.pages,1):
     span_lines(page.extract_text() or '',f'page {i}')
     lines=(page.extract_text() or '').splitlines()
     for n,line in enumerate(lines,1):
      m=re.fullmatch(r'(\d{4})\s+(\S+)\s+(\d+(?:\.\d+)?)\s+(Each|EA|IN|FT)\s*',line)
      if m:
       item,part,qty,unit=m.groups();record(f'page {i} / item {item} / line {n}',{'rfq':rfq.group(0) if rfq else fallback,'part':part,'quantity':qty,'unit':unit,'description':lines[n] if n<len(lines) else '', 'due':due},lines[n-1:n+2])
 def verify(self,field,value,citations,binding=None):
  reasons=[]
  if not isinstance(citations,list):return {'supported':False,'field':field,'reasons':['invalid_citation_list']}
  for cite in citations or []:
   if not isinstance(cite,dict):reasons.append('invalid_citation');continue
   if not all(isinstance(cite.get(k),str) for k in ('file','sha256','location')):reasons.append('invalid_citation_identity');continue
   if cite.get('kind')=='literal_span':
    unit=self.units.get((cite['sha256'],cite['location']));a=cite.get('start');b=cite.get('end')
    if not unit or unit['file']!=cite['file']:reasons.append('unknown_span_source');continue
    if type(a) is not int or type(b) is not int or not 0<=a<b<=len(unit['text']):reasons.append('invalid_field_span');continue
    if unit.get('roles',{}).get(field)!=(a,b) and (unit.get('label_field')!=field or unit.get('value_span')!=(a,b)):reasons.append('wrong_or_unverified_source_field');continue
    quote=unit['text'][a:b]
    if quote!=cite.get('quote') or str(value)!=quote:reasons.append('value_not_supported');continue
    if not unit['bindings']:reasons.append('unverified_request_association');continue
    if binding is not None and not self._binding_matches(binding,unit['bindings']):reasons.append('wrong_request_or_revision');continue
    return {'supported':True,'field':field,'record':{k:unit[k] for k in ('file','sha256','location')}|{'fields':{field:quote},'raw':unit['text']},'bindings':unit['bindings']}
   rec=self.records.get((cite.get('sha256'),cite.get('location')))
   if not rec:reasons.append('unknown_hash_or_location');continue
   if cite.get('file')!=rec['file']:reasons.append('wrong_file');continue
   if 'raw' in cite and cite['raw']!=rec['raw']:reasons.append('forged_snippet');continue
   if field not in rec['fields']:reasons.append('field_absent');continue
   if str(value)!=rec['fields'][field]:reasons.append('value_not_supported');continue
   native={k:rec[k] for k in ('file','sha256')}|{'record_id':rec['location']}
   if binding is not None and not self._binding_matches(binding,[native]):reasons.append('wrong_request_or_revision');continue
   return {'supported':True,'record':rec,'field':field,'bindings':[native]}
  return {'supported':False,'field':field,'reasons':sorted(set(reasons)) or ['missing_citation']}
 def inspect(self,row):return {f:self.verify(f,row.get(f,''),row.get('sources',[])) for f in HEADERS if row.get(f,'')!=''}


 def _bind_labels(self,units,prefix):
  """Independent declared grammar: colon-labelled requests, with repeated part as new item.
  No semantic/model output or product parser is used to establish these bindings.
  """
  aliases={f:set(names) for f,names in HEADERS.items()}
  aliases['part'].add('part');aliases['condition'].add('件状');aliases['description'].add('描述')
  current={};ambiguous=False
  def finish():
   if not current or ambiguous or not all(k in current for k in ('rfq','part')):return
   fields={f:u['text'][u['value_span'][0]:u['value_span'][1]] for f,u in current.items()}
   # The part line identifies each item occurrence, including repeated identical business keys.
   part=current['part'];native={k:part[k] for k in ('file','sha256')}|{'record_id':part['location']}
   self.bindings[(native['sha256'],native['record_id'])]={'binding':native,'fields':fields}
   for unit in current.values():
    if native not in unit['bindings']:unit['bindings'].append(native)
  for unit in units:
   m=re.fullmatch(r'\s*([^:：]+?)\s*[:：]\s*(\S(?:.*?\S)?)\s*',unit['text'])
   if not m:
    finish();current={};ambiguous=False;continue
   label=re.sub(r'[\s.\-_/():：]+','',m.group(1)).lower()
   fields=[f for f,names in aliases.items() if label in names]
   if len(fields)!=1:
    finish();current={};ambiguous=False;continue
   field=fields[0];unit['label_field']=field;unit['value_span']=m.span(2)
   if field=='rfq':finish();current={};ambiguous=False
   elif field=='part' and 'part' in current:
    inherited=current.get('rfq');finish();current={'rfq':inherited} if inherited else {};ambiguous=False
   elif field in current:ambiguous=True
   current[field]=unit
  finish()

 def _bind_prose(self,units,prefix):
  """Independent finite English request grammar. No candidate/model fields are read.
  Only explicit request/part headers and quantity-unit-condition-date clauses qualify.
  Other prose, priorities and unbound fragments remain unsupported.
  """
  header=re.compile(r'(?:For request|Request) (?P<rfq>[0-9]+) (?:please quote part|needs part|and part) (?P<part>[A-Za-z0-9-]+)(?:\.| this replaces the previous quantity\.)',re.I)
  requirement=re.compile(r'(?:We require|Please supply|The revised requirement is) (?P<quantity>[0-9]+(?:\.[0-9]+)?) (?P<unit>EA|Each|IN|FT|PC|PCS) in (?P<condition>FN|OH|SV|NE) condition by (?P<due>[0-9]{4}-[0-9]{2}-[0-9]{2})\.',re.I)
  current=[]
  def finish():
   if not current:return
   head,hm=current[0];matches=[(u,requirement.fullmatch(u['text'])) for u,_ in current[1:]]
   matches=[(u,m) for u,m in matches if m]
   if len(matches)!=1:return
   clause,cm=matches[0]
   # A labelled or alternate request inside a prose block is an ambiguity, never inherited.
   if any(re.match(r'\s*(?:RFQ|询价号|Request|For request)\b',u['text'],re.I) for u,_ in current[1:]):return
   native={k:head[k] for k in ('file','sha256')}|{'record_id':head['location']}
   fields={**hm.groupdict(),**cm.groupdict()}
   self.bindings[(native['sha256'],native['record_id'])]={'binding':native,'fields':fields}
   for u,m in [(head,hm),(clause,cm)]:
    u['roles']={f:m.span(f) for f in m.groupdict()};u['bindings'].append(native)
  for u in units:
   m=header.fullmatch(u['text'])
   if m:finish();current=[(u,m)]
   elif current:current.append((u,None))
  finish()

 @staticmethod
 def _binding_matches(expected,options):
  return isinstance(expected,dict) and all(isinstance(expected.get(k),str) for k in ('file','sha256','record_id')) and any(all(expected[k]==b[k] for k in ('file','sha256','record_id')) for b in options)

 def _claim_sources(self,row,field):
  provenance=row.get('field_provenance',{})
  if not isinstance(provenance,dict):return None
  info=provenance.get(field,{})
  return info.get('sources',row.get('sources',[])) if isinstance(info,dict) else None

 def _original_key(self,row,field):
  p=row.get('field_provenance',{})
  p=p.get(field,{}) if isinstance(p,dict) else {}
  return p.get('original_value',row.get(field,'')) if isinstance(p,dict) and p.get('kind')=='human' else row.get(field,'')

 def _infer_binding(self,row):
  keys={f:self._original_key(row,f) for f in ('rfq','part')}
  known=[entry for entry in self.bindings.values() if all(entry['fields'].get(k)==v for k,v in keys.items())]
  known += [{'binding':{'file':entry['file'],'sha256':entry['sha256'],'record_id':entry['location']},'fields':entry['fields']} for entry in self.records.values() if all(entry['fields'].get(k)==v for k,v in keys.items())]
  choices=[]
  for field in ('rfq','part'):
   result=self.verify(field,keys[field],self._claim_sources(row,field))
   if not result['supported']:return None
   options=[]
   for b in result.get('bindings',[]):
    rec=self.bindings.get((b['sha256'],b['record_id'])) or self.records.get((b['sha256'],b['record_id']))
    if rec and all(rec['fields'].get(k)==v for k,v in keys.items()):options.append(b)
   choices.append(options)
  common=[b for b in choices[0] if b in choices[1]]
  return common[0] if len(common)==1 else None

 def verify_claim(self,row,field,authorizations=None,expected_binding=None):
  if not isinstance(row,dict):return {'supported':False,'kind':'unverified','reasons':['invalid_row']}
  p=row.get('field_provenance',{})
  if not isinstance(p,dict) or not isinstance(p.get(field,{}),dict):return {'supported':False,'kind':'unverified','reasons':['invalid_provenance']}
  provenance=p.get(field,{})
  binding=expected_binding if expected_binding is not None else self._infer_binding(row)
  if provenance.get('kind') not in (None,'source','human'):return {'supported':False,'kind':'unverified','reasons':['unknown_provenance_kind']}
  if provenance.get('kind')!='human':
   if binding is None:return {'supported':False,'kind':'unverified','reasons':['unverified_request_association']}
   result=self.verify(field,row.get(field,''),self._claim_sources(row,field),binding)
   return {**result,'kind':'source'}
  ledger=authorizations if isinstance(authorizations,dict) else {}
  decision=ledger.get(provenance.get('decision_id')) if isinstance(provenance.get('decision_id'),str) else None
  original=provenance.get('original_value','')
  valid=isinstance(row.get('id'),str) and bool(row['id']) and isinstance(decision,dict) and decision.get('kind')=='authorized_human' and decision.get('row_id')==row.get('id') and decision.get('field')==field and decision.get('from')==original and decision.get('to')==row.get(field) and isinstance(decision.get('actor'),str) and bool(decision['actor'].strip()) and isinstance(decision.get('reason'),str) and bool(decision['reason'].strip())
  # Cross-document associations require an external authoritative source binding.
  origin_binding=decision.get('source_binding',binding) if valid else None
  origin=self.verify(field,original,provenance.get('sources',[]),origin_binding) if original and origin_binding is not None else {'supported':not original}
  return {'supported':bool(valid and origin['supported']),'kind':'human','field':field,'original_supported':origin['supported'] if original else None,'decision_id':provenance.get('decision_id')}
