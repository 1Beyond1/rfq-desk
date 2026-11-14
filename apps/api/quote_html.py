from html import escape
from decimal import Decimal

def render_quote(result):
 e=lambda v:escape(str(v),quote=True)
 totals={};lines=[]
 for r in result['rows']:
  p=r['price'];totals[p['currency']]=totals.get(p['currency'],Decimal(0))+Decimal(r['total'])
  ev=p.get('evidence');source=p['source']+((' · '+ev['file']+' / '+ev['location']) if ev else ' · 人工录入依据')
  vals=[r['rfq'],r['part'],r['quantity']+' '+r['unit'],r['condition'],p['currency']+' '+p['amount'],r['total'],p['lead_time'],source]
  lines.append('<tr>'+''.join('<td>'+e(v)+'</td>' for v in vals)+'</tr>')
 return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>报价响应</title><style>body{font:14px/1.6 system-ui,'Microsoft YaHei',sans-serif;color:#1f1d3a;margin:32px}h1{font-size:24px;margin:0 0 4px;color:#1f1d3a}h2{font-size:15px;margin:22px 0 6px;color:#4b3cc4}table{border-collapse:collapse;width:100%}thead th{background:#f3f1ff;color:#4b3cc4;font-size:12px}td,th{border-bottom:1px solid #e4e2f0;padding:9px 10px;text-align:left;overflow-wrap:anywhere}td:nth-child(-n+7),th:nth-child(-n+7){white-space:nowrap}td:last-child{font-size:12px}header{border-bottom:3px solid #5b4bdb;margin-bottom:14px}header p{margin:0;color:#6b6987}small{color:#6b6987}@page{size:A4 landscape;margin:12mm}@media print{body{margin:0;font-size:10pt}tr{break-inside:avoid}}@media(max-width:650px){body{margin:12px}table{font-size:11px}td,th{padding:4px}}</style><header><h1>'''+e(result['label'])+''' · 报价响应</h1><p>工作单 '''+e(result['case_id'])+' · 输入版本 '+e(result['revision'])+' · 价目版本 '+e(result['price_version'])+'''</p></header><p>批准人：'''+e(', '.join(sorted({r['approval']['actor'] for r in result['rows']})))+' · 批准日期：'+e(result['rows'][0]['approval']['date'])+'''</p><table><thead><tr>'''+''.join('<th>'+x+'</th>' for x in ['询价号','件号','数量 / 单位','件状','单价 / 币种','小计','交期','价格依据'])+'</tr></thead><tbody>'+''.join(lines)+'''</tbody></table><h2>按币种汇总</h2>'''+''.join('<p>'+e(k)+' '+e(v)+'</p>' for k,v in sorted(totals.items()))+'''<p>报价有效期、税费、质保条款：未提供，待确认。以上价源有效期用于本次核价，不推断为报价承诺。不同币种不折汇。</p><small>本文件是所列批准版本的历史快照。下载后不能自动撤回；后续变更须重新核验当前版本。</small></html>'''
