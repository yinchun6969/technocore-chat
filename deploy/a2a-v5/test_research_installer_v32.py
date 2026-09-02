"""Exercise the actual shell installer offline, including the .env preflight.

Only host paths are relocated to a temporary directory. Downloads are served
from pinned local fixture bytes; the final deploy boundary is intercepted.
Transactional deploy behaviour is tested in test_research_context_v32.py.
"""
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
INSTALLER = HERE / "install-research-context-v3.2.sh"


class Installer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / "config.env"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.trace = self.root / "trace"
        self.script = self.root / "installer.sh"
        self.script.write_text(INSTALLER.read_text().replace(
            'config="/opt/technocore-a2a/.env"', f'config="{self.config}"'
        ).replace('/root/tc-research-context-v32-stage.',
                  str(self.root / 'stage.')))
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'])
        self.tool('id', '#!/bin/sh\necho 0\n')
        self.tool('curl', f'''#!{sys.executable}
import pathlib, shutil, sys
args = sys.argv[1:]
url = args[args.index('-o') - 1]
assert '/f2ec3985f3ec0fdcf797f330cdc3cb214b0a0bc0/deploy/a2a-v5/' in url
name = url.rsplit('/', 1)[1]
with open({str(self.trace)!r}, 'a') as f: f.write('download:' + name + '\\n')
shutil.copyfile(pathlib.Path({str(HERE)!r}) / name, args[args.index('-o') + 1])
''')
        self.tool('python3', f'''#!{sys.executable}
import os, sys
if sys.argv[1].endswith(('deploy-research-context-v3.2.py', 'audit-research-rooms-v3.2.py')):
    with open({str(self.trace)!r}, 'a') as f: f.write('boundary:' + ' '.join(sys.argv[1:]) + '\\n')
    print('OFFLINE_BOUNDARY_REACHED')
else:
    os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])
''')

    def tool(self, name, body):
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o700)

    def run_installer(self, config=None, *args):
        if config is not None:
            self.config.write_text(config)
        return subprocess.run(['bash', str(self.script), *args], env=self.env,
                              capture_output=True, text=True, timeout=15)

    def test_real_install_entry_plain_quoted_and_crlf(self):
        for config in ('AGENT_NAME=ai2ai\n', 'AGENT_NAME="ai2ai"\n',
                       "AGENT_NAME='ai2ai'\n", '# comment\r\nAGENT_NAME=ai2ai\r\n',
                       '  AGENT_NAME = ai2ai  \n'):
            with self.subTest(config=config):
                result = self.run_installer(config)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('OFFLINE_BOUNDARY_REACHED', result.stdout)
                self.assertFalse(list(self.root.glob('stage.*')))

    def test_wrong_missing_duplicate_and_malformed_values_stop_before_download(self):
        for config in ('AGENT_NAME=love8\n', 'AGENT_NAME=aizong\n', '',
                       'AGENT_NAME=ai2ai\nAGENT_NAME=ai2ai\n',
                       'AGENT_NAME=ai2ai\nAGENT_NAME=love8\n',
                       'AGENT_NAME="ai2ai\n', "AGENT_NAME='ai2ai\"\n",
                       'AGENT_NAME=ai2ai-other\n'):
            with self.subTest(config=config):
                result = self.run_installer(config)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.trace.exists())
                self.assertFalse(list(self.root.glob('stage.*')))

    def test_no_source_no_secret_output_no_shell_expansion(self):
        sentinel = self.root / 'MUST_NOT_EXIST'
        config = f'AGENT_NAME=ai2ai\nBOT_TOKEN=secret-must-not-print\nDANGER=$(touch {shlex.quote(str(sentinel))})\n'
        result = self.run_installer(config)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(sentinel.exists())
        self.assertNotIn('secret-must-not-print', result.stdout + result.stderr)

    def test_missing_config_stops_before_download(self):
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.trace.exists())

    def test_nonroot_install_stops_before_config(self):
        self.tool('id', '#!/bin/sh\necho 1000\n')
        result = self.run_installer('AGENT_NAME=ai2ai\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.trace.exists())

    def test_audit_does_not_need_ai2ai_config_and_cleans_staging(self):
        result = self.run_installer(None, '--audit', '--read-public-room', '--topic', 'A2A 可靠性')
        self.assertEqual(result.returncode, 0, result.stderr)
        trace = self.trace.read_text()
        self.assertIn('download:audit-research-rooms-v3.2.py', trace)
        self.assertNotIn('download:research_context_v32.py', trace)
        self.assertNotIn('--install', trace)
        self.assertFalse(list(self.root.glob('stage.*')))

    def test_bad_checksum_stops_before_deploy_and_cleans_staging(self):
        self.tool('curl', '#!/bin/sh\nwhile [ "$1" != "-o" ]; do shift; done\nshift\nprintf corrupt > "$1"\n')
        result = self.run_installer('AGENT_NAME=ai2ai\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('OFFLINE_BOUNDARY_REACHED', result.stdout)
        self.assertFalse(list(self.root.glob('stage.*')))

    def test_deploy_failure_propagates_and_cleans_staging(self):
        self.tool('python3', f'''#!{sys.executable}
import os, sys
if sys.argv[1].endswith('deploy-research-context-v3.2.py'):
    sys.exit(23)
os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])
''')
        result = self.run_installer('AGENT_NAME=ai2ai\n')
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertFalse(list(self.root.glob('stage.*')))


if __name__ == '__main__':
    unittest.main()
