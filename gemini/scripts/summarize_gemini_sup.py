"""URL associations only: shared activities/HTML are not attributed to one conversation."""
import argparse,json,re,hashlib
from pathlib import Path
from datetime import datetime,timezone
TAGS=[f'SUP-GEMINI-{i:02d}' for i in range(1,7)]
def urls(a):
 return sorted({x['url'] for x in a.get('details',[]) if isinstance(x,dict) and isinstance(x.get('url'),str) and re.fullmatch(r'https://gemini\.google\.com/app/[A-Za-z0-9_-]+/?',x['url'])})
def main():
 ap=argparse.ArgumentParser();ap.add_argument('input');args=ap.parse_args();p=Path(args.input);raw=p.read_bytes();data=json.loads(raw.decode('utf-8-sig'));mapping={}
 for tag in TAGS:
  seeds=[(i,a) for i,a in enumerate(data) if '['+tag+']' in a.get('title','')]
  if len(seeds)!=1:raise ValueError('Expected one tag anchor: '+tag)
  us=urls(seeds[0][1])
  if len(us)!=1:raise ValueError('Anchor has ambiguous URL: '+tag)
  mapping[tag]=us[0]
 if len(set(mapping.values()))!=6:raise ValueError('Anchor URLs not unique')
 records=[]
 for i,a in enumerate(data):
  us=urls(a);tags=[t for t in TAGS if mapping[t] in us]
  if not tags:continue
  records.append(dict(activity_index=i,associated_tags=tags,url_count=len(us),exclusive=len(us)==1,time=a.get('time'),response_html_items=len(a.get('safeHtmlItem',[])),attachment_references=a.get('attachedFiles',[]),title=a.get('title')))
 summary=[]
 for tag in TAGS:
  rs=[r for r in records if tag in r['associated_tags']];exclusive=[r for r in rs if r['exclusive']]
  s=dict(tag=tag,associated_activities=len(rs),exclusive_activities=len(exclusive),shared_activities=len(rs)-len(exclusive),exclusive_response_html_items=sum(r['response_html_items'] for r in exclusive));summary.append(s);print(s)
 totals=dict(all_export_activities=len(data),sup_related_unique_activities=len(records),exclusive_activities=sum(r['exclusive'] for r in records),shared_activities=sum(not r['exclusive'] for r in records),sup_related_response_html_items=sum(r['response_html_items'] for r in records))
 out=Path('results')/('gemini_sup_inventory_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));out.mkdir(parents=True,exist_ok=False)
 report=dict(version='1.0.0',input_sha256=hashlib.sha256(raw).hexdigest(),script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),anchors=mapping,summary=summary,totals=totals,activities=records,limitations=['Per-scenario associated activity counts overlap; do not sum them as unique records.','No positional mapping between details URLs and safeHtmlItem is assumed.','Activity time is not assigned to every associated message or conversation.','This inventory does not establish preservation of every UI edit/regeneration or completeness.'])
 (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 if p.read_bytes()!=raw:raise AssertionError('Input changed')
 print('Totals:',totals);print('Output:',out.resolve())
if __name__=='__main__':main()
