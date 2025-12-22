#!/usr/bin/env python3
"""
CheckIn 类 for x666
"""

import json
import os
from datetime import datetime

import httpx


class CheckIn:
    """x666 签到管理类"""

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
        self.http_proxy_config = self._get_http_proxy(global_proxy)

    @staticmethod
    def _get_http_proxy(proxy_config: dict | None = None) -> httpx.URL | None:
        """将 proxy_config 转换为 httpx.URL 格式的代理 URL

        Args:
            proxy_config: 代理配置字典

        Returns:
            httpx.URL 格式的代理对象，如果没有配置代理则返回 None
        """
        if not proxy_config:
            return None

        proxy_url = proxy_config.get("server")
        if not proxy_url:
            return None

        username = proxy_config.get("username")
        password = proxy_config.get("password")

        if username and password:
            parsed = httpx.URL(proxy_url)
            return parsed.copy_with(username=username, password=password)

        return httpx.URL(proxy_url)

    def _check_and_handle_response(self, response: httpx.Response, context: str = "response") -> dict | None:
        """检查响应类型，如果是 HTML 则保存为文件，否则返回 JSON 数据

        Args:
            response: httpx Response 对象
            context: 上下文描述，用于生成文件名

        Returns:
            JSON 数据字典，如果响应是 HTML 则返回 None
        """
        # 创建 logs 目录
        logs_dir = "logs"
        os.makedirs(logs_dir, exist_ok=True)

        try:
            return response.json()
        except json.JSONDecodeError as e:
            print(f"❌ {self.account_name}: Failed to parse JSON response: {e}")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_context = "".join(c if c.isalnum() else "_" for c in context)

            content_type = response.headers.get("content-type", "").lower()

            if "text/html" in content_type or "text/plain" in content_type:
                filename = f"{self.safe_account_name}_{timestamp}_{safe_context}.html"
                filepath = os.path.join(logs_dir, filename)

                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(response.text)

                print(f"⚠️ {self.account_name}: Received HTML response, saved to: {filepath}")
            else:
                filename = f"{self.safe_account_name}_{timestamp}_{safe_context}_invalid.txt"
                filepath = os.path.join(logs_dir, filename)

                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(response.text)

                print(f"⚠️ {self.account_name}: Invalid response saved to: {filepath}")
            return None
        except Exception as e:
            print(f"❌ {self.account_name}: Error occurred while checking and handling response: {e}")
            return None

    def get_user_info(
        self, client: httpx.Client, headers: dict, auth_token: str
    ) -> tuple[bool, bool, str, float, float]:
        """获取用户信息，检查是否可以抽奖

        Args:
            client: httpx 客户端
            headers: 请求头
            auth_token: Bearer token

        Returns:
            (是否成功, can_spin, cdk, quota_amount, total_quota)
        """
        print(f"ℹ️ {self.account_name}: Getting user info")

        info_headers = headers.copy()
        info_headers.update(
            {
                "authorization": f"Bearer {auth_token}",
                "content-length": "0",
                "content-type": "application/json",
                "origin": "https://qd.x666.me",
                "referer": "https://qd.x666.me/",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            }
        )

        response = client.post(
            "https://qd.x666.me/api/user/info", headers=info_headers, timeout=30
        )

        print(f"📨 {self.account_name}: User info response status code {response.status_code}")

        if response.status_code == 200:
            json_data = self._check_and_handle_response(response, "get_user_info")
            if json_data is None:
                return False, False, "", 0, 0

            if json_data.get("success"):
                data = json_data.get("data", {})
                can_spin = data.get("can_spin", False)
                today_record = data.get("today_record")
                cdk = today_record.get("cdk", "") if today_record else ""
                quota_amount = today_record.get("quota_amount", 0) if today_record else 0

                user = data.get("user", {})
                username = user.get("username", "Unknown")
                total_quota = user.get("total_quota", 0)
                print(f"✅ {self.account_name}: User: {username}, Total Quota: {total_quota / 500}")
                print(f"ℹ️ {self.account_name}: Can spin: {can_spin}, CDK: {cdk}")
                return True, can_spin, cdk, quota_amount / 500, total_quota / 500

            return False, False, "", 0, 0
        return False, False, "", 0, 0

    def execute_spin(
        self, client: httpx.Client, headers: dict, auth_token: str
    ) -> tuple[bool, str, float]:
        """执行抽奖请求 (spin)

        Args:
            client: httpx 客户端
            headers: 请求头
            auth_token: Bearer token

        Returns:
            (是否成功, cdk, quota_amount)
        """
        print(f"🎰 {self.account_name}: Executing spin")

        # 构建请求头
        spin_headers = headers.copy()
        spin_headers.update(
            {
                "authorization": f"Bearer {auth_token}",
                "content-length": "0",
                "content-type": "application/json",
                "origin": "https://qd.x666.me",
                "referer": "https://qd.x666.me/",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            }
        )

        response = client.post(
            "https://qd.x666.me/api/lottery/spin", headers=spin_headers, timeout=30
        )

        print(f"📨 {self.account_name}: Spin response status code {response.status_code}")

        if response.status_code in [200, 400]:
            json_data = self._check_and_handle_response(response, "execute_spin")
            if json_data is None:
                print(f"❌ {self.account_name}: Spin failed - Invalid response format")
                return False, "", 0

            message = json_data.get("message", json_data.get("msg", ""))

            if json_data.get("success"):
                data = json_data.get("data", {})
                label = data.get("label", "Unknown")
                cdk = data.get("cdk", "")
                quota = data.get("quota", 0)
                print(f"✅ {self.account_name}: Spin successful! Prize: {label}, CDK: {cdk}")
                return True, cdk, quota / 500
            if "already" in message.lower() or "已经" in message or "已抽" in message:
                print(f"✅ {self.account_name}: Already spun today!")
                return True, "", 0
            error_msg = message if message else "Unknown error"
            print(f"❌ {self.account_name}: Spin failed - {error_msg}")
            return False, "", 0
        print(f"❌ {self.account_name}: Spin failed - HTTP {response.status_code}")
        return False, "", 0

    def execute_topup(
        self, client: httpx.Client, headers: dict, cookies: dict, api_user: str | int, cdk: str
    ) -> bool:
        """执行充值签到请求 (topup)

        Args:
            client: httpx 客户端
            headers: 请求头
            cookies: 用户 cookies
            api_user: API 用户 ID
            cdk: 从 spin 获取的 CDK

        Returns:
            充值签到是否成功
        """
        print(f"💰 {self.account_name}: Executing topup with CDK: {cdk}")

        # 设置 cookies
        client.cookies.update(cookies)

        # 构建请求头
        topup_headers = headers.copy()
        topup_headers.update(
            {
                "accept": "application/json, text/plain, */*",
                "content-type": "application/json",
                "cache-control": "no-store",
                "new-api-user": str(api_user),
                "origin": "https://x666.me",
                "referer": "https://x666.me/console/topup",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            }
        )

        payload = {"key": cdk}
        response = client.post(
            "https://x666.me/api/user/topup", headers=topup_headers, json=payload, timeout=30
        )

        print(f"📨 {self.account_name}: Topup response status code {response.status_code}")

        if response.status_code in [200, 400]:
            json_data = self._check_and_handle_response(response, "execute_topup")
            if json_data is None:
                print(f"❌ {self.account_name}: Topup failed - Invalid response format")
                return False

            message = json_data.get("message", json_data.get("msg", ""))

            if json_data.get("success") or json_data.get("code") == 0:
                print(f"✅ {self.account_name}: Topup successful!")
                return True
            elif "already" in message.lower() or "已被使用" in message:
                print(f"✅ {self.account_name}: Already claimed topup today!")
                return True
            else:
                error_msg = message if message else "Unknown error"
                print(f"❌ {self.account_name}: Topup failed - {error_msg}")
                return False
        else:
            print(f"❌ {self.account_name}: Topup failed - HTTP {response.status_code}")
            return False

    async def execute(
        self, access_token: str, cookies: dict, api_user: str | int
    ) -> tuple[bool, dict]:
        """执行完整签到流程：先 spin 再 topup

        Args:
            access_token: Bearer 认证 token (用于 spin)
            cookies: 用户 cookies (用于 topup)
            api_user: API 用户 ID (用于 topup)

        Returns:
            (签到是否成功, 结果信息)
        """
        print(f"\n\n⏳ Starting to process {self.account_name}")
        print(
            f"ℹ️ {self.account_name}: Executing check-in "
            f"(using proxy: {'true' if self.http_proxy_config else 'false'})"
        )

        client = httpx.Client(http2=False, timeout=30.0, proxy=self.http_proxy_config)
        try:
            # 构建基础请求头
            headers = {
                "accept": "*/*",
                "accept-language": "en,en-US;q=0.9,zh;q=0.8,en-CN;q=0.7,zh-CN;q=0.6,am;q=0.5",
                "cache-control": "no-cache",
                "pragma": "no-cache",
                "priority": "u=1, i",
                "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
            }

            # 设置 cookie
            client.cookies.set("i18next", "en")

            results = {"spin": False, "topup": False, "quota_amount": 0, "total_quota": 0}
            cdk = ""
            quota_amount = 0
            total_quota = 0

            # Step 1: 获取用户信息，检查是否可以抽奖
            info_success, can_spin, existing_cdk, existing_quota, total_quota = (
                self.get_user_info(client, headers, access_token)
            )

            if not info_success:
                print(f"❌ {self.account_name}: Failed to get user info")
                return False, {"error": "Failed to get user info"}

            results["total_quota"] = total_quota

            if can_spin:
                # Step 2: 执行 spin (使用 access_token)，获取 cdk
                spin_success, cdk, quota_amount = self.execute_spin(
                    client, headers, access_token
                )
                results["spin"] = spin_success
                results["quota_amount"] = quota_amount
                # spin 成功后，total_quota 需要加上新获得的 quota_amount
                if spin_success:
                    total_quota += quota_amount
                    results["total_quota"] = total_quota
            else:
                # 今天已经抽过，使用已有的 cdk
                print(f"✅ {self.account_name}: Already spun today, using existing CDK")
                results["spin"] = True
                cdk = existing_cdk
                quota_amount = existing_quota
                results["quota_amount"] = quota_amount

            # Step 3: 执行 topup (使用 cookies、api_user 和 cdk)
            if cdk:
                topup_success = self.execute_topup(client, headers, cookies, api_user, cdk)
                results["topup"] = topup_success
            else:
                print(f"⚠️ {self.account_name}: No CDK available, skipping topup")
                results["topup"] = True  # 没有 CDK 时跳过，不算失败

            # 判断整体是否成功
            overall_success = results["spin"] and results["topup"]

            if overall_success:
                print(
                    f"✅ {self.account_name}: Check-in completed, "
                    f"Quota: {quota_amount}, Total: {total_quota}"
                )
            else:
                failed_tasks = []
                if not results["spin"]:
                    failed_tasks.append("spin")
                if not results["topup"]:
                    failed_tasks.append("topup")
                print(f"⚠️ {self.account_name}: Some tasks failed: {', '.join(failed_tasks)}")

            return overall_success, results

        except Exception as e:
            print(f"❌ {self.account_name}: Error occurred during check-in process - {e}")
            return False, {"error": f"Check-in process error: {str(e)}"}
        finally:
            client.close()
