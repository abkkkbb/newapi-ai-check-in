#!/usr/bin/env python3
"""
Topup 工具函数 - 简单封装充值功能
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from curl_cffi import requests as curl_requests

from utils.http_utils import proxy_resolve, response_resolve

if TYPE_CHECKING:
    from utils.config import AccountConfig, ProviderConfig


def topup(
    provider_config: "ProviderConfig",
    account_config: "AccountConfig",
    headers: dict,
    cookies: dict,
    key: str,
    impersonate: str = "firefox135",
) -> dict:
    """执行充值请求

    Args:
        provider_config: Provider 配置
        account_config: 账号配置
        headers: 请求头
        cookies: cookies 字典
        key: 充值密钥
        impersonate: curl_cffi 浏览器指纹模拟，默认为 "firefox135"

    Returns:
        包含 success 和 message 或 error 的字典
    """
    account_name = account_config.get_display_name()
    # 代理优先级: 账号配置 > 全局配置
    proxy_config = account_config.proxy or account_config.get("global_proxy")
    http_proxy = proxy_resolve(proxy_config)
    
    # 获取 topup URL
    topup_url = provider_config.get_topup_url()
    if not topup_url:
        print(f"❌ {account_name}: No topup URL configured")
        return {
            "success": False,
            "error": "No topup URL configured",
        }
    
    session = curl_requests.Session(impersonate=impersonate, proxy=http_proxy, timeout=30)
    try:
        # 设置 cookies
        session.cookies.update(cookies)

        # 构建 topup 请求头
        topup_headers = headers.copy()
        topup_headers.update({
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        })

        response = session.post(
            topup_url,
            headers=topup_headers,
            json={"key": key},
            timeout=30,
        )

        if response.status_code in [200, 400]:
            json_data = response_resolve(response, "topup", account_name)
            if json_data is None:
                return {
                    "success": False,
                    "error": "Failed to topup: Invalid response type (saved to logs)",
                }

            if json_data.get("success"):
                message = json_data.get("message", "Topup successful")
                data = json_data.get("data")
                print(f"✅ {account_name}: Topup successful - {message}, data: {data}")
                return {
                    "success": True,
                    "message": message,
                    "data": data,
                }
            else:
                error_msg = json_data.get("message", "Unknown error")
                # 检查是否是已使用的情况
                if "已被使用" in error_msg or "already" in error_msg.lower() or "已使用" in error_msg:
                    print(f"✅ {account_name}: Code already used - {error_msg}")
                    return {
                        "success": True,
                        "message": error_msg,
                        "already_used": True,
                    }
                print(f"❌ {account_name}: Topup failed - {error_msg}")
                return {
                    "success": False,
                    "error": f"Topup failed: {error_msg}(key: {key})",
                }
        else:
            print(f"❌ {account_name}: Topup failed - HTTP {response.status_code}")
            return {
                "success": False,
                "error": f"Topup failed: HTTP {response.status_code}(key: {key})",
            }
    except Exception as e:
        print(f"❌ {account_name}: Topup error - {e}")
        return {
            "success": False,
            "error": f"Topup failed: {e}(key: {key})",
        }
    finally:
        session.close()