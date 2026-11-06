from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from knowledge_base.infrastructure import get_settings
from knowledge_base.infrastructure.integrations import TianyanchaClient


def main() -> int:
    debug = False
    args = sys.argv[1:]
    if "--debug" in args:
        debug = True
        args = [arg for arg in args if arg != "--debug"]

    company_name = args[0].strip() if args else ""
    if not company_name:
        print('用法: python3 scripts/test_tianyancha_mcp.py "北京金堤科技有限公司" [--debug]')
        return 1

    settings = get_settings()
    client = TianyanchaClient(settings)
    if not client.enabled():
        print("天眼查未启用，请先配置 KB_TIANYANCHA_ENABLED=true 和 KB_TIANYANCHA_API_KEY")
        return 2

    profile = client.lookup_company_profile(
        brand_name=company_name,
        company_name=company_name,
    )
    if profile is None:
        print("请求已返回，但未解析出可用企业信息。更建议传企业主体全称测试，并检查 MCP 返回内容是否只有原始 content。")
        if debug:
            print(json.dumps(client.last_debug_trace, ensure_ascii=False, indent=2))
        return 3

    print(json.dumps(profile.__dict__, ensure_ascii=False, indent=2))
    if debug:
        print(json.dumps(client.last_debug_trace, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
