"""ChatGPT archive cross-file consistency study; Python standard library only.
Does not execute HTML/JavaScript and never overwrites the supplied archive.
"""
import argparse
import copy
import csv
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

VERSION = '0.3.0-crossfile-1'
MARKER = re.compile(r'\bvar\s+jsonData\s*=\s*')

def pairs(items):
    d = {}
    for k, v in items:
        if k in d:
            raise ValueError('Duplicate JSON key: ' + k)
        d[k] = v
    return d

def reject(s):
    raise ValueError('Non-finite JSON number: ' + s)

def number(s):
    import math
    v = float(s)
    if not math.isfinite(v):
        raise ValueError('Non-finite JSON number')
    return v

DECODER = json.JSONDecoder(object_pairs_hook=pairs, parse_constant=reject, parse_float=number)

def parse(b):
    return json.loads(b.decode('utf-8-sig'), object_pairs_hook=pairs,
                      parse_constant=reject, parse_float=number)

def encode(d):
    return json.dumps(d, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')

def sha(b):
    return hashlib.sha256(b).hexdigest()

def read_archive(path):
    with zipfile.ZipFile(path) as z:
        names = [i.filename for i in z.infolist() if not i.is_dir()]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate ZIP member names')
        if sum(i.file_size for i in z.infolist()) > 100_000_000:
            raise ValueError('Archive exceeds this text-only prototype size limit')
        return {n: z.read(n) for n in names}

def html_data(b):
    s = b.decode('utf-8-sig')
    matches = list(MARKER.finditer(s))
    if len(matches) != 1:
        raise ValueError('Expected one jsonData declaration')
    start = matches[0].end()
    d, length = DECODER.raw_decode(s[start:])
    if not isinstance(d, list):
        raise ValueError('jsonData must be a list')
    return d, s, start, start + length

def pointer(p, key):
    return p + '/' + str(key).replace('~', '~0').replace('/', '~1')

def differences(a, b, p=''):
    out = []
    if type(a) is not type(b):
        return [{'path': p, 'left': a, 'right': b, 'kind': 'type_or_value'}]
    if isinstance(a, dict):
        for k in sorted(a.keys() | b.keys()):
            q = pointer(p, k)
            if k not in a or k not in b:
                out.append({'path': q, 'kind': 'missing_key', 'left_present': k in a,
                            'right_present': k in b, 'left': a.get(k), 'right': b.get(k)})
            else:
                out.extend(differences(a[k], b[k], q))
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append({'path': p, 'kind': 'array_length', 'left': len(a), 'right': len(b)})
        for i, (x, y) in enumerate(zip(a, b)):
            out.extend(differences(x, y, pointer(p, i)))
    elif a != b:
        out.append({'path': p, 'kind': 'value', 'left': a, 'right': b})
    return out

def validate(files):
    """Input-only validation: no original, mutation manifest or expected label."""
    report = {'version': VERSION, 'rules': {}, 'authenticity_determination': False}
    def result(name, checked, findings, error=None):
        report['rules'][name] = {'status': 'incomplete' if error else
            ('inconsistency_found' if findings else 'no_inconsistency_found'),
            'checked': checked, 'findings': findings, 'error': error}
    try:
        d = parse(files['conversations.json'])
        if not isinstance(d, list):
            raise ValueError('conversations.json must be a list')
        h, _, _, _ = html_data(files['chat.html'])
        result('json_html_consistency', len(d), differences(d, h))
    except (KeyError, ValueError, UnicodeError) as e:
        result('json_html_consistency', 0, [], str(e))
    try:
        m = parse(files['export_manifest.json'])
        rows = m['export_files']
        if not isinstance(rows, list):
            raise ValueError('export_files must be a list')
        seen, findings = set(), []
        for row in rows:
            n, size = row['path'], row['size_bytes']
            if not isinstance(n, str) or type(size) is not int or size < 0 or n in seen:
                raise ValueError('Invalid or duplicate manifest entry')
            seen.add(n)
            if n not in files:
                findings.append({'path': n, 'kind': 'missing_file'})
            elif len(files[n]) != size:
                findings.append({'path': n, 'kind': 'size_mismatch',
                                 'recorded': size, 'actual': len(files[n])})
        for n in sorted(set(files) - seen - {'export_manifest.json'}):
            findings.append({'path': n, 'kind': 'unlisted_file'})
        result('manifest_inventory_size', len(rows), findings)
    except (KeyError, ValueError, TypeError, UnicodeError) as e:
        result('manifest_inventory_size', 0, [], str(e))
    return report

def update_sizes(files):
    m = parse(files['export_manifest.json'])
    for r in m['export_files']:
        r['size_bytes'] = len(files[r['path']])
    files['export_manifest.json'] = encode(m)

def save_json(path, obj):
    path.write_bytes(encode(obj))

def write_zip(path, files):
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)

def is_clean(report):
    return all(r['status'] == 'no_inconsistency_found' for r in report['rules'].values())

