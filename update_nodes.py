import requests
import yaml
from datetime import datetime

# 远程节点源（目标仓库）
SOURCE_URL = "https://raw.githubusercontent.com/hebe061103/cfip/refs/heads/master/config_dns_yes.yaml"
# 本地仓库中的你的配置文件
TARGET_FILE = "ch.yaml"

def load_yaml_from_url(url):
    response = requests.get(url)
    response.raise_for_status()
    return yaml.safe_load(response.text)

def load_yaml_from_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_yaml_to_file(data, path):
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)

def main():
    print("📥 正在加载远程节点配置...")
    source_config = load_yaml_from_url(SOURCE_URL)
    source_proxies = source_config.get("proxies", [])

    print("📂 正在加载本地配置...")
    target_config = load_yaml_from_file(TARGET_FILE)
    target_proxies_old = target_config.get("proxies", [])

    if source_proxies != target_proxies_old:
        print("🔄 检测到节点变化，正在更新...")
        target_config["proxies"] = source_proxies
        save_yaml_to_file(target_config, TARGET_FILE)
        print(f"✅ 配置已更新，节点数量：{len(source_proxies)}")
    else:
        print("✔️ 节点无变化，无需更新。")

if __name__ == "__main__":
    main()
