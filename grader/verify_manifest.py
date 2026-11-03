#!/usr/bin/env python3
"""Verify shared trusted files; mutable answer/generated files are explicitly excluded."""
import hashlib
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'grader/manifest.json').read_text())
for name,digest in manifest.items():
    if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:
        raise SystemExit('hash mismatch: '+name)
print('verified %d trusted files' % len(manifest))
