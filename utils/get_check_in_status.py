#!/usr/bin/env python3
"""
签到状态查询模块

提供各种签到状态查询函数
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from curl_cffi import requests as curl_requests

from utils.http_utils import proxy_resolve, response_resolve

if TYPE_CHECKING:
    from utils.config import AccountConfig, ProviderConfig


def get_newapi_check_in_status(
    provider_config: "ProviderConfig",
    account_config: "AccountConfig",
    cookies: dict,
    headers: dict,
    path: str = "/api/user/checkin",
    impersonate: str = "firefox135",
) -> bool:
    """
    查询标准 newapi 签到状态，自动拼接当前月份

    Args:
        provider_config: Provider 配置
        account_config: 账号配置
        cookies: cookies 字典
        headers: 请求头字典
        path: 签到状态接口路径，默认为 "/api/user/checkin"
        impersonate: curl_cffi 浏览器指纹模拟，默认为 "firefox135"

    Returns:
        bool: 今日是否已签到
    """
    account_name = account_config.get_display_name()
    # 代理优先级: 账号配置 > 全局配置
    proxy_config = account_config.proxy or account_config.get("global_proxy")
    http_proxy = proxy_resolve(proxy_config)
    
    current_month = datetime.now().strftime("%Y-%m")
    check_in_status_url = f"{provider_config.origin}{path}?month={current_month}"

    print(f"🔍 {account_name}: Getting check-in status")

    try:
        session = curl_requests.Session(impersonate=impersonate, proxy=http_proxy, timeout=30)
        try:
            session.cookies.update(cookies)
            response = session.get(
                check_in_status_url,
                headers=headers,
                timeout=30,
            )

            if response.status_code == 200:
                json_data = response_resolve(response, "get_check_in_status", account_name)
                if json_data is None:
                    print(f"❌ {account_name}: Invalid response format for check-in status")
                    return False

                if json_data.get("success"):
                    status_data = json_data.get("data", {})
                    stats = status_data.get("stats", {})

                    checked_in_today = stats.get("checked_in_today", False)
                    checkin_count = stats.get("checkin_count", 0)
                    total_quota = stats.get("total_quota", 0)

                    total_quota_display = round(total_quota / 500000, 2) if total_quota else 0

                    print(
                        f"📊 {account_name}: Check-in status - "
                        f"Today: {'✅' if checked_in_today else '❌'}, "
                        f"Count: {checkin_count}, "
                        f"Total quota: ${total_quota_display}"
                    )

                    return checked_in_today
                else:
                    error_msg = json_data.get("message", "Unknown error")
                    print(f"❌ {account_name}: Failed to get check-in status: {error_msg}")
                    return False
            else:
                print(f"❌ {account_name}: Failed to get check-in status: HTTP {response.status_code}")
                return False
        finally:
            session.close()
    except Exception as e:
        print(f"❌ {account_name}: Error getting check-in status: {e}")
        return False


def create_newapi_check_in_status(
    path: str = "/api/user/checkin",
    impersonate: str = "firefox135",
):
    """
    创建一个标准 newapi 签到状态查询函数

    用于 ProviderConfig 的 check_in_status 配置

    Args:
        path: 签到状态接口路径，默认为 "/api/user/checkin"
        impersonate: curl_cffi 浏览器指纹模拟，默认为 "firefox135"

    Returns:
        Callable: 签到状态查询函数，签名为 (provider_config, account_config, cookies, headers) -> bool
    """

    def _check_status(
        provider_config: "ProviderConfig",
        account_config: "AccountConfig",
        cookies: dict,
        headers: dict,
    ) -> bool:
        return get_newapi_check_in_status(
            provider_config=provider_config,
            account_config=account_config,
            cookies=cookies,
            headers=headers,
            path=path,
            impersonate=impersonate,
        )

    return _check_status


# 预定义的标准 newapi 签到状态查询函数
newapi_check_in_status = create_newapi_check_in_status()