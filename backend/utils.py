import requests
import yaml
import json
import base64
import urllib.parse
from hashlib import md5
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def download(url: str) -> str:
    """下载订阅内容，设置超时和状态码检查"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36'
    }
    try:
        resp = requests.get(url, timeout=15, headers=headers)
        resp.raise_for_status()
        logging.info(f"成功下载 {url}")
        return resp.text
    except requests.exceptions.RequestException as e:
        logging.error(f"[❌] 下载失败: {url} 错误: {e}")
        return None

def deduplicate(proxies: list) -> list:
    """使用 md5 对节点进行去重"""
    seen = set()
    result = []
    for p in proxies:
        key_parts = [p.get('server'), str(p.get('port')), p.get('type')]
        if p.get('type') == 'vmess':
            key_parts.append(p.get('uuid'))
        elif p.get('type') in ['ss', 'trojan']:
            key_parts.append(p.get('password'))
        
        key = md5(':'.join(key_parts).encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            result.append(p)
    return result

def parse_clash_yaml(text: str) -> list:
    """解析 Clash YAML 格式的订阅"""
    try:
        data = yaml.safe_load(text)
        if isinstance(data, dict) and "proxies" in data:
            return data["proxies"]
    except Exception as e:
        logging.warning(f"[⚠️] 解析 Clash YAML 失败: {e}")
    return None

def parse_base64(text: str) -> list:
    """解析 Base64 编码的订阅链接"""
    proxies = []
    try:
        text_corrected = text.strip().replace('-', '+').replace('_', '/')
        decoded_text = base64.b64decode(text_corrected + "===").decode("utf-8", errors="ignore")
    except Exception as e:
        logging.warning(f"[⚠️] Base64 解码失败，可能不是 Base64 格式: {e}")
        decoded_text = text

    for line in decoded_text.splitlines():
        line = line.strip()
        if not line:
            continue

        # vmess://
        if line.startswith("vmess://"):
            try:
                node_str = base64.b64decode(line[8:] + "===").decode("utf-8")
                node_json = json.loads(node_str)
                proxies.append({
                    "name": node_json.get("ps", "vmess"),
                    "type": "vmess",
                    "server": node_json["add"],
                    "port": int(node_json["port"]),
                    "uuid": node_json["id"],
                    "alterId": int(node_json.get("aid", 0)),
                    "cipher": node_json.get("scy", "auto"),
                    "tls": True if node_json.get("tls") == "tls" else False,
                    "network": node_json.get("net", "tcp"),
                })
            except Exception as e:
                logging.warning(f"[⚠️] 解析 vmess 节点失败: {e}")

        # ss://
        elif line.startswith("ss://"):
            try:
                info = line[5:]
                if "#" in info:
                    info, name = info.split("#", 1)
                    name = urllib.parse.unquote(name)
                else:
                    name = "ss"
                userinfo_enc, server_port = info.split("@", 1)
                userinfo = base64.b64decode(userinfo_enc + "===").decode(errors="ignore")
                cipher, password = userinfo.split(":", 1)
                server, port = server_port.split(":")
                proxies.append({
                    "name": name, "type": "ss", "server": server,
                    "port": int(port), "cipher": cipher, "password": password,
                })
            except Exception as e:
                logging.warning(f"[⚠️] 解析 ss 节点失败: {e}")

        # trojan://
        elif line.startswith("trojan://"):
            try:
                info = line[9:]
                if "@" in info:
                    password, rest = info.split("@", 1)
                    server_port_raw, *params_raw = rest.split("?", 1)
                else:
                    password, server_port_raw = "", info.split("?", 1)[0]
                    params_raw = info.split("?", 1)[1:]

                server, port = server_port_raw.split(":", 1)
                
                params = {}
                if params_raw:
                    for p in params_raw[0].split("&"):
                        if "=" in p:
                            k, v = p.split("=", 1)
                            params[k] = urllib.parse.unquote(v)
                
                node_config = {
                    "name": params.get("peer", "trojan"),
                    "type": "trojan",
                    "server": server,
                    "port": int(port),
                    "password": password,
                    "tls": True if params.get("security") == "tls" else False,
                }
                proxies.append(node_config)
            except Exception as e:
                logging.warning(f"[⚠️] 解析 trojan 节点失败: {e}")
        
        # vless://
        elif line.startswith("vless://"):
            try:
                info = line[8:]
                uuid_and_server = info.split("@", 1)
                uuid = uuid_and_server[0]
                server_info = uuid_and_server[1].split("?", 1)
                server_port = server_info[0].split(":", 1)
                server = server_port[0]
                port = int(server_port[1])
                
                params = {}
                if len(server_info) > 1:
                    params_str = server_info[1]
                    for p in params_str.split("&"):
                        if "=" in p:
                            k, v = p.split("=", 1)
                            params[k] = urllib.parse.unquote(v)

                node_config = {
                    "name": params.get("peer", "vless"),
                    "type": "vless",
                    "server": server,
                    "port": port,
                    "uuid": uuid,
                    "network": params.get("type", "tcp"),
                }

                if node_config["network"] == "ws":
                    ws_opts = {}
                    if "path" in params:
                        path_cleaned = params["path"].split("?")[0].strip()
                        path_cleaned = path_cleaned.split(" ")[0].strip()
                        ws_opts["path"] = path_cleaned
                    if "host" in params:
                        ws_opts["headers"] = {"Host": params["host"]}
                    node_config["ws-opts"] = ws_opts
                    
                if params.get("security") == "tls":
                    node_config["tls"] = True
                    if "sni" in params:
                        node_config["servername"] = params["sni"]
                        
                if "udp" in params:
                    node_config["udp"] = (params["udp"].lower() == "true")
                if "xudp" in params:
                    node_config["xudp"] = (params["xudp"].lower() == "true")
                    
                proxies.append(node_config)
            except Exception as e:
                logging.warning(f"[⚠️] 解析 vless 节点失败: {e}")

    return proxies if proxies else None
