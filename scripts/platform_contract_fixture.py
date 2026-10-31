"""Offline fixture only. Never opens the RFQ DB or constructs a live transport."""
from pathlib import Path
import asyncio
import json
import httpx
from apps.api.domain import new_case
from apps.api.parsing import parse_file
from apps.api.platform_snapshot import prepare_synthetic_snapshot, CatalogSnapshotAdapter, Settings

ROOT=Path(__file__).resolve().parents[1]


def fixture():
    raw=(ROOT/'data/synthetic/platform/base.eml').read_bytes()
    case=new_case('synthetic platform contract',parse_file('base.eml',raw))
    case['id']='synthetic-platform-fixture';case['revision']=2
    for n,row in enumerate(case['rows'],1):row['id']=f'synthetic-row-{n}'
    row=case['rows'][0];row.update(quantity='5',revision=2,resolution='Synthetic reviewed quantity correction, not a supplier response')
    case['human_decisions']=[{'id':'synthetic-decision-1','row_id':row['id'],'field':'quantity','from':'2','to':'5',
                              'actor':'synthetic reviewer','reason':row['resolution'],'kind':'authorized_human'}]
    row['field_provenance']={'quantity':{'kind':'human','original_value':'2','decision_id':'synthetic-decision-1','sources':row['sources']}}
    case['events']=[{'time':'2026-10-25T00:00:00+08:00','action':'synthetic_review'}]
    return case,{'base.eml':raw}


async def run():
    case,sources=fixture();snapshot=prepare_synthetic_snapshot(case,sources);calls=[]
    def transport(request):
        # Artificial responses following public schemas; never evidence of a platform response.
        calls.append({'method':request.method,'path':request.url.path,'mode':'injected_not_run'})
        if request.url.path.endswith('/upload'):
            assert snapshot.content in request.content
            return httpx.Response(200,json={'code':'OK','msg':'OK','data':{'file_id':'synthetic-file-001'}})
        assert json.loads(request.content)=={'volume_id':123,'file_ids':['synthetic-file-001']}
        return httpx.Response(200,json={'code':'OK','msg':'OK','data':None})
    receipt=await CatalogSnapshotAdapter(Settings(True,key='synthetic-not-a-credential',workspace_id='synthetic-workspace',volume_id=123),httpx.MockTransport(transport)).publish(snapshot,expected_sha256=snapshot.sha256)
    out=ROOT/'var/platform-readiness-20261025';out.mkdir(parents=True,exist_ok=True)
    (out/'synthetic-snapshot.json').write_bytes(snapshot.content)
    report={'receipt':receipt,'calls':calls,'real_platform_requests':0,'real_model_requests':0,'native_platform_versioning':'not_run',
            'source':'Artificial contract transport; local revision2 is not a platform revision'}
    (out/'contract-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))


if __name__=='__main__':asyncio.run(run())
