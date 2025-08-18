import requests
import yaml
import os
from hashlib import md5

# ========== 配置：多个订阅源 ==========
SUBSCRIPTION_URLS = [
    "https://nodesfree.github.io/clashnode/subscribe/clash.yml",
    "https://raw.githubusercontent.com/vxiaov/free_proxies/main/clash/clash.provider.yaml",
    "https://raw.githubusercontent.com/shaoyouvip/free/refs/heads/main/all.yaml",
    "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.yml",
    "https://raw.githubusercontent.com/zhangkaiitugithub/passcro/main/speednodes.yaml",
    "https://raw.githubusercontent.com/xyfqzy/free-nodes/main/nodes/clash.yaml",
    "https://v2rayshare.githubrowcontent.com/2025/08/20250813.yaml",
    "https://raw.githubusercontent.com/go4sharing/sub/main/sub.yaml",
    "https://freenode.openrunner.net/uploads/20250813-clash.yaml",
    "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/clash.yml"
]

OUTPUT_FILE = "providers/all.yaml"


def download_yaml(url):
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return yaml.safe_load(resp.text)
    except Exception as e:
        print(f"[❌] 下载失败: {url} 错误: {e}")
        return None


def deduplicate(proxies):
    seen = set()
    result = []
    for p in proxies:
        # 用 server+port+type 做唯一标识
        key = md5(f"{p.get('server')}:{p.get('port')}:{p.get('type')}".encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            result.append(p)
    return result


def main():
    all_proxies = []
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    for url in SUBSCRIPTION_URLS:
        data = download_yaml(url)
        if data and "proxies" in data:
            all_proxies.extend(data["proxies"])
            print(f"[✅] 成功加载 {url}，节点数: {len(data['proxies'])}")

    # 去重
    merged = deduplicate(all_proxies)
    print(f"[📦] 合并后节点总数: {len(merged)}")

    # 写入文件
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        yaml.safe_dump({"proxies": merged}, f, allow_unicode=True)

    print(f"[💾] 已保存到 {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
