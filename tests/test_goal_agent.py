import pytest
from evals.goal_agent import material,locate
from apps.api.semantic import validate_payload
def test_locate_original_and_refuse_forgery():
    m,raw=material('dual.txt');f=locate({'rfq':{'value':'000771','line':1},'part':{'value':'HC-21','line':1}},m)
    assert validate_payload({'candidates':[{'fields':f}]},m)[0]['fields']['rfq']=='000771'
    with pytest.raises(ValueError):locate({'quantity':{'value':'999','line':1}},m)
    bad=dict(f);bad['rfq']=dict(f['rfq']);bad['rfq']['evidence']=dict(f['rfq']['evidence'],sha256='0'*64)
    with pytest.raises(ValueError):validate_payload({'candidates':[{'fields':bad}]},m)
def test_distinct_chinese_requests_cannot_mix():
    m,_=material('dual.txt');fields=locate({'rfq':{'value':'000771','line':1},'part':{'value':'HC-21','line':2}},m)
    with pytest.raises(ValueError):validate_payload({'candidates':[{'fields':fields}]},m)
def test_quantity_does_not_bind_digit_inside_date():
    m,_=material('tune.txt');x=locate({'quantity':{'value':'2','line':1}},m)['quantity']['evidence']
    assert m['files'][0]['units'][0]['text'][x['start']:].startswith('2 EA')
    with pytest.raises(ValueError):locate({'quantity':{'value':'2','line':1,'occurrence':1}},m)

def test_compact_protocol_preserves_guard():
    from apps.api.semantic import expand_compact_payload
    m,_=material('tune.txt');row={'rfq':{'value':'000761','file':'tune.txt','location':'text / line 1'},'part':{'value':'BW-31','file':'tune.txt','location':'text / line 1'},'quantity':{'value':'2','file':'tune.txt','location':'text / line 1'}}
    p,dropped=expand_compact_payload({'candidates':[{'fields':row}]},m);assert dropped==0 and validate_payload(p,m)[0]['fields']['quantity']=='2'
    row['quantity']['value']='99'
    p,dropped=expand_compact_payload({'candidates':[{'fields':row}]},m);assert dropped==1 and 'quantity' not in p['candidates'][0]['fields']
    row['quantity']={'value':'2','file':'tune.txt','location':'text / line 99'}
    p,dropped=expand_compact_payload({'candidates':[{'fields':row}]},m);assert dropped==0 and validate_payload(p,m)[0]['field_sources']['quantity']['location']=='text / line 1'
