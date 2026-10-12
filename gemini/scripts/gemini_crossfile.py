"""Observed Gemini Takeout attachment profile; no authenticity determination."""
import argparse, copy, csv, hashlib, json, posixpath, re, sys, zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
VERSION = '0.3.0-gemini-attachments-1'
def sha(b): return hashlib.sha256(b).hexdigest()
def strict(data):
    def pairs(p):
        d={}
        for k,v in p:
            if k in d: raise ValueError('Duplicate JSON key')
            d[k]=v
        return d
    return json.loads(data, object_pairs_hook=pairs, parse_constant=lambda s: (_ for _ in ()).throw(ValueError('Nonfinite number')))
def load(path):
    with zipfile.ZipFile(path) as z:
        infos=[i for i in z.infolist() if not i.is_dir()]
        names=[i.filename for i in infos]
        if len(names)!=len(set(names)): raise ValueError('Duplicate archive member')
        if sum(i.file_size for i in infos)>100*1024*1024: raise ValueError('Archive exceeds 100 MiB profile limit')
        return {i.filename:z.read(i) for i in infos}
def locate(files):
    names=[]
    for n,b in files.items():
        if n.endswith('.json'):
            try:d=strict(b)
            except Exception:continue
            if isinstance(d,list) and d and all(isinstance(x,dict) for x in d) and any('attachedFiles' in x for x in d):names.append(n)
    if len(names)!=1:raise ValueError('Expected one activity JSON containing attachedFiles')
    return names[0]
