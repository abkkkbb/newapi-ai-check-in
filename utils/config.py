#!/usr/bin/env python3
"""
配置管理模块
"""

import json
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, Generator, AsyncGenerator, List, Literal

from utils.get_check_in_status import newapi_check_in_status
from utils.get_cdk import (
    get_runawaytime_cdk,
    get_x666_cdk,
    get_b4u_cdk,
)


# 前向声明 AccountConfig 类型，用于类型注解
# 实际的 AccountConfig 类在后面定义
# 定义 CDK 获取函数的类型：接收 AccountConfig 参数，返回 Generator[str, None, None]
CdkGetterFunc = Callable[["AccountConfig"], Generator[str, None, None]]
AsyncCdkGetterFunc = Callable[["AccountConfig"], AsyncGenerator[str, None]]

# 签到状态查询函数类型：接收 ProviderConfig 和 AccountConfig 参数，返回 bool（今日是否已签到）
# 函数签名: (provider_config, account_config, cookies, headers) -> bool
# 代理配置从 account_config.proxy 或 account_config.get("global_proxy") 获取
# headers 中已包含 api_user_key，无需单独传递 api_user
CheckInStatusFunc = Callable[
    ["ProviderConfig", "AccountConfig", dict, dict],
    bool
]


@dataclass
class ProviderConfig:
    """Provider 配置"""

    name: str
    origin: str
    login_path: str = "/login"
    status_path: str = "/api/status"
    auth_state_path: str = "api/oauth/state"
    check_in_path: str | Callable[[str, str | int], str] | None = None
    check_in_status: CheckInStatusFunc | None = None  # 签到状态查询函数，返回 bool
    user_info_path: str = "/api/user/self"
    topup_path: str | None = "/api/user/topup"
    get_cdk: CdkGetterFunc | AsyncCdkGetterFunc | None = None
    api_user_key: str = "new-api-user"
    github_client_id: str | None = None
    github_auth_path: str = "/api/oauth/github"
    github_auth_redirect_path: str = "/oauth/**"  # OAuth 回调路径匹配模式，支持通配符
    linuxdo_client_id: str | None = None
    linuxdo_auth_path: str = "/api/oauth/linuxdo"
    linuxdo_auth_redirect_path: str = "/oauth/**"  # OAuth 回调路径匹配模式，支持通配符
    aliyun_captcha: bool = False
    bypass_method: Literal["waf_cookies", "cf_clearance"] | None = None

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "ProviderConfig":
        """从字典创建 ProviderConfig

        配置格式:
        - 基础: {"origin": "https://example.com"}
        - 完整: {"origin": "https://example.com", "login_path": "/login", "api_user_key": "x-api-user", "bypass_method": "waf_cookies", ...}
        """
        return cls(
            name=name,
            origin=data["origin"],
            login_path=data.get("login_path", "/login"),
            status_path=data.get("status_path", "/api/status"),
            auth_state_path=data.get("auth_state_path", "api/oauth/state"),
            check_in_path=data.get("check_in_path"),
            check_in_status=data.get("check_in_status"),  # 函数类型无法从 JSON 解析，需要代码中设置
            user_info_path=data.get("user_info_path", "/api/user/self"),
            topup_path=data.get("topup_path", "/api/user/topup"),
            get_cdk=data.get("get_cdk"),  # 函数类型无法从 JSON 解析，需要代码中设置
            api_user_key=data.get("api_user_key", "new-api-user"),
            github_client_id=data.get("github_client_id"),
            github_auth_path=data.get("github_auth_path", "/api/oauth/github"),
            github_auth_redirect_path=data.get("github_auth_redirect_path", "/oauth/**"),
            linuxdo_client_id=data.get("linuxdo_client_id"),
            linuxdo_auth_path=data.get("linuxdo_auth_path", "/api/oauth/linuxdo"),
            linuxdo_auth_redirect_path=data.get("linuxdo_auth_redirect_path", "/oauth/**"),
            aliyun_captcha=data.get("aliyun_captcha", False),
            bypass_method=data.get("bypass_method"),
        )

    def needs_waf_cookies(self) -> bool:
        """判断是否需要获取 WAF cookies"""
        return self.bypass_method == "waf_cookies"

    def needs_cf_clearance(self) -> bool:
        """判断是否需要获取 Cloudflare cf_clearance cookie"""
        return self.bypass_method == "cf_clearance"

    def needs_manual_check_in(self) -> bool:
        """判断是否需要手动调用签到接口"""
        return self.check_in_path is not None

    def needs_manual_topup(self) -> bool:
        """判断是否需要手动执行充值（通过 CDK）
        
        当同时配置了 topup_path 和 get_cdk 时，需要执行 execute_topup
        """
        return self.topup_path is not None and self.get_cdk is not None

    def get_login_url(self) -> str:
        """获取登录 URL"""
        return f"{self.origin}{self.login_path}"

    def get_status_url(self) -> str:
        """获取状态 URL"""
        return f"{self.origin}{self.status_path}"

    def get_auth_state_url(self) -> str:
        """获取认证状态 URL"""
        return f"{self.origin}{self.auth_state_path}"

    def get_check_in_url(self, user_id: str | int) -> str | None:
        """获取签到 URL

        如果 check_in_path 是函数，则调用函数生成带签名的 URL

        Args:
            user_id: 用户 ID

        Returns:
            str | None: 签到 URL，如果不需要签到则返回 None
        """
        if not self.check_in_path:
            return None

        # 如果是函数，则调用函数生成 URL
        if callable(self.check_in_path):
            return self.check_in_path(self.origin, user_id)

        # 否则拼接路径
        return f"{self.origin}{self.check_in_path}"

    def has_check_in_status(self) -> bool:
        """判断是否配置了签到状态查询函数"""
        return self.check_in_status is not None

    def get_user_info_url(self) -> str:
        """获取用户信息 URL"""
        return f"{self.origin}{self.user_info_path}"

    def get_topup_url(self) -> str | None:
        """获取充值 URL"""
        if not self.topup_path:
            return None
        return f"{self.origin}{self.topup_path}"

    def get_github_auth_url(self) -> str:
        """获取 GitHub 认证 URL"""
        return f"{self.origin}{self.github_auth_path}"

    def get_github_auth_redirect_pattern(self) -> str:
        """获取 GitHub OAuth 回调 URL 匹配模式
        
        返回用于 page.wait_for_url() 的匹配模式，支持通配符 **
        例如: "**https://example.com/oauth/**" 或 "**https://example.com/oauth-redirect.html**"
        """
        return f"**{self.origin}{self.github_auth_redirect_path}"

    def get_linuxdo_auth_url(self) -> str:
        """获取 LinuxDo 认证 URL"""
        return f"{self.origin}{self.linuxdo_auth_path}"

    def get_linuxdo_auth_redirect_pattern(self) -> str:
        """获取 LinuxDo OAuth 回调 URL 匹配模式
        
        返回用于 page.wait_for_url() 的匹配模式，支持通配符 **
        例如: "**https://example.com/oauth/**" 或 "**https://example.com/oauth-redirect.html**"
        """
        return f"**{self.origin}{self.linuxdo_auth_redirect_path}"

