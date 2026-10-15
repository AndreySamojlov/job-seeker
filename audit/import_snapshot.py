"""One-time recovery import from an immutable Git archive; no source mutations."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(r'C:\Users\samoj\Documents\Claude\Projects\Поиск работы')
COMMIT = '842e46a1f436d31ad2cad5d0a49830356d818907'
SELECTED = ['src', 'tests', 'db/migrations', 'config', 'pyproject.toml',
            'uv.lock', '.python-version', '.gitattributes', 'scripts/requeue_quick_skips.py']

def main():
    entries = []
    with tempfile.TemporaryDirectory(prefix='job-machine-import-') as tmp:
        archive = Path(tmp) / 'source.zip'
        subprocess.run(['git', '-C', str(SOURCE), 'archive', '--format=zip',
                        f'--output={archive}', COMMIT, *SELECTED], check=True)
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                dest = (ROOT / info.filename).resolve()
                if not dest.is_relative_to(ROOT):
                    raise ValueError('Archive path escapes project')
                data = z.read(info)
                if dest.exists() and dest.read_bytes() != data:
                    raise ValueError(f'Refusing overwrite: {info.filename}')
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                digest = hashlib.sha256(data).hexdigest()
                entries.append({'path': info.filename, 'source_sha256': digest,
                                'target_sha256': digest, 'adaptation': None})
    manifest = {'schema_version': 1, 'repository': str(SOURCE), 'source_commit': COMMIT,
                'files': entries, 'excluded': ['runtime', 'secrets', 'personal artifacts',
                'historical instructions and plans', 'MCP configuration', 'deploy/cron scripts']}
    (ROOT / 'provenance').mkdir(exist_ok=True)
    (ROOT / 'provenance/baseline.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f'Imported and hashed {len(entries)} files from {COMMIT}')

if __name__ == '__main__':
    main()
