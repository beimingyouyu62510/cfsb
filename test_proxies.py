import logging
import requests
import yaml
from typing import Dict
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_proxy(proxy: Dict) -> bool:
    """测试单个代理节点的连通性"""
    try:
        server = proxy.get('server')
        port = proxy.get('port', 80)
        url = f"http://{server}:{port}"
        logger.info(f"Testing proxy: {proxy.get('name')} ({server}:{port})")
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        logger.info(f"Proxy {proxy.get('name')} is reachable")
        return True
    except requests.RequestException as e:
        logger.warning(f"Proxy {proxy.get('name')} failed: {e}")
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
            if not test_proxy(proxy):
                failed_proxies.append(proxy.get('name'))
        
        if failed_proxies:
            logger.error(f"Failed proxies: {', '.join(failed_proxies)}")
            exit(1)
        else:
            logger.info("All proxies are reachable")
    
    except Exception as e:
        logger.error(f"Script failed: {e}")
        exit(1)

if __name__ == '__main__':
    main()
```
