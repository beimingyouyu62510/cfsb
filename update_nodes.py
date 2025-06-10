import yaml
import requests

# 下载远程配置
remote_url = "https://raw.githubusercontent.com/hebe061103/cfip/refs/heads/master/config_dns_yes.yaml"
local_file = "ch.yaml"

remote_yaml = requests.get(remote_url, timeout=10).text
remote_data = yaml.safe_load(remote_yaml)

# 只取 proxies 部分
remote_proxies = remote_data.get("proxies", [])

# 读取本地配置
with open(local_file, "r", encoding="utf-8") as f:
    local_data = yaml.safe_load(f)

local_data["proxies"] = remote_proxies  # 替换 proxies

# 保存更新
with open(local_file, "w", encoding="utf-8") as f:
    yaml.dump(local_data, f, allow_unicode=True, sort_keys=False)
