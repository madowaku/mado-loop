"""Deterministically classify a task into MADO LOOP routing domains."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common.result import (  # noqa: E402
    EXIT_INTERNAL,
    EXIT_USAGE_CONFIG,
    exit_code_for_status,
    make_check,
    make_result,
    result_json,
)


DOMAIN_TERMS = {
    "CODE": (
        "code", "script", "gdscript", "c#", "bug", "refactor", "programming",
        "コード", "スクリプト", "実装", "バグ", "リファクタ",
    ),
    "GAMEPLAY": (
        "gameplay", "player movement", "combat", "enemy", "physics", "score",
        "mechanic", "level design", "ゲームプレイ", "操作", "戦闘", "敵", "物理", "得点",
    ),
    "UI": (
        "ui", "hud", "menu", "button", "dialog", "inventory", "interface",
        "ユーザーインターフェース", "画面", "メニュー", "ボタン", "ダイアログ",
    ),
    "SPRITE": (
        "sprite", "spritesheet", "sprite sheet", "atlas", "frame animation",
        "スプライト", "スプライトシート", "アトラス", "コマアニメ",
    ),
    "IMAGE": (
        "image", "illustration", "concept art", "texture", "background art",
        "画像", "イラスト", "コンセプトアート", "テクスチャ", "背景画",
    ),
    "ANIMATION": (
        "animation", "animate", "tween", "keyframe", "アニメーション", "動かす", "補間",
    ),
    "ASSET_INTEGRATION": (
        "asset integration", "import asset", "import settings", "resource path",
        "アセット統合", "素材を組み込", "インポート設定", "リソースパス",
    ),
    "REFERENCE_TO_UI": (
        "reference to ui", "reference-to-ui", "screenshot to ui", "mockup to ui",
        "reference image ui", "参考画像からui", "スクリーンショットからui",
        "モックアップからui", "見本から画面",
    ),
    "PIXEL_ART": (
        "pixel art", "pixel-art", "pixelart", "nearest neighbor", "nearest-neighbor",
        "ドット絵", "ピクセルアート", "ニアレストネイバー",
    ),
    "PLAYTEST": (
        "playtest", "play test", "smoke test", "game test", "プレイテスト",
        "試遊", "動作確認",
    ),
    "RELEASE": (
        "release", "export build", "shipping", "distribution", "store build",
        "リリース", "公開", "配布", "エクスポートビルド",
    ),
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _contains(text: str, term: str) -> bool:
    """Match words without making Japanese substring matching dependent on locale."""
    normalized_term = term.casefold()
    if normalized_term.isascii() and normalized_term.replace(" ", "").isalnum():
        return re.search(r"(?<![a-z0-9])" + re.escape(normalized_term) + r"(?![a-z0-9])", text) is not None
    return normalized_term in text


def classify_domains(task: str) -> list[str]:
    """Return matched concrete domains; the result contract derives MIXED."""
    normalized = _normalize(task)
    return [
        domain
        for domain, terms in DOMAIN_TERMS.items()
        if any(_contains(normalized, term) for term in terms)
    ]


def classify_task(task: str) -> dict[str, object]:
    """Build a schema-v1.1 routing result for one task description."""
    domains = classify_domains(task)
    if domains:
        check = make_check(
            "routing.classification",
            "PASS",
            message="Task domains were classified deterministically.",
            evidence=domains,
            details={"matched_domain_count": len(domains)},
        )
        return make_result(
            "classify_task",
            proof_level="P0",
            summary="Task routing domains classified.",
            task_domains=domains,
            checks=[check],
            environment={"classifier": "keyword-v1", "input_length": len(task)},
        )

    unknown = {
        "id": "routing.no_domain_match",
        "message": "No concrete task domain could be determined from the supplied text.",
    }
    check = make_check(
        "routing.classification",
        "UNKNOWN",
        message=unknown["message"],
    )
    return make_result(
        "classify_task",
        proof_level="P0",
        summary="Task routing is ambiguous.",
        domain_neutral=True,
        checks=[check],
        unknowns=[unknown],
        environment={"classifier": "keyword-v1", "input_length": len(task)},
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", nargs="+", help="task description to classify")
    parser.add_argument("--pretty", action="store_true", help="indent JSON output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    try:
        args = _parser().parse_args(args_list)
    except SystemExit as exc:
        return 0 if exc.code == 0 else EXIT_USAGE_CONFIG
    try:
        payload = classify_task(" ".join(args.task))
        if args.pretty:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        else:
            sys.stdout.write(result_json(payload))
        return exit_code_for_status(str(payload["status"]))
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        sys.stderr.write(f"classify_task internal error: {exc}\n")
        return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())
