"""Existing-parent reassignment, exploratory extension. Candidate-only frozen validator."""
import argparse, copy, csv, hashlib, importlib.util, json
from pathlib import Path
from datetime import datetime, timezone
VERSION='1.0.0-claude-parent'
EXPECTED='71a54078a3b79d86027187267c07117fbec3928640bbd31f18079daf18bc744c'
def sha(b): return hashlib.sha256(b).hexdigest()
def dump(p,d): p.write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def dt(m): return datetime.fromisoformat(m['created_at'].replace('Z','+00:00'))
def ancestor(by, descendant, candidate):
    seen=set(); cur=descendant
    while cur in by and cur not in seen:
        if cur==candidate:return True
        seen.add(cur);cur=by[cur]['parent_message_uuid']
    return False

def select(c,condition):
    mm=c['chat_messages'];by={m['uuid']:m for m in mm}
    if len(by)!=len(mm):raise ValueError('Duplicate IDs')
    pairs=[]
    for i,m in enumerate(mm):
        if m['sender']!='assistant' or m['parent_message_uuid'] not in by:continue
        for j,p in enumerate(mm):
            if p['sender']!='human' or p['uuid']==m['parent_message_uuid']:continue
            desc=ancestor(by,p['uuid'],m['uuid'])
            eligible=(not desc and dt(p)<=dt(m)) if condition=='P1_existing_parent_acyclic' else desc
            if eligible:pairs.append((i,j))
    if not pairs:raise ValueError('No eligible pair: '+c['name']+' '+condition)
    # Explicit fixed selection: earliest eligible assistant in stored array, earliest human.
    i,j=min(pairs);return i,j

def diff(a,b,path=''):
    if type(a)!=type(b):return [dict(path=path,before=a,after=b)]
    if isinstance(a,dict):
        if a.keys()!=b.keys():raise AssertionError('Unexpected key changes')
        return [v for k in a for v in diff(a[k],b[k],path+'/'+k)]
    if isinstance(a,list):
        if len(a)!=len(b):raise AssertionError('Unexpected list size change')
        return [v for i,(x,y) in enumerate(zip(a,b)) for v in diff(x,y,path+'/'+str(i))]
    return [] if a==b else [dict(path=path,before=a,after=b)]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('input');ap.add_argument('--out');args=ap.parse_args()
    src=Path(args.input);raw=src.read_bytes();vp=Path(__file__).with_name('validate_exports.py')
    if sha(vp.read_bytes())!=EXPECTED:raise ValueError('Frozen v0.2 validator hash differs; do not overwrite or bypass')
    spec=importlib.util.spec_from_file_location('v02',vp);v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
    data=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=v.pairs_hook,parse_constant=v.reject_constant,parse_float=v.finite_float)
    selections=[]
    for n in range(1,10):
        title=f'EVAL-CLAUDE-{n:02d}';ii=[i for i,c in enumerate(data) if c.get('name')==title]
        if len(ii)!=1:raise ValueError('Expected one '+title)
        selections.append(ii[0])
    baseline=v.validate('claude',data)
    if any(r['findings'] or r['blocked'] for i in selections for r in baseline[i]['rules']):raise ValueError('EVAL baseline requires review')
    plans=[]
    for ci in selections:
        for condition in ['P1_existing_parent_acyclic','P2_existing_parent_cycle']:
            mi,pi=select(data[ci],condition);plans.append(dict(conversation_index=ci,label=data[ci]['name'],condition=condition,message_index=mi,new_parent_index=pi))
    out=Path(args.out) if args.out else Path('results')/('claude_parent_eval_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True,exist_ok=False)
    dump(out/'run_metadata.json',dict(version=VERSION,source_sha256=sha(raw),validator_sha256=EXPECTED,script_sha256=sha(Path(__file__).read_bytes()),selection_policy='Earliest eligible assistant then human in stored array; P1 acyclic and time-preserving, P2 descendant parent. Conditions may use different target messages.',related_reference_sync='Not applied: no independently duplicated parent reference established in this profile.',time_policy='timestamp_format and parent_time_order findings reported as time warnings; v0.2 raw outputs retained.'))
    dump(out/'baseline_report.json',baseline);dump(out/'selected_targets.json',plans)
    rows=[]
    for plan in plans:
        ci,mi,pi=plan['conversation_index'],plan['message_index'],plan['new_parent_index'];d=copy.deepcopy(data)
        m=d[ci]['chat_messages'][mi];p=d[ci]['chat_messages'][pi];m['parent_message_uuid']=p['uuid']
        changes=diff(data,d);expected_path=f'/{ci}/chat_messages/{mi}/parent_message_uuid'
        if len(changes)!=1 or changes[0]['path']!=expected_path:raise AssertionError('Mutation scope mismatch')
        folder=out/(plan['label']+'_'+plan['condition']);folder.mkdir();dump(folder/'variant.json',d)
        candidate=json.loads((folder/'variant.json').read_text(encoding='utf-8'));reports=v.validate('claude',candidate)
        outside=[i for i in range(len(data)) if i!=ci and reports[i]!=baseline[i]]
        if outside:raise AssertionError('Unexpected report change outside target')
        dump(folder/'report.json',reports)
        dump(folder/'mutation_record.json',dict(**plan,changes=changes,target_uuid=m['uuid'],new_parent_uuid=p['uuid'],source_sha256=sha(raw),variant_sha256=sha((folder/'variant.json').read_bytes()),audit_passed=True))
        rr={r['rule']:r for r in reports[ci]['rules']};time_names={'timestamp_format','parent_time_order'}
        row=dict(case=folder.name,condition=plan['condition'],structural_detected=int(any(r['findings'] for k,r in rr.items() if k not in time_names)),time_warning=int(any(rr[k]['findings'] for k in time_names)),parent_reference_findings=len(rr['parent_reference']['findings']),parent_cycle_findings=len(rr['parent_cycle']['findings']),incomplete=int(any(r['blocked'] for r in rr.values())))
        rows.append(row)
    with (out/'case_results.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    summary=[]
    for cond in dict.fromkeys(r['condition'] for r in rows):
        rs=[r for r in rows if r['condition']==cond];item=dict(condition=cond,cases=len(rs),structural_detected=sum(r['structural_detected'] for r in rs),time_warning=sum(r['time_warning'] for r in rs),incomplete=sum(r['incomplete'] for r in rs));summary.append(item);print(item)
    dump(out/'condition_summary.json',summary)
    if src.read_bytes()!=raw:raise AssertionError('Input changed')
    (out/'COMPLETED.txt').write_text('Input unchanged. 18 derived variants, not 18 independent conversations. No authenticity determination.\n',encoding='utf-8')
    print('Output:',out.resolve())
if __name__=='__main__':main()
