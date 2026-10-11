#!/usr/bin/env python3
"""Read-only environment provenance collector; never reads model credentials."""
import argparse
import datetime
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kylin_memory_bench.runner import platform_info
def command(args):
    try:
        result=subprocess.run(args,capture_output=True,text=True,timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'command':args,'exit_code':None,'error':str(exc)}
    return {'command':args,'exit_code':result.returncode,'stdout':result.stdout.strip(),'stderr':result.stderr.strip()}
def git_revision(root):
    gitdir=Path(root)/'.git'
    try:
        head=(gitdir/'HEAD').read_text().strip()
        if head.startswith('ref: '):
            ref=head[5:]
            if '..' in Path(ref).parts or Path(ref).is_absolute(): return None
            loose=gitdir/ref
            if loose.is_file(): return loose.read_text().strip()
            for line in (gitdir/'packed-refs').read_text().splitlines():
                if line.endswith(' '+ref): return line.split()[0]
            return None
        return head
    except OSError:
        return None

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--runtime-base',type=Path,required=True)
    p.add_argument('--rootfs',type=Path)
    args=p.parse_args()
    info=platform_info()
    if not info['is_openkylin']: raise SystemExit('Run this collector inside actual openKylin.')
    data={'recorded_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'platform':info,
          'processor':platform.processor(),'sqlite':__import__('sqlite3').sqlite_version,
          'rootfs_source':{'url':'https://gitee.com/openkylin/openkylin-wsl.git','commit':None}}
    # The rootfs commit is independently checked below where git metadata exists.
    if args.rootfs:
        data['rootfs_source']['sha256']=hashlib.sha256(args.rootfs.read_bytes()).hexdigest()
        data['rootfs_source']['bytes']=args.rootfs.stat().st_size
        data['rootfs_source']['commit']=git_revision(args.rootfs.parent)
    packages=['python3','sqlite3','libc6','libzstd1','ukui-desktop-environment-core','ukui-session-manager','ukui-panel','peony','kwin-x11','xvfb','x11vnc','novnc','firefox']
    data['packages']=command(['dpkg-query','-W','-f=${Package}\t${Version}\n',*packages])
    data['openclaw']=command([str(args.runtime_base/'openclaw/bin/openclaw'),'--version'])
    data['hermes_commit']={'revision':git_revision(args.runtime_base/'hermes-source'),'source':'Read checkout git metadata; no new git installation'}
    data['apt_sources']={}
    for path in [Path('/etc/apt/sources.list'),*Path('/etc/apt/sources.list.d').glob('*.list')]:
        if path.is_file():data['apt_sources'][str(path)]=path.read_text()
    data['desktop']={'type':'UKUI components on Xvfb via local noVNC','display':':14','pixels':[1600,900],
                     'scope':'Real openKylin userland on WSL2; not bare-metal boot, login-manager or kernel certification.',
                     'script':'scripts/start_desktop.sh'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(args.output)
if __name__=='__main__':main()
