"""Record one real GET to a fixture file: record_fixture.py <source> <url> <out_path>.

Respect rate limits: call at most once per second per source.
"""
import sys
from pathlib import Path

import httpx

CONTACT_URL = "https://github.com/album-explorer"


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    _source, url, out_path = argv[1:]
    try:
        from django.conf import settings

        contact = settings.CONTACT_URL if settings.configured else CONTACT_URL
    except Exception:  # noqa: BLE001
        contact = CONTACT_URL
    response = httpx.get(
        url,
        headers={"User-Agent": f"AlbumExplorer/0.1 ( {contact} )"},
        timeout=30,
        follow_redirects=True,
    )
    response.raise_for_status()
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    print(f"wrote {path} ({len(response.content)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
