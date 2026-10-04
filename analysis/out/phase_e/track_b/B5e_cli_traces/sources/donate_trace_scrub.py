#!/usr/bin/env python3
"""
scrub.py — deterministic anonymization pass for Trace Commons donations.

Removes the high-confidence, crisply-patterned leaks from a coding-agent
session before it is reviewed and donated:
  - home-directory paths and the username embedded in them
  - common secret formats (API keys, tokens, PEM blocks, JWTs, env assignments)
  - email addresses

This is intentionally NOT the whole anonymization story, and the secret list
here is a fast first pass, not the authoritative one. Three layers back it up:
the ingestion server re-runs TruffleHog (hundreds of maintained, updated secret
detectors) and rejects anything it flags; the skill performs an LLM/human review
pass for fuzzy things a regex can't recognize (personal names in prose, company
names, internal codenames); and the contributor reviews the exact diff before
anything is uploaded. The split is deliberate: code handles the patterns that
have signatures, a dedicated scanner handles breadth, and a human handles meaning.

The script walks the parsed JSON of each session line and rewrites string
values in place, so it works regardless of where in the structure a string
sits. It writes a cleaned file plus a JSON report of every redaction.

Usage:
  python scrub.py --in session.jsonl --harness claude_code \
      --out cleaned.jsonl --report report.json
"""

import argparse
import json
import re
import sys
from collections import Counter

# --- redaction patterns -----------------------------------------------------
# Order matters: more specific patterns run before more general ones.

HOME_PATH = re.compile(r'(\\?/(?:Users|home))\\?/([^/\\\s"\']+)')
# Dash-encoded home paths. Coding agents (e.g. Claude Code) name their project
# directories by replacing the slashes of an absolute path with dashes, so
# /Users/<name>/proj becomes the slug .claude/projects/-Users-<name>-proj. The
# slash-based HOME_PATH never sees these, so the username leaks. Anchored on the
# leading "/-Users-" / "/-home-" of the slug to avoid mangling hyphenated prose.
HOME_PATH_DASH = re.compile(r'(/-(?:Users|home))-([^-\s"\'\\/]+)')
# Windows user paths too
WIN_PATH = re.compile(r'([A-Za-z]:\\Users\\)([^\\\s"\']+)', re.IGNORECASE)

EMAIL = re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b')

# RFC1918 private / internal IPv4 addresses. Not a secret, but it leaks internal
# network topology (DB hosts, service IPs), so it is redacted like home paths —
# without causing the server backstop to reject the whole donation. The four-octet
# shape with a fixed private prefix avoids mangling version numbers like 1.2.3.4.
PRIVATE_IP = re.compile(
    r'\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}'
    r'|192\.168\.\d{1,3}\.\d{1,3}'
    r'|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}'
    r'|169\.254\.\d{1,3}\.\d{1,3})\b'
)

