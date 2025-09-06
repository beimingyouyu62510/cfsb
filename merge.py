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
TEST_TIMEOUT = 5  # 单次测速超时时间
MAX_CONCURRENCY = 100  # 增加最大并发测试数以提高效率（根据环境调整）
PING_TIMEOUT = 2  # 新增：ping 测试超时

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
    """解析 Clash YAML 格式的订阅（优化：假设为 vless，支持回退）"""
    try:
        data = yaml.safe_load(text)
        if isinstance(data, dict) and "proxies" in data:
            return data["proxies"]
    except Exception as e:
        print(f"[⚠️] 解析 Clash YAML 失败: {e}", file=sys.stderr)
    return None

def parse_base64_links(text):
    """解析 Base64 编码的订阅链接，专注于 vless 协议"""
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
            # 专注于 vless://
            if line.startswith("vless://"):
                # 首先，按 # 分割，获取备注
                url_part, *remark_part = line[8:].split("#", 1)
                
                # 如果有备注，进行 URL 解码
                name = urllib.parse.unquote(remark_part[0]) if remark_part else "vless"
                
                # 剩下的部分继续解析
                uuid, server_info = url_part.split("@", 1)
                server_port, *params_raw = server_info.split("?", 1)
                server, port = server_port.split(":", 1)
                
                params = urllib.parse.parse_qs(params_raw[0]) if params_raw else {}
                
                node_config = {
                    "name": name,  # 使用解析出来的备注作为名称
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
    """根据名称过滤美国节点"""
    us_nodes = [p for p in proxies if "US" in p.get("name", "").upper() or "美国" in p.get("name", "")]
    return us_nodes

def save_yaml(path, proxies):
    """将代理列表保存为 YAML 文件"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"proxies": proxies}, f, allow_unicode=True)

# ========== 异步节点连通性测试 (针对 vless 优化：增加 ping 测试) ==========
def direct_socket_test(server, port, timeout=TEST_TIMEOUT):
    """直接使用socket测试TCP连接，返回延迟(ms)或None"""
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
    except Exception:
        return None

def ping_test(server, timeout=PING_TIMEOUT):
    """使用 socket 模拟 ping 测试，返回延迟(ms)或None（优化：快速检查连通性）"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
        sock.settimeout(timeout)
        start_time = time.time()
        sock.sendto(b'\x08\x00\x7d\x4b\x00\x00\x00\x00Ping', (server, 1))
        sock.recvfrom(1024)
        end_time = time.time()
        sock.close()
        return (end_time - start_time) * 1000
    except Exception:
        return None

async def test_connection_async(session, proxy_config, semaphore):
    """异步测试单个节点的连接性，针对 vless 优化：socket + ping"""
    async with semaphore:
        node_name = proxy_config.get('name', '未知节点')
        server = proxy_config.get('server')
        port = int(proxy_config.get('port', 0))
        if not server or not port:
            print(f"[❌] {node_name} | 缺少服务器或端口信息", file=sys.stderr)
            return None, None

        # 第一步：ping 测试 (快速检查服务器可达性)
        loop = asyncio.get_running_loop()
        ping_latency = await loop.run_in_executor(
            concurrent.futures.ThreadPoolExecutor(),
            ping_test, server
        )
        if ping_latency is None:
            print(f"[❌] {node_name} | Ping 测试失败", file=sys.stderr)
            return None, None

        # 第二步：socket 连接测试
        socket_latency = await loop.run_in_executor(
            concurrent.futures.ThreadPoolExecutor(),
            direct_socket_test, server, port
        )
        if socket_latency is None:
            print(f"[❌] {node_name} | Socket 连接失败", file=sys.stderr)
            return None, None

        # 对于 vless，无法直接用 aiohttp 测试代理，使用平均延迟
        final_latency = (ping_latency + socket_latency) / 2
        print(f"[✅] {node_name} | vless (Ping: {ping_latency:.0f}ms, Socket: {socket_latency:.0f}ms), 平均延迟: {final_latency:.0f}ms")

        return proxy_config, final_latency

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

    # 筛选出所有 US 节点进行测试
    us_nodes_to_test = filter_us(merged)
    print(f"[🔎] 已筛选出 {len(us_nodes_to_test)} 个 US 节点进行并发测试...")
    if not us_nodes_to_test:
        print("[⚠️] 未找到任何名称包含 'US' 或 '美国' 的节点，us.yaml 文件将为空。")

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
    save_yaml(OUTPUT_US, available_us_nodes[:50])
    print(f"[💾] 已保存 {len(available_us_nodes[:50])} 个可用美国节点到 {OUTPUT_US}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n脚本已手动停止。")
    except Exception as e:
        print(f"脚本运行出错: {e}", file=sys.stderr)
