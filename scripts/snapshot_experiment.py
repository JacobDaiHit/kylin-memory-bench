#!/usr/bin/env python3
"""Archive the exact implementation used by a recorded run, without any workspaces."""
import argparse,hashlib,json,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kylin_memory_bench.common import digest,read_json
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    code={f.name:f.read_text(encoding='utf-8') for f in sorted((args.source/'kylin_memory_bench').glob('*.py'))}
    fingerprint=digest(code)
    if fingerprint!=read_json(args.manifest)['implementation_sha256']:
        raise SystemExit('Source fingerprint does not match the experiment manifest.')
    entries={}
    for f in args.source.rglob('*'):
        if not f.is_file() or '__pycache__' in f.parts: continue
        if f.is_symlink(): raise SystemExit('Source snapshot must not contain symlinks.')
        if f.suffix in ('.py','.json','.jsonl') and not f.name.endswith('.local.json'):
            entries[f.relative_to(args.source).as_posix()]=f.read_bytes()
    entries['LICENSE']=(ROOT/'LICENSE').read_bytes()
    metadata={'implementation_sha256':fingerprint,
              'files':{n:hashlib.sha256(b).hexdigest() for n,b in sorted(entries.items())},
              'purpose':'Frozen implementation for the two openKylin live suites; no model credentials or mutable workspaces.'}
    entries['SNAPSHOT.json']=(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n').encode()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(args.output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for n,b in sorted(entries.items()):
            info=zipfile.ZipInfo('experiment-source-0.2.0/'+n,(2026,10,3,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
            archive.writestr(info,b)
    print(json.dumps({'implementation_sha256':fingerprint,'archive_sha256':hashlib.sha256(args.output.read_bytes()).hexdigest(),'files':len(entries)},indent=2))
if __name__=='__main__':main()
