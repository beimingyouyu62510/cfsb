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

def download(url):
    """下载订阅内容，设置超时和状态码检查"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36'
    }
    try:
        resp = requests.get(url, timeout=15, headers=headers)
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
    except Exception as e:
        print(f"[⚠️] 解析 Clash YAML 失败: {e}", file=sys.stderr)
    return None

def parse_base64(text):
    """解析 Base64 编码的订阅链接，增加了更健壮的容错处理"""
    proxies = []
    try:
        text_corrected = text.strip().replace('-', '+').replace('_', '/')
        # 尝试解码为 Base64，如果失败则按行处理原始文本
        try:
            decoded_text = base64.b64decode(text_corrected + "===").decode("utf-8", errors="ignore")
        except Exception:
            decoded_text = text_corrected
        
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
                        "name": node_json.get("ps", "vmess"), "type": "vmess", "server": node_json["add"],
                        "port": int(node_json["port"]), "uuid": node_json["id"], "alterId": int(node_json.get("aid", 0)),
                        "cipher": node_json.get("scy", "auto"), "tls": True if node_json.get("tls") == "tls" else False,
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
                        name = requests.utils.unquote(name)
                    else:
                        name = "ss"
                    userinfo_enc, server_port = info.split("@", 1)
                    userinfo = base64.b64decode(userinfo_enc + "===").decode(errors="ignore")
                    cipher, password = userinfo.split(":", 1)
                    server, port = server_port.split(":")
                    proxies.append({
                        "name": name, "type": "ss", "server": server,
                        "port": int(port), "cipher": cipher, "password": password,
                    })
                except Exception as e:
                    print(f"[⚠️] 解析 ss 节点失败: {e}", file=sys.stderr)

            # trojan://
            elif line.startswith("trojan://"):
                try:
                    info = line[9:]
                    if "@" in info:
                        password, rest = info.split("@", 1)
                        server_port_raw, *params_raw = rest.split("?", 1)
                    else:
                        password, server_port_raw = "", info.split("?", 1)[0]
                        params_raw = info.split("?", 1)[1:]

                    server, port = server_port_raw.split(":", 1)
                    
                    params = {}
                    if params_raw:
                        for p in params_raw[0].split("&"):
                            if "=" in p:
                                k, v = p.split("=", 1)
                                params[k] = urllib.parse.unquote(v)
                    
                    node_config = {
                        "name": params.get("peer", "trojan"),
                        "type": "trojan",
                        "server": server,
                        "port": int(port),
                        "password": password,
                        "tls": True if params.get("security") == "tls" else False,
                    }
                    proxies.append(node_config)
                except Exception as e:
                    print(f"[⚠️] 解析 trojan 节点失败: {e}", file=sys.stderr)
            
            # vless://
            elif line.startswith("vless://"):
                try:
                    info = line[8:]
                    uuid_and_server = info.split("@", 1)
                    uuid = uuid_and_server[0]
                    server_info = uuid_and_server[1].split("?", 1)
                    server_port = server_info[0].split(":", 1)
                    server = server_port[0]
                    port = int(server_port[1])
                    
                    params = {}
                    if len(server_info) > 1:
                        params_str = server_info[1]
                        for p in params_str.split("&"):
                            if "=" in p:
                                k, v = p.split("=", 1)
                                params[k] = urllib.parse.unquote(v)

                    node_config = {
                        "name": params.get("peer", "vless"),
                        "type": "vless",
                        "server": server,
                        "port": port,
                        "uuid": uuid,
                        "network": params.get("type", "tcp"),
                    }

                    if node_config["network"] == "ws":
                        ws_opts = {}
                        if "path" in params:
                            path_cleaned = params["path"].split("?")[0].strip().split(" ")[0].strip()
                            ws_opts["path"] = path_cleaned
                        if "host" in params:
                            ws_opts["headers"] = {"Host": params["host"]}
                        node_config["ws-opts"] = ws_opts
                        
                    if params.get("security") == "tls":
                        node_config["tls"] = True
                        if "sni" in params:
                            node_config["servername"] = params["sni"]
                            
                    if "udp" in params:
                        node_config["udp"] = (params["udp"].lower() == "true")
                    if "xudp" in params:
                        node_config["xudp"] = (params["xudp"].lower() == "true")
                        
                    proxies.append(node_config)
                except Exception as e:
                    print(f"[⚠️] 解析 vless 节点失败: {e}", file=sys.stderr)

            # ssr://
            elif line.startswith("ssr://"):
                try:
                    base64_info = line[6:]
                    info = base64.b64decode(base64_info + "===").decode('utf-8')
                    
                    server, port, protocol, cipher, obfs, password_base64 = info.split(':')
                    password = base64.b64decode(password_base64.split("/")[0] + "===").decode('utf-8')
                    
                    params_str = info.split('?')[-1]
                    params = {k: urllib.parse.unquote(v) for k, v in (p.split('=') for p in params_str.split('&'))}
                    
                    proxies.append({
                        'name': params.get('remarks', 'ssr'), 'type': 'ssr', 'server': server,
                        'port': int(port), 'password': password, 'cipher': cipher, 'protocol': protocol,
                        'obfs': obfs, 'obfs-param': params.get('obfsparam', ''), 'protocol-param': params.get('protoparam', '')
                    })
                except Exception as e:
                    print(f"[⚠️] 解析 ssr 节点失败: {e}", file=sys.stderr)

    return proxies if proxies else None

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
        
        # 仅支持 ss, trojan 协议测试
        if proxy_type not in ["ss", "trojan"]:
            # print(f"[⚠️] 暂不支持测试节点类型: {proxy_type}", file=sys.stderr)
            return None, None

        proxy_url = f"{proxy_type}://{proxy_config.get('password')}@{proxy_config.get('server')}:{proxy_config.get('port')}"
        
        start_time = time.time()
        try:
            # aiohttp 请求
            async with session.get(TEST_URL, proxy=proxy_url, timeout=TEST_TIMEOUT, verify_ssl=False) as resp:
                if resp.status == 204:
                    latency = int((time.time() - start_time) * 1000)
                    print(f"[✅] {proxy_config['name']} | 延迟: {latency}ms")
                    return proxy_config, latency
                else:
                    print(f"[❌] {proxy_config['name']} | 状态码: {resp.status}", file=sys.stderr)
                    return None, None
        except Exception as e:
            # print(f"[❌] {proxy_config['name']} | 失败: {e}", file=sys.stderr)
            return None, None

async def main_async():
    """主函数"""
    all_proxies = []
    
    print("--- 开始下载并合并订阅 ---")
    for url in SUBSCRIPTION_URLS:
        text = download(url)
        if not text:
            continue
        proxies = parse_clash_yaml(text) or parse_base64(text)
        if proxies:
            print(f"[✅] 订阅: {url} → {len(proxies)} 节点")
            all_proxies.extend(proxies)
        else:
            print(f"[⚠️] 未能识别订阅格式: {url}", file=sys.stderr)

    merged = deduplicate(all_proxies)
    print(f"[📦] 合并并去重后节点总数: {len(merged)}")
    
    # 筛选出潜在的美国节点
    us_nodes_to_test = filter_us(merged)
    print(f"[🔎] 已筛选出 {len(us_nodes_to_test)} 个 US 节点进行并发测试...")

    available_us_nodes = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    
    # 异步并发测试
    async with aiohttp.ClientSession() as session:
        tasks = [test_connection_async(session, node, semaphore) for node in us_nodes_to_test]
        results = await asyncio.gather(*tasks)

    for node_result, latency in results:
        if node_result:
            node_result['latency'] = latency
            available_us_nodes.append(node_result)

    available_us_nodes.sort(key=lambda x: x['latency'])
    
    print(f"[✅] 经过测试，获得 {len(available_us_nodes)} 个可用 US 节点")

    # 保存 all.yaml (所有去重后的节点)
    save_yaml(OUTPUT_ALL, merged)
    print(f"[💾] 已保存所有去重节点到 {OUTPUT_ALL}")

    # 保存 us.yaml (所有可用的美国节点)
    save_yaml(OUTPUT_US, available_us_nodes[:10])  # 只保存前10个
    print(f"[💾] 已保存 {len(available_us_nodes[:10])} 个可用美国节点到 {OUTPUT_US}")

if __name__ == "__main__":
    # 在 GitHub Actions 中，需要确保 aiohttp 库已安装
    # 在你的工作流中添加：
    # - name: Install dependencies
    #   run: pip install requests pyyaml aiohttp
    
    asyncio.run(main_async())
