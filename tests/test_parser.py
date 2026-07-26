"""解析器测试 — 覆盖真实世界的分享链接形态。"""
import base64
import json
import unittest

from proxy_hub.parser import (
    parse_ss, parse_vmess, parse_trojan, parse_vless, parse_hysteria2,
    parse_clash_yaml, parse_content, parse_sip008, normalize_extra,
)


def b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


class TestSS(unittest.TestCase):
    def test_sip002_base64_userinfo(self):
        link = f"ss://{b64('aes-256-gcm:passw0rd')}@1.2.3.4:8388#%E9%A6%99%E6%B8%AF"
        p = parse_ss(link)
        self.assertEqual(p["cipher"], "aes-256-gcm")
        self.assertEqual(p["password"], "passw0rd")
        self.assertEqual(p["host"], "1.2.3.4")
        self.assertEqual(p["port"], 8388)
        self.assertEqual(p["name"], "香港")

    def test_sip002_urlsafe_no_padding(self):
        userinfo = base64.urlsafe_b64encode(b"chacha20-ietf-poly1305:p@ss/w+rd").decode().rstrip("=")
        p = parse_ss(f"ss://{userinfo}@example.com:443#node")
        self.assertIsNotNone(p)
        self.assertEqual(p["cipher"], "chacha20-ietf-poly1305")
        self.assertEqual(p["password"], "p@ss/w+rd")

    def test_sip002_2022_plain_userinfo(self):
        p = parse_ss("ss://2022-blake3-aes-256-gcm:YWJjZGVmZw%3D%3D@8.8.8.8:8388#n")
        self.assertIsNotNone(p)
        self.assertEqual(p["cipher"], "2022-blake3-aes-256-gcm")
        self.assertEqual(p["password"], "YWJjZGVmZw==")

    def test_legacy_full_base64(self):
        p = parse_ss(f"ss://{b64('rc4-md5:pwd@9.9.9.9:1234')}#old")
        self.assertIsNotNone(p)
        self.assertEqual(p["cipher"], "rc4-md5")
        self.assertEqual(p["host"], "9.9.9.9")
        self.assertEqual(p["port"], 1234)

    def test_plugin_param(self):
        link = (f"ss://{b64('aes-128-gcm:pw')}@1.1.1.1:443/"
                "?plugin=obfs-local%3Bobfs%3Dtls%3Bobfs-host%3Dbing.com#x")
        p = parse_ss(link)
        self.assertIsNotNone(p)
        self.assertEqual(p["plugin"], "obfs-local")
        self.assertIn("obfs=tls", p["plugin_opts"])

    def test_ipv6_host(self):
        p = parse_ss(f"ss://{b64('aes-256-gcm:pw')}@[2001:db8::1]:8388#v6")
        self.assertIsNotNone(p)
        self.assertEqual(p["host"], "2001:db8::1")
        self.assertEqual(p["port"], 8388)

    def test_invalid(self):
        self.assertIsNone(parse_ss("ss://garbage"))
        self.assertIsNone(parse_ss("ss://@host:80"))
        self.assertIsNone(parse_ss(f"ss://{b64('aes:pw')}@host:99999#x"))


class TestVmess(unittest.TestCase):
    def _link(self, **kw):
        d = {"v": "2", "ps": "测试", "add": "example.com", "port": "443",
             "id": "b831381d-6324-4d53-ad4f-8cda48b30811", "aid": "0",
             "net": "ws", "type": "none", "host": "cdn.example.com",
             "path": "/ws", "tls": "tls"}
        d.update(kw)
        return "vmess://" + b64(json.dumps(d))

    def test_ws_tls(self):
        p = parse_vmess(self._link())
        self.assertEqual(p["uuid"], "b831381d-6324-4d53-ad4f-8cda48b30811")
        e = p["extra"]
        self.assertEqual(e["network"], "ws")
        self.assertEqual(e["ws_path"], "/ws")
        self.assertEqual(e["ws_host"], "cdn.example.com")
        self.assertTrue(e["tls"])
        self.assertEqual(e["sni"], "cdn.example.com")  # 无 sni 时回退 host

    def test_port_as_int(self):
        p = parse_vmess(self._link(port=8080))
        self.assertEqual(p["port"], 8080)

    def test_grpc(self):
        p = parse_vmess(self._link(net="grpc", path="my-service"))
        self.assertEqual(p["extra"]["grpc_service_name"], "my-service")

    def test_tcp_http_header(self):
        p = parse_vmess(self._link(net="tcp", type="http", path="/", tls=""))
        e = p["extra"]
        self.assertEqual(e.get("header_type"), "http")

    def test_invalid_json(self):
        self.assertIsNone(parse_vmess("vmess://bm90anNvbg=="))


