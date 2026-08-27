"""Route bounded MADO LOOP worker tasks to explicitly configured model providers.

This module is intentionally stdlib-only. It never installs clients, persists API
keys, or enables a logged free endpoint without explicit consent.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys
from typing import Mapping, Sequence
from urllib import error, request


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
EMPERO_BASE_URL = "https://free.empero.org/v1"
EMPERO_DEFAULT_MODEL = "free"
TRUE_VALUES = {"1", "true", "yes", "on"}
SENSITIVITIES = ("public", "private", "secret")
PROVIDER_NAMES = ("auto", "openrouter", "empero", "local", "off")


class ProviderConfigError(ValueError):
    """Raised when a requested provider cannot be selected safely."""


class ProviderCallError(RuntimeError):
    """Raised when a configured provider call fails."""


@dataclass(frozen=True)
class WorkerProvider:
    name: str
    base_url: str
    model: str
    api_key: str
    external: bool
    logs_content: bool
    privacy_mode: str

    def public_dict(self) -> dict[str, object]:
        """Return a serializable description that never exposes credentials."""
        data = asdict(self)
        data.pop("api_key", None)
        return data


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUE_VALUES


def _value(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _local_provider(env: Mapping[str, str], model_override: str | None = None) -> WorkerProvider | None:
    base_url = _value(env, "MADO_LOCAL_BASE_URL")
    model = model_override or _value(env, "MADO_LOCAL_MODEL")
    if not base_url or not model:
        return None
    return WorkerProvider(
        name="local",
        base_url=base_url.rstrip("/"),
        model=model,
        api_key=_value(env, "MADO_LOCAL_API_KEY") or "local",
        external=False,
        logs_content=False,
        privacy_mode="local-only",
    )


def _openrouter_provider(env: Mapping[str, str], model_override: str | None = None) -> WorkerProvider | None:
    api_key = _value(env, "OPENROUTER_API_KEY")
    model = model_override or _value(env, "MADO_OPENROUTER_MODEL") or _value(env, "OPENROUTER_MODEL")
    if not api_key or not model:
        return None
    return WorkerProvider(
        name="openrouter",
        base_url=OPENROUTER_BASE_URL,
        model=model,
        api_key=api_key,
        external=True,
        logs_content=False,
        privacy_mode="data_collection=deny,zdr=true",
    )


def _empero_provider(
    env: Mapping[str, str],
    *,
    model_override: str | None = None,
    allow_logged_free: bool = False,
) -> WorkerProvider | None:
    allowed = allow_logged_free or _truthy(_value(env, "MADO_ALLOW_LOGGED_FREE"))
    if not allowed:
        return None
    return WorkerProvider(
        name="empero",
        base_url=_value(env, "MADO_EMPERO_BASE_URL") or EMPERO_BASE_URL,
        model=model_override or _value(env, "MADO_EMPERO_MODEL") or EMPERO_DEFAULT_MODEL,
        api_key=_value(env, "MADO_EMPERO_API_KEY") or "free",
        external=True,
        logs_content=True,
        privacy_mode="logged-public-only",
    )


def select_provider(
    *,
    provider: str = "auto",
    sensitivity: str = "private",
    prefer_free: bool = False,
    allow_logged_free: bool = False,
    model_override: str | None = None,
    env: Mapping[str, str] | None = None,
) -> WorkerProvider:
    """Select one provider without silently weakening the data-handling policy."""
    env_map = os.environ if env is None else env
    if provider not in PROVIDER_NAMES:
        raise ProviderConfigError(f"unknown provider: {provider}")
    if sensitivity not in SENSITIVITIES:
        raise ProviderConfigError(f"unknown sensitivity: {sensitivity}")
    if provider == "off":
        raise ProviderConfigError("worker providers are disabled")
    if provider == "auto" and model_override:
        raise ProviderConfigError("--model requires an explicit provider because model IDs are provider-specific")

    local = _local_provider(env_map, model_override if provider == "local" else None)
    openrouter = _openrouter_provider(env_map, model_override if provider == "openrouter" else None)
    empero = _empero_provider(
        env_map,
        model_override=model_override if provider == "empero" else None,
        allow_logged_free=allow_logged_free,
    )

    if provider == "local":
        if local is None:
            raise ProviderConfigError("local provider requires MADO_LOCAL_BASE_URL and MADO_LOCAL_MODEL")
        return local
    if provider == "openrouter":
        if sensitivity == "secret":
            raise ProviderConfigError("secret tasks may not use external providers")
        if openrouter is None:
            raise ProviderConfigError("OpenRouter requires OPENROUTER_API_KEY and MADO_OPENROUTER_MODEL")
        return openrouter
    if provider == "empero":
        if sensitivity != "public":
            raise ProviderConfigError("Empero free is restricted to public tasks because prompts and completions are logged")
        if empero is None:
            raise ProviderConfigError("Empero free requires --allow-logged-free or MADO_ALLOW_LOGGED_FREE=1")
        return empero

    # auto: never invent credentials, never downgrade privacy silently.
    if sensitivity == "secret":
        if local is not None:
            return local
        raise ProviderConfigError("secret task requires a configured local provider")

    if sensitivity == "public" and prefer_free and empero is not None:
        return empero
    if openrouter is not None:
        return openrouter
    if local is not None:
        return local
    if sensitivity == "public" and empero is not None:
        return empero
    raise ProviderConfigError(
        "no permitted worker provider is configured; set OpenRouter, local provider, or explicitly allow Empero for public work"
    )


def build_chat_request(
    selected: WorkerProvider,
    *,
    prompt: str,
    system: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.2,
) -> dict[str, object]:
    if not prompt.strip():
        raise ProviderConfigError("prompt must not be empty")
    if max_tokens <= 0:
        raise ProviderConfigError("max_tokens must be positive")
    if not 0 <= temperature <= 2:
        raise ProviderConfigError("temperature must be between 0 and 2")

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload: dict[str, object] = {
        "model": selected.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    if selected.name == "openrouter":
        payload["provider"] = {"data_collection": "deny", "zdr": True}
    return payload


def call_provider(
    selected: WorkerProvider,
    *,
    prompt: str,
    system: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.2,
    timeout: float = 120.0,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Execute a non-streaming OpenAI-compatible chat request."""
    if not 0 < timeout <= 600:
        raise ProviderConfigError("timeout must be greater than 0 and at most 600 seconds")
    payload = build_chat_request(
        selected,
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    headers = {
        "Authorization": f"Bearer {selected.api_key}",
        "Content-Type": "application/json",
        "User-Agent": "mado-loop/1.0 provider-router",
    }
    env_map = os.environ if env is None else env
    if selected.name == "openrouter":
        site = _value(env_map, "MADO_OPENROUTER_SITE_URL")
        title = _value(env_map, "MADO_OPENROUTER_TITLE") or "MADO LOOP"
        if site:
            headers["HTTP-Referer"] = site
        headers["X-Title"] = title

    endpoint = selected.base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", errors="replace")
        raise ProviderCallError(f"{selected.name} returned HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise ProviderCallError(f"{selected.name} request failed: {exc.reason}") from exc

    try:
        decoded = json.loads(raw)
        content = decoded["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise ProviderCallError(f"{selected.name} returned an unexpected response shape") from exc
    return {
        "provider": selected.public_dict(),
        "content": content,
        "usage": decoded.get("usage"),
    }


def _read_prompt(args: argparse.Namespace) -> str:
    sources = sum(bool(value) for value in (args.prompt, args.prompt_file, args.stdin))
    if sources != 1:
        raise ProviderConfigError("call requires exactly one of --prompt, --prompt-file, or --stdin")
    if args.prompt is not None:
        return args.prompt
    if args.prompt_file is not None:
        return Path(args.prompt_file).read_text(encoding="utf-8")
    return sys.stdin.read()


def _add_selection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", choices=PROVIDER_NAMES, default="auto")
    parser.add_argument("--sensitivity", choices=SENSITIVITIES, default="private")
    parser.add_argument("--model", dest="model_override")
    parser.add_argument("--prefer-free", action="store_true")
    parser.add_argument("--allow-logged-free", action="store_true")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="select and describe a provider without making a network call")
    _add_selection_args(plan)

    call = sub.add_parser("call", help="send one bounded worker prompt")
    _add_selection_args(call)
    call.add_argument("--prompt")
    call.add_argument("--prompt-file")
    call.add_argument("--stdin", action="store_true")
    call.add_argument("--system")
    call.add_argument("--max-tokens", type=int, default=4096)
    call.add_argument("--temperature", type=float, default=0.2)
    call.add_argument("--timeout", type=float, default=120.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
        selected = select_provider(
            provider=args.provider,
            sensitivity=args.sensitivity,
            prefer_free=args.prefer_free,
            allow_logged_free=args.allow_logged_free,
            model_override=args.model_override,
        )
        if args.command == "plan":
            payload = {"status": "PASS", "selected": selected.public_dict()}
        else:
            prompt = _read_prompt(args)
            result = call_provider(
                selected,
                prompt=prompt,
                system=args.system,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                timeout=args.timeout,
            )
            payload = {"status": "PASS", **result}
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return 0
    except ProviderConfigError as exc:
        sys.stderr.write(f"provider configuration error: {exc}\n")
        return 2
    except ProviderCallError as exc:
        sys.stderr.write(f"provider call error: {exc}\n")
        return 3
    except OSError as exc:
        sys.stderr.write(f"provider input error: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
