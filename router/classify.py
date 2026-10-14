import re

# local heuristic, no api call. scores the prompt, maps the score to a tier.
# it is a guess, not a fact. the readme says so.

_hard = [
    (re.compile(r"```"), "code fence", 2),
    (re.compile(r"\b(def |class |function |=>|#include|fn |pub fn|SELECT |CREATE TABLE)"), "code keywords", 2),
    (re.compile(r"\b(prove|derivation|derive|debug|refactor|redesign|architect|optimiz|analy[sz]e|compare|contrast|step[- ]by[- ]step|explain why|trade-?offs?|root cause)\b", re.I), "reasoning verbs", 2),
    (re.compile(r"\$[^$\n]+\$|\\[a-zA-Z]+|∑|∫|√|≠|≈"), "math notation", 2),
    (re.compile(r"\b(algorithm|complexity|big-?o|recursion|concurrency|distributed|consensus|deadlock)\b", re.I), "cs theory terms", 1),
]

_medium = [
    (re.compile(r"\b(summariz|explain|describe|outline|rewrite|translate|draft|brainstorm)\w*\b", re.I), "explanation verbs", 1),
]

_greeting = re.compile(r"(?i)^(hi|hey|hello|yo|sup|good (morning|afternoon|evening)|thanks|thank you)\b[.! ]*$")


def classify(text):
    t = (text or "").strip()
    signals = []
    score = 0
    for rx, name, w in _hard + _medium:
        hits = rx.findall(t)
        if hits:
            # count repeats a little, cap it so one prompt cant blow the scale
            signals.append(name)
            score += w * min(len(hits), 2)
    if len(t) > 4000:
        signals.append("very long prompt")
        score += 2
    elif len(t) > 1500:
        signals.append("long prompt")
        score += 1
    if t.count("?") >= 3:
        signals.append("many questions")
        score += 1
    if len(t) < 60 and _greeting.match(t):
        return {"difficulty": "easy", "score": 0, "signals": ["greeting"]}
    if score >= 4:
        difficulty = "hard"
    elif score >= 1:
        difficulty = "medium"
    else:
        difficulty = "easy"
    if not signals:
        signals = ["no strong signals"]
    return {"difficulty": difficulty, "score": score, "signals": signals}
