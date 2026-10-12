"""kmb command line. All core paths run on the Python standard library."""
import argparse
import datetime
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .adapters import load_config
from .common import BenchError, DIMENSIONS, read_json, write_json
from .dataset import describe, load_dataset
from .generate import generate, save_dataset
from .report import render_report
from .runner import execute, platform_info, read_run, verify_run

DATA = Path(__file__).parent / 'data'


def parser():
    root = argparse.ArgumentParser(prog='kmb', description='openKylin 长期记忆自动化评测 / Evidence-first memory benchmark')
    root.add_argument('--version', action='version', version=__version__)
    sub = root.add_subparsers(dest='command', required=True)
    demo = sub.add_parser('demo', help='Run three clearly labelled offline reference baselines')
    demo.add_argument('--output', '-o')
    demo.add_argument('--repeats', type=int, default=1)
    demo.add_argument('--quiet', action='store_true')
    run = sub.add_parser('run', help='Run a dataset against agent configurations')
    run.add_argument('--dataset', '-d', default=str(DATA / 'sample.jsonl'))
    run.add_argument('--config', '-c', required=True)
    run.add_argument('--output', '-o')
    run.add_argument('--repeats', type=int, default=1)
    run.add_argument('--jobs', type=int, default=1, help='Concurrent isolated cases, 1..16')
    run.add_argument('--dimension', choices=list(DIMENSIONS))
    run.add_argument('--case', action='append', dest='case_ids')
    run.add_argument('--quiet', action='store_true')
    validate = sub.add_parser('validate', help='Validate JSONL schema and report coverage')
    validate.add_argument('dataset')
    gen = sub.add_parser('generate', help='Generate reproducible synthetic dataset variants')
    gen.add_argument('--output', '-o', required=True)
    gen.add_argument('--seed', type=int, default=2026)
    gen.add_argument('--suite', choices=['core', 'challenge', 'challenge-v21'], default='core')
    gen.add_argument('--variants', type=int, default=6)
    gen.add_argument('--noise', type=int, default=3)
    gen.add_argument('--force', action='store_true')
    for command in ('score', 'verify', 'report'):
        action = sub.add_parser(command, help={'score': 'Independently replay saved evidence', 'verify': 'Verify hash chain and score replay', 'report': 'Rebuild HTML/SVG/CSV from verified evidence'}[command])
        action.add_argument('run_directory')
    doctor = sub.add_parser('doctor', help='Read-only platform and executable checks')
    doctor.add_argument('--config')
    compare = sub.add_parser('compare', help='Compare verified runs of the same dataset')
    compare.add_argument('run_directories', nargs='+')
    compare.add_argument('--output', '-o', required=True)
    return root


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    args = parser().parse_args(argv)
    try:
        if args.command == 'validate':
            emit(describe(load_dataset(args.dataset)))
        elif args.command == 'generate':
            if not 1 <= args.variants <= 1000 or not 0 <= args.noise <= 100:
                raise BenchError('variants must be 1..1000; noise must be 0..100')
            if Path(args.output).exists() and not args.force:
                raise BenchError('Dataset already exists; use --force to replace it')
            if args.suite in ('challenge', 'challenge-v21'):
                from .challenges import generate_challenges, generate_revised_challenges
                cases = (generate_revised_challenges if args.suite == 'challenge-v21' else generate_challenges)(args.seed)
            else:
                cases = generate(args.seed, args.variants, args.noise)
            save_dataset(args.output, cases)
            emit(describe(cases))
        elif args.command in ('demo', 'run'):
            dataset = DATA / 'sample.jsonl' if args.command == 'demo' else args.dataset
            config_path = DATA / 'baselines.json' if args.command == 'demo' else args.config
            cases, config = load_dataset(dataset), load_config(config_path)
            if args.command == 'run':
                if args.dimension:
                    cases = [c for c in cases if c['dimension'] == args.dimension]
                if args.case_ids:
                    unknown = set(args.case_ids) - {c['id'] for c in cases}
                    if unknown:
                        raise BenchError('Unknown or excluded case IDs: ' + ', '.join(sorted(unknown)))
                    cases = [c for c in cases if c['id'] in args.case_ids]
            if not cases:
                raise BenchError('No cases selected')
            output = args.output or ('runs/' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            def progress(agent, trial, case):
                print(f'[{agent} / trial {trial+1}] {case}', file=sys.stderr)
            report = execute(cases, config, output, args.repeats, None if args.quiet else progress, getattr(args, 'jobs', 1))
            emit({'output': str(Path(output).resolve()), 'run_status': report['run_status'],
                  'agents': [{'id': a['id'], **a['overall']} for a in report['agents']]})
            return 3 if report['run_status'] == 'completed_with_errors' else 0
        elif args.command == 'verify':
            emit(verify_run(args.run_directory))
        elif args.command in ('score', 'report'):
            manifest, cases, events, report = read_run(args.run_directory)
            write_json(Path(args.run_directory) / 'scores.json', report)
            render_report(report, args.run_directory)
            emit({'run_id': manifest['run_id'], 'events': len(events), 'status': manifest['status'], 'replayed': True})
        elif args.command == 'doctor':
            info = platform_info()
            info['benchmark_version'] = __version__
            info['executables'] = {name: shutil.which(name) for name in ('python3', 'dpkg-deb', 'openclaw', 'hermes', 'ffmpeg')}
            missing = []
            if args.config:
                config = load_config(args.config)
                for agent in config['agents']:
                    name = (agent.get('executable', agent['kind']) if agent['kind'] in ('openclaw', 'hermes')
                            else agent.get('command', [''])[0])
                    if name and name != '{python}' and not shutil.which(name):
                        missing.append({'agent': agent['id'], 'executable': name})
            info['missing_configured_executables'] = missing
            info['native_validation'] = 'openKylin detected' if info['is_openkylin'] else 'openKylin host validation still required'
            emit(info)
            return 3 if missing else 0
        elif args.command == 'compare':
            output = Path(args.output)
            if output.exists() and any(output.iterdir()):
                raise BenchError('Comparison output must be empty')
            agents, dataset_hash, sources = [], None, []
            for index, directory in enumerate(args.run_directories):
                verify_run(directory)
                manifest, cases, events, report = read_run(directory)
                if dataset_hash and report['dataset_sha256'] != dataset_hash:
                    raise BenchError('Cannot compare different dataset fingerprints')
                dataset_hash = report['dataset_sha256']
                sources.append({'run_id': manifest['run_id'], 'path': str(Path(directory).resolve())})
                for agent in report['agents']:
                    agent['id'] = f'run{index+1}-' + agent['id']
                    agent['label'] = f'Run {index+1} / ' + agent['label']
                    agents.append(agent)
            report = {'schema_version': '1.0', 'run_id': 'comparison', 'run_status': 'comparison',
                      'dataset_sha256': dataset_hash, 'agents': agents, 'sources': sources}
            write_json(output / 'scores.json', report)
            render_report(report, output)
            # Comparisons link to a source index; evidence events retain their source-run meaning.
            write_json(output / 'sources.json', {'source_runs': sources, 'note': 'Open each source run for original evidence.'})
            emit({'output': str(output.resolve()), 'systems': len(agents)})
        return 0
    except (BenchError, OSError, UnicodeError, KeyError, TypeError, AttributeError, IndexError) as exc:
        print('kmb: ' + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('kmb: interrupted; completed evidence events were preserved', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
