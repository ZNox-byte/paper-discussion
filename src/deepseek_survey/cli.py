from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

from .artifacts import new_run_directory, read_json
from .config import load_config
from .pipeline import discover, run_pipeline
from .providers import RoutedClient
from .review import finalize_review, review_hashes
from .rounds import load_next_round_context


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deepseek-survey",
        description="多供应商 Flash 阅读与可替换上层审阅的论文研究调度器",
    )
    parser.add_argument("--config", default="config.toml", help="TOML 配置路径")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="检查配置和 API Key，不发送任何请求")
    serve_parser = subparsers.add_parser("serve", help="启动本地研究工作台；浏览结果无需 API Key")
    serve_parser.add_argument("--runs", type=Path, default=Path("runs"), help="研究记录目录")
    serve_parser.add_argument("--port", type=int, default=8765, help="本机监听端口")
    discover_parser = subparsers.add_parser("discover", help="只检索 arXiv，不需要 API Key")
    discover_parser.add_argument("--output", type=Path, help="候选论文 JSON 输出路径")
    run_parser = subparsers.add_parser("run", help="执行筛选、32 路阅读、校验和汇总")
    run_parser.add_argument("--candidates", type=Path, help="使用已有 candidates.json")
    run_parser.add_argument("--resume-policy", choices=["reuse", "strict"],
                            help="复用合格成果，或要求阅读模型配置严格一致")
    continuation = run_parser.add_mutually_exclusive_group()
    continuation.add_argument("--resume", type=Path, help="从已有运行目录续跑同一轮")
    continuation.add_argument(
        "--next-round-from",
        type=Path,
        help="以上一轮目录为父轮次，排除全部历史入选论文并启动新一轮",
    )
    finalize_parser = subparsers.add_parser(
        "finalize-review",
        help="校验审查决定、覆盖及文件哈希后生成最终报告（不需要 API Key）",
    )
    finalize_parser.add_argument("--run", type=Path, required=True, help="运行目录")
    hashes_parser = subparsers.add_parser("review-hashes", help="显示正文和审查包哈希，不改变审查决定")
    hashes_parser.add_argument("--run", type=Path, required=True)
    reread_parser = subparsers.add_parser("reread", help="按审查决定中的请求补读，再交回上层审阅")
    reread_parser.add_argument("--run", type=Path, required=True)
    return parser


def _doctor(config_path: str) -> int:
    config = load_config(config_path)
    print(f"配置: OK ({config.source_path})")
    print(f"研究主题: {config.project.title}")
    for role in ("screening", "reader", "reader_fallback", "reviewer"):
        alias = getattr(config.routing, role)
        if alias:
            model = config.models[alias]
            active = "（external 模式不调用）" if role == "reviewer" and (
                config.review.mode == "external"
            ) else ""
            print(f"{role}: {alias} → {model.provider}/{model.model} [{model.tier}]{active}")
    print(f"审阅方式: {config.review.mode} / {config.review.name}")
    print(f"阅读任务: {config.project.target_papers}")
    print(f"部分汇总阈值: {config.validation.minimum_results_for_synthesis}")
    print(f"最大阅读并发: {config.execution.reader_concurrency}")
    missing = RoutedClient(config).check_keys()
    print(f"活跃路由所需密钥: {'缺少 ' + ', '.join(missing) if missing else '均已设置'}")
    print(f"请求预算: {config.execution.max_requests}；token 预算: {config.execution.max_total_tokens}")
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
        final_report = finalize_review(args.run)
        print(f"[review] 审查已完成：{final_report}")
        return 0
    if args.command == "review-hashes":
        print(json.dumps(review_hashes(args.run), ensure_ascii=False, indent=2))
        return 0

    if getattr(args, "resume_policy", None):
        config = replace(config, execution=replace(
            config.execution, resume_policy=args.resume_policy
        ))
    missing = RoutedClient(config).check_keys()
    if missing:
        print(
            "错误：缺少活跃路由所需密钥环境变量：" + ", ".join(missing),
            file=sys.stderr,
        )
        return 2
    round_context = None
    candidates_path = args.candidates.resolve() if getattr(args, "candidates", None) else None
    requests = None
    resume_dir = args.resume.resolve() if getattr(args, "resume", None) else None
    if args.command == "reread":
        resume_dir = args.run.resolve()
        decision = read_json(resume_dir / "review" / "decision.json")
        requests = decision.get("reread_requests")
        if not isinstance(requests, list) or not requests:
            raise ValueError("审查决定中没有待执行的 reread_requests")
    if getattr(args, "next_round_from", None):
        parent_run = args.next_round_from.resolve()
        round_context = load_next_round_context(
            parent_run, expected_title=config.project.title
        )
        if candidates_path is None:
            candidates_path = parent_run / "candidates.json"

    async with RoutedClient(config) as client:
        run_dir = await run_pipeline(
            config,
            client,
            candidates_path=candidates_path,
            resume_dir=resume_dir,
            round_context=round_context,
            reread_requests=requests,
        )
    print(run_dir)
    return 0


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    try:
        if args.command == "serve":
            from .web import serve

            serve(args.runs, args.port, Path(args.config))
            return
        if args.command == "doctor":
            raise SystemExit(_doctor(args.config))
        raise SystemExit(asyncio.run(_async_main(args)))
    except KeyboardInterrupt:
        print("已中断；可使用 run --resume <运行目录> 续跑。", file=sys.stderr)
        raise SystemExit(130) from None
    except Exception as exc:
        print(f"运行失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
