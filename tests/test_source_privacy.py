import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_release


class SourcePrivacyTests(unittest.TestCase):
    def test_ignored_private_inputs_are_not_packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ['configs/.env','configs/private.local.json','experiments/workspaces/one/token.txt',
                         'experiments/run/.hermes/config.yaml','experiments/demo/gold.json','configs/.env.example']:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('synthetic')
            with patch.object(build_release,'ROOT',root):
                names={name for name,_ in build_release.files()}
            self.assertEqual(names,{'experiments/demo/gold.json','configs/.env.example'})

    def test_revised_data_and_source_are_in_the_package_manifest(self):
        names={name for name,_ in build_release.files()}
        self.assertTrue({'experiments/math_memory/memory_v31.py',
                         'experiments/math_memory/validation-v31/health/protocol.json',
                         'kylin_memory_bench/data/challenges-v21.jsonl',
                         'scripts/prepare_memory_validation.py','scripts/isolated_native_v31.sh',
                         'docs/memory-revision-v31.md'}<=names)
        self.assertFalse(any('/workspaces/' in name or name.endswith('.local.json') for name in names))


if __name__=='__main__':unittest.main()
