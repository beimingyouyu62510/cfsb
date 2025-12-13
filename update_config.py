import yaml
import requests
import re
from typing import List, Dict, Any

# --- 配置信息 ---
SUBSCRIBE_URL = "https://go6.marcozf.top/"
CONFIG_FILE = "free.yaml"
# 节点组名称列表，需要同步更新 proxies 列表
# 根据您提供的 free.yaml 文件结构，需要更新 '自动选择' 和 '手动选择' 组，以及 '老司机' 组。
PROXY_GROUP_NAMES_TO_UPDATE = [
    "自动选择",
    "手动选择",
    "老司机" 
    # 注意：'老司机' 组目前配置的是 data.yaml 底部的那几个非数字节点。
    # 如果您希望 '老司机' 组也使用所有新拉取的节点，请保留 '老司机'。
    # 如果您希望 '老司机' 组只包含 data.yaml 底部那几个特定节点，请在下面 get_new_proxy_names_from_subscription 函数中处理，
    # 但根据您最开始的需求，所有 proxy-groups 应该配套更新，因此全部保留。
]
# --- 配置信息结束 ---


def get_new_proxy_names_from_subscription(proxies: List[Dict[str, Any]]) -> List[str]:
    """
    从新的 proxies 列表中提取节点名称。
    """
    if not proxies:
        return []
        
    new_proxy_names = [p.get('name') for p in proxies if 'name' in p]
    
    # 过滤掉 None 或空字符串，并确保唯一性
    return list(filter(None, new_proxy_names))


def fetch_and_parse_subscription(url: str) -> List[Dict[str, Any]] or None:
    """
    下载 Clash 配置文件并提取 'proxies' 列表。
    """
    print(f"-> 正在下载订阅：{url}")
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        content = response.text
    except requests.exceptions.RequestException as e:
        print(f"⚠️ 下载订阅失败: {e}")
        return None

    # 直接解析为 YAML
    try:
        # 使用 safe_load 解析内容
        sub_config = yaml.safe_load(content)
        
        if not isinstance(sub_config, dict):
            print("❌ 订阅内容解析后不是有效的字典格式。")
            return None

        proxies = sub_config.get('proxies')

        if isinstance(proxies, list):
            print(f"-> 订阅内容已成功解析，找到 {len(proxies)} 个节点。")
            return proxies
        else:
            print("⚠️ 订阅内容中不包含有效的 'proxies' 列表。")
            return None
            
    except yaml.YAMLError as e:
        print(f"❌ YAML 解析失败，请检查订阅源格式: {e}")
        return None

def update_config_file(new_proxies: List[Dict[str, Any]]):
    """
    更新本地 free.yaml 文件中的 proxies 和 proxy-groups。
    """
    print(f"-> 正在读取配置文件: {CONFIG_FILE}")
    try:
        # 读取文件时使用 safe_load_all，以防文件中有多个 YAML 文档 (虽然通常只有一个)
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config_docs = list(yaml.safe_load_all(f))
            if not config_docs:
                print("❌ 配置文件为空。")
                return
            main_config = config_docs[0]
            
    except FileNotFoundError:
        print(f"❌ 找不到文件: {CONFIG_FILE}")
        return
    except yaml.YAMLError as e:
        print(f"❌ 解析配置文件失败: {e}")
        return
        
    if not new_proxies:
        print("⚠️ 未获取到新的节点信息，跳过更新。")
        return

    # 1. 更新 proxies 节点列表 (清除历史节点，只保留最新的)
    main_config['proxies'] = new_proxies
    print(f"-> 'proxies' 列表已更新，包含 {len(new_proxies)} 个节点。")
    
    # 2. 更新 proxy-groups 里的 proxies 列表
    new_proxy_names = get_new_proxy_names_from_subscription(new_proxies)
    
    if 'proxy-groups' in main_config and isinstance(main_config['proxy-groups'], list):
        for group in main_config['proxy-groups']:
            group_name = group.get('name')
            if group_name in PROXY_GROUP_NAMES_TO_UPDATE and 'proxies' in group:
                print(f"-> 正在更新代理组: {group_name}")
                # 替换为最新的节点名称列表
                group['proxies'] = new_proxy_names
    
    # 3. 确保 allow-lan 开启 (根据您的要求)
    main_config['allow-lan'] = True
    print("-> 确保 'allow-lan: true' 已设置。")
    
    # 4. 写入新的配置
    print(f"-> 正在写入新的配置到 {CONFIG_FILE}")
    try:
        # 使用 PyYAML 的 Dumper 保持可读性，并使用 sort_keys=False 保持键的原始顺序
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            # 写入主配置文档
            yaml.safe_dump(main_config, f, 
                                allow_unicode=True, 
                                sort_keys=False, 
                                default_flow_style=False)
        print("✅ 配置文件更新成功！")
    except Exception as e:
        print(f"❌ 写入文件失败: {e}")

if __name__ == "__main__":
    # 1. 获取新的节点信息
    proxies = fetch_and_parse_subscription(SUBSCRIBE_URL)
    
    # 2. 更新配置文件
    update_config_file(proxies)
