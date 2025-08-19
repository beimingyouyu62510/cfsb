import os
import requests
import yaml
import json
import subprocess
import time
import shutil
import base64
import urllib.parse
from hashlib import md5
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import signal
import sys

# 配置
CLASH_CORE_NAME = "/usr/bin/mihomo"  # 使用系统安装的 mihomo
CLASH_CONFIG_PATH = "clash-config.yaml"
CLASH_API_URL = "http://127.0.0.1:9090"
CLASH_API_SECRET = os.environ.get("CLASH_API_SECRET", "511622")
API_TEST_URL = "http://cp.cloudflare.com/generate_204"

app = FastAPI()

# 全局变量存储 Clash 进程
clash_process = None

class TestNodesRequest(BaseModel):
    urls: List[str]

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
        print(f"[❌] 下载失败: {url} 错误: {e}")
        return None

def parse_clash_yaml(text):
    """解析 Clash YAML 格式的订阅"""
    try:
        data = yaml.safe_load(text)
        if isinstance(data, dict) and "proxies" in data:
            return data["proxies"]
    except Exception as e:
        print(f"[⚠️] 解析 Clash YAML 失败: {e}")
        return None
    return None

def parse_base64(text):
    """解析 Base64 编码的订阅链接"""
    proxies = []
    try:
        text_corrected = text.strip().replace('-', '+').replace('_', '/')
        decoded_text = base64.b64decode(text_corrected + "===").decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[⚠️] Base64 解码失败，可能不是 Base64 格式: {e}")
        decoded_text = text

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
                print(f"[⚠️] 解析 vmess 节点失败: {e}")

        # ss://
        elif line.startswith("ss://"):
            try:
                info = line[5:]
                if "#" in info:
                    info, name = info.split("#", 1)
                    name = urllib.parse.unquote(name)
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
                print(f"[⚠️] 解析 ss 节点失败: {e}")

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
                print(f"[⚠️] 解析 trojan 节点失败: {e}")
        
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
                        path_cleaned = params["path"].split("?")[0].strip()
                        path_cleaned = path_cleaned.split(" ")[0].strip()
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
                print(f"[⚠️] 解析 vless 节点失败: {e}")

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

def cleanup_clash_process():
    """清理 Clash 进程"""
    global clash_process
    if clash_process:
        try:
            clash_process.terminate()
            clash_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            clash_process.kill()
        except Exception as e:
            print(f"清理进程时出错: {e}")
        clash_process = None
    
    # 清理配置文件
    if os.path.exists(CLASH_CONFIG_PATH):
        try:
            os.remove(CLASH_CONFIG_PATH)
        except Exception as e:
            print(f"清理配置文件时出错: {e}")

# 注册信号处理器
def signal_handler(signum, frame):
    print(f"收到信号 {signum}，正在清理...")
    cleanup_clash_process()
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

@app.post("/test-nodes")
async def test_nodes(request: TestNodesRequest):
    """
    接收订阅URL列表，下载、合并、测速并返回最快的节点。
    """
    global clash_process
    
    print("接收到测速请求...")
    all_proxies = []

    # 1. 下载并合并所有节点
    for url in request.urls:
        text = download(url)
        if not text:
            continue
        proxies = parse_clash_yaml(text) or parse_base64(text)
        if proxies:
            print(f"成功下载并解析 {len(proxies)} 个节点 from {url}")
            all_proxies.extend(proxies)
    
    if not all_proxies:
        raise HTTPException(status_code=400, detail="无法从提供的URL获取任何节点")

    merged_proxies = deduplicate(all_proxies)
    print(f"合并并去重后节点总数: {len(merged_proxies)}")
    
    # 2. 准备 Clash 配置
    clash_config = {
        "proxies": merged_proxies,
        "mode": "rule",
        "log-level": "info",
        "external-controller": "127.0.0.1:9090",  # 改为本地监听，提高安全性
        "secret": CLASH_API_SECRET,
        "rules": [
            "MATCH,DIRECT"
        ]
    }
    
    try:
        with open(CLASH_CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(clash_config, f, allow_unicode=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建配置文件失败: {e}")
    
    # 3. 启动 Clash 核心进程
    if not os.path.exists("/usr/bin/mihomo"):
        raise HTTPException(status_code=500, detail="Mihomo 核心文件不存在")
    
    try:
        # 先清理之前的进程
        cleanup_clash_process()
        
        clash_process = subprocess.Popen(
            ["/usr/bin/mihomo", '-f', CLASH_CONFIG_PATH],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        print(f"Clash 核心进程已启动，PID: {clash_process.pid}")
        
        # 等待 Clash 核心启动
        time.sleep(8)
        
        # 检查进程是否正常运行
        if clash_process.poll() is not None:
            stdout, stderr = clash_process.communicate()
            raise HTTPException(
                status_code=500, 
                detail=f"Clash 进程启动失败。stdout: {stdout.decode()}, stderr: {stderr.decode()}"
            )
        
        # 4. 获取所有节点名称并进行测速
        proxies_url = f"{CLASH_API_URL}/proxies"
        headers = {"Authorization": f"Bearer {CLASH_API_SECRET}"}
        
        # 测试 API 连接
        max_retries = 3
        for i in range(max_retries):
            try:
                response = requests.get(proxies_url, headers=headers, timeout=10)
                response.raise_for_status()
                break
            except requests.RequestException as e:
                if i == max_retries - 1:
                    raise HTTPException(status_code=500, detail=f"无法连接到 Clash API: {e}")
                time.sleep(2)
        
        proxies_info = response.json().get("proxies", {})
        
        # 筛选美国节点进行测速
        us_proxies_names = [
            name for name, info in proxies_info.items() 
            if ("US" in name.upper() or "美国" in name or "United States" in name) 
            and info.get("type") != "Selector"  # 排除选择器
        ]
        
        print(f"找到 {len(us_proxies_names)} 个美国节点进行测速")
        
        test_results = []
        for name in us_proxies_names[:30]:  # 限制测试数量
            test_url = f"{CLASH_API_URL}/proxies/{urllib.parse.quote(name)}/delay"
            params = {
                "url": API_TEST_URL,
                "timeout": "5000"
            }
            
            try:
                test_resp = requests.get(test_url, headers=headers, params=params, timeout=15)
                test_resp.raise_for_status()
                delay_data = test_resp.json()
                latency = delay_data.get("delay")
                
                if latency is not None and latency > 0:
                    test_results.append({"name": name, "delay": latency})
                    print(f"节点 {name} 测速完成，延迟 {latency}ms")
                else:
                    print(f"节点 {name} 测速失败，无延迟数据")
                    
            except Exception as e:
                print(f"节点 {name} 测速失败: {e}")

        # 5. 按延迟排序并返回
        test_results.sort(key=lambda x: x["delay"])
        
        # 从原始 merged_proxies 中找到对应的节点配置
        final_nodes = []
        for result in test_results[:10]:  # 只返回最快的前10个
            for node in merged_proxies:
                if node.get("name") == result["name"]:
                    node["delay"] = result["delay"]  # 添加延迟信息
                    final_nodes.append(node)
                    break
        
        print(f"返回 {len(final_nodes)} 个测试通过的节点")
        return {"nodes": final_nodes, "total_tested": len(test_results)}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"测速过程出错: {str(e)}")
    finally:
        # 清理进程和配置文件
        cleanup_clash_process()

@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok", "mihomo_exists": os.path.exists("/usr/bin/mihomo")}

@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时清理资源"""
    cleanup_clash_process()
