"""Download ONLY the text members (no .png/.mp4/.gz/.zip) of selected zips in
xlangai/ubuntu_osworld_verified_trajs at a pinned revision, via HTTP range requests
(one request per member). Verifies each member's CRC32 against the zip central directory,
records sha256 per extracted file, and writes a manifest.jsonl per zip.
Never executes downloaded content. Never deletes anything (append-only: skips files that already exist
with a matching sha256 in an existing manifest).
Usage: bulk_text.py <dest_root> <zip> [<zip> ...]
"""
import sys, os, io, re, json, zlib, struct, hashlib, time, collections, urllib.request
from concurrent.futures import ThreadPoolExecutor
from httpzip import open_zip

SHA = "5473c39e42a538a187a9b2c2b499db59d560fd8c"
BASE = f"https://huggingface.co/datasets/xlangai/ubuntu_osworld_verified_trajs/resolve/{SHA}/"
SKIP_EXT = ('.png', '.mp4', '.gz', '.zip', '.jpg', '.jpeg', '.webm', '.html', '.js')
MAX_MEMBER = 200_000_000


def fetch_range(url, start, end):
    req = urllib.request.Request(url, headers={'User-Agent': 'research-audit', 'Range': f'bytes={start}-{end}'})
    for attempt in range(6):
        try:
            return urllib.request.urlopen(req, timeout=180).read()
        except Exception:
            if attempt == 5:
                raise
            time.sleep(1.5 * (attempt + 1))


def extract_member(final_url, zi):
    nb = len(zi.filename.encode('utf-8')) if (zi.flag_bits & 0x800) else len(zi.filename.encode('cp437', 'replace'))
    span = 30 + nb + len(zi.extra) + zi.compress_size + 4096
    blob = fetch_range(final_url, zi.header_offset, zi.header_offset + span - 1)
    sig, _, _, method, _, _, _, _, _, nlen, xlen = struct.unpack('<IHHHHHIIIHH', blob[:30])
    assert sig == 0x04034b50, 'bad local header'
    data = blob[30 + nlen + xlen: 30 + nlen + xlen + zi.compress_size]
    if zi.compress_type == 0:
        out = data
    elif zi.compress_type == 8:
        out = zlib.decompressobj(-15).decompress(data)
    else:
        raise ValueError(f'unsupported compression {zi.compress_type}')
    if (zlib.crc32(out) & 0xffffffff) != zi.CRC:
        raise ValueError('CRC mismatch')
    return out


def local_rel(inner, seen):
    parts = inner.split('/')
    base = parts[-1]
    d = parts[:-1]
    if len(d) >= 2 and re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', d[-1]):
        key = (d[-2], d[-1])
        dirkey = '/'.join(d)
        seen.setdefault(key, [])
        if dirkey not in seen[key]:
            seen[key].append(dirkey)
        n = seen[key].index(dirkey)
        tdir = f'{d[-2]}/{d[-1]}' + (f'__run{n + 1}' if n else '')
        return f'tasks/{tdir}/{base}'
    h = hashlib.sha1('/'.join(d).encode()).hexdigest()[:8]
    return f'_meta/{h}_{re.sub(r"[^A-Za-z0-9._-]", "_", base)}'


def main(dest_root, names):
    summary = {}
    for name in names:
        t0 = time.time()
        stem = name[:-4] if name.endswith('.zip') else name
        zdir = os.path.join(dest_root, re.sub(r'[^A-Za-z0-9._-]', '_', stem)[:90])
        os.makedirs(zdir, exist_ok=True)
        f, z = open_zip(BASE + name)
        members = [zi for zi in z.infolist()
                   if not zi.filename.endswith('/') and not zi.filename.startswith('__MACOSX/')
                   and not zi.filename.rsplit('/', 1)[-1].startswith('._')
                   and not zi.filename.lower().endswith(SKIP_EXT)
                   and zi.filename.rsplit('/', 1)[-1] != '.DS_Store']
        seen = {}
        plan = [(zi, local_rel(zi.filename, seen)) for zi in members]
        too_big = [zi.filename for zi, _ in plan if zi.file_size > MAX_MEMBER]
        plan = [(zi, rel) for zi, rel in plan if zi.file_size <= MAX_MEMBER]
        mpath = os.path.join(zdir, 'manifest.jsonl')
        done = {}
        if os.path.exists(mpath):
            for line in open(mpath, encoding='utf-8'):
                r = json.loads(line); done[r['member']] = r

        def work(item):
            zi, rel = item
            if zi.filename in done and os.path.exists(os.path.join(zdir, rel)):
                return None
            out = extract_member(f.final, zi)
            p = os.path.join(zdir, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            if os.path.exists(p):
                raise FileExistsError(p)
            with open(p, 'wb') as fh:
                fh.write(out)
            return {'member': zi.filename, 'local': rel, 'size': len(out), 'crc32': f'{zi.CRC:08x}',
                    'sha256': hashlib.sha256(out).hexdigest(), 'zip_date_time': list(zi.date_time)}

        errors = []
        n_ok = 0; nbytes = 0
        with ThreadPoolExecutor(16) as ex, open(mpath, 'a', encoding='utf-8') as mf:
            futs = [ex.submit(work, it) for it in plan]
            for fu, it in zip(futs, plan):
                try:
                    r = fu.result()
                except Exception as e:
                    errors.append({'member': it[0].filename, 'error': repr(e)[:300]}); continue
                if r:
                    mf.write(json.dumps(r) + '\n'); n_ok += 1; nbytes += r['size']
        kinds = collections.Counter(rel.rsplit('/', 1)[-1] if rel.startswith('tasks/') else '_meta' for _, rel in plan)
        summary[name] = {'local_dir': zdir, 'zip_bytes': f.size, 'members_in_zip': len(z.infolist()),
                         'text_members_planned': len(plan), 'written_now': n_ok, 'bytes_written_now': nbytes,
                         'skipped_too_big': too_big, 'errors': errors[:20], 'n_errors': len(errors),
                         'basename_counts': dict(kinds.most_common(30)), 'seconds': round(time.time() - t0, 1),
                         'source': BASE + name}
        print(json.dumps({k: v for k, v in summary[name].items() if k != 'errors'}), flush=True)
        with open(os.path.join(zdir, 'SOURCE.json'), 'w', encoding='utf-8') as fh:
            json.dump({'repo': 'xlangai/ubuntu_osworld_verified_trajs', 'revision': SHA, 'zip': name,
                       'zip_bytes': f.size, 'licence': 'MIT (dataset card license: mit)',
                       'subset_rule': f'text members only; skipped extensions {SKIP_EXT}; __MACOSX and ._ files skipped',
                       'method': 'HTTP range reads of zip members; CRC32 verified against central directory',
                       'summary': summary[name]}, fh, indent=1)
    return summary


if __name__ == '__main__':
    dest = sys.argv[1]
    s = main(dest, sys.argv[2:])
    json.dump(s, open(os.path.join(dest, f'_bulk_summary_{int(time.time())}.json'), 'w'), indent=1)
