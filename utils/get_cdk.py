#!/usr/bin/env python3
"""
CDK 获取模块

提供各个 provider 的 CDK 获取函数
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from utils.http_utils import proxy_resolve, response_resolve

if TYPE_CHECKING:
    from utils.config import AccountConfig


def get_runawaytime_checkin_cdk(account_config: "AccountConfig") -> str | None:
    """获取 runawaytime 签到 CDK
    
    通过 fuli.hxi.me 签到获取 CDK
    
    Args:
        account_config: 账号配置对象，需要包含 fuli_cookies 在 extra 中
    
    Returns:
        str | None: CDK 字符串，如果获取失败则返回 None
    """
    account_name = account_config.get_display_name()
    fuli_cookies = account_config.get("fuli_cookies")
    proxy = account_config.proxy or account_config.get("global_proxy")
    
    if not fuli_cookies:
        print(f"❌ {account_name}: fuli_cookies not found in account config")
        return None
    
    http_proxy = proxy_resolve(proxy)
    
    try:
        client = httpx.Client(http2=False, timeout=30.0, proxy=http_proxy)
        try:
            # 构建基础请求头
            headers = {
                "accept": "*/*",
                "accept-language": "en,en-US;q=0.9,zh;q=0.8",
                "cache-control": "no-cache",
                "pragma": "no-cache",
                "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
            }
            
            # 设置 cookies
            client.cookies.update(fuli_cookies)
            client.cookies.set("i18next", "en")
            
            # 先检查签到状态
            status_headers = headers.copy()
            status_headers.update({
                "referer": "https://fuli.hxi.me/",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            })
            
            status_response = client.get(
                "https://fuli.hxi.me/api/checkin/status",
                headers=status_headers,
                timeout=30
            )
            
            if status_response.status_code == 200:
                status_data = response_resolve(status_response, "get_checkin_status", account_name)
                if status_data and status_data.get("checked"):
                    print(f"✅ {account_name}: Already checked in today")
                    return None  # 已签到，无需再次签到
            
            # 执行签到
            checkin_headers = headers.copy()
            checkin_headers.update({
                "content-length": "0",
                "origin": "https://fuli.hxi.me",
                "referer": "https://fuli.hxi.me/",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            })
            
            response = client.post(
                "https://fuli.hxi.me/api/checkin",
                headers=checkin_headers,
                timeout=30
            )
            
            if response.status_code in [200, 400]:
                json_data = response_resolve(response, "execute_checkin", account_name)
                if json_data is None:
                    return None
                
                if json_data.get("success"):
                    code = json_data.get("code", "")
                    if code:
                        print(f"✅ {account_name}: Checkin successful! Code: {code}")
                        return code
                
                message = json_data.get("message", json_data.get("msg", ""))
                if "already" in message.lower() or "已经" in message or "已签" in message:
                    print(f"✅ {account_name}: Already checked in today")
                    return None
                
                print(f"❌ {account_name}: Checkin failed - {message}")
            
            return None
        finally:
            client.close()
    except Exception as e:
        print(f"❌ {account_name}: Error getting runawaytime checkin CDK - {e}")
        return None


def get_runawaytime_wheel_cdk(account_config: "AccountConfig") -> list[str] | None:
    """获取 runawaytime 大转盘 CDK
    
    通过 fuli.hxi.me 大转盘获取 CDK，支持多次转盘
    
    Args:
        account_config: 账号配置对象，需要包含 fuli_cookies 在 extra 中
    
    Returns:
        list[str] | None: CDK 字符串列表，如果获取失败则返回 None
    """
    account_name = account_config.get_display_name()
    fuli_cookies = account_config.get("fuli_cookies")
    proxy = account_config.proxy or account_config.get("global_proxy")
    
    if not fuli_cookies:
        print(f"❌ {account_name}: fuli_cookies not found in account config")
        return None
    
    http_proxy = proxy_resolve(proxy)
    cdks: list[str] = []
    
    try:
        client = httpx.Client(http2=False, timeout=30.0, proxy=http_proxy)
        try:
            # 构建基础请求头
            headers = {
                "accept": "*/*",
                "accept-language": "en,en-US;q=0.9,zh;q=0.8",
                "cache-control": "no-cache",
                "pragma": "no-cache",
                "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
            }
            
            # 设置 cookies
            client.cookies.update(fuli_cookies)
            client.cookies.set("i18next", "en")
            
            # 先检查大转盘状态
            status_headers = headers.copy()
            status_headers.update({
                "referer": "https://fuli.hxi.me/wheel",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            })
            
            status_response = client.get(
                "https://fuli.hxi.me/api/wheel/status",
                headers=status_headers,
                timeout=30
            )
            
            remaining = 0
            if status_response.status_code == 200:
                status_data = response_resolve(status_response, "get_wheel_status", account_name)
                if status_data:
                    remaining = status_data.get("remaining", 0)
                    if remaining <= 0:
                        print(f"ℹ️ {account_name}: No wheel spins remaining")
                        return None
                    print(f"ℹ️ {account_name}: {remaining} wheel spin(s) remaining")
            
            # 执行大转盘（循环直到 remaining <= 0）
            wheel_headers = headers.copy()
            wheel_headers.update({
                "content-length": "0",
                "origin": "https://fuli.hxi.me",
                "referer": "https://fuli.hxi.me/wheel",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            })
            
            spin_count = 0
            
            while remaining > 0:
                response = client.post(
                    "https://fuli.hxi.me/api/wheel",
                    headers=wheel_headers,
                    timeout=30
                )
                
                if response.status_code in [200, 400]:
                    json_data = response_resolve(response, "execute_wheel", account_name)
                    if json_data is None:
                        break
                    
                    if json_data.get("success"):
                        code = json_data.get("code", "")
                        # 从响应中更新 remaining
                        remaining = json_data.get("remaining", remaining - 1)
                        if code:
                            spin_count += 1
                            print(f"✅ {account_name}: Wheel spin #{spin_count} successful! Code: {code}, remaining: {remaining}")
                            cdks.append(code)
                            continue
                    
                    message = json_data.get("message", json_data.get("msg", ""))
                    if "already" in message.lower() or "已经" in message or "次数" in message or "no more" in message.lower():
                        print(f"ℹ️ {account_name}: No more wheel spins remaining")
                        break
                    
                    print(f"❌ {account_name}: Wheel spin #{spin_count + 1} failed - {message}")
                    break
                else:
                    break
            
            if cdks:
                print(f"✅ {account_name}: Total {len(cdks)} CDK(s) obtained from wheel")
                return cdks
            
            return None
        finally:
            client.close()
    except Exception as e:
        print(f"❌ {account_name}: Error getting runawaytime wheel CDK - {e}")
        return cdks if cdks else None


def get_x666_cdk(account_config: "AccountConfig") -> str | None:
    """获取 x666 抽奖 CDK
    
    通过 qd.x666.me 抽奖获取 CDK
    
    Args:
        account_config: 账号配置对象，需要包含 access_token 在 extra 中
    
    Returns:
        str | None: CDK 字符串，如果获取失败则返回 None
    """
    account_name = account_config.get_display_name()
    access_token = account_config.get("access_token")
    proxy = account_config.proxy or account_config.get("global_proxy")
    
    if not access_token:
        print(f"❌ {account_name}: access_token not found in account config")
        return None
    
    http_proxy = proxy_resolve(proxy)
    
    try:
        client = httpx.Client(http2=False, timeout=30.0, proxy=http_proxy)
        try:
            # 构建基础请求头
            headers = {
                "accept": "*/*",
                "accept-language": "en,en-US;q=0.9,zh;q=0.8",
                "cache-control": "no-cache",
                "pragma": "no-cache",
                "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
            }
            
            client.cookies.set("i18next", "en")
            
            # 先获取用户信息，检查是否可以抽奖
            info_headers = headers.copy()
            info_headers.update({
                "authorization": f"Bearer {access_token}",
                "content-length": "0",
                "content-type": "application/json",
                "origin": "https://qd.x666.me",
                "referer": "https://qd.x666.me/",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            })
            
            info_response = client.post(
                "https://qd.x666.me/api/user/info",
                headers=info_headers,
                timeout=30
            )
            
            if info_response.status_code == 200:
                info_data = response_resolve(info_response, "get_user_info", account_name)
                if info_data and info_data.get("success"):
                    data = info_data.get("data", {})
                    can_spin = data.get("can_spin", False)
                    
                    if not can_spin:
                        # 今天已经抽过，返回已有的 CDK
                        today_record = data.get("today_record")
                        if today_record:
                            existing_cdk = today_record.get("cdk", "")
                            if existing_cdk:
                                print(f"✅ {account_name}: Already spun today, existing CDK: {existing_cdk}")
                                return existing_cdk
                        print(f"ℹ️ {account_name}: Already spun today, no CDK available")
                        return None
            
            # 执行抽奖
            spin_headers = headers.copy()
            spin_headers.update({
                "authorization": f"Bearer {access_token}",
                "content-length": "0",
                "content-type": "application/json",
                "origin": "https://qd.x666.me",
                "referer": "https://qd.x666.me/",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            })
            
            response = client.post(
                "https://qd.x666.me/api/lottery/spin",
                headers=spin_headers,
                timeout=30
            )
            
            if response.status_code in [200, 400]:
                json_data = response_resolve(response, "execute_spin", account_name)
                if json_data is None:
                    return None
                
                if json_data.get("success"):
                    data = json_data.get("data", {})
                    cdk = data.get("cdk", "")
                    if cdk:
                        label = data.get("label", "Unknown")
                        print(f"✅ {account_name}: Spin successful! Prize: {label}, CDK: {cdk}")
                        return cdk
                
                message = json_data.get("message", json_data.get("msg", ""))
                if "already" in message.lower() or "已经" in message or "已抽" in message:
                    print(f"✅ {account_name}: Already spun today")
                    return None
                
                print(f"❌ {account_name}: Spin failed - {message}")
            
            return None
        finally:
            client.close()
    except Exception as e:
        print(f"❌ {account_name}: Error getting x666 CDK - {e}")
        return None