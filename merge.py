import requests
import yaml
import os
import base64
import json
from hashlib import md5
import sys

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
    """下载订阅内容，设置超时和状态码检查"""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.RequestException as e:
        print(f"[❌] 下载失败: {url} 错误: {e}", file=sys.stderr)
        return None

def parse_clash_yaml(text):
    """解析 Clash YAML 格式的订阅"""
    try:
        data = yaml.safe_load(text)
        if isinstance(data, dict) and "proxies" in data:
            return data["proxies"]
    except Exception:
        return None
    return None

def parse_base64(text):
    """解析 Base64 编码的订阅链接"""
    proxies = []
    # 尝试解码为 Base64
    try:
        # 修复 URL-safe Base64 和填充问题
        text_corrected = text.strip().replace('-', '+').replace('_', '/')
        decoded_text = base64.b64decode(text_corrected + "===").decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[⚠️] Base64 解码失败，可能不是 Base64 格式: {e}", file=sys.stderr)
        return None

    for line in decoded_text.splitlines():
        line = line.strip()
        if not line:
            continue

        # vmess://
        if line.startswith("vmess://"):
            try:
                node_str = base64.b64decode(line[8:] + "===").decode("utf-8")
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
                print(f"[⚠️] 解析 vmess 节点失败: {e}", file=sys.stderr)

        # ss://
        elif line.startswith("ss://"):
            try:
                info = line[5:]
                if "#" in info:
                    info, name = info.split("#", 1)
                    name = requests.utils.unquote(name) # 处理URL编码的名称
                else:
                    name = "ss"

                userinfo_enc, server_port = info.split("@", 1)
                userinfo = base64.b64decode(userinfo_enc + "===").decode(errors="ignore")
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
                print(f"[⚠️] 解析 ss 节点失败: {e}", file=sys.stderr)

        # trojan://
        elif line.startswith("trojan://"):
            try:
                info = line[9:]
                if "@" in info:
                    password, rest = info.split("@", 1)
                    server_port, *params = rest.split("?", 1)
                else: # 兼容不带密码的链接
                    password, server_port = "", info
                
                server, port = server_port.split(":", 1)
                
                # 尝试获取节点名称，通常在 URL 参数中
                name = "trojan"
                if params:
                    query_params = {k: v for k, v in [p.split("=") for p in params[0].split("&")]}
                    if "peer" in query_params:
                        name = query_params["peer"]

                proxies.append({
                    "name": name,
                    "type": "trojan",
                    "server": server,
                    "port": int(port),
                    "password": password,
                })
            except Exception as e:
                print(f"[⚠️] 解析 trojan 节点失败: {e}", file=sys.stderr)
        
        else:
            print(f"[⚠️] 未知协议: {line.split(':', 1)[0]}", file=sys.stderr)

    return proxies if proxies else None

def deduplicate(proxies):
    """使用 md5 对节点进行去重"""
    seen = set()
    result = []
    for p in proxies:
        # 为每个节点生成唯一指纹
        key_parts = [p.get('server'), str(p.get('port')), p.get('type')]
        if p.get('type') == 'vmess':
            key_parts.append(p.get('uuid'))
        elif p.get('type') == 'ss':
            key_parts.append(p.get('password'))
        elif p.get('type') == 'trojan':
            key_parts.append(p.get('password'))
            
        key = md5(':'.join(key_parts).encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            result.append(p)
    return result

def filter_us(proxies, limit=10):
    """根据名称过滤美国节点"""
    us_nodes = [p for p in proxies if "US" in p.get("name", "").upper() or "美国" in p.get("name", "")]
    return us_nodes[:limit]

def save_yaml(path, proxies):
    """将代理列表保存为 YAML 文件"""
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"proxies": proxies}, f, allow_unicode=True)

def main():
    """主函数"""
    all_proxies = []
    os.makedirs("providers", exist_ok=True)

    print("--- 开始下载并合并订阅 ---")
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

        print(f"[⚠️] 未能识别订阅格式: {url}", file=sys.stderr)

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
