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
import re
import subprocess
import tempfile

# ========== 配置：固定更新文件 URL 和文件路径 ==========
UPDATE_FILE_URL = "https://apicsv.sosorg.nyc.mn/gengxin.txt?token=CMorg"
FALLBACK_FILE = "fallback_urls.txt"
OUTPUT_ALL = "providers/all.yaml"
OUTPUT_US = "providers/us.yaml"
QUALITY_REPORT = "quality_report.json"
BLACKLIST_FILE = "blacklist_ips.txt"

# 优化后的测试配置 - 更宽松但更实用
TEST_URLS = [
    "http://cp.cloudflare.com/generate_204",
    "http://www.google.com/generate_204", 
    "http://detectportal.firefox.com/success.txt",
    "http://httpbin.org/ip"
]
TEST_TIMEOUT = 25
MAX_CONCURRENCY = 15
RETRY_COUNT = 2
LATENCY_THRESHOLD = 3000
SUCCESS_RATE_THRESHOLD = 0.3
MAX_NODES_PER_IP = 5
MIN_QUALITY_SCORE = 25

# 命名配置
NAMING_CONFIG = {
    "PRESERVE_ORIGINAL_NAMES": True,
    "CLEAN_JUNK_CHARS": True,
    "ADD_LOCATION_PREFIX": False,
    "MAX_NAME_LENGTH": 80,
    "REMOVE_TEST_WARNINGS": True,
}

# 质量评分权重
WEIGHTS = {
    'connectivity': 0.50,
    'latency': 0.25,
    'success_rate': 0.20,
    'stability': 0.05
}

# ========= IP 黑名单管理 =========
def load_ip_blacklist():
    if os.path.exists(BLACKLIST_FILE):
        with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_ip_blacklist(blacklist):
    with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(blacklist)))

def is_valid_ip(ip):
    try:
        ip_obj = ipaddress.ip_address(ip)
        if ip_obj.is_loopback or ip_obj.is_multicast or ip_obj.is_reserved:
            return False
        return True
    except:
        return False

