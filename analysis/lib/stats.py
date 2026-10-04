"""Shared statistics. The session is the resampling unit everywhere: calls within a session are not independent.
All functions are deterministic given SEED."""
import math
import numpy as np

SEED = 20261003
N_BOOT = 1000


def wilson(k, n, z=1.96):
    """Wilson 95% interval for a proportion k/n. Returns (p, lo, hi); (None, None, None) if n == 0."""
    if n == 0:
        return (None, None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def cluster_rate(num_by_session, den_by_session, n_boot=N_BOOT, seed=SEED):
    """Ratio estimate sum(num)/sum(den) with a session-clustered bootstrap 95% CI.
    num_by_session, den_by_session: equal-length arrays, one entry per session.
    Returns dict(rate, lo, hi, n_sessions, num, den)."""
    num = np.asarray(num_by_session, dtype=float)
    den = np.asarray(den_by_session, dtype=float)
    keep = den > 0
    num, den = num[keep], den[keep]
    n = len(den)
    if n == 0 or den.sum() == 0:
        return {"rate": None, "lo": None, "hi": None, "n_sessions": int(n), "num": float(num.sum()), "den": float(den.sum())}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    boots = num[idx].sum(1) / np.maximum(den[idx].sum(1), 1e-12)
    return {"rate": float(num.sum() / den.sum()), "lo": float(np.quantile(boots, 0.025)), "hi": float(np.quantile(boots, 0.975)),
            "n_sessions": int(n), "num": float(num.sum()), "den": float(den.sum())}


def cluster_quantile(values, session_ids, q, n_boot=N_BOOT, seed=SEED):
    """Quantile q of pooled values with a session-clustered bootstrap 95% CI. Returns dict(q, value, lo, hi, n, n_sessions)."""
    v = np.asarray(values, dtype=float)
    s = np.asarray(session_ids)
    if len(v) == 0:
        return {"q": q, "value": None, "lo": None, "hi": None, "n": 0, "n_sessions": 0}
    uniq, inv = np.unique(s, return_inverse=True)
    groups = [v[inv == i] for i in range(len(uniq))]
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(groups), size=len(groups))
        boots.append(np.quantile(np.concatenate([groups[i] for i in pick]), q))
    return {"q": q, "value": float(np.quantile(v, q)), "lo": float(np.quantile(boots, 0.025)), "hi": float(np.quantile(boots, 0.975)),
            "n": int(len(v)), "n_sessions": int(len(uniq))}


def describe(values, qs=(0.0, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 1.0)):
    """Plain distribution summary (no CI). Returns dict with n and named quantiles."""
    v = np.asarray(values, dtype=float)
    v = v[~np.isnan(v)]
    if len(v) == 0:
        return {"n": 0}
    names = {0.0: "min", 1.0: "max"}
    return {"n": int(len(v)), **{names.get(q, f"p{round(q * 100, 2):g}"): float(np.quantile(v, q)) for q in qs},
            "mean": float(v.mean())}


def log_histogram(values, base=10, per_decade=4):
    """Histogram on log-spaced bins for positive values; zeros/negatives counted separately."""
    v = np.asarray(values, dtype=float)
    pos = v[v > 0]
    out = {"n": int(len(v)), "zero_or_negative": int((v <= 0).sum())}
    if len(pos):
        lo, hi = math.floor(math.log(pos.min(), base) * per_decade), math.ceil(math.log(pos.max(), base) * per_decade)
        edges = [base ** (k / per_decade) for k in range(lo, hi + 1)]
        counts, _ = np.histogram(pos, bins=edges)
        out["bins"] = [{"lo": float(edges[i]), "hi": float(edges[i + 1]), "count": int(c)} for i, c in enumerate(counts)]
    return out


def chi2_uniform(counts):
    """Pearson chi-square goodness of fit to uniform. Returns dict(stat, df, p, n)."""
    from scipy.stats import chisquare
    c = np.asarray(counts, dtype=float)
    if c.sum() == 0:
        return {"stat": None, "df": len(c) - 1, "p": None, "n": 0}
    r = chisquare(c)
    return {"stat": float(r.statistic), "df": int(len(c) - 1), "p": float(r.pvalue), "n": int(c.sum())}
