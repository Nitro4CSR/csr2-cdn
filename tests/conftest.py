"""Shared test fixtures."""
import pytest


# --- symlink capability -------------------------------------------------
# Several tests assert that loaders *reject* a symlinked input. Creating the
# symlink to test with needs a privilege Windows withholds unless Developer
# Mode is on, which made seven tests fail for an OS setting rather than a
# defect. They skip instead, so a real regression is not buried in noise.
#
# Tradeoff, stated plainly: where symlinks cannot be created the rejection
# path goes unexercised. It is still covered on any POSIX run and in CI.
def _can_create_symlink() -> bool:
    import pathlib as _p, tempfile as _t
    try:
        with _t.TemporaryDirectory() as d:
            target = _p.Path(d) / "target"
            target.write_text("x", encoding="utf-8")
            (_p.Path(d) / "link").symlink_to(target)
        return True
    except (OSError, NotImplementedError, AttributeError):
        return False


SYMLINKS_AVAILABLE = _can_create_symlink()
requires_symlinks = pytest.mark.skipif(
    not SYMLINKS_AVAILABLE,
    reason="creating a symlink needs a privilege this OS/user lacks "
           "(Windows without Developer Mode)")
