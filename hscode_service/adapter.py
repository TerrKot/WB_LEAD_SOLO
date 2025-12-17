from __future__ import annotations

import importlib
import json
import subprocess
from typing import Any, Dict

from libs.core.config import settings


def map_request(data: Dict[str, Any]) -> Dict[str, Any]:
    m = settings.hscore_code_req_map
    return {m.get(k, k): v for k, v in data.items() if v is not None}


def map_response(raw: Dict[str, Any]) -> Dict[str, Any]:
    # return raw as-is; mapping happens in app for pydantic HSResult extraction
    return raw


async def call_http(data: Dict[str, Any]) -> Dict[str, Any]:
    import httpx

    url = f"{settings.hscore_base_url}{settings.hscore_endpoint_code}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, json=data)
        r.raise_for_status()
        return r.json()


async def call_lib(data: Dict[str, Any]) -> Dict[str, Any]:
    module_name, func_name = settings.hscore_lib_import.split(":", 1)
    mod = importlib.import_module(module_name)
    func = getattr(mod, func_name)
    return await func(data)


async def call_cli(data: Dict[str, Any]) -> Dict[str, Any]:
    cmd = settings.hscore_cli_code.split()
    result = subprocess.run(cmd, input=json.dumps(data), capture_output=True, text=True)
    result.check_returncode()
    return json.loads(result.stdout)


