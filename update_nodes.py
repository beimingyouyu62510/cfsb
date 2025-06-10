import requests
import yaml

# 远程配置地址（你给的两个）
REMOTE_URLS = [
    "https://raw.githubusercontent.com/beimingyouyu62510/cfsb/refs/heads/main/ch.yaml",
    "https://raw.githubusercontent.com/hebe061103/cfip/refs/heads/master/config_dns_yes.yaml"
]

# 本地配置文件路径
LOCAL_CONFIG_FILE = "ch.yaml"

# 需要更新的代理组名称
TARGET_PROXY_GROUP_NAME = "🌍 国外媒体"

# 代理组中需要保留的固定代理名称（顺序保持）
FIXED_PROXIES = ["🚀 节点选择", "♻️ 自动选择", "🎯 全球直连"]

def fetch_yaml(url):
    resp = requests.get(url)
    resp.raise_for_status()
    return yaml.safe_load(resp.text)

def main():
    # 1. 拉取远程配置，合并 proxies 列表
    all_proxies = []
    for url in REMOTE_URLS:
        conf = fetch_yaml(url)
        proxies = conf.get("proxies", [])
        all_proxies.extend(proxies)

    # 去重并保持顺序的节点名列表
    seen = set()
    node_names = []
    for p in all_proxies:
        name = p.get("name")
        if name and name not in seen:
            seen.add(name)
            node_names.append(name)

    # 2. 读取本地配置文件
    with open(LOCAL_CONFIG_FILE, "r", encoding="utf-8") as f:
        local_conf = yaml.safe_load(f)

    # 3. 替换本地配置的 proxies 部分为远程拉取的最新节点
    local_conf["proxies"] = all_proxies

    # 4. 更新指定 proxy-group 的 proxies 字段
    proxy_groups = local_conf.get("proxy-groups", [])
    for group in proxy_groups:
        if group.get("name") == TARGET_PROXY_GROUP_NAME:
            # 组装新 proxies 列表：先固定的，再最新节点名
            group["proxies"] = FIXED_PROXIES + node_names

    # 5. 写回本地配置文件
    with open(LOCAL_CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.safe_dump(local_conf, f, allow_unicode=True)

    print(f"更新完成，{LOCAL_CONFIG_FILE} 已同步最新节点和代理组。")

if __name__ == "__main__":
    main()
