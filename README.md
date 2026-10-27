router - route every prompt to the cheapest model that can handle it [ai infrastructure project]

disclaimer:
this is a scratch tool, not a product. i run a bunch of models through
openai-compatible endpoints and got tired of either burning the expensive
one on "hey" or getting garbage answers from the cheap one on real work.
so this guesses how hard a prompt is and picks a tier. the guess is a
regex heuristic, it will be wrong sometimes, that is what --tier is for.

why i made this:
i kept hand-picking which model to send things to and it was dumb. easy
stuff (greetings, one-line questions) goes to the fast cheap tier, hard
stuff (debugging, proofs, anything with code fences) goes to the smart
tier, everything else lands on fast too. when a model is down or 500s,
it walks up to the next tier instead of just dying. every decision gets
logged with tokens, cost, and latency so `router stats` tells me what
i actually spent and where.

i wrote the argparse subcommands by hand and there are no dependencies
on purpose. the http client is urllib, the log
is jsonl in ~/.router, the config is one json file. i did not want another
daemon or database for this.

the guide:

```bash
router init # scaffold ~/.router/models.json, then edit it
router models # list your models, check keys are set
router chat "summarize this:..." --show-route
echo "debug this:..." | router chat
router classify "prove x, step by step"
router stats # spend and usage from the decision log
router tune --dry-run # suggest route changes from the log
```

models.json looks like this:

```json
{
  "tier_order": ["fast", "smart"],
  "routes": {"easy": "fast", "medium": "fast", "hard": "smart"},
  "models": [
    {"name": "flash", "tier": "fast", "base_url": "http://127.0.0.1:11434/v1",
     "api_key_env": "FAST_API_KEY", "price_in": 0.10, "price_out": 0.40},
    {"name": "pro", "tier": "smart", "base_url": "https://api.openai.com/v1",
     "api_key_env": "OPENAI_API_KEY", "price_in": 2.50, "price_out": 10.00}
]
}
```

api keys live in env vars named by `api_key_env`, never in the config.
`--tier fast|smart` forces a tier and skips classification. `--no-fallback`
tries only the first model. exit code is 2 when every model fails.

tune reads the decision log and suggests route changes. if the smart
tier keeps getting a bucket the fast tier already handled fine (same
difficulty, similar output length, lower cost), it suggests moving
that bucket down a tier. if a tier keeps falling back, it suggests
moving the bucket up. suggestions need at least 5 samples per bucket
(`--min-samples` to change that). tune only prints, it never writes
config, `--dry-run` is the only mode. apply a suggestion by editing
models.json by hand.

run the tests:

```bash
python3 -m unittest discover -s tests
```

44 checks, all against fake local openai-compatible servers, no api key
needed. classifier unit tests, config validation, routing order, fallback
on dead ports, cost math, decision log roundtrip, tune suggestions, cli end to end.
