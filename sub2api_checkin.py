#!/usr/bin/env python3
"""
Sub2API 自动签到模块

独立于 newapi 签到流程，专门处理 Sub2API 站点的：
  - JWT refresh token 旋转续期
  - 签到接口探测（多路由降级）
  - 余额查询
  - token 持久化（cache 文件，供 GitHub Actions cache 步骤保存）

接口路径参考 all-api-hub 项目验证过的实现：
  - refresh:  POST /api/v1/auth/refresh
  - 签到:     POST /api/v1/check-in（404 降级 /api/v1/redeem/checkin）
  - 签到状态: GET  /api/v1/check-in/status（404 降级 /api/v1/redeem/checkin/status）
  - 用户信息: GET  /api/v1/auth/me
"""

import json
import os
import time
from pathlib import Path

from curl_cffi import requests as curl_requests

# 签到路由候选（按探测顺序）
# 和 all-api-hub 的 SUB2API_CHECKIN_ROUTES 保持一致
SUB2API_CHECKIN_ROUTES = [
    {"status": "/api/v1/check-in/status", "checkin": "/api/v1/check-in"},
    {"status": "/api/v1/redeem/checkin/status", "checkin": "/api/v1/redeem/checkin"},
]

# 表示路由不存在的 HTTP 状态码
MISSING_ROUTE_STATUS_CODES = {404, 405}

# 重复签到的 HTTP 状态码
ALREADY_CHECKED_STATUS_CODE = 409

ALREADY_CHECKED_SNIPPETS = [
    "已签到",
    "已经签到",
    "重复签到",
    "already checked",
    "already check",
]

# token 缓存目录
TOKEN_CACHE_DIR = os.environ.get("SUB2API_TOKEN_CACHE_DIR", "sub2api-tokens")