def run(args):
    src = Path(args.archive).resolve()
    original_hash = sha(src.read_bytes())
    files = read_archive(src)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    dest = Path(args.output) / ('chatgpt_crossfile_' + args.command + '_' + stamp)
    dest.mkdir(parents=True, exist_ok=False)
    base = validate(files)
    save_json(dest / 'baseline.json', base)
    save_json(dest / 'inventory.json', [{'path': n, 'bytes': len(b), 'sha256': sha(b)} for n,b in files.items()])
    save_json(dest / 'run_metadata.json', {'version': VERSION, 'source': str(src),
        'source_sha256': original_hash, 'script_sha256': sha(Path(__file__).read_bytes()),
        'python': sys.version, 'utc': stamp, 'mode': args.command,
        'scope': 'Parsed JSON and embedded HTML data; manifest paths and uncompressed byte sizes. No HTML rendering, authenticity or v0.2 structural checks.'})
    if args.command == 'validate':
        for n,r in base['rules'].items():
            print(n, r['status'], 'findings=' + str(len(r['findings'])))
    else:
        if not is_clean(base):
            raise ValueError('Baseline not clean; inspect baseline report before experimentation')
        data = parse(files['conversations.json'])
        selection = []
        for i,c in enumerate(data):
            if not re.fullmatch(r'EVAL-CGPT-(?:01|02|03-R1|0[4-9])', c.get('title','')):
                continue
            candidates = []
            for key,node in c['mapping'].items():
                msg = node.get('message')
                if not msg or msg.get('author',{}).get('role') != 'assistant':
                    continue
                parts = msg.get('content',{}).get('parts',[])
                if parts and isinstance(parts[0],str) and parts[0]:
                    t = msg.get('create_time')
                    if type(t) in (int,float):
                        candidates.append((t,key,parts[0]))
            if not candidates:
                raise ValueError('No eligible answer: ' + c['title'])
            _,key,before = sorted(candidates)[0]
            selection.append({'conversation_index': i, 'title': c['title'],
                'node_id': key, 'before': before,
                'after': before + '\n[연구용 변경] 회의 장소는 Z회의실입니다.'})
        if len(selection) != 9 or len({s['title'] for s in selection}) != 9:
            raise ValueError('Expected the nine unique predefined EVAL titles')
        save_json(dest / 'selection.json', selection)
        rows = []
        conditions = ['C0_reserialize', 'X1_json_only_sizes_updated',
                      'X2_both_sizes_stale', 'X3_both_sizes_updated']
        for sel in selection:
            for condition in conditions:
                if condition == 'C0_reserialize' and sel is not selection[0]:
                    continue
                case = sel['title'] + '_' + condition
                folder = dest / case
                folder.mkdir()
                changed = dict(files)
                d = copy.deepcopy(data)
                if condition != 'C0_reserialize':
                    d[sel['conversation_index']]['mapping'][sel['node_id']]['message']['content']['parts'][0] = sel['after']
                delta = differences(data,d)
                expected_path = '/' + str(sel['conversation_index']) + '/mapping/' + sel['node_id'] + '/message/content/parts/0'
                if condition == 'C0_reserialize':
                    assert not delta
                else:
                    assert len(delta) == 1 and delta[0]['path'] == expected_path
                changed['conversations.json'] = encode(d)
                if condition.startswith(('X2_', 'X3_')):
                    _,text,start,end = html_data(files['chat.html'])
                    changed['chat.html'] = (text[:start] + json.dumps(d,ensure_ascii=True,allow_nan=False) + text[end:]).encode('utf-8')
                if condition != 'X2_both_sizes_stale':
                    update_sizes(changed)
                variant = folder / 'variant.zip'
                write_zip(variant, changed)
                reopened = read_archive(variant)
                assert reopened == changed
                report = validate(reopened)
                save_json(folder / 'report.json', report)
                save_json(folder / 'mutation_record.json', {'case':case,'condition':condition,
                    'source_sha256':original_hash,'variant_sha256':sha(variant.read_bytes()),
                    'semantic_changes':delta,'changed_files':[{'path':n,'before_sha256':sha(files[n]),
                    'after_sha256':sha(b),'before_bytes':len(files[n]),'after_bytes':len(b)}
                    for n,b in changed.items() if b != files[n]], 'audit_passed':True})
                a=report['rules']['json_html_consistency'];b=report['rules']['manifest_inventory_size']
                rows.append({'case':case,'condition':condition,'conversation':sel['title'],
                    'json_html_status':a['status'],'json_html_findings':len(a['findings']),
                    'manifest_status':b['status'],'manifest_findings':len(b['findings'])})
        with (dest/'case_results.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        summary=[]
        for cond in conditions:
            group=[r for r in rows if r['condition']==cond]
            row={'condition':cond,'cases':len(group),
                'json_html_detected':sum(r['json_html_status']=='inconsistency_found' for r in group),
                'manifest_detected':sum(r['manifest_status']=='inconsistency_found' for r in group),
                'incomplete':sum('incomplete' in (r['json_html_status'],r['manifest_status']) for r in group)}
            summary.append(row);print(row)
        save_json(dest/'condition_summary.json',summary)
    assert original_hash == sha(src.read_bytes()), 'Input archive changed'
    (dest/'COMPLETED.txt').write_text('Completed. Input unchanged. No authenticity judgment.\n',encoding='utf-8')
    print('Version:',VERSION);print('Output:',dest.resolve())

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['validate','experiment'])
    p.add_argument('archive')
    p.add_argument('--output',default='results')
    try:
        run(p.parse_args())
    except Exception as e:
        print('STOP:',type(e).__name__,str(e),file=sys.stderr)
        sys.exit(1)
