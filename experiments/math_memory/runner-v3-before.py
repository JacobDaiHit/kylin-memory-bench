#!/usr/bin/env python3
"""Run the authorized, frozen V3 pilot on openKylin with cumulative budget guard."""
import argparse
import datetime
import hashlib
import json
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.math_memory.record_pilot import verify_frozen
from kylin_memory_bench.common import digest
from kylin_memory_bench.dataset import load_dataset
from kylin_memory_bench.runner import platform_info


def fingerprint(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--additional-budget-cny',type=Decimal,required=True)
    args=p.parse_args()
    if not args.additional_budget_cny.is_finite() or not 0<args.additional_budget_cny<=10:
        p.error('This authorized pilot has an additional ceiling of 10 CNY')
    environment=platform_info()
    if not environment['is_openkylin']:p.error('Run on the validated openKylin environment')
    frozen=ROOT/'experiments/math_memory/pilot-v3'
    protocol=verify_frozen(frozen)
    for name,value in protocol['implementation_sha256'].items():
        if fingerprint(ROOT/name)!=value:raise ValueError('Frozen implementation changed: '+name)
    preflight=json.loads((ROOT/'docs/evidence/research-v3-native-preflight.json').read_text())
    if not all(preflight['isolation'].values()) or len(preflight['native_stub_turns'])!=4:
        raise ValueError('Native isolation/startup preflight did not pass')
    target_test_log=(ROOT/'runs/research-v3-tests-openkylin.local.log').read_text()
    if 'Ran 14 tests' not in target_test_log or '\nOK\n' not in target_test_log:
        raise ValueError('Expected target-environment pilot tests')
    base=Path('/home/kmb/runs/kmb-research-v3-native')
    if base.exists():raise ValueError('Never reuse pilot workspaces or replace an earlier run')
    base.mkdir(parents=True)
    binary=base/'bin';binary.mkdir()
    shutil.copyfile(ROOT/'scripts/isolated_native.sh',binary/'isolated_native.sh')
    (binary/'isolated_native.sh').chmod(0o700)
    for agent in protocol['agents']:(binary/(agent+'-isolated')).symlink_to('isolated_native.sh')
    ledger_path=ROOT/'runs/deepseek-budget.local.json'
    ledger=json.loads(ledger_path.read_text())
    cumulative_start=Decimal(ledger['estimated_upper_cny'])
    ceiling=cumulative_start+args.additional_budget_cny
    audit=ROOT/'runs/research-v3-native/api-audit.jsonl'
    audit.parent.mkdir(parents=True,exist_ok=False)
    output=base/'result'
    execution_freeze={'status':'frozen-before-paid-run',
        'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'environment':environment,
        'selected_cases':protocol['selected_cases'],'repeats':1,'jobs':6,'scheduled_final_slots':6,
        'incremental_authorized_limit_cny':str(args.additional_budget_cny),
        'cumulative_estimate_start_cny':str(cumulative_start),'cumulative_estimate_ceiling_cny':str(ceiling),
        'budget_policy':'Preserve original ledger; cap both current incremental estimate and account decrease; no video allowance used.',
        'retry_policy':'No automatic retry or result-selected replacement.',
        'model':'deepseek-flash','thinking':'disabled','temperature':0,'max_output_tokens':2048,
        'hermes_max_turns':6,'native_tools':'Native file and memory tools; no math solver or file-delivery check.',
        'selection_note':'Three predeclared conditions of this mathematical research-record example; concurrent cases have isolated state.',
        'dataset_sha256':digest(load_dataset(frozen/'dataset.evaluator.jsonl')),
        'frozen_material_sha256':fingerprint(frozen/'protocol.json'),
        'preflight_sha256':fingerprint(ROOT/'docs/evidence/research-v3-native-preflight.json'),
        'source_sha256':{str(path.relative_to(ROOT)):fingerprint(path) for path in (
            Path(__file__),ROOT/'scripts/live_deepseek.py',ROOT/'scripts/isolated_native.sh',
            ROOT/'experiments/math_memory/record_pilot.py',ROOT/'experiments/math_memory/memory_only.py')},
        'price_check':{'official_url':'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/',
                       'guard_cny_per_million':{'input_cache_miss':2,'input_cache_hit':0.04,'output':8},
                       'note':'Verified current official peak rates; deliberately retain peak bound during off-peak hours.'}}
    (ROOT/'docs/evidence/research-v3-execution-freeze.json').write_text(
        json.dumps(execution_freeze,ensure_ascii=False,indent=2)+'\n')
    command=[sys.executable,str(ROOT/'scripts/live_deepseek.py'),
             '--env-file','/mnt/d/github/mathagent/.env','--ledger',str(ledger_path),
             '--budget-cny',str(ceiling),'--additional-budget-cny',str(args.additional_budget_cny),
             '--request-limit','1800','--audit',str(audit),'--config',str(frozen/'config.template.json'),
             '--dataset',str(frozen/'dataset.evaluator.jsonl'),'--output',str(output),'--repeats','1','--jobs','6']
    print('V3 paid pilot starting: 3 frozen conditions, 2 native agents, 1 round; additional cap '+str(args.additional_budget_cny)+' CNY.',flush=True)
    with (ROOT/'runs/research-v3-native-launch.local.log').open('w') as log:
        result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    if (output/'manifest.json').exists():
        manifest=json.loads((output/'manifest.json').read_text())
        print(json.dumps({'status':manifest['status'],'events':manifest['event_count'],
                          'execution_errors':manifest['execution_errors'],'output':str(output)}),flush=True)
    raise SystemExit(result.returncode)


if __name__=='__main__':main()
