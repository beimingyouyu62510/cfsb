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
import socket
import concurrent.futures
from aiohttp import client_exceptions

# ========== 配置：多个订阅源 ==========
SUBSCRIPTION_URLS = [
    "https://gosub.sosorg.nyc.mn/sub?uuid=01991f31-4f11-1c67-b1f4-ff7fab35e816&encryption=none&security=tls&sni=www.flashspeed.cloud-ip.cc&type=ws&host=www.flashspeed.cloud-ip.cc&path=%2Fsnippets%3Fip%3Dproxyip%3Aport%28443%29%26nat64%3D6to4",
    "https://gosub.sosorg.nyc.mn/sub?uuid=01991f31-4f11-1c67-b1f4-ff7fab35e816&encryption=none&security=tls&sni=speed.gospeedygo.cyou&type=ws&host=speed.gospeedygo.cyou&path=%2Fsnippets%3Fip%3Dproxyip%3Aport%28443%29%26nat64%3D6to4",
    "https://gosub.sosorg.nyc.mn/sub?uuid=01991f31-4f11-1c67-b1f4-ff7fab35e816&encryption=none&security=tls&sni=www.1154874.xyz&type=ws&host=www.1154874.xyz&path=%2Fsnippets%3Fip%3Dproxyip%3Aport%28443%29%26nat64%3D6to4",
    "https://gosub.sosorg.nyc.mn/sub?uuid=01991f31-4f11-1c67-b1f4-ff7fab35e816&encryption=none&security=tls&sni=cloud.5587124.xyz&type=ws&host=cloud.5587124.xyz&path=%2Fsnippets%3Fip%3Dproxyip%3Aport%28443%29%26nat64%3D6to4",
    "https://gosub.sosorg.nyc.mn/sub?uuid=01991f31-4f11-1c67-b1f4-ff7fab35e816&encryption=none&security=tls&sni=blog.1547415.xyz&type=ws&host=blog.1547415.xyz&path=%2Fsnippets%3Fip%3Dproxyip%3Aport%28443%29%26nat64%3D6to4",
    "https://gosub.sosorg.nyc.mn/sub?uuid=01991f31-4f11-1c67-b1f4-ff7fab35e816&encryption=none&security=tls&sni=www.zmxquick.cloudns.org&type=ws&host=www.zmxquick.cloudns.org&path=%2Fsnippets%3Fip%3Dproxyip%3Aport%28443%29%26nat64%3D6to4",
    "https://gosub.sosorg.nyc.mn/sub?uuid=01991f31-4f11-1c67-b1f4-ff7fab35e816&encryption=none&security=tls&sni=www.vl.de5.net&type=ws&host=www.vl.de5.net&path=%2Fsnippets%3Fip%3Dproxyip%3Aport%28443%29%26nat64%3D6to4",
    "https://gosub.sosorg.nyc.mn/sub?uuid=01991f31-4f11-1c67-b1f4-ff7fab35e816&encryption=none&security=tls&sni=www2.zmxquick.cloudns.org&type=ws&host=www2.zmxquick.cloudns.org&path=%2Fsnippets%3Fip%3Dproxyip%3Aport%28443%29%26nat64%3D6to4",
    "https://gosub.sosorg.nyc.mn/sub?uuid=01991f31-4f11-1c67-b1f4-ff7fab35e816&encryption=none&security=tls&sni=lovemoneycat.ggff.net&type=ws&host=lovemoneycat.ggff.net&path=%2Fsnippets%3Fip%3Dproxyip%3Aport%28443%29%26nat64%3D6to4",
    "https://gosub.sosorg.nyc.mn/sub?uuid=01991f31-4f11-1c67-b1f4-ff7fab35e816&encryption=none&security=tls&sni=cfvs.eu.org&type=ws&host=cfvs.eu.org&path=%2Fsnippets%3Fip%3Dproxyip%3Aport%28443%29%26nat64%3D6to4"
]
OUTPUT_ALL = "providers/all.yaml"
OUTPUT_US = "providers/us.yaml"

# 测试配置
TEST_URL = "http://cp.cloudflare.com/generate_204"
TEST_TIMEOUT = 20  # 增加超时时间以提高成功率
MAX_CONCURRENCY = 50  # 并发数
PING_TIMEOUT = 3  # ping 超时时间（未使用）

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
    """解析 Base64 编码的订阅链接，专注于 vless 协议，使用原始名称"""
    proxies = []
    uuid_count = {}  # 跟踪 UUID 重复
    seen_names = set()  # 跟踪已使用名称
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
            if line.startswith("vless://"):
                url_part, *remark_part = line[8:].split("#", 1)
                base_name = urllib.parse.unquote(remark_part[0]) if remark_part else "vless"
                uuid, server_info = url_part.split("@", 1)
                server_port, *params_raw = server_info.split("?", 1)
                server, port = server_port.split(":", 1)
                params = urllib.parse.parse_qs(params_raw[0]) if params_raw else {}
                
                # 使用原始名称，附加 server/port 确保唯一性
                name = base_name
                if name in seen_names:
                    name = f"{base_name}_{server}_{port}"
                seen_names.add(name)
                
                # 检查 UUID 重复
                uuid_count[uuid] = uuid_count.get(uuid, 0) + 1
                if uuid_count[uuid] > 5:
                    print(f"[⚠️] UUID {uuid} 重复使用超过 5 次，可能影响节点可用性", file=sys.stderr)
                
                node_config = {
                    "name": name,
                    "type": "vless",
                    "server": server,
                    "port": int(port),
                    "uuid": uuid,
                    "network": params.get("type", ["tcp"])[0],
                }
                if node_config["network"] == "ws":
                    path = params.get("path", [""])[0]
                    if "proxyip:port(443)" in path:
                        path = path.replace("proxyip:port(443)", f"{server}:{port}")
                    ws_opts = {"path": path}
                    if "host" in params:
                        ws_opts["headers"] = {"Host": params["host"][0]}
                    node_config["ws-opts"] = ws_opts
                if params.get("security", [""])[0] == "tls":
                    node_config["tls"] = True
                    if "sni" in params:
                        node_config["servername"] = params["sni"][0]
                
                proxies.append(node_config)
        except Exception as e:
            print(f"[⚠️] 解析节点链接失败: {line} 错误: {e}", file=sys.stderr)
    return proxies

