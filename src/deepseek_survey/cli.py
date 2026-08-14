from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from .artifacts import new_run_directory
from .config import load_config
from .deepseek import DeepSeekClient
from .pipeline import discover, run_pipeline
from .review import finalize_codex_review
from .rounds import load_next_round_context


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deepseek-survey",
        description="DeepSeek 官方 API 驱动的 32 路并行论文研究调度器",
    )
    parser.add_argument("--config", default="config.toml", help="TOML 配置路径")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="检查配置和 API Key，不发送任何请求")
    discover_parser = subparsers.add_parser("discover", help="只检索 arXiv，不需要 API Key")
    discover_parser.add_argument("--output", type=Path, help="候选论文 JSON 输出路径")
    run_parser = subparsers.add_parser("run", help="执行筛选、32 路阅读、校验和汇总")
    run_parser.add_argument("--candidates", type=Path, help="使用已有 candidates.json")
    continuation = run_parser.add_mutually_exclusive_group()
    continuation.add_argument("--resume", type=Path, help="从已有运行目录续跑同一轮")
    continuation.add_argument(
        "--next-round-from",
        type=Path,
        help="以上一轮目录为父轮次，排除全部历史入选论文并启动新一轮",
    )
    finalize_parser = subparsers.add_parser(
        "finalize-review",
        help="合并 Codex 审查稿与 Flash 阅读卡片，并完成本轮（不需要 API Key）",
    )
    finalize_parser.add_argument("--run", type=Path, required=True, help="运行目录")
    return parser


def _doctor(config_path: str) -> int:
    config = load_config(config_path)
    api_key_set = bool(os.getenv("DEEPSEEK_API_KEY", "").strip())
    print(f"配置: OK ({config.source_path})")
    print(f"研究主题: {config.project.title}")
    print(f"筛选模型: {config.deepseek.screening_model}")
    print(f"阅读模型: {config.deepseek.reader_model}")
    print(f"汇总模型: {config.deepseek.synthesis_model}")
    print(f"汇总 thinking: {config.deepseek.synthesis_thinking}")
    print(f"阅读任务: {config.project.target_papers}")
    print(f"部分汇总阈值: {config.validation.minimum_results_for_synthesis}")
    print(f"最大并发: {config.deepseek.reader_concurrency}")
    print(f"DEEPSEEK_API_KEY: {'已设置' if api_key_set else '未设置（当前可先运行 discover）'}")
    return 0


async def _async_main(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.command == "discover":
        if args.output:
            destination = args.output.resolve()
        else:
            directory = new_run_directory(config.project.output_dir)
            destination = directory / "candidates.json"
        await discover(config, destination)
        return 0
    if args.command == "finalize-review":
        final_report = finalize_codex_review(args.run)
        print(f"[review] Codex 审查已完成：{final_report}")
        return 0

    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        print(
            "错误：尚未设置 DEEPSEEK_API_KEY。项目已可用；设置后再运行 run 即可。",
            file=sys.stderr,
        )
        return 2
    round_context = None
    candidates_path = args.candidates.resolve() if args.candidates else None
    if args.next_round_from:
        parent_run = args.next_round_from.resolve()
        round_context = load_next_round_context(
            parent_run, expected_title=config.project.title
        )
        if candidates_path is None:
            candidates_path = parent_run / "candidates.json"

    async with DeepSeekClient(config.deepseek, api_key) as client:
        run_dir = await run_pipeline(
            config,
            client,
            candidates_path=candidates_path,
            resume_dir=args.resume.resolve() if args.resume else None,
            round_context=round_context,
        )
    print(run_dir)
    return 0


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            raise SystemExit(_doctor(args.config))
        raise SystemExit(asyncio.run(_async_main(args)))
    except KeyboardInterrupt:
        print("已中断；可使用 run --resume <运行目录> 续跑。", file=sys.stderr)
        raise SystemExit(130) from None
    except Exception as exc:
        print(f"运行失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