# ========= 当前节点分析 =========
def analyze_current_nodes(yaml_file):
    try:
        with open(yaml_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            proxies = data.get('proxies', [])
        
        print(f"\n=== 当前节点分析 ===")
        print(f"总节点数: {len(proxies)}")
        
        ip_count = defaultdict(int)
        uuid_count = defaultdict(int)
        name_patterns = defaultdict(int)
        
        for proxy in proxies:
            ip = proxy.get('server', '')
            uuid = proxy.get('uuid', '')
            name = proxy.get('name', '')
            ip_count[ip] += 1
            uuid_count[uuid] += 1
            base_name = name.split('【')[0] if '【' in name else name
            name_patterns[base_name] += 1
        
        print(f"唯一IP数量: {len(ip_count)}")
        print(f"唯一UUID数量: {len(uuid_count)}")
        
        high_repeat_ips = {ip: count for ip, count in ip_count.items() if count > 8}
        if high_repeat_ips:
            print(f"⚠️ 高重复IP ({len(high_repeat_ips)}个):")
            for ip, count in sorted(high_repeat_ips.items(), key=lambda x: x[1], reverse=True)[:5]:
                print(f"  {ip}: {count}个节点")
        
        if len(uuid_count) < 5:
            print(f"⚠️ UUID多样性不足，只有{len(uuid_count)}个不同UUID")
        
        return proxies, ip_count, uuid_count
    except Exception as e:
        print(f"❌ 分析文件失败: {e}")
        return [], {}, {}

# ========= 节点验证和去重 =========
def enhanced_validate_proxy(proxy):
    required_fields = ['name', 'type', 'server', 'port']
    for field in required_fields:
        if field not in proxy or not proxy[field]:
            return False, f"缺少字段: {field}"
    try:
        port = int(proxy['port'])
        if port <= 0 or port > 65535:
            return False, f"端口范围错误: {port}"
    except:
        return False, "端口不是数字"
    
    server = proxy.get('server', '')
    if not is_valid_ip(server):
        if not re.match(r'^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', server):
            return False, f"无效服务器地址: {server}"
    
    if proxy.get('type') == 'vless':
        uuid = proxy.get('uuid', '')
        if len(uuid) < 20:
            return False, f"UUID过短: {uuid}"
    
    return True, "valid"

def intelligent_dedup(proxies):
    ip_groups = defaultdict(list)
    for proxy in proxies:
        ip = proxy.get('server', '')
        ip_groups[ip].append(proxy)
    
    result = []
    blacklist = load_ip_blacklist()
    
    for ip, group in ip_groups.items():
        if ip in blacklist:
            print(f"[⚠️] 跳过黑名单IP: {ip}")
            continue
        if len(group) > MAX_NODES_PER_IP:
            print(f"[📊] IP {ip} 有 {len(group)} 个节点，限制为 {MAX_NODES_PER_IP} 个")
            group.sort(key=lambda x: (x.get('port', 0), x.get('servername', ''), str(x.get('ws-opts', {}))))
            group = group[:MAX_NODES_PER_IP]
        result.extend(group)
    
    print(f"[DEBUG] 智能去重后节点数: {len(result)} (原始: {len(proxies)})")
    return result

# ========= US节点筛选 =========
def enhanced_us_filter(proxies):
    us_nodes = []
    exclude_keywords = [
        "HK", "SG", "JP", "KR", "TW", "CN", "MY", "TH", "VN", "IN",
        "UK", "DE", "FR", "NL", "IT", "ES", "RU", "TR", "PL", "CA", "AU", "BR"
    ]
    us_keywords = [
        "US", "USA", "美国", "UNITED STATES", "AMERICA", "AMERICAN",
        "LOS ANGELES", "NEW YORK", "CHICAGO", "DALLAS", "HOUSTON",
        "SAN FRANCISCO", "SEATTLE", "MIAMI", "DENVER", "ATLANTA",
        "BOSTON", "PHILADELPHIA", "PHOENIX", "SAN DIEGO", "SAN JOSE",
        "AUSTIN", "COLUMBUS", "FORT WORTH", "CHARLOTTE", "DETROIT",
        "EL PASO", "MEMPHIS", "BALTIMORE", "MILWAUKEE", "ALBUQUERQUE",
        "VIRGINIA", "CALIFORNIA", "TEXAS", "OREGON", "FLORIDA",
        "WASHINGTON", "NEVADA", "ARIZONA", "COLORADO", "GEORGIA",
        "ILLINOIS", "OHIO", "PENNSYLVANIA", "MICHIGAN", "TENNESSEE",
        "LA", "NYC", "SF", "DC", "VA", "CA", "TX", "FL", "WA"
    ]
    
    for proxy in proxies:
        name = proxy.get("name", "").upper()
        server = proxy.get("server", "")
        latency = proxy.get("test_info", {}).get("avg_latency", 9999)
        has_us_keyword = any(keyword in name for keyword in us_keywords)
        has_exclude_keyword = any(exclude in name for exclude in exclude_keywords)
        ip_seems_us = is_likely_us_ip(server)
        if ((has_us_keyword and not has_exclude_keyword) or ip_seems_us) and latency >= 50:
            us_nodes.append(proxy)
    print(f"[DEBUG] 筛选出 {len(us_nodes)} 个真实 US 节点（延迟 ≥ 50ms）")
    return us_nodes

def is_likely_us_ip(ip):
    try:
        ip_obj = ipaddress.ip_address(ip)
        ip_int = int(ip_obj)
        us_ranges = [
            (ipaddress.ip_address('1.1.1.0'), ipaddress.ip_address('1.1.1.255')),
            (ipaddress.ip_address('8.8.8.0'), ipaddress.ip_address('8.8.8.255')),
            (ipaddress.ip_address('108.0.0.0'), ipaddress.ip_address('108.255.255.255')),
            (ipaddress.ip_address('162.0.0.0'), ipaddress.ip_address('162.255.255.255')),
            (ipaddress.ip_address('154.0.0.0'), ipaddress.ip_address('154.255.255.255')),
        ]
        for start, end in us_ranges:
            if int(start) <= ip_int <= int(end):
                return True
    except:
        pass
    return False

# ========= 节点名称优化 =========
def clean_node_name(original_name):
    if not original_name:
        return "Unknown"
    cleaned_name = original_name
    if NAMING_CONFIG["CLEAN_JUNK_CHARS"]:
        junk_patterns = [
            r'【请勿测速】', r'™️+', r'🐲+', r'🌐+', r'：t\.me/\w+', r'HKG™️+'
        ]
        for pattern in junk_patterns:
            cleaned_name = re.sub(pattern, '', cleaned_name, flags=re.IGNORECASE)
    cleaned_name = re.sub(r'\s+', ' ', cleaned_name).strip()
    cleaned_name = re.sub(r'^[^\w]+|[^\w]+$', '', cleaned_name)
    if len(cleaned_name) < 3:
        return original_name[:NAMING_CONFIG["MAX_NAME_LENGTH"]]
    if len(cleaned_name) > NAMING_CONFIG["MAX_NAME_LENGTH"]:
        cleaned_name = cleaned_name[:NAMING_CONFIG["MAX_NAME_LENGTH"]] + "..."
    return cleaned_name if cleaned_name else original_name

def ensure_unique_names(proxies):
    name_counts = defaultdict(int)
    result = []
    for proxy in proxies:
        original_name = proxy.get('name', 'Unknown')
        base_name = clean_node_name(original_name) if NAMING_CONFIG["PRESERVE_ORIGINAL_NAMES"] else f"{proxy.get('type','VLESS')}-{proxy.get('server','unknown')}:{proxy.get('port','unknown')}"
        name_counts[base_name] += 1
        final_name = base_name if name_counts[base_name] == 1 else f"{base_name} #{name_counts[base_name]}"
        proxy['name'] = final_name
        result.append(proxy)
    return result

# ========= 异步质量测试 =========
async def relaxed_quality_test(session, proxy_config):
    node_name = proxy_config.get('name', '未知节点')
    server = proxy_config.get('server')
    port = int(proxy_config.get('port', 0))
    if not server or not port:
        return None, "无效配置"
    print(f"[🔍] 测试节点: {node_name} ({server}:{port})")
    
    socket_results = []
    for _ in range(2):
        latency = await test_socket_connection(server, port, timeout=15)
        if latency is not None:
            socket_results.append(latency)
        await asyncio.sleep(0.5)
    if not socket_results:
        return None, "Socket连接失败"
    
    socket_avg = statistics.mean(socket_results)
    
    http_success = False
    test_url = random.choice(TEST_URLS)
    for _ in range(2):
        try:
            timeout = aiohttp.ClientTimeout(total=TEST_TIMEOUT)
            async with session.get(test_url, timeout=timeout) as resp:
                if resp.status in [200, 204]:
                    http_success = True
                    break
        except:
            continue
    
    connectivity_score = 100 if http_success else 0
    latency_score = max(0, 100 - (socket_avg / 50))
    quality_score = (
        connectivity_score * WEIGHTS['connectivity'] +
        latency_score * WEIGHTS['latency'] +
        50 * WEIGHTS['success_rate'] +
        50 * WEIGHTS['stability']
    )
    
    if socket_results and quality_score >= MIN_QUALITY_SCORE:
        proxy_config['quality_score'] = quality_score
        proxy_config['test_info'] = {
            'avg_latency': round(socket_avg, 2),
            'http_success': http_success,
            'test_time': datetime.now().isoformat()
        }
        status = "优秀" if quality_score >= 70 else "良好" if quality_score >= 50 else "可用"
        print(f"[✅] {node_name} | 质量: {quality_score:.0f} ({status}) | 延迟: {socket_avg:.0f}ms | HTTP: {'通过' if http_success else '失败'}")
        return proxy_config, "success"
    else:
        print(f"[❌] {node_name} | 质量分数过低: {quality_score:.0f}")
        return None, f"质量分数过低: {quality_score:.0f}"

async def test_socket_connection(server, port, timeout=15):
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

# ========= YAML 保存 =========
def save_yaml_optimized(path, proxies):
    abs_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    if not proxies:
        with open(abs_path, "w", encoding="utf-8") as f:
            yaml.safe_dump({"proxies": []}, f, allow_unicode=True)
        print(f"[⚠️] 保存空文件: {abs_path}")
        return
