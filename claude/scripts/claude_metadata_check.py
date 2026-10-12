"""Observed Claude two-archive account-reference profile; not body authentication."""
import argparse,hashlib,json,zipfile
from pathlib import Path
from datetime import datetime,timezone
VERSION='0.1.0-claude-metadata'
def sha(b):return hashlib.sha256(b).hexdigest()
def load(p):
 with zipfile.ZipFile(p) as z:
  ns=[i.filename for i in z.infolist() if not i.is_dir()]
  if len(ns)!=len(set(ns)):raise ValueError('Duplicate ZIP paths')
  if sum(i.file_size for i in z.infolist())>100_000_000:raise ValueError('Archive too large for profile')
  return {n:z.read(n) for n in ns}
def member(files,name):
 ns=[n for n in files if n.rsplit('/',1)[-1]==name]
 if len(ns)!=1:raise ValueError('Expected one '+name)
 return json.loads(files[ns[0]].decode('utf-8-sig'))
def check(records,get_id,users):
 r=dict(checked=0,blocked=0,findings=[])
 for i,item in enumerate(records):
  key=get_id(item)
  if not isinstance(key,str) or not key:r['blocked']+=1;continue
  r['checked']+=1
  if sum(u.get('uuid')==key for u in users)!=1:r['findings'].append(dict(record_index=i,reason='account_reference_not_uniquely_resolved'))
 r['status']='inconsistency_found' if r['findings'] else 'incomplete' if r['blocked'] else 'no_inconsistency_found' if r['checked'] else 'no_eligible_data'
 return r

def main():
 p=argparse.ArgumentParser();p.add_argument('conversations_zip');p.add_argument('metadata_zip');a=p.parse_args()
 paths=[Path(a.conversations_zip),Path(a.metadata_zip)];raw=[x.read_bytes() for x in paths];cfiles,mfiles=[load(x) for x in paths]
 cs=member(cfiles,'conversations.json');users=member(mfiles,'users.json');events=member(mfiles,'login_history.json')['login_events']
 if not all(isinstance(v,list) and all(isinstance(x,dict) for x in v) for v in [cs,users,events]):raise ValueError('Unexpected record shape')
 rules=dict(conversation_account_reference=check(cs,lambda x:(x.get('account') or {}).get('uuid'),users),login_account_reference=check(events,lambda x:x.get('account_uuid'),users))
 profile=[]
 for c in cs:
  ms=c.get('chat_messages',[])
  profile.append(dict(title=c.get('name'),messages=len(ms),attachment_entries=sum(len(m.get('attachments',[])) for m in ms),file_entries=sum(len(m.get('files',[])) for m in ms)))
 out=Path('results')/('claude_metadata_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));out.mkdir(parents=True,exist_ok=False)
 report=dict(version=VERSION,rules=rules,conversations=profile,inventory=[dict(archive_role=role,path=n,size_bytes=len(b),sha256=sha(b)) for role,fs in [('conversations',cfiles),('metadata',mfiles)] for n,b in fs.items()],source_sha256=[sha(b) for b in raw],script_sha256=sha(Path(__file__).read_bytes()),scope='Account reference resolution only. No conversation-to-login session attribution. No attachment content or body authenticity validation.',authenticity_determination=False)
 (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 for name,r in rules.items():print(name,r['status'],'checked=',r['checked'],'blocked=',r['blocked'],'findings=',len(r['findings']))
 for path,b in zip(paths,raw):
  if path.read_bytes()!=b:raise AssertionError('Input changed')
 print('Output:',out.resolve());print('Inputs unchanged. Account consistency only; no authenticity judgment.')
if __name__=='__main__':main()
