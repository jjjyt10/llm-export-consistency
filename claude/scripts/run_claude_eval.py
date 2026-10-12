"""Claude EVAL batch v1.0.0. Requires unmodified validate_exports.py v0.2.
Usage: python scripts/run_claude_eval.py input/claude_eval_export.json
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
CONDITIONS=('B1','B2','D1','D2','T1','T2','I1','F1')
TEXT='연구용 변경 문장입니다. 회의 장소는 Z회의실이며 시간은 오후 5시입니다.'
TIME_FIELDS=('created_at','updated_at','start_timestamp','stop_timestamp')


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


def text_ok(m):
    blocks=m.get('content')
    return (isinstance(m.get('text'),str) and isinstance(blocks,list) and len(blocks)==1
            and blocks[0].get('type')=='text' and isinstance(blocks[0].get('text'),str)
            and not m.get('attachments') and not m.get('files'))


def set_text(m,value):
    if not text_ok(m):raise ValueError('Requires a single text block and no attachments/files')
    m['text']=value;m['content'][0]['text']=value


def select(data):
    planned=[]
    for n in range(1,10):
        label=f'EVAL-CLAUDE-{n:02d}'
        matches=[i for i,c in enumerate(data) if c.get('name')==label]
        if len(matches)!=1:raise ValueError(f'Expected one {label}, found {len(matches)}')
        ci=matches[0];c=data[ci];messages=c['chat_messages']
        first=min((m for m in messages if m['sender']=='human'),key=lambda m:(dt(m['created_at']),m['uuid']))
        answers=[m for m in messages if m['sender']=='assistant' and m['parent_message_uuid']==first['uuid']]
        preferred=[m for m in answers if any(x['sender']=='human' and x['parent_message_uuid']==m['uuid'] for x in messages)]
        answer=min(preferred or answers,key=lambda m:(dt(m['created_at']),m['uuid']))
        parent_ids={m['parent_message_uuid'] for m in messages}
        leaves=[m for m in messages if m['sender']=='assistant' and m['uuid'] not in parent_ids]
        leaf=max(leaves,key=lambda m:(dt(m['created_at']),m['uuid']))
        planned.append(dict(label=label,conversation_index=ci,conversation_uuid=c['uuid'],
                    question_uuid=first['uuid'],answer_uuid=answer['uuid'],answer_created_at=answer['created_at'],
                    preferred_followup_answer=bool(preferred),
                    insertion_leaf_uuid=leaf['uuid'],insertion_leaf_policy='latest-created assistant leaf; not a claim about active UI branch'))
    return planned


def shift_times(obj,delta):
    if isinstance(obj,dict):
        for k,v in obj.items():
            if k in TIME_FIELDS and v is not None:obj[k]=iso(dt(v)+delta)
            elif isinstance(v,(dict,list)):shift_times(v,delta)
    elif isinstance(obj,list):
        for v in obj:shift_times(v,delta)


def set_message_times(m,value):
    for k in ('created_at','updated_at'):
        if k=='created_at' or m.get(k) is not None:m[k]=iso(value)
    for block in m['content']:
        for k in ('start_timestamp','stop_timestamp'):
            if block.get(k) is not None:block[k]=iso(value)


def make_case(data,selection,condition,source_hash):
    out=copy.deepcopy(data);ci=selection['conversation_index'];conv=out[ci];messages=conv['chat_messages']
    by_id={m['uuid']:m for m in messages};answer=by_id[selection['answer_uuid']];question=by_id[selection['question_uuid']]
    if not text_ok(answer) or not text_ok(question):raise ValueError('Selected question/answer not eligible for text-only batch profile')
    seed=int(hash_bytes((source_hash+selection['label']+condition).encode()),16)
    rng=random.Random(seed);used={c['uuid'] for c in data}|{m['uuid'] for c in data for m in c['chat_messages']}
    id_map={}
    def new_id():
        while True:
            value=str(uuid.UUID(int=rng.getrandbits(128),version=4))
            if value not in used:used.add(value);return value
    affected_index=ci
    if condition=='B1':answer['text']=TEXT
    elif condition=='B2':set_text(answer,TEXT)
    elif condition in ('D1','D2'):
        target=answer['uuid'];parent=answer['parent_message_uuid']
        conv['chat_messages']=[m for m in messages if m['uuid']!=target]
        if condition=='D2':
            for m in conv['chat_messages']:
                if m['parent_message_uuid']==target:m['parent_message_uuid']=parent
    elif condition=='T1':answer['created_at']=iso(dt(question['created_at'])-timedelta(seconds=60))
    elif condition=='T2':shift_times(conv,timedelta(days=-1))
    elif condition=='I1':
        user=copy.deepcopy(question);bot=copy.deepcopy(answer)
        user['uuid']=new_id();bot['uuid']=new_id()
        user['parent_message_uuid']=selection['insertion_leaf_uuid'];bot['parent_message_uuid']=user['uuid']
        set_text(user,'[CONTROLLED INSERTION] 가상 회의 안내문을 작성해 주세요.');set_text(bot,TEXT)
        latest=max(dt(m['created_at']) for m in messages)
        if conv.get('updated_at') is not None:latest=max(latest,dt(conv['updated_at']))
        set_message_times(user,latest+timedelta(seconds=60));set_message_times(bot,latest+timedelta(seconds=61))
        messages.extend([user,bot])
        if conv.get('updated_at') is not None:conv['updated_at']=bot['created_at']
        id_map={'inserted_user':user['uuid'],'inserted_assistant':bot['uuid']}
    elif condition=='F1':
        fake=copy.deepcopy(conv);fake['uuid']=new_id();fake['name']='SYNTHETIC-'+selection['label'];fake['summary']='Controlled synthetic conversation for research.'
        id_map={m['uuid']:new_id() for m in fake['chat_messages']}
        for m in fake['chat_messages']:
            old=m['uuid'];m['uuid']=id_map[old]
            if m['parent_message_uuid']!=ROOT:m['parent_message_uuid']=id_map[m['parent_message_uuid']]
            set_text(m,('[가상 사용자 질문] ' if m['sender']=='human' else '[가상 응답] ')+TEXT)
        out.append(fake);affected_index=len(out)-1
        id_map['conversation']=fake['uuid']
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
    ci=selection['conversation_index']
    assert variant!=data,'No semantic JSON change'
    if condition=='F1':assert variant[:-1]==data and len(variant)==len(data)+1
    else:
        assert len(variant)==len(data)
        assert all(a==b for i,(a,b) in enumerate(zip(data,variant)) if i!=ci),'Unrelated conversation modified'
    c=variant[affected];messages=c['chat_messages'];original=data[ci]['chat_messages'];old={m['uuid']:m for m in original};new={m['uuid']:m for m in messages};aid=selection['answer_uuid']
    if condition in ('D1','D2'):assert len(messages)==len(original)-1 and aid not in new
    if condition=='D1':assert any(m['parent_message_uuid']==aid for m in messages),'No dangling ref after deletion'
    if condition=='D2':assert all(m['parent_message_uuid']!=aid for m in messages)
    if condition=='B1':assert new[aid]['text']==TEXT and new[aid]['content']==old[aid]['content']
    if condition=='B2':assert new[aid]['text']==new[aid]['content'][0]['text']==TEXT
    if condition=='T1':assert dt(new[aid]['created_at'])<dt(old[selection['question_uuid']]['created_at'])
    if condition=='T2':assert all(dt(new[k]['created_at'])-dt(m['created_at'])==timedelta(days=-1) for k,m in old.items())
    if condition=='I1':assert len(messages)==len(original)+2 and len(new)==len(messages)
    if condition=='F1':assert len(messages)==len(original) and not(set(old)&set(new)) and c['uuid']!=data[ci]['uuid']


def report_for(v,data,source_path,source_sha):
    units=v.validate('claude',data)
    return dict(validator_version=v.VERSION,validator_sha256=VALIDATOR_HASH,service='claude',
                executed_at_utc=datetime.now(timezone.utc).isoformat(),input_path=str(source_path),input_sha256=source_sha,
                processing_status='completed',unit_count=len(units),unit_type='conversation',
                summary=v.summarize('claude',units),units=units,
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
    folder=a.out_dir/('claude_eval_run_'+stamp);folder.mkdir(parents=True,exist_ok=False)
    for sub in ('variants','reports','manifests'):(folder/sub).mkdir()
    baseline=report_for(v,data,a.input.resolve(),source_hash)
    dump(folder/'baseline_report.json',baseline)
    dump(folder/'selection_manifest.json',dict(source_sha256=source_hash,selections=selection,conditions=list(CONDITIONS)))
    metadata=dict(runner_version=VERSION,runner_sha256=hash_bytes(Path(__file__).read_bytes()),validator_sha256=VALIDATOR_HASH,
                  source_path=str(a.input.resolve()),source_sha256=source_hash,created_at_utc=stamp,planned_cases=len(selection)*len(CONDITIONS),
                  fixed_choices=dict(id_generation='deterministic seeded UUIDv4, not a mimic of observed UUIDv7',time_shift_fields=list(TIME_FIELDS),insertion='latest-created assistant leaf; current UI branch unknown'),
                  limitations='Exploratory study with prior EVAL inspection. No independent-sample assumption. Relinking does not preserve role alternation/semantics. Other metadata copied; no proof of advanced forgery realism.')
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