@dataclass
class AccountConfig:
    """账号配置"""

    provider: str = "anyrouter"
    cookies: dict | str = ""
    api_user: str = ""
    name: str | None = None
    linux_do: dict | None = None
    github: dict | None = None
    proxy: dict | None = None
    extra: dict = field(default_factory=dict)  # 存储额外的配置字段

    @classmethod
    def from_dict(cls, data: dict) -> "AccountConfig":
        """从字典创建 AccountConfig"""
        provider = data.get("provider", "anyrouter")
        name = data.get("name")

        # Handle different authentication types
        cookies = data.get("cookies", "")
        linux_do = data.get("linux.do")
        github = data.get("github")
        proxy = data.get("proxy")

        # 提取已知字段
        known_keys = {"provider", "name", "cookies", "api_user", "linux.do", "github", "proxy"}
        # 收集额外的配置字段
        extra = {k: v for k, v in data.items() if k not in known_keys}

        return cls(
            provider=provider,
            name=name if name else None,
            cookies=cookies,
            api_user=data.get("api_user", ""),
            linux_do=linux_do,
            github=github,
            proxy=proxy,
            extra=extra,
        )

    def get_display_name(self, index: int = 0) -> str:
        """获取显示名称
        
        如果设置了 name 则返回 name，否则返回 "{provider} {index + 1}"
        """
        return self.name if self.name else f"{self.provider} {index + 1}"

    def get(self, key: str, default=None):
        """获取配置值，优先从已知属性获取，否则从 extra 中获取"""
        if hasattr(self, key) and key != "extra":
            value = getattr(self, key)
            return value if value is not None else default
        return self.extra.get(key, default)


