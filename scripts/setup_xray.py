#!/usr/bin/env python3
"""解析 VLESS+Reality URL 并生成 Xray 客户端配置文件。

优先从 VLESS_URLS（JSON 数组）读取多个 vless:// 链接，回退读取 VLESS_URL
（单个链接）。生成单一 Xray JSON 配置：一个进程在多个本地端口监听 SOCKS5
（默认从 127.0.0.1:1080 起，节点 i 对应 base+i），各自转发至对应远程节点。

用法:
    VLESS_URLS='["vless://...", "vless://..."]' python scripts/setup_xray.py
    VLESS_URL="vless://..." python scripts/setup_xray.py
"""

import json
import os
import sys
from urllib.parse import parse_qs, unquote, urlparse

# Windows 控制台/管道默认可能使用 GBK 编码，无法打印 emoji，强制 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

# Xray 配置输出路径
OUTPUT_PATH = "xray_config.json"

# Reality 协议必须的 URL 参数
REALITY_REQUIRED_PARAMS = ("pbk", "fp", "sni", "sid")

# 支持的 security
ALLOWED_SECURITY = ("reality", "tls", "none")

# 支持的传输类型
ALLOWED_NETWORK_TYPES = ("tcp", "ws", "grpc")


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

    if security not in ALLOWED_SECURITY:
        raise ValueError(
            f"security 必须为 {'/'.join(ALLOWED_SECURITY)}，实际为: {security or '<empty>'}"
        )

    if network not in ALLOWED_NETWORK_TYPES:
        raise ValueError(f"不支持的传输类型: {network}（仅支持 {', '.join(ALLOWED_NETWORK_TYPES)}）")

    result: dict = {
        "uuid": uuid,
        "host": host,
        "port": port,
        "network": network,
        "security": security,
    }

    if security == "reality":
        for key in REALITY_REQUIRED_PARAMS:
            value = _get_single(params, key)
            if not value:
                raise ValueError(f"缺少 Reality 必须参数: {key}")
            result[key] = value
        spx = _get_single(params, "spx")
        if spx:
            result["spx"] = unquote(spx)
    elif security == "tls":
        # TLS: sni/fp 可选；alpn/allowInsecure 可选
        sni = _get_single(params, "sni") or _get_single(params, "peer")
        if sni:
            result["sni"] = sni
        fp = _get_single(params, "fp")
        if fp:
            result["fp"] = fp
        alpn = _get_single(params, "alpn")
        if alpn:
            result["alpn"] = [x for x in unquote(alpn).split(",") if x]
        result["allowInsecure"] = _get_single(params, "allowInsecure") in ("1", "true")
    # security == "none": 纯 VLESS，无 TLS/Reality 层，不需要额外参数

    # 传输层可选参数
    if network == "ws":
        path = _get_single(params, "path")
        if path:
            result["ws_path"] = unquote(path)
        ws_host = _get_single(params, "host")
        if ws_host:
            result["ws_host"] = ws_host
    elif network == "grpc":
        service_name = _get_single(params, "serviceName") or _get_single(params, "servicename")
        if service_name:
            result["grpc_service_name"] = unquote(service_name)

    flow = _get_single(params, "flow")
    if flow:
        result["flow"] = flow

    return result


def _build_stream_settings(vless: dict) -> dict:
    """根据解析结果生成 streamSettings（Reality/TLS/none + ws/grpc 传输）。"""
    stream_settings: dict = {
        "network": vless["network"],
        "security": vless["security"],
    }

    if vless["security"] == "reality":
        reality_settings: dict = {
            "publicKey": vless["pbk"],
            "fingerprint": vless["fp"],
            "serverName": vless["sni"],
            "shortId": vless["sid"],
        }
        if "spx" in vless:
            reality_settings["spiderX"] = vless["spx"]
        stream_settings["realitySettings"] = reality_settings
    elif vless["security"] == "tls":
        tls_settings: dict = {}
        if "sni" in vless:
            tls_settings["serverName"] = vless["sni"]
        if "fp" in vless:
            tls_settings["fingerprint"] = vless["fp"]
        if "alpn" in vless:
            tls_settings["alpn"] = vless["alpn"]
        if vless.get("allowInsecure"):
            tls_settings["allowInsecure"] = True
        stream_settings["tlsSettings"] = tls_settings
    # security == "none": 纯 VLESS，无传输层加密设置
    # stream_settings 已含 "security": "none"，Xray 会按无加密处理

    if vless["network"] == "ws":
        ws_settings: dict = {}
        if "ws_path" in vless:
            ws_settings["path"] = vless["ws_path"]
        if "ws_host" in vless:
            ws_settings["headers"] = {"Host": vless["ws_host"]}
        stream_settings["wsSettings"] = ws_settings
    elif vless["network"] == "grpc":
        grpc_settings: dict = {}
        if "grpc_service_name" in vless:
            grpc_settings["serviceName"] = vless["grpc_service_name"]
        stream_settings["grpcSettings"] = grpc_settings

    return stream_settings


