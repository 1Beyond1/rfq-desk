"""Build a hash-only deployment manifest locally; never copy the official originals."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.api.materials import material_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'data/raw/official-rfq')
    parser.add_argument('--output', type=Path, default=ROOT / 'apps/api/official_hashes.json')
    args = parser.parse_args()
    originals = [p for p in args.source.rglob('*') if p.is_file()]
    if not originals:
        parser.error('No originals found; existing manifest was left unchanged.')
    hashes = {f['sha256'] for p in originals for f in material_files(p.name, p.read_bytes())}
    args.output.write_text(json.dumps({'schema': 1, 'sha256': sorted(hashes)}, indent=2) + '\n', encoding='utf-8')
    print(f'Wrote {len(hashes)} fingerprints; no original text or filenames included.')


if __name__ == '__main__':
    main()
