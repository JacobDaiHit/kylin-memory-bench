#!/bin/bash
# V3 pilot: expose only this workspace and installed native runtimes to the agent.
set -euo pipefail
if [[ "${1:-}" != --inside ]]; then
    case "$(basename "$0")" in
        openclaw-isolated) native_kind=openclaw ;;
        hermes-isolated) native_kind=hermes ;;
        *) echo 'Expected openclaw-isolated or hermes-isolated wrapper.' >&2; exit 2 ;;
    esac
    exec unshare --user --map-root-user --mount --pid --fork --mount-proc \
        --propagation private "$0" --inside "$native_kind" "$@"
fi
native_kind="${2:?Expected native kind}"
shift 2
workspace="$(pwd -P)"
case "$workspace" in
    /home/kmb/runs/kmb-research-v3-*/workspaces/*) ;;
    *) echo 'Expected a V3 pilot workspace.' >&2; exit 2 ;;
esac
runtime_base=/home/maedaily/.local/share/kmb-live
stage="$(mktemp -d /tmp/kmb-native-stage.XXXXXXXX)"
runtime_parts=(openclaw hermes-source hermes-home/installs hermes-home/tools)
for part in "${runtime_parts[@]}"; do
    mkdir -p "$stage/runtime/$part"
    mount --rbind "$runtime_base/$part" "$stage/runtime/$part"
done
mkdir -p "$stage/workspace"
mount --bind "$workspace" "$stage/workspace"
mount -t tmpfs -o nosuid,nodev tmpfs /home
mkdir -p "$workspace"
mount --bind "$stage/workspace" "$workspace"
for part in "${runtime_parts[@]}"; do
    mkdir -p "$runtime_base/$part"
    mount --rbind "$stage/runtime/$part" "$runtime_base/$part"
done
# Repository, evaluator files, old workspaces and old temporary files disappear.
for path in /mnt /tmp /var/tmp; do mount -t tmpfs -o nosuid,nodev tmpfs "$path"; done
cd "$workspace"
drop_privileges=(setpriv --no-new-privs --bounding-set=-all)
if [[ "${1:-}" == --isolation-probe ]]; then
    exec "${drop_privileges[@]}" python3 - "$workspace" "$runtime_base" <<'PY'
import json, os, pathlib, sys
workspace, runtime = map(pathlib.Path, sys.argv[1:])
result = {
    'workspace_read_write': (workspace/'allowed.txt').read_text() == 'workspace-only',
    'repository_hidden': not pathlib.Path('/mnt/d/github/openkylin').exists(),
    'other_workspaces_hidden': not (workspace.parent/'forbidden'/'secret.txt').exists(),
    'other_run_files_hidden': not (workspace.parents[1]/'scorer-secret.txt').exists(),
    'old_tmp_hidden': not pathlib.Path('/tmp/kmb-v3-private-sentinel.txt').exists(),
    'global_hermes_config_hidden': not (runtime/'hermes-home'/'config.yaml').exists(),
    'openclaw_runtime_present': (runtime/'openclaw'/'bin'/'openclaw').is_file(),
    'hermes_runtime_present': (runtime/'hermes-source'/'.hermes'/'bin'/'hermes').is_file(),
    'pid_namespace': os.getpid() < 20,
    'no_new_privileges': 'NoNewPrivs:\t1' in pathlib.Path('/proc/self/status').read_text(),
    'capabilities_dropped': 'CapEff:\t0000000000000000' in pathlib.Path('/proc/self/status').read_text(),
}
(workspace/'write-probe.txt').write_text('isolated-write-ok')
print(json.dumps(result, sort_keys=True))
if not all(result.values()): raise SystemExit(1)
PY
fi
case "$native_kind" in
    openclaw) native_executable="$runtime_base/openclaw/bin/openclaw" ;;
    hermes) native_executable="$runtime_base/hermes-source/.hermes/bin/hermes" ;;
    *) exit 2 ;;
esac
exec "${drop_privileges[@]}" "$native_executable" "$@"
