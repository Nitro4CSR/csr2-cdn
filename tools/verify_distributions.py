"""Verify the wheel outside the checkout and the complete extracted sdist."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]

def run(python, *args, cwd):
    subprocess.run([str(python), *map(str, args)], cwd=cwd, check=True)

with tempfile.TemporaryDirectory(prefix='csr2-release-check-') as temp:
    temp = Path(temp)
    for kind, pattern in [('wheel', '*.whl'), ('sdist', '*.tar.gz')]:
        artifacts = list((ROOT / 'dist').glob(pattern))
        if len(artifacts) != 1:
            raise RuntimeError('Expected exactly one ' + kind)
        work = temp / kind
        work.mkdir()
        venv.EnvBuilder(with_pip=True).create(work / 'venv')
        python = work / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        artifact = artifacts[0]
        run(python, '-m', 'pip', 'install', str(artifact) + '[dev,events,attestation]', cwd=work)
        if kind == 'wheel':
            tests = work / 'tests'
            tests.mkdir()
            for source in (ROOT / 'tests').glob('*.py'):
                content = source.read_text(encoding='utf-8')
                # Research scaffolding intentionally ships only in the sdist.
                if 'csr2cdn._research' not in content:
                    shutil.copy2(source, tests / source.name)
            shutil.copytree(ROOT / 'tests' / 'fixtures', tests / 'fixtures')
            shutil.copytree(ROOT / 'docs', work / 'docs')
            run(python, '-c', 'import csr2cdn; print(csr2cdn.__version__, csr2cdn.__file__)', cwd=work)
            run(python, '-m', 'pytest', '-q', 'tests', cwd=work)
        else:
            sources = work / 'source'
            with tarfile.open(artifact) as archive:
                archive.extractall(sources, filter='data')
            source = next(sources.iterdir())
            run(python, '-m', 'pytest', '-q', cwd=source)
        run(python, '-m', 'csr2cdn.prestige_release_validation', '--ui-window', '--crew-filtered', cwd=work)
        run(python, '-m', 'csr2cdn.crew_season_validation', '--simulate', cwd=work)