def encode(d):return json.dumps(d,ensure_ascii=False,indent=2).encode('utf-8')
def rule():return dict(status='no_inconsistency_found',checked=0,findings=[],blocked=0)
def validate(files):
    n=locate(files);d=strict(files[n]);base=posixpath.dirname(n)
    exists=rule();agree=rule();count=0
    for i,a in enumerate(d):
        refs=a.get('attachedFiles')
        if refs is None:continue
        count+=1
        if not isinstance(refs,list) or not all(isinstance(r,str) for r in refs):
            exists['blocked']+=1;agree['blocked']+=1;continue
        subtitles=a.get('subtitles',[])
        if not isinstance(subtitles,list) or not all(isinstance(s,dict) for s in subtitles):agree['blocked']+=1
        else:
            # This observed profile uses relative subtitles.url for attachment links.
            urls=[s['url'] for s in subtitles if isinstance(s.get('url'),str) and not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',s['url'])]
            agree['checked']+=1
            if Counter(refs)!=Counter(urls):agree['findings'].append(dict(activity_index=i,attachedFiles=refs,subtitle_urls=urls))
        for ref in refs:
            if not ref or ref.startswith('/') or '\\' in ref or '..' in ref.split('/') or re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',ref):
                exists['blocked']+=1;continue
            exists['checked']+=1
            target=posixpath.join(base,ref)
            if target not in files:exists['findings'].append(dict(activity_index=i,reference=ref,archive_path=target))
    for r in [exists,agree]:
        r['status']='inconsistency_found' if r['findings'] else 'incomplete' if r['blocked'] else 'no_eligible_data' if not r['checked'] else 'no_inconsistency_found'
    return dict(version=VERSION,json_member=n,activities=len(d),attachment_activities=count,rules=dict(attachment_reference_exists=exists,attachment_reference_agreement=agree),authenticity_determination=False)
def dump(path,d):path.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
def writezip(path,files):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for n,b in files.items():z.writestr(n,b)
def experiment(files,out):
    n=locate(files);data=strict(files[n]);base=posixpath.dirname(n)
    selected=[]
    for tag in ['SUP-GEMINI-04','SUP-GEMINI-05','SUP-GEMINI-06']:
        indexes=[i for i,a in enumerate(data) if tag in a.get('title','') and a.get('attachedFiles')]
        if len(indexes)!=1:raise ValueError('Expected one tagged attachment activity: '+tag)
        i=indexes[0];ref=data[i]['attachedFiles'][0]
        selected.append(dict(tag=tag,activity_index=i,reference=ref))
    dump(out/'selected_targets.json',selected)
    rows=[]
    def run(case,condition,variant,changes):
        folder=out/case;folder.mkdir()
        path=folder/'variant.zip';writezip(path,variant)
        reopened=load(path)
        if reopened!=variant:raise AssertionError('Archive round trip differs')
        report=validate(reopened);dump(folder/'report.json',report)
        changed=[dict(path=k,before_sha256=sha(files[k]) if k in files else None,after_sha256=sha(variant[k]) if k in variant else None) for k in sorted(set(files)|set(variant)) if files.get(k)!=variant.get(k)]
        dump(folder/'mutation_record.json',dict(condition=condition,changes=changes,changed_files=changed,variant_sha256=sha(path.read_bytes())))
        rows.append(dict(case=case,condition=condition,reference_exists_findings=len(report['rules']['attachment_reference_exists']['findings']),reference_agreement_findings=len(report['rules']['attachment_reference_agreement']['findings']),incomplete=any(r['blocked'] for r in report['rules'].values())))
    v=dict(files);v[n]=encode(data);run('C0_reserialize','C0_reserialize',v,[])
    for sel in selected:
        i=sel['activity_index'];ref=sel['reference'];target=posixpath.join(base,ref)
        if target not in files:raise ValueError('Missing baseline target')
        for condition in ['A1_file_delete','A2_one_reference_change','A3_both_references_missing','A4_consistent_rename']:
            v=dict(files);d=copy.deepcopy(data);changes=[]
            new='research_renamed_'+ref
            if posixpath.join(base,new) in files:raise ValueError('New filename collision')
            if condition=='A1_file_delete':del v[target];changes=[dict(kind='delete_member',path=target)]
            else:
                d[i]['attachedFiles'][0]=new
                changes.append(dict(path=f'/{i}/attachedFiles/0',before=ref,after=new))
                if condition in ['A3_both_references_missing','A4_consistent_rename']:
                    found=0
                    for j,s in enumerate(d[i].get('subtitles',[])):
                        if s.get('url')==ref:
                            s['url']=new;found+=1;changes.append(dict(path=f'/{i}/subtitles/{j}/url',before=ref,after=new))
                    if found!=1:raise ValueError('Expected one subtitle reference')
                v[n]=encode(d)
                if condition=='A4_consistent_rename':v[posixpath.join(base,new)]=v.pop(target);changes.append(dict(kind='rename_member',before=target,after=posixpath.join(base,new)))
            run(sel['tag']+'_'+condition,condition,v,changes)
        if ref.endswith('.txt'):
            v=dict(files);v[target]=files[target]+ '\n[연구용 변경] 회의 장소는 Z회의실입니다.'.encode('utf-8')
            run(sel['tag']+'_A5_content_edit','A5_content_edit',v,[dict(kind='append_text',path=target)])
    with (out/'case_results.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    summary=[]
    for condition in dict.fromkeys(r['condition'] for r in rows):
        rr=[r for r in rows if r['condition']==condition]
        item=dict(condition=condition,cases=len(rr),reference_exists_detected=sum(r['reference_exists_findings']>0 for r in rr),reference_agreement_detected=sum(r['reference_agreement_findings']>0 for r in rr),incomplete=sum(r['incomplete'] for r in rr));summary.append(item);print(item)
    dump(out/'condition_summary.json',summary)
def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['validate','experiment']);p.add_argument('archive');p.add_argument('--out');a=p.parse_args()
    src=Path(a.archive);source=src.read_bytes();files=load(src)
    out=Path(a.out) if a.out else Path('results')/('gemini_crossfile_'+a.mode+'_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True,exist_ok=False)
    baseline=validate(files);dump(out/'baseline_report.json',baseline)
    dump(out/'run_metadata.json',dict(version=VERSION,source_sha256=sha(source),script_sha256=sha(Path(__file__).read_bytes()),python=sys.version,inventory=[dict(path=k,size_bytes=len(b),sha256=sha(b)) for k,b in files.items()]))
    if a.mode=='experiment':
        if any(r['status']!='no_inconsistency_found' for r in baseline['rules'].values()):raise ValueError('Baseline not fully consistent')
        experiment(files,out)
    else:
        for k,r in baseline['rules'].items():print(k,r['status'],'checked=',r['checked'],'findings=',len(r['findings']))
    if src.read_bytes()!=source:raise AssertionError('Source modified')
    (out/'COMPLETED.txt').write_text('Source unchanged. Findings do not establish authenticity.\n',encoding='utf-8');print('Output:',out.resolve())
if __name__=='__main__':main()
