"""Exercise failure isolation and file integrity without starting native Qt3D."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_3d_safety import CommandError, handler_function

spec = importlib.util.spec_from_file_location('isolated_capture', Path(__file__).resolve().parents[1] / 'qgis_mcp_plugin' / 'isolated_capture.py')
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class TestIsolatedCapture(unittest.TestCase):
    def test_export_limits_reject_nonfinite_and_excessive_allocations(self):
        for values in ({'width': True}, {'width': 63}, {'height': 4097}, {'dpi': 0}, {'width': 4096, 'height': 4096}, {'pitch': 91}, {'heading': float('nan')}, {'distance': 0}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                capture.capture_options(**values)
        self.assertEqual(capture.capture_options(heading=-45)['heading'], 315)

    def test_native_worker_crash_is_reported_without_running_more_qgis_operations(self):
        process = Mock(returncode=-1073741819)
        process.poll.return_value = process.returncode
        with tempfile.TemporaryDirectory() as folder, patch.object(capture.subprocess, 'Popen', return_value=process) as spawn:
            with self.assertRaisesRegex(ValueError, '3D_EXPORT_FAILED'):
                capture.run_worker({'qgis_prefix': 'QGIS/apps/qgis'}, folder, 'python', waiter=lambda *args: None)
            args, kwargs = spawn.call_args
            self.assertEqual(args[0][0], 'python')
            self.assertNotIn('shell', kwargs)
            self.assertEqual(kwargs['stdin'], capture.subprocess.DEVNULL)
            process.kill.assert_not_called()

    def test_timeout_kills_only_the_child_and_preserves_timeout_error(self):
        process = Mock()
        process.poll.return_value = None
        def timeout(*args):
            raise ValueError('3D_EXPORT_TIMEOUT: child stalled')
        with tempfile.TemporaryDirectory() as folder, patch.object(capture.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(ValueError, '3D_EXPORT_TIMEOUT'):
                capture.run_worker({'qgis_prefix': 'QGIS/apps/qgis'}, folder, 'python', waiter=timeout)
        process.kill.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=5)

    def test_worker_watchdog_exit_is_a_timeout(self):
        process = Mock(returncode=124)
        process.poll.return_value = 124
        with tempfile.TemporaryDirectory() as folder, patch.object(capture.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(ValueError, '3D_EXPORT_TIMEOUT'):
                capture.run_worker({'qgis_prefix': 'QGIS/apps/qgis'}, folder, 'python', waiter=lambda *args: None)

    def test_success_requires_report_not_just_a_zero_exit(self):
        process = Mock(returncode=0)
        process.poll.return_value = 0
        with tempfile.TemporaryDirectory() as folder, patch.object(capture.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(ValueError, '3D_EXPORT_FAILED'):
                capture.run_worker({'qgis_prefix': 'QGIS/apps/qgis'}, folder, 'python', waiter=lambda *args: None)
            Path(folder, 'result.json').write_text(json.dumps({'ok': False, 'error': 'blank image'}))
            with self.assertRaisesRegex(ValueError, 'blank image'):
                capture.run_worker({'qgis_prefix': 'QGIS/apps/qgis'}, folder, 'python', waiter=lambda *args: None)

    def test_failed_export_does_not_replace_existing_png(self):
        modules = {'qgis': SimpleNamespace(), 'qgis.PyQt': SimpleNamespace(), 'qgis.PyQt.QtGui': SimpleNamespace(QImage=Mock())}
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, modules), \
             patch.object(capture, 'scene_description', return_value={'qgis_prefix': 'qgis'}), \
             patch.object(capture, 'python_runtime', return_value='python'), \
             patch.object(capture, 'run_worker', side_effect=ValueError('3D_EXPORT_FAILED')):
            output = Path(folder, 'final.png')
            output.write_bytes(b'previous validated image')
            with self.assertRaisesRegex(ValueError, '3D_EXPORT_FAILED'):
                capture.capture_scene(object(), path=str(output))
            self.assertEqual(output.read_bytes(), b'previous validated image')

    def test_invalid_png_never_replaces_existing_output(self):
        modules = {'qgis': SimpleNamespace(), 'qgis.PyQt': SimpleNamespace(), 'qgis.PyQt.QtGui': SimpleNamespace(QImage=lambda path: SimpleNamespace(isNull=lambda: True))}
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, modules), \
             patch.object(capture, 'scene_description', return_value={'qgis_prefix': 'qgis'}), \
             patch.object(capture, 'python_runtime', return_value='python'), \
             patch.object(capture, 'run_worker', return_value={'ok': True}):
            output = Path(folder, 'final.png')
            output.write_bytes(b'old PNG')
            with self.assertRaisesRegex(ValueError, '3D_EXPORT_INVALID_IMAGE'):
                capture.capture_scene(object(), path=str(output))
            self.assertEqual(output.read_bytes(), b'old PNG')

    def test_old_screenshot_alias_uses_the_same_isolated_capture(self):
        alias = handler_function('canvas.py', 'get_3d_screenshot', {})
        handler = SimpleNamespace(capture_3d_view=Mock(return_value={'capture_mode': 'layout_3d_isolated'}))
        output = alias(handler, width=1200, height=800, pitch=35, path='final.png')
        self.assertEqual(output['capture_mode'], 'layout_3d_isolated')
        self.assertEqual(handler.capture_3d_view.call_args.kwargs['width'], 1200)
        self.assertEqual(handler.capture_3d_view.call_args.kwargs['height'], 800)
        self.assertEqual(handler.capture_3d_view.call_args.kwargs['pitch'], 35)

    def test_capture_guard_rejects_modal_dialog_before_starting_worker(self):
        export = handler_function('canvas.py', 'capture_3d_view', {'CommandError': CommandError, 'capture_scene': Mock()})
        handler = SimpleNamespace(_assert_no_modal_dialog=Mock(side_effect=CommandError('modal')))
        with self.assertRaisesRegex(CommandError, 'modal'):
            export(handler)


if __name__ == '__main__':
    unittest.main()