class TestTrojan(unittest.TestCase):
    def test_basic(self):
        p = parse_trojan("trojan://pass%40word@example.com:443?sni=sni.example.com&allowInsecure=1#节点")
        self.assertEqual(p["password"], "pass@word")
        e = p["extra"]
        self.assertTrue(e["tls"])
        self.assertEqual(e["sni"], "sni.example.com")
        self.assertTrue(e["skip_cert_verify"])

    def test_ws_transport(self):
        p = parse_trojan("trojan://pw@1.2.3.4:443?type=ws&path=%2Ftr&host=cdn.x.com#n")
        e = p["extra"]
        self.assertEqual(e["network"], "ws")
        self.assertEqual(e["ws_path"], "/tr")
        self.assertEqual(e["ws_host"], "cdn.x.com")


class TestVless(unittest.TestCase):
    def test_reality(self):
        p = parse_vless(
            "vless://b831381d-6324-4d53-ad4f-8cda48b30811@1.2.3.4:443"
            "?security=reality&sni=www.apple.com&fp=chrome&pbk=SbVKOEMjK0sIlbwg4akyBg5mL5KZwwB-ed4eEE7YnRc"
            "&sid=6ba85179&type=tcp&flow=xtls-rprx-vision#RealityNode")
        e = p["extra"]
        self.assertTrue(e["tls"])
        self.assertEqual(e["security"], "reality")
        self.assertEqual(e["reality_pbk"], "SbVKOEMjK0sIlbwg4akyBg5mL5KZwwB-ed4eEE7YnRc")
        self.assertEqual(e["reality_sid"], "6ba85179")
        self.assertEqual(e["flow"], "xtls-rprx-vision")

    def test_ws_tls_missing_security_not_tls(self):
        p = parse_vless("vless://b831381d-6324-4d53-ad4f-8cda48b30811@x.com:80?type=ws&path=/#n")
        self.assertNotIn("tls", p["extra"])

    def test_vless_encryption_preserved(self):
        p = parse_vless(
            "vless://b831381d-6324-4d53-ad4f-8cda48b30811@x.com:443"
            "?encryption=mlkem768x25519plus.native.0rtt.abc&security=tls#n")
        self.assertTrue(p["extra"]["encryption"].startswith("mlkem768x25519plus"))


class TestHysteria2(unittest.TestCase):
    def test_basic(self):
        p = parse_hysteria2("hysteria2://letmein@example.com:443/?insecure=1&sni=real.example.com#hy2")
        self.assertEqual(p["password"], "letmein")
        e = p["extra"]
        self.assertTrue(e["skip_cert_verify"])
        self.assertEqual(e["sni"], "real.example.com")

    def test_obfs_and_ports(self):
        p = parse_hysteria2("hy2://pw@1.2.3.4:443?obfs=salamander&obfs-password=ob%2Bfs&mport=40000-50000#n")
        e = p["extra"]
        self.assertEqual(e["obfs"], "salamander")
        self.assertEqual(e["obfs_password"], "ob+fs")  # '+' 不能被解码成空格
        self.assertEqual(e["ports"], "40000-50000")

    def test_port_range_in_host(self):
        p = parse_hysteria2("hysteria2://pw@example.com:443-445#n")
        self.assertEqual(p["port"], 443)
        self.assertEqual(p["extra"]["ports"], "443-445")


