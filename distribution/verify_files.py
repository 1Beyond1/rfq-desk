"""Standard-library verification of the distributed, non-runtime file inventory."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
for entry in manifest['files']:
    path=(ROOT/entry['path']).resolve()
    if not path.is_relative_to(ROOT):raise SystemExit('Unsafe inventory path')
    data=path.read_bytes()
    if len(data)!=entry['size_bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:
        raise SystemExit('Changed: '+entry['path'])
print(f"Verified {len(manifest['files'])} distributed files. Runtime .venv/var are outside this inventory.")
