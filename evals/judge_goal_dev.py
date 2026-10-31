"""Author-fact DEV judge, run after model tasks. Never exposed as an agent tool."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'data/synthetic/goal-readiness-20261029';OUT=ROOT/'var/goal-readiness-20261029'
EXPECTED={
 'dual':[
  {'rfq':'000771','part':'HC-21','quantity':'3','unit':'EA','condition':'OH','due':'2027-08-09'},
  {'rfq':'000772','part':'HC-21','quantity':'8','unit':'EA','condition':'OH','due':'2027-08-11'}],
 'revision':[
  {'rfq':'000783','part':'NJ-62','quantity':'4','unit':'EA','condition':'FN','due':'2027-09-03'},
  {'rfq':'000783','part':'NJ-62','quantity':'7','unit':'EA','due':'2027-09-10'}]}
def judge(kind,record):
    data=(DATA/(kind+'.txt')).read_bytes();sha=hashlib.sha256(data).hexdigest();lines=data.decode('utf-8-sig').splitlines();rows=record.get('candidates',[]);actual=[];bad=[]
    for index,row in enumerate(rows):
        fields={}
        for field,entry in row.get('fields',{}).items():
            value=entry.get('value');ref=entry.get('evidence',{});fields[field]=value
            try:
                line=int(ref['location'].removeprefix('text / line '));text=lines[line-1];a=ref['start'];b=ref['end']
                ok=ref['file']==kind+'.txt' and ref['sha256']==sha and type(a) is int and type(b) is int and 0<=a<b<=len(text) and text[a:b]==value==ref['quote']
            except (ValueError,KeyError,IndexError,TypeError):ok=False
            if not ok:bad.append({'row':index,'field':field})
        actual.append(fields)
    expected=EXPECTED[kind];matched=[]
    for need in expected:
        found=next((i for i,r in enumerate(actual) if all(r.get(k)==v for k,v in need.items()) and i not in matched),None)
        if found is not None:matched.append(found)
    return {'case':kind,'arm':record['arm'],'status':record['status'],'expected_rows':len(expected),'matched_rows':len(matched),'actual_rows':len(actual),'exact_required_values':len(matched)==len(expected) and len(actual)==len(expected),'bad_literal_citations':bad,'model_calls':record['model_calls'],'tokens':record['tokens'],'seconds':record['seconds'],'human_reviews':0,'business_workflow':'not_run','notes':'Literal matching is not an independent determination of semantic role; revision inheritance remains human review.'}
def main():
    results=[]
    for kind in EXPECTED:
        for rep in (1,2):
            for arm in ('product','baseline'):
                p=OUT/f'{kind}-{rep}-{arm}.json'
                if p.exists():
                    x=json.loads(p.read_text(encoding='utf-8'));results.append(judge(kind,x))
                else:results.append({'case':kind,'rep':rep,'arm':arm,'status':'not_run'})
    (OUT/'DEV_JUDGMENT.json').write_text(json.dumps({'kind':'author_fact_dev_only','not_independent_holdout':True,'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False))
if __name__=='__main__':main()
