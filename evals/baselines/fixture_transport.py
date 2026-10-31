"""Deterministic transport for protocol tests only. No model or gold file is read."""
import json
from decimal import Decimal
class ScriptedTransport:
 real=False
 def complete(self,messages,max_tokens,timeout):
  last_user=max(i for i,m in enumerate(messages) if m['role']=='user')
  state=json.loads(messages[last_user]['content']);state=state.get('state',state.get('next_event'))
  responses=[json.loads(m['content']) for m in messages[last_user+1:] if m['role']=='tool']
  phase=len(responses)
  def tool(name,args):
   return {'usage':{'total_tokens':120},'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[{'id':'fixture-'+str(len(messages)),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}]}
  if phase==0:return tool('parse',{'index':0})
  if phase==1:return tool('lookup',{'part':responses[0]['rows'][0]['fields']['part']})
  if phase==2:return tool('code',{'code':"import json\ndef total(rows):\n    return sum(int(r['quantity']) for r in rows)\nprint(json.dumps({'quantity_sum':total(data['rows'])}))\n",'data':{'rows':[r['fields'] for r in responses[0]['rows']]}})
  if phase==3:return tool('ask',{'key':'approve' if responses[1]['candidates'] else 'price','question':'请批准当前价格版本' if responses[1]['candidates'] else '缺价，请提供有效报价'})
  rows=[]
  for item in responses[0]['rows']:
   f=item['fields'];candidates=responses[1]['candidates'];p=candidates[0] if len(candidates)==1 else None
   approved=p and responses[3].get('approved_price_version')==responses[1]['version']
   rows.append({**f,'sources':[item['source']],'status':'ready' if approved else 'unpriced','total':str(Decimal(f['quantity'])*Decimal(p['amount'])) if p else None,'price':p,'price_source':{'sha256':responses[1]['sha256'],'index':p['index']} if p else None,'approval':{'price_version':responses[1]['version'],'answer_id':responses[3].get('id')} if approved else {}})
  output={'rows':rows,'export_allowed':all(r['status']=='ready' for r in rows),'approval_snapshot':responses[1]['sha256'] if all(r['status']=='ready' for r in rows) else None,'clarifications':[] if responses[1]['candidates'] else ['price unavailable']}
  if phase==4:return tool('render',{'document':output})
  return {'usage':{'total_tokens':120},'choices':[{'message':{'role':'assistant','content':json.dumps(output)}}]}
