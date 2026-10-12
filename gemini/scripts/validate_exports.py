"""Export consistency validator v0.2.0-pilot. Python standard library only."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

VERSION = '0.2.0-pilot'
SENTINEL = '00000000-0000-4000-8000-000000000000'
RULES = [('schema','format'),('timestamp_format','format'),('id_consistency','relational'),
         ('parent_reference','relational'),('parent_cycle','relational'),
         ('parent_time_order','relational'),('current_node_reference','relational'),('duplicate_text','relational')]


def new_rule(name, category, supported=True):
    return dict(rule=name, category=category, supported=supported, checked=0, blocked=0,
                excluded=0, findings=[], notes=[], status=None)


def finding(r, location, reason, **details):
    r['findings'].append(dict(location=location, reason=reason, **details))


def check(r, location, condition, reason, **details):
    r['checked'] += 1
    if not condition:
        finding(r,location,reason,**details)


def finish(r):
    if not r['supported']:
        status='not_supported'
    elif r['findings']:
        status='inconsistency_found'
    elif r['blocked']:
        status='incomplete'
    elif not r['checked']:
        status='no_eligible_data'
    else:
        status='no_inconsistency_found'
    r['status']=status
    return r


def iso(value):
    if not isinstance(value,str) or 'T' not in value:
        raise ValueError('Expected ISO timestamp string')
    d=datetime.fromisoformat(value.replace('Z','+00:00'))
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError('Timezone required')
    return d.astimezone(timezone.utc)


def time_value(service,value):
    if service=='chatgpt':
        if type(value) not in (int,float) or not math.isfinite(value):
            raise ValueError('Expected finite Unix seconds')
        return value
    return iso(value)


def base_rules(service):
    supported={r for r,_ in RULES}
    if service=='gemini':supported={'schema','timestamp_format'}
    elif service=='claude':supported.remove('current_node_reference')
    else:supported.remove('duplicate_text')
    return {r:new_rule(r,c,r in supported) for r,c in RULES}


def text_field(r,obj,key,path):
    check(r,path+'.'+key,isinstance(obj.get(key),str),'missing_or_nonstring_field')


def graph_unit(service,conv,index):
    path=f'$[{index}]'; rules=base_rules(service); schema=rules['schema']
    records=[]; current=None
    if not isinstance(conv,dict):
        check(schema,path,False,'conversation_not_object')
        for r in rules.values():
            if r['supported'] and r is not schema:r['blocked']+=1
        return dict(location=path,label=None,messages=None,rules=[finish(r) for r in rules.values()])
    label=conv.get('title' if service=='chatgpt' else 'name')
    if service=='chatgpt':
        container=conv.get('mapping'); valid=isinstance(container,dict)
        check(schema,path+'.mapping',valid,'mapping_missing_or_not_object')
        if valid:
            for key,node in container.items():
                loc=path+'.mapping['+json.dumps(key)+']'
                if not isinstance(node,dict):
                    check(schema,loc,False,'node_not_object');continue
                msg=node.get('message'); explicit='message' in node
                ok=explicit and (msg is None or isinstance(msg,dict))
                check(schema,loc+'.message',ok,'message_missing_or_invalid')
                text_field(schema,node,'id',loc)
                check(schema,loc+'.parent','parent' in node and (node['parent'] is None or isinstance(node['parent'],str)),'parent_missing_or_invalid')
                if isinstance(msg,dict):
                    text_field(schema,msg,'id',loc+'.message')
                    check(schema,loc+'.message.author',isinstance(msg.get('author'),dict) and isinstance(msg['author'].get('role'),str),'author_role_missing_or_invalid')
                    check(schema,loc+'.message.content',isinstance(msg.get('content'),dict),'content_missing_or_invalid')
                records.append(dict(id=key,node_id=node.get('id'),message_id=msg.get('id') if isinstance(msg,dict) else None,
                                    has_message=isinstance(msg,dict),valid_message=ok,parent=node.get('parent'),parent_present='parent' in node,
                                    time=msg.get('create_time') if isinstance(msg,dict) else None,raw=msg,location=loc))
        current=conv.get('current_node')
    else:
        container=conv.get('chat_messages');valid=isinstance(container,list)
        check(schema,path+'.chat_messages',valid,'chat_messages_missing_or_not_array')
        if valid:
            for j,msg in enumerate(container):
                loc=f'{path}.chat_messages[{j}]'
                if not isinstance(msg,dict):
                    check(schema,loc,False,'message_not_object');continue
                text_field(schema,msg,'uuid',loc);text_field(schema,msg,'sender',loc)
                check(schema,loc+'.parent_message_uuid',isinstance(msg.get('parent_message_uuid'),str),'parent_missing_or_nonstring')
                text_field(schema,msg,'text',loc)
                check(schema,loc+'.content',isinstance(msg.get('content'),list),'content_missing_or_not_array')
                records.append(dict(id=msg.get('uuid'),has_message=True,valid_message=True,parent=msg.get('parent_message_uuid'),
                                    parent_present='parent_message_uuid' in msg,time=msg.get('created_at'),raw=msg,location=loc))
    if not valid:
        for r in rules.values():
            if r['supported'] and r is not schema:r['blocked']+=1
        return dict(location=path,label=label,messages=None,rules=[finish(r) for r in rules.values()])
    # Identifiers are checked within one conversation; versions of UUID are not constrained.
    ids=[x['id'] for x in records]; valid_ids=all(isinstance(x,str) and bool(x) for x in ids)
    counts=Counter(x for x in ids if isinstance(x,str))
    for rec in records:
        rid=rec['id'];ok=isinstance(rid,str) and bool(rid) and counts.get(rid,0)==1
        if service=='claude':ok=ok and rid!=SENTINEL
        else:ok=ok and rec['node_id']==rid and (not rec['has_message'] or rec['message_id']==rid)
        check(rules['id_consistency'],rec['location'],ok,'identifier_missing_duplicate_or_inconsistent')
    graph_ok=(valid_ids and all(n==1 for n in counts.values()) and len(records)==len(container)
              and all(x['valid_message'] for x in records) and (service!='claude' or SENTINEL not in ids))
    times={}
    for j,rec in enumerate(records):
        if not rec['has_message']:
            rules['timestamp_format']['excluded']+=1;continue
        try:
            times[j]=time_value(service,rec['time']);ok=True
        except (ValueError,TypeError,OverflowError):ok=False
        check(rules['timestamp_format'],rec['location'],ok,'invalid_or_missing_message_creation_time',value=rec['time'])
    if graph_ok:
        lookup={r['id']:(j,r) for j,r in enumerate(records)}
        for j,rec in enumerate(records):
            parent=rec['parent']; valid_edge=isinstance(parent,str) and parent in lookup
            valid_root=(parent==SENTINEL if service=='claude' else rec['parent_present'] and parent is None and not rec['has_message'])
            check(rules['parent_reference'],rec['location'],valid_edge or valid_root,'parent_reference_unresolved',parent=parent)
            if valid_root:
                rules['parent_time_order']['excluded']+=1
            elif not valid_edge:
                rules['parent_time_order']['blocked']+=1
            else:
                pi,pr=lookup[parent]
                if not rec['has_message'] or not pr['has_message']:
                    rules['parent_time_order']['excluded']+=1
                elif j not in times or pi not in times:
                    rules['parent_time_order']['blocked']+=1
                else:
                    check(rules['parent_time_order'],rec['location'],times[j]>=times[pi],'child_created_before_parent',parent=parent,child_time=rec['time'],parent_time=pr['time'])
        cycles=set()
        for start in lookup:
            node=start; seq=[];positions={}
            while isinstance(node,str) and node in lookup:
                if node in positions:
                    cycles.add(tuple(sorted(seq[positions[node]:])));break
                positions[node]=len(seq);seq.append(node);node=lookup[node][1]['parent']
        rules['parent_cycle']['checked']=len(records)
        rules['parent_cycle']['notes'].append('Cycles tested only on existing resolved edges; missing references are reported separately.')
        for cycle in sorted(cycles):finding(rules['parent_cycle'],path,'parent_cycle',members=list(cycle))
        if service=='chatgpt':check(rules['current_node_reference'],path+'.current_node',isinstance(current,str) and current in lookup,'current_node_unresolved',value=current)
    else:
        for name in ('parent_reference','parent_cycle','parent_time_order','current_node_reference'):
            if rules[name]['supported']:
                rules[name]['blocked']+=1;rules[name]['notes'].append('Graph evaluation blocked by ambiguous IDs or invalid nodes.')
    if service=='claude':
        r=rules['duplicate_text']
        for rec in records:
            msg=rec['raw'];blocks=msg.get('content')
            if not isinstance(msg.get('text'),str) or not isinstance(blocks,list):r['blocked']+=1;continue
            if not blocks:r['excluded']+=1;continue
            malformed=any(not isinstance(b,dict) or not isinstance(b.get('type'),str) or (b.get('type')=='text' and not isinstance(b.get('text'),str)) for b in blocks)
            if malformed:
                check(schema,rec['location']+'.content',False,'invalid_content_block');r['blocked']+=1;continue
            if any(b['type']!='text' for b in blocks):r['excluded']+=1;continue
            check(r,rec['location'],msg['text']==''.join(b['text'] for b in blocks),'duplicate_text_mismatch')
    return dict(location=path,label=label,messages=sum(r['has_message'] for r in records),rules=[finish(r) for r in rules.values()])


def gemini_unit(item,index):
    path=f'$[{index}]';rules=base_rules('gemini');r=rules['schema']
    if not isinstance(item,dict):
        check(r,path,False,'activity_not_object');rules['timestamp_format']['blocked']+=1
        return dict(location=path,label=None,response_items=None,rules=[finish(x) for x in rules.values()])
    text_field(r,item,'title',path)
    blocks=item.get('safeHtmlItem');check(r,path+'.safeHtmlItem',isinstance(blocks,list),'response_array_missing_or_invalid')
    if isinstance(blocks,list):
        for j,b in enumerate(blocks):check(r,f'{path}.safeHtmlItem[{j}]',isinstance(b,dict) and isinstance(b.get('html'),str),'response_html_missing_or_nonstring')
    if 'details' in item:
        details=item['details'];check(r,path+'.details',isinstance(details,list),'details_not_array')
        if isinstance(details,list):
            for j,d in enumerate(details):check(r,f'{path}.details[{j}]',isinstance(d,dict) and ('url' not in d or isinstance(d['url'],str)),'details_item_invalid')
    try:iso(item.get('time'));ok=True
    except (ValueError,TypeError,OverflowError):ok=False
    check(rules['timestamp_format'],path+'.time',ok,'invalid_or_missing_activity_time',value=item.get('time'))
    return dict(location=path,label=item.get('title'),response_items=len(blocks) if isinstance(blocks,list) else None,rules=[finish(x) for x in rules.values()])


def validate(service,data):
    if not isinstance(data,list):raise ValueError('Top-level JSON must be an array')
    return [gemini_unit(c,i) if service=='gemini' else graph_unit(service,c,i) for i,c in enumerate(data)]


def finite_float(value):
    result=float(value)
    if not math.isfinite(result):raise ValueError("Nonfinite JSON number")
    return result


def reject_constant(value):
    raise ValueError("Nonstandard JSON constant: "+value)


def pairs_hook(pairs):
    d={}
    for k,v in pairs:
        if k in d:raise ValueError(f'Duplicate JSON object key: {k}')
        d[k]=v
    return d


def summarize(service,units):
    totals=[]
    for name,category in RULES:
        rules=[next(r for r in u['rules'] if r['rule']==name) for u in units]
        supported=base_rules(service)[name]['supported']
        total=new_rule(name,category,supported)
        for key in ('checked','blocked','excluded'):total[key]=sum(r[key] for r in rules)
        n=sum(len(r['findings']) for r in rules)
        total['findings']=[None]*n
        finish(total)
        total.pop('findings');total['finding_count']=n
        total['units_with_findings']=sum(bool(r['findings']) for r in rules)
        total['unit_status_counts']=dict(Counter(r['status'] for r in rules))
        totals.append(total)
    return totals


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('service',choices=['chatgpt','claude','gemini'])
    p.add_argument('input',type=Path)
    p.add_argument('--out-dir',type=Path,default=Path(__file__).resolve().parent.parent/'results')
    a=p.parse_args();raw=None;units=[];error=None
    try:
        raw=a.input.read_bytes();data=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=pairs_hook,parse_float=finite_float,parse_constant=reject_constant)
        units=validate(a.service,data)
    except (OSError,UnicodeError,ValueError,TypeError) as e:error=str(e)
    summary=summarize(a.service,units)
    now=datetime.now(timezone.utc)
    report=dict(validator_version=VERSION,service=a.service,stage='development_candidate',
        executed_at_utc=now.isoformat(),input_path=str(a.input.resolve()),
        input_sha256=hashlib.sha256(raw).hexdigest() if raw is not None else None,
        validator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        processing_status='input_error' if error else 'completed',input_error=error,
        unit_type='activity' if a.service=='gemini' else 'conversation',unit_count=len(units),
        scope='Every item in supplied file; no PILOT/EVAL/title filtering. No source authenticity inference.',
        summary=summary,units=units)
    a.out_dir.mkdir(parents=True,exist_ok=True)
    dest=a.out_dir/(a.service+'_v02_'+now.strftime('%Y%m%dT%H%M%S%fZ')+'.json')
    with dest.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False)
    print(f'Version: {VERSION}\nService: {a.service}\nInput: {a.input.resolve()}\nUnits: {len(units)} ({report["unit_type"]})')
    if error:print('INPUT ERROR:',error)
    else:
        if a.service!='gemini':
            for u in units:print(f'  {u["label"]}: messages={u["messages"]}')
        else:print('Response HTML items:',sum(u.get('response_items') or 0 for u in units))
        for r in summary:print(f'{r["rule"]}: {r["status"]} | checked={r["checked"]} blocked={r["blocked"]} excluded={r["excluded"]} findings={r["finding_count"]}')
    print(f'Report: {dest.resolve()}\nInput not modified. This is not an authenticity determination.')
    if error:raise SystemExit(1)


if __name__=='__main__':main()
