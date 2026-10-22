"""Entrypoint for offline visual library comparison; avoids runpy import warnings."""
from .visual_source_delta import main

if __name__ == "__main__":
    raise SystemExit(main())
