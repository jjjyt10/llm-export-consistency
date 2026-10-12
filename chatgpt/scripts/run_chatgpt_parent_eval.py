"""Exploratory existing-parent / duplicate representation comparison."""
import argparse,copy,csv,json,hashlib
from pathlib import Path
from datetime import datetime,timezone
import validate_exports as v
import chatgpt_crossfile as x
VERSION='1.0.0-chatgpt-parent'
VHASH='71a54078a3b79d86027187267c07117fbec3928640bbd31f18079daf18bc744c'
def ancestor(mm,desc,candidate):
    seen=set()
    while desc in mm and desc not in seen:
        if desc==candidate:return True
        seen.add(desc);desc=mm[desc].get('parent')
    return False

def select(c,cycle):
    mm=c['mapping'];pairs=[]
    for k,n in mm.items():
        m=n.get('message') or {}
        if m.get('author',{}).get('role')!='assistant':continue
        for p,pn in mm.items():
            pm=pn.get('message') or {}
            if pm.get('author',{}).get('role')!='user' or p==n.get('parent'):continue
            t,pt=m.get('create_time'),pm.get('create_time')
            if type(t) not in (int,float) or type(pt) not in (int,float):continue
            desc=ancestor(mm,p,k)
            if (desc if cycle else not desc and pt<=t):pairs.append((t,k,pt,p))
    if not pairs:raise ValueError('No eligible pair: '+c['title'])
    _,k,_,p=min(pairs);return k,p

def main():
    a=argparse.ArgumentParser();a.add_argument('archive');a.add_argument('--out');args=a.parse_args()
    if x.sha(Path(v.__file__).read_bytes())!=VHASH:raise ValueError('Frozen validator hash mismatch')
    if x.sha(Path(x.__file__).read_bytes())!=XHASH:raise ValueError('Crossfile validator hash mismatch')
    src=Path(args.archive);raw=src.read_bytes();files=x.read_archive(src);data=x.parse(files['conversations.json']);base=x.validate(files)
    if not x.is_clean(base):raise ValueError('Crossfile baseline needs review')
    titles=[f'EVAL-CGPT-{n:02d}' if n!=3 else 'EVAL-CGPT-03-R1' for n in range(1,10)]
    selected=[]
    for title in titles:
        ii=[i for i,c in enumerate(data) if c.get('title')==title]
        if len(ii)!=1:raise ValueError('Expected exactly one '+title+'; use original EVAL archive')
        ci=ii[0]
        if any('children' in node for node in data[ci]['mapping'].values()):raise ValueError('Profile changed: children fields require review')
        for graph,cycle in [('P1_acyclic',False),('P2_cycle',True)]:
            k,p=select(data[ci],cycle);selected.append(dict(title=title,conversation_index=ci,graph=graph,node_id=k,new_parent=p))
    baseline=v.validate('chatgpt',data)
    if any(r['findings'] or r['blocked'] for s in selected for r in baseline[s['conversation_index']]['rules']):raise ValueError('Graph baseline needs review')
    out=Path(args.out) if args.out else Path('results')/('chatgpt_parent_eval_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True,exist_ok=False)
    x.save_json(out/'selected_targets.json',selected)
    x.save_json(out/'baseline_report.json',dict(graph=baseline,crossfile=base))
    x.save_json(out/'run_metadata.json',dict(version=VERSION,source_sha256=x.sha(raw),script_sha256=x.sha(Path(__file__).read_bytes()),validator_sha256=VHASH,crossfile_sha256=XHASH,selection='Earliest eligible assistant creation time/ID, then user creation time/ID; same pair for JSON-only and both representations.',scope='mapping.parent only. metadata.parent_id is not assumed equivalent. No children field in observed input.',time_policy='timestamp_format and parent_time_order separated as warnings. Raw v0.2 retained.',interpretation='HTML redundant copy is not an independent trusted source. Existing-parent plus related representation comparison, not bidirectional graph-pointer repair.'))
    rows=[]
    cases=[(None,'C0_reserialize')]+[(s,mode) for s in selected for mode in ['json_only','json_html_both']]
    for s,mode in cases:
        d=copy.deepcopy(data);changed=dict(files);ci=s['conversation_index'] if s else None
        if s:d[ci]['mapping'][s['node_id']]['parent']=s['new_parent']
        delta=x.differences(data,d)
        if s:
            expected=f"/{ci}/mapping/{s['node_id']}/parent"
            if len(delta)!=1 or delta[0]['path']!=expected:raise AssertionError('Unexpected semantic change')
        elif delta:raise AssertionError('Control changed semantics')
        changed['conversations.json']=x.encode(d)
        if mode=='json_html_both':
            _,text,start,end=x.html_data(files['chat.html'])
            changed['chat.html']=(text[:start]+json.dumps(d,ensure_ascii=True,allow_nan=False)+text[end:]).encode('utf-8')
            if x.differences(data,x.html_data(changed['chat.html'])[0])!=delta:raise AssertionError('HTML semantic change mismatch')
        else:
            if changed['chat.html']!=files['chat.html']:raise AssertionError('Unexpected HTML change')
        x.update_sizes(changed)
        cond=s['graph']+'_'+mode if s else mode;case=s['title']+'_'+cond if s else mode
        folder=out/case;folder.mkdir();zp=folder/'variant.zip';x.write_zip(zp,changed);reopened=x.read_archive(zp)
        if reopened!=changed:raise AssertionError('ZIP roundtrip differs')
        reports=v.validate('chatgpt',x.parse(reopened['conversations.json']));cross=x.validate(reopened)
        if any(reports[i]!=baseline[i] for i in range(len(data)) if i!=ci):raise AssertionError('Outside target report changed')
        x.save_json(folder/'report.json',dict(graph=reports,crossfile=cross,authenticity_determination=False))
        x.save_json(folder/'mutation_record.json',dict(condition=cond,selection=s,semantic_changes=delta,source_sha256=x.sha(raw),variant_sha256=x.sha(zp.read_bytes()),audit_passed=True,changed_files=[dict(path=k,before_sha256=x.sha(files[k]),after_sha256=x.sha(changed[k])) for k in files if files[k]!=changed[k]]))
        rr=reports[ci]['rules'] if s else [r for u in reports for r in u['rules']];time={'timestamp_format','parent_time_order'}
        rows.append(dict(case=case,condition=cond,structural_detected=int(any(r['findings'] for r in rr if r['rule'] not in time)),time_warning=int(any(r['findings'] for r in rr if r['rule'] in time)),json_html_detected=int(bool(cross['rules']['json_html_consistency']['findings'])),manifest_detected=int(bool(cross['rules']['manifest_inventory_size']['findings'])),incomplete=int(any(r['blocked'] for r in rr) or any(r['error'] for r in cross['rules'].values()))))
    with (out/'case_results.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    summary=[]
    for cond in dict.fromkeys(r['condition'] for r in rows):
        rs=[r for r in rows if r['condition']==cond];item=dict(condition=cond,cases=len(rs),**{k:sum(r[k] for r in rs) for k in list(rows[0])[2:]});summary.append(item);print(item)
    x.save_json(out/'condition_summary.json',summary)
    if src.read_bytes()!=raw:raise AssertionError('Input changed')
    (out/'COMPLETED.txt').write_text('Input unchanged. 36 derived variants plus one serialization control. No authenticity judgment.\n',encoding='utf-8')
    print('Output:',out.resolve())
XHASH='0854531580a8765a7d51eb5e0857dd8479134e274028fed17f95cc42e677aa3f'
if __name__=='__main__':main()
