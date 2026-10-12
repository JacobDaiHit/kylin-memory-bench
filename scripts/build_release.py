#!/usr/bin/env python3
"""Build a reproducible architecture-independent .deb and source archive without third-party tools."""
import argparse
import gzip
import hashlib
import io
import os
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kylin_memory_bench import __version__

EPOCH = int(os.environ.get('SOURCE_DATE_EPOCH', '1790985600'))
LAUNCHER = b'#!/usr/bin/python3\nimport sys\nfrom pathlib import Path, PurePosixPath\nsys.path.insert(0, str(Path(__file__).resolve().parent.parent / "share/kylin-memory-bench"))\nfrom kylin_memory_bench.cli import main\nraise SystemExit(main())\n'


def public_source_file(path):
    relative = path.relative_to(ROOT)
    private_parts = {'__pycache__', '.venv', '.git', '.home', '.hermes', '.openclaw', 'workspaces', 'runs', 'tmp'}
    return (path.is_file() and not path.is_symlink() and not private_parts.intersection(relative.parts)
            and path.suffix != '.pyc' and not path.name.endswith('.local.json')
            and (not path.name.startswith('.env') or path.name == '.env.example')
            and path.name != 'account-balance-final.json')


def files():
    roots = ['kylin_memory_bench', 'docs', 'schemas', 'configs', 'scripts', 'tests', '.github', 'reproducibility', 'experiments']
    for folder in roots:
        for path in sorted((ROOT / folder).rglob('*')):
            if public_source_file(path):
                yield path.relative_to(ROOT).as_posix(), path.read_bytes()
    for name in ('README.md', 'LICENSE', 'NOTICE', 'pyproject.toml', '.gitignore',
                 'CHANGELOG.md', 'CONTRIBUTING.md', 'ROADMAP.md'):
        path = ROOT / name
        if path.is_file():
            yield name, path.read_bytes()
    # Sample run is deliberately self-contained and excludes mutable workspaces.
    for folder in ('examples/sample-run', 'examples/live-run', 'examples/openkylin-core', 'examples/openkylin-challenge',
                   'examples/openkylin-difficulty', 'examples/openkylin-difficulty-interrupted',
                   'examples/openkylin-math-pilot-v1', 'examples/openkylin-math-pilot-v2',
                   'examples/openkylin-research-memory-v3', 'examples/openkylin-research-memory-v3-interrupted'):
        for path in sorted((ROOT / folder).glob('*')):
            if public_source_file(path):
                yield path.relative_to(ROOT).as_posix(), path.read_bytes()
    for path in sorted((ROOT / 'examples').glob('*.py')):
        yield path.relative_to(ROOT).as_posix(), path.read_bytes()


def tar_gz(entries):
    entries = list(entries)
    directories = {str(parent) for name, _, _ in entries for parent in PurePosixPath(name).parents if str(parent) != '.'}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.GNU_FORMAT) as archive:
        # dpkg requires explicit directories on a clean installation.
        for name in sorted(directories):
            info = tarfile.TarInfo(name)
            info.type, info.mode, info.mtime = tarfile.DIRTYPE, 0o755, EPOCH
            info.uid = info.gid = 0
            info.uname = info.gname = 'root'
            archive.addfile(info)
        for name, content, mode in sorted(entries):
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(content), mode, EPOCH
            info.uid = info.gid = 0
            info.uname = info.gname = 'root'
            archive.addfile(info, io.BytesIO(content))
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=EPOCH, compresslevel=9) as stream:
        stream.write(buffer.getvalue())
    return output.getvalue()


def ar_member(name, data):
    header = f'{name + "/":<16}{EPOCH:<12}{0:<6}{0:<6}{"100644":<8}{len(data):<10}`\n'.encode('ascii')
    if len(header) != 60:
        raise ValueError('Invalid ar header')
    return header + data + (b'\n' if len(data) % 2 else b'')


def build(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    source = list(files())
    entries = [('usr/bin/kmb', LAUNCHER, 0o755)]
    for name, data in source:
        if name.startswith('kylin_memory_bench/'):
            entries.append(('usr/share/kylin-memory-bench/' + name, data, 0o644))
        elif name.startswith(('docs/', 'schemas/', 'configs/', 'examples/', 'experiments/')) or name in ('README.md', 'LICENSE', 'NOTICE', 'CHANGELOG.md', 'CONTRIBUTING.md', 'ROADMAP.md'):
            entries.append(('usr/share/doc/kylin-memory-bench/' + name, data, 0o644))
    size = sum(len(data) for _, data, _ in entries)
    control = (f'Package: kylin-memory-bench\nVersion: {__version__}\nSection: science\nPriority: optional\n'
               f'Architecture: all\nDepends: python3 (>= 3.9)\nInstalled-Size: {(size+1023)//1024}\n'
               'Maintainer: Kylin Memory Bench contributors <maintainers@example.invalid>\n'
               'Description: Evidence-first long-term agent memory benchmark\n'
               ' Reproducible CLI, synthetic scenarios, explainable six-dimensional scoring,\n'
               ' offline HTML reports and adapters for openKylin agent evaluation.\n').encode('utf-8')
    md5sums = ''.join(hashlib.md5(data).hexdigest() + '  ' + name + '\n' for name, data, _ in sorted(entries)).encode('ascii')
    deb = b'!<arch>\n' + ar_member('debian-binary', b'2.0\n')
    deb += ar_member('control.tar.gz', tar_gz([('control', control, 0o644), ('md5sums', md5sums, 0o644)]))
    deb += ar_member('data.tar.gz', tar_gz(entries))
    deb_path = output / f'kylin-memory-bench_{__version__}_all.deb'
    deb_path.write_bytes(deb)
    zip_path = output / f'kylin-memory-bench-{__version__}-source.zip'
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(source):
            info = zipfile.ZipInfo(f'kylin-memory-bench-{__version__}/' + name, (2026, 10, 3, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if name.endswith('.sh') else 0o100644) << 16
            archive.writestr(info, data)
    hashes = ''.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n' for path in (deb_path, zip_path))
    (output / 'SHA256SUMS').write_text(hashes, encoding='ascii')
    print(hashes, end='')
    return deb_path, zip_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT / 'dist'))
    build(parser.parse_args().output)
