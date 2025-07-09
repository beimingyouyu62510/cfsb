import logging
import socket
import yaml
from pathlib import Path
import os
import concurrent.futures
from typing import Dict

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CONFIG_FILE = Path('ch.yaml')
TIMEOUT = int(os.getenv('TIMEOUT', 5))

def load_config(file_path: Path) -> Dict:
    """Load YAML configuration."""
    try:
        with file_path.open('r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except (IOError, yaml.YAMLError) as e:
        logger.error(f"Failed to load {file_path}: {e}")
        raise

def test_proxy(proxy: Dict) -> bool:
    """Test if a proxy server is reachable."""
    server = proxy.get('server')
    port = proxy.get('port')
    name = proxy.get('name', 'unknown')
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        result = sock.connect_ex((server, port))
        sock.close()
        if result == 0:
            logger.info(f"Proxy {name} ({server}:{port}) is reachable")
            return True
        else:
            logger.warning(f"Proxy {name} ({server}:{port}) is not reachable")
            return False
    except Exception as e:
        logger.error(f"Error testing proxy {name} ({server}:{port}): {e}")
        return False

def main():
    """Test all proxies in the configuration."""
    config = load_config(CONFIG_FILE)
    proxies = config.get('proxies', [])
    if not proxies:
        raise ValueError("No proxies found in configuration")

    failed_proxies = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(test_proxy, proxies)
        for proxy, is_reachable in zip(proxies, results):
            if not is_reachable:
                failed_proxies.append(proxy['name'])

    if failed_proxies:
        logger.error(f"Failed proxies: {', '.join(failed_proxies)}")
        raise RuntimeError(f"{len(failed_proxies)} proxies failed connectivity test")
    logger.info("All proxies passed connectivity test")

if __name__ == '__main__':
    main()
