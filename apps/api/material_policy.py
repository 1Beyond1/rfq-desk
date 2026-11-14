"""Recognise known official originals without shipping their contents to a public demo."""
import hashlib
import json
from pathlib import Path
import re

MANIFEST = Path(__file__).with_name('official_hashes.json')


def known_hashes(root):
    try:
        data = json.loads(MANIFEST.read_text(encoding='utf-8'))
        hashes = data['sha256']
        if data['schema'] != 1 or not isinstance(hashes, list) or not hashes:
            raise ValueError('invalid manifest')
        if any(not isinstance(h, str) or not re.fullmatch('[0-9a-f]{64}', h) for h in hashes):
            raise ValueError('invalid fingerprint')
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ValueError('官方素材指纹清单不可用，已停止模型请求；请检查部署文件') from e
    # Also protect newly added local originals before the deployment manifest is rebuilt.
    local = Path(root) / 'data/raw/official-rfq'
    return set(hashes) | {hashlib.sha256(p.read_bytes()).hexdigest() for p in local.rglob('*') if p.is_file()}


def check_remote_materials(materials, root):
    known = known_hashes(root)
    # Includes attachments, which have their own byte hashes in the canonical material view.
    if any(f['sha256'] in known for f in materials['files']):
        raise ValueError('这张工作单含已知官方素材，不发送给模型；请用本地解析或合成样例')