def deduplicate(proxies):
    """使用 md5 对节点进行去重，针对 vless 优化键"""
    seen = set()
    result = []
    for p in proxies:
        key_parts = [p.get('server'), str(p.get('port')), p.get('type'), p.get('uuid')]
        if 'ws-opts' in p:
            key_parts.append(p['ws-opts'].get('path', ''))
        key = md5(':'.join(key_parts).encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            result.append(p)
    return result

def filter_us(proxies):
    """放宽筛选条件，捕获 US 节点，排除非 US 节点"""
    us_nodes = []
    exclude_keywords = ["HK", "HONG KONG", "香港", "SG", "SINGAPORE", "新加坡", "JP", "JAPAN", "日本"]
    for p in proxies:
        name = p.get("name", "").upper()
        if any(keyword in name for keyword in ["US", "USA", "美国", "UNITED STATES", "AMERICA"]):
            if not any(exclude in name for exclude in exclude_keywords):
                us_nodes.append(p)
            else:
                print(f"[⚠️] 排除非 US 节点: {p['name']}", file=sys.stderr)
    print(f"[🔍] 筛选出 {len(us_nodes)} 个 US 节点: {[p['name'] for p in us_nodes]}")
    return us_nodes

def save_yaml(path, proxies):
    """将代理列表保存为 YAML 文件"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"proxies": proxies}, f, allow_unicode=True)

def direct_socket_test(server, port, timeout=TEST_TIMEOUT):
    """直接使用 socket 测试 TCP 连接，返回延迟(ms)或 None"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        start_time = time.time()
        result = sock.connect_ex((server, port))
        end_time = time.time()
        sock.close()
        if result == 0:
            return (end_time - start_time) * 1000
        else:
            return None
    except Exception as e:
        print(f"[⚠️] Socket 测试失败: {server}:{port}, 错误: {e}", file=sys.stderr)
        return None

async def test_connection_async(session, proxy_config, semaphore):
    """异步测试单个节点的连接性，针对 vless 优化：仅 socket 测试"""
    async with semaphore:
        node_name = proxy_config.get('name', '未知节点')
        server = proxy_config.get('server')
        port = int(proxy_config.get('port', 0))
        if not server or not port:
            print(f"[❌] {node_name} | 缺少服务器或端口信息", file=sys.stderr)
            return None

        loop = asyncio.get_running_loop()
        socket_latency = await loop.run_in_executor(
            concurrent.futures.ThreadPoolExecutor(),
            direct_socket_test, server, port
        )
        if socket_latency is None:
            print(f"[❌] {node_name} | Socket 连接失败", file=sys.stderr)
            return None

        print(f"[✅] {node_name} | vless (Socket: {socket_latency:.0f}ms)")
        return proxy_config

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
    print(f"[🔍] 所有节点: {[p['name'] for p in merged]}")
    save_yaml(OUTPUT_ALL, merged)
    print(f"[💾] 已保存所有去重节点到 {OUTPUT_ALL}")

    us_nodes_to_test = filter_us(merged)
    if not us_nodes_to_test:
        print("[⚠️] 未找到任何名称包含 'US'、'USA'、'美国'、'UNITED STATES' 或 'AMERICA' 的节点，us.yaml 文件将为空。")
        return

    available_us_nodes = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async with aiohttp.ClientSession() as session:
        tasks = [test_connection_async(session, node, semaphore) for node in us_nodes_to_test]
        results = await asyncio.gather(*tasks)

    for node_result in results:
        if node_result:
            available_us_nodes.append(node_result)

    available_us_nodes.sort(key=lambda x: x['name'])
    print(f"[✅] 经过测试，获得 {len(available_us_nodes)} 个可用 US 节点")
    print(f"[🔍] 可用 US 节点: {[node['name'] for node in available_us_nodes]}")
    
    if not available_us_nodes:
        print("[⚠️] 所有 US 节点测试失败，us.yaml 将为空")
    else:
        save_yaml(OUTPUT_US, available_us_nodes)
        print(f"[💾] 已保存 {len(available_us_nodes)} 个可用美国节点到 {OUTPUT_US}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n脚本已手动停止。")
    except Exception as e:
        print(f"脚本运行出错: {e}", file=sys.stderr)
