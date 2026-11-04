"""Exercise release/rollback ordering without Docker, SSH, or real credentials."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
VERSION = 'sha-' + 'a' * 40
MOCK = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p = Path(os.environ['MOCK_STATE'])
s = json.loads(p.read_text())
args = sys.argv[1:]
program = Path(sys.argv[0]).name
s['calls'].append([program] + args)
status = 0
if program == 'sudo':
    assert args[:2] == ['-n', 'docker']
    a = args[2:]
    if a[:2] == ['container', 'inspect']:
        status = 0 if a[2] in s['containers'] else 1
    elif a[0] == 'inspect':
        c = s['containers'].get(a[-1])
        if not c:
            status = 1
        elif '.Config.Image' in a[2]:
            print(c['image'])
        else:
            print(c['project'])
    elif a[0] == 'rm':
        s['containers'].pop(a[1], None)
    elif a[0] == 'compose':
        if 'pull' in a and os.environ.get('FAIL_PHASE') == 'pull':
            status = 1
        if 'up' in a:
            image = os.environ['BACKEND_IMAGE']
            rollback = image == 'old-backend:release'
            s['ups'].append({'rollback': rollback, 'backend': image})
            if not rollback and os.environ.get('FAIL_PHASE') == 'up':
                status = 1
            else:
                s['containers'] = {
                    'smart-recipe-backend': {'image': image, 'project': 'smart-recipe-app'},
                    'smart-recipe-frontend': {'image': os.environ['FRONTEND_IMAGE'], 'project': 'smart-recipe-app'},
                }
elif program == 'curl' and os.environ.get('FAIL_PHASE') == 'https':
    status = 1
p.write_text(json.dumps(s))
sys.exit(status)
'''


class DeploymentTests(unittest.TestCase):
    def run_release(self, fail_phase='', version=VERSION):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        app = root / 'app'
        bundle = root / 'bundle'
        binaries = root / 'bin'
        for folder in (app, bundle, binaries):
            folder.mkdir()
        for name in ('qdrant_data', 'notes', 'logs'):
            (app / 'runtime' / name).mkdir(parents=True)
        (app / 'backend.env').write_text('APP_ENV=production\n')
        (app / '.deployed-version').write_text('previous-version\n')
        for name in ('deploy.sh', 'compose.yaml'):
            shutil.copy(ROOT / name, bundle / name)
        state_path = root / 'state.json'
        state_path.write_text(json.dumps({
            'calls': [], 'ups': [],
            'containers': {
                'smart-recipe-backend': {'image': 'old-backend:release', 'project': 'legacy'},
                'smart-recipe-frontend': {'image': 'old-frontend:release', 'project': 'legacy'},
            },
        }))
        for name in ('sudo', 'curl', 'flock'):
            script = binaries / name
            script.write_text(MOCK)
            script.chmod(0o755)
        env = {**os.environ, 'PATH': str(binaries) + os.pathsep + os.environ['PATH'],
               'MOCK_STATE': str(state_path), 'FAIL_PHASE': fail_phase}
        result = subprocess.run(['bash', str(bundle / 'deploy.sh'), str(app), 'cammytang', version],
                                env=env, text=True, capture_output=True)
        return result, json.loads(state_path.read_text()), app

    def test_success_pulls_before_replacing_and_records_version(self):
        result, state, app = self.run_release()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((app / '.deployed-version').read_text().strip(), VERSION)
        self.assertEqual((app / '.previous-version').read_text().strip(), 'previous-version')
        calls = state['calls']
        pull = next(i for i, c in enumerate(calls) if 'pull' in c)
        stop = next(i for i, c in enumerate(calls) if 'stop' in c)
        self.assertLess(pull, stop)
        self.assertFalse(any('smart-recipe-db' in c or 'smart-recipe-gateway' in c for c in calls))

    def test_pull_failure_keeps_running_containers(self):
        result, state, app = self.run_release('pull')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any('stop' in c or 'rm' in c for c in state['calls']))
        self.assertEqual((app / '.deployed-version').read_text().strip(), 'previous-version')

    def test_failed_health_restores_old_image_pair(self):
        for phase in ('up', 'https'):
            with self.subTest(phase=phase):
                result, state, app = self.run_release(phase)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(state['ups'][-1]['rollback'])
                self.assertEqual(state['containers']['smart-recipe-frontend']['image'], 'old-frontend:release')
                self.assertEqual((app / '.deployed-version').read_text().strip(), 'previous-version')

    def test_invalid_version_is_rejected_before_docker(self):
        result, state, _ = self.run_release(version='latest; echo invalid')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state['calls'], [])


if __name__ == '__main__':
    unittest.main()
