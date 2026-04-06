#!/usr/bin/env python3
"""
storage state 相关工具
"""

import json
import os


def ensure_storage_state_from_env(
    cache_file_path: str,
    account_name: str,
    username: str,
    env_name: str = "STORATE_STATES",
) -> bool:
    """当本地缓存不存在时，从环境变量恢复 storage state 文件。"""
    if not cache_file_path:
        print(f"⚠️ {account_name}: Skip restoring storage state because cache_file_path is empty")
        return False

    if os.path.exists(cache_file_path):
        print(f"⚠️ {account_name}: Skip restoring storage state because cache file already exists: {cache_file_path}")
        return False

    storage_states_str = os.getenv(env_name, "")
    if not storage_states_str:
        print(f"⚠️ {account_name}: Skip restoring storage state because {env_name} is empty or not set")
        return False

    try:
        storage_states = json.loads(storage_states_str)
    except json.JSONDecodeError as exc:
        print(f"⚠️ {account_name}: Failed to parse {env_name}: {exc}")
        return False

    if not isinstance(storage_states, dict):
        print(f"⚠️ {account_name}: {env_name} must be a JSON object")
        return False

    storage_state_data = storage_states.get(username)
    if storage_state_data is None:
        print(f"⚠️ {account_name}: Skip restoring storage state because '{username}' was not found in {env_name}")
        return False

    if isinstance(storage_state_data, str):
        try:
            storage_state_data = json.loads(storage_state_data)
        except json.JSONDecodeError as exc:
            print(f"⚠️ {account_name}: Storage state '{username}' is not valid JSON: {exc}")
            return False

    if not isinstance(storage_state_data, dict):
        print(f"⚠️ {account_name}: Storage state '{username}' must be a JSON object")
        return False

    cache_dir = os.path.dirname(cache_file_path)
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)

    with open(cache_file_path, "w", encoding="utf-8") as file:
        json.dump(storage_state_data, file, ensure_ascii=False, indent=2)

    print(f"ℹ️ {account_name}: Restored storage state from {env_name} -> {username}")
    return True
