from copy import deepcopy
import asyncio
import pytest
from evals.goal_agent import material,locate
from apps.api import semantic,domain

def test_sparse_revision_retains_original_condition_and_stales_approval():
    m,_=material('revision.txt')
    original={'rfq':{'value':'000783','line':1},'part':{'value':'NJ-62','line':1},'quantity':{'value':'4','line':1},'unit':{'value':'EA','line':1},'condition':{'value':'FN','line':1},'due':{'value':'2027-09-03','line':1}}
    revision={'rfq':{'value':'000783','line':2},'part':{'value':'NJ-62','line':2},'quantity':{'value':'7','line':2},'unit':{'value':'EA','line':2},'due':{'value':'2027-09-10','line':2}}
    payload={'candidates':[{'fields':locate(original,m)},{'fields':locate(revision,m)}]}
    class Adapter:
        async def extract(self,m,b):return semantic.AdapterReply(payload,10,0,'not_run','fixture')
    case=domain.new_case('synthetic',{'rows':[],'warnings':[],'fragments':[]});batch=asyncio.run(semantic.propose(case,m,'model',Adapter(),True));case['revision']+=1
    semantic.accept_candidate(case,batch,batch['candidates'][0],m,{'actor':'DEV','reason':'original selection','confirm_association':True});case['revision']+=1
    case['prices']=[{'part':'NJ-62','unit':'EA','condition':'FN','currency':'USD','amount':'10.00','valid_from':'2026-01-01','valid_until':'2030-12-31','lead_time':'SYN','source':'SYN DEV','kind':'synthetic'}]
    domain.approve(case,'DEV',today='2026-10-29');before=deepcopy(case['rows'][0]);candidate=batch['candidates'][1]
    args={'actor':'DEV','reason':'explicit target and revision','confirm_association':True,'mode':'partial','target_row_id':before['id'],'base_revision':case['revision'],'base_row_revision':before['revision'],'update_fields':['quantity','due'],'clear_fields':[]}
    wrong=deepcopy(args);wrong['target_row_id']='not-this-row'
    with pytest.raises(ValueError):semantic.accept_candidate(case,batch,candidate,m,wrong)
    semantic.accept_candidate(case,batch,candidate,m,args);row=case['rows'][0];state=domain.analyze(case,'2026-10-29')[0]
    assert row['quantity']=='7' and row['due']=='2027-09-10' and row['condition']=='FN'
    assert row['field_provenance']['condition']['sources']==before['field_provenance']['condition']['sources']
    assert row['field_provenance']['condition']['inherited_from']['row_revision']==before['revision']
    for field in ('description','requirements','priority'):
        assert row[field]=='' and row['field_provenance'][field]['sources']==[]
    assert row['field_provenance']['quantity']['sources'][0]['location']=='text / line 2'
    assert state['stale'] and not state['approved'] and state['total']=='70.00'
    with pytest.raises(ValueError):domain.export_data(case,'2026-10-29')
    splice=deepcopy(payload['candidates'][1]);splice['fields']['condition']=payload['candidates'][0]['fields']['condition']
    with pytest.raises(ValueError):semantic.validate_payload({'candidates':[splice]},m)
