import requests
import yaml
import os
import base64
import json
from hashlib import md5

# ========== 配置：多个订阅源 ==========
SUBSCRIPTION_URLS = [
    "https://nodesfree.github.io/clashnode/subscribe/clash.yml",
    "https://raw.githubusercontent.com/vxiaov/free_proxies/main/clash/clash.provider.yaml",
    "https://raw.githubusercontent.com/shaoyouvip/free/refs/heads/main/all.yaml",
    "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.yml",
    "https://raw.githubusercontent.com/zhangkaiitugithub/passcro/main/speednodes.yaml",
    "https://raw.githubusercontent.com/xyfqzy/free-nodes/main/nodes/clash.yaml",
    "https://v2rayshare.githubrowcontent.com/2025/08/20250813.yaml",
    "https://raw.githubusercontent.com/go4sharing/sub/main/sub.yaml",
    "https://freenode.openrunner.net/uploads/20250813-clash.yaml",
    "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/clash.yml"
]

OUTPUT_ALL = "providers/all.yaml"
OUTPUT_US = "providers/us.yaml"


def download(url):
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"[❌] 下载失败: {url} 错误: {e}")
        return None


def parse_clash_yaml(text):
    try:
        data = yaml.safe_load(text)
        if isinstance(data, dict) and "proxies" in data:
            return data["proxies"]
    except Exception:
        return None
    return None


def parse_base64(text):
    try:
        decoded = base64.b64decode(text.strip() + "===")  # 修正 padding
        decoded_text = decoded.decode("utf-8", errors="ignore")
    except Exception:
        return None

    proxies = []
    for line in decoded_text.splitlines():
        line = line.strip()
        if not line:
            continue

        # vmess://
        if line.startswith("vmess://"):
            try:
                node_str = base64.b64decode(line[8:]).decode("utf-8")
                node_json = json.loads(node_str)
                proxies.append({
                    "name": node_json.get("ps", "vmess"),
                    "type": "vmess",
                    "server": node_json["add"],
                    "port": int(node_json["port"]),
                    "uuid": node_json["id"],
                    "alterId": int(node_json.get("aid", 0)),
                    "cipher": node_json.get("scy", "auto"),
                    "tls": True if node_json.get("tls") == "tls" else False,
                    "network": node_json.get("net", "tcp"),
                })
            except Exception as e:
                print(f"[⚠️] 解析 vmess 节点失败: {e}")

        # ss://
        elif line.startswith("ss://"):
            try:
                info = line[5:]
                if "#" in info:
                    info, name = info.split("#", 1)
                else:
                    name = "ss"

                userinfo_enc, server_port = info.split("@", 1)
                userinfo = base64.b64decode(userinfo_enc).decode(errors="ignore")
                cipher, password = userinfo.split(":", 1)
                server, port = server_port.split(":")
                proxies.append({
                    "name": name,
                    "type": "ss",
                    "server": server,
                    "port": int(port),
                    "cipher": cipher,
                    "password": password,
                })
            except Exception as e:
                print(f"[⚠️] 解析 ss 节点失败: {e}")

        # trojan://
        elif line.startswith("trojan://"):
            try:
                info = line[9:]
                if "@" in info:
                    password, rest = info.split("@", 1)
                    server, port = rest.split(":", 1)
                    proxies.append({
                        "name": "trojan",
                        "type": "trojan",
                        "server": server,
                        "port": int(port),
                        "password": password,
                    })
            except Exception as e:
                print(f"[⚠️] 解析 trojan 节点失败: {e}")

    return proxies if proxies else None


def deduplicate(proxies):
    seen = set()
    result = []
    for p in proxies:
        key = md5(f"{p.get('server')}:{p.get('port')}:{p.get('type')}".encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            result.append(p)
    return result


def filter_us(proxies, limit=10):
    us_nodes = [p for p in proxies if "US" in p.get("name", "").upper() or "美国" in p.get("name", "")]
    return us_nodes[:limit]


def save_yaml(path, proxies):
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"proxies": proxies}, f, allow_unicode=True)


def main():
    all_proxies = []
    os.makedirs("providers", exist_ok=True)

    for url in SUBSCRIPTION_URLS:
        text = download(url)
        if not text:
            continue

        proxies = parse_clash_yaml(text)
        if proxies:
            print(f"[✅] Clash YAML 订阅: {url} → {len(proxies)} 节点")
            all_proxies.extend(proxies)
            continue

        proxies = parse_base64(text)
        if proxies:
            print(f"[✅] Base64 订阅: {url} → {len(proxies)} 节点")
            all_proxies.extend(proxies)
            continue

        print(f"[⚠️] 未能识别订阅格式: {url}")

    merged = deduplicate(all_proxies)
    print(f"[📦] 合并后节点总数: {len(merged)}")

    # 保存 all.yaml
    save_yaml(OUTPUT_ALL, merged)
    print(f"[💾] 已保存到 {OUTPUT_ALL}")

    # 生成 us.yaml
    us_nodes = filter_us(merged, limit=10)
    save_yaml(OUTPUT_US, us_nodes)
    print(f"[💾] 已保存到 {OUTPUT_US} (US 节点 {len(us_nodes)} 个)")


if __name__ == "__main__":
    main()
