"""Exploratory answer-position deletion; frozen v0.2, no reference repair."""
import argparse,copy,csv,hashlib,importlib.util,json
from pathlib import Path
from datetime import datetime,timezone
EXPECTED='71a54078a3b79d86027187267c07117fbec3928640bbd31f18079daf18bc744c'
def sha(b):return hashlib.sha256(b).hexdigest()
def dump(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('service',choices=['chatgpt','claude']);ap.add_argument('input');a=ap.parse_args()
 src=Path(a.input);raw=src.read_bytes();vp=Path(__file__).with_name('validate_exports.py')
 if sha(vp.read_bytes())!=EXPECTED:raise ValueError('Frozen validator hash mismatch. Do not replace it.')
 spec=importlib.util.spec_from_file_location('v02',vp);v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
 data=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=v.pairs_hook,parse_float=v.finite_float,parse_constant=v.reject_constant)
 titles=['EVAL-CGPT-01','EVAL-CGPT-02','EVAL-CGPT-03-R1'] if a.service=='chatgpt' else ['EVAL-CLAUDE-01','EVAL-CLAUDE-02','EVAL-CLAUDE-03']
 field='title' if a.service=='chatgpt' else 'name';base=v.validate(a.service,data);plans=[]
 for title in titles:
  ii=[i for i,c in enumerate(data) if c.get(field)==title]
  if len(ii)!=1:raise ValueError('Expected exactly one '+title)
  ci=ii[0];c=data[ci]
  if any(r['findings'] or r['blocked'] for r in base[ci]['rules']):raise ValueError('Baseline needs review: '+title)
  if a.service=='chatgpt':
   by=c['mapping'];parent={k:n.get('parent') for k,n in by.items()};roles={k:(n.get('message') or {}).get('author',{}).get('role') for k,n in by.items()};leaf=c['current_node']
  else:
   by={m['uuid']:m for m in c['chat_messages']};parent={k:m['parent_message_uuid'] for k,m in by.items()};roles={k:m['sender'] for k,m in by.items()};leaves=set(by)-set(parent.values())
   if len(leaves)!=1:raise ValueError('Expected single linear leaf: '+title)
   leaf=next(iter(leaves))
  chain=[];cur=leaf
  while cur in by:
   if cur in chain:raise ValueError('Cycle in baseline')
   chain.append(cur);cur=parent[cur]
  chain.reverse()
  if set(chain)!=set(by):raise ValueError('Expected linear baseline: '+title)
  answers=[k for k in chain if roles[k]=='assistant']
  if len(answers)!=3:raise ValueError('Expected three answers: '+title)
  for pos,k in zip(['first','middle','last'],answers):plans.append(dict(title=title,conversation_index=ci,position=pos,target_id=k))
 out=Path('results')/(a.service+'_position_eval_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));out.mkdir(parents=True,exist_ok=False)
 dump(out/'run_metadata.json',dict(service=a.service,source_sha256=sha(raw),validator_sha256=EXPECTED,script_sha256=sha(Path(__file__).read_bytes()),policy='Three normal linear EVAL conversations; first/middle/last assistant along parent chain. Delete only selected node/message; preserve all references including current_node. Full-file validation, target-only aggregation. Exploratory extension; not independent samples or blind evaluation.',authenticity_determination=False))
 dump(out/'selected_targets.json',plans);dump(out/'baseline_report.json',base);rows=[]
 for plan in plans:
  ci=plan['conversation_index'];k=plan['target_id'];d=copy.deepcopy(data);c=d[ci]
  if a.service=='chatgpt':removed=c['mapping'].pop(k);restored=copy.deepcopy(d);restored[ci]['mapping'][k]=removed
  else:
   mi=next(i for i,m in enumerate(c['chat_messages']) if m['uuid']==k);removed=c['chat_messages'].pop(mi);restored=copy.deepcopy(d);restored[ci]['chat_messages'].insert(mi,removed)
  assert restored==data,'Unexpected mutation'
  folder=out/(plan['title']+'_'+plan['position']);folder.mkdir();dump(folder/'variant.json',d)
  candidate=json.loads((folder/'variant.json').read_text(encoding='utf-8'));report=v.validate(a.service,candidate)
  assert all(report[i]==base[i] for i in range(len(data)) if i!=ci),'Outside-target report changed'
  dump(folder/'report.json',report);dump(folder/'mutation_record.json',dict(**plan,removed_record=removed,source_sha256=sha(raw),variant_sha256=sha((folder/'variant.json').read_bytes()),audit_passed=True))
  rr={r['rule']:r for r in report[ci]['rules']};tn={'timestamp_format','parent_time_order'}
  row=dict(case=folder.name,position=plan['position'],structural_detected=int(any(r['findings'] for n,r in rr.items() if n not in tn)),time_warning=int(any(rr[n]['findings'] for n in tn)),parent_reference=int(bool(rr['parent_reference']['findings'])),current_node_reference=int(bool(rr['current_node_reference']['findings'])),incomplete=int(any(r['blocked'] for r in rr.values())))
  rows.append(row)
 with (out/'case_results.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 summary=[]
 for pos in ['first','middle','last']:
  rs=[r for r in rows if r['position']==pos];s=dict(position=pos,cases=len(rs),**{k:sum(r[k] for r in rs) for k in ['structural_detected','time_warning','parent_reference','current_node_reference','incomplete']});summary.append(s);print(s)
 dump(out/'condition_summary.json',summary);assert src.read_bytes()==raw
 (out/'COMPLETED.txt').write_text('9 deletion variants from 3 conversations. Original unchanged. No authenticity determination.',encoding='utf-8');print('Output:',out.resolve())
if __name__=='__main__':main()
