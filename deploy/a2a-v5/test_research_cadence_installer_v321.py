"""Run the actual shell entry offline with only downloads/deployment mocked."""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class ShellEntry(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.config = self.root / 'config.env'
        self.trace = self.root / 'trace'
        source = (HERE / 'install-research-cadence-v3.2.1.sh').read_text()
        self.ref = re.search(r'core_ref="([0-9a-f]{40})"', source).group(1)
        self.script = self.root / 'install.sh'
        self.script.write_text(source.replace('config="/opt/technocore-a2a/.env"', f'config="{self.config}"').replace(
            '/root/tc-a2a-cadence-v321-stage.', str(self.root / 'stage.')))
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'])
        self.tool('id', '#!/bin/sh\necho 0\n')
        self.tool('curl', f'''#!{sys.executable}
import pathlib, shutil, sys
args = sys.argv[1:]
assert {self.ref!r} in args[args.index('-o')-1]
pathlib.Path({str(self.trace)!r}).write_text('download')
shutil.copyfile({str(HERE / 'repair-research-cadence-v3.2.1.py')!r}, args[args.index('-o')+1])
''')
        self.tool('python3', f'''#!{sys.executable}
import os, sys
if sys.argv[1] == '-B':
    print('OFFLINE_DEPLOY_BOUNDARY')
else:
    os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])
''')

    def tool(self, name, text):
        p = self.bin / name
        p.write_text(text)
        p.chmod(0o700)

    def run_script(self, config='AGENT_NAME=ai2ai', *args):
        self.config.write_text(config)
        return subprocess.run(['bash', str(self.script), *args], env=self.env, text=True,
                              capture_output=True, timeout=15)

    def test_pinned_checksum_and_real_shell_preflight(self):
        for data in ('AGENT_NAME=ai2ai', 'AGENT_NAME="ai2ai"', "AGENT_NAME='ai2ai'\r\n"):
            result = self.run_script(data)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('OFFLINE_DEPLOY_BOUNDARY', result.stdout)
            self.assertFalse(list(self.root.glob('stage.*')))

    def test_wrong_node_or_duplicate_refused_before_download(self):
        for data in ('AGENT_NAME=love8', 'AGENT_NAME=aizong', '', 'AGENT_NAME=ai2ai\nAGENT_NAME=ai2ai'):
            result = self.run_script(data)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(self.trace.exists())

    def test_no_shell_expansion_or_secret_output(self):
        p = self.root / 'bad'
        result = self.run_script(f'AGENT_NAME=ai2ai\nTOKEN=must-not-appear\nDANGER=$(touch {p})')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(p.exists())
        self.assertNotIn('must-not-appear', result.stdout + result.stderr)

    def test_bad_checksum_blocks_execution(self):
        self.tool('curl', f'''#!{sys.executable}
import pathlib, sys
pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text('invalid')
''')
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('OFFLINE_DEPLOY_BOUNDARY', result.stdout)
        self.assertFalse(list(self.root.glob('stage.*')))

    def test_deploy_failure_exits_nonzero(self):
        self.tool('python3', f'''#!{sys.executable}
import os, sys
if sys.argv[1] == '-B': sys.exit(23)
os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])
''')
        result = self.run_script()
        self.assertEqual(result.returncode, 23)
        self.assertFalse(list(self.root.glob('stage.*')))

    def test_nonroot_and_unexpected_argument_refused(self):
        result = self.run_script('AGENT_NAME=ai2ai', '--force')
        self.assertNotEqual(result.returncode, 0)
        self.tool('id', '#!/bin/sh\necho 1000\n')
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.trace.exists())


if __name__ == '__main__':
    unittest.main()
