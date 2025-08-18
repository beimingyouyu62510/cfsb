import os
import requests
import yaml
import json
import subprocess
import time
import shutil
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List

# 配置
CLASH_CORE_NAME = "clash-linux-amd64"  # 确保这个文件名和你的 Clash 核心可执行文件一致
CLASH_CONFIG_PATH = "clash-config.yaml"
CLASH_API_URL = "http://127.0.0.1:9090"
CLASH_API_SECRET = "your-api-secret" # 记得修改为你的密钥
API_TEST_URL = "http://cp.cloudflare.com/generate_204"

app = FastAPI()

class TestNodesRequest(BaseModel):
    urls: List[str]

# 辅助函数：下载订阅、解析和去重
# ... 请将你之前脚本中的 download, parse_clash_yaml, parse_base64, deduplicate 等函数完整复制到这里 ...
# 为了保持代码简洁，这里省略了这些函数的实现，但它们是必需的。
# 确保你之前的解析和去重函数能够正常工作。
# 以下是 placeholder，你需要用你自己的代码替换：
def download(url):
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.text
    except:
        return None

def parse_clash_yaml(text):
    try:
        data = yaml.safe_load(text)
        if isinstance(data, dict) and "proxies" in data:
            return data["proxies"]
    except:
        return None
    return None

def parse_base64(text):
    # 此处需要你完整的 base64 解析逻辑
    return []

def deduplicate(proxies):
    # 此处需要你完整的去重逻辑
    return proxies

@app.post("/test-nodes")
async def test_nodes(request: TestNodesRequest):
    """
    接收订阅URL列表，下载、合并、测速并返回最快的节点。
    """
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
        "external-controller": "0.0.0.0:9090",
        "secret": CLASH_API_SECRET
    }
    with open(CLASH_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(clash_config, f, allow_unicode=True)
    
    # 3. 启动 Clash 核心进程
    if not os.path.exists(CLASH_CORE_NAME):
        raise HTTPException(status_code=500, detail=f"Clash 核心文件 {CLASH_CORE_NAME} 不存在")
    
    clash_process = None
    try:
        clash_process = subprocess.Popen([f'./{CLASH_CORE_NAME}', '-f', CLASH_CONFIG_PATH], 
                                         cwd=os.path.dirname(__file__))
        print(f"Clash 核心进程已启动，PID: {clash_process.pid}")
        # 等待 Clash 核心启动并监听 API
        time.sleep(10)
        
        # 4. 获取所有节点名称并进行测速
        proxies_url = f"{CLASH_API_URL}/proxies"
        headers = {"Authorization": f"Bearer {CLASH_API_SECRET}"}
        
        response = requests.get(proxies_url, headers=headers)
        response.raise_for_status()
        proxies_info = response.json().get("proxies", {})
        
        # 筛选美国节点进行测速
        us_proxies_names = [name for name, info in proxies_info.items() if "US" in name.upper() or "美国" in name]
        
        test_results = []
        for name in us_proxies_names:
            test_url = f"{CLASH_API_URL}/proxies/{urllib.parse.quote(name)}/delay?url={urllib.parse.quote(API_TEST_URL)}&timeout=5000"
            try:
                test_resp = requests.get(test_url, headers=headers, timeout=10)
                test_resp.raise_for_status()
                latency = test_resp.json().get("delay")
                if latency is not None:
                    test_results.append({"name": name, "delay": latency})
                    print(f"节点 {name} 测速完成，延迟 {latency}ms")
            except Exception as e:
                print(f"节点 {name} 测速失败: {e}")

        # 5. 按延迟排序并返回
        test_results.sort(key=lambda x: x["delay"])
        
        # 从原始 merged_proxies 中找到对应的节点配置
        final_nodes = []
        for result in test_results[:10]: # 只返回最快的前10个
            for node in merged_proxies:
                if node.get("name") == result["name"]:
                    node["delay"] = result["delay"] # 添加延迟信息
                    final_nodes.append(node)
                    break
        
        return {"nodes": final_nodes}

    finally:
        # 6. 停止 Clash 进程并清理
        if clash_process:
            clash_process.terminate()
            clash_process.wait()
            print("Clash 核心进程已停止。")
        if os.path.exists(CLASH_CONFIG_PATH):
            os.remove(CLASH_CONFIG_PATH)
