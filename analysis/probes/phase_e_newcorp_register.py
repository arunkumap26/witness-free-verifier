"""Register the Track-B-acquired corpora as pre-registered extensions (prereg_e.json splits.new_corpora) BEFORE any B/E read.

For each analysis/out/phase_e/prereg_e_extensions/<corpus>.json: verify the calibration file's sha256, then append one change_log entry
to analysis/prereg_e.json. Append one entry recording the orchestrator decisions the builders and their verifier asked for. Merge the per-
corpus held-out manifests into analysis/HELDOUT_MANIFEST.json. Write the agentcap exclusion list (sessions exposed by an abandoned split)
to analysis/out/phase_e/newcorp_exclusions.json. check_frozen() hashes only prereg_e_common.py, so appending here does not break it."""
import glob, hashlib, json, os

AN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(AN, "out", "phase_e")
WHEN = "2026-10-04 (orchestrator, before any new-corpus B/E read)"


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def main():
    pj_path = os.path.join(AN, "prereg_e.json")
    pj = json.load(open(pj_path, encoding="utf-8"))
    log = pj.setdefault("change_log", [])
    done = {e.get("corpus") for e in log if isinstance(e, dict)}
    report = {"extensions": [], "mismatches": []}
    for f in sorted(glob.glob(os.path.join(OUT, "prereg_e_extensions", "*.json"))):
        ext = json.load(open(f, encoding="utf-8"))
        c = ext["corpus"]
        cal = os.path.join(os.path.dirname(AN), ext["calibration_file"]) if not os.path.isabs(ext["calibration_file"]) else ext["calibration_file"]
        got = sha(cal)
        ok = got == ext["calibration_sha256"]
        if not ok:
            report["mismatches"].append({"corpus": c, "recorded": ext["calibration_sha256"], "on_disk": got})
        report["extensions"].append({"corpus": c, "calibration_sha256_ok": ok, "extension_record_sha256": sha(f)})
        if c not in done:
            log.append({"when": WHEN, "kind": "pre-registered extension (splits.new_corpora)", "corpus": c,
                        "calibration_file": ext["calibration_file"], "calibration_sha256": got, "calibration_sha256_matches_record": ok,
                        "extension_record": os.path.relpath(f, os.path.dirname(AN)).replace("\\", "/"), "extension_record_sha256": sha(f)})
    decisions = {
        "when": WHEN, "kind": "orchestrator decisions for new corpora (requested by the builders and their verifier)",
        "D1_calibration_unit_proxy": "Accepted as each builder used it; measurement scripts must pass the same unit argument: pub_cc_hf and "
                                     "pub_trace_commons -> 'cc_local' (same Claude Code generation); pub_codex -> 'swechat/codex'; agentcap -> "
                                     "'swechat/opencode' (OpenCode traces) and 'agentcap/pi' (Pi traces); tbench2 and glm_tb21 -> their own names. "
                                     "Quantities calibrate_unit did not produce for a unit (e.g. N1 bounds, N5 truncation constants where absent) "
                                     "take the pre-registered pooled values where the prereg defines one, else the cell is NOT_TESTABLE.",
        "D2_dominance_cluster": "For new corpora, the AC4 dominance and confinement cluster is the corpus stratum (source repo / submitting agent / "
                                "modal model), because prereg_e_common.session_cluster_map has no new-corpus branch.",
        "D3_split_floor": "New-corpus splits use floor = min(5, n_draw // n_cells) per cell (lib/sample._alloc does not cap floors; with many "
                          "cells the floors alone exceed the draw). Applied uniformly by all builders; recorded per corpus as floor_used.",
        "D4_field_audit_criteria": "Accepted as drawn: the builders' field audits are not identical (agentcap and pub_codex keep tool-less sessions, "
                                   "pub_cc_* exclude them; tbench2 keeps sessions whose stamps are nulled by the collapsed-stamp rule). "
                                   "Redrawing after A calibration would be worse; cross-corpus comparisons must state it.",
        "D5_agentcap_exposure": "The 42 B and 15 E agentcap sessions parsed in an abandoned A build are EXCLUDED from B/E measurement "
                                "(analysis/out/phase_e/newcorp_exclusions.json); the 14 exposed H sessions are flagged in HELDOUT_MANIFEST "
                                "for Track C to drop (sha256 of their sorted ids recorded).",
        "D6_blindness": "New-corpus results are NOT blind for the request-id bracket (R1/F1), latency (Probe 1) and reaction time (N3): Track B "
                        "(B5e) computed request-id decode deltas and call->result gap quantiles over the full acquired corpora, and builders ran "
                        "structure-only population passes over all files. Label these cells NOT_BLIND; they are replications on new data "
                        "under frozen thresholds, not held-out confirmations.",
        "D7_not_loaded": "openhands_eval and the group-4 corpora (tracelab-uw, cli-pi-hf, miniswe, sweagent-combo2, osworld, webarena-infinity, "
                         "openhands-feedback) were not loaded (time budget): N6 cells NOT_LOADED.",
    }
    if not any(isinstance(e, dict) and e.get("kind", "").startswith("orchestrator decisions for new corpora") for e in log):
        log.append(decisions)
    json.dump(pj, open(pj_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    man_path = os.path.join(AN, "HELDOUT_MANIFEST.json")
    man = json.load(open(man_path, encoding="utf-8"))
    for f in sorted(glob.glob(os.path.join(OUT, "heldout_manifest_*.json"))):
        c = os.path.basename(f)[len("heldout_manifest_"):-len(".json")]
        man.setdefault("corpora", {})[c] = {"source": os.path.relpath(f, os.path.dirname(AN)).replace("\\", "/"), "source_sha256": sha(f),
                                             **{k: v for k, v in json.load(open(f, encoding="utf-8")).items() if not isinstance(v, list)}}
    inc = json.load(open(os.path.join(OUT, "newcorp_split_incident_agentcap.json"), encoding="utf-8"))
    man["corpora"].setdefault("agentcap", {})["exposed_H_sessions"] = {"n": inc["n_H"], "sha256_sorted_ids": inc["sha256_sorted_H_ids"],
                                                                        "rule": "Track C drops these (parsed in an abandoned A build)"}
    json.dump(man, open(man_path, "w", encoding="utf-8"), indent=1)

    excl = {"agentcap": {"B": sorted(inc["B_ids"]), "E": sorted(inc["E_ids"]), "reason": inc["what"], "decision": "D5"}}
    json.dump(excl, open(os.path.join(OUT, "newcorp_exclusions.json"), "w", encoding="utf-8"), indent=1)
    report["change_log_entries"] = len(log)
    report["exclusions"] = {"agentcap_B": len(excl["agentcap"]["B"]), "agentcap_E": len(excl["agentcap"]["E"])}
    json.dump(report, open(os.path.join(OUT, "newcorp_register.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
