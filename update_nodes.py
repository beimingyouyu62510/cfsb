import logging
import requests
import yaml
from pathlib import Path
from typing import List, Dict

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

REMOTE_URLS = [
    "https://raw.githubusercontent.com/hebe061103/cfip/refs/heads/master/config_dns_yes.yaml"
]
TARGET_PROXY_GROUPS = ["🚀 节点选择", "♻️ 自动选择", "🌍 国外媒体", "📲 电报信息", "Ⓜ️ 微软服务", "🍎 苹果服务", "📢 谷歌FCM", "🐟 漏网之鱼", "🚀 负载均衡"]

def fetch_remote_yaml(url: str) -> Dict:
    """从远程 URL 获取 YAML 数据"""
    try:
        logger.info(f"Fetching YAML from {url}")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = yaml.safe_load(response.text) or {}
        proxies = data.get('proxies', [])
        logger.info(f"Fetched {len(proxies)} proxies from {url}: {[p.get('name', 'Unknown') for p in proxies]}")
        return data
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return {}
    except yaml.YAMLError as e:
        logger.error(f"Invalid YAML from {url}: {e}")
        return {}

def load_local_yaml(file_path: Path) -> Dict:
    """加载本地 YAML 文件"""
    try:
        logger.info(f"Loading local YAML from {file_path}")
        with file_path.open('r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        logger.info(f"Loaded config with {len(config.get('proxies', []))} proxies: {[p.get('name', 'Unknown') for p in config.get('proxies', [])]}")
        return config
    except yaml.YAMLError as e:
        logger.error(f"Invalid YAML in {file_path}: {e}")
        return {}
    except FileNotFoundError:
        logger.warning(f"{file_path} not found, starting with empty config")
        return {}

def save_yaml(data: Dict, file_path: Path):
    """保存 YAML 数据到文件"""
    try:
        logger.info(f"Saving YAML to {file_path}")
        with file_path.open('w', encoding='utf-8') as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    except Exception as e:
        logger.error(f"Failed to save {file_path}: {e}")
        raise

def filter_proxies(proxies: List[Dict]) -> List[Dict]:
    """过滤代理节点，仅保留 VLESS+WebSocket 节点"""
    filtered = []
    for proxy in proxies:
        if proxy.get('type') == 'vless' and proxy.get('network') == 'ws':
            filtered.append(proxy)
            logger.info(f"Kept proxy {proxy.get('name', 'Unknown')}")
        else:
            logger.warning(f"Skipping proxy {proxy.get('name', 'Unknown')}: not VLESS+WS")
    return filtered

def update_proxy_groups(config: Dict, proxy_names: List[str]):
    """更新 proxy-groups，确保包含负载均衡组和动态节点"""
    if 'proxy-groups' not in config:
        logger.error("No proxy-groups found in config, initializing")
        config['proxy-groups'] = []

    # 添加或更新负载均衡组
    load_balance_group = {
        'name': '🚀 负载均衡',
        'type': 'load-balance',
        'url': 'http://www.google.com/generate_204',
        'interval': 300,
        'strategy': 'consistent-hashing',
        'proxies': proxy_names
    }
    
    found = False
    for group in config['proxy-groups']:
        if group.get('name') == '🚀 负载均衡':
            group.update(load_balance_group)
            found = True
            logger.info(f"Updated load-balance group with {len(proxy_names)} proxies: {proxy_names}")
            break
    if not found:
        config['proxy-groups'].append(load_balance_group)
        logger.info(f"Added load-balance group with {len(proxy_names)} proxies: {proxy_names}")

    # 更新其他 proxy-groups
    for group in config['proxy-groups']:
        group_name = group.get('name')
        if group_name in TARGET_PROXY_GROUPS and group_name != '🚀 负载均衡':
            new_proxies = []
            if group_name == "🎯 全球直连":
                new_proxies = ["DIRECT"]
            elif group_name == "🛑 全球拦截" or group_name == "🍃 应用净化":
                new_proxies = ["REJECT", "DIRECT"]
            else:
                if group_name != "🚀 节点选择":
                    new_proxies.append("🚀 节点选择")
                if group_name != "♻️ 自动选择":
                    new_proxies.append("♻️ 自动选择")
                new_proxies.append("🚀 负载均衡")
                if group_name not in ["Ⓜ️ 微软服务", "🍎 苹果服务"]:
                    new_proxies.append("🎯 全球直连")
                new_proxies.extend(proxy_names)
            
            group['proxies'] = new_proxies
            logger.info(f"Updated proxy-group {group_name} with {len(new_proxies)} proxies: {new_proxies}")
        elif group_name != '🚀 负载均衡':
            logger.warning(f"Skipping unknown proxy-group: {group_name}")

def main():
    """主函数：更新 ch.yaml 的 proxies 和 proxy-groups"""
    config_file = Path('ch.yaml')
    backup_file = Path('ch.yaml.bak')
    
    # 备份当前配置文件
    if config_file.exists():
        logger.info(f"Backing up {config_file} to {backup_file}")
        config_file.replace(backup_file)
    
    # 加载当前配置文件
    config = load_local_yaml(config_file)
    
    # 获取远程节点
    all_proxies = []
    for url in REMOTE_URLS:
        remote_data = fetch_remote_yaml(url)
        remote_proxies = remote_data.get('proxies', [])
        all_proxies.extend(filter_proxies(remote_proxies))
    
    if not all_proxies:
        logger.error("No valid proxies found from remote sources")
        if backup_file.exists():
            logger.info(f"Restoring backup from {backup_file}")
            backup_file.replace(config_file)
        return
    
    # 更新 proxies
    old_proxies = config.get('proxies', [])
    old_proxy_names = [p.get('name', 'Unknown') for p in old_proxies]
    config['proxies'] = all_proxies
    proxy_names = [proxy.get('name', 'Unknown') for proxy in all_proxies]
    logger.info(f"Updated proxies: {len(proxy_names)} new proxies {proxy_names} replaced {len(old_proxies)} old proxies {old_proxy_names}")
    
    # 更新 proxy-groups
    update_proxy_groups(config, proxy_names)
    
    # 保存更新后的配置文件
    save_yaml(config, config_file)
    
    # 验证更新后的 YAML
    try:
        with config_file.open('r', encoding='utf-8') as f:
            yaml.safe_load(f)
        logger.info(f"Successfully updated and validated {config_file}")
    except yaml.YAMLError as e:
        logger.error(f"Invalid YAML after update: {e}")
        if backup_file.exists():
            logger.info(f"Restoring backup from {backup_file}")
            backup_file.replace(config_file)
        raise

if __name__ == '__main__':
    main()
