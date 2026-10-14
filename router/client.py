import json
import time
import urllib.error
import urllib.request


class ModelError(Exception):
    pass


def _endpoint(base_url):
    return base_url.rstrip("/") + "/chat/completions"


def chat(base_url, api_key, model, messages, timeout=60, retries=2):
    body = json.dumps({"model": model, "messages": messages}).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    last = ModelError("no attempts made")
    for attempt in range(retries + 1):
        req = urllib.request.Request(_endpoint(base_url), data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            msg = data["choices"][0]["message"]
            usage = data.get("usage") or {}
            return {
                "text": msg.get("content") or "",
                "tokens_in": usage.get("prompt_tokens", 0),
                "tokens_out": usage.get("completion_tokens", 0),
            }
        except urllib.error.HTTPError as e:
            last = ModelError(f"http {e.code}")
            retryable = e.code == 429 or 500 <= e.code < 600
            if retryable and attempt < retries:
                time.sleep(0.5 * (2 ** attempt))
                continue
            raise last
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = ModelError(f"connection failed: {e}")
            if attempt < retries:
                time.sleep(0.5 * (2 ** attempt))
                continue
            raise last
    raise last
