"""Compose analysis/out/phase_e/track_b/B5c_web_os_agents.json from:
  - b5c_field_audit.json (descriptive census of the downloaded corpora; produced by b5c_field_audit.py)
  - osworld_verified_zip_census.json (central-directory census of every zip in the OSWorld-Verified repo; cd_all.py)
  - SOURCE.json / manifest files written by the downloaders (bulk_text.py, wai_fill.py)
Text fields (verdicts, interpretation) are written here by hand and marked as such; numbers are read from files.
"""
import json, os, glob, hashlib, collections

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'B5c_web_os_agents.json')
AUD = json.load(open(os.path.join(HERE, 'b5c_field_audit.json')))
CEN = json.load(open(os.path.join(HERE, 'osworld_verified_zip_census.json')))
OSW = 'C:/Swarms/data/acquired/osworld_verified_trajs'
WAI = 'C:/Swarms/data/acquired/webarena_infinity_trajs'
OSW_SHA = '5473c39e42a538a187a9b2c2b499db59d560fd8c'
WAI_SHA = '73cf7f57a6ff61c95722a23bffdd9c1de4069bfe'


def dir_bytes(p):
    t = 0
    for r, _, fs in os.walk(p):
        if '.cache' in r:
            continue
        for f in fs:
            t += os.path.getsize(os.path.join(r, f))
    return t


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as fh:
        for b in iter(lambda: fh.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


# ---------- OSWorld-Verified: downloaded subset ----------
osw_sub = {}
for zdir in sorted(glob.glob(os.path.join(OSW, '*'))):
    sp = os.path.join(zdir, 'SOURCE.json')
    if not os.path.exists(sp):
        continue
    src = json.load(open(sp))
    a = AUD['osworld_verified'].get(os.path.basename(zdir), {})
    man = os.path.join(zdir, 'manifest.jsonl')
    osw_sub[os.path.basename(zdir)] = {
        'zip': src['zip'], 'zip_bytes': src['zip_bytes'],
        'text_members_written': src['summary']['written_now'] if src['summary'].get('written_now') else None,
        'text_members_planned': src['summary']['text_members_planned'],
        'download_errors': src['summary']['n_errors'],
        'local_bytes': dir_bytes(zdir),
        'manifest_sha256': sha256_file(man) if os.path.exists(man) else None,
        'audit': a,
    }
osw_local_bytes = sum(v['local_bytes'] for v in osw_sub.values())

# whole-repo census numbers (all 99 zips; central directories only)
zips = CEN['zips']
cen_tot = {
    'zips': len(zips),
    'zip_bytes_total': sum(z.get('zip_bytes', 0) for z in zips.values()),
    'task_run_dirs_with_traj_jsonl': sum(z.get('n_traj', 0) for z in zips.values()),
    'traj_jsonl_bytes_total': sum(z.get('bytes', {}).get('traj.jsonl', 0) for z in zips.values()),
    'runtime_log_bytes_total': sum(z.get('bytes', {}).get('runtime.log', 0) for z in zips.values()),
    'png_files_total': sum(z.get('counts', {}).get('png', 0) for z in zips.values()),
    'zips_without_traj_jsonl': sorted(n for n, z in zips.items() if z.get('n_traj', 0) == 0),
}

# ---------- WebArena-Infinity: downloaded subset ----------
wai_src = json.load(open(os.path.join(WAI, 'SOURCE.json')))
wai_aud = AUD.get('webarena_infinity') or {}
wai_local = dir_bytes(WAI)

json.dump({'osw_sub': osw_sub, 'cen_tot': cen_tot, 'wai_src': wai_src, 'wai_aud': wai_aud, 'wai_local': wai_local,
           'osw_local_bytes': osw_local_bytes}, open(os.path.join(HERE, '_compose_inputs.json'), 'w'), indent=1, default=str)
print('osw submissions', len(osw_sub), 'osw bytes', osw_local_bytes, 'wai bytes', wai_local)
