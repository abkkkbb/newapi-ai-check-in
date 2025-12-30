#!/usr/bin/env python3
"""
Topup 工具函数 - 简单封装充值功能
"""

import httpx

from utils.http_utils import response_resolve


def topup(
    account_name: str,
    topup_url: str,
    headers: dict,
    cookies: dict,
    key: str,
    proxy: httpx.URL | None = None,
) -> dict:
    """执行充值请求

    Args:
        account_name: 账号名称（用于日志）
        topup_url: 充值 API URL
        headers: 请求头
        cookies: cookies 字典
        key: 充值密钥
        proxy: 代理配置（可选）

    Returns:
        包含 success 和 message 或 error 的字典
    """
    client = httpx.Client(http2=True, timeout=30.0, proxy=proxy)
    try:
        # 设置 cookies
        client.cookies.update(cookies)

        # 构建 topup 请求头
        topup_headers = headers.copy()
        topup_headers.update({
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        })

        response = client.post(
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
        client.close()