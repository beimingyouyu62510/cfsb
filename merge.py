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
import concurrent.futures # Needed for direct_socket_test if not using async socket
from aiohttp import client_exceptions

# ========== 配置：多个订阅源 ==========
SUBSCRIPTION_URLS = [
    "https://raw.githubusercontent.com/Epodonios/bulk-xray-v2ray-vless-vmess-...-configs/main/sub/United%20States/config.txt"
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

# ========== 异步节点连通性测试 (包含 Socket 和 Proxy 测试) ==========

def direct_socket_test(server, port, timeout=TEST_TIMEOUT):
    """直接使用socket测试TCP连接，返回延迟(ms)或None"""
    try:
        # 使用 IPv4 和 TCP 协议
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout) # 设置超时
        start_time = time.time()
        # 尝试连接，connect_ex 返回0表示成功，否则是错误码
        result = sock.connect_ex((server, port))
        end_time = time.time()
        sock.close()

        if result == 0:
            return (end_time - start_time) * 1000  # 转换为毫秒
        else:
            return None
    except Exception:
        # 捕获所有异常，返回None表示失败
        return None

async def test_connection_async(session, proxy_config, semaphore):
    """异步测试单个节点的连接性，先进行Socket测试，再进行协议测试"""
    async with semaphore:
        node_name = proxy_config.get('name', '未知节点')
        proxy_type = proxy_config.get("type")
        server = proxy_config.get('server')
        port = int(proxy_config.get('port', 0))

        if not server or not port:
            print(f"[❌] {node_name} | 缺少服务器或端口信息", file=sys.stderr)
            return None, None # 返回None表示测试失败

        # 第一步：进行 Socket 连接测试 (基础可达性)
        # 注意: direct_socket_test 是同步函数，需要通过 loop.run_in_executor 异步调用
        loop = asyncio.get_running_loop()
        socket_latency = await loop.run_in_executor(
            concurrent.futures.ThreadPoolExecutor(), # 使用线程池执行同步IO
            direct_socket_test, server, port
        )

        if socket_latency is None:
            print(f"[❌] {node_name} | Socket连接失败", file=sys.stderr)
            return None, None # Socket连接失败，直接判定节点不可用

        # 第二步：如果 Socket 连接成功，根据协议类型进行下一步测试
        final_latency = socket_latency # 默认使用socket延迟

        if proxy_type in ["ss", "trojan"]:
            # 对于 SS 和 Trojan，尝试进行完整的代理功能测试
            proxy_url = f"{proxy_type}://{proxy_config.get('password')}@{server}:{port}"
            try:
                start_time_proxy = time.time()
                async with session.get(TEST_URL, proxy=proxy_url, timeout=TEST_TIMEOUT, verify_ssl=False) as resp:
                    if resp.status == 204:
                        proxy_latency = int((time.time() - start_time_proxy) * 1000)
                        final_latency = proxy_latency # 使用更精确的代理延迟
                        print(f"[✅] {node_name} | 代理 {proxy_type} 通过, 延迟: {final_latency}ms")
                    else:
                        print(f"[⚠️] {node_name} | 代理 {proxy_type} 状态码 {resp.status}, 仍按Socket延迟 ({socket_latency}ms) 计入", file=sys.stderr)
                
            except Exception as e:
                print(f"[⚠️] {node_name} | 代理 {proxy_type} 功能测试失败: {e}, 仍按Socket延迟 ({socket_latency}ms) 计入", file=sys.stderr)
        elif proxy_type in ["vmess", "vless", "ssr"]:
            # 对于这些协议，只使用 Socket 测试结果，并注明无法进行完整代理功能测试
            print(f"[🔵] {node_name} | 协议 {proxy_type} (仅Socket测试通过), 延迟: {socket_latency}ms")
        else:
            # 未知协议或不支持测试的协议
            print(f"[❓] {node_name} | 未知或不支持测试的协议 {proxy_type}, 仅Socket测试通过, 延迟: {socket_latency}ms", file=sys.stderr)
        
        # 返回节点配置和最终确定的延迟
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
        else:
            # 打印被过滤掉的节点（例如Socket测试失败的节点）
            # 注意: results 中对应的原始节点可能需要更复杂的查找，此处简化为只打印失败类型
            pass 

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
