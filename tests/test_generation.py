"""生成端测试 — Clash 字段正确性 + URI 往返。"""
import base64
import json
import unittest

from proxy_hub.parser import (
    parse_ss, parse_vmess, parse_trojan, parse_vless, parse_hysteria2,
    parse_single_link,
)
from proxy_hub.subscription import _proxy_to_clash, _build_clash_proxies, _clean_name
from proxy_hub.uri_gen import proxy_to_uri, generate_base64_subscription


def b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


UUID = "b831381d-6324-4d53-ad4f-8cda48b30811"


class TestClashGen(unittest.TestCase):
    def test_vless_ws_tls(self):
        p = parse_vless(
            f"vless://{UUID}@1.2.3.4:443?security=tls&sni=sni.x.com"
            "&type=ws&path=%2Fws&host=cdn.x.com&fp=chrome#n")
        cp = _proxy_to_clash(p)
        self.assertIsNotNone(cp)
        self.assertTrue(cp["tls"])
        self.assertEqual(cp["servername"], "sni.x.com")
        self.assertEqual(cp["network"], "ws")
        self.assertEqual(cp["ws-opts"]["path"], "/ws")
        self.assertEqual(cp["ws-opts"]["headers"]["Host"], "cdn.x.com")
        self.assertEqual(cp["client-fingerprint"], "chrome")
        # 不能再出现 mihomo 不认识的旧字段
        for bad in ("sni", "fp", "ws-path", "cipher", "alterId", "encryption", "host"):
            self.assertNotIn(bad, cp)

    def test_vless_reality(self):
        pbk = "SbVKOEMjK0sIlbwg4akyBg5mL5KZwwB-ed4eEE7YnRc"
        p = parse_vless(
            f"vless://{UUID}@1.2.3.4:443?security=reality&sni=www.apple.com"
            f"&pbk={pbk}&sid=ab12&fp=chrome&type=tcp&flow=xtls-rprx-vision#r")
        cp = _proxy_to_clash(p)
        self.assertIsNotNone(cp)
        self.assertEqual(cp["reality-opts"]["public-key"], pbk)
        self.assertEqual(cp["reality-opts"]["short-id"], "ab12")
        self.assertEqual(cp["flow"], "xtls-rprx-vision")
        self.assertEqual(cp["client-fingerprint"], "chrome")

    def test_vless_xray_encryption_skipped(self):
        p = parse_vless(
            f"vless://{UUID}@1.2.3.4:443?encryption=mlkem768x25519plus.native.x&security=tls#n")
        self.assertIsNone(_proxy_to_clash(p))

    def test_vless_bad_uuid_skipped(self):
        p = parse_vless("vless://not-a-uuid@1.2.3.4:443?security=tls#n")
        self.assertIsNone(_proxy_to_clash(p))

    def test_vless_reality_missing_pbk_skipped(self):
        p = parse_vless(f"vless://{UUID}@1.2.3.4:443?security=reality&sni=a.com#n")
        self.assertIsNone(_proxy_to_clash(p))

    def test_vmess_ws(self):
        d = {"v": "2", "ps": "n", "add": "a.com", "port": "443", "id": UUID,
             "aid": "0", "net": "ws", "host": "cdn.a.com", "path": "/v",
             "tls": "tls", "sni": "sni.a.com"}
        p = parse_vmess("vmess://" + b64(json.dumps(d)))
        cp = _proxy_to_clash(p)
        self.assertEqual(cp["ws-opts"]["path"], "/v")
        self.assertEqual(cp["ws-opts"]["headers"]["Host"], "cdn.a.com")
        self.assertEqual(cp["servername"], "sni.a.com")
        self.assertNotIn("ws-path", cp)

    def test_vmess_kcp_skipped(self):
        d = {"v": "2", "ps": "n", "add": "a.com", "port": "443", "id": UUID,
             "net": "kcp"}
        p = parse_vmess("vmess://" + b64(json.dumps(d)))
        self.assertIsNone(_proxy_to_clash(p))

    def test_trojan_uses_sni_field(self):
        p = parse_trojan("trojan://pw@t.com:443?sni=real.t.com&allowInsecure=1#n")
        cp = _proxy_to_clash(p)
        self.assertEqual(cp["sni"], "real.t.com")
        self.assertTrue(cp["skip-cert-verify"])

    def test_ss_bad_cipher_skipped(self):
        p = parse_ss(f"ss://{b64('ssr-cipher-x:pw')}@1.1.1.1:1#x")
        self.assertIsNone(_proxy_to_clash(p))

    def test_ss_empty_cipher_skipped(self):
        self.assertIsNone(_proxy_to_clash(
            {"proxy_type": "ss", "name": "x", "host": "1.1.1.1", "port": 1,
             "cipher": "", "password": "p"}))

    def test_ss_obfs_plugin(self):
        link = (f"ss://{b64('aes-128-gcm:pw')}@1.1.1.1:443/"
                "?plugin=obfs-local%3Bobfs%3Dhttp%3Bobfs-host%3Dbing.com#x")
        cp = _proxy_to_clash(parse_ss(link))
        self.assertEqual(cp["plugin"], "obfs")
        self.assertEqual(cp["plugin-opts"]["mode"], "http")
        self.assertEqual(cp["plugin-opts"]["host"], "bing.com")

    def test_hysteria2(self):
        p = parse_hysteria2(
            "hysteria2://pw@h.com:443?insecure=1&sni=s.com&obfs=salamander&obfs-password=op&mport=443-445#n")
        cp = _proxy_to_clash(p)
        self.assertEqual(cp["sni"], "s.com")
        self.assertTrue(cp["skip-cert-verify"])
        self.assertEqual(cp["obfs"], "salamander")
        self.assertEqual(cp["obfs-password"], "op")
        self.assertEqual(cp["ports"], "443-445")

    def test_name_cleanup_and_dedup(self):
        ps = []
        for i, host in enumerate(("1.1.1.1", "2.2.2.2")):
            p = parse_trojan(f"trojan://pw@{host}:443#%F0%9F%87%A9%F0%9F%87%AA%20DE")
            ps.append(p)
        out = _build_clash_proxies(ps)
        self.assertEqual(out[0]["name"], "🇩🇪 DE")
        self.assertEqual(out[1]["name"], "🇩🇪 DE #2")

    def test_clean_name_strips_controls(self):
        self.assertEqual(_clean_name("a\x00b\tc", "f"), "abc")
        self.assertEqual(_clean_name("  %E9%A6%99%E6%B8%AF  01  ", "f"), "香港 01")
        self.assertEqual(_clean_name("", "fallback"), "fallback")


