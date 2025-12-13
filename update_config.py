import yaml
import requests
import re
from typing import List, Dict, Any

# --- 配置信息 ---
SUBSCRIBE_URL = "https://go6.marcozf.top/"
CONFIG_FILE = "free.yaml"
# 节点组名称列表，需要同步更新 proxies 列表
PROXY_GROUP_NAMES_TO_UPDATE = [
    "自动选择",
    "手动选择",
    "老司机" 
]
# 用于修复头部 YAML 结构的关键顶层配置项。
# 【关键修复】已将 'unifiée-delay' 修正为正确的 'unified-delay'。
TOP_LEVEL_HEADER_KEYS = [
    "allow-lan", "mode", "log-level", "external-controller", 
    "secret", "unified-delay", "global-client-fingerprint", "dns", 
    "proxies" # 'proxies'是修复的终点
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
    下载 Clash 配置文件，清理内容并修正结构错误，然后提取 'proxies' 列表。
    """
    print(f"-> 正在下载订阅：{url}")
    try:
        # 允许重定向，设置超时
        response = requests.get(url, timeout=15, allow_redirects=True) 
        # 确保以 UTF-8 编码读取
        response.encoding = 'utf-8' 
        response.raise_for_status()
        content = response.text
    except requests.exceptions.RequestException as e:
        print(f"⚠️ 下载订阅失败: {e}")
        return None

    # 1. 清理控制字符 (解决 #x008a 等问题)
    # 使用 re.sub 替换掉所有 ASCII 控制字符 (0x00-0x1F) 和扩展的控制字符 (0x7F-0x9F)
    clean_content = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', content)
    
    # 2. 尝试修复 YAML 结构性错误 (解决键值对被合并到一行的问题)
    fixed_content = clean_content
    for key in TOP_LEVEL_HEADER_KEYS:
        # 匹配模式：
        # 找到一个非空格/非换行符/非冒号的字符 (即前一个值的末尾)，紧接着是我们的 key 和冒号。
        # flags=re.IGNORECASE 允许匹配大小写不敏感的 key。
        # \s* 匹配零个或多个空格。
        pattern = r'([^ \n:])(' + re.escape(key) + r'\s*:)'
        # 替换成：[前一个字符] + 换行符 + [下一个键: ...]
        fixed_content = re.sub(pattern, r'\1\n\2', fixed_content, flags=re.IGNORECASE)
        
    # 3. 解析 YAML
    try:
        sub_config = yaml.safe_load(fixed_content)
        
        if not isinstance(sub_config, dict):
            print("❌ 订阅内容解析后不是有效的字典格式。")
            return None

        proxies = sub_config.get('proxies')

        if isinstance(proxies, list):
            print(f"-> 订阅内容已成功解析，找到 {len(proxies)} 个节点。")
            return proxies
        else:
            print("⚠️ 订阅内容中不包含有效的 'proxies' 列表。")
            # 打印修复后的头部，以便进一步排查
            header_lines = fixed_content.splitlines()[:10]
            print("--- 修复后的头部内容片段 ---")
            print('\n'.join(header_lines))
            print("--------------------------")
            return None
            
    except yaml.YAMLError as e:
        print(f"❌ YAML 解析失败，请检查订阅源格式: {e}")
        print(f"尝试修复后的内容长度: {len(fixed_content)}")
        
        # 打印失败行，方便排查
        error_line_match = re.search(r'line (\d+), column (\d+)', str(e))
        if error_line_match:
            line_num = int(error_line_match.group(1))
            lines = fixed_content.splitlines()
            if line_num <= len(lines):
                print(f"失败行（第 {line_num} 行）的片段（前80字符）: {lines[line_num - 1][:80]}")

        return None

def update_config_file(new_proxies: List[Dict[str, Any]]):
    """
    更新本地 free.yaml 文件中的 proxies 和 proxy-groups。
    """
    print(f"-> 正在读取配置文件: {CONFIG_FILE}")
    try:
        # 读取文件时使用 safe_load_all
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
    
    # 3. 确保 allow-lan 开启 
    # 这一步是为了防止订阅源覆盖掉该配置项
    main_config['allow-lan'] = True
    print("-> 确保 'allow-lan: true' 已设置。")
    
    # 4. 写入新的配置
    print(f"-> 正在写入新的配置到 {CONFIG_FILE}")
    try:
        # 使用 PyYAML 的 Dumper 保持可读性，并使用 sort_keys=False 保持键的原始顺序
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
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
