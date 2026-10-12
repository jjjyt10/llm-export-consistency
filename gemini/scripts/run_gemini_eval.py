"""Gemini EVAL batch v1.0.0. Requires unmodified validate_exports.py v0.2.
Usage: python scripts/run_gemini_eval.py input/gemini_eval_export.json
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
CONDITIONS=('B1','D1','T2','I1','F1')
TEXT='연구용 변경 문장입니다. 회의 장소는 Z회의실이며 시간은 오후 5시입니다.'
TIME_FIELDS=('time',)


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


def csv_save(path,rows,fields):
    with path.open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


def urls(item):
    return sorted({d['url'] for d in item.get('details',[]) if isinstance(d,dict) and isinstance(d.get('url'),str)})


def select(data):
    selected={}
    for n in range(1,10):
        label=f'EVAL-GEMINI-{n:02d}';tag='['+label+']'
        candidates=[i for i,x in enumerate(data) if tag in x.get('title','')]
        if not candidates:raise ValueError('Missing '+label)
        i=min(candidates,key=lambda j:(dt(data[j]['time']),j))
        if i in selected:selected[i]['labels'].append(label);continue
        selected[i]=dict(label=label,labels=[label],activity_index=i,time=data[i]['time'],
                         linked_urls=urls(data[i]),response_html_index=0,
                         selection_policy='earliest tagged activity; first HTML array position, not inferred response chronology')
    return list(selected.values())


def make_case(data,sel,condition,sha):
    out=copy.deepcopy(data);i=sel['activity_index'];item=out[i];ids={};affected=i
    if condition=='B1':
        if not item.get('safeHtmlItem'):raise ValueError('No response HTML')
        item['safeHtmlItem'][0]['html']='<p>'+TEXT+'</p>'
    elif condition=='D1':del out[i];affected=None
    elif condition=='T2':item['time']=iso(dt(item['time'])-timedelta(days=1))
    elif condition in ('I1','F1'):
        new=copy.deepcopy(item)
        new['title']='[CONTROLLED '+condition+'] 연구용 가상 회의 안내문을 작성해 주세요. 항목을 검색함'
        new['safeHtmlItem']=[{'html':'<p>'+TEXT+'</p>'}]
        new['time']=iso(max(dt(x['time']) for x in data)+timedelta(seconds=60))
        if condition=='F1':
            seed=hash_bytes((sha+sel['label']+condition).encode());counter=0
            existing={u for x in data for u in urls(x)}
            while True:
                u='https://gemini.google.com/app/'+hash_bytes((seed+str(counter)).encode())[:16]
                if u not in existing:break
                counter+=1
            new['details']=[{'name':u,'url':u}];ids={'synthetic_conversation_url':u}
        elif not urls(new):raise ValueError('No existing conversation URL for I1')
        out.append(new);affected=len(out)-1
    else:raise ValueError('Unknown condition')
    return out,affected,ids


def audit(data,out,sel,condition,affected):
    i=sel['activity_index'];assert out!=data
    if condition=='D1':assert out==data[:i]+data[i+1:]
    elif condition in ('I1','F1'):
        assert out[:-1]==data and len(out)==len(data)+1
        assert out[-1]['safeHtmlItem']==[{'html':'<p>'+TEXT+'</p>'}]
        if condition=='I1':assert out[-1]['details']==data[i]['details']
        else:assert not(set(urls(out[-1]))&{u for x in data for u in urls(x)})
    else:
        assert len(out)==len(data) and all(x==out[j] for j,x in enumerate(data) if j!=i)
        changes=diffs(data,out);assert len(changes)==1
        if condition=='B1':assert changes[0]['path']==f'/{i}/safeHtmlItem/0/html'
        if condition=='T2':assert dt(out[i]['time'])-dt(data[i]['time'])==timedelta(days=-1)


def report_for(v,data,path,sha):
    units=v.validate('gemini',data)
    return dict(validator_version=v.VERSION,validator_sha256=VALIDATOR_HASH,service='gemini',
        executed_at_utc=datetime.now(timezone.utc).isoformat(),input_path=str(path),input_sha256=sha,
        processing_status='completed',unit_count=len(units),unit_type='activity',
        summary=v.summarize('gemini',units),units=units,
        interpretation='Format checks only for this export profile. Relational rules unsupported. No authenticity judgment.')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path)
    p.add_argument('--out-dir',type=Path,default=Path(__file__).resolve().parent.parent/'results');a=p.parse_args()
    v=load_validator(Path(__file__).resolve().with_name('validate_exports.py'))
    raw=a.input.read_bytes();sha=hash_bytes(raw)
    data=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=v.pairs_hook,parse_float=v.finite_float,parse_constant=v.reject_constant)
    if not isinstance(data,list):raise ValueError('Expected activity list')
    selection=select(data);stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder=a.out_dir/('gemini_eval_run_'+stamp);folder.mkdir(parents=True,exist_ok=False)
    for sub in ('variants','reports','manifests'):(folder/sub).mkdir()
    baseline=report_for(v,data,a.input.resolve(),sha);dump(folder/'baseline_report.json',baseline)
    eval_urls={u for sel in selection for u in sel['linked_urls']}
    eval_indices=[i for i,x in enumerate(data) if set(urls(x))&eval_urls]
    dump(folder/'selection_manifest.json',dict(source_sha256=sha,selections=selection,conditions=CONDITIONS,
         eval_related_activity_indices=eval_indices,excluded_activity_indices=[i for i in range(len(data)) if i not in eval_indices]))
    unsupported=[r['rule'] for r in baseline['units'][0]['rules'] if not r['supported']]
    dump(folder/'run_metadata.json',dict(runner_version=VERSION,runner_sha256=hash_bytes(Path(__file__).read_bytes()),
        validator_sha256=VALIDATOR_HASH,source_sha256=sha,source_path=str(a.input.resolve()),created_at_utc=stamp,
        planned_cases=len(selection)*len(CONDITIONS),unsupported_rules=unsupported,
        not_applicable_conditions=['B2','D2','T1'],time_shift_fields=['time'],
        limitations='Exploratory, prior EVAL inspection; activities are not messages or independent conversations. Only format checks implemented. No total service ranking.',
        insertion='Append without sorting. I1 preserves existing details/URLs; F1 assigns one synthetic URL. Other metadata copied.',
        deletion='Whole activity deletion; no deleted unit remains to inspect. Scan all surviving units; warnings there are outside the deleted unit and require review.'))
    if any(r['finding_count'] or r['blocked'] for r in baseline['summary']):raise ValueError('Baseline has findings/blocked checks; review before mutation')
    rows=[];jsonrows=[]
    for sel in selection:
        for condition in CONDITIONS:
            case=sel['label']+'_'+condition
            try:out,affected,ids=make_case(data,sel,condition,sha)
            except (ValueError,KeyError,TypeError) as e:
                rows.append(dict(case_id=case,activity_label=sel['label'],condition=condition,status='skipped',format_detected='',relational_detected='NA',any_detected='',incomplete='',input_error=0,related_rules='',outside_findings='',relational_supported=0,reason=str(e)))
                continue
            audit(data,out,sel,condition,affected)
            path=folder/'variants'/(case+'.json');outsha=dump(path,out)
            reread=json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=v.pairs_hook)
            assert reread==out
            dump(folder/'manifests'/(case+'.json'),dict(case_id=case,condition=condition,selection=sel,
                affected_activity_index=affected,source_sha256=sha,variant_sha256=outsha,id_map=ids,
                changes=diffs(data,out),mutation_audit='passed',array_policy='No reordering; deletion shifts subsequent array indices; insertions appended'))
            rep=report_for(v,reread,path.resolve(),outsha);dump(folder/'reports'/(case+'.json'),rep)
            rules=[] if affected is None else rep['units'][affected]['rules']
            hit=[r for r in rules if r['findings']]
            outside=sum(len(r['findings']) for j,u in enumerate(rep['units']) if j!=affected for r in u['rules'])
            blocked=int(any(r['blocked'] for r in rules))
            row=dict(case_id=case,activity_label=sel['label'],condition=condition,status='evaluated',
                format_detected=int(bool(hit)),relational_detected='NA',any_detected=int(bool(hit)),incomplete=blocked,
                input_error=0,related_rules=';'.join(r['rule'] for r in hit),outside_findings=outside,relational_supported=0,reason='')
            rows.append(row);jsonrows.append(dict(**row,affected_activity_index=affected,variant_sha256=outsha,
                mutation_audit='passed',report='reports/'+case+'.json'))
    assert a.input.read_bytes()==raw,'Input changed during run'
    csv_save(folder/'case_results.csv',rows,list(rows[0]));dump(folder/'case_results.json',jsonrows)
    summaries=[]
    for condition in CONDITIONS:
        rr=[r for r in rows if r['condition']==condition];ev=[r for r in rr if r['status']=='evaluated'];n=len(ev);hits=sum(r['any_detected'] for r in ev)
        summaries.append(dict(condition=condition,planned=len(rr),evaluated=n,skipped=len(rr)-n,
            format_detected=sum(r['format_detected'] for r in ev),relational_detected='NA',relational_supported=0,
            any_detected=hits,no_finding_under_supported_rules=sum(not r['any_detected'] and not r['incomplete'] for r in ev),
            incomplete_any=sum(r['incomplete'] for r in ev),incomplete_only=sum(r['incomplete'] and not r['any_detected'] for r in ev),
            input_errors=0,detection_fraction=f'{hits}/{n}' if n else 'NA',detection_percent=round(100*hits/n,2) if n else 'NA'))
    csv_save(folder/'condition_summary.csv',summaries,list(summaries[0]))
    dump(folder/'COMPLETED.json',dict(status='completed',source_unchanged=True,case_count=len(rows),evaluated=sum(r['status']=='evaluated' for r in rows)))
    print(f'Validator: {v.VERSION} (hash verified)\nSelected unique EVAL activities: {len(selection)}\nEVAL-related baseline activities: {len(eval_indices)}\nPlanned cases: {len(rows)}\nRelational checks: NOT SUPPORTED')
    for r in summaries:print(f"{r['condition']}: detected={r['detection_fraction']} | incomplete_any={r['incomplete_any']} skipped={r['skipped']}")
    print(f'Output: {folder.resolve()}\nInput unchanged. Format checks only; no authenticity judgment.')


if __name__=='__main__':
    try:main()
    except Exception as e:
        print(f'BATCH STOPPED: {type(e).__name__}: {e}',file=sys.stderr)
        print('Preserve partial outputs. Do not treat this run as complete.',file=sys.stderr);sys.exit(1)
