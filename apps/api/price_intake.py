"""Strict, reviewed CSV/XLSX price intake. Synthetic or explicitly authorized only."""
import csv,io,json,hashlib,uuid
from pathlib import Path
from openpyxl import load_workbook
from .domain import price_validate,fingerprint
from .parsing import XLSX_MAX_COLS, validate_xlsx
COLUMNS=('part','unit','condition','currency','amount','valid_from','valid_until','lead_time','source','kind')

def parse_prices(name,data):
 suffix=Path(name).suffix.lower();errors=[];rows=[]
 if suffix=='.csv':
  if b'\x00' in data:raise ValueError('CSV文件包含非法二进制字节')
  reader=csv.reader(io.StringIO(data.decode('utf-8-sig')))
  table=[]
  for idx,row in enumerate(reader):
   table.append(row)
   if idx+1>=1002:break
  sheet='CSV'
 elif suffix=='.xlsx':
  validate_xlsx(data)
  try:book=load_workbook(io.BytesIO(data),data_only=False,read_only=True)
  except Exception:raise ValueError('XLSX文件无法读取，请使用规范文本单元格模板')
  try:
   if len(book.sheetnames)!=1:raise ValueError('模板只允许一个工作表')
   ws=book.active;ws.reset_dimensions();sheet=ws.title
   table=[]
   for idx,row in enumerate(ws.iter_rows(values_only=True)):
    if len(row)>XLSX_MAX_COLS:raise ValueError('XLSX列数超限')
    table.append(row)
    if idx+1>=1002:break
  finally:
   book.close()
 else:raise ValueError('仅支持规范CSV或XLSX模板')
 if not table or tuple(table[0])!=COLUMNS:raise ValueError('列名和顺序须与规范模板完全一致')
 if len(table)>1001:raise ValueError('价目最多1000行')
 seen={}
 for line,values in enumerate(table[1:],2):
  if not any(v is not None and v!='' for v in values):continue
  issues=[]
  if len(values)!=len(COLUMNS):issues.append('列数不符')
  if suffix=='.xlsx' and any(not isinstance(v,str) for v in values):issues.append('XLSX全部单元格须为文本；件号前导零不可由数字猜测')
  p=dict(zip(COLUMNS,[str(v).strip() if v is not None else '' for v in values]))
  if any(v.startswith('=') for v in p.values()):issues.append('模板不接受公式')
  try:price_validate(p)
  except (ValueError,TypeError) as e:issues.append(str(e))
  key=tuple(p.get(f) for f in ('part','unit','condition'))
  if key in seen:issues.append('重复/冲突价源，与行'+str(seen[key])+'匹配同一物料条件；请在原文件中裁定')
  seen[key]=line
  rows.append({'line':line,'location':f'{sheet} / row {line}','price':p,'errors':issues})
  errors.extend({'line':line,'message':i} for i in issues)
 if not rows:errors.append({'line':1,'message':'没有价目行'})
 return {'rows':rows,'errors':errors,'sheet':sheet}

def preview(root,case,name,data):
 if len(data)>5*1024*1024:raise ValueError('价目文件上限5MB')
 parsed=parse_prices(name,data);id=uuid.uuid4().hex
 folder=root/'var/price-imports'/case['id']/id;folder.mkdir(parents=True)
 name=Path(name).name;(folder/name).write_bytes(data)
 result={**parsed,'id':id,'filename':name,'sha256':hashlib.sha256(data).hexdigest(),'base_revision':case['revision']}
 (folder/'preview.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8');return result

def accept(root,case,values):
 id=values.get('preview_id','')
 if not isinstance(id,str) or len(id)!=32 or any(c not in '0123456789abcdef' for c in id):raise ValueError('导入预览标识无效')
 folder=root/'var/price-imports'/case['id']/id
 try:record=json.loads((folder/'preview.json').read_text(encoding='utf-8'));data=(folder/record['filename']).read_bytes()
 except (OSError,ValueError):raise ValueError('价源预览不存在或损坏')
 if case['revision']!=record['base_revision']:raise ValueError('预览后工作版本已变化，请重新导入审阅')
 if hashlib.sha256(data).hexdigest()!=record['sha256']:raise ValueError('预览后原价目文件已变化')
 parsed=parse_prices(record['filename'],data)
 if parsed['errors']:raise ValueError('价源存在逐行错误，不能接纳')
 if not all(isinstance(values.get(k),str) and values[k].strip() for k in ('actor','reason')):raise ValueError('填写价源核对人和审阅依据')
 mode=values.get('mode')
 if mode not in ('append','replace'):raise ValueError('明确选择追加或替换全部价目')
 prices=list(case['prices']) if mode=='append' else []
 for row in parsed['rows']:
  p=row['price'];p['evidence']={'import_id':id,'file':record['filename'],'sha256':record['sha256'],'location':row['location'],'line':row['line'],'values_hash':fingerprint(row['price']),'actor':values['actor'],'reason':values['reason']};prices.append(p)
 keys=[tuple(p[k] for k in ('part','unit','condition')) for p in prices]
 if len(keys)!=len(set(keys)):raise ValueError('与现有价目匹配重复/冲突；先裁定原件或明确替换全部价目')
 return prices

def guard(root,case):
 for p in case['prices']:
  e=p.get('evidence')
  if not e:continue
  id=e.get('import_id','');file=e.get('file','')
  if len(id)!=32 or any(c not in '0123456789abcdef' for c in id) or Path(file).name!=file:raise ValueError('价源归档定位无效')
  try:
   data=(root/'var/price-imports'/case['id']/id/file).read_bytes()
   if hashlib.sha256(data).hexdigest()!=e['sha256']:raise ValueError('价源原文件hash已变化')
   row=next(r for r in parse_prices(file,data)['rows'] if r['line']==e['line'])
   if row['errors'] or row['location']!=e['location'] or fingerprint(row['price'])!=e['values_hash'] or any(p[k]!=row['price'][k] for k in COLUMNS):raise ValueError('价目当前值与归档原件不一致')
  except (OSError,KeyError,StopIteration):raise ValueError('价源原文件/定位不可核验')
