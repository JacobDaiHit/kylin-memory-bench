"""No paid/native execution may start after a failed or incomplete isolation gate."""
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from scripts import run_openkylin_video as video


class RecordingIsolationGateTests(unittest.TestCase):
    def check_blocked(self, observations, returncode, reason):
        output = MagicMock()
        output.__str__.return_value = '/home/kmb/.local/share/kmb-live/runs/kmb-plan-gate-test'
        output.name = 'kmb-plan-gate-test'
        output.exists.return_value = False
        config = {'model': 'gpt-5.6-luna', 'agents': [], 'environment': {}}
        result = subprocess.CompletedProcess([], returncode, json.dumps(observations), '')
        with patch.object(video, 'platform_info', return_value={
                    'is_openkylin': True, 'os_release': {'PRETTY_NAME': 'fixture'}}), \
                patch('sys.argv', ['recording', '--bridge-config', 'fixture.local.json',
                                  '--output', '/home/kmb/.local/share/kmb-live/runs/kmb-plan-gate-test']), \
                patch.object(Path, 'resolve', return_value=output), \
                patch.object(Path, 'read_text', return_value=json.dumps(config)), \
                patch.object(Path, 'mkdir'), patch.object(Path, 'chmod'), \
                patch.object(Path, 'write_text'), patch.object(video.shutil, 'copyfile'), \
                patch.object(video.subprocess, 'run', return_value=result), \
                patch.object(video, 'execute') as execute:
            with self.assertRaisesRegex(RuntimeError, reason):
                video.main()
            execute.assert_not_called()

    def test_visible_installed_answers_block_all_model_execution(self):
        self.check_blocked({'repository_hidden': True, 'installed_benchmark_data_hidden': False},
                           1, 'Isolation preflight failed')

    def test_old_incomplete_probe_cannot_authorize_paid_execution(self):
        self.check_blocked({'repository_hidden': True, 'workspace_read_write': True},
                           0, 'Installed evaluator isolation was not verified')


if __name__ == '__main__':
    unittest.main()
