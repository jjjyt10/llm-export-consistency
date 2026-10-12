"""ChatGPT EVAL batch v1.0.0. Requires unmodified validate_exports.py v0.2.
Usage: python scripts/run_chatgpt_eval.py input/chatgpt_eval_export.json
"""
import argparse
import copy
import csv
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import sys
import uuid

VERSION='1.0.0'
VALIDATOR_HASH='71a54078a3b79d86027187267c07117fbec3928640bbd31f18079daf18bc744c'
ROOT='00000000-0000-4000-8000-000000000000'
CONDITIONS=('B1','D1','D2','T1','T2','I1','F1')
TEXT='연구용 변경 문장입니다. 회의 장소는 Z회의실이며 시간은 오후 5시입니다.'
TIME_FIELDS=('create_time','update_time')


def hash_bytes(raw):return hashlib.sha256(raw).hexdigest()
def dt(s):return datetime.fromisoformat(s.replace('Z','+00:00')).astimezone(timezone.utc)
def iso(t):return t.isoformat(timespec='microseconds').replace('+00:00','Z')
def dump(path,obj):
    raw=json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8')
    with path.open('xb') as f:f.write(raw)
    return hash_bytes(raw)

def load_validator(path):
    if hash_bytes(path.read_bytes())!=VALIDATOR_HASH:raise ValueError('Validator hash mismatch. Use the fixed v0.2 file; do not bypass this check.')
    spec=importlib.util.spec_from_file_location('fixed_validator',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def text_ok(node):
    m=node.get('message')
    return (isinstance(m,dict) and m.get('content',{}).get('content_type')=='text'
            and isinstance(m['content'].get('parts'),list) and len(m['content']['parts'])==1
            and isinstance(m['content']['parts'][0],str))


def set_text(node,value):
    if not text_ok(node):raise ValueError('Requires single plain-text part')
    node['message']['content']['parts'][0]=value


def role(node):return (node.get('message') or {}).get('author',{}).get('role')
def node_time(node):return node['message']['create_time']


def select(data):
    planned=[]
    for n in range(1,10):
        label='EVAL-CGPT-03-R1' if n==3 else f'EVAL-CGPT-{n:02d}'
        matches=[i for i,c in enumerate(data) if c.get('title')==label]
        if len(matches)!=1:raise ValueError(f'Expected one {label}, found {len(matches)}')
        ci=matches[0];c=data[ci];mapping=c['mapping'];nodes=list(mapping.values())
        if any('children' in x for x in nodes):raise ValueError('Unexpected children field: review export profile before running')
        first=min((x for x in nodes if role(x)=='user'),key=lambda x:(node_time(x),x['id']))
        answers=[x for x in nodes if role(x)=='assistant' and x['parent']==first['id']]
        preferred=[x for x in answers if any(role(y)=='user' and y['parent']==x['id'] for y in nodes)]
        answer=min(preferred or answers,key=lambda x:(node_time(x),x['id']))
        if not preferred:raise ValueError(f'{label}: selected deletion must leave a child reference')
        leaf=mapping[c['current_node']]
        if role(leaf)!='assistant' or any(x['parent']==leaf['id'] for x in nodes):
            raise ValueError(f'{label}: current_node must be an assistant leaf')
        planned.append(dict(label=label,conversation_index=ci,conversation_uuid=c['id'],
            question_uuid=first['id'],answer_uuid=answer['id'],answer_created_at=node_time(answer),
            preferred_followup_answer=True,insertion_leaf_uuid=leaf['id'],
            insertion_leaf_policy='export current_node, required to be an assistant leaf'))
    return planned


def shift_times(obj,seconds):
    if isinstance(obj,dict):
        for k,v in obj.items():
            if k in TIME_FIELDS and v is not None:
                if isinstance(v,bool) or not isinstance(v,(int,float)):raise ValueError('Non-numeric time')
                obj[k]=v+seconds
            elif isinstance(v,(dict,list)):shift_times(v,seconds)
    elif isinstance(obj,list):
        for v in obj:shift_times(v,seconds)


def make_case(data,selection,condition,source_hash):
    out=copy.deepcopy(data);ci=selection['conversation_index'];conv=out[ci];mapping=conv['mapping']
    aid=selection['answer_uuid'];qid=selection['question_uuid'];answer=mapping[aid];question=mapping[qid]
    if not text_ok(answer) or not text_ok(question):raise ValueError('Selected nodes require single text part')
    seed=int(hash_bytes((source_hash+selection['label']+condition).encode()),16)
    rng=random.Random(seed)
    used={c['id'] for c in data}|{k for c in data for k in c['mapping']}
    def new_id():
        while True:
            value=str(uuid.UUID(int=rng.getrandbits(128),version=4))
            if value not in used:used.add(value);return value
    id_map={};affected_index=ci
    if condition=='B1':set_text(answer,TEXT)
    elif condition in ('D1','D2'):
        parent=answer['parent'];del mapping[aid]
        if condition=='D2':
            for node in mapping.values():
                if node['parent']==aid:node['parent']=parent
            if conv['current_node']==aid:conv['current_node']=parent
    elif condition=='T1':answer['message']['create_time']=node_time(question)-60
    elif condition=='T2':shift_times(conv,-86400)
    elif condition=='I1':
        user=copy.deepcopy(question);bot=copy.deepcopy(answer)
        uid=new_id();bid=new_id()
        for node,nid,parent in ((user,uid,selection['insertion_leaf_uuid']),(bot,bid,uid)):
            node['id']=nid;node['message']['id']=nid;node['parent']=parent
            metadata=node['message'].get('metadata',{})
            if 'parent_id' in metadata:metadata['parent_id']=parent
        set_text(user,'[CONTROLLED INSERTION] 가상 회의 안내문을 작성해 주세요.');set_text(bot,TEXT)
        latest=max([node_time(x) for x in mapping.values() if x.get('message')]+[conv['update_time']])
        for node,t in ((user,latest+60),(bot,latest+61)):
            node['message']['create_time']=t
            if node['message'].get('update_time') is not None:node['message']['update_time']=t
        mapping[uid]=user;mapping[bid]=bot;conv['current_node']=bid;conv['update_time']=latest+61
        id_map={'inserted_user':uid,'inserted_assistant':bid}
    elif condition=='F1':
        fake=copy.deepcopy(conv);cid=new_id();fake['id']=cid;fake['conversation_id']=cid
        fake['title']='SYNTHETIC-'+selection['label']
        id_map={k:new_id() for k in fake['mapping']};new_mapping={}
        for old,node in fake['mapping'].items():
            nid=id_map[old];node['id']=nid
            if node['parent'] is not None:node['parent']=id_map[node['parent']]
            m=node.get('message')
            if m is not None:
                m['id']=nid
                set_text(node,('[가상 사용자 질문] ' if role(node)=='user' else '[가상 응답] ')+TEXT)
                meta=m.get('metadata',{})
                # Preserve observed non-structural parent_id differences; remap known node IDs only.
                if meta.get('parent_id') in id_map:meta['parent_id']=id_map[meta['parent_id']]
            new_mapping[nid]=node
        fake['mapping']=new_mapping;fake['current_node']=id_map[fake['current_node']]
        out.append(fake);affected_index=len(out)-1;id_map['conversation']=cid
    else:raise ValueError('Unknown condition')
    return out,affected_index,id_map


def diffs(before,after,path=''):
    # JSON Pointer paths refer to each full before/after snapshot. List removals can cause index shifts.
    if type(before)!=type(after):return [dict(path=path,action='replace',before=before,after=after)]
    if isinstance(before,dict):
        result=[]
        for k in sorted(before.keys()|after.keys()):
            p=path+'/'+k.replace('~','~0').replace('/','~1')
            if k not in before:result.append(dict(path=p,action='add',after=after[k]))
            elif k not in after:result.append(dict(path=p,action='remove',before=before[k]))
            else:result.extend(diffs(before[k],after[k],p))
        return result
    if isinstance(before,list):
        result=[]
        for i in range(max(len(before),len(after))):
            p=path+'/'+str(i)
            if i>=len(before):result.append(dict(path=p,action='add',after=after[i]))
            elif i>=len(after):result.append(dict(path=p,action='remove',before=before[i]))
            else:result.extend(diffs(before[i],after[i],p))
        return result
    return [] if before==after else [dict(path=path,action='replace',before=before,after=after)]


def check_mutation(data,variant,selection,condition,affected):
    ci=selection['conversation_index'];assert variant!=data,'No semantic change'
    if condition=='F1':assert variant[:-1]==data and len(variant)==len(data)+1
    else:
        assert len(variant)==len(data)
        assert all(a==b for i,(a,b) in enumerate(zip(data,variant)) if i!=ci),'Unrelated conversation modified'
    c=variant[affected];old=data[ci]['mapping'];new=c['mapping'];aid=selection['answer_uuid']
    if condition in ('D1','D2'):assert len(new)==len(old)-1 and aid not in new
    if condition=='D1':assert any(x['parent']==aid for x in new.values())
    if condition=='D2':assert all(x['parent']!=aid for x in new.values())
    if condition=='B1':assert new[aid]['message']['content']['parts']==[TEXT]
    if condition=='T1':assert node_time(new[aid])==node_time(old[selection['question_uuid']])-60
    if condition=='T2':
        for k,node in old.items():
            if node.get('message'):assert abs((node_time(new[k])-node_time(node))+86400)<0.000001
    if condition=='I1':
        assert len(new)==len(old)+2 and all(new[k]==x for k,x in old.items())
        assert c['current_node'] not in old
    if condition=='F1':assert len(new)==len(old) and not(set(old)&set(new)) and c['id']!=data[ci]['id']
    if condition not in ('D1',):
        assert all(x['parent'] is None or x['parent'] in new for x in new.values())
    assert all(k==x['id'] and (x.get('message') is None or x['message']['id']==k) for k,x in new.items())
    assert c['current_node'] in new


def report_for(v,data,source_path,source_sha):
    units=v.validate('chatgpt',data)
    return dict(validator_version=v.VERSION,validator_sha256=VALIDATOR_HASH,service='chatgpt',
                executed_at_utc=datetime.now(timezone.utc).isoformat(),input_path=str(source_path),input_sha256=source_sha,
                processing_status='completed',unit_count=len(units),unit_type='conversation',
                summary=v.summarize('chatgpt',units),units=units,
                interpretation='Internal consistency only. Not authenticity or intent verification.')


def csv_save(path,rows,fields):
    with path.open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path)
    p.add_argument('--out-dir',type=Path,default=Path(__file__).resolve().parent.parent/'results')
    a=p.parse_args()
    validator_path=Path(__file__).resolve().with_name('validate_exports.py')
    v=load_validator(validator_path);raw=a.input.read_bytes();source_hash=hash_bytes(raw)
    data=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=v.pairs_hook,parse_float=v.finite_float,parse_constant=v.reject_constant)
    if not isinstance(data,list):raise ValueError('Expected conversation list')
    selection=select(data)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder=a.out_dir/('chatgpt_eval_run_'+stamp);folder.mkdir(parents=True,exist_ok=False)
    for sub in ('variants','reports','manifests'):(folder/sub).mkdir()
    baseline=report_for(v,data,a.input.resolve(),source_hash)
    dump(folder/'baseline_report.json',baseline)
    dump(folder/'selection_manifest.json',dict(source_sha256=source_hash,selections=selection,conditions=list(CONDITIONS)))
    metadata=dict(runner_version=VERSION,runner_sha256=hash_bytes(Path(__file__).read_bytes()),validator_sha256=VALIDATOR_HASH,
                  source_path=str(a.input.resolve()),source_sha256=source_hash,created_at_utc=stamp,planned_cases=len(selection)*len(CONDITIONS),
                  fixed_choices=dict(id_generation='deterministic seeded UUIDv4; not an authenticity feature',time_shift_fields=list(TIME_FIELDS),insertion='export current_node required to be an assistant leaf'),
                  limitations='Exploratory study with prior EVAL inspection. No independent-sample assumption. Relinking does not preserve role alternation/semantics. Other metadata copied; metadata.parent_id is not assumed equal to mapping.parent. No proof of advanced forgery realism. B2 is not applicable to the observed ChatGPT content representation.')
    dump(folder/'run_metadata.json',metadata)
    if any(r['finding_count'] or r['blocked'] for r in baseline['summary']):raise ValueError(f'Baseline has findings/blocked checks. Review {folder}; no variants generated.')
    rows=[];json_rows=[]
    for sel in selection:
        for condition in CONDITIONS:
            case=sel['label']+'_'+condition
            try:variant,affected,id_map=make_case(data,sel,condition,source_hash)
            except (ValueError,KeyError,TypeError) as e:
                rows.append(dict(case_id=case,conversation=sel['label'],condition=condition,status='skipped',format_detected='',relational_detected='',any_detected='',incomplete='',input_error=0,related_rules='',outside_findings='',reason=str(e)))
                json_rows.append(dict(case_id=case,status='skipped',reason=str(e)));continue
            check_mutation(data,variant,sel,condition,affected)
            target=folder/'variants'/(case+'.json');target_hash=dump(target,variant)
            # Read generated bytes back before validation; audit is separate from validator.
            reread=json.loads(target.read_text(encoding='utf-8'),object_pairs_hook=v.pairs_hook)
            assert reread==variant
            changes=diffs(data,variant)
            dump(folder/'manifests'/(case+'.json'),dict(case_id=case,condition=condition,selection=sel,affected_conversation_index=affected,
                 source_sha256=source_hash,variant_sha256=target_hash,id_map=id_map,changes=changes,mutation_audit='passed'))
            rep=report_for(v,reread,target.resolve(),target_hash);dump(folder/'reports'/(case+'.json'),rep)
            u=rep['units'][affected]
            hit=[r for r in u['rules'] if r['findings']]
            outside=sum(len(r['findings']) for j,unit in enumerate(rep['units']) if j!=affected for r in unit['rules'])
            fmt=int(any(r['category']=='format' for r in hit));rel=int(any(r['category']=='relational' for r in hit))
            blocked=int(any(r['blocked'] for r in u['rules']))
            row=dict(case_id=case,conversation=sel['label'],condition=condition,status='evaluated',format_detected=fmt,relational_detected=rel,any_detected=int(bool(hit)),incomplete=blocked,input_error=0,related_rules=';'.join(r['rule'] for r in hit),outside_findings=outside,reason='')
            rows.append(row);json_rows.append(dict(**row,affected_conversation_index=affected,variant_sha256=target_hash,mutation_audit='passed',report=str(Path('reports')/(case+'.json'))))
    assert a.input.read_bytes()==raw,'Input changed during run'
    fields=['case_id','conversation','condition','status','format_detected','relational_detected','any_detected','incomplete','input_error','related_rules','outside_findings','reason']
    csv_save(folder/'case_results.csv',rows,fields);dump(folder/'case_results.json',json_rows)
    summaries=[]
    for condition in CONDITIONS:
        selected=[r for r in rows if r['condition']==condition];ev=[r for r in selected if r['status']=='evaluated'];n=len(ev);hits=sum(r['any_detected'] for r in ev)
        summaries.append(dict(condition=condition,planned=len(selected),evaluated=n,skipped=len(selected)-n,
             format_detected=sum(r['format_detected'] for r in ev),relational_detected=sum(r['relational_detected'] for r in ev),
             any_detected=hits,fully_checked_no_finding=sum(not r['any_detected'] and not r['incomplete'] for r in ev),
             incomplete_any=sum(r['incomplete'] for r in ev),incomplete_only=sum(r['incomplete'] and not r['any_detected'] for r in ev),
             input_errors=0,detection_fraction=f'{hits}/{n}' if n else 'NA',detection_percent=round(100*hits/n,2) if n else 'NA'))
    csv_save(folder/'condition_summary.csv',summaries,list(summaries[0]))
    print(f'Validator: {v.VERSION} (hash verified)\nSelected EVAL conversations: {len(selection)}\nPlanned cases: {len(rows)}')
    for r in summaries:print(f"{r['condition']}: detected={r['detection_fraction']} | incomplete_any={r['incomplete_any']} skipped={r['skipped']}")
    dump(folder/'COMPLETED.json',dict(status='completed',source_unchanged=True,case_count=len(rows),evaluated=sum(r['status']=='evaluated' for r in rows)))
    print(f'Output: {folder.resolve()}\nInput unchanged. Findings are not authenticity judgments.')


if __name__=='__main__':
    try:main()
    except Exception as e:
        print(f'BATCH STOPPED: {type(e).__name__}: {e}',file=sys.stderr)
        print('Preserve partial outputs for diagnosis. Do not treat this run as complete.',file=sys.stderr)
        sys.exit(1)
