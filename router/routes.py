import json


class ConfigError(Exception):
    pass


def load_config(path):
    try:
        with open(path) as f:
            raw = json.load(f)
    except FileNotFoundError:
        raise ConfigError(f"no config at {path}, run `router init` first")
    except json.JSONDecodeError as e:
        raise ConfigError(f"bad json in {path}: {e}")
    if not isinstance(raw, dict):
        raise ConfigError("config must be a json object")
    tier_order = raw.get("tier_order", ["fast", "smart"])
    routes = raw.get("routes", {"easy": "fast", "medium": "fast", "hard": "smart"})
    models = raw.get("models", [])
    if not tier_order:
        raise ConfigError("tier_order is empty")
    for diff, tier in routes.items():
        if tier not in tier_order:
            raise ConfigError(f"routes[{diff}] points at unknown tier {tier!r}")
    names = [m.get("name") for m in models]
    if len(set(names)) != len(names):
        raise ConfigError("model names must be unique")
    for m in models:
        if m.get("tier") not in tier_order:
            raise ConfigError(f"model {m.get('name')!r} has unknown tier {m.get('tier')!r}")
        if not m.get("base_url"):
            raise ConfigError(f"model {m.get('name')!r} is missing base_url")
    if not models:
        raise ConfigError("config has no models")
    return {"tier_order": tier_order, "routes": routes, "models": models}


def candidates_for(config, difficulty, tier_override=None, fallback=True):
    want = tier_override or config["routes"][difficulty]
    order = config["tier_order"]
    same = [m for m in config["models"] if m["tier"] == want]
    if not fallback:
        return same
    out = list(same)
    for t in order[order.index(want) + 1:]:
        out += [m for m in config["models"] if m["tier"] == t]
    return out
