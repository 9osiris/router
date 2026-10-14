import json
import os
import time

# every routing decision lands here, one json object per line.
# plain text, grep-able, no database.


def home():
    return os.environ.get("ROUTER_HOME", os.path.expanduser("~/.router"))


def config_path():
    return os.path.join(home(), "models.json")


def log_path():
    return os.path.join(home(), "decisions.jsonl")


def log(entry):
    os.makedirs(home(), exist_ok=True)
    entry = dict(entry)
    entry.setdefault("ts", time.time())
    with open(log_path(), "a") as f:
        f.write(json.dumps(entry) + "\n")


def read_all():
    if not os.path.exists(log_path()):
        return []
    out = []
    with open(log_path()) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def stats():
    rows = read_all()
    by_model = {}
    total_cost = 0.0
    total_ms = 0
    fallbacks = 0
    for r in rows:
        m = by_model.setdefault(r.get("model", "?"), {"n": 0, "cost": 0.0, "ms": 0})
        m["n"] += 1
        m["cost"] += r.get("cost_usd", 0)
        m["ms"] += r.get("ms", 0)
        total_cost += r.get("cost_usd", 0)
        total_ms += r.get("ms", 0)
        if r.get("fallback_used"):
            fallbacks += 1
    return {
        "requests": len(rows),
        "total_cost": total_cost,
        "avg_ms": (total_ms / len(rows)) if rows else 0,
        "fallbacks": fallbacks,
        "by_model": by_model,
    }
