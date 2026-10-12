"""Local, offline attachment consistency experiment. Python standard library only.
Original ZIP is read-only. Output variant.zip files KEEP ALL PERSONAL DATA:
do not upload them. Reports contain only selected research attachment records.
Scope: attachment/library/manifest/file relationships, NOT chat.html parity,
message structure, authenticity, or PDF semantic integrity.
"""
import argparse
import copy
import csv
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
import zipfile

VERSION = '0.3.0-chatgpt-attachments-1'
TITLES = ('SUP-CGPT-04', 'SUP-CGPT-05', 'SUP-CGPT-06')
EXPECTED_SOURCE = 'c0f1878ede05547b1db84c32ff6cd441267055ed5fd273da9592179f627a43a8'
RULES = ('attachment_file_exists', 'library_reference', 'metadata_agreement',
         'attachment_size', 'library_size', 'manifest_size')

def sha(b):
    return hashlib.sha256(b).hexdigest()

def encode(x):
    return (json.dumps(x, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf-8')

def decode(b):
    def pairs(xs):
        d = {}
        for k,v in xs:
            if k in d: raise ValueError('Duplicate JSON key')
            d[k] = v
        return d
    return json.loads(b.decode('utf-8-sig'), object_pairs_hook=pairs)

def dump(p,x):
    p.write_bytes(encode(x))

def lid(row):
    v = row.get('id')
    return v.get('id') if isinstance(v,dict) else v

def title(c):
    return c.get('title','').strip().strip('[]')

def documents(files):
    # Exact root paths: sites/export_manifest.json is a different document.
    return (decode(files['conversations.json']), decode(files['library_files.json']),
            decode(files['export_manifest.json']))

def selected(data):
    out=[]
    for t in TITLES:
        hits=[c for c in data if title(c)==t]
        if len(hits)!=1: raise ValueError('Expected exactly one '+t)
        c=hits[0]
        for nodeid,node in c['mapping'].items():
            m=node.get('message') or {}
            for i,a in enumerate((m.get('metadata') or {}).get('attachments',[])):
                out.append({'title':t,'node_id':nodeid,'attachment_index':i,
                            'attachment':a,'path':a['id']+'.dat'})
    if len(out)!=4: raise ValueError('Expected four research attachments')
    return out

def validate(files):
    data,library,manifest=documents(files)
    entries=manifest['export_files']
    rules={k:{'checked':0,'blocked':0,'findings':[]} for k in RULES}
    def check(k, ok, target, detail):
        rules[k]['checked']+=1
        if not ok: rules[k]['findings'].append({'title':target['title'],'path':target['path'],'detail':detail})
    for t in selected(data):
        a=t['attachment']; path=t['path']; exists=path in files
        check('attachment_file_exists',exists,t,'referenced member missing')
        rs=[r for r in library if r.get('file_id')==a['id']]
        good=len(rs)==1 and lid(rs[0])==a.get('library_file_id')
        check('library_reference',good,t,'file_id/library_file_id match is not unique or is inconsistent')
        if good:
            r=rs[0]
            for ak,rk in [('name','file_name'),('mime_type','mime_type'),('size','file_size_bytes')]:
                check('metadata_agreement',ak in a and rk in r and a[ak]==r[rk],t,ak+' differs between conversation and library')
        else:
            rules['metadata_agreement']['blocked']+=3
        es=[e for e in entries if e.get('path')==path]
        for rule,expected in [('attachment_size',a.get('size')),
                               ('library_size',rs[0].get('file_size_bytes') if good else None),
                               ('manifest_size',es[0].get('size_bytes') if len(es)==1 else None)]:
            if not exists:
                rules[rule]['blocked']+=1
            elif type(expected) is not int:
                check(rule,False,t,'missing, ambiguous or noninteger size reference')
            else:
                check(rule,len(files[path])==expected,t,{'recorded':expected,'actual':len(files[path])})
    for r in rules.values():
        r['status']='inconsistency_found' if r['findings'] else ('incomplete' if r['blocked'] else 'no_inconsistency_found')
    return {'version':VERSION,'scope':'four research attachments only; HTML/message structure excluded',
            'rules':rules,'authenticity_determination':False}

def changes(before,after):
    return [{'path':p,'before_bytes':len(before[p]) if p in before else None,
             'after_bytes':len(after[p]) if p in after else None,
             'before_sha256':sha(before[p]) if p in before else None,
             'after_sha256':sha(after[p]) if p in after else None}
            for p in sorted(set(before)|set(after)) if before.get(p)!=after.get(p)]

def writezip(p, files):
    with zipfile.ZipFile(p,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for n,b in files.items(): z.writestr(n,b)

def experiment(files, out, source_hash):
    data,library,manifest=documents(files)
    targets=selected(data)
    txt=[t for t in targets if t['attachment']['mime_type']=='text/plain']
    if len(txt)!=1: raise ValueError('Expected one TXT attachment for content changes')
    text_target=txt[0]; path=text_target['path']
    # Exact semantic replacement with identical UTF-8 byte length.
    old='장소: A회의실'.encode(); new='장소: Z회의실'.encode()
    if files[path].count(old)!=1 or len(old)!=len(new):
        raise ValueError('Expected unique equal-byte TXT replacement')
    plans=[('C0_repack',None)]+[('A1_file_delete',t) for t in targets]+[
        ('A2_txt_append_sizes_stale',text_target),('A3_txt_equal_bytes',text_target),
        ('A4_txt_append_all_sizes_updated',text_target)]
    results=[]
    for num,(condition,t) in enumerate(plans):
        variant=dict(files); ops=[]
        if condition=='A1_file_delete':
            del variant[t['path']]; ops=[{'kind':'delete_member','path':t['path']}]
        elif condition.startswith(('A2_','A4_')):
            variant[path]=files[path]+'\n[연구용 변경] 회의 장소는 Z회의실입니다.\n'.encode()
            ops=[{'kind':'append_text','path':path,'added_text':'[연구용 변경] 회의 장소는 Z회의실입니다.'}]
            if condition.startswith('A4_'):
                d=copy.deepcopy(data); lib=copy.deepcopy(library); man=copy.deepcopy(manifest)
                target=next(x for x in selected(d) if x['path']==path)
                target['attachment']['size']=len(variant[path])
                row=next(r for r in lib if r.get('file_id')==t['attachment']['id'])
                row['file_size_bytes']=len(variant[path])
                variant['conversations.json']=encode(d)
                variant['library_files.json']=encode(lib)
                # Keep every other manifest field, update sizes of these three members.
                for e in man['export_files']:
                    if e.get('path') in (path,'conversations.json','library_files.json'):
                        e['size_bytes']=len(variant[e['path']])
                variant['export_manifest.json']=encode(man)
                ops.append({'kind':'update_related_sizes','fields':['attachment.size','library.file_size_bytes','manifest.size_bytes'],
                            'note':'chat.html deliberately unchanged and outside this attachment validator scope'})
        elif condition=='A3_txt_equal_bytes':
            variant[path]=files[path].replace(old,new)
            ops=[{'kind':'equal_byte_text_replace','path':path,'before':old.decode(),'after':new.decode()}]
        folder=out/(str(num).zfill(2)+'_'+condition+('_'+t['title'] if t else ''))
        folder.mkdir()
        zp=folder/'variant.zip'; writezip(zp,variant)
        # Validate persisted output, not just in-memory object.
        with zipfile.ZipFile(zp) as z: saved={n:z.read(n) for n in z.namelist()}
        assert saved==variant, 'ZIP round-trip failure'
        report=validate(saved); diff=changes(files,saved)
        allowed=set() if condition=='C0_repack' else {t['path']}
        if condition.startswith('A4_'): allowed|={'conversations.json','library_files.json','export_manifest.json'}
        assert {r['path'] for r in diff}==allowed, 'Unexpected changed members'
        if condition=='A3_txt_equal_bytes': assert len(saved[path])==len(files[path]) and saved[path]!=files[path]
        dump(folder/'mutation_record.json',{'condition':condition,'target':t,'operations':ops,'changed_files':diff,
            'source_sha256':source_hash,'variant_sha256':sha(zp.read_bytes()),'changed_member_audit_passed':True})
        dump(folder/'report.json',report)
        row={'case':folder.name,'condition':condition,'target':t['title'] if t else '',
             'incomplete_any':int(any(r['blocked'] for r in report['rules'].values()))}
        row.update({k:int(bool(report['rules'][k]['findings'])) for k in RULES})
        results.append(row)
    with (out/'case_results.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(results[0])); w.writeheader(); w.writerows(results)
    summaries=[]
    for condition in dict.fromkeys(r['condition'] for r in results):
        rs=[r for r in results if r['condition']==condition]
        s={'condition':condition,'cases':len(rs),'detected':sum(any(r[k] for k in RULES) for r in rs),
           'incomplete_any':sum(r['incomplete_any'] for r in rs)}
        s.update({k:sum(r[k] for r in rs) for k in RULES}); summaries.append(s); print(s)
    dump(out/'condition_summary.json',summaries)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('mode',choices=['validate','experiment'])
    ap.add_argument('archive',type=Path)
    args=ap.parse_args(); raw=args.archive.read_bytes(); source_hash=sha(raw)
    if source_hash!=EXPECTED_SOURCE:
        raise ValueError('Source SHA-256 differs from the reviewed official paid SUP archive. Stop and check input; do not change this guard.')
    with zipfile.ZipFile(args.archive) as z:
        names=z.namelist()
        if len(names)!=len(set(names)): raise ValueError('Duplicate ZIP member names')
        files={n:z.read(n) for n in names}
    baseline=validate(files)
    if any(r['findings'] or r['blocked'] for r in baseline['rules'].values()):
        print(json.dumps(baseline,ensure_ascii=False,indent=2)); raise ValueError('Baseline needs review; experiments not run')
    out=Path('results')/('chatgpt_attachment_'+args.mode+'_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    dump(out/'baseline_report.json',baseline)
    dump(out/'run_metadata.json',{'version':VERSION,'mode':args.mode,'source_sha256':source_hash,
        'script_sha256':sha(Path(__file__).read_bytes()),'selected_titles':TITLES,
        'personal_data_warning':'Variant ZIPs retain the entire local original. Do not upload.',
        'limitations':['No HTML parity check','No message structural validation','No authenticity judgment',
                      'Content mutations are TXT-only; PDF targets tested for deletion only',
                      'Stored digest fields were null in four observed library records']})
    if args.mode=='experiment': experiment(files,out,source_hash)
    else:
        for k,r in baseline['rules'].items(): print(k,r['status'],'checked=',r['checked'],'blocked=',r['blocked'],'findings=',len(r['findings']))
    assert sha(args.archive.read_bytes())==source_hash,'Source changed during run'
    (out/'COMPLETED.txt').write_text('Completed. Original unchanged. Not an authenticity determination.\n',encoding='utf-8')
    print('Version:',VERSION); print('Output:',out.resolve()); print('Original unchanged. No files uploaded.')

if __name__=='__main__':
    try: main()
    except (ValueError,KeyError,AssertionError,FileNotFoundError,zipfile.BadZipFile) as e:
        print('STOP:',type(e).__name__,str(e)); sys.exit(1)
