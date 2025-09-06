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
import statistics
from datetime import datetime, timedelta
import random

# ========== 配置：固定更新文件 URL 和文件路径 ==========
UPDATE_FILE_URL = "https://apicsv.sosorg.nyc.mn/gengxin.txt?token=CMorg"
FALLBACK_FILE = "fallback_urls.txt"
OUTPUT_ALL = "providers/all.yaml"
OUTPUT_US = "providers/us.yaml"
QUALITY_REPORT = "quality_report.json"

# 测试配置 - 优化的测试参数
TEST_URLS = [
    "http://cp.cloudflare.com/generate_204",
    "http://www.google.com/generate_204", 
    "http://detectportal.firefox.com/success.txt",
    "http://connectivity-check.ubuntu.com/"
]
TEST_TIMEOUT = 15  # 降低超时时间，快速淘汰慢节点
MAX_CONCURRENCY = 30  # 降低并发数，提高稳定性
RETRY_COUNT = 2  # 重试次数
LATENCY_THRESHOLD = 1500  # 延迟阈值(ms)
SUCCESS_RATE_THRESHOLD = 0.6  # 成功率阈值

# 质量评分权重
WEIGHTS = {
    'latency': 0.4,      # 延迟权重
    'success_rate': 0.3,  # 成功率权重
    'stability': 0.2,     # 稳定性权重
    'speed': 0.1         # 速度权重
}

# ========== 管理 fallback URLs ==========
def load_fallback_urls():
    """加载本地保存的 fallback URL 列表"""
    if os.path.exists(FALLBACK_FILE):
        with open(FALLBACK_FILE, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip() and line.strip().startswith('http')]
    return []

def save_fallback_urls(urls):
    """保存 fallback URL 列表到本地文件"""
    os.makedirs(os.path.dirname(FALLBACK_FILE) or ".", exist_ok=True)
    with open(FALLBACK_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(urls))
    print(f"[✅] 已保存 {len(urls)} 个 URL 到 {FALLBACK_FILE}")

