"""All sample business identities and prices are synthetic; never supplier quotes."""
from email.message import EmailMessage
from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
root=Path(__file__).resolve().parents[1]/'data/synthetic'
root.mkdir(parents=True,exist_ok=True)
rows=[['000101','SYN-001','WASHER / 垫片','8','EA','FN'],['000102','SYN-001','WASHER / 垫片','8','EA','FN'],['000102','SYN-001','WASHER / 垫片','8','EA','FN'],['000103','SYN-002','SEAL / 密封件','2','EA','FN'],['000103','SYN-002','SEAL / 密封件','3','EA','FN'],['000104','SYN-003','CLAMP / 卡箍','5','EA','FN']]
m=EmailMessage();m['Subject']='Synthetic RFQ training sample';m['From']='buyer@example.invalid';m['To']='desk@example.invalid'
m.set_content('Synthetic example only. Refer to the HTML table.')
m.add_alternative('<h1>合成询价 · 仅供演示</h1><table><tr>'+''.join('<th>'+x+'</th>' for x in ['RFQ No.','Part Number','Description','Quantity','Unit','Condition'])+'</tr>'+''.join('<tr>'+''.join('<td>'+v+'</td>' for v in row)+'</tr>' for row in rows)+'</table>',subtype='html')
(root/'demo.eml').write_bytes(m.as_bytes())
prices=[{'part':p,'unit':'EA','condition':'FN','currency':'USD','amount':a,'valid_from':'2026-01-01','valid_until':'2027-12-31','lead_time':'演示 7 天','source':'SYN-CATALOG-01 / 人工生成合成价表','kind':'synthetic'} for p,a in [('SYN-001','12.35'),('SYN-002','48.20')]]
(root/'prices.json').write_text(json.dumps(prices,ensure_ascii=False,indent=2),encoding='utf-8')
