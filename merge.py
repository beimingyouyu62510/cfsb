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
import ipaddress
from collections import defaultdict

# ========== 配置：固定更新文件 URL 和文件路径 ==========
UPDATE_FILE_URL = "https://apicsv.sosorg.nyc.mn/gengxin.txt?token=CMorg"
FALLBACK_FILE = "fallback_urls.txt"
OUTPUT_ALL = "providers/all.yaml"
OUTPUT_US = "providers/us.yaml"
QUALITY_REPORT = "quality_report.json"
BLACKLIST_FILE = "blacklist_ips.txt"

# 优化的测试配置
TEST_URLS = [
    "http://cp.cloudflare.com/generate_204",
    "http://www.google.com/generate_204",
    "http://detectportal.firefox.com/success.txt",
    "http://connectivity-check.ubuntu.com/"
]
TEST_TIMEOUT = 12  # 进一步降低超时，快速淘汰慢节点
MAX_CONCURRENCY = 25  # 降低并发数提高稳定性
RETRY_COUNT = 2
LATENCY_THRESHOLD = 1000  # 降低延迟阈值到1秒
SUCCESS_RATE_THRESHOLD = 0.7  # 提高成功率要求
MAX_NODES_PER_IP = 3  # 限制每个IP的节点数量
MIN_QUALITY_SCORE = 60  # 最低质量分数要求

# 质量评分权重 - 调整权重更注重稳定性
WEIGHTS = {
    'latency': 0.35,
    'success_rate': 0.35,
    'stability': 0.25,
    'diversity': 0.05
}

# ========== IP 质量管理 ==========
def load_ip_blacklist():
    """加载IP黑名单"""
    if os.path.exists(BLACKLIST_FILE):
        with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_ip_blacklist(blacklist):
    """保存IP黑名单"""
    with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(blacklist)))

def is_valid_ip(ip):
    """验证IP地址有效性，排除内网IP"""
    try:
        ip_obj = ipaddress.ip_address(ip)
        # 排除内网、回环、多播等特殊IP
        if (ip_obj.is_private or ip_obj.is_loopback or
            ip_obj.is_multicast or ip_obj.is_reserved):
            return False
        return True
    except:
        return False

