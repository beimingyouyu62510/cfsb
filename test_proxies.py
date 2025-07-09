import logging
import socket
import ssl
import yaml
from pathlib import Path
from typing import Dict
import websocket
import os # 引入 os 模块

# 配置日志
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
numeric_log_level = getattr(logging, log_level, logging.INFO)
logging.basicConfig(level=numeric_log_level, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_proxy_tcp(proxy: Dict) -> bool:
    """测试代理节点的 TCP 连接"""
    server = proxy.get('server')
    port = proxy.get('port', 80)
    name = proxy.get('name', 'Unknown')
    
    if not server or not port:
        logger.warning(f"Skipping TCP test for proxy {name}: Missing 'server' or 'port'.")
        return False

    try:
        logger.info(f"Testing TCP connection for proxy: {name} ({server}:{port})")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((server, port))
        sock.close()
        logger.info(f"TCP connection to {name} ({server}:{port}) succeeded.")
        return True
    except (socket.timeout, socket.gaierror, ConnectionRefusedError, OSError) as e:
        logger.warning(f"TCP connection to {name} ({server}:{port}) failed: {e}")
        return False

def test_proxy_websocket(proxy: Dict) -> bool:
    """测试 WebSocket 连接（支持 TLS 和非 TLS）"""
    server = proxy.get('server')
    port = proxy.get('port', 80)
    name = proxy.get('name', 'Unknown')
    ws_path = proxy.get('ws-opts', {}).get('path', '/')
    ws_host = proxy.get('ws-opts', {}).get('headers', {}).get('Host', server)
    
    if not server or not port:
        logger.warning(f"Skipping WebSocket test for proxy {name}: Missing 'server' or 'port'.")
        return False

    protocol = 'wss' if proxy.get('tls', False) else 'ws'
    ws_url = f"{protocol}://{ws_host}:{port}{ws_path}"
    
    ssl_opts = {}
    if proxy.get('tls', False):
        ssl_opts["cert_reqs"] = ssl.CERT_NONE # 通常在测试中为了方便，忽略证书验证

    try:
        logger.info(f"Testing WebSocket connection for proxy: {name} ({ws_url})")
        ws = websocket.WebSocket(sslopt=ssl_opts)
        ws.connect(ws_url, timeout=5)
        ws.close()
        logger.info(f"WebSocket connection to {name} ({ws_url}) succeeded.")
        return True
    except websocket.WebSocketException as e:
        logger.warning(f"WebSocket connection to {name} ({ws_url}) failed: {e}")
        return False
    except Exception as e:
        logger.warning(f"WebSocket connection to {name} ({ws_url}) encountered an unexpected error: {e}")
        return False

def main():
    """测试 ch.yaml 中所有代理节点的连通性"""
    config_file = Path('ch.yaml')
    
    try:
        if not config_file.exists():
            logger.error(f"Config file {config_file} not found.")
            return 1 # 返回非零状态码
            
        with config_file.open('r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        
        if not isinstance(config, dict) or 'proxies' not in config:
            logger.error("Invalid YAML structure in config file: missing 'proxies' section.")
            return 1
        
        proxies = config.get('proxies', [])
        if not proxies:
            logger.warning("No proxies found in config file.")
            return 0 # 没有代理也是成功执行，但无测试结果
        
        failed_proxies = []
        tested_proxies_count = 0
        
        for proxy in proxies:
            name = proxy.get('name', 'Unknown')
            
            if proxy.get('type') != 'vless' or proxy.get('network') != 'ws':
                logger.info(f"Skipping proxy {name}: Not VLESS+WS type.")
                continue

            # 确保 server 和 port 存在
            if not proxy.get('server') or not proxy.get('port'):
                logger.warning(f"Skipping proxy {name}: Missing 'server' or 'port' configuration.")
                failed_proxies.append(name)
                continue

            tested_proxies_count += 1
            
            if not test_proxy_tcp(proxy):
                failed_proxies.append(name)
                continue
            
            if not test_proxy_websocket(proxy):
                failed_proxies.append(name)
        
        if tested_proxies_count == 0:
            logger.info("No VLESS+WS proxies found to test.")
        elif failed_proxies:
            logger.warning(f"Test completed. Failed proxies ({len(failed_proxies)}/{tested_proxies_count}): {', '.join(failed_proxies)}")
            return 1
        else:
            logger.info(f"Test completed. All {tested_proxies_count} VLESS+WS proxies are reachable.")
        
        return 0 # 成功返回 0

    except (yaml.YAMLError, FileNotFoundError, IOError) as e:
        logger.error(f"Error processing config file: {e}")
        return 1
    except Exception as e:
        logger.critical(f"An unexpected script error occurred: {e}", exc_info=True)
        return 1

if __name__ == '__main__':
    exit_code = main()
    exit(exit_code)
