# prices are usd per 1m tokens, matching the openai-style pricing tables

def dollars(tokens_in, tokens_out, price_in, price_out):
    return tokens_in / 1_000_000 * (price_in or 0) + tokens_out / 1_000_000 * (price_out or 0)


def fmt(usd):
    if usd < 0.01:
        return f"${usd:.6f}"
    return f"${usd:.4f}"
