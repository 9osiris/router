import json
import os
import time

from . import classify as classify_mod
from . import client
from . import cost
from . import routes
from . import store


class RouterError(Exception):
    pass


class Router:
    def __init__(self, config_path=None):
        self.config = routes.load_config(config_path or store.config_path())
        self.config_path = config_path or store.config_path()

    def route(self, text, tier=None):
        c = classify_mod.classify(text)
        want = tier or self.config["routes"][c["difficulty"]]
        cands = routes.candidates_for(self.config, c["difficulty"], tier_override=tier)
        return {
            "difficulty": c["difficulty"],
            "score": c["score"],
            "signals": c["signals"],
            "tier": want,
            "candidates": [m["name"] for m in cands],
        }

    def chat(self, prompt, messages=None, tier=None, fallback=True, timeout=60):
        msgs = messages or [{"role": "user", "content": prompt or ""}]
        flat = prompt if prompt else json.dumps(msgs)
        c = classify_mod.classify(flat)
        want = tier or self.config["routes"][c["difficulty"]]
        cands = routes.candidates_for(self.config, c["difficulty"], tier_override=tier, fallback=fallback)
        if not cands:
            raise RouterError(f"no models configured for tier {want!r}")
        errors = []
        first = cands[0]["name"]
        for m in cands:
            key = os.environ.get(m.get("api_key_env") or "", "")
            t0 = time.time()
            try:
                res = client.chat(m["base_url"], key, m["name"], msgs, timeout=timeout)
            except client.ModelError as e:
                errors.append(f"{m['name']}: {e}")
                continue
            ms = int((time.time() - t0) * 1000)
            usd = cost.dollars(res["tokens_in"], res["tokens_out"],
                               m.get("price_in", 0), m.get("price_out", 0))
            entry = {
                "prompt_preview": flat[:120],
                "difficulty": c["difficulty"],
                "signals": c["signals"],
                "tier": want,
                "model": m["name"],
                "fallback_used": m["name"] != first,
                "tokens_in": res["tokens_in"],
                "tokens_out": res["tokens_out"],
                "cost_usd": usd,
                "ms": ms,
            }
            store.log(entry)
            return {"text": res["text"], **entry}
        raise RouterError("every model failed: " + "; ".join(errors))