class TestReviewRegressions(unittest.TestCase):
    """diff 复审确认的问题的回归测试。"""

    def test_malformed_reality_pbk_skipped(self):
        # 畸形 pbk（解不出 32 字节）会让 mihomo 拒绝整个配置，必须跳过节点
        p = parse_vless(f"vless://{UUID}@1.2.3.4:443?security=reality&pbk=abc&sni=a.com&fp=chrome#bad")
        self.assertIsNone(_proxy_to_clash(p))
        # 合法 43 字符 base64url pbk 正常通过
        p2 = parse_vless(
            f"vless://{UUID}@1.2.3.4:443?security=reality"
            "&pbk=SbVKOEMjK0sIlbwg4akyBg5mL5KZwwB-ed4eEE7YnRc&sid=6ba85179&sni=a.com#ok")
        self.assertIsNotNone(_proxy_to_clash(p2))

    def test_malformed_reality_sid_skipped(self):
        pbk = "SbVKOEMjK0sIlbwg4akyBg5mL5KZwwB-ed4eEE7YnRc"
        for sid in ("zzzz", "abc", "a" * 18):  # 非 hex / 奇数长度 / 超长
            p = parse_vless(
                f"vless://{UUID}@1.2.3.4:443?security=reality&pbk={pbk}&sid={sid}#bad")
            self.assertIsNone(_proxy_to_clash(p), f"sid={sid} 应被跳过")
        p_ok = parse_vless(
            f"vless://{UUID}@1.2.3.4:443?security=reality&pbk={pbk}&sid=ab12#ok")
        self.assertIsNotNone(_proxy_to_clash(p_ok))

    def test_hy2_obfs_without_password_skipped(self):
        # mihomo: "missing obfs password" 会让整份配置被拒
        p = parse_hysteria2("hy2://pw@1.2.3.4:443?obfs=salamander#n")
        self.assertIsNone(_proxy_to_clash(p))
        p_ok = parse_hysteria2("hy2://pw@1.2.3.4:443?obfs=salamander&obfs-password=x#n")
        self.assertIsNotNone(_proxy_to_clash(p_ok))

    def test_hy2_ports_sanitized(self):
        p = parse_hysteria2("hy2://pw@1.2.3.4:443?mport=443;8443#n")
        cp = _proxy_to_clash(p)
        self.assertEqual(cp.get("ports"), "443,8443")
        p2 = parse_hysteria2("hy2://pw@1.2.3.4:443?mport=abc-def#n")
        cp2 = _proxy_to_clash(p2)
        self.assertIsNotNone(cp2)
        self.assertNotIn("ports", cp2)  # 垃圾值丢弃但节点保留

    def test_legacy_security_none_still_convertible(self):
        # 旧 DB 行：security=none 的 ws 节点不能被误杀
        p = {"proxy_type": "vless", "name": "l", "host": "1.2.3.4", "port": 80,
             "uuid": UUID,
             "extra": json.dumps({"encryption": "none", "security": "none",
                                  "type": "ws", "path": "/ws"})}
        cp = _proxy_to_clash(p)
        self.assertIsNotNone(cp)
        self.assertEqual(cp["ws-opts"]["path"], "/ws")

    def test_legacy_type_grpc_network(self):
        p = {"proxy_type": "vless", "name": "l", "host": "1.2.3.4", "port": 443,
             "uuid": UUID,
             "extra": json.dumps({"security": "tls", "type": "grpc",
                                  "serviceName": "gun", "sni": "a.com"})}
        cp = _proxy_to_clash(p)
        self.assertEqual(cp["network"], "grpc")
        self.assertEqual(cp["grpc-opts"]["grpc-service-name"], "gun")

    def test_vmess_float_port(self):
        d = {"v": "2", "ps": "n", "add": "a.com", "port": 443.0, "id": UUID, "net": "tcp"}
        p = parse_vmess("vmess://" + b64(json.dumps(d)))
        self.assertIsNotNone(p)
        self.assertEqual(p["port"], 443)

    def test_legacy_ss_b64_with_slash(self):
        raw = "aes-256-gcm:pa?ss@1.2.3.4:8388"
        body = base64.b64encode(raw.encode()).decode()
        self.assertIn("/", body)
        from proxy_hub.parser import parse_ss
        p = parse_ss(f"ss://{body}")
        self.assertIsNotNone(p)
        self.assertEqual(p["password"], "pa?ss")

    def test_vmess_httpupgrade_flag(self):
        d = {"v": "2", "ps": "n", "add": "a.com", "port": "443", "id": UUID,
             "net": "httpupgrade", "path": "/up", "tls": "tls"}
        p = parse_vmess("vmess://" + b64(json.dumps(d)))
        self.assertTrue(p["extra"].get("http_upgrade"))
        cp = _proxy_to_clash(p)
        self.assertTrue(cp["ws-opts"]["v2ray-http-upgrade"])

    def test_trojan_http_header_skipped(self):
        p = parse_trojan("trojan://pw@1.2.3.4:443?type=tcp&headerType=http&path=/a#x")
        self.assertIsNone(_proxy_to_clash(p))


