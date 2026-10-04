"""B7: licence classes of the GitHub repositories whose sessions SWE-chat (pinned f66cca95) redistributes.

ODC-BY 1.0 s.2.4: the licence does not cover rights in individual Contents. SWE-chat transcripts embed repo content
(file reads, diffs), so the repo licence travels with the Contents. This counts repos and sessions per licence class.
Metadata only (sessions.parquet, repositories.parquet); no transcript content is read.

Output: analysis/out/phase_e/track_b/B7/repo_licences.json
Run:    python analysis/out/phase_e/track_b/B7/repo_licences.py
"""
import json, os, collections
import pyarrow.parquet as pq

DATA = os.path.join(os.environ.get("SWARMS_DATA", "C:/Swarms/data"), "swe-chat-pinned")
OUT = os.path.join(os.path.dirname(__file__), "repo_licences.json")

PERMISSIVE = {"MIT", "Apache-2.0", "ISC", "CC0-1.0", "WTFPL", "MIT-0", "BSD-2-Clause", "BSD-3-Clause", "Unlicense"}
COPYLEFT = {"AGPL-3.0", "GPL-3.0", "GPL-3.0-or-later", "GPL-2.0", "LGPL-3.0", "MPL-2.0"}
SOURCE_AVAILABLE = {"Elastic License 2.0", "FSL-1.1-ALv2", "FSL-1.1-Apache-2.0", "O'Saasy", "BUSL-1.1"}


def cls(lic):
    if lic in PERMISSIVE:
        return "permissive"
    if lic in COPYLEFT:
        return "copyleft"
    if lic in SOURCE_AVAILABLE:
        return "source_available_non_osi"
    return "other_or_null"


repos = pq.read_table(os.path.join(DATA, "repositories.parquet"), columns=["repo_id", "license_type"]).to_pydict()
lic_of = dict(zip(repos["repo_id"], repos["license_type"]))
sess = pq.read_table(os.path.join(DATA, "sessions.parquet"), columns=["session_id", "repo_id"]).to_pydict()

repo_by_lic = collections.Counter(repos["license_type"])
repo_by_cls = collections.Counter(cls(l) for l in repos["license_type"])
sess_by_cls = collections.Counter(cls(lic_of.get(r)) for r in sess["repo_id"])
sess_unmatched = sum(1 for r in sess["repo_id"] if r not in lic_of)

json.dump({"script": "analysis/out/phase_e/track_b/B7/repo_licences.py", "source": DATA,
           "repos": len(repos["repo_id"]), "repos_by_license_type": dict(repo_by_lic.most_common()),
           "repos_by_class": dict(repo_by_cls), "sessions": len(sess["session_id"]),
           "sessions_by_repo_licence_class": dict(sess_by_cls), "sessions_repo_not_in_repositories": sess_unmatched,
           "classes": {"permissive": sorted(PERMISSIVE), "copyleft": sorted(COPYLEFT),
                       "source_available_non_osi": sorted(SOURCE_AVAILABLE)}},
          open(OUT, "w", encoding="utf-8"), indent=1)
print(open(OUT, encoding="utf-8").read())
