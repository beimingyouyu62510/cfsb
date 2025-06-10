import requests
import yaml

# 远程 YAML 地址
REMOTE_URLS = [
    'https://raw.githubusercontent.com/beimingyouyu62510/cfsb/refs/heads/main/ch.yaml',
    'https://raw.githubusercontent.com/hebe061103/cfip/refs/heads/master/config_dns_yes.yaml'
]

# 本地文件路径
LOCAL_CONFIG_FILE = 'ch.yaml'

# 目标代理组
TARGET_PROXY_GROUP_NAME = '🚀 节点选择'
TARGET_PROXY_GROUP_NAME = '🌍 国外媒体'
TARGET_PROXY_GROUP_NAME = '📲 电报信息'
TARGET_PROXY_GROUP_NAME = 'Ⓜ️ 微软服务'
TARGET_PROXY_GROUP_NAME = '🍎 苹果服务'
TARGET_PROXY_GROUP_NAME = '📢 谷歌FCM'
TARGET_PROXY_GROUP_NAME = '🎯 全球直连'
TARGET_PROXY_GROUP_NAME = '🛑 全球拦截'
TARGET_PROXY_GROUP_NAME = '🍃 应用净化'
TARGET_PROXY_GROUP_NAME = '🐟 漏网之鱼'

# 保留的固定项（手动设置的节点名）
FIXED_PROXIES = ['🚀 节点选择', '♻️ 自动选择', '🎯 全球直连']

def fetch_yaml(url):
    resp = requests.get(url)
    resp.raise_for_status()
    return yaml.safe_load(resp.text)

def main():
    all_proxies = []
    node_names = []
    seen = set()

    # 1. 获取远程所有节点
    for url in REMOTE_URLS:
        conf = fetch_yaml(url)
        proxies = conf.get('proxies', [])
        for p in proxies:
            name = p.get('name')
            if name and name not in seen:
                seen.add(name)
                all_proxies.append(p)
                node_names.append(name)

    # 2. 加载本地配置
    with open(LOCAL_CONFIG_FILE, 'r', encoding='utf-8') as f:
        local_conf = yaml.safe_load(f)

    # 3. 清空并更新 proxies
    local_conf['proxies'] = all_proxies

    # 4. 更新目标代理组
    for group in local_conf.get('proxy-groups', []):
        if group.get('name') == TARGET_PROXY_GROUP_NAME:
            group['proxies'] = FIXED_PROXIES + node_names

    # 5. 保存配置
    with open(LOCAL_CONFIG_FILE, 'w', encoding='utf-8') as f:
        yaml.safe_dump(local_conf, f, allow_unicode=True)

if __name__ == '__main__':
    main()
