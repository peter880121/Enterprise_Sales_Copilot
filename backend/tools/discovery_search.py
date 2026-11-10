"""Explicit one-shot public Tavily search. No database, CRM or model access."""

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values

from app.core.errors import AppError
from app.discovery.tavily import TavilySearch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--confirm-public", action="store_true")
    parser.add_argument("--output-parent", required=True)
    args = parser.parse_args()
    if not args.confirm_public:
        parser.error(
            "--confirm-public is required; query must contain public, non-customer data only"
        )
    root = Path(__file__).resolve().parents[2]
    local = (root / ".local").resolve()
    parent = Path(args.output_parent).resolve()
    if not parent.is_relative_to(local) or parent == local:
        parser.error("output parent must be a dedicated directory inside project .local")
    parent.mkdir(parents=True, exist_ok=True)
    output = parent / ("search-" + uuid4().hex)
    output.mkdir()  # Unique exclusive directory; preserve all old evidence.
    values = {**dotenv_values(root / ".env"), **os.environ}
    (output / "request.json").write_text(
        json.dumps(
            {"query": args.query, "status": "STARTED", "limit": 5, "automatic_retries": 0},
            ensure_ascii=False,
        ),
        encoding="utf8",
    )
    try:
        result = TavilySearch(
            values.get("TAVILY_BASE_URL", "https://mcp.tavily.com/mcp"),
            values.get("TAVILY_API_KEY"),
        ).search(args.query)
        serialized = json.dumps(result, ensure_ascii=False)
        key = values.get("TAVILY_API_KEY")
        if key and key in serialized:
            raise AppError(502, "SEARCH_UNSAFE_RESPONSE", "搜索响应包含凭据，拒绝保存。")
        (output / "results.json").write_text(serialized, encoding="utf8")
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "provider": "TAVILY",
                    "results": len(result["results"]),
                    "evidence": str(output.relative_to(root)),
                    "crm_written": False,
                }
            )
        )
        return 0
    except AppError as error:
        summary = {"status": "FAIL", "code": error.code, "automatic_retries": 0}
        (output / "error.json").write_text(json.dumps(summary), encoding="utf8")
        print(json.dumps(summary))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
