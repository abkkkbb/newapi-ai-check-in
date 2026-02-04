#!/usr/bin/env python3
"""
敏感信息掩码工具模块
"""


def mask_username(username: str) -> str:
    """对用户名进行掩码处理

    规则：
    - 如果用户名长度 <= 2，全部用 * 替换
    - 如果用户名长度 <= 4，保留首字符，其余用 * 替换
    - 如果用户名长度 > 4，保留首尾各一个字符，中间用 * 替换（最多显示 4 个 *）

    Args:
        username: 原始用户名

    Returns:
        掩码后的用户名
    """
    if not username:
        return ""

    length = len(username)

    if length <= 2:
        return "*" * length
    elif length <= 4:
        return username[0] + "*" * (length - 1)
    else:
        # 中间用 * 替换，最多 4 个 *
        mask_len = min(length - 2, 4)
        return username[0] + "*" * mask_len + username[-1]
