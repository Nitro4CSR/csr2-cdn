"""Zero-network CLI for locating official Android visual library asset files."""
from __future__ import annotations

import argparse
import json
from typing import Optional

from .visual_asset_plan import VISUAL_ASSET_SLOTS, PENDING_VISUAL_ASSET_SLOTS, plan_visual_assets_from_file


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description='Plan offline visual asset downloads from an existing asset database')
    parser.add_argument('--asset-database', required=True, help='local asset_database_* file, not a game folder')
    parser.add_argument('--slot', action='append', choices=VISUAL_ASSET_SLOTS,
                        help='specific cosmetic slot; repeat as needed (default: pending only)')
    parser.add_argument('--all', action='store_true', help='include previously decoded libraries as well')
    parser.add_argument('--quality', choices=('ASTC', 'High'), default='ASTC',
                        help='Android ASTC (default); High needs separate validation')
    parser.add_argument('--show-urls', action='store_true', help='include CDN URLs in the JSON output')
    args = parser.parse_args(argv)
    if args.slot and args.all:
        parser.error('--slot and --all are mutually exclusive')
    slots = tuple(args.slot) if args.slot else (VISUAL_ASSET_SLOTS if args.all else PENDING_VISUAL_ASSET_SLOTS)
    try:
        plan = plan_visual_assets_from_file(args.asset_database, slots=slots, quality=args.quality)
    except (OSError, ValueError):
        print(json.dumps({'status': 'invalid_offline_database', 'mode': 'offline', 'network_requests': 0}))
        return 2
    results = [dict(slot=x.slot, code=x.code, version=x.version, size_bytes=x.size_bytes,
                    filename=x.filename, decoder_status=x.decoder_status,
                    roster_join_status=x.roster_join_status,
                    **({'url': x.url} if args.show_urls else {})) for x in plan.candidates]
    print(json.dumps({'status': 'ready' if not plan.absent_slots else 'partial',
                      'mode': 'offline', 'network_requests': 0,
                      'database_version': plan.database_version,
                      'product_version': plan.product_version,
                      'branch_name': plan.branch_name,
                      'platform': plan.platform, 'quality': plan.quality,
                      'asset_count': len(results), 'total_bytes': plan.total_bytes,
                      'missing_slots': list(plan.absent_slots), 'assets': results}, indent=2))
    return 0 if not plan.absent_slots else 2


if __name__ == '__main__':
    raise SystemExit(main())
