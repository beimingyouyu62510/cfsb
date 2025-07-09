import logging
import requests
import yaml
from pathlib import Path
from typing import List, Dict
import shutil # 引入 shutil 模块
import os # 引入 os 模块

# 配置日志
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
numeric_log_level = getattr(logging, log_level, logging.INFO)
logging.basicConfig(level=numeric_log_level, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

REMOTE_URLS = [
    "https://raw.githubusercontent.com/hebe061103/cfip/refs/heads/master/config_dns_yes.yaml"
]

def fetch_remote_yaml(url: str) -> Dict:
    """从远程 URL 获取 YAML 数据"""
    try:
        logger.info(f"Fetching YAML from {url}")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = yaml.safe_load(response.text) or {}
        proxies = data.get('proxies', [])
        logger.info(f"Fetched {len(proxies)} proxies from {url}.")
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
        logger.info(f"Loaded config with {len(config.get('proxies', []))} proxies.")
        return config
    except yaml.YAMLError as e:
        logger.error(f"Invalid YAML in {file_path}: {e}")
        return {}
    except FileNotFoundError:
        logger.warning(f"{file_path} not found, starting with empty config.")
        return {}

def save_yaml(data: Dict, file_path: Path):
    """保存 YAML 数据到文件"""
    try:
        logger.info(f"Saving YAML to {file_path}")
        with file_path.open('w', encoding='utf-8') as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        logger.info(f"Successfully saved YAML to {file_path}")
    except (IOError, OSError) as e:
        logger.error(f"Failed to save {file_path}: {e}")
        raise

def filter_proxies(proxies: List[Dict]) -> List[Dict]:
    """过滤代理节点，仅保留 VLESS+WebSocket 节点"""
    filtered = []
    logger.info(f"Starting to filter {len(proxies)} proxies...")
    for proxy in proxies:
        if proxy.get('type') == 'vless' and proxy.get('network') == 'ws':
            filtered.append(proxy)
            logger.debug(f"Kept proxy {proxy.get('name', 'Unknown')}")
        else:
            logger.debug(f"Skipping proxy {proxy.get('name', 'Unknown')}: not VLESS+WS type.")
    logger.info(f"Finished filtering. Kept {len(filtered)} VLESS+WS proxies.")
    return filtered

def update_main_proxy_group(config: Dict, proxy_names: List[str]):
    """更新 proxy-groups 中名为 '🚀 负载均衡' 的组"""
    if 'proxy-groups' not in config:
        logger.info("No 'proxy-groups' found in config, initializing an empty list.")
        config['proxy-groups'] = []

    # 目标更新的代理组名称，与源订阅和 ch.yaml 中保持一致
    target_group_name = '🚀 负载均衡' 
    # 该组的默认模板，类型为 url-test (因为源订阅和你的ch.yaml中最可能被所有组引用的类型)
    target_group_template = {
        'name': target_group_name,
        'type': 'url-test', # 默认设置为 url-test，如果 ch.yaml 中是 load-balance 也会被覆盖
        'url': 'http://www.google.com/generate_204',
        'interval': 300,
        'tolerance': 50, # url-test 需要 tolerance
        'proxies': proxy_names
    }
    
    found = False
    for i, group in enumerate(config['proxy-groups']):
        if group.get('name') == target_group_name:
            # 保留原有组的 type, url, interval, tolerance 等，只更新 proxies 列表
            # 这样可以兼容 ch.yaml 中该组是 load-balance 或 select 的情况
            # 如果 ch.yaml 中没有这些字段，会使用模板中的默认值
            group['proxies'] = proxy_names
            # 更新其他可能变动的字段，但优先保留 ch.yaml 中的
            group['type'] = group.get('type', target_group_template['type'])
            group['url'] = group.get('url', target_group_template['url'])
            group['interval'] = group.get('interval', target_group_template['interval'])
            if group['type'] == 'url-test': # 只有 url-test 需要 tolerance
                group['tolerance'] = group.get('tolerance', target_group_template.get('tolerance'))
            
            config['proxy-groups'][i] = group
            found = True
            logger.info(f"Updated '{target_group_name}' group with {len(proxy_names)} proxies.")
            break
    if not found:
        # 如果不存在，则添加新组
        config['proxy-groups'].append(target_group_template)
        logger.info(f"Added '{target_group_name}' group with {len(proxy_names)} proxies.")


def main():
    """主函数：更新 ch.yaml 的 proxies 和 proxy-groups 中的 🚀 负载均衡"""
    config_file = Path('ch.yaml')
    backup_file = Path('ch.yaml.bak')
    original_config = {} # 用于保存原始配置，以便回滚

    try:
        # 如果 ch.yaml 存在，先加载原始配置并创建备份
        if config_file.exists():
            original_config = load_local_yaml(config_file)
            if original_config: # 只有成功加载才备份
                logger.info(f"Backing up {config_file} to {backup_file}")
                shutil.copy2(config_file, backup_file) # 使用 shutil.copy2 复制文件，保留元数据
            else:
                logger.warning(f"Could not load existing {config_file}, proceeding with empty config (no backup made from invalid file).")
                original_config = {} # 确保是空字典，即使文件存在但内容无效
        else:
            logger.info(f"{config_file} not found, starting with empty configuration.")
            original_config = {}

        # 使用原始配置作为基础进行修改，避免在失败时影响到它
        updated_config = original_config.copy() 
        
        # 获取远程节点
        all_proxies = []
        for url in REMOTE_URLS:
            remote_data = fetch_remote_yaml(url)
            remote_proxies = remote_data.get('proxies', [])
            all_proxies.extend(filter_proxies(remote_proxies))
        
        if not all_proxies:
            logger.error("No valid VLESS+WS proxies found from remote sources. Exiting without update.")
            # 如果没有有效节点，不进行任何写入操作，直接返回
            return 1 # 返回非零状态码表示非成功
        
        # 更新 proxies
        old_proxies_count = len(updated_config.get('proxies', []))
        updated_config['proxies'] = all_proxies
        proxy_names = [proxy.get('name', 'Unknown') for proxy in all_proxies]
        logger.info(f"Updated proxies: {len(proxy_names)} new proxies replacing {old_proxies_count} old proxies.")
        
        # 更新 🚀 负载均衡 组
        update_main_proxy_group(updated_config, proxy_names)
        
        # 保存更新后的配置文件
        save_yaml(updated_config, config_file)
        
        # 验证更新后的 YAML
        try:
            with config_file.open('r', encoding='utf-8') as f:
                yaml.safe_load(f)
            logger.info(f"Successfully updated and validated {config_file}.")
            # 如果成功，清理备份文件
            if backup_file.exists():
                backup_file.unlink()
                logger.info(f"Removed backup file {backup_file}")
            return 0 # 成功返回 0
        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML after update to {config_file}: {e}")
            raise # 抛出异常，进入 finally 块处理回滚
            
    except Exception as e:
        logger.error(f"An error occurred during the update process: {e}", exc_info=True)
        # 在发生任何异常时尝试恢复备份
        if backup_file.exists():
            logger.info(f"Attempting to restore backup from {backup_file} to {config_file}.")
            try:
                shutil.copy2(backup_file, config_file)
                logger.info(f"Successfully restored {config_file} from backup.")
            except Exception as restore_e:
                logger.error(f"Failed to restore backup {backup_file}: {restore_e}")
        else:
            logger.warning("No backup file found to restore from.")
        return 1 # 失败返回 1

if __name__ == '__main__':
    exit_code = main()
    exit(exit_code)
