#!/usr/bin/env python
"""Download the labelled spoof dataset (release asset) and extract it to ./dataset. Stdlib only.

    python scripts/download_dataset.py                      # -> ./dataset
    python scripts/download_dataset.py --dest D:/data/wfv   # anywhere else (then: --data D:/data/wfv or WFV_DATA)
    python scripts/download_dataset.py --file spoof_dataset_v1.tar.xz   # extract an archive you downloaded by hand

Downloads spoof_dataset_v1.tar.xz (25.6 MB; Python's tarfile/lzma extract it, no extra tools) from
https://github.com/arunkumap26/witness-free-verifier/releases/download/v1.0.0/ . Each download is checked against the
sha256 recorded at release time (MANIFEST.json of the release) before anything is extracted. Set WFV_DATASET_URL to
download from a mirror instead (a URL prefix ending in /).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("WFV_DATASET_URL",            # override for a mirror; must end with /
                      "https://github.com/arunkumap26/witness-free-verifier/releases/download/v1.0.0/")
# filled from the release MANIFEST.json; an asset whose sha256 differs is rejected (use --no-verify to override)
ASSETS = {
    "spoof_dataset_v1.tar.xz": "c630aa7c37c1ea29778caad0cdcc9b13b47451cf5d20f487b9e60fc69a514d2b",
}
# Members live under dataset/ (tar.xz) or spoof_dataset_v1/ (the two split zips also on the release page:
# spoof_dataset_v1_db.zip + spoof_dataset_v1_transcripts.zip; --file each of them in turn. They lack rows.jsonl,
# which only the rule-baseline column of score_dataset.py reads.)
PREFIXES = ("dataset/", "spoof_dataset_v1/")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fetch(url: str, dst: Path) -> bool:
    """Download url to dst with a progress line. False on HTTP 404 (asset not published), raises on other errors."""
    req = urllib.request.Request(url, headers={"User-Agent": "witness-free-verifier/1.0 (download_dataset.py)"})
    try:
        r = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise
    total = int(r.headers.get("Content-Length") or 0)
    done, t0, last = 0, time.time(), 0.0
    tty = sys.stdout.isatty()
    with r, open(dst, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
            done += len(b)
            if tty and time.time() - last > 0.5:
                last = time.time()
                pct = f"{100 * done / total:5.1f}%" if total else ""
                print(f"\r  {done / 1e6:7.1f} MB {pct}  {done / 1e6 / max(time.time() - t0, 1e-6):5.1f} MB/s",
                      end="", flush=True)
    print((f"\r  {done / 1e6:7.1f} MB in {time.time() - t0:.0f}s" + " " * 20) if tty else
          f"  {done / 1e6:.1f} MB in {time.time() - t0:.0f}s")
    return True


def _target(dest: Path, name: str) -> Path | None:
    """Archive member -> path under dest (leading 'dataset/' stripped); None for the root dir entry or unsafe names."""
    n = name.replace("\\", "/")
    for pre in PREFIXES:
        if n.startswith(pre):
            n = n[len(pre):]
            break
    n = n.strip("/")
    parts = n.split("/")                  # split zips: transcripts/<block>/transcripts/<sid>.jsonl -> transcripts/<block>/
    if len(parts) == 4 and parts[0] == "transcripts" and parts[2] == "transcripts":
        n = "/".join(parts[:2] + parts[3:])
    if not n:
        return None
    p = (dest / n).resolve()
    if dest.resolve() not in p.parents:
        raise SystemExit(f"refusing unsafe archive member: {name}")
    return p


def extract(archive: Path, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for m in z.infolist():
                p = _target(dest, m.filename)
                if p is None or m.is_dir():
                    continue
                p.parent.mkdir(parents=True, exist_ok=True)
                with z.open(m) as src, open(p, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
                n += 1
    else:
        with tarfile.open(archive, "r:*") as t:
            for m in t:
                if not m.isfile():
                    continue
                p = _target(dest, m.name)
                if p is None:
                    continue
                p.parent.mkdir(parents=True, exist_ok=True)
                with t.extractfile(m) as src, open(p, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
                n += 1
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Download + extract the spoof_dataset_v1 release asset.")
    ap.add_argument("--dest", default=str(ROOT / "dataset"), help="where to extract (default: ./dataset)")
    ap.add_argument("--file", help="extract this local archive instead of downloading")
    ap.add_argument("--asset", choices=sorted(ASSETS), help="download only this asset")
    ap.add_argument("--force", action="store_true", help="extract even if the dataset is already there")
    ap.add_argument("--no-verify", action="store_true", help="skip the sha256 check")
    ap.add_argument("--keep", action="store_true", help="keep the downloaded archive next to --dest")
    a = ap.parse_args(argv)
    dest = Path(a.dest)
    if (dest / "spoof_v1.db").is_file() and not a.force and not a.file:
        print(f"dataset already present: {dest / 'spoof_v1.db'}  (use --force to re-extract)")
        return 0

    if a.file:
        archive, tmp = Path(a.file), None
        if not archive.is_file():
            raise SystemExit(f"no such file: {archive}")
    else:
        tmp = Path(tempfile.mkdtemp(prefix="wfv_dl_"))
        order = [a.asset] if a.asset else list(ASSETS)
        archive = None
        for name in order:
            url = BASE + name
            print(f"downloading {url}")
            dst = tmp / name
            try:
                ok = fetch(url, dst)
            except (urllib.error.URLError, OSError) as e:
                print(f"  failed: {e}")
                continue
            if not ok:
                print("  not published (404), trying the next format")
                continue
            want = ASSETS[name]
            got = sha256(dst)
            if not a.no_verify and not want.startswith("__") and got != want:
                raise SystemExit(f"sha256 mismatch for {name}: got {got}, expected {want}. Not extracting.")
            print(f"  sha256 {got}" + ("  (verified)" if not want.startswith("__") and not a.no_verify else ""))
            archive = dst
            break
        if archive is None:
            raise SystemExit("could not download the dataset. Download an asset by hand from\n  "
                             "https://github.com/arunkumap26/witness-free-verifier/releases/tag/v1.0.0\n"
                             "and run: python scripts/download_dataset.py --file <archive>")
    t0 = time.time()
    shown = os.path.relpath(dest) if dest.resolve().is_relative_to(Path.cwd().resolve()) else str(dest)
    print(f"extracting {archive.name} -> {shown}")
    n = extract(archive, dest)
    n_tr = sum(1 for _ in (dest / "transcripts").glob("*/*.jsonl"))
    print(f"  {n} files in {time.time() - t0:.0f}s; spoof_v1.db present: {(dest / 'spoof_v1.db').is_file()}; "
          f"honest transcripts: {n_tr}")
    if tmp is not None:
        if a.keep:
            shutil.move(str(archive), str(dest.parent / archive.name))
        shutil.rmtree(tmp, ignore_errors=True)
    if not (dest / "spoof_v1.db").is_file():
        raise SystemExit("extraction finished but spoof_v1.db is missing; the archive is not the expected one")
    if dest.resolve() != (ROOT / "dataset").resolve():
        print(f"dataset is not at ./dataset; pass --data {dest} to score_dataset.py (or set WFV_DATA={dest})")
    print("done. next: python scripts/score_dataset.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