def build_outbound(vless: dict, tag: str) -> dict:
    """根据解析结果生成单个 VLESS outbound 配置。

    Args:
        vless: parse_vless_url() 的返回值
        tag: outbound 标签（如 "out-0"）

    Returns:
        outbound 配置字典
    """
    user_obj: dict = {"id": vless["uuid"], "encryption": "none"}
    if "flow" in vless:
        user_obj["flow"] = vless["flow"]

    return {
        "tag": tag,
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
        "streamSettings": _build_stream_settings(vless),
    }


def build_multi_xray_config(vless_list: list[dict], base_port: int) -> dict:
    """根据多个解析结果生成单一 Xray JSON 配置（一个进程监听多个端口）。

    Args:
        vless_list: parse_vless_url() 返回值列表
        base_port: 基准本地 SOCKS5 端口，节点 i 对应端口 base_port + i

    Returns:
        Xray 配置字典
    """
    n = len(vless_list)
    inbounds = [
        {
            "listen": "127.0.0.1",
            "port": base_port + i,
            "protocol": "socks",
            "tag": f"in-{i}",
            "settings": {"udp": True},
        }
        for i in range(n)
    ]
    outbounds = [
        build_outbound(vless, f"out-{i}") for i, vless in enumerate(vless_list)
    ]
    routing_rules = [
        {"type": "field", "inboundTag": [f"in-{i}"], "outboundTag": f"out-{i}"}
        for i in range(n)
    ]

    return {
        "log": {
            "loglevel": "warning",
            "access": "xray_access.log",
            "error": "xray_error.log",
        },
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": {"rules": routing_rules},
    }


def build_xray_config(vless: dict, socks_port: int) -> dict:
    """根据单个解析结果生成 Xray JSON 配置（单节点兼容入口）。

    Args:
        vless: parse_vless_url() 的返回值
        socks_port: 本地 SOCKS5 监听端口

    Returns:
        Xray 配置字典
    """
    return build_multi_xray_config([vless], socks_port)


def _load_vless_urls() -> list[str] | None:
    """读取 VLESS URL 列表。

    优先读 VLESS_URLS（JSON 数组字符串）；若未设置/为空/解析失败，
    回退读 VLESS_URL（单个链接，保持原有行为）。两者皆无返回 None。

    Returns:
        URL 字符串列表；无法获得任何 URL 时返回 None
    """
    urls_json = os.getenv("VLESS_URLS", "").strip()
    if urls_json:
        try:
            parsed = json.loads(urls_json)
        except json.JSONDecodeError:
            print(
                f"WARNING: VLESS_URLS 不是合法 JSON，忽略并回退 VLESS_URL: {urls_json}"
            )
        else:
            if isinstance(parsed, list) and parsed and all(
                isinstance(u, str) and u.strip() for u in parsed
            ):
                return [u.strip() for u in parsed]
            print(
                f"WARNING: VLESS_URLS 必须是非空 JSON 数组（元素为非空字符串），"
                f"忽略并回退 VLESS_URL: {urls_json}"
            )

    vless_url = os.getenv("VLESS_URL", "").strip()
    if vless_url:
        return [vless_url]

    return None


def main() -> int:
    vless_urls = _load_vless_urls()
    if vless_urls is None:
        print("ERROR: 环境变量 VLESS_URLS（JSON 数组）和 VLESS_URL 均未设置或为空")
        return 1

    # 解析所有 VLESS URL（任何一个失败即整体失败，不允许部分成功）
    vless_list: list[dict] = []
    for i, url in enumerate(vless_urls):
        try:
            vless = parse_vless_url(url)
        except ValueError as exc:
            print(f"ERROR: 第 {i} 个 VLESS URL 解析失败 — {exc}")
            return 1
        vless_list.append(vless)

    # SOCKS5 基准端口（节点 i 使用 base_port + i）
    socks_port_str = os.getenv("SOCKS_PORT", "1080").strip()
    try:
        base_port = int(socks_port_str)
        if not 1 <= base_port <= 65535:
            raise ValueError("port out of range")
    except ValueError:
        print(f"ERROR: 无效的 SOCKS_PORT: {socks_port_str}")
        return 1

    # 生成单一配置（一个进程监听多个端口）
    config = build_multi_xray_config(vless_list, base_port)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    # 逐节点输出日志
    for i, vless in enumerate(vless_list):
        print(
            f"✅ 节点{i}: {vless['host']}:{vless['port']} ({vless['security']}) "
            f"-> 本地 SOCKS5 127.0.0.1:{base_port + i}"
        )

    print(f"Xray 配置已写入: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
