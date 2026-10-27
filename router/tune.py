"""tune: suggest route changes from the decision log.

the log knows difficulty, model, cost, latency, and whether a fallback
fired, but it has no idea if an answer was good. so the suggestions are
conservative and never applied automatically: they are evidence to look
at, not decisions. `router tune` only prints, it never writes config.
"""

from . import cost


def _median(values):
    vals = sorted(values)
    n = len(vals)
    if n == 0:
        return 0
    if n % 2:
        return vals[n // 2]
    return (vals[n // 2 - 1] + vals[n // 2]) / 2


def _bucket_stats(rows):
    """per serving tier: n, median cost/ms/tokens_out, fallback rate."""
    by_tier = {}
    for r in rows:
        tier = r["_tier"]
        b = by_tier.setdefault(tier, {"rows": []})
        b["rows"].append(r)
    out = {}
    for tier, b in by_tier.items():
        rs = b["rows"]
        out[tier] = {
            "n": len(rs),
            "median_cost": _median([r.get("cost_usd", 0) for r in rs]),
            "median_ms": _median([r.get("ms", 0) for r in rs]),
            "median_out": _median([r.get("tokens_out", 0) for r in rs]),
            "fallback_rate": (sum(1 for r in rs if r.get("fallback_used"))
                              / len(rs)),
        }
    return out


def analyze(rows, config, min_samples=5):
    """one suggestion per difficulty bucket, at most.

    move down: the tier below the current one already served this bucket
    at least min_samples times, with comparable output length (median
    tokens_out within half of the current tier, a rough "it still
    answers" proxy) and a lower median cost.
    move up: the current tier fell back on at least 30% of this bucket,
    so it keeps failing and a higher tier keeps rescuing it.
    """
    order = config["tier_order"]
    model_tier = {m["name"]: m["tier"] for m in config["models"]}
    by_diff = {}
    for r in rows:
        diff = r.get("difficulty")
        tier = model_tier.get(r.get("model"))
        if diff is None or tier is None:
            continue
        row = dict(r)
        row["_tier"] = tier
        by_diff.setdefault(diff, []).append(row)
    suggestions = []
    for diff in sorted(by_diff):
        current = config["routes"].get(diff)
        if current not in order:
            continue
        stats = _bucket_stats(by_diff[diff])
        cur = stats.get(current)
        if cur is None or cur["n"] < min_samples:
            continue
        idx = order.index(current)
        # reliability first: if this tier keeps failing, move up
        if cur["fallback_rate"] >= 0.3 and idx + 1 < len(order):
            suggestions.append({
                "difficulty": diff,
                "direction": "up",
                "from_tier": current,
                "to_tier": order[idx + 1],
                "reason": "fell back on %d%% of %d requests"
                          % (round(cur["fallback_rate"] * 100), cur["n"]),
                "evidence": stats,
            })
            continue
        # savings second: the cheaper tier already handles this bucket
        if idx > 0:
            lower = order[idx - 1]
            low = stats.get(lower)
            if low is None or low["n"] < min_samples:
                continue
            if low["median_cost"] >= cur["median_cost"]:
                continue
            if low["median_out"] < 0.5 * cur["median_out"]:
                continue
            saved = (cur["median_cost"] - low["median_cost"]) * cur["n"]
            suggestions.append({
                "difficulty": diff,
                "direction": "down",
                "from_tier": current,
                "to_tier": lower,
                "reason": "%s served this bucket %d times at %s median "
                          "vs %s, similar output length"
                          % (lower, low["n"], cost.fmt(low["median_cost"]),
                             cost.fmt(cur["median_cost"])),
                "saved_usd": saved,
                "evidence": stats,
            })
    return suggestions
