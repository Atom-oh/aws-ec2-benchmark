import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
import springboot_traffic48 as runner


class IsolatedAnalysisTests(unittest.TestCase):
    def test_child_uses_current_interpreter_explicit_cwd_and_foreground_check(self):
        output = ROOT/'results/springboot-traffic48/test1'
        with patch.object(runner.subprocess, 'run') as run:
            runner.analyze_isolated(output)
        run.assert_called_once_with(
            [sys.executable, str(ROOT/'scripts/springboot_traffic48.py'),
             'analyze', '--run-id', 'test1'], cwd=ROOT, check=True)

    def test_failed_child_propagates_and_keeps_last_good_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root/'results/springboot-traffic48/test1'
            output.mkdir(parents=True)
            previous = b'{"previous": true}\n'
            (output/'progress-latest.json').write_bytes(previous)
            with patch.object(runner, 'ROOT', root), \
                    patch.object(runner.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['analyze'])):
                with self.assertRaises(subprocess.CalledProcessError):
                    runner.analyze_isolated(output)
            self.assertEqual((output/'progress-latest.json').read_bytes(), previous)

    def test_wrong_output_path_is_rejected_before_child_launch(self):
        for path in (ROOT/'elsewhere/test1', ROOT/'results/springboot-traffic48/bad_name'):
            with self.subTest(path=path), patch.object(runner.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    runner.analyze_isolated(path)
                run.assert_not_called()

    def test_failed_report_serialization_keeps_previous_atomic_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'progress-latest.json'
            previous = '{"previous": true}\n'
            path.write_text(previous)
            with self.assertRaises(TypeError):
                runner.write_json(path, {'bad': object()})
            self.assertEqual(path.read_text(), previous)


if __name__ == '__main__':
    unittest.main()
