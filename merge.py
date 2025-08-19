import requests
import yaml
import os
import base64
import json
from hashlib import md5
import sys
import time
import urllib.parse
import asyncio
import aiohttp
from aiohttp import client_exceptions

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

# 测试配置
TEST_URL = "http://cp.cloudflare.com/generate_204"
TEST_TIMEOUT = 5  # 单次测速超时时间
MAX_CONCURRENCY = 50  # 最大并发测试数

# ========== 代理处理函数 ==========

async def fetch_subscription(session, url):
    """异步下载订阅内容，设置超时和状态码检查"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36'
    }
    try:
        async with session.get(url, timeout=15, headers=headers) as resp:
            resp.raise_for_status()
            text = await resp.text()
            return url, text
    except client_exceptions.ClientError as e:
        print(f"[❌] 下载失败: {url} 错误: {e}", file=sys.stderr)
        return url, None
    except asyncio.TimeoutError:
        print(f"[❌] 下载超时: {url}", file=sys.stderr)
        return url, None

def parse_clash_yaml(text):
    """解析 Clash YAML 格式的订阅"""
    try:
        data = yaml.safe_load(text)
        if isinstance(data, dict) and "proxies" in data:
            return data["proxies"]
    except Exception as e:
        print(f"[⚠️] 解析 Clash YAML 失败: {e}", file=sys.stderr)
    return None

def parse_base64_links(text):
    """解析 Base64 编码的订阅链接，支持多种协议"""
    proxies = []
    try:
        text_corrected = text.strip().replace('-', '+').replace('_', '/')
        decoded_text = base64.b64decode(text_corrected + "===").decode("utf-8", errors="ignore")
    except Exception:
        decoded_text = text.strip()
    
    for line in decoded_text.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            # vmess://
            if line.startswith("vmess://"):
                node_str = base64.b64decode(line[8:] + "===").decode("utf-8")
                node_json = json.loads(node_str)
                proxies.append({
                    "name": node_json.get("ps", "vmess"), "type": "vmess", "server": node_json["add"],
                    "port": int(node_json["port"]), "uuid": node_json["id"], "alterId": int(node_json.get("aid", 0)),
                    "cipher": node_json.get("scy", "auto"), "tls": node_json.get("tls") == "tls",
                    "network": node_json.get("net", "tcp"),
                })
            
            # ss://
            elif line.startswith("ss://"):
                info = line[5:]
                info, *rest = info.split("#", 1)
                name = urllib.parse.unquote(rest[0]) if rest else "ss"
                userinfo_enc, server_port = info.split("@", 1)
                userinfo = base64.b64decode(userinfo_enc + "===").decode(errors="ignore")
                cipher, password = userinfo.split(":", 1)
                server, port = server_port.split(":")
                proxies.append({
                    "name": name, "type": "ss", "server": server,
                    "port": int(port), "cipher": cipher, "password": password,
                })
            
            # trojan://
            elif line.startswith("trojan://"):
                info = line[9:]
                password, rest = info.split("@", 1) if "@" in info else ("", info)
                server_port_raw, *params_raw = rest.split("?", 1)
                server, port = server_port_raw.split(":", 1)
                
                params = urllib.parse.parse_qs(params_raw[0]) if params_raw else {}
                
                proxies.append({
                    "name": params.get("peer", ["trojan"])[0], "type": "trojan", "server": server,
                    "port": int(port), "password": password,
                    "tls": params.get("security", [""])[0] == "tls",
                })
            
            # vless://
            elif line.startswith("vless://"):
                info = line[8:]
                uuid, server_info = info.split("@", 1)
                server_port, *params_raw = server_info.split("?", 1)
                server, port = server_port.split(":", 1)
                
                params = urllib.parse.parse_qs(params_raw[0]) if params_raw else {}
                
                node_config = {
                    "name": params.get("peer", ["vless"])[0],
                    "type": "vless",
                    "server": server,
                    "port": int(port),
                    "uuid": uuid,
                    "network": params.get("type", ["tcp"])[0],
                }

                if node_config["network"] == "ws":
                    ws_opts = {"path": params.get("path", [""])[0]}
                    if "host" in params:
                        ws_opts["headers"] = {"Host": params["host"][0]}
                    node_config["ws-opts"] = ws_opts
                    
                if params.get("security", [""])[0] == "tls":
                    node_config["tls"] = True
                    if "sni" in params:
                        node_config["servername"] = params["sni"][0]
                
                proxies.append(node_config)
            
            # ssr://
            elif line.startswith("ssr://"):
                base64_info = line[6:]
                info = base64.b64decode(base64_info + "===").decode('utf-8')
                
                server, port, protocol, cipher, obfs, password_base64 = info.split(':', 5)
                password, *params_str_list = password_base64.split("/?", 1)
                
                password_decoded = base64.b64decode(password + "===").decode('utf-8')
                
                params = urllib.parse.parse_qs(params_str_list[0]) if params_str_list else {}
                
                proxies.append({
                    'name': params.get('remarks', ['ssr'])[0], 'type': 'ssr', 'server': server,
                    'port': int(port), 'password': password_decoded, 'cipher': cipher, 'protocol': protocol,
                    'obfs': obfs, 'obfs-param': params.get('obfsparam', [''])[0], 'protocol-param': params.get('protoparam', [''])[0]
                })

        except Exception as e:
            print(f"[⚠️] 解析节点链接失败: {line} 错误: {e}", file=sys.stderr)

    return proxies

def deduplicate(proxies):
    """使用 md5 对节点进行去重"""
    seen = set()
    result = []
    for p in proxies:
        key_parts = [p.get('server'), str(p.get('port')), p.get('type')]
        if p.get('type') == 'vmess':
            key_parts.append(p.get('uuid'))
        elif p.get('type') in ['ss', 'trojan']:
            key_parts.append(p.get('password'))
        
        key = md5(':'.join(key_parts).encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            result.append(p)
    return result

def filter_us(proxies):
    """根据名称过滤美国节点"""
    us_nodes = [p for p in proxies if "US" in p.get("name", "").upper() or "美国" in p.get("name", "")]
    return us_nodes

def save_yaml(path, proxies):
    """将代理列表保存为 YAML 文件"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"proxies": proxies}, f, allow_unicode=True)