class Sub2ApiCheckIn:
    """Sub2API 站点签到管理器"""

    def __init__(self, site_config: dict, token_cache_dir: str = TOKEN_CACHE_DIR):
        """
        Args:
            site_config: 站点配置字典，包含 name/origin/refresh_token
            token_cache_dir: token 缓存目录路径
        """
        self.name = site_config.get("name", "sub2api")
        self.origin = site_config["origin"].rstrip("/")
        self.initial_refresh_token = site_config.get("refresh_token", "").strip()
        self.token_cache_dir = token_cache_dir
        self.proxy = site_config.get("proxy")

        os.makedirs(self.token_cache_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # token 缓存持久化
    # ------------------------------------------------------------------

    @property
    def _cache_file(self) -> Path:
        """缓存文件路径，用 name 做文件名"""
        safe_name = "".join(c if c.isalnum() else "_" for c in self.name)
        return Path(self.token_cache_dir) / f"{safe_name}.json"

    def _load_cached_token(self) -> dict | None:
        """从缓存文件读取上次的 token 对"""
        try:
            if self._cache_file.exists():
                data = json.loads(self._cache_file.read_text(encoding="utf-8"))
                if data.get("refresh_token"):
                    return data
        except Exception as e:
            print(f"⚠️ {self.name}: 读取 token 缓存失败: {e}")
        return None

    def _save_cached_token(self, access_token: str, refresh_token: str, expires_at: float) -> None:
        """把旋转后的新 token 对写入缓存文件"""
        try:
            self._cache_file.write_text(
                json.dumps(
                    {
                        "access_token": access_token,
                        "refresh_token": refresh_token,
                        "expires_at": expires_at,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            print(f"✅ {self.name}: token 缓存已更新")
        except Exception as e:
            print(f"⚠️ {self.name}: 写入 token 缓存失败: {e}")

    def _resolve_refresh_token(self) -> str:
        """
        解析本次签到用的 refresh token：
          优先用缓存文件里的（旋转后的最新值），没有再用环境变量初始值
        """
        cached = self._load_cached_token()
        if cached and cached.get("refresh_token"):
            print(f"ℹ️ {self.name}: 使用缓存中的 refresh token")
            return cached["refresh_token"]

        if self.initial_refresh_token:
            print(f"ℹ️ {self.name}: 使用初始 refresh token（首次运行或缓存丢失）")
            return self.initial_refresh_token

        raise ValueError(f"{self.name}: 没有可用的 refresh token")

    # ------------------------------------------------------------------
    # HTTP 请求
    # ------------------------------------------------------------------

    def _create_session(self) -> curl_requests.Session:
        """创建 curl_cffi Session"""
        proxy_config = None
        if self.proxy:
            if isinstance(self.proxy, dict):
                server = self.proxy.get("server", "")
                if server:
                    proxy_config = server
            elif isinstance(self.proxy, str):
                proxy_config = self.proxy

        session = curl_requests.Session(
            impersonate="firefox135",
            proxy=proxy_config,
            timeout=30,
        )
        return session

    def _post_json(self, session: curl_requests.Session, url: str, body: dict, headers: dict) -> dict:
        """POST JSON 请求，返回解析后的 JSON"""
        response = session.post(url, headers=headers, json=body, timeout=30)
        return self._parse_response(response, url)

    def _get_json(self, session: curl_requests.Session, url: str, headers: dict) -> dict:
        """GET 请求，返回解析后的 JSON"""
        response = session.get(url, headers=headers, timeout=30)
        return self._parse_response(response, url)

    def _parse_response(self, response, url: str) -> dict:
        """解析响应，Sub2API 统一格式 {code, message, data}"""
        status_code = response.status_code

        # 尝试解析 JSON
        try:
            data = response.json()
        except Exception:
            # 非 JSON 响应（可能是 HTML 错误页）
            text = response.text[:500] if response.text else ""
            raise RuntimeError(f"HTTP {status_code} 非 JSON 响应: {text}")

        # 把 HTTP 状态码和原始响应都带上，供调用方判断
        data["_http_status"] = status_code
        data["_url"] = url
        return data

    # ------------------------------------------------------------------
    # token 刷新
    # ------------------------------------------------------------------

    def _refresh_token(self, session: curl_requests.Session, refresh_token: str) -> dict:
        """
        调用 /api/v1/auth/refresh 刷新 token

        Returns:
            {"access_token": ..., "refresh_token": ..., "expires_in": ..., "expires_at": ...}
        """
        url = f"{self.origin}/api/v1/auth/refresh"
        print(f"🔄 {self.name}: 刷新 token...")

        body = self._post_json(session, url, {"refresh_token": refresh_token}, {"Content-Type": "application/json"})

        if body.get("code") != 0:
            msg = body.get("message", body.get("msg", "未知错误"))
            raise RuntimeError(f"refresh 失败: {msg} (HTTP {body.get('_http_status')})")

        token_data = body.get("data", {})
        access_token = (token_data.get("access_token") or "").strip()
        new_refresh_token = (token_data.get("refresh_token") or "").strip()
        expires_in = token_data.get("expires_in", 0)

        if not access_token or not new_refresh_token or not isinstance(expires_in, (int, float)) or expires_in <= 0:
            raise RuntimeError("refresh 响应缺少必要字段")

        expires_at = time.time() + expires_in

        print(f"✅ {self.name}: token 刷新成功，access_token 有效期 {expires_in} 秒")
        return {
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "expires_in": expires_in,
            "expires_at": expires_at,
        }

    # ------------------------------------------------------------------
    # 签到
    # ------------------------------------------------------------------

    def _is_already_checked(self, body: dict) -> bool:
        """判断是否已签到"""
        # HTTP 409
        if body.get("_http_status") == ALREADY_CHECKED_STATUS_CODE:
            return True

        # 消息匹配
        message = str(body.get("message", body.get("msg", ""))).lower()
        return any(snippet.lower() in message for snippet in ALREADY_CHECKED_SNIPPETS)

    def _is_missing_route(self, body: dict) -> bool:
        """判断是否路由不存在"""
        return body.get("_http_status") in MISSING_ROUTE_STATUS_CODES

    def _probe_checkin_route(self, session: curl_requests.Session, access_token: str) -> dict | None:
        """
        探测可用的签到路由，返回第一个存在的路由配置

        Returns:
            {"status": ..., "checkin": ...} 或 None（都不存在）
        """
        headers = self._auth_headers(access_token)

        for route in SUB2API_CHECKIN_ROUTES:
            status_url = f"{self.origin}{route['status']}"
            try:
                body = self._get_json(session, status_url, headers)
            except RuntimeError as e:
                # 非 JSON 响应，可能路由不存在
                print(f"⚠️ {self.name}: 探测 {route['status']} 失败: {e}")
                continue

            if self._is_missing_route(body):
                print(f"ℹ️ {self.name}: {route['status']} 不存在 (HTTP {body['_http_status']})，尝试下一个路由")
                continue

            # 路由存在（可能返回已签到或正常状态）
            print(f"✅ {self.name}: 使用签到路由 {route['checkin']}")
            return route

        return None

    def _check_in(self, session: curl_requests.Session, access_token: str) -> dict:
        """
        执行签到

        Returns:
            {"success": bool, "already_checked": bool, "message": str, "reward": str}
        """
        headers = self._auth_headers(access_token)
        headers["Content-Type"] = "application/json"

        route = self._probe_checkin_route(session, access_token)
        if not route:
            return {
                "success": False,
                "already_checked": False,
                "message": "签到接口不存在（所有候选路由均返回 404/405）",
                "reward": "",
            }

        # 先查签到状态
        status_url = f"{self.origin}{route['status']}"
        try:
            status_body = self._get_json(session, status_url, headers)
            if self._is_already_checked(status_body):
                msg = status_body.get("message", status_body.get("msg", "今日已签到"))
                print(f"ℹ️ {self.name}: 今日已签到，跳过")
                return {"success": True, "already_checked": True, "message": str(msg), "reward": ""}
        except RuntimeError:
            pass  # 状态查询失败，继续尝试签到

        # 执行签到
        checkin_url = f"{self.origin}{route['checkin']}"
        body = self._post_json(session, checkin_url, {}, headers)

        if self._is_already_checked(body):
            msg = body.get("message", body.get("msg", "今日已签到"))
            print(f"ℹ️ {self.name}: 签到接口返回已签到")
            return {"success": True, "already_checked": True, "message": str(msg), "reward": ""}

        if body.get("code") == 0 or body.get("success"):
            msg = body.get("message", body.get("msg", "签到成功"))
            reward = ""
            data = body.get("data", {})
            if isinstance(data, dict):
                for key in ("quota_awarded", "reward_amount", "reward", "amount", "credits_awarded"):
                    if key in data and data[key]:
                        reward = str(data[key])
                        break
            print(f"✅ {self.name}: 签到成功！{msg}")
            return {"success": True, "already_checked": False, "message": str(msg), "reward": reward}

        msg = body.get("message", body.get("msg", "签到失败"))
        print(f"❌ {self.name}: 签到失败 - {msg}")
        return {"success": False, "already_checked": False, "message": str(msg), "reward": ""}

    # ------------------------------------------------------------------
    # 余额查询
    # ------------------------------------------------------------------

    def _fetch_balance(self, session: curl_requests.Session, access_token: str) -> dict:
        """
        查询用户余额 GET /api/v1/auth/me

        Returns:
            {"success": bool, "quota": ..., "display": str}
        """
        headers = self._auth_headers(access_token)
        url = f"{self.origin}/api/v1/auth/me"

        try:
            body = self._get_json(session, url, headers)
        except RuntimeError as e:
            return {"success": False, "display": f"余额查询失败: {e}"}

        if body.get("code") != 0:
            msg = body.get("message", body.get("msg", "未知错误"))
            return {"success": False, "display": f"余额查询失败: {msg}"}

        data = body.get("data", {})
        if not isinstance(data, dict):
            return {"success": False, "display": "余额查询失败: 响应格式异常"}

        # Sub2API 不同部署返回值字段名不同：balance 或 quota
        # balance 通常是美元单位，不需要除 500000
        raw_balance = data.get("balance", data.get("quota", 0))
        if not isinstance(raw_balance, (int, float)):
            raw_balance = 0

        # 如果值大于 1e7（内部单位特征），才除以 500000 转美元
        if raw_balance > 1e7:
            balance_display = round(raw_balance / 500000, 2)
        else:
            balance_display = round(raw_balance, 2)

        email = data.get("email", "")
        display_name = data.get("username") or email.split("@")[0] if email else ""

        display = f"用户: {display_name}, 余额: ${balance_display}"
        print(f"💰 {self.name}: {display}")
        return {"success": True, "quota": balance_display, "display": display}

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _auth_headers(self, access_token: str) -> dict:
        """构造认证请求头"""
        return {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json, text/plain, */*",
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        }

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    async def execute(self) -> tuple[bool, dict]:
        """
        执行完整的签到流程：
          1. 读取 refresh token（缓存优先，初始值兜底）
          2. 调 /api/v1/auth/refresh 刷新 access token + 旋转 refresh token
          3. 探测签到路由 + 执行签到
          4. 查询余额
          5. 持久化旋转后的新 refresh token

        Returns:
            (success, user_info) 和 newapi 签到流程的返回格式一致
        """
        print(f"\n⏳ 开始处理 Sub2API 站点: {self.name}")

        session = self._create_session()

        try:
            # 1. 解析 refresh token
            refresh_token = self._resolve_refresh_token()

            # 2. 刷新 token（每次签到都 refresh，滚动续期 refresh token）
            try:
                refreshed = self._refresh_token(session, refresh_token)
            except RuntimeError as e:
                error_msg = f"refresh token 失败: {e}"
                print(f"❌ {self.name}: {error_msg}")
                print(f"💡 {self.name}: refresh token 可能已过期（30天），请重新从浏览器获取")
                return False, {"error": error_msg, "need_relogin": True}

            access_token = refreshed["access_token"]
            new_refresh_token = refreshed["refresh_token"]

            # 3. 签到
            checkin_result = self._check_in(session, access_token)

            # 4. 查余额（签到失败也尝试查余额，便于排查）
            balance_result = self._fetch_balance(session, access_token)

            # 5. 持久化新 token（无论签到成功与否，refresh 已经旋转了，必须保存）
            self._save_cached_token(
                access_token,
                new_refresh_token,
                refreshed["expires_at"],
            )

            # 汇总结果
            success = checkin_result["success"]
            parts = []
            if checkin_result["already_checked"]:
                parts.append("✅ 今日已签到")
            elif success:
                parts.append("✅ 签到成功")
                if checkin_result["reward"]:
                    parts.append(f"奖励: {checkin_result['reward']}")
            else:
                parts.append(f"❌ 签到失败: {checkin_result['message']}")

            if balance_result.get("success"):
                parts.append(balance_result["display"])
            else:
                parts.append(balance_result.get("display", "余额查询失败"))

            display = ", ".join(parts)
            print(f"📋 {self.name}: {display}")

            return success, {
                "success": success,
                "display": display,
                "quota": balance_result.get("quota"),
                "used_quota": balance_result.get("used"),
                "bonus_quota": 0,
            }

        except Exception as e:
            print(f"❌ {self.name}: 签到异常: {e}")
            return False, {"error": str(e)}
        finally:
            session.close()
