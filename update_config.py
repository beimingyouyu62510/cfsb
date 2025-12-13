import yaml
import requests
from base64 import b64decode
import re

# --- 配置信息 ---
SUBSCRIBE_URL = "https://go6.marcozf.top/"
CONFIG_FILE = "free.yaml"
# 节点组名称列表，需要同步更新 proxies 列表
PROXY_GROUP_NAMES = [
    "🎮 PoE专线",
    "♻️ 自动选择"
]
# --- 配置信息结束 ---

def decode_clash_meta_subscription(url):
    """
    下载 Clash Meta 订阅链接，并解析出 proxies 列表。
    由于 Clash Meta 订阅链接可能返回 base64 编码的 YAML 内容，
    因此尝试解析返回内容，如果不是有效的 YAML，则尝试 base64 解码。
    """
    print(f"-> 正在下载订阅：{url}")
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        content = response.text
    except requests.exceptions.RequestException as e:
        print(f"⚠️ 下载订阅失败: {e}")
        return None

    # 尝试直接解析为 YAML (适用于返回原始 YAML 的情况)
    try:
        # 使用 safe_load_all 以兼容可能的多个文档，但我们只关心第一个
        sub_config = next(yaml.safe_load_all(content))
        if 'proxies' in sub_config and isinstance(sub_config['proxies'], list):
            print("-> 订阅内容已直接解析为 YAML 配置。")
            return sub_config['proxies']
    except yaml.YAMLError:
        print("-> 订阅内容不是有效的原始 YAML，尝试 base64 解码...")
        pass
    except StopIteration:
        print("-> 订阅内容为空，尝试 base64 解码...")
        pass

    # 尝试 Base64 解码
    try:
        decoded_content = b64decode(content).decode('utf-8')
        sub_config = next(yaml.safe_load_all(decoded_content))
        if 'proxies' in sub_config and isinstance(sub_config['proxies'], list):
            print("-> Base64 解码成功并解析为 YAML 配置。")
            return sub_config['proxies']
        else:
            print("⚠️ Base64 解码后的内容不包含有效的 'proxies' 列表。")
            return None
    except Exception as e:
        print(f"⚠️ Base64 解码或 YAML 解析失败: {e}")
        return None

def update_config_file(new_proxies):
    """
    更新本地 free.yaml 文件中的 proxies 和 proxy-groups。
    """
    print(f"-> 正在读取配置文件: {CONFIG_FILE}")
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            # 使用 safe_load_all 以保留文件的结构，特别是注释
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

    # 1. 更新 proxies 节点列表
    main_config['proxies'] = new_proxies
    print(f"-> 'proxies' 列表已更新，包含 {len(new_proxies)} 个节点。")
    
    # 2. 更新 proxy-groups 里的 proxies 列表
    # 获取新的节点名称列表
    new_proxy_names = [p['name'] for p in new_proxies]
    
    if 'proxy-groups' in main_config and isinstance(main_config['proxy-groups'], list):
        for group in main_config['proxy-groups']:
            if group.get('name') in PROXY_GROUP_NAMES and 'proxies' in group:
                print(f"-> 正在更新代理组: {group['name']}")
                # 清除旧的节点，替换为最新的节点列表
                group['proxies'] = new_proxy_names
    
    # 3. 确保 allow-lan 开启 (根据您的要求)
    main_config['allow-lan'] = True
    print("-> 确保 'allow-lan: true' 已设置。")
    
    # 4. 写入新的配置
    print(f"-> 正在写入新的配置到 {CONFIG_FILE}")
    try:
        # 使用 PyYAML 的 Dumper 保持可读性，并使用 default_flow_style=False 避免长列表被内联
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            # 使用 safe_dump_all 处理可能的多文档结构（虽然这里只有一个文档）
            yaml.safe_dump_all([main_config] + config_docs[1:], f, 
                                allow_unicode=True, 
                                sort_keys=False, # 保持原始键的顺序
                                default_flow_style=False)
        print("✅ 配置文件更新成功！")
    except Exception as e:
        print(f"❌ 写入文件失败: {e}")

if __name__ == "__main__":
    # 获取新的节点信息
    proxies = decode_clash_meta_subscription(SUBSCRIBE_URL)
    
    # 更新配置文件
    update_config_file(proxies)
