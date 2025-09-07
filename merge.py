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
    "http://httpbin.org/ip"  # 添加IP检测URL
]
TEST_TIMEOUT = 25  # 增加超时时间
MAX_CONCURRENCY = 15  # 降低并发数提高稳定性
RETRY_COUNT = 2
LATENCY_THRESHOLD = 3000  # 放宽延迟阈值到3秒
SUCCESS_RATE_THRESHOLD = 0.3  # 降低成功率要求到30%
MAX_NODES_PER_IP = 5  # 增加每个IP的节点数量限制
MIN_QUALITY_SCORE = 25  # 大幅降低最低质量分数要求

# 命名配置
NAMING_CONFIG = {
    "PRESERVE_ORIGINAL_NAMES": True,  # 保留原始名称
    "CLEAN_JUNK_CHARS": True,         # 清理垃圾字符
    "ADD_LOCATION_PREFIX": False,     # 不添加地理位置前缀
    "MAX_NAME_LENGTH": 80,            # 增加最大名称长度
    "REMOVE_TEST_WARNINGS": True,     # 移除测速警告
}

# 质量评分权重 - 更注重连通性而非速度
WEIGHTS = {
    'connectivity': 0.50,    # 连通性权重最高
    'latency': 0.25,         # 降低延迟权重
    'success_rate': 0.20,    # 成功率权重
    'stability': 0.05        # 稳定性权重最低
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
    """验证IP地址有效性，但不排除所有内网IP（某些代理可能使用）"""
    try:
        ip_obj = ipaddress.ip_address(ip)
        # 只排除回环、多播等明显无效的IP
        if ip_obj.is_loopback or ip_obj.is_multicast or ip_obj.is_reserved:
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
        high_repeat_ips = {ip: count for ip, count in ip_count.items() if count > 8}
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
    """增强的代理配置验证，更宽松的验证规则"""
    required_fields = ['name', 'type', 'server', 'port']
    
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
    
    # IP地址验证（更宽松）
    server = proxy.get('server', '')
    if not is_valid_ip(server):
        # 允许域名
        if not re.match(r'^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', server):
            return False, f"无效服务器地址: {server}"
    
    # UUID验证（更宽松）
    if proxy.get('type') == 'vless':
        uuid = proxy.get('uuid', '')
        if len(uuid) < 20:  # 放宽UUID要求
            return False, f"UUID过短: {uuid}"
    
    return True, "valid"

def intelligent_dedup(proxies):
    """智能去重，保留更多节点"""
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
            
        # 增加每个IP的节点数量限制
        if len(group) > MAX_NODES_PER_IP:
            print(f"[📊] IP {ip} 有 {len(group)} 个节点，限制为 {MAX_NODES_PER_IP} 个")
            # 按端口和配置多样性排序，保留不同配置的节点
            group.sort(key=lambda x: (x.get('port', 0), x.get('servername', ''), str(x.get('ws-opts', {}))))
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
        "PL", "POLAND", "波兰",
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
        
        # 基于IP地址的地理位置推断
        ip_seems_us = is_likely_us_ip(server)
        
        if (has_us_keyword and not has_exclude_keyword) or ip_seems_us:
            if not has_exclude_keyword:  # 即使IP像美国，也要排除明确标记为其他国家的
                us_nodes.append(proxy)
            else:
                print(f"[⚠️] IP似乎是美国但名称显示其他地区: {proxy['name']}")
    
    print(f"[DEBUG] 筛选出 {len(us_nodes)} 个 US 节点")
    return us_nodes

def is_likely_us_ip(ip):
    """简单的IP地理位置推断 - 基于已知的美国IP段"""
    try:
        ip_obj = ipaddress.ip_address(ip)
        ip_int = int(ip_obj)
        
        # 一些已知的美国IP段
        us_ranges = [
            # Cloudflare
            (ipaddress.ip_address('1.1.1.0'), ipaddress.ip_address('1.1.1.255')),
            # Google DNS
            (ipaddress.ip_address('8.8.8.0'), ipaddress.ip_address('8.8.8.255')),
            # 常见美国数据中心IP段
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

# ========== 优化的节点名称处理 ==========
def clean_node_name(original_name):
    """清理节点名称，保留有意义的信息"""
    if not original_name:
        return "Unknown"
    
    cleaned_name = original_name
    
    if NAMING_CONFIG["CLEAN_JUNK_CHARS"]:
        # 移除测速警告和装饰字符
        junk_patterns = [
            r'【请勿测速】',
            r'™️+',
            r'🐲+',
            r'🌐+', 
            r'：t\.me/\w+',  # 移除电报群链接
            r'HKG™️+',
        ]
        
        for pattern in junk_patterns:
            cleaned_name = re.sub(pattern, '', cleaned_name, flags=re.IGNORECASE)
    
    # 清理多余空格和标点
    cleaned_name = re.sub(r'\s+', ' ', cleaned_name).strip()
    cleaned_name = re.sub(r'^[^\w]+|[^\w]+$', '', cleaned_name)
    
    # 如果清理后为空或过短，返回原名
    if len(cleaned_name) < 3:
        return original_name[:NAMING_CONFIG["MAX_NAME_LENGTH"]]
    
    # 限制长度
    if len(cleaned_name) > NAMING_CONFIG["MAX_NAME_LENGTH"]:
        cleaned_name = cleaned_name[:NAMING_CONFIG["MAX_NAME_LENGTH"]] + "..."
    
    return cleaned_name if cleaned_name else original_name

def ensure_unique_names(proxies):
    """确保节点名称唯一，但尽量保持原始含义"""
    name_counts = defaultdict(int)
    result = []
    
    for proxy in proxies:
        original_name = proxy.get('name', 'Unknown')
        
        if NAMING_CONFIG["PRESERVE_ORIGINAL_NAMES"]:
            base_name = clean_node_name(original_name)
        else:
            # 如果不保留原名，生成标准化名称
            server = proxy.get('server', 'unknown')
            port = proxy.get('port', 'unknown')
            base_name = f"VLESS-{server}:{port}"
        
        # 处理重复名称
        name_counts[base_name] += 1
        if name_counts[base_name] == 1:
            final_name = base_name
        else:
            final_name = f"{base_name} #{name_counts[base_name]}"
        
        proxy['name'] = final_name
        result.append(proxy)
    
    return result

# ========== 更宽松的连接质量测试 ==========
async def relaxed_quality_test(session, proxy_config):
    """更宽松的节点质量测试，重点测试基础连通性"""
    node_name = proxy_config.get('name', '未知节点')
    server = proxy_config.get('server')
    port = int(proxy_config.get('port', 0))
    
    if not server or not port:
        return None, "无效配置"
    
    print(f"[🔍] 测试节点: {node_name} ({server}:{port})")
    
    # 1. Socket 连接测试 - 降低要求
    socket_results = []
    for round_num in range(2):  # 减少测试轮数
        latency = await test_socket_connection(server, port, timeout=15)
        if latency is not None:
            socket_results.append(latency)
        await asyncio.sleep(0.5)  # 增加轮次间隔
    
    if not socket_results:  # 完全无法连接
        print(f"[❌] {node_name} | Socket 连接完全失败")
        return None, "Socket连接失败"
    
    socket_avg = statistics.mean(socket_results)
    
    if socket_avg > LATENCY_THRESHOLD:
        print(f"[⚠️] {node_name} | 延迟较高但可接受: {socket_avg:.0f}ms")
        # 不直接拒绝，继续测试
    
    # 2. 简化的HTTP测试 - 只测试一个URL
    http_success = False
    test_url = random.choice(TEST_URLS)
    
    for attempt in range(2):
        try:
            timeout = aiohttp.ClientTimeout(total=TEST_TIMEOUT)
            async with session.get(test_url, timeout=timeout) as resp:
                if resp.status in [200, 204]:
                    http_success = True
                    break
            await asyncio.sleep(1)
        except Exception as e:
            continue
    
    # 3. 宽松的质量评分
    connectivity_score = 100 if http_success else 0
    if socket_results:
        latency_score = max(0, 100 - (socket_avg / 50))  # 更宽松的延迟评分
    else:
        latency_score = 0
        
    # 综合评分 - 重点关注连通性
    quality_score = (
        connectivity_score * WEIGHTS['connectivity'] +
        latency_score * WEIGHTS['latency'] +
        50 * WEIGHTS['success_rate'] +  # 基础分数
        50 * WEIGHTS['stability']       # 基础分数
    )
    
    # 大幅降低筛选标准
    if socket_results and quality_score >= MIN_QUALITY_SCORE:
        proxy_config['quality_score'] = quality_score
        proxy_config['test_info'] = {
            'avg_latency': round(socket_avg, 2) if socket_results else None,
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
    """优化的YAML保存，保留原始名称并确保兼容性"""
    abs_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    
    if not proxies:
        print(f"[⚠️] 没有可保存的节点到 {abs_path}")
        # 创建空文件以避免错误
        with open(abs_path, "w", encoding="utf-8") as f:
            yaml.safe_dump({"proxies": []}, f, allow_unicode=True)
        return
    
    # 按质量分数排序
    sorted_proxies = sorted(proxies, key=lambda x: x.get('quality_score', 0), reverse=True)
    
    # 处理节点名称
    named_proxies = ensure_unique_names(sorted_proxies)
    
    # 清理配置，移除测试数据
    clean_proxies = []
    for proxy in named_proxies:
        clean_proxy = {k: v for k, v in proxy.items()
                       if k not in ['quality_score', 'test_info']}
        clean_proxies.append(clean_proxy)
    
    # 标准Clash格式
    output_data = {"proxies": clean_proxies}
    
    try:
        with open(abs_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(output_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        
        print(f"[💾] 已保存到 {abs_path}，节点数: {len(clean_proxies)}")
        
        if sorted_proxies and 'quality_score' in sorted_proxies[0]:
            scores = [p.get('quality_score', 0) for p in sorted_proxies]
            avg_score = statistics.mean(scores)
            best_score = max(scores)
            print(f"[📊] 质量分数范围: {min(scores):.0f}-{best_score:.0f}，平均: {avg_score:.1f}")
            
            # 显示前3个最佳节点
            print(f"[🏆] 前3个最佳节点:")
            for i, proxy in enumerate(sorted_proxies[:3], 1):
                print(f"  {i}. {proxy['name']} (分数: {proxy.get('quality_score', 0):.0f})")
                
    except Exception as e:
        print(f"[❌] 保存文件失败: {e}")

# ========== 从固定 URL 获取订阅源 ==========
async def fetch_subscription_urls(session):
    """从固定 URL 下载订阅源列表"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with session.get(UPDATE_FILE_URL, timeout=timeout, headers=headers) as resp:
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
            urls = [line.strip() for line in f if line.strip() and line.strip().startswith('http')]
            print(f"[💾] 从本地加载 {len(urls)} 个备用订阅源")
            return urls
    print(f"[⚠️] 没有找到备用订阅源文件")
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
            timeout = aiohttp.ClientTimeout(total=20 + attempt * 10)
            async with session.get(url, timeout=timeout, headers=headers) as resp:
                resp.raise_for_status()
                text = await resp.text()
                return url, text
        except Exception as e:
            if attempt == RETRY_COUNT - 1:
                print(f"[❌] 下载失败: {url} - {e}")
                return url, None
            else:
                print(f"[⚠️] 尝试 {attempt + 1} 失败，重试: {url}")
                await asyncio.sleep(3 * (attempt + 1))
    
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
                # 不再打印每个无效配置的详细信息
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
    print("=== 代理节点质量优化工具 v2.0 ===")
    print("优化特性:")
    print("✓ 更宽松的质量测试标准")
    print("✓ 保留原始节点名称")
    print("✓ 增强的连通性测试")
    print("✓ 智能去重算法")
    print()
    
    # 分析当前节点(如果存在)
    if os.path.exists(OUTPUT_US):
        print("分析当前us.yaml文件...")
        analyze_current_nodes(OUTPUT_US)
        print()
    
    all_proxies = []

    print("--- 获取订阅源 ---")
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(
            limit=30, 
            ttl_dns_cache=600,
            limit_per_host=5
        ),
        timeout=aiohttp.ClientTimeout(total=60)
    ) as session:
        subscription_urls = await fetch_subscription_urls(session)
        if not subscription_urls:
            print("[❌] 无可用订阅 URL")
            return
        
        print("--- 下载订阅内容 ---")
        tasks = [fetch_subscription(session, url) for url in subscription_urls]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        successful_downloads = 0
        for result in responses:
            if isinstance(result, Exception):
                print(f"[❌] 下载异常: {result}")
                continue
                
            url, text = result
            if text:
                proxies = parse_clash_yaml(text) or parse_base64_links(text)
                if proxies:
                    print(f"[✅] {url} → {len(proxies)} 节点")
                    all_proxies.extend(proxies)
                    successful_downloads += 1
                else:
                    print(f"[⚠️] {url} → 无有效节点")
            else:
                print(f"[❌] {url} → 下载失败")
        
        print(f"\n成功下载: {successful_downloads}/{len(subscription_urls)} 个订阅源")

    if not all_proxies:
        print("[❌] 未获取到任何节点")
        # 创建空文件避免错误
        save_yaml_optimized(OUTPUT_ALL, [])
        save_yaml_optimized(OUTPUT_US, [])
        return

    print(f"\n--- 节点处理与筛选 ---")
    print(f"原始节点数: {len(all_proxies)}")
    
    # 智能去重
    deduplicated = intelligent_dedup(all_proxies)
    
    print(f"\n--- 开始质量测试 ---")
    print(f"测试配置: 超时{TEST_TIMEOUT}s, 延迟阈值{LATENCY_THRESHOLD}ms, 成功率阈值{SUCCESS_RATE_THRESHOLD*100}%")
    
    tested_proxies = []
    failed_proxies = 0

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(
            limit=MAX_CONCURRENCY,
            keepalive_timeout=30,
            enable_cleanup_closed=True
        ),
        timeout=aiohttp.ClientTimeout(total=TEST_TIMEOUT * 2)
    ) as session:
        
        # 分批处理以避免过载
        batch_size = MAX_CONCURRENCY
        total_batches = (len(deduplicated) + batch_size - 1) // batch_size
        
        for batch_idx in range(total_batches):
            start_idx = batch_idx * batch_size
            end_idx = min(start_idx + batch_size, len(deduplicated))
            batch = deduplicated[start_idx:end_idx]
            
            print(f"\n[📊] 处理批次 {batch_idx + 1}/{total_batches} ({len(batch)} 个节点)")
            
            tasks = [relaxed_quality_test(session, proxy) for proxy in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            batch_success = 0
            for result in results:
                if isinstance(result, Exception):
                    print(f"[❌] 测试异常: {result}")
                    failed_proxies += 1
                    continue
                
                tested_proxy, status = result
                if tested_proxy:
                    tested_proxies.append(tested_proxy)
                    batch_success += 1
                else:
                    failed_proxies += 1
            
            print(f"[✅] 批次 {batch_idx + 1} 成功: {batch_success}/{len(batch)}")
            
            # 批次间休息
            if batch_idx < total_batches - 1:
                await asyncio.sleep(2)

    print(f"\n--- 测试结果总结 ---")
    print(f"总共测试节点: {len(deduplicated)}")
    print(f"成功节点数: {len(tested_proxies)}")
    print(f"失败节点数: {failed_proxies}")
    print(f"成功率: {len(tested_proxies)/len(deduplicated)*100:.1f}%")

    if not tested_proxies:
        print("[❌] 没有节点通过测试，保存空配置")
        save_yaml_optimized(OUTPUT_ALL, [])
        save_yaml_optimized(OUTPUT_US, [])
        return
    
    # 筛选US节点
    print(f"\n--- 筛选地区节点 ---")
    us_nodes = enhanced_us_filter(tested_proxies)
    
    # 保存结果
    print(f"\n--- 保存结果 ---")
    save_yaml_optimized(OUTPUT_ALL, tested_proxies)
    save_yaml_optimized(OUTPUT_US, us_nodes)
    
    # 生成质量报告
    generate_quality_report(tested_proxies, us_nodes)
    
    print(f"\n=== 完成 ===")
    print(f"✅ 全量节点: {len(tested_proxies)} 个")
    print(f"✅ US节点: {len(us_nodes)} 个")
    print(f"📊 配置已保存到 providers/ 目录")

def generate_quality_report(all_nodes, us_nodes):
    """生成质量报告"""
    try:
        if not all_nodes:
            return
            
        scores = [node.get('quality_score', 0) for node in all_nodes]
        
        report = {
            "generated_at": datetime.now().isoformat(),
            "total_nodes": len(all_nodes),
            "us_nodes": len(us_nodes),
            "quality_stats": {
                "min_score": min(scores),
                "max_score": max(scores),
                "avg_score": statistics.mean(scores),
                "median_score": statistics.median(scores)
            },
            "grade_distribution": {
                "excellent": len([s for s in scores if s >= 80]),
                "good": len([s for s in scores if 60 <= s < 80]),
                "fair": len([s for s in scores if 40 <= s < 60]),
                "poor": len([s for s in scores if s < 40])
            },
            "top_nodes": [
                {
                    "name": node.get('name', 'Unknown'),
                    "server": node.get('server', 'Unknown'),
                    "score": node.get('quality_score', 0)
                }
                for node in sorted(all_nodes, key=lambda x: x.get('quality_score', 0), reverse=True)[:10]
            ]
        }
        
        with open(QUALITY_REPORT, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
            
        print(f"[📊] 质量报告已保存到 {QUALITY_REPORT}")
        
    except Exception as e:
        print(f"[⚠️] 生成质量报告失败: {e}")

# 主入口
if __name__ == "__main__":
    try:
        # 设置事件循环策略（Windows兼容）
        if os.name == 'nt':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
        asyncio.run(main())
        
    except KeyboardInterrupt:
        print("\n[⚠️] 程序被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n[❌] 程序发生未知错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
