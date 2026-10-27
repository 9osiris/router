import argparse
import json
import os
import sys

from . import __version__, classify, cost, tune
from .policy import Router, RouterError
from . import store

EXAMPLE_CONFIG = {
    "tier_order": ["fast", "smart"],
    "routes": {"easy": "fast", "medium": "fast", "hard": "smart"},
    "models": [
        {
            "name": "my-fast-model",
            "tier": "fast",
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key_env": "FAST_API_KEY",
            "price_in": 0.10,
            "price_out": 0.40,
        },
        {
            "name": "my-smart-model",
            "tier": "smart",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
            "price_in": 2.50,
            "price_out": 10.00,
        },
    ],
}


def _prompt_from(args):
    if args.prompt:
        return args.prompt
    if not sys.stdin.isatty():
        return sys.stdin.read()
    print("error: give a prompt as an argument or pipe it on stdin", file=sys.stderr)
    sys.exit(1)


def cmd_init(args):
    path = args.path or store.config_path()
    if os.path.exists(path) and not args.force:
        print(f"error: {path} already exists, use --force to overwrite", file=sys.stderr)
        sys.exit(1)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(EXAMPLE_CONFIG, f, indent=2)
    print(f"wrote {path}, edit the models and keys to match your setup")


def cmd_models(args):
    r = Router(args.config)
    for m in r.config["models"]:
        key_set = "set" if os.environ.get(m.get("api_key_env") or "") else "missing"
        print(f"{m['name']:24} tier={m['tier']:8} key({m.get('api_key_env')})={key_set}")


def cmd_classify(args):
    text = _prompt_from(args)
    c = classify(text)
    print(f"difficulty: {c['difficulty']} (score {c['score']})")
    print("signals: " + ", ".join(c["signals"]))


def cmd_chat(args):
    text = _prompt_from(args)
    try:
        r = Router(args.config)
    except RouterError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    if args.show_route:
        d = r.route(text, tier=args.tier)
        print(f"[route] {d['difficulty']} -> {d['tier']} tier, trying {', '.join(d['candidates'])}",
              file=sys.stderr)
    try:
        res = r.chat(text, tier=args.tier, fallback=not args.no_fallback, timeout=args.timeout)
    except RouterError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
    if args.show_route:
        print(f"[served] {res['model']} in {res['ms']}ms, "
              f"{res['tokens_in']}/{res['tokens_out']} tokens, {cost.fmt(res['cost_usd'])}"
              + (" (fallback)" if res["fallback_used"] else ""),
              file=sys.stderr)
    print(res["text"])


def cmd_stats(args):
    s = store.stats()
    if not s["requests"]:
        print("no decisions logged yet")
        return
    print(f"{s['requests']} requests, {cost.fmt(s['total_cost'])} total, "
          f"{s['avg_ms']:.0f}ms avg, {s['fallbacks']} fallbacks")
    for name, m in sorted(s["by_model"].items(), key=lambda kv: -kv[1]["n"]):
        print(f"  {name:24} {m['n']:4} reqs  {cost.fmt(m['cost']):>12}  {m['ms']/m['n']:.0f}ms avg")


def cmd_tune(args):
    r = Router(args.config)
    rows = store.read_all()
    if not rows:
        print("no decisions logged yet")
        return
    suggestions = tune.analyze(rows, r.config,
                               min_samples=args.min_samples)
    print(f"{len(rows)} logged decisions, "
          f"min {args.min_samples} samples per bucket")
    for diff in sorted({row.get("difficulty") for row in rows
                        if row.get("difficulty")}):
        current = r.config["routes"].get(diff, "?")
        print(f"  {diff:8} routed to {current}")
    if not suggestions:
        print("no route changes suggested")
    for s in suggestions:
        line = (f"suggest: {s['difficulty']} {s['from_tier']} -> "
                f"{s['to_tier']} ({s['direction']}): {s['reason']}")
        if s["direction"] == "down":
            line += f", saves about {cost.fmt(s['saved_usd'])} on past volume"
        print(line)
    print("dry run, nothing changed. edit models.json by hand to apply "
          "a suggestion.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="router", description="route prompts to the cheapest model that can handle them")
    p.add_argument("--config", default=None, help="path to models.json")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("init", help="scaffold a models.json")
    a.add_argument("--path", default=None)
    a.add_argument("--force", action="store_true")
    a.set_defaults(fn=cmd_init)

    a = sub.add_parser("models", help="list configured models")
    a.set_defaults(fn=cmd_models)

    a = sub.add_parser("classify", help="show the difficulty guess for a prompt")
    a.add_argument("prompt", nargs="?")
    a.set_defaults(fn=cmd_classify)

    a = sub.add_parser("chat", help="route a prompt and print the answer")
    a.add_argument("prompt", nargs="?")
    a.add_argument("--tier", default=None, help="force a tier, skip classification")
    a.add_argument("--no-fallback", action="store_true", help="try only the first model")
    a.add_argument("--show-route", action="store_true", help="print routing info to stderr")
    a.add_argument("--timeout", type=int, default=60)
    a.set_defaults(fn=cmd_chat)

    a = sub.add_parser("stats", help="spend and usage from the decision log")
    a.set_defaults(fn=cmd_stats)

    a = sub.add_parser("tune", help="suggest route changes from the decision log")
    a.add_argument("--dry-run", action="store_true",
                   help="print suggestions only (this is the only mode)")
    a.add_argument("--min-samples", type=int, default=5,
                   help="requests per bucket before suggesting (default 5)")
    a.set_defaults(fn=cmd_tune)

    args = p.parse_args(argv)
    try:
        args.fn(args)
    except RouterError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
