#!/usr/bin/env python3
"""解析 VLESS+Reality URL 并生成 Xray 客户端配置文件。

从 VLESS_URL 环境变量读取 vless:// 链接，生成 Xray JSON 配置，
使本地 SOCKS5 代理（默认 127.0.0.1:1080）转发至远程 VLESS+Reality 服务器。

用法:
    VLESS_URL="vless://..." python scripts/setup_xray.py
"""

import json
import os
import sys
from urllib.parse import parse_qs, unquote, urlparse

# Xray 配置输出路径
OUTPUT_PATH = "xray_config.json"

# Reality 协议必须的 URL 参数
REQUIRED_PARAMS = ("pbk", "fp", "sni", "sid")

# 允许的传输类型（当前仅支持 tcp）
ALLOWED_NETWORK_TYPES = ("tcp",)


def _mask(value: str, visible_head: int = 4, visible_tail: int = 4) -> str:
    """对敏感字符串做脱敏处理，保留首尾各若干字符。"""
    if not value:
        return "<empty>"
    if len(value) <= visible_head + visible_tail:
        return value[:1] + "***" + value[-1:]
    return value[:visible_head] + "***" + value[-visible_tail:]


def _get_single(params: dict[str, list[str]], key: str) -> str:
    """从 parse_qs 结果中取单个值，缺失返回空字符串。"""
    values = params.get(key, [])
    return values[0] if values else ""


def parse_vless_url(url: str) -> dict:
    """解析 VLESS URL，返回结构化配置参数。

    Args:
        url: vless://uuid@host:port?params#name 格式的链接

    Returns:
        包含 uuid, host, port 及 query 参数的字典

    Raises:
        ValueError: URL 格式错误或缺少必须参数
    """
    parsed = urlparse(url)

    if parsed.scheme.lower() != "vless":
        raise ValueError(f"scheme 必须为 vless，实际为: {parsed.scheme}")

    uuid = parsed.username
    if not uuid:
        raise ValueError("URL 缺少 UUID（userinfo 部分为空）")

    host = parsed.hostname
    if not host:
        raise ValueError("URL 缺少 host")

    if not parsed.port:
        raise ValueError("URL 缺少 port")
    port = parsed.port

    # 解析 query 参数
    params = parse_qs(parsed.query)
    security = _get_single(params, "security").lower()
    network = _get_single(params, "type").lower() or "tcp"

    if security != "reality":
        raise ValueError(f"security 必须为 reality，实际为: {security or '<empty>'}")

    if network not in ALLOWED_NETWORK_TYPES:
        raise ValueError(f"不支持的传输类型: {network}（仅支持 {', '.join(ALLOWED_NETWORK_TYPES)}）")

    # 校验 Reality 必须参数
    result = {"uuid": uuid, "host": host, "port": port, "network": network}
    for key in REQUIRED_PARAMS:
        value = _get_single(params, key)
        if not value:
            raise ValueError(f"缺少 Reality 必须参数: {key}")
        result[key] = value

    # 可选参数
    spx = _get_single(params, "spx")
    if spx:
        result["spx"] = unquote(spx)

    flow = _get_single(params, "flow")
    if flow:
        result["flow"] = flow

    return result


def build_xray_config(vless: dict, socks_port: int) -> dict:
    """根据解析结果生成 Xray JSON 配置。

    Args:
        vless: parse_vless_url() 的返回值
        socks_port: 本地 SOCKS5 监听端口

    Returns:
        Xray 配置字典
    """
    user_obj: dict = {"id": vless["uuid"], "encryption": "none"}
    if "flow" in vless:
        user_obj["flow"] = vless["flow"]

    reality_settings: dict = {
        "publicKey": vless["pbk"],
        "fingerprint": vless["fp"],
        "serverName": vless["sni"],
        "shortId": vless["sid"],
    }
    if "spx" in vless:
        reality_settings["spiderX"] = vless["spx"]

    return {
        "log": {
            "loglevel": "warning",
            "access": "xray_access.log",
            "error": "xray_error.log",
        },
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": socks_port,
                "protocol": "socks",
                "settings": {"udp": True},
            }
        ],
        "outbounds": [
            {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": vless["host"],
                            "port": vless["port"],
                            "users": [user_obj],
                        }
                    ]
                },
                "streamSettings": {
                    "network": vless["network"],
                    "security": "reality",
                    "realitySettings": reality_settings,
                },
            }
        ],
    }


def main() -> int:
    vless_url = os.getenv("VLESS_URL", "").strip()
    if not vless_url:
        print("ERROR: 环境变量 VLESS_URL 未设置或为空")
        return 1

    # 解析 VLESS URL
    try:
        vless = parse_vless_url(vless_url)
    except ValueError as exc:
        print(f"ERROR: VLESS URL 解析失败 — {exc}")
        return 1

    # 脱敏日志
    print(
        f"VLESS 参数: uuid={_mask(vless['uuid'])}, "
        f"host={vless['host']}, port={vless['port']}, "
        f"sni={vless['sni']}, fp={vless['fp']}, "
        f"pbk={_mask(vless['pbk'])}, sid={_mask(vless['sid'], 2, 2)}"
    )

    # SOCKS5 端口
    socks_port_str = os.getenv("SOCKS_PORT", "1080").strip()
    try:
        socks_port = int(socks_port_str)
        if not 1 <= socks_port <= 65535:
            raise ValueError("port out of range")
    except ValueError:
        print(f"ERROR: 无效的 SOCKS_PORT: {socks_port_str}")
        return 1

    # 生成配置
    config = build_xray_config(vless, socks_port)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"Xray 配置已写入: {OUTPUT_PATH} (SOCKS5 -> 127.0.0.1:{socks_port})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