# Secrets — each tuple is (name, compiled regex). Keep these conservative
# enough to avoid mangling ordinary prose but broad enough to catch real keys.
SECRET_PATTERNS = [
    ("aws_access_key", re.compile(r'\bAKIA[0-9A-Z]{16}\b')),
    ("aws_secret", re.compile(r'\b(?i:aws_secret_access_key)\s*[=:]\s*["\']?[A-Za-z0-9/+=]{40}["\']?')),
    ("github_token", re.compile(r'\bgh[pousr]_[A-Za-z0-9]{36,}\b')),
    ("hf_token", re.compile(r'\bhf_[A-Za-z0-9]{30,}\b')),
    ("openai_key", re.compile(r'\bsk-[A-Za-z0-9_\-]{20,}\b')),
    ("anthropic_key", re.compile(r'\bsk-ant-[A-Za-z0-9_\-]{20,}\b')),
    ("slack_token", re.compile(r'\bxox[baprs]-[A-Za-z0-9\-]{10,}\b')),
    ("google_api_key", re.compile(r'\bAIza[0-9A-Za-z_\-]{35}\b')),
    ("jwt", re.compile(r'\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b')),
    ("private_key_block", re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----', re.DOTALL)),
    ("bearer_token", re.compile(r'\b(?i:bearer)\s+[A-Za-z0-9_\-\.=]{20,}')),
    ("connection_string", re.compile(r'\b(?:postgres|postgresql|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s"\'<>]+:[^\s"\'<>@]+@[^\s"\'<>]+')),
    # More vendor-prefixed tokens. This list is necessarily incomplete — it is a
    # fast first pass, NOT the authoritative check. The ingestion server runs
    # TruffleHog (hundreds of maintained detectors) as the real backstop and
    # rejects anything it flags. Keep these prefix-anchored to avoid false hits.
    ("github_fine_grained_pat", re.compile(r'\bgithub_pat_[0-9A-Za-z_]{22,}\b')),
    ("gitlab_pat", re.compile(r'\bglpat-[0-9A-Za-z_\-]{20,}\b')),
    ("gcp_oauth_token", re.compile(r'\bya29\.[0-9A-Za-z_\-]{20,}\b')),
    ("stripe_key", re.compile(r'\b(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{20,}\b')),
    ("sendgrid_key", re.compile(r'\bSG\.[A-Za-z0-9_\-]{16,32}\.[A-Za-z0-9_\-]{16,64}\b')),
    ("npm_token", re.compile(r'\bnpm_[0-9A-Za-z]{36}\b')),
    ("pypi_token", re.compile(r'\bpypi-[A-Za-z0-9_\-]{16,}\b')),
    # Twilio (SK + 32 hex) is deliberately NOT regexed here: the shape collides
    # with ordinary hashes/IDs and would cause false redactions. TruffleHog's
    # validated Twilio detector handles it on the server backstop instead.
    ("azure_storage_key", re.compile(r'\bAccountKey=[A-Za-z0-9+/=]{40,}')),
    ("slack_webhook", re.compile(r'https://hooks\.slack\.com/services/[A-Za-z0-9/_\-]+')),
    ("discord_webhook", re.compile(r'https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_\-]+')),
    # generic KEY=secret env assignments where the value looks secret-ish
    ("env_secret", re.compile(r'\b([A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|CREDENTIAL|API)[A-Z0-9_]*)\s*=\s*["\']?([^\s"\']{8,})["\']?')),
]


def redact_string(s, counts):
    """Apply all redactions to a single string, tallying what was changed."""
    if not isinstance(s, str) or not s:
        return s

    # Secrets first (before paths/emails, since some secrets contain those shapes)
    for name, pat in SECRET_PATTERNS:
        def _sub(m, _name=name):
            counts[_name] += 1
            if _name == "env_secret":
                # keep the key name, redact the value
                return f"{m.group(1)}=[REDACTED_SECRET]"
            return "[REDACTED_SECRET]"
        s = pat.sub(_sub, s)

    # Home paths -> normalize the username segment
    def _home(m):
        counts["home_path"] += 1
        return f"{m.group(1)}/USER"
    s = HOME_PATH.sub(_home, s)

    def _home_dash(m):
        counts["home_path"] += 1
        return f"{m.group(1)}-USER"
    s = HOME_PATH_DASH.sub(_home_dash, s)

    def _win(m):
        counts["home_path"] += 1
        return f"{m.group(1)}USER"
    s = WIN_PATH.sub(_win, s)

    # Emails
    def _email(m):
        counts["email"] += 1
        return "[REDACTED_EMAIL]"
    s = EMAIL.sub(_email, s)

    # Private/internal IPs (redact-only, not treated as a rejectable secret)
    def _ip(m):
        counts["private_ip"] += 1
        return "[REDACTED_IP]"
    s = PRIVATE_IP.sub(_ip, s)

    return s


def walk(obj, counts):
    """Recursively rewrite all string values in a parsed JSON structure."""
    if isinstance(obj, str):
        return redact_string(obj, counts)
    if isinstance(obj, list):
        return [walk(x, counts) for x in obj]
    if isinstance(obj, dict):
        # Keys can carry leaks too — some agents key objects by absolute file
        # path (e.g. {"/Users/<name>/proj/file": ...}), so scrub keys as well.
        return {
            (redact_string(k, counts) if isinstance(k, str) else k): walk(v, counts)
            for k, v in obj.items()
        }
    return obj


def scrub_text(raw, harness):
    """Scrub a raw session string. Returns (cleaned_text, report_dict).

    Importable so the server can run the exact same detection as the skill,
    as a backstop. Mirrors the file-based main() below.
    """
    counts = Counter()
    lines_in = 0
    lines_out = []

    stripped = raw.strip()
    is_single_doc = stripped.startswith("{") and stripped.count("\n") > 0 and not _looks_like_jsonl(stripped)

    if is_single_doc:
        try:
            doc = json.loads(stripped)
            cleaned = walk(doc, counts)
            lines_out.append(json.dumps(cleaned, ensure_ascii=False))
            lines_in = 1
        except json.JSONDecodeError:
            is_single_doc = False

    if not is_single_doc:
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            lines_in += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                lines_out.append(redact_string(line, counts))
                continue
            cleaned = walk(obj, counts)
            lines_out.append(json.dumps(cleaned, ensure_ascii=False))

    report = {
        "harness": harness,
        "lines_processed": lines_in,
        "redactions": dict(counts),
        "total_redactions": sum(counts.values()),
    }
    return "\n".join(lines_out) + "\n", report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--harness", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    with open(args.inp, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()

    cleaned_text, report = scrub_text(raw, args.harness)
    counts = Counter(report["redactions"])
    lines_in = report["lines_processed"]

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(cleaned_text)

    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # Human-readable summary to stdout for the skill to relay
    print(f"Scrubbed {lines_in} lines from {args.harness} session.")
    if counts:
        for k, v in counts.most_common():
            print(f"  {v}× {k}")
    else:
        print("  No high-confidence secrets or paths found by the automated pass.")
    print(f"\nCleaned file: {args.out}")
    print(f"Report: {args.report}")
    print("\nThis is the automated pass only. Now do the review pass for names,")
    print("company names, and internal references before showing the user.")


def _looks_like_jsonl(text):
    """Heuristic: if the first two non-empty lines each parse as JSON, it's JSONL."""
    parsed = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            json.loads(line)
            parsed += 1
        except json.JSONDecodeError:
            return False
        if parsed >= 2:
            return True
    return False


if __name__ == "__main__":
    main()
