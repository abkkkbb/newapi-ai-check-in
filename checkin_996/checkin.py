#!/usr/bin/env python3
"""
CheckIn 类 for 996 hub
"""

import sys
from pathlib import Path

from curl_cffi import requests as curl_requests

# Add parent directory to Python path to find utils module
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.http_utils import proxy_resolve, response_resolve


class CheckIn:
    """996 hub 签到管理类"""

    def __init__(
        self,
        account_name: str,
        global_proxy: dict | None = None,
    ):
        """初始化签到管理器

        Args:
            account_name: 账号名称
            global_proxy: 全局代理配置(可选)
        """
        self.account_name = account_name
        self.safe_account_name = "".join(c if c.isalnum() else "_" for c in account_name)
        self.global_proxy = global_proxy
        self.http_proxy_config = proxy_resolve(global_proxy)

    def execute_check_in(self, session: curl_requests.Session, headers: dict, auth_token: str) -> tuple[bool, str]:
        """执行签到请求

        Args:
            session: curl_cffi Session 客户端
            headers: 请求头
            auth_token: Bearer token

        Returns:
            (签到是否成功, 错误信息或成功信息)
        """
        print(f"🌐 {self.account_name}: Executing check-in")

        # 构建签到请求头
        checkin_headers = headers.copy()
        checkin_headers.update(
            {
                "authorization": f"Bearer {auth_token}",
                "origin": "https://hub.529961.com",
                "referer": "https://hub.529961.com/checkin",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            }
        )

        response = session.post("https://hub.529961.com/api/checkin", headers=checkin_headers, timeout=30)

        print(f"📨 {self.account_name}: Response status code {response.status_code}")

        # 尝试解析响应（200 或 400 都可能包含有效的 JSON）
        if response.status_code in [200, 400]:
            json_data = response_resolve(response, "execute_check_in", self.account_name)
            if json_data is None:
                print(f"❌ {self.account_name}: Check-in failed - Invalid response format")
                return False, "Invalid response format"

            # 检查签到结果
            message = json_data.get("message", json_data.get("msg", ""))

            # "今天已经签到过了" 也算成功
            if json_data.get("success") or json_data.get("code") == 0 or "已经签到" in message:
                if "已经签到" in message:
                    print(f"✅ {self.account_name}: Already checked in today!")
                else:
                    print(f"✅ {self.account_name}: Check-in successful!")
                return True, "Check-in successful"
            else:
                error_msg = message if message else "Unknown error"
                print(f"❌ {self.account_name}: Check-in failed - {error_msg}")
                return False, error_msg
        else:
            print(f"❌ {self.account_name}: Check-in failed - HTTP {response.status_code}")
            return False, f"HTTP error with code {response.status_code}"

    def get_checkin_info(self, session: curl_requests.Session, headers: dict, auth_token: str) -> dict | None:
        """获取签到信息

        Args:
            session: curl_cffi Session 客户端
            headers: 请求头
            auth_token: Bearer token

        Returns:
            签到信息字典，失败返回 None
        """
        print(f"ℹ️ {self.account_name}: Getting check-in info")

        # 构建请求头
        info_headers = headers.copy()
        info_headers.update(
            {
                "authorization": f"Bearer {auth_token}",
                "origin": "https://hub.529961.com",
                "referer": "https://hub.529961.com/checkin",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            }
        )

        try:
            response = session.get("https://hub.529961.com/api/checkin/info", headers=info_headers, timeout=30)

            print(f"📨 {self.account_name}: Response status code {response.status_code}")

            if response.status_code == 200:
                json_data = response_resolve(response, "get_checkin_info", self.account_name)
                if json_data and json_data.get("success"):
                    data = json_data.get("data", {})
                    print(f"✅ {self.account_name}: Got check-in info")
                    print(f"  📅 Has checked today: {data.get('has_checked_today', 'N/A')}")
                    print(f"  🔥 Continuous days: {data.get('continuous_days', 'N/A')}")
                    print(f"  📊 Total check-ins: {data.get('total_checkins', 'N/A')}")
                    print(f"  💰 Total rewards: ${data.get('total_rewards_usd', 'N/A')}")
                    return data
                else:
                    error_msg = json_data.get("message", "Unknown error") if json_data else "Invalid response"
                    print(f"❌ {self.account_name}: Failed to get check-in info: {error_msg}")
                    return None
            else:
                print(f"❌ {self.account_name}: Failed to get check-in info - HTTP {response.status_code}")
                return None
        except Exception as e:
            print(f"❌ {self.account_name}: Error getting check-in info: {e}")
            return None

    async def check_in_with_token(self, auth_token: str) -> tuple[bool, dict]:
        """使用 Bearer token 执行签到操作

        Args:
            auth_token: Bearer 认证 token

        Returns:
            (签到是否成功, 用户信息或错误信息)
        """
        print(
            f"ℹ️ {self.account_name}: Executing check-in with Bearer token (using proxy: {'true' if self.http_proxy_config else 'false'})"
        )

        # 使用 curl_cffi Session，模拟 Chrome 浏览器指纹
        session = curl_requests.Session(proxy=self.http_proxy_config, timeout=30)
        try:
            # 构建请求头
            headers = {
                "accept": "application/json, text/plain, */*",
                "accept-language": "en,en-US;q=0.9,zh;q=0.8,en-CN;q=0.7,zh-CN;q=0.6,am;q=0.5",
                "cache-control": "no-cache",
                "pragma": "no-cache",
                "priority": "u=1, i",
                "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
            }

            # 执行签到
            success, error_msg = self.execute_check_in(session, headers, auth_token)

            if success:
                user_info = self.get_checkin_info(session, headers, auth_token)
                if user_info is None:
                    return False, {"error": "Failed to retrieve user info after check-in"}
                return True, user_info
            else:
                return False, {"error": f"Check-in failed, {error_msg}"}

        except Exception as e:
            print(f"❌ {self.account_name}: Error occurred during check-in process - {e}")
            return False, {"error": f"Check-in process error: {str(e)}"}
        finally:
            session.close()

    async def execute(self, access_token: str) -> tuple[bool, dict]:
        """使用提供的 token 执行签到操作

        Args:
            access_token: Bearer 认证 token

        Returns:
            (签到是否成功, 用户信息或错误信息)
        """
        print(f"\n\n⏳ Starting to process {self.account_name}")

        # 执行签到
        print(f"\nℹ️ {self.account_name}: Trying token authentication")
        success, user_info = await self.check_in_with_token(access_token)

        if success:
            print(f"✅ {self.account_name}: Token authentication successful")
        else:
            print(f"❌ {self.account_name}: Token authentication failed")

        # 返回结果，包含签到信息
        result = user_info if user_info else {}

        return success, result