# ========== 增强的质量检测功能 ==========
def load_quality_history():
    """加载历史质量数据"""
    if os.path.exists(QUALITY_REPORT):
        try:
            with open(QUALITY_REPORT, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_quality_history(quality_data):
    """保存质量数据"""
    with open(QUALITY_REPORT, "w", encoding="utf-8") as f:
        json.dump(quality_data, f, indent=2, ensure_ascii=False)

def calculate_quality_score(latencies, success_count, total_tests, historical_data=None):
    """计算节点质量分数"""
    if not latencies:
        return 0
    
    # 延迟分数 (越低越好)
    avg_latency = statistics.mean(latencies)
    latency_score = max(0, 100 - (avg_latency / 20))  # 2000ms = 0分
    
    # 成功率分数
    success_rate = success_count / total_tests if total_tests > 0 else 0
    success_score = success_rate * 100
    
    # 稳定性分数 (延迟方差越小越好)
    stability_score = 100
    if len(latencies) > 1:
        latency_std = statistics.stdev(latencies)
        stability_score = max(0, 100 - (latency_std / 10))
    
    # 速度分数 (基于最小延迟)
    speed_score = max(0, 100 - (min(latencies) / 15)) if latencies else 0
    
    # 历史表现加权
    historical_bonus = 0
    if historical_data:
        recent_scores = historical_data.get('recent_scores', [])
        if recent_scores:
            historical_bonus = min(10, statistics.mean(recent_scores) / 10)
    
    # 综合评分
    final_score = (
        latency_score * WEIGHTS['latency'] +
        success_score * WEIGHTS['success_rate'] +
        stability_score * WEIGHTS['stability'] +
        speed_score * WEIGHTS['speed'] +
        historical_bonus
    )
    
    return round(final_score, 2)

# ========== 新增：从固定 URL 获取订阅源 ==========
async def fetch_subscription_urls(session):
    """从固定 URL 下载订阅源列表，更新并返回 fallback URLs"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        async with session.get(UPDATE_FILE_URL, timeout=15, headers=headers) as resp:
            resp.raise_for_status()
            content = await resp.text()
            print(f"[DEBUG] 原始内容: {content[:100]}...")
            if not content.strip():
                print(f"[⚠️] {UPDATE_FILE_URL} 文件为空，使用本地 fallback URLs", file=sys.stderr)
                return load_fallback_urls()
            urls = [line.strip() for line in content.splitlines() if line.strip() and line.strip().startswith('http')]
            if urls:
                print(f"[✅] 从 {UPDATE_FILE_URL} 获取 {len(urls)} 个订阅源")
                save_fallback_urls(urls)
                return urls
            else:
                print(f"[⚠️] {UPDATE_FILE_URL} 无有效 URL，使用本地 fallback URLs", file=sys.stderr)
                return load_fallback_urls()
    except Exception as e:
        print(f"[❌] 下载 {UPDATE_FILE_URL} 失败: {e}，使用本地 fallback URLs", file=sys.stderr)
        return load_fallback_urls()

# ========== 代理处理函数 ==========
async def fetch_subscription(session, url):
    """异步下载订阅内容，增加重试机制"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    for attempt in range(RETRY_COUNT):
        try:
            timeout = aiohttp.ClientTimeout(total=15 + attempt * 5)
            async with session.get(url, timeout=timeout, headers=headers) as resp:
                resp.raise_for_status()
                text = await resp.text()
                print(f"[DEBUG] 订阅 {url} 内容首100字符: {text[:100]}...")
                return url, text
        except Exception as e:
            if attempt == RETRY_COUNT - 1:
                print(f"[❌] 下载失败 (重试{RETRY_COUNT}次): {url} 错误: {e}", file=sys.stderr)
                return url, None
            else:
                await asyncio.sleep(2 ** attempt)  # 指数退避
    
    return url, None

def validate_proxy_config(proxy):
    """验证代理配置的完整性"""
    required_fields = ['name', 'type', 'server', 'port']
    for field in required_fields:
        if field not in proxy or not proxy[field]:
            return False
    
    # 验证端口范围
    try:
        port = int(proxy['port'])
        if port <= 0 or port > 65535:
            return False
    except:
        return False
    
    # 验证服务器地址
    server = proxy.get('server', '')
    if not server or server in ['localhost', '127.0.0.1', '0.0.0.0']:
        return False
    
    return True

def parse_clash_yaml(text):
    """解析 Clash YAML 格式的订阅，增加验证"""
    try:
        data = yaml.safe_load(text)
        if isinstance(data, dict) and "proxies" in data:
            valid_proxies = []
            for proxy in data["proxies"]:
                if validate_proxy_config(proxy):
                    valid_proxies.append(proxy)
                else:
                    print(f"[⚠️] 跳过无效配置: {proxy.get('name', 'unknown')}", file=sys.stderr)
            print(f"[DEBUG] 解析到 {len(valid_proxies)} 个有效 Clash 节点")
            return valid_proxies
    except Exception as e:
        print(f"[⚠️] 解析 Clash YAML 失败: {e}，内容: {text[:200]}...", file=sys.stderr)
    return []

def parse_base64_links(text):
    """优化的 Base64 解析，增强容错性和节点验证"""
    proxies = []
    uuid_count = {}
    seen_configs = set()
    
    try:
        # 多种 Base64 解码尝试
        for encoding_attempt in [
            lambda x: base64.b64decode(x + "==="),
            lambda x: base64.b64decode(x.replace('-', '+').replace('_', '/') + "==="),
            lambda x: base64.urlsafe_b64decode(x + "===")
        ]:
            try:
                decoded_text = encoding_attempt(text.strip()).decode("utf-8", errors="ignore")
                break
            except:
                continue
        else:
            decoded_text = text.strip()
    except Exception as e:
        print(f"[⚠️] Base64 解码失败: {e}，使用原始文本", file=sys.stderr)
        decoded_text = text.strip()

    for line in decoded_text.splitlines():
        line = line.strip()
        if not line:
            continue
            
        try:
            if line.startswith("vless://"):
                proxy_config = parse_vless_url(line)
                if proxy_config and validate_proxy_config(proxy_config):
                    # 避免重复配置
                    config_key = f"{proxy_config['server']}:{proxy_config['port']}:{proxy_config['uuid']}"
                    if config_key not in seen_configs:
                        seen_configs.add(config_key)
                        proxies.append(proxy_config)
                        
                        # UUID 使用统计
                        uuid = proxy_config['uuid']
                        uuid_count[uuid] = uuid_count.get(uuid, 0) + 1
                        
            elif line.startswith(("vmess://", "ss://", "trojan://")):
                # 可以扩展支持其他协议
                pass
                
        except Exception as e:
            print(f"[⚠️] 解析节点链接失败: {line[:50]}... 错误: {e}", file=sys.stderr)
    
    # 检查 UUID 重复使用情况
    for uuid, count in uuid_count.items():
        if count > 10:
            print(f"[⚠️] UUID {uuid} 重复使用 {count} 次，可能影响节点质量", file=sys.stderr)
    
    print(f"[DEBUG] 解析到 {len(proxies)} 个有效 vless 节点")
    return proxies

def parse_vless_url(url):
    """解析单个 vless URL"""
    try:
        url_part, *remark_part = url[8:].split("#", 1)
        base_name = urllib.parse.unquote(remark_part[0]) if remark_part else "vless"
        uuid, server_info = url_part.split("@", 1)
        server_port, *params_raw = server_info.split("?", 1)
        server, port = server_port.split(":", 1)
        params = urllib.parse.parse_qs(params_raw[0]) if params_raw else {}
        
        node_config = {
            "name": base_name,
            "type": "vless",
            "server": server,
            "port": int(port),
            "uuid": uuid,
            "network": params.get("type", ["tcp"])[0],
        }
        
        # WebSocket 配置
        if node_config["network"] == "ws":
            path = params.get("path", [""])[0]
            if "proxyip:port(443)" in path:
                path = path.replace("proxyip:port(443)", f"{server}:{port}")
            ws_opts = {"path": path}
            if "host" in params:
                ws_opts["headers"] = {"Host": params["host"][0]}
            node_config["ws-opts"] = ws_opts
            
        # TLS 配置
        if params.get("security", [""])[0] == "tls":
            node_config["tls"] = True
            if "sni" in params:
                node_config["servername"] = params["sni"][0]
        
        return node_config
    except Exception as e:
        print(f"[⚠️] 解析 vless URL 失败: {e}", file=sys.stderr)
        return None

def deduplicate(proxies):
    """增强的去重逻辑，考虑更多因素"""
    seen = set()
    result = []
    for p in proxies:
        # 生成更精确的去重键
        key_parts = [
            p.get('server', ''),
            str(p.get('port', 0)),
            p.get('type', ''),
            p.get('uuid', ''),
            p.get('network', 'tcp')
        ]
        
        if 'ws-opts' in p and p['ws-opts'].get('path'):
            key_parts.append(p['ws-opts']['path'])
        if p.get('servername'):
            key_parts.append(p['servername'])
            
        key = md5(':'.join(key_parts).encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            result.append(p)
    
    print(f"[DEBUG] 去重后节点数: {len(result)} (原始: {len(proxies)})")
    return result

def filter_us(proxies):
    """增强的 US 节点筛选"""
    us_nodes = []
    exclude_keywords = [
        "HK", "HONG KONG", "香港", "港",
        "SG", "SINGAPORE", "新加坡", "狮城",
        "JP", "JAPAN", "日本", "东京", "TOKYO",
        "KR", "KOREA", "韩国", "首尔",
        "TW", "TAIWAN", "台湾", "台北",
        "CN", "CHINA", "中国", "大陆",
        "UK", "LONDON", "英国", "伦敦",
        "DE", "GERMANY", "德国", "法兰克福",
        "FR", "FRANCE", "法国", "巴黎"
    ]
    
    us_keywords = [
        "US", "USA", "美国", "UNITED STATES", "AMERICA",
        "LOS ANGELES", "NEW YORK", "CHICAGO", "DALLAS",
        "SAN FRANCISCO", "SEATTLE", "MIAMI", "DENVER",
        "VIRGINIA", "CALIFORNIA", "TEXAS", "OREGON"
    ]
    
    for p in proxies:
        name = p.get("name", "").upper()
        
        # 必须包含 US 关键词
        has_us_keyword = any(keyword in name for keyword in us_keywords)
        # 不能包含排除关键词
        has_exclude_keyword = any(exclude in name for exclude in exclude_keywords)
        
        if has_us_keyword and not has_exclude_keyword:
            us_nodes.append(p)
        elif has_exclude_keyword:
            print(f"[⚠️] 排除非 US 节点: {p['name']}", file=sys.stderr)
    
    print(f"[DEBUG] 筛选出 {len(us_nodes)} 个 US 节点")
    return us_nodes

def save_yaml(path, proxies):
    """保存 YAML 文件，增加质量信息"""
    abs_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    
    # 按质量分数排序
    sorted_proxies = sorted(proxies, key=lambda x: x.get('quality_score', 0), reverse=True)
    
    # 添加元数据
    output_data = {
        "proxies": sorted_proxies,
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "total_nodes": len(sorted_proxies),
            "quality_tested": sum(1 for p in sorted_proxies if 'quality_score' in p)
        }
    }
    
    with open(abs_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(output_data, f, allow_unicode=True, default_flow_style=False)
    
    print(f"[💾] 已保存到 {abs_path}，节点数: {len(proxies)}")
    if sorted_proxies and 'quality_score' in sorted_proxies[0]:
        avg_score = statistics.mean([p['quality_score'] for p in sorted_proxies if 'quality_score' in p])
        print(f"[📊] 平均质量分数: {avg_score:.2f}")

# ========== 增强的连接测试 ==========
async def advanced_connection_test(session, proxy_config, test_urls=None):
    """高级连接测试，多维度评估节点质量"""
    if test_urls is None:
        test_urls = TEST_URLS
    
    node_name = proxy_config.get('name', '未知节点')
    server = proxy_config.get('server')
    port = int(proxy_config.get('port', 0))
    
    if not server or not port:
        return None
    
    # 1. Socket 连接测试
    socket_latencies = []
    socket_success = 0
    
    for i in range(3):  # 多次测试提高准确性
        latency = await test_socket_connection(server, port)
        if latency is not None:
            socket_latencies.append(latency)
            socket_success += 1
        await asyncio.sleep(0.1)  # 小间隔
    
    if not socket_latencies or statistics.mean(socket_latencies) > LATENCY_THRESHOLD:
        print(f"[❌] {node_name} | Socket 测试失败或延迟过高", file=sys.stderr)
        return None
    
    # 2. HTTP 响应测试
    http_success = 0
    http_latencies = []
    
    for test_url in random.sample(test_urls, min(2, len(test_urls))):  # 随机测试2个URL
        try:
            start_time = time.time()
            timeout = aiohttp.ClientTimeout(total=TEST_TIMEOUT)
            async with session.get(test_url, timeout=timeout) as resp:
                await resp.read()  # 确保完全下载
                latency = (time.time() - start_time) * 1000
                if resp.status in [200, 204]:
                    http_latencies.append(latency)
                    http_success += 1
        except Exception as e:
            print(f"[⚠️] {node_name} HTTP 测试失败: {e}", file=sys.stderr)
    
    # 计算质量分数
    all_latencies = socket_latencies + http_latencies
    total_tests = 3 + len(test_urls)  # socket测试3次 + HTTP测试
    success_count = socket_success + http_success
    
    if success_count / total_tests < SUCCESS_RATE_THRESHOLD:
        print(f"[❌] {node_name} | 成功率过低 ({success_count}/{total_tests})", file=sys.stderr)
        return None
    
    # 加载历史数据
    quality_history = load_quality_history()
    node_key = f"{server}:{port}"
    historical_data = quality_history.get(node_key, {})
    
    quality_score = calculate_quality_score(all_latencies, success_count, total_tests, historical_data)
    
    # 更新历史数据
    historical_data.setdefault('recent_scores', []).append(quality_score)
    historical_data['recent_scores'] = historical_data['recent_scores'][-10:]  # 保留最近10次
    historical_data['last_test'] = datetime.now().isoformat()
    quality_history[node_key] = historical_data
    
    # 添加质量信息到代理配置
    proxy_config['quality_score'] = quality_score
    proxy_config['test_info'] = {
        'avg_latency': round(statistics.mean(all_latencies), 2),
        'success_rate': round(success_count / total_tests, 3),
        'last_tested': datetime.now().isoformat()
    }
    
    print(f"[✅] {node_name} | 质量分数: {quality_score:.2f} | 延迟: {statistics.mean(all_latencies):.0f}ms | 成功率: {success_count}/{total_tests}")
    
    # 保存更新的历史数据
    save_quality_history(quality_history)
    
    return proxy_config

async def test_socket_connection(server, port, timeout=TEST_TIMEOUT):
    """异步 Socket 连接测试"""
    try:
        loop = asyncio.get_running_loop()
        start_time = time.time()
        
        # 使用 asyncio 的连接测试
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(server, port),
                timeout=timeout
            )
            end_time = time.time()
            writer.close()
            await writer.wait_closed()
            return (end_time - start_time) * 1000
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None
            
    except Exception as e:
        return None

async def test_connection_async(session, proxy_config, semaphore):
    """异步测试单个节点的连接性，使用增强的测试方法"""
    async with semaphore:
        return await advanced_connection_test(session, proxy_config)

async def main():
    """主函数，包含完整的优化流程"""
    all_proxies = []

    print("--- 开始从固定 URL 获取订阅源 ---")
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=100, ttl_dns_cache=300),
        timeout=aiohttp.ClientTimeout(total=30)
    ) as session:
        subscription_urls = await fetch_subscription_urls(session)
        if not subscription_urls:
            print("[❌] 无可用订阅 URL，退出", file=sys.stderr)
            return
        
        print("--- 开始下载并合并订阅 ---")
        tasks = [fetch_subscription(session, url) for url in subscription_urls]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in responses:
            if isinstance(result, Exception):
                print(f"[❌] 下载任务失败: {result}", file=sys.stderr)
                continue
                
            url, text = result
            if text:
                proxies = parse_clash_yaml(text) or parse_base64_links(text)
                if proxies:
                    print(f"[✅] 订阅: {url} → {len(proxies)} 节点")
                    all_proxies.extend(proxies)
                else:
                    print(f"[⚠️] 未能识别订阅格式: {url}", file=sys.stderr)

    if not all_proxies:
        print("[❌] 未解析到任何节点，all.yaml 将为空", file=sys.stderr)
        save_yaml(OUTPUT_ALL, [])
        return

    # 去重和基础筛选
    merged = deduplicate(all_proxies)
    print(f"[📦] 合并并去重后节点总数: {len(merged)}")
    
    # 保存所有节点
    save_yaml(OUTPUT_ALL, merged)

    # 筛选 US 节点
    us_nodes_to_test = filter_us(merged)
    if not us_nodes_to_test:
        print("[⚠️] 未找到任何 US 节点，us.yaml 将为空")
        save_yaml(OUTPUT_US, [])
        return

    print(f"[🔍] 开始测试 {len(us_nodes_to_test)} 个 US 节点...")
    
    # 质量测试
    available_us_nodes = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=100, ttl_dns_cache=300),
        timeout=aiohttp.ClientTimeout(total=30)
    ) as session:
        tasks = [test_connection_async(session, node, semaphore) for node in us_nodes_to_test]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            print(f"[⚠️] 节点测试异常: {result}", file=sys.stderr)
            continue
        if result:
            available_us_nodes.append(result)

    # 按质量分数排序
    available_us_nodes.sort(key=lambda x: x.get('quality_score', 0), reverse=True)
    
    print(f"\n[✅] 测试完成！获得 {len(available_us_nodes)} 个高质量 US 节点")
    
    if available_us_nodes:
        print(f"[🏆] 最高质量节点: {available_us_nodes[0]['name']} (分数: {available_us_nodes[0]['quality_score']:.2f})")
        avg_score = statistics.mean([node['quality_score'] for node in available_us_nodes])
        print(f"[📊] 平均质量分数: {avg_score:.2f}")
        save_yaml(OUTPUT_US, available_us_nodes)
    else:
        print("[⚠️] 所有 US 节点测试失败，us.yaml 将为空")
        save_yaml(OUTPUT_US, [])

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n脚本已手动停止。")
    except Exception as e:
        print(f"脚本运行出错: {e}", file=sys.stderr)
