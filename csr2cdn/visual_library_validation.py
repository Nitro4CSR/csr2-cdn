"""Offline, privacy-safe ASTC visual library inspection and record verification."""
from __future__ import annotations

import argparse
import json
from typing import Optional

from .visual_library_bundle import (VisualLibrarySourceError,
                                     load_visual_unityfs)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description='Inspect original CSR2 Android ASTC visual libraries locally')
    parser.add_argument('--asset', action='append', default=[], required=True,
                        help='local supported Car*Library.ASTC asset; repeat as needed')
    parser.add_argument('--show-examples', action='store_true',
                        help='opt in to showing at most three visual names per source')
    args = parser.parse_args(argv)
    results = []
    status = 'ok'
    for filename in args.asset:
        try:
            from pathlib import Path
            library = Path(filename).name.split('.')[0]
            result = load_visual_unityfs(filename, library=library)
            rows = result.records
            info = {'source_library': library, 'status': 'decoded',
                    'rows': len(rows), 'unique_ids': len(set(x.code for x in rows)),
                    'scope': ('tnr_source_ids_category_scoped_join_candidate'
                              if library.startswith('CarTunerStars') else 'global_library_ids'), 'source_sha256': rows[0].source_sha256,
                    'interior_zone_names': library in ('CarInteriorLibrary', 'CarTunerStarsInteriorLibrary'),
                    'version_is_from_filename_only': True}
            if args.show_examples:
                info['examples'] = [{'code': x.code, 'name': x.name, 'names': list(x.names)}
                                    for x in rows[:3]]
        except (OSError, ValueError, TypeError, VisualLibrarySourceError):
            status = 'partial_failure'
            info = {'status': 'unsupported_or_invalid_source', 'details': 'suppressed'}
        results.append(info)
    print(json.dumps({'status': status, 'mode':'offline', 'network_requests': 0,
                      'source_files': results}, indent=2, ensure_ascii=False))
    return 0 if status == 'ok' else 2


if __name__ == '__main__':
    raise SystemExit(main())