# ========== 异步节点连通性测试 ==========

async def test_connection_async(session, proxy_config, semaphore):
    """异步测试单个节点的连接性"""
    async with semaphore:
        proxy_type = proxy_config.get("type")
        
        # 仅支持 ss, trojan 协议测试，因为 aiohttp 代理只支持 http/https
        if proxy_type not in ["ss", "trojan"]:
            return None, None

        proxy_url = f"{proxy_type}://{proxy_config.get('password')}@{proxy_config.get('server')}:{proxy_config.get('port')}"
        
        start_time = time.time()
        try:
            async with session.get(TEST_URL, proxy=proxy_url, timeout=TEST_TIMEOUT, verify_ssl=False) as resp:
                if resp.status == 204:
                    latency = int((time.time() - start_time) * 1000)
                    return proxy_config, latency
                else:
                    return None, None
        except Exception:
            return None, None

# ========== 主运行逻辑 ==========

async def main():
    """主函数，包含异步下载和测试流程"""
    all_proxies = []
    
    print("--- 开始下载并合并订阅 ---")
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_subscription(session, url) for url in SUBSCRIPTION_URLS]
        responses = await asyncio.gather(*tasks)

        for url, text in responses:
            if text:
                proxies = parse_clash_yaml(text) or parse_base64_links(text)
                if proxies:
                    print(f"[✅] 订阅: {url} → {len(proxies)} 节点")
                    all_proxies.extend(proxies)
                else:
                    print(f"[⚠️] 未能识别订阅格式: {url}", file=sys.stderr)
            else:
                print(f"[❌] 跳过订阅: {url}", file=sys.stderr)

    merged = deduplicate(all_proxies)
    print(f"[📦] 合并并去重后节点总数: {len(merged)}")
    
    us_nodes_to_test = filter_us(merged)
    print(f"[🔎] 已筛选出 {len(us_nodes_to_test)} 个 US 节点进行并发测试...")

    available_us_nodes = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    
    async with aiohttp.ClientSession() as session:
        tasks = [test_connection_async(session, node, semaphore) for node in us_nodes_to_test]
        results = await asyncio.gather(*tasks)

    for node_result, latency in results:
        if node_result:
            node_result['latency'] = latency
            available_us_nodes.append(node_result)

    available_us_nodes.sort(key=lambda x: x['latency'])
    
    print(f"[✅] 经过测试，获得 {len(available_us_nodes)} 个可用 US 节点")

    save_yaml(OUTPUT_ALL, merged)
    print(f"[💾] 已保存所有去重节点到 {OUTPUT_ALL}")

    save_yaml(OUTPUT_US, available_us_nodes[:10])
    print(f"[💾] 已保存 {len(available_us_nodes[:10])} 个可用美国节点到 {OUTPUT_US}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n脚本已手动停止。")
    except Exception as e:
        print(f"脚本运行出错: {e}", file=sys.stderr)
