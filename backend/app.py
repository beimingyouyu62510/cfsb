import os
import requests
import yaml
import subprocess
import time
import shutil
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import signal
import sys
import logging

from .config import settings
from .utils import download, deduplicate, parse_clash_yaml, parse_base64

# 配置日志级别
logging.basicConfig(level=settings.LOG_LEVEL.upper(), format='%(asctime)s - %(levelname)s - %(message)s')

app = FastAPI()

# 全局变量存储 Clash 进程
clash_process = None

class TestNodesRequest(BaseModel):
    urls: List[str]
    region: Optional[str] = "US"
    count: Optional[int] = 30
    return_count: Optional[int] = 10
    test_url: Optional[str] = None

def cleanup_clash_process():
    """清理 Clash 进程"""
    global clash_process
    if clash_process:
        logging.info("正在终止 Clash 进程...")
        try:
            clash_process.terminate()
            clash_process.wait(timeout=5)
            logging.info("Clash 进程已终止。")
        except subprocess.TimeoutExpired:
            clash_process.kill()
            logging.warning("强制杀死 Clash 进程。")
        except Exception as e:
            logging.error(f"清理进程时出错: {e}")
        clash_process = None
    
    # 清理配置文件
    clash_config_path = os.path.join(os.getcwd(), "clash-config.yaml")
    if os.path.exists(clash_config_path):
        try:
            os.remove(clash_config_path)
            logging.info("配置文件已删除。")
        except Exception as e:
            logging.error(f"清理配置文件时出错: {e}")

# 注册信号处理器
def signal_handler(signum, frame):
    logging.info(f"收到信号 {signum}，正在清理...")
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
    
    logging.info("接收到测速请求...")
    all_proxies = []

    # 1. 下载并合并所有节点
    for url in request.urls:
        text = download(url)
        if not text:
            continue
        proxies = parse_clash_yaml(text) or parse_base64(text)
        if proxies:
            logging.info(f"成功下载并解析 {len(proxies)} 个节点 from {url}")
            all_proxies.extend(proxies)
    
    if not all_proxies:
        raise HTTPException(status_code=400, detail="无法从提供的URL获取任何节点")

    merged_proxies = deduplicate(all_proxies)
    logging.info(f"合并并去重后节点总数: {len(merged_proxies)}")
    
    # 2. 准备 Clash 配置
    clash_config = {
        "proxies": merged_proxies,
        "mode": "rule",
        "log-level": settings.LOG_LEVEL,
        "external-controller": "127.0.0.1:9090",
        "secret": settings.CLASH_API_SECRET,
        "rules": [
            "MATCH,DIRECT"
        ]
    }
    
    clash_config_path = os.path.join(os.getcwd(), "clash-config.yaml")
    try:
        with open(clash_config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(clash_config, f, allow_unicode=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建配置文件失败: {e}")
    
    # 3. 启动 Clash 核心进程
    try:
        cleanup_clash_process()
        
        clash_process = subprocess.Popen(
            [settings.CLASH_CORE_NAME, '-f', clash_config_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        logging.info(f"Clash 核心进程已启动，PID: {clash_process.pid}")
        
        # 4. 轮询等待 Clash 核心启动
        max_retries = 15
        headers = {"Authorization": f"Bearer {settings.CLASH_API_SECRET}"}
        for i in range(max_retries):
            try:
                response = requests.get(f"{settings.CLASH_API_URL}/proxies", headers=headers, timeout=5)
                response.raise_for_status()
                logging.info("Clash API 连接成功。")
                break
            except requests.exceptions.RequestException as e:
                logging.warning(f"等待 Clash API 启动... ({i+1}/{max_retries})")
                time.sleep(1)
        else:
            raise HTTPException(status_code=500, detail="Clash API 在指定时间内未能启动，请检查日志。")
        
        # 5. 获取所有节点名称并进行测速
        proxies_info = response.json().get("proxies", {})
        
        test_url_to_use = request.test_url or settings.API_TEST_URL
        
        # 过滤指定地区的节点
        if request.region:
            proxies_to_test = [
                name for name, info in proxies_info.items()
                if request.region.upper() in name.upper()
                and info.get("type") != "Selector"
            ]
        else:
            proxies_to_test = [name for name, info in proxies_info.items() if info.get("type") != "Selector"]
        
        logging.info(f"找到 {len(proxies_to_test)} 个节点进行测速")
        
        test_results = []
        for name in proxies_to_test[:request.count]:
            test_url = f"{settings.CLASH_API_URL}/proxies/{requests.utils.quote(name)}/delay"
            params = {
                "url": test_url_to_use,
                "timeout": str(settings.API_TEST_TIMEOUT)
            }
            
            try:
                test_resp = requests.get(test_url, headers=headers, params=params, timeout=15)
                test_resp.raise_for_status()
                delay_data = test_resp.json()
                latency = delay_data.get("delay")
                
                if latency is not None and latency > 0:
                    test_results.append({"name": name, "delay": latency})
                    logging.info(f"节点 {name} 测速完成，延迟 {latency}ms")
                else:
                    logging.warning(f"节点 {name} 测速失败，无延迟数据")
            except Exception as e:
                logging.error(f"节点 {name} 测速失败: {e}")

        # 6. 按延迟排序并返回
        test_results.sort(key=lambda x: x["delay"])
        
        final_nodes = []
        for result in test_results[:request.return_count]:
            for node in merged_proxies:
                if node.get("name") == result["name"]:
                    node["delay"] = result["delay"]
                    final_nodes.append(node)
                    break
        
        logging.info(f"返回 {len(final_nodes)} 个测试通过的节点")
        return {"nodes": final_nodes, "total_tested": len(test_results)}

    except HTTPException:
        raise
    except Exception as e:
        logging.critical(f"测速过程出错: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"测速过程出错: {str(e)}")
    finally:
        cleanup_clash_process()

@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok", "mihomo_exists": os.path.exists(settings.CLASH_CORE_NAME)}

@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时清理资源"""
    cleanup_clash_process()