def analyze_current_nodes(yaml_file):
    """分析当前节点质量问题"""
    try:
        with open(yaml_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            proxies = data.get('proxies', [])
        
        print(f"\n=== 当前节点分析 ===")
        print(f"总节点数: {len(proxies)}")
        
        # 统计IP使用情况
        ip_count = defaultdict(int)
        uuid_count = defaultdict(int)
        name_patterns = defaultdict(int)
        
        for proxy in proxies:
            ip = proxy.get('server', '')
            uuid = proxy.get('uuid', '')
            name = proxy.get('name', '')
            
            ip_count[ip] += 1
            uuid_count[uuid] += 1
            # 提取名称模式
            base_name = name.split('【')[0] if '【' in name else name
            name_patterns[base_name] += 1
        
        # 显示统计
        print(f"唯一IP数量: {len(ip_count)}")
        print(f"唯一UUID数量: {len(uuid_count)}")
        
        # 重复IP过多的情况
        high_repeat_ips = {ip: count for ip, count in ip_count.items() if count > 10}
        if high_repeat_ips:
            print(f"⚠️ 高重复IP ({len(high_repeat_ips)}个):")
            for ip, count in sorted(high_repeat_ips.items(), key=lambda x: x[1], reverse=True)[:5]:
                print(f"  {ip}: {count}个节点")
        
        # UUID重复情况
        if len(uuid_count) < 5:
            print(f"⚠️ UUID多样性不足，只有{len(uuid_count)}个不同UUID")
        
        return proxies, ip_count, uuid_count
        
    except Exception as e:
        print(f"❌ 分析文件失败: {e}")
        return [], {}, {}

# ========== 增强的节点验证和筛选 ==========
def enhanced_validate_proxy(proxy):
    """增强的代理配置验证"""
    required_fields = ['name', 'type', 'server', 'port', 'uuid']
    
    # 基础字段检查
    for field in required_fields:
        if field not in proxy or not proxy[field]:
            return False, f"缺少字段: {field}"
    
    # 端口验证
    try:
        port = int(proxy['port'])
        if port <= 0 or port > 65535:
            return False, f"端口范围错误: {port}"
    except:
        return False, "端口不是数字"
    
    # IP地址验证
    server = proxy.get('server', '')
    if not is_valid_ip(server):
        return False, f"无效IP: {server}"
    
    # UUID验证 (基础长度检查)
    uuid = proxy.get('uuid', '')
    if len(uuid) < 30:  # UUID应该足够长
        return False, f"UUID过短: {uuid}"
    
    # 协议特定验证
    if proxy.get('type') == 'vless':
        if proxy.get('network') == 'ws':
            ws_opts = proxy.get('ws-opts', {})
            if not ws_opts.get('path'):
                return False, "WebSocket缺少path"
    
    return True, "valid"

def intelligent_dedup(proxies):
    """智能去重，保留质量更好的节点"""
    # 按服务器IP分组
    ip_groups = defaultdict(list)
    for proxy in proxies:
        ip = proxy.get('server', '')
        ip_groups[ip].append(proxy)
    
    result = []
    blacklist = load_ip_blacklist()
    
    for ip, group in ip_groups.items():
        # 跳过黑名单IP
        if ip in blacklist:
            print(f"[⚠️] 跳过黑名单IP: {ip}")
            continue
            
        # 限制每个IP的节点数量
        if len(group) > MAX_NODES_PER_IP:
            print(f"[📊] IP {ip} 有 {len(group)} 个节点，限制为 {MAX_NODES_PER_IP} 个")
            # 按端口和配置多样性排序
            group.sort(key=lambda x: (x.get('port', 0), x.get('servername', ''), x.get('uuid', '')))
            group = group[:MAX_NODES_PER_IP]
        
        result.extend(group)
    
    print(f"[DEBUG] 智能去重后节点数: {len(result)} (原始: {len(proxies)})")
    return result

def enhanced_us_filter(proxies):
    """增强的US节点筛选，更精确识别"""
    us_nodes = []
    
    # 扩展的排除关键词
    exclude_keywords = [
        # 亚洲
        "HK", "HONG KONG", "香港", "港", "HONGKONG",
        "SG", "SINGAPORE", "新加坡", "狮城",
        "JP", "JAPAN", "日本", "东京", "TOKYO", "OSAKA",
        "KR", "KOREA", "韩国", "首尔", "SEOUL",
        "TW", "TAIWAN", "台湾", "台北", "TAIPEI",
        "CN", "CHINA", "中国", "大陆", "MAINLAND",
        "MY", "MALAYSIA", "马来西亚",
        "TH", "THAILAND", "泰国",
        "VN", "VIETNAM", "越南",
        "IN", "INDIA", "印度",
        # 欧洲
        "UK", "LONDON", "英国", "伦敦", "BRITAIN",
        "DE", "GERMANY", "德国", "法兰克福", "FRANKFURT",
        "FR", "FRANCE", "法国", "巴黎", "PARIS",
        "NL", "NETHERLANDS", "荷兰", "AMSTERDAM",
        "IT", "ITALY", "意大利",
        "ES", "SPAIN", "西班牙",
        "RU", "RUSSIA", "俄罗斯", "莫斯科",
        "TR", "TURKEY", "土耳其",
        # 其他
        "CA", "CANADA", "加拿大", "TORONTO",
        "AU", "AUSTRALIA", "澳大利亚",
        "BR", "BRAZIL", "巴西",
    ]
    
    # 美国关键词 - 更全面
    us_keywords = [
        "US", "USA", "美国", "UNITED STATES", "AMERICA", "AMERICAN",
        # 主要城市
        "LOS ANGELES", "NEW YORK", "CHICAGO", "DALLAS", "HOUSTON",
        "SAN FRANCISCO", "SEATTLE", "MIAMI", "DENVER", "ATLANTA",
        "BOSTON", "PHILADELPHIA", "PHOENIX", "SAN DIEGO", "SAN JOSE",
        "AUSTIN", "COLUMBUS", "FORT WORTH", "CHARLOTTE", "DETROIT",
        "EL PASO", "MEMPHIS", "BALTIMORE", "MILWAUKEE", "ALBUQUERQUE",
        # 州名
        "VIRGINIA", "CALIFORNIA", "TEXAS", "OREGON", "FLORIDA",
        "WASHINGTON", "NEVADA", "ARIZONA", "COLORADO", "GEORGIA",
        "ILLINOIS", "OHIO", "PENNSYLVANIA", "MICHIGAN", "TENNESSEE",
        # 缩写
        "LA", "NYC", "SF", "DC", "VA", "CA", "TX", "FL", "WA"
    ]
    
    for proxy in proxies:
        name = proxy.get("name", "").upper()
        server = proxy.get("server", "")
        
        # 检查名称中的关键词
        has_us_keyword = any(keyword in name for keyword in us_keywords)
        has_exclude_keyword = any(exclude in name for exclude in exclude_keywords)
        
        # 基于IP地址的地理位置推断(简单的IP段判断)
        ip_seems_us = is_likely_us_ip(server)
        
        if (has_us_keyword and not has_exclude_keyword) or ip_seems_us:
            if not has_exclude_keyword:  # 即使IP像美国，也要排除明确标记为其他国家的
                us_nodes.append(proxy)
            else:
                print(f"[⚠️] IP似乎是美国但名称显示其他地区: {proxy['name']}")
        elif has_exclude_keyword:
            print(f"[⚠️] 排除非 US 节点: {proxy['name']}")
    
    print(f"[DEBUG] 筛选出 {len(us_nodes)} 个 US 节点")
    return us_nodes

def is_likely_us_ip(ip):
    """简单的IP地理位置推断 - 基于已知的美国IP段"""
    try:
        ip_obj = ipaddress.ip_address(ip)
        ip_int = int(ip_obj)
        
        # 一些已知的美国IP段 (简化版本)
        us_ranges = [
            (ipaddress.ip_address('8.8.8.0'), ipaddress.ip_address('8.8.8.255')),  # Google DNS
            (ipaddress.ip_address('1.1.1.0'), ipaddress.ip_address('1.1.1.255')),  # Cloudflare
            # 可以添加更多已知的美国IP段
        ]
        
        for start, end in us_ranges:
            if int(start) <= ip_int <= int(end):
                return True
                
    except:
        pass
    return False

# ========== 增强的连接质量测试 ==========
async def comprehensive_quality_test(session, proxy_config):
    """全面的节点质量测试"""
    node_name = proxy_config.get('name', '未知节点')
    server = proxy_config.get('server')
    port = int(proxy_config.get('port', 0))
    
    if not server or not port:
        return None, "无效配置"
    
    print(f"[🔍] 测试节点: {node_name} ({server}:{port})")
    
    # 1. 多轮 Socket 连接测试
    socket_results = []
    for round_num in range(3):
        latency = await test_socket_connection(server, port, timeout=8)
        if latency is not None:
            socket_results.append(latency)
        await asyncio.sleep(0.2)  # 轮次间隔
    
    if len(socket_results) < 2:  # 至少成功2次
        print(f"[❌] {node_name} | Socket 连接失败")
        return None, "Socket连接失败"
    
    socket_avg = statistics.mean(socket_results)
    socket_std = statistics.stdev(socket_results) if len(socket_results) > 1 else 0
    
    if socket_avg > LATENCY_THRESHOLD:
        print(f"[❌] {node_name} | 延迟过高: {socket_avg:.0f}ms")
        return None, f"延迟过高: {socket_avg:.0f}ms"
    
    # 2. HTTP 连通性测试
    http_results = []
    test_urls = random.sample(TEST_URLS, min(2, len(TEST_URLS)))
    
    for test_url in test_urls:
        for attempt in range(2):  # 每个URL测试2次
            try:
                start_time = time.time()
                timeout = aiohttp.ClientTimeout(total=TEST_TIMEOUT)
                async with session.get(test_url, timeout=timeout) as resp:
                    await resp.read()
                    latency = (time.time() - start_time) * 1000
                    if resp.status in [200, 204]:
                        http_results.append(latency)
                        break
                    await asyncio.sleep(0.1)
            except Exception as e:
                if attempt == 1:  # 最后一次尝试
                    print(f"[⚠️] {node_name} HTTP测试失败: {test_url} - {e}")
                continue
    
    # 3. 综合评分
    all_latencies = socket_results + http_results
    total_tests = 6  # 3次socket + 最多4次HTTP
    success_count = len(all_latencies)
    success_rate = success_count / total_tests
    
    if success_rate < SUCCESS_RATE_THRESHOLD:
        print(f"[❌] {node_name} | 成功率过低: {success_rate:.2f}")
        return None, f"成功率过低: {success_rate:.2f}"
    
    # 计算质量分数
    quality_score = calculate_enhanced_quality_score(
        all_latencies, success_count, total_tests, socket_std
    )
    
    if quality_score < MIN_QUALITY_SCORE:
        print(f"[❌] {node_name} | 质量分数过低: {quality_score:.2f}")
        return None, f"质量分数过低: {quality_score:.2f}"
    
    # 成功的节点
    proxy_config['quality_score'] = quality_score
    proxy_config['test_info'] = {
        'avg_latency': round(statistics.mean(all_latencies), 2),
        'socket_latency': round(socket_avg, 2),
        'socket_stability': round(socket_std, 2),
        'success_rate': round(success_rate, 3),
        'test_time': datetime.now().isoformat()
    }
    
    print(f"[✅] {node_name} | 质量: {quality_score:.2f} | 延迟: {socket_avg:.0f}±{socket_std:.0f}ms | 成功率: {success_count}/{total_tests}")
    return proxy_config, "success"

def calculate_enhanced_quality_score(latencies, success_count, total_tests, stability_variance):
    """增强的质量分数计算"""
    if not latencies:
        return 0
    
    avg_latency = statistics.mean(latencies)
    success_rate = success_count / total_tests if total_tests > 0 else 0
    
    # 延迟分数 (0-100)
    latency_score = max(0, 100 - (avg_latency / 15))
    
    # 成功率分数 (0-100)
    success_score = success_rate * 100
    
    # 稳定性分数 (基于延迟方差)
    stability_score = max(0, 100 - (stability_variance / 5))
    
    # 速度分数 (基于最小延迟)
    speed_score = max(0, 100 - (min(latencies) / 10)) if latencies else 0
    
    # 综合评分
    final_score = (
        latency_score * WEIGHTS['latency'] +
        success_score * WEIGHTS['success_rate'] +
        stability_score * WEIGHTS['stability'] +
        speed_score * 0.1  # 速度权重
    )
    
    return round(final_score, 2)

async def test_socket_connection(server, port, timeout=8):
    """优化的异步 Socket 连接测试"""
    try:
        start_time = time.time()
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(server, port),
            timeout=timeout
        )
        end_time = time.time()
        writer.close()
        await writer.wait_closed()
        return (end_time - start_time) * 1000
    except:
        return None

