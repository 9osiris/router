import json
import os
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from router import classify
from router import cost
from router import routes
from router import store
from router.cli import main as cli_main
from router.policy import Router, RouterError


class FakeModel(BaseHTTPRequestHandler):
    # class-level knobs the tests flip
    fail_with = None
    seen = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        FakeModel.seen.append(body.get("model"))
        if FakeModel.fail_with:
            code, payload = FakeModel.fail_with
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())
            return
        reply = {
            "choices": [{"message": {"content": f"answer from {body.get('model')}"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(reply).encode())


def serve(handler_cls):
    srv = HTTPServer(("127.0.0.1", 0), handler_cls)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def write_config(path, fast_url, smart_url):
    cfg = {
        "tier_order": ["fast", "smart"],
        "routes": {"easy": "fast", "medium": "fast", "hard": "smart"},
        "models": [
            {"name": "flash", "tier": "fast", "base_url": fast_url,
             "api_key_env": "ROUTER_TEST_FAST", "price_in": 0.1, "price_out": 0.4},
            {"name": "flash-2", "tier": "fast", "base_url": fast_url,
             "api_key_env": "ROUTER_TEST_FAST", "price_in": 0.1, "price_out": 0.4},
            {"name": "pro", "tier": "smart", "base_url": smart_url,
             "api_key_env": "ROUTER_TEST_SMART", "price_in": 2.5, "price_out": 10.0},
        ],
    }
    with open(path, "w") as f:
        json.dump(cfg, f)
    return cfg


class ClassifyTests(unittest.TestCase):
    def test_greeting_is_easy(self):
        c = classify("hey")
        self.assertEqual(c["difficulty"], "easy")

    def test_plain_question_is_easy(self):
        c = classify("what year is it")
        self.assertEqual(c["difficulty"], "easy")

    def test_summarize_is_medium(self):
        c = classify("summarize this article for me in three bullet points")
        self.assertEqual(c["difficulty"], "medium")

    def test_explain_is_medium(self):
        c = classify("explain how dns resolution works")
        self.assertEqual(c["difficulty"], "medium")

    def test_debug_code_is_hard(self):
        c = classify("debug this:\n```python\ndef f(x):\n    return x/0\n```")
        self.assertEqual(c["difficulty"], "hard")

    def test_prove_is_hard(self):
        c = classify("prove that the square root of 2 is irrational, step by step")
        self.assertEqual(c["difficulty"], "hard")

    def test_signals_listed(self):
        c = classify("debug this:\n```python\ndef f(x):\n    return x/0\n```")
        self.assertIn("code fence", c["signals"])
        self.assertIn("reasoning verbs", c["signals"])

    def test_long_prompt_scores_up(self):
        short = classify("explain recursion")
        long = classify("explain recursion " + "x" * 2000)
        self.assertLessEqual(short["score"], long["score"])

    def test_many_questions_scores_up(self):
        one = classify("what is a closure")
        many = classify("what is a closure? how does it capture state? when would you use one?")
        self.assertLess(one["score"], many["score"])

    def test_empty_prompt_is_easy(self):
        self.assertEqual(classify("")["difficulty"], "easy")


class RoutesTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.cfg_path = os.path.join(self.d, "models.json")

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_load_valid(self):
        write_config(self.cfg_path, "http://x/v1", "http://y/v1")
        cfg = routes.load_config(self.cfg_path)
        self.assertEqual(cfg["tier_order"], ["fast", "smart"])
        self.assertEqual(len(cfg["models"]), 3)

    def test_missing_file(self):
        with self.assertRaises(routes.ConfigError):
            routes.load_config(os.path.join(self.d, "nope.json"))

    def test_bad_json(self):
        with open(self.cfg_path, "w") as f:
            f.write("{not json")
        with self.assertRaises(routes.ConfigError):
            routes.load_config(self.cfg_path)

    def test_duplicate_names(self):
        with open(self.cfg_path, "w") as f:
            json.dump({"models": [
                {"name": "a", "tier": "fast", "base_url": "http://x"},
                {"name": "a", "tier": "fast", "base_url": "http://y"},
            ]}, f)
        with self.assertRaises(routes.ConfigError):
            routes.load_config(self.cfg_path)

    def test_unknown_tier_in_routes(self):
        with open(self.cfg_path, "w") as f:
            json.dump({"tier_order": ["fast"], "routes": {"easy": "huge"},
                       "models": [{"name": "a", "tier": "fast", "base_url": "http://x"}]}, f)
        with self.assertRaises(routes.ConfigError):
            routes.load_config(self.cfg_path)

    def test_model_missing_base_url(self):
        with open(self.cfg_path, "w") as f:
            json.dump({"models": [{"name": "a", "tier": "fast"}]}, f)
        with self.assertRaises(routes.ConfigError):
            routes.load_config(self.cfg_path)

    def test_candidates_easy_stays_fast_first(self):
        write_config(self.cfg_path, "http://x/v1", "http://y/v1")
        cfg = routes.load_config(self.cfg_path)
        names = [m["name"] for m in routes.candidates_for(cfg, "easy")]
        self.assertEqual(names, ["flash", "flash-2", "pro"])

    def test_candidates_hard_goes_smart(self):
        write_config(self.cfg_path, "http://x/v1", "http://y/v1")
        cfg = routes.load_config(self.cfg_path)
        names = [m["name"] for m in routes.candidates_for(cfg, "hard")]
        self.assertEqual(names, ["pro"])

    def test_no_fallback_only_first_tier(self):
        write_config(self.cfg_path, "http://x/v1", "http://y/v1")
        cfg = routes.load_config(self.cfg_path)
        names = [m["name"] for m in routes.candidates_for(cfg, "easy", fallback=False)]
        self.assertEqual(names, ["flash", "flash-2"])

    def test_tier_override(self):
        write_config(self.cfg_path, "http://x/v1", "http://y/v1")
        cfg = routes.load_config(self.cfg_path)
        names = [m["name"] for m in routes.candidates_for(cfg, "easy", tier_override="smart")]
        self.assertEqual(names, ["pro"])


class CostTests(unittest.TestCase):
    def test_math(self):
        self.assertAlmostEqual(cost.dollars(1_000_000, 1_000_000, 2.5, 10.0), 12.5)

    def test_zero_tokens(self):
        self.assertEqual(cost.dollars(0, 0, 2.5, 10.0), 0)

    def test_fmt_small(self):
        self.assertTrue(cost.fmt(0.0000123).startswith("$0.00"))


class PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fast = serve(FakeModel)
        cls.smart = serve(FakeModel)
        cls.fast_url = f"http://127.0.0.1:{cls.fast.server_port}/v1"
        cls.smart_url = f"http://127.0.0.1:{cls.smart.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.fast.shutdown()
        cls.smart.shutdown()
        cls.fast.server_close()
        cls.smart.server_close()

    def setUp(self):
        FakeModel.fail_with = None
        FakeModel.seen = []
        self.home = tempfile.mkdtemp()
        os.environ["ROUTER_HOME"] = self.home
        os.environ["ROUTER_TEST_FAST"] = "k"
        os.environ["ROUTER_TEST_SMART"] = "k"
        self.cfg_path = os.path.join(self.home, "models.json")
        write_config(self.cfg_path, self.fast_url, self.smart_url)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        for v in ("ROUTER_HOME", "ROUTER_TEST_FAST", "ROUTER_TEST_SMART"):
            os.environ.pop(v, None)

    def test_route_easy_picks_fast(self):
        r = Router(self.cfg_path)
        d = r.route("hey")
        self.assertEqual(d["tier"], "fast")
        self.assertEqual(d["candidates"][0], "flash")

    def test_route_hard_picks_smart(self):
        r = Router(self.cfg_path)
        d = r.route("debug this:\n```python\ndef f(x):\n    return x/0\n```")
        self.assertEqual(d["tier"], "smart")
        self.assertEqual(d["candidates"], ["pro"])

    def test_chat_easy_hits_fast_model(self):
        r = Router(self.cfg_path)
        res = r.chat("hey")
        self.assertEqual(res["model"], "flash")
        self.assertIn("answer from flash", res["text"])
        self.assertFalse(res["fallback_used"])
        self.assertEqual(FakeModel.seen, ["flash"])

    def test_chat_hard_hits_smart_model(self):
        r = Router(self.cfg_path)
        res = r.chat("prove the halting problem is undecidable, step by step")
        self.assertEqual(res["model"], "pro")

    def test_fallback_on_failure(self):
        twin = serve(FakeModel)
        try:
            cfg = {
                "tier_order": ["fast", "smart"],
                "routes": {"easy": "fast", "medium": "fast", "hard": "smart"},
                "models": [
                    {"name": "bad", "tier": "fast",
                     "base_url": "http://127.0.0.1:1/v1",
                     "api_key_env": "ROUTER_TEST_FAST", "price_in": 0.1, "price_out": 0.4},
                    {"name": "good", "tier": "smart",
                     "base_url": f"http://127.0.0.1:{twin.server_port}/v1",
                     "api_key_env": "ROUTER_TEST_SMART", "price_in": 2.5, "price_out": 10.0},
                ],
            }
            with open(self.cfg_path, "w") as f:
                json.dump(cfg, f)
            r = Router(self.cfg_path)
            res = r.chat("hey")
            self.assertEqual(res["model"], "good")
            self.assertTrue(res["fallback_used"])
        finally:
            twin.shutdown()

    def test_all_fail_raises(self):
        cfg = {
            "tier_order": ["fast"],
            "routes": {"easy": "fast", "medium": "fast", "hard": "fast"},
            "models": [{"name": "dead", "tier": "fast", "base_url": "http://127.0.0.1:1/v1",
                        "api_key_env": "ROUTER_TEST_FAST"}],
        }
        with open(self.cfg_path, "w") as f:
            json.dump(cfg, f)
        r = Router(self.cfg_path)
        with self.assertRaises(RouterError):
            r.chat("hey")

    def test_cost_recorded(self):
        r = Router(self.cfg_path)
        res = r.chat("hey")
        self.assertAlmostEqual(res["cost_usd"], 10 / 1e6 * 0.1 + 20 / 1e6 * 0.4)

    def test_decision_logged(self):
        r = Router(self.cfg_path)
        r.chat("hey")
        rows = store.read_all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["model"], "flash")
        self.assertEqual(rows[0]["difficulty"], "easy")

    def test_tier_override(self):
        r = Router(self.cfg_path)
        res = r.chat("hey", tier="smart")
        self.assertEqual(res["model"], "pro")
        self.assertEqual(res["tier"], "smart")

    def test_stats_aggregate(self):
        r = Router(self.cfg_path)
        r.chat("hey")
        r.chat("debug this:\n```python\ndef f(x):\n    return x/0\n```")
        s = store.stats()
        self.assertEqual(s["requests"], 2)
        self.assertGreater(s["total_cost"], 0)
        self.assertIn("flash", s["by_model"])
        self.assertIn("pro", s["by_model"])


class CliTests(unittest.TestCase):
    def test_init_writes_config(self):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "models.json")
            cli_main(["init", "--path", path])
            cfg = routes.load_config(path)
            self.assertEqual(len(cfg["models"]), 2)
        finally:
            shutil.rmtree(d)

    def test_init_refuses_overwrite(self):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "models.json")
            with open(path, "w") as f:
                f.write("{}")
            with self.assertRaises(SystemExit):
                cli_main(["init", "--path", path])
        finally:
            shutil.rmtree(d)

    def test_classify_prints(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli_main(["classify", "debug this:\n```python\nx=1\n```"])
        self.assertIn("hard", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
