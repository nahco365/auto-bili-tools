import os
import unittest
from io import BytesIO
import hashlib
from types import SimpleNamespace
from unittest.mock import patch

import bili_qinglong as bili
import bili_medal
import bili_device
import bili_login


class FakeClient:
    def __init__(self):
        self.calls = []
        self.csrf = "csrf"
        self.uid = "42"

    def get(self, path, params=None, **kwargs):
        self.calls.append(("GET", path, params))
        if path == "/x/member/web/exp/reward":
            return {"watch": True, "share": True}
        if path == "/x/web-interface/coin/today/exp":
            return 20
        if path == "/site/getCoin":
            return {"money": 4}
        if path == "/x/web-interface/archive/coins":
            return {"multiply": 0}
        raise AssertionError(path)

    def post(self, path, form=None, **kwargs):
        self.calls.append(("POST", path, form))
        return {}


class BiliTests(unittest.TestCase):
    def test_qinglong_login_upserts_cookie_for_same_uid(self):
        cookie = "DedeUserID=42; SESSDATA=new; bili_jct=x"
        old = {"id": 7, "name": "BiliBiliCookies__1",
               "value": "DedeUserID=42; SESSDATA=old; bili_jct=x"}
        replies = [{"code": 200, "data": {"token_type": "Bearer", "token": "token"}},
                   {"code": 200, "data": [old]}, {"code": 200}]
        with patch.dict(os.environ, {"Ray_QingLongConfig__ClientId": "id",
                                     "Ray_QingLongConfig__ClientSecret": "secret"}, clear=True), \
             patch.object(bili_login, "open_json", side_effect=replies) as request:
            self.assertTrue(bili_login.save_qinglong(cookie))
        self.assertEqual(request.call_args.args[2], "PUT")
        self.assertEqual(request.call_args.args[3]["id"], 7)
        self.assertEqual(request.call_args.args[3]["value"], cookie)

    def test_qinglong_login_creates_unprefixed_cookie_variable(self):
        cookie = "DedeUserID=42; SESSDATA=new; bili_jct=x"
        old = {"id": 7, "name": "Ray_BiliBiliCookies__1",
               "value": "DedeUserID=42; SESSDATA=old; bili_jct=x"}
        replies = [{"code": 200, "data": {"token_type": "Bearer", "token": "token"}},
                   {"code": 200, "data": [old]}, {"code": 200}]
        with patch.dict(os.environ, {"Ray_QingLongConfig__ClientId": "id",
                                     "Ray_QingLongConfig__ClientSecret": "secret"}, clear=True), \
             patch.object(bili_login, "open_json", side_effect=replies) as request:
            self.assertTrue(bili_login.save_qinglong(cookie))
        self.assertEqual(request.call_args.args[2], "POST")
        self.assertEqual(request.call_args.args[3][0]["name"], "BiliBiliCookies__1")

    def test_only_old_prefixed_cookie_does_not_load(self):
        with patch.dict(os.environ, {"Ray_BiliBiliCookies__1": "old=1"}, clear=True):
            self.assertEqual(bili.cookies(), [])

    def test_qr_login_always_logs_full_cookie_and_save_result(self):
        cookies = [SimpleNamespace(name=name, value=value) for name, value in (
            ("DedeUserID", "42"), ("SESSDATA", "session"), ("bili_jct", "csrf"))]
        replies = [{"code": 0, "data": {"url": "https://example.test/qr", "qrcode_key": "key"}},
                   {"code": 0, "data": {"code": 0}}]
        for save_result in (True, False, RuntimeError("temporary failure")):
            save_options = ({"side_effect": save_result} if isinstance(save_result, Exception)
                            else {"return_value": save_result})
            with self.subTest(save_result=save_result), \
                 patch.object(bili_login, "CookieJar", return_value=cookies), \
                 patch.object(bili_login, "HTTPCookieProcessor"), \
                 patch.object(bili_login, "build_opener"), \
                 patch.object(bili_login, "open_json", side_effect=replies), \
                 patch.object(bili_login.time, "sleep"), \
                 patch.object(bili_device, "ensure_device", return_value=False), \
                 patch.object(bili_login, "save_qinglong", **save_options), \
                 self.assertLogs("bili", level="INFO") as logs:
                self.assertEqual(bili_login.qr_login(), 0)
            output = "\n".join(logs.output)
            self.assertIn("DedeUserID=42; SESSDATA=session; bili_jct=csrf", output)
            self.assertIn("Ray_QingLongConfig__ClientId", output)
            self.assertIn("已自动写入" if save_result is True else "未自动写入", output)

    def test_terminal_qr_has_scannable_matrix_shape(self):
        matrix = bili_login.terminal_qr("https://passport.bilibili.com/qr-test")
        rows = matrix.splitlines()
        self.assertGreater(len(rows), 10)
        self.assertEqual(len({len(row) for row in rows}), 1)
        self.assertIn("█", matrix)
        self.assertTrue(any(char in matrix for char in ("▀", "▄")))

    def test_cookie_order_and_ignores_old_prefixed_name(self):
        env = {"BiliBiliCookies__1": "new=1", "Ray_BiliBiliCookies__1": "old=1",
               "BiliBiliCookies__3": "third=1"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(bili.cookies(), [(1, "new=1"), (3, "third=1")])

    def test_coin_respects_target_and_protected_balance(self):
        client = FakeClient()
        with patch.dict(os.environ, {"Ray_DailyTaskConfig__NumberOfCoins": "5",
                                     "Ray_DailyTaskConfig__NumberOfProtectedCoins": "3"}, clear=True), \
             patch.object(bili, "random_video", side_effect=[bili.Video(x, f"BV{x}") for x in range(4)]):
            bili.donate_coins(client, {"money": 4})
        posts = [call for call in client.calls if call[0] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][2]["multiply"], 1)

    def test_daily_skips_video_if_already_done(self):
        client = FakeClient()
        with patch.dict(os.environ, {"Ray_DailyTaskConfig__NumberOfCoins": "0"}, clear=True):
            bili.daily(client, {"level_info": {"current_level": 1}, "vipType": 0})
        self.assertFalse(any(method == "POST" for method, _, _ in client.calls))

    def test_video_failure_does_not_block_vip_privilege(self):
        client = FakeClient()
        original_get = client.get
        def get(path, params=None, **kwargs):
            if path == "/x/member/web/exp/reward":
                return {"watch": False, "share": False}
            return original_get(path, params, **kwargs)
        client.get = get
        with patch.dict(os.environ, {"Ray_DailyTaskConfig__NumberOfCoins": "0"}, clear=True), \
             patch.object(bili, "random_video", side_effect=bili.ApiError("无视频")):
            bili.daily(client, {"level_info": {"current_level": 1}, "vipType": 2, "vipStatus": 1})
        self.assertEqual(len([c for c in client.calls if c[1] == "/x/vip/privilege/receive"]), 2)

    def test_invalid_cookie_never_sent(self):
        with self.assertRaisesRegex(ValueError, "SESSDATA"):
            bili.Client("bili_jct=abc")

    def test_charge_requires_annual_vip_and_coupon(self):
        client = FakeClient()
        with patch.dict(os.environ, {"Ray_ChargeTaskConfig__AutoChargeUpId": "12345"}, clear=True):
            bili.charge(client, {"vipType": 1, "vipStatus": 1, "wallet": {"coupon_balance": 5}})
            bili.charge(client, {"vipType": 2, "vipStatus": 1, "wallet": {"coupon_balance": 1}})
        self.assertEqual(client.calls, [])

    def test_charge_uses_each_accounts_target_and_skips_unconfigured_account(self):
        user = {"vipType": 2, "vipStatus": 1, "wallet": {"coupon_balance": 3}}
        clients = [FakeClient() for _ in range(3)]
        for client, uid in zip(clients, ("42", "43", "44")):
            client.uid = uid
            def post(path, form=None, *, owner=client, **kwargs):
                owner.calls.append(("POST", path, form))
                return {"status": 4}
            client.post = post
        env = {"BiliBiliCookies__1": "one", "BiliBiliCookies__2": "two",
               "BiliBiliCookies__3": "three",
               "Ray_ChargeTaskConfig__AutoChargeUpId": "999",
               "Ray_ChargeTaskConfig__AutoChargeUpId__42": "123",
               "Ray_ChargeTaskConfig__AutoChargeUpId__43": "456"}
        with patch.dict(os.environ, env, clear=True):
            for client in clients:
                bili.charge(client, user)
        self.assertEqual(clients[0].calls[0][2]["up_mid"], "123")
        self.assertEqual(clients[1].calls[0][2]["up_mid"], "456")
        self.assertEqual(clients[2].calls, [])

    def test_charge_without_target_never_posts(self):
        client = FakeClient()
        with patch.dict(os.environ, {"BiliBiliCookies__1": "one"}, clear=True):
            bili.charge(client, {"vipType": 2, "vipStatus": 1,
                                 "wallet": {"coupon_balance": 10}})
        self.assertEqual(client.calls, [])
        self.assertIs(bili.TASKS["CookieTest"], bili.TASKS["Test"])

    def test_manga_already_signed_is_idempotent(self):
        client = FakeClient()
        def post(path, form=None, **kwargs):
            if path.endswith("ClockIn"):
                raise bili.ApiError("不能重复签到~", 1)
            return {}
        client.post = post
        bili.RUN_FAILURES.clear()
        with patch.dict(os.environ, {}, clear=True):
            bili.manga(client, {})
        self.assertEqual(bili.RUN_FAILURES, [])

    def test_unfollow_preserves_whitelist(self):
        client = FakeClient()
        def get(path, params=None, **kwargs):
            if path == "/x/relation/tags":
                return [{"name": "天选时刻", "tagid": 7, "count": 2}]
            if path == "/x/relation/tag":
                return [{"mid": 1}, {"mid": 2}]
            raise AssertionError(path)
        client.get = get
        with patch.dict(os.environ, {"Ray_UnfollowBatchedTaskConfig__RetainUids": "1",
                                     "Ray_UnfollowBatchedTaskConfig__Count": "2"}, clear=True):
            bili.unfollow_batched(client, {})
        posts = [call for call in client.calls if call[0] == "POST"]
        self.assertEqual([item[2]["fid"] for item in posts], ["2"])

    def test_medal_progress_and_hmac(self):
        data = {"is_lighted": True, "task_info": [{"jump_type": "watchLive", "title": "观看 5 分钟",
                "sub_title": "1/3", "is_done": False}]}
        self.assertEqual(bili_medal.task_plan(data, "watchLive"), (600, 300))
        self.assertEqual(bili_medal.signature("abc", [0], "key"),
                         "d2fe98063f876b03193afb49b4979591")

    def test_gaia_payload_has_updated_uuid(self):
        data = bili_device.gaia_payload("TEST-UUID")
        import json
        parsed = json.loads(data)
        self.assertEqual(parsed["df35"], "TEST-UUID")
        self.assertIn(parsed["3c43"]["748e"][0], (1920, 1600, 1536, 1440, 2560))

    def test_vip_big_point_claims_and_completes_available_task(self):
        client = FakeClient()
        client.fields = {"buvid3": "device"}
        client.get = lambda path, params=None, **kwargs: (
            {"list": []} if path == "/x/vip/privilege/my" else
            {"three_day_sign": {"signed": True}} if path.endswith("three_days_sign") else
            {"point_info": {"point": 100}, "task_info": {"modules": [
                {"common_task_item": [{"task_code": "dress-view", "state": 0}]}]}}
            if path == "/x/vip_point/task/combine" else self.fail(path))
        with patch.dict(os.environ, {}, clear=True):
            bili.vip_big_point(client, {"vipType": 2, "vipStatus": 1})
        self.assertEqual([call[1] for call in client.calls if call[0] == "POST"],
                         ["/pgc/activity/score/task/receive/v2", "/pgc/activity/score/task/complete/v2"])

    def test_expired_vip_cannot_claim(self):
        client = FakeClient()
        bili.vip_privilege(client, {"vipType": 2, "vipStatus": 0})
        self.assertEqual(client.calls, [])

    def test_http_form_encoding_and_api_error(self):
        class Response:
            def __init__(self, payload):
                self.payload = BytesIO(payload)
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self):
                return self.payload.read()
        with patch.dict(os.environ, {"Ray_Security__IntervalSecondsBetweenRequestApi": "0"}, clear=True):
            client = bili.Client("SESSDATA=x; bili_jct=token; DedeUserID=42")
        recorded = []
        def open_request(request, timeout):
            recorded.append(request)
            return Response(b'{"code":0,"data":{"ok":true}}')
        client.opener.open = open_request
        self.assertEqual(client.post("/test", {"csrf": "a+b"}), {"ok": True})
        self.assertEqual(recorded[0].get_method(), "POST")
        self.assertEqual(recorded[0].data, b"csrf=a%2Bb")

    def test_wbi_signs_escaped_values_but_keeps_original_payload(self):
        with patch.dict(os.environ, {}, clear=True):
            client = bili.Client("SESSDATA=x; bili_jct=token; DedeUserID=42")
        client.mixin_key = "secret"
        with patch.object(bili.time, "time", return_value=1000):
            result = client.wbi({"ua": "Browser (Test)", "id": "1"})
        self.assertEqual(result["ua"], "Browser (Test)")
        query = "id=1&ua=Browser%20Test&wts=1000"
        self.assertEqual(result["w_rid"], hashlib.md5((query + "secret").encode()).hexdigest())


if __name__ == "__main__":
    unittest.main()