def save_yaml_optimized(path, proxies):
    """优化的YAML保存，确保Clash兼容性，并解决节点名称重复问题"""
    abs_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    
    # 按质量分数排序
    sorted_proxies = sorted(proxies, key=lambda x: x.get('quality_score', 0), reverse=True)
    
    # 清理配置，移除测试数据并确保名称唯一
    clean_proxies = []
    name_counts = defaultdict(int)
    
    for proxy in sorted_proxies:
        clean_proxy = {k: v for k, v in proxy.items()
                       if k not in ['quality_score', 'test_info']}
                       
        # 确保名称唯一
        original_name = clean_proxy.get('name', 'unnamed')
        name_counts[original_name] += 1
        if name_counts[original_name] > 1:
            clean_proxy['name'] = f"{original_name} #{name_counts[original_name]}"
        
        clean_proxies.append(clean_proxy)
    
    # 标准Clash格式
    output_data = {"proxies": clean_proxies}
    
    with open(abs_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(output_data, f, allow_unicode=True, default_flow_style=False)
    
    print(f"[💾] 已保存到 {abs_path}，节点数: {len(clean_proxies)}")
    
    if sorted_proxies and 'quality_score' in sorted_proxies[0]:
        avg_score = statistics.mean([p.get('quality_score', 0) for p in sorted_proxies])
        best_score = sorted_proxies[0]['quality_score']
        print(f"[📊] 最高质量分数: {best_score:.2f}")
        print(f"[📊] 平均质量分数: {avg_score:.2f}")
        print(f"[ℹ️] 已移除测试数据，确保 Clash 兼容性")
        
        # 显示前5个最佳节点
        print(f"[🏆] 前5个最佳节点:")
        for i, proxy in enumerate(sorted_proxies[:5], 1):
            print(f"  {i}. {proxy['name']} (分数: {proxy['quality_score']:.2f})")

# ========== 从固定 URL 获取订阅源 ==========
async def fetch_subscription_urls(session):
    """从固定 URL 下载订阅源列表"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        async with session.get(UPDATE_FILE_URL, timeout=15, headers=headers) as resp:
            resp.raise_for_status()
            content = await resp.text()
            if not content.strip():
                return load_fallback_urls()
            urls = [line.strip() for line in content.splitlines()
                   if line.strip() and line.strip().startswith('http')]
            if urls:
                print(f"[✅] 获取 {len(urls)} 个订阅源")
                save_fallback_urls(urls)
                return urls
            else:
                return load_fallback_urls()
    except Exception as e:
        print(f"[❌] 获取订阅源失败: {e}")
        return load_fallback_urls()

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

async def fetch_subscription(session, url):
    """下载订阅内容"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    for attempt in range(RETRY_COUNT):
        try:
            timeout = aiohttp.ClientTimeout(total=15 + attempt * 5)
            async with session.get(url, timeout=timeout, headers=headers) as resp:
                resp.raise_for_status()
                text = await resp.text()
                return url, text
        except Exception as e:
            if attempt == RETRY_COUNT - 1:
                print(f"[❌] 下载失败: {url} - {e}")
                return url, None
            else:
                await asyncio.sleep(2 ** attempt)
    
    return url, None

def parse_clash_yaml(text):
    """解析 Clash YAML"""
    try:
        data = yaml.safe_load(text)
        if isinstance(data, dict) and "proxies" in data:
            valid_proxies = []
            for proxy in data["proxies"]:
                is_valid, reason = enhanced_validate_proxy(proxy)
                if is_valid:
                    valid_proxies.append(proxy)
                else:
                    print(f"[⚠️] 跳过无效配置: {proxy.get('name', 'unknown')} - {reason}")
            return valid_proxies
    except Exception as e:
        print(f"[⚠️] 解析 Clash YAML 失败: {e}")
    return []

def parse_base64_links(text):
    """解析 Base64 订阅"""
    proxies = []
    try:
        # 尝试不同的解码方式
        for decode_func in [
            lambda x: base64.b64decode(x + "==="),
            lambda x: base64.b64decode(x.replace('-', '+').replace('_', '/') + "==="),
            lambda x: base64.urlsafe_b64decode(x + "===")
        ]:
            try:
                decoded_text = decode_func(text.strip()).decode("utf-8", errors="ignore")
                break
            except:
                continue
        else:
            decoded_text = text.strip()
    except:
        decoded_text = text.strip()

    for line in decoded_text.splitlines():
        line = line.strip()
        if not line:
            continue
            
        if line.startswith("vless://"):
            proxy_config = parse_vless_url(line)
            if proxy_config:
                is_valid, reason = enhanced_validate_proxy(proxy_config)
                if is_valid:
                    proxies.append(proxy_config)
                else:
                    print(f"[⚠️] 跳过无效vless配置: {reason}")
    
    return proxies

def parse_vless_url(url):
    """解析 vless URL"""
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
        
        if node_config["network"] == "ws":
            path = params.get("path", [""])[0]
            ws_opts = {"path": path}
            if "host" in params:
                ws_opts["headers"] = {"Host": params["host"][0]}
            node_config["ws-opts"] = ws_opts
            
        if params.get("security", [""])[0] == "tls":
            node_config["tls"] = True
            if "sni" in params:
                node_config["servername"] = params["sni"][0]
        
        return node_config
    except Exception as e:
        return None

async def main():
    """主函数 - 全面优化流程"""
    print("=== 代理节点质量优化工具 ===\n")
    
    # 分析当前节点(如果存在)
    if os.path.exists(OUTPUT_US):
        print("分析当前us.yaml文件...")
        analyze_current_nodes(OUTPUT_US)
        print()
    
    all_proxies = []

    print("--- 获取订阅源 ---")
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=50, ttl_dns_cache=300),
        timeout=aiohttp.ClientTimeout(total=30)
    ) as session:
        subscription_urls = await fetch_subscription_urls(session)
        if not subscription_urls:
            print("[❌] 无可用订阅 URL")
            return
        
        print("--- 下载订阅内容 ---")
        tasks = [fetch_subscription(session, url) for url in subscription_urls]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in responses:
            if isinstance(result, Exception):
                continue
                
            url, text = result
            if text:
                proxies = parse_clash_yaml(text) or parse_base64_links(text)
                if proxies:
                    print(f"[✅] {url} → {len(proxies)} 节点")
                    all_proxies.extend(proxies)

    if not all_proxies:
        print("[❌] 未获取到任何节点")
        return

    print(f"\n--- 节点处理与筛选 ---")
    print(f"原始节点数: {len(all_proxies)}")
    
    # 智能去重
    deduplicated = intelligent_dedup(all_proxies)
    
    print("\n--- 开始全面质量测试 ---")
    tested_proxies = []
    failed_proxies = 0

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=MAX_CONCURRENCY),
        timeout=aiohttp.ClientTimeout(total=TEST_TIMEOUT * 2) # 测试超时时间可以更长
    ) as session:
        tasks = [
            comprehensive_quality_test(session, proxy)
            for proxy in deduplicated
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                print(f"[❌] 测试中发生异常: {result}")
                continue
            
            tested_proxy, status = result
            if tested_proxy:
                tested_proxies.append(tested_proxy)
            else:
                failed_proxies += 1

    print(f"\n--- 测试结果总结 ---")
    print(f"总共测试节点: {len(deduplicated)}")
    print(f"成功节点数: {len(tested_proxies)}")
    print(f"失败节点数: {failed_proxies}")

    # 保存 US 节点
    us_nodes = enhanced_us_filter(tested_proxies)
    save_yaml_optimized(OUTPUT_US, us_nodes)
    
    # 保存所有通过测试的节点
    save_yaml_optimized(OUTPUT_ALL, tested_proxies)
    
# 主入口
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"\n程序发生未知错误: {e}")
