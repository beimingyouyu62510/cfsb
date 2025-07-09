import logging
import requests
import yaml
from pathlib import Path
from typing import List, Dict, Set
import socket
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
REMOTE_URLS = [
    'https://raw.githubusercontent.com/beimingyouyu62510/cfsb/refs/heads/main/ch.yaml',
    'https://raw.githubusercontent.com/hebe061103/cfip/refs/heads/master/config_dns_yes.yaml'
]
LOCAL_CONFIG_FILE = Path('ch.yaml')
BACKUP_CONFIG_FILE = Path('ch.yaml.bak')
TARGET_PROXY_GROUPS = [
    '🚀 节点选择', '♻️ 自动选择', '🌍 国外媒体', '📲 电报信息', 'Ⓜ️ 微软服务',
    '🍎 苹果服务', '📢 谷歌FCM', '🎯 全球直连', '🛑 全球拦截', '🍃 应用净化', '🐟 漏网之鱼'
]
FIXED_PROXIES = ['🚀 节点选择', '♻️ 自动选择', '🎯 全球直连']

def fetch_yaml(url: str) -> Dict:
    """Fetch and parse YAML from a URL."""
    try:
        logger.info(f"Fetching YAML from {url}")
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = yaml.safe_load(resp.text)
        if not isinstance(data, dict):
            raise ValueError(f"Invalid YAML structure from {url}")
        return data
    except (requests.RequestException, yaml.YAMLError, ValueError) as e:
        logger.error(f"Failed to fetch or parse {url}: {e}")
        raise

def load_local_config(file_path: Path) -> Dict:
    """Load and validate local YAML configuration."""
    try:
        if not file_path.exists():
            raise FileNotFoundError(f"{file_path} not found")
        with file_path.open('r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        if not isinstance(config, dict):
            raise ValueError(f"Invalid YAML in {file_path}")
        return config
    except (IOError, yaml.YAMLError, ValueError) as e:
        logger.error(f"Failed to load {file_path}: {e}")
        raise

def save_config(file_path: Path, config: Dict) -> None:
    """Save configuration to YAML file with backup."""
    try:
        if file_path.exists():
            file_path.replace(BACKUP_CONFIG_FILE)
            logger.info(f"Backed up {file_path} to {BACKUP_CONFIG_FILE}")
        with file_path.open('w', encoding='utf-8') as f:
            yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
        logger.info(f"Saved updated config to {file_path}")
    except (IOError, yaml.YAMLError) as e:
        logger.error(f"Failed to save {file_path}: {e}")
        raise

def validate_proxy(proxy: Dict) -> bool:
    """Validate proxy configuration."""
    required_fields = ['name', 'server', 'port', 'type', 'uuid']
    if not all(field in proxy for field in required_fields):
        logger.warning(f"Invalid proxy: missing required fields {proxy.get('name', 'unknown')}")
        return False
    if not isinstance(proxy['name'], str) or not proxy['name'].strip():
        logger.warning(f"Invalid proxy name: {proxy.get('name')}")
        return False
    try:
        socket.inet_aton(proxy['server'])  # Basic IP validation
    except (socket.error, TypeError):
        logger.warning(f"Invalid server IP: {proxy['server']} for {proxy['name']}")
        return False
    return True

def main():
    """Update local YAML configuration with remote proxy nodes."""
    try:
        # Fetch and merge unique proxies
        all_proxies = []
        node_names = []
        seen = set()
        for url in REMOTE_URLS:
            conf = fetch_yaml(url)
            proxies = conf.get('proxies', [])
            if not proxies:
                logger.warning(f"No proxies found in {url}")
            for proxy in proxies:
                if not validate_proxy(proxy):
                    continue
                name = proxy['name']
                if name in seen:
                    continue
                seen.add(name)
                all_proxies.append(proxy)
                node_names.append(name)
        if not all_proxies:
            raise ValueError("No valid proxies collected")
        logger.info(f"Collected {len(all_proxies)} unique proxies")

        # Load local configuration
        local_conf = load_local_config(LOCAL_CONFIG_FILE)

        # Update proxies section
        local_conf['proxies'] = all_proxies
        logger.info(f"Updated proxies section with {len(all_proxies)} entries")

        # Update target proxy groups
        updated = False
        for group in local_conf.get('proxy-groups', []):
            if group.get('name') in TARGET_PROXY_GROUPS:
                group['proxies'] = FIXED_PROXIES + [n for n in node_names if n not in FIXED_PROXIES]
                logger.info(f"Updated proxy group: {group['name']}")
                updated = True
        if not updated:
            logger.warning("No target proxy groups updated")

        # Save updated configuration
        save_config(LOCAL_CONFIG_FILE, local_conf)

    except Exception as e:
        logger.error(f"Script failed: {e}")
        raise

if __name__ == '__main__':
    main()
