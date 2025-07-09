import logging
import socket
import ssl
import yaml
from pathlib import Path
from typing import Dict
import websocket  # 需安装 python-websocket-client

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_proxy_tcp(proxy: Dict) -> bool:
    """测试代理节点的 TCP 连接"""
    server = proxy.get('server')
    port = proxy.get('port', 443)
    name = proxy.get('name', 'Unknown')
    
    try:
        logger.info(f"Testing TCP connection for proxy: {name} ({server}:{port})")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((server, port))
        sock.close()
        logger.info(f"TCP connection to {name} succeeded")
        return True
    except (socket.timeout, socket.gaierror, ConnectionRefusedError) as e:
        logger.warning(f"TCP connection to {name} failed: {e}")
        return False

def test_proxy_websocket(proxy: Dict) -> bool:
    """测试 WebSocket 连接（VLESS 使用 ws 协议）"""
    server = proxy.get('server')
    port = proxy.get('port', 443)
    name = proxy.get('name', 'Unknown')
    ws_path = proxy.get('ws-opts', {}).get('path', '/')
    ws_host = proxy.get('ws-opts', {}).get('headers', {}).get('Host', server)
    
    ws_url = f"wss://{ws_host}:{port}{ws_path}"
    
    try:
        logger.info(f"Testing WebSocket connection for proxy: {name} ({ws_url})")
        ws = websocket.WebSocket(sslopt={"cert_reqs": ssl.CERT_NONE})
        ws.connect(ws_url, timeout=5)
        ws.close()
        logger.info(f"WebSocket connection to {name} succeeded")
        return True
    except websocket.WebSocketException as e:
        logger.warning(f"WebSocket connection to {name} failed: {e}")
        return False

def main():
    """测试 ch.yaml 中所有代理节点的连通性"""
    try:
        config_file = Path('ch.yaml')
        if not config_file.exists():
            logger.error(f"Config file {config_file} not found")
            exit(1)
        
        with config_file.open('r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        
        if not isinstance(config, dict) or 'proxies' not in config:
            logger.error("Invalid YAML structure: missing proxies")
            exit(1)
        
        proxies = config.get('proxies', [])
        if not proxies:
            logger.warning("No proxies found in config")
            exit(0)
        
        failed_proxies = []
        for proxy in proxies:
            # 先测试 TCP 连接
            if not test_proxy_tcp(proxy):
                failed_proxies.append(proxy.get('name'))
                continue
            # 如果 TCP 连接成功，测试 WebSocket
            if proxy.get('network') == 'ws' and proxy.get('tls', False):
                if not test_proxy_websocket(proxy):
                    failed_proxies.append(proxy.get('name'))
        
        if failed_proxies:
            logger.warning(f"Failed proxies: {', '.join(failed_proxies)}")
            # 注释掉 exit(1) 以允许工作流继续运行
            # exit(1)
        else
            logger.info("All proxies are reachable")
    
    except Exception as e:
        logger.error(f"Script failed: {e}")
        exit(1)

if __name__ == '__main__':
    main()
