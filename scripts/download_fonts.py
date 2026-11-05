"""Vendor open font assets from the Google Fonts repository, including OFL licenses."""
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ("barlowcondensed/BarlowCondensed-SemiBold.ttf", "display.ttf"),
    ("barlowcondensed/BarlowCondensed-ExtraBoldItalic.ttf", "display-italic.ttf"),
    ("barlow/Barlow-Regular.ttf", "body.ttf"),
    ("barlow/Barlow-SemiBold.ttf", "body-semibold.ttf"),
    ("ibmplexmono/IBMPlexMono-Regular.ttf", "mono.ttf"),
    ("barlowcondensed/OFL.txt", "LICENSE-display.txt"),
    ("barlow/OFL.txt", "LICENSE-body.txt"),
    ("ibmplexmono/OFL.txt", "LICENSE-mono.txt"),
]


def main():
    target = ROOT / "apps/web/public/fonts"
    target.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for source,name in FILES:
            response = client.get("https://raw.githubusercontent.com/google/fonts/main/ofl/" + source)
            response.raise_for_status()
            (target / name).write_bytes(response.content)
            print(f"Saved {name}", flush=True)


if __name__ == "__main__":
    main()
