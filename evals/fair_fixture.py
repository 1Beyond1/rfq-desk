"""Non-model transports for connectivity tests. No gold/authorization ledger is read."""
import json,re
from decimal import Decimal

def candidates(materials):
 fields={}
 names={'rfq':'rfq','part':'part','quantity':'quantity','unit':'unit','condition':'condition'}
 for f in materials['files']:
  for u in f['units']:
   m=re.fullmatch(r'(RFQ|Part|Quantity|Unit|Condition): (.+)',u['text'])
   if m:
    k=names[m.group(1).lower()];a,b=m.span(2);fields[k]={'value':m.group(2),'evidence':{x:u[x] for x in ('file','sha256','location')}|{'start':a,'end':b,'quote':m.group(2)}}
 return {'candidates':[{'fields':fields}]}

class ProductFixture:
 real=False
 def __init__(self):self.contexts=[];self.requests=0
 def reserve_usage(self,messages):return {'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}
 def complete(self,messages,model,timeout):
  context=json.loads(messages[-1]['content']);self.contexts.append({'context':context,'model':model,'timeout':timeout})
  return {'usage':self.reserve_usage(messages),'choices':[{'message':{'role':'assistant','content':json.dumps(candidates(context['original_materials']))}}]}

class BaselineFixture(ProductFixture):
 def complete(self,messages,model,timeout):
  start=max(i for i,m in enumerate(messages) if m['role']=='user');context=json.loads(messages[start]['content'])
  self.contexts.append({'context':context,'model':model,'timeout':timeout})
  values=candidates(context['original_materials'])['candidates'][0]['fields'];flat={f:v['value'] for f,v in values.items()}
  replies=[json.loads(m['content']) for m in messages[start+1:] if m['role']=='tool'];phase=len(replies)
  def response(message):return {'usage':self.reserve_usage(messages),'choices':[{'message':message}]}
  def tool(name,args):return response({'role':'assistant','tool_calls':[{'id':'fixture-'+str(len(messages)),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]})
  if phase==0:return tool('parse',{'index':0})
  if phase==1:return tool('lookup',{'part':flat['part']})
  if phase==2:return tool('code',{'code':"from decimal import Decimal\nprint(Decimal(data['quantity']))",'data':{'quantity':flat['quantity']}})
  if phase==3:return tool('ask',{'key':'review','question':'Confirm this request and event association'})
  if phase==4:return tool('ask',{'key':'approve' if replies[1]['candidates'] else 'price','question':'Current price approval or missing price'})
  lookup=replies[1];answer=replies[4];review=replies[3]
  matches=[p for p in lookup['candidates'] if (p['unit'],p['condition'])==(flat['unit'],flat['condition']) and p['valid_from']<=context['as_of']<=p['valid_until']]
  p=matches[0] if len(matches)==1 else None;allowed=bool(p and review.get('confirm_association') and answer.get('approved_price_version')==lookup['version'])
  sources=[{**v['evidence'],'kind':'literal_span','field':f} for f,v in values.items()]
  row={**flat,'sources':sources,'status':'ready' if allowed else 'unpriced','total':str((Decimal(flat['quantity'])*Decimal(p['amount'])).quantize(Decimal('.01'))) if p else None,'price':p,'price_source':{'sha256':lookup['sha256'],'index':p['index']} if p else None,'approval':{'price_version':lookup['version'],'answer_id':answer.get('id')} if allowed else {}}
  output={'rows':[row],'export_allowed':allowed,'approval_snapshot':lookup['sha256'] if allowed else None,'clarifications':[] if allowed else ['Missing valid price; clarification required']}
  if phase==5:return tool('render',{'document':output})
  return response({'role':'assistant','content':json.dumps(output)})