@dataclass
class AppConfig:
    """应用配置"""

    providers: Dict[str, ProviderConfig]
    accounts: List["AccountConfig"] = field(default_factory=list)
    global_proxy: Dict | None = None

    @classmethod
    def load_from_env(
        cls,
        providers_env: str = "PROVIDERS",
        accounts_env: str = "ACCOUNTS",
        proxy_env: str = "PROXY",
    ) -> "AppConfig":
        """从环境变量加载配置
        
        Args:
            providers_env: 自定义 providers 配置的环境变量名称，默认为 "PROVIDERS"
            accounts_env: 账号配置的环境变量名称，默认为 "ACCOUNTS"
            proxy_env: 全局代理配置的环境变量名称，默认为 "PROXY"
        """
        # 加载 providers 配置
        providers = cls._load_providers(providers_env)

        # 加载账号配置
        accounts = cls._load_accounts(accounts_env)

        # 加载全局代理配置
        global_proxy = cls._load_proxy(proxy_env)

        return cls(providers=providers, accounts=accounts, global_proxy=global_proxy)

    @classmethod
    def _load_proxy(cls, proxy_env: str) -> Dict | None:
        """从环境变量加载全局代理配置
        
        Args:
            proxy_env: 环境变量名称
        
        Returns:
            代理配置字典，如果未配置则返回 None
        """
        proxy_str = os.getenv(proxy_env)
        if not proxy_str:
            return None

        try:
            # 尝试解析为 JSON
            proxy = json.loads(proxy_str)
            print(f"⚙️ Global proxy loaded from {proxy_env} environment variable (dict format)")
            return proxy
        except json.JSONDecodeError:
            # 如果不是 JSON，则视为字符串
            proxy = {"server": proxy_str}
            print(f"⚙️ Global proxy loaded from {proxy_env} environment variable: {proxy_str}")
            return proxy

    @classmethod
    def _load_providers(cls, providers_env: str) -> Dict[str, ProviderConfig]:
        """从环境变量加载 providers 配置
        
        Args:
            providers_env: 环境变量名称
        
        Returns:
            providers 配置字典
        """
        providers = {
            "anyrouter": ProviderConfig(
                name="anyrouter",
                origin="https://anyrouter.top",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/sign_in",
                check_in_status=None,
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                api_user_key="new-api-user",
                github_client_id="Ov23liOwlnIiYoF3bUqw",
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="8w2uZtoWH9AUXrZr1qeCEEmvXLafea3c",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method="waf_cookies",
            ),
            "agentrouter": ProviderConfig(
                name="agentrouter",
                origin="https://agentrouter.org",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path=None,  # 无需签到接口，查询用户信息时自动完成签到
                check_in_status=None,
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                api_user_key="new-api-user",
                github_client_id="Ov23lidtiR4LeVZvVRNL",
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="KZUecGfhhDZMVnv8UtEdhOhf9sNOhqVX",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=True,
                bypass_method=None,
            ),
            "wong": ProviderConfig(
                name="wong",
                origin="https://wzw.pp.ua",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",
                check_in_status=None,
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path=None,
                linuxdo_client_id="451QxPCe4n9e7XrvzokzPcqPH9rUyTQF",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method=None,
            ),
            "huan666": ProviderConfig(
                name="huan666",
                origin="https://ai.huan666.de",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=newapi_check_in_status,  # 签到状态查询函数，返回 bool
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path=None,
                linuxdo_client_id="FNvJFnlfpfDM2mKDp8HTElASdjEwUriS",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method=None,
            ),
            "runawaytime": ProviderConfig(
                name="runawaytime",
                origin="https://runanytime.hxi.me",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=newapi_check_in_status,  # 签到状态查询函数，返回 bool
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=get_runawaytime_cdk,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path=None,
                linuxdo_client_id="AHjK9O3FfbCXKpF6VXGBC60K21yJ2fYk",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method="cf_clearance",
            ),
            "x666": ProviderConfig(
                name="x666",
                origin="https://x666.me",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path=None,  # 签到通过 qd.x666.me 完成
                check_in_status=None,
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=get_x666_cdk,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path=None,
                linuxdo_client_id="4OtAotK6cp4047lgPD4kPXNhWRbRdTw3",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method=None,
            ),
            "kfc": ProviderConfig(
                name="kfc",
                origin="https://kfc-api.sxxe.net",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=newapi_check_in_status,  # 签到状态查询函数，返回 bool
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=None,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="UZgHjwXCE3HTrsNMjjEi0d8wpcj7d4Of",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method=None,
            ),
            "neb": ProviderConfig(
                name="neb",
                origin="https://ai.zzhdsgsss.xyz",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=newapi_check_in_status,  # 签到状态查询函数，返回 bool
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=None,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="ZflEL6xK90fbCcuWpHEKAcofgK8B5msn",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method=None,
            ),
            "elysiver": ProviderConfig(
                name="elysiver",
                origin="https://elysiver.h-e.top",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=newapi_check_in_status,  # 签到状态查询函数，返回 bool
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=None,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path="/api/oauth/github",
                github_auth_redirect_path="/oauth-redirect.html**",  # 使用 oauth-redirect.html 页面
                linuxdo_client_id="E2eaCQVl9iecd4aJBeTKedXfeKiJpSPF",
                linuxdo_auth_path="/api/oauth/linuxdo",
                linuxdo_auth_redirect_path="/oauth-redirect.html**",  # 使用 oauth-redirect.html 页面
                aliyun_captcha=False,
                bypass_method="cf_clearance",
            ),
            "hotaru": ProviderConfig(
                name="hotaru",
                origin="https://api.hotaruapi.top",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=newapi_check_in_status,  # 签到状态查询函数，返回 bool
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=None,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="qVGkHnU8fLzJVEMgHCuNUCYifUQwePWn",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method="cf_clearance",
            ),
            "b4u": ProviderConfig(
                name="b4u",
                origin="https://b4u.qzz.io",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path=None,  # 无签到接口，通过 luckydraw 获取 CDK 并 topup
                check_in_status=None,
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=get_b4u_cdk,  # 通过 tw.b4u.qzz.io/luckydraw 抽奖获取 CDK
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="Cf3PtT3ecj4kzJrMvOGM48FrHFKYXusb",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method="cf_clearance",
            ),
        }

        # 尝试从环境变量加载自定义 providers
        providers_str = os.getenv(providers_env)

        if providers_str:
            try:
                providers_data = json.loads(providers_str)

                if not isinstance(providers_data, dict):
                    print(f"⚠️ {providers_env} must be a JSON object, ignoring custom providers")
                    return providers

                # 解析自定义 providers,会覆盖默认配置
                for name, provider_data in providers_data.items():
                    try:
                        providers[name] = ProviderConfig.from_dict(name, provider_data)
                    except Exception as e:
                        print(f'⚠️ Failed to parse provider "{name}": {e}, skipping')
                        continue

                print(f"ℹ️ Loaded {len(providers_data)} custom provider(s) from {providers_env} environment variable")
            except json.JSONDecodeError as e:
                print(f"⚠️ Failed to parse {providers_env} environment variable: {e}, using default configuration only")
            except Exception as e:
                print(f"⚠️ Error loading {providers_env}: {e}, using default configuration only")
        else:
            print(f"⚠️ {providers_env} environment variable not found, using default configuration only")

        return providers

    @classmethod
    def _load_accounts(cls, accounts_env: str) -> List["AccountConfig"]:
        """从环境变量加载多账号配置
        
        Args:
            accounts_env: 环境变量名称或直接的 JSON 字符串值
                         优先尝试作为环境变量名获取，获取不到则作为值使用
        
        Returns:
            账号配置列表，如果加载失败则返回空列表
        """
        # 从环境变量获取账号配置
        accounts_str = os.getenv(accounts_env)
        
        if not accounts_str:
            print(f"⚠️ {accounts_env} environment variable not found")
            return []

        try:
            accounts_data = json.loads(accounts_str)

            # 检查是否为数组格式
            if not isinstance(accounts_data, list):
                print("❌ Account configuration must use array format [{}]")
                return []

            accounts = []
            # 验证账号数据格式
            for i, account in enumerate(accounts_data):
                if not isinstance(account, dict):
                    print(f"❌ Account {i + 1} configuration format is incorrect")
                    return []

                # 检查必须有 linux.do、github 或 cookies 配置
                has_linux_do = "linux.do" in account
                has_github = "github" in account
                has_cookies = "cookies" in account

                if not has_linux_do and not has_github and not has_cookies:
                    print(f"❌ Account {i + 1} must have either 'linux.do', 'github', or 'cookies' configuration")
                    return []

                # 确保必要字段存在后再创建 AccountConfig
                if has_cookies:
                    if not account.get("cookies"):
                        print(f"❌ Account {i + 1} cookies cannot be empty")
                        return []
                    if not account.get("api_user"):
                        print(f"❌ Account {i + 1} api_user cannot be empty")
                        return []

                # 验证 linux.do 配置
                if has_linux_do:
                    auth_config = account["linux.do"]
                    if not isinstance(auth_config, dict):
                        print(f"❌ Account {i + 1} linux.do configuration must be a dictionary")
                        return []

                    # 验证必需字段
                    if "username" not in auth_config or "password" not in auth_config:
                        print(f"❌ Account {i + 1} linux.do configuration must contain username and password")
                        return []

                    # 验证字段不为空
                    if not auth_config["username"] or not auth_config["password"]:
                        print(f"❌ Account {i + 1} linux.do username and password cannot be empty")
                        return []

                # 验证 github 配置
                if has_github:
                    auth_config = account["github"]
                    if not isinstance(auth_config, dict):
                        print(f"❌ Account {i + 1} github configuration must be a dictionary")
                        return []

                    # 验证必需字段
                    if "username" not in auth_config or "password" not in auth_config:
                        print(f"❌ Account {i + 1} github configuration must contain username and password")
                        return []

                    # 验证字段不为空
                    if not auth_config["username"] or not auth_config["password"]:
                        print(f"❌ Account {i + 1} github username and password cannot be empty")
                        return []

                # 验证 cookies 配置
                if has_cookies:
                    cookies_config = account["cookies"]
                    if not cookies_config:
                        print(f"❌ Account {i + 1} cookies cannot be empty")
                        return []

                    # 验证必须要有 api_user 字段
                    if "api_user" not in account:
                        print(f"❌ Account {i + 1} with cookies must have api_user field")
                        return []

                    if not account["api_user"]:
                        print(f"❌ Account {i + 1} api_user cannot be empty")
                        return []

                # 如果有 name 字段,确保它不是空字符串
                if "name" in account and not account["name"]:
                    print(f"❌ Account {i + 1} name field cannot be empty")
                    return []

                accounts.append(AccountConfig.from_dict(account))

            return accounts
        except json.JSONDecodeError as e:
            print(f"❌ Account configuration JSON format is incorrect: {e}")
            return []
        except Exception as e:
            print(f"❌ Account configuration format is incorrect: {e}")
            return []

    def get_provider(self, name: str) -> ProviderConfig | None:
        """获取指定 provider 配置"""
        return self.providers.get(name)