class TestUriRoundtrip(unittest.TestCase):
    def _roundtrip(self, link):
        p = parse_single_link(link)
        self.assertIsNotNone(p, f"parse failed: {link}")
        uri = proxy_to_uri(p)
        self.assertIsNotNone(uri, f"gen failed: {link}")
        p2 = parse_single_link(uri)
        self.assertIsNotNone(p2, f"reparse failed: {uri}")
        return p, p2

    def test_ss_roundtrip(self):
        p, p2 = self._roundtrip(f"ss://{b64('aes-256-gcm:p@ss:word')}@1.2.3.4:8388#名字")
        self.assertEqual(p["cipher"], p2["cipher"])
        self.assertEqual(p["password"], p2["password"])
        self.assertEqual(p["name"], p2["name"])

    def test_ss_2022_roundtrip(self):
        p, p2 = self._roundtrip("ss://2022-blake3-aes-256-gcm:a%2Bb%3Dc@1.2.3.4:8388#n")
        self.assertEqual(p2["password"], "a+b=c")

    def test_vless_reality_roundtrip(self):
        p, p2 = self._roundtrip(
            f"vless://{UUID}@1.2.3.4:443?security=reality&sni=www.apple.com"
            "&pbk=PBK-123&sid=ab&fp=chrome&type=tcp&flow=xtls-rprx-vision#节点A")
        e1, e2 = p["extra"], p2["extra"]
        for k in ("reality_pbk", "reality_sid", "sni", "fp", "flow"):
            self.assertEqual(e1.get(k), e2.get(k), k)

    def test_vmess_ws_roundtrip(self):
        d = {"v": "2", "ps": "日本 East", "add": "a.com", "port": "443", "id": UUID,
             "aid": "2", "net": "ws", "host": "cdn.a.com", "path": "/v?x=1",
             "tls": "tls", "sni": "sni.a.com", "scy": "auto"}
        p, p2 = self._roundtrip("vmess://" + b64(json.dumps(d)))
        e1, e2 = p["extra"], p2["extra"]
        self.assertEqual(e2["ws_path"], "/v?x=1")
        self.assertEqual(e2["ws_host"], "cdn.a.com")
        self.assertEqual(e2.get("alter_id"), 2)
        self.assertEqual(p2["name"], "日本 East")

    def test_trojan_ws_roundtrip(self):
        p, p2 = self._roundtrip(
            "trojan://p%40w@t.com:443?type=ws&path=%2Fa%20b&host=cdn.t.com&sni=s.t.com&allowInsecure=1#x")
        e2 = p2["extra"]
        self.assertEqual(p2["password"], "p@w")
        self.assertEqual(e2["ws_path"], "/a b")
        self.assertTrue(e2["skip_cert_verify"])

    def test_hy2_roundtrip(self):
        p, p2 = self._roundtrip(
            "hysteria2://pw%2B1@h.com:443?sni=s.com&insecure=1&obfs=salamander&obfs-password=o%2Bp&mport=443-445#h")
        self.assertEqual(p2["password"], "pw+1")
        self.assertEqual(p2["extra"]["obfs_password"], "o+p")
        self.assertEqual(p2["extra"]["ports"], "443-445")

    def test_ipv6_roundtrip(self):
        p, p2 = self._roundtrip(f"trojan://pw@[2001:db8::2]:443?sni=a.com#v6")
        self.assertEqual(p2["host"], "2001:db8::2")

    def test_b64_subscription_padding(self):
        p = parse_trojan("trojan://pw@1.2.3.4:443#n")
        out = generate_base64_subscription([p])
        # 标准 base64（含 padding），客户端普遍兼容
        base64.b64decode(out)


if __name__ == "__main__":
    unittest.main()