class TestClashYamlIngest(unittest.TestCase):
    def test_modern_ws_opts(self):
        text = """
proxies:
  - name: test-vmess
    type: vmess
    server: 1.2.3.4
    port: 443
    uuid: b831381d-6324-4d53-ad4f-8cda48b30811
    alterId: 0
    cipher: auto
    tls: true
    servername: sni.example.com
    network: ws
    ws-opts:
      path: /deep/path
      headers:
        Host: cdn.example.com
"""
        ps = parse_clash_yaml(text)
        self.assertEqual(len(ps), 1)
        e = ps[0]["extra"]
        self.assertEqual(e["ws_path"], "/deep/path")
        self.assertEqual(e["ws_host"], "cdn.example.com")
        self.assertTrue(e["tls"])
        self.assertEqual(e["sni"], "sni.example.com")

    def test_vless_reality_ingest(self):
        text = """
proxies:
  - name: r1
    type: vless
    server: 1.2.3.4
    port: 443
    uuid: b831381d-6324-4d53-ad4f-8cda48b30811
    tls: true
    servername: www.apple.com
    flow: xtls-rprx-vision
    client-fingerprint: chrome
    reality-opts:
      public-key: pbk123
      short-id: abcd
"""
        ps = parse_clash_yaml(text)
        self.assertEqual(len(ps), 1)
        e = ps[0]["extra"]
        self.assertEqual(e["reality_pbk"], "pbk123")
        self.assertEqual(e["reality_sid"], "abcd")
        self.assertEqual(e["flow"], "xtls-rprx-vision")

    def test_hysteria2_ingest(self):
        text = """
proxies:
  - {name: h1, type: hysteria2, server: h.com, port: 443, password: pw, sni: x.com, skip-cert-verify: true, obfs: salamander, obfs-password: op}
"""
        ps = parse_clash_yaml(text)
        self.assertEqual(len(ps), 1)
        self.assertEqual(ps[0]["extra"]["obfs"], "salamander")

    def test_numeric_name(self):
        text = "proxies:\n  - {name: 123, type: ss, server: a.com, port: 1, cipher: aes-128-gcm, password: p}\n"
        ps = parse_clash_yaml(text)
        self.assertEqual(ps[0]["name"], "123")

    def test_legacy_ws_path(self):
        text = """
proxies:
  - name: legacy
    type: vmess
    server: 1.2.3.4
    port: 80
    uuid: b831381d-6324-4d53-ad4f-8cda48b30811
    network: ws
    ws-path: /legacy
    ws-headers: {Host: h.example.com}
"""
        ps = parse_clash_yaml(text)
        e = ps[0]["extra"]
        self.assertEqual(e["ws_path"], "/legacy")
        self.assertEqual(e["ws_host"], "h.example.com")


class TestParseContent(unittest.TestCase):
    def test_base64_urlsafe_body(self):
        links = "\n".join([
            "trojan://pw@1.2.3.4:443#a",
            "vless://b831381d-6324-4d53-ad4f-8cda48b30811@x.com:443?security=tls#b",
        ])
        body = base64.urlsafe_b64encode(links.encode()).decode()
        ps = parse_content(body.encode())
        self.assertEqual(len(ps), 2)

    def test_sip008_dict_form(self):
        data = {"version": 1, "servers": [
            {"server": "1.1.1.1", "server_port": 8388,
             "method": "aes-256-gcm", "password": "pw", "remarks": "x"}]}
        ps = parse_content(json.dumps(data).encode())
        self.assertEqual(len(ps), 1)

    def test_yaml_with_leading_comment(self):
        text = "# generated\nmixed-port: 7890\nproxies:\n  - {name: a, type: ss, server: s.com, port: 1, cipher: aes-128-gcm, password: p}\n"
        ps = parse_content(text.encode())
        self.assertEqual(len(ps), 1)


class TestNormalizeExtra(unittest.TestCase):
    def test_legacy_keys_from_old_db(self):
        p = {"extra": json.dumps({
            "network": "ws", "path": "/x", "host": "cdn.a.com",
            "security": "tls", "sni": "a.com", "allowInsecure": "1",
        })}
        e = normalize_extra(p)
        self.assertTrue(e["tls"])
        self.assertEqual(e["ws_path"], "/x")
        self.assertEqual(e["ws_host"], "cdn.a.com")
        self.assertTrue(e["skip_cert_verify"])


if __name__ == "__main__":
    unittest.main()
