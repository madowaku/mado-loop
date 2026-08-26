"""Recommend the lowest sufficient MADO LOOP proof ladder for a claim."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common.result import (  # noqa: E402
    CONCRETE_TASK_DOMAINS,
    EXIT_INTERNAL,
    EXIT_USAGE_CONFIG,
    PROOF_LEVELS,
    exit_code_for_status,
    make_check,
    make_result,
    result_json,
)


LEVEL_DESCRIPTIONS = {
    "P0": "syntax, import, and static checks",
    "P1": "boot and runtime-error checks",
    "P2": "UI, layout, and static visual inspection",
    "P3": "deterministic gameplay behavior checks",
    "P4": "motion, capture, and temporal inspection",
    "P5": "export, artifact, and release audit",
}

LEVEL_TERMS = {
    "P0": ("syntax", "import", "lint", "parse", "static", "構文", "インポート", "静的"),
    "P1": ("boot", "startup", "runtime", "crash", "launch", "起動", "実行時", "クラッシュ"),
    "P2": ("ui", "hud", "layout", "visual", "screenshot", "menu", "画面", "レイアウト", "見た目", "スクリーンショット"),
    "P3": ("gameplay", "behavior", "movement", "combat", "physics", "input", "ゲームプレイ", "挙動", "操作", "戦闘", "物理"),
    "P4": ("animation", "motion", "capture", "temporal", "video", "アニメーション", "動き", "録画", "時間変化"),
    "P5": ("export", "artifact", "release", "package", "shipping", "エクスポート", "成果物", "リリース", "配布"),
}

DOMAIN_MINIMUMS = {
    "CODE": "P1",
    "GAMEPLAY": "P3",
    "UI": "P2",
    "SPRITE": "P2",
    "IMAGE": "P2",
    "ANIMATION": "P4",
    "ASSET_INTEGRATION": "P1",
    "REFERENCE_TO_UI": "P2",
    "PIXEL_ART": "P2",
    "PLAYTEST": "P3",
    "RELEASE": "P5",
}


def _contains(text: str, term: str) -> bool:
    folded = term.casefold()
    if folded.isascii() and folded.replace(" ", "").isalnum():
        return re.search(r"(?<![a-z0-9])" + re.escape(folded) + r"(?![a-z0-9])", text) is not None
    return folded in text


def _required_level(text: str, domains: Iterable[str], requested: str | None) -> str | None:
    candidates = []
    folded = re.sub(r"\s+", " ", text.casefold()).strip()
    for level, terms in LEVEL_TERMS.items():
        if any(_contains(folded, term) for term in terms):
            candidates.append(level)
    candidates.extend(DOMAIN_MINIMUMS[domain] for domain in domains)
    if requested is not None:
        candidates.append(requested)
    return max(candidates, key=PROOF_LEVELS.index) if candidates else None


def classify_proof(
    claim: str,
    *,
    task_domains: Iterable[str] = (),
    requested_proof: str | None = None,
    not_applicable: bool = False,
) -> dict[str, object]:
    """Return a deterministic proof recommendation, without claiming proof execution."""
    domains = list(task_domains)
    if not_applicable:
        return make_result(
            "classify_proof",
            proof_level=None,
            summary="Proof classification was explicitly not applicable.",
            task_domains=domains,
            domain_neutral=not domains,
            status="SKIPPED",
            operation_skipped=True,
            environment={"classifier": "proof-ladder-v1", "input_length": len(claim)},
        )

    level = _required_level(claim, domains, requested_proof)
    if level is None:
        unknown = {
            "id": "proof.insufficient_claim_context",
            "message": "The claim does not identify observable behavior or a required proof surface.",
        }
        return make_result(
            "classify_proof",
            proof_level=None,
            summary="Proof requirement is ambiguous.",
            task_domains=domains,
            domain_neutral=not domains,
            checks=[make_check("proof.classification", "UNKNOWN", message=unknown["message"])],
            unknowns=[unknown],
            environment={"classifier": "proof-ladder-v1", "input_length": len(claim)},
        )

    ladder = list(PROOF_LEVELS[: PROOF_LEVELS.index(level) + 1])
    check = make_check(
        "proof.classification",
        "PASS",
        message="Proof recommendation classified; no proof step was executed.",
        evidence=ladder,
        details={
            "recommended_level": level,
            "recommended_ladder": ladder,
            "requirement": LEVEL_DESCRIPTIONS[level],
        },
    )
    return make_result(
        "classify_proof",
        proof_level=level,
        summary=f"Recommend {level} with prerequisite ladder {' -> '.join(ladder)}; execution is unverified.",
        task_domains=domains,
        domain_neutral=not domains,
        checks=[check],
        environment={"classifier": "proof-ladder-v1", "input_length": len(claim)},
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("claim", nargs="+", help="task or claim text")
    parser.add_argument("--domain", action="append", default=[], choices=CONCRETE_TASK_DOMAINS)
    parser.add_argument("--requested-proof", choices=PROOF_LEVELS)
    parser.add_argument("--not-applicable", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as exc:
        return 0 if exc.code == 0 else EXIT_USAGE_CONFIG
    try:
        payload = classify_proof(
            " ".join(args.claim),
            task_domains=args.domain,
            requested_proof=args.requested_proof,
            not_applicable=args.not_applicable,
        )
        if args.pretty:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        else:
            sys.stdout.write(result_json(payload))
        return exit_code_for_status(str(payload["status"]))
    except (ValueError, KeyError) as exc:
        sys.stderr.write(f"classify_proof configuration error: {exc}\n")
        return EXIT_USAGE_CONFIG
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"classify_proof internal error: {exc}\n")
        return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())
