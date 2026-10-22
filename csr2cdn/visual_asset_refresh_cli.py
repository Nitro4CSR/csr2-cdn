"""CLI entry point separated from public API imports for clean -m execution."""
from .visual_asset_refresh import main

if __name__ == '__main__':
    raise SystemExit(main())
