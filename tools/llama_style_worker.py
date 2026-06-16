#!/usr/bin/env python3
"""llama.cpp worker for prompt style generation tasks.

Reads one JSON task from stdin and writes one JSON response to stdout. This is
the adapter expected by tools/generate_missing_styles.py --llm-cmd.

Two modes:
  --model PATH / --hf-repo REPO  spawn llama-cli per job (slow, loads model each time)
  --server URL                   reuse a running llama-server (fast, model stays loaded)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one style-generation task through llama-cli.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--model", help="Path to a local GGUF model.")
    mode.add_argument("--hf-repo", help="Hugging Face GGUF repo.")
    mode.add_argument("--server", help="llama-server URL e.g. http://127.0.0.1:8080")
    parser.add_argument("--hf-file", help="Specific GGUF filename inside --hf-repo.")
    parser.add_argument("--llama-cli", default="llama-cli", help="llama.cpp CLI executable.")
    parser.add_argument("--ctx-size", type=int, default=4096)
    parser.add_argument("--predict", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--threads", type=int)
    parser.add_argument("--gpu-layers", default="auto")
    return parser.parse_args()


def build_messages(task: dict) -> list[dict]:
    source_pos = task.get("source_positive_template", "")
    source_neg = task.get("source_negative_template", "")
    target = task.get("target_style", {})
    style_name = target.get("identifier", "")
    required = task.get("required_wildcards", [])

    required_str = ", ".join("{" + w + "}" for w in required) if required else "(none)"

    style_examples = {
        "booru-tags": '{"positive_template": "1girl, solo, {placeholder}, detailed_background", "negative_template": "lowres, bad_anatomy", "notes": "..."}',
        "enhanced-prompt": '{"positive_template": "Highly detailed {placeholder} of a subject, {placeholder2}, layered detail", "negative_template": "low quality, blurry", "notes": "..."}',
        "everyday-speech": '{"positive_template": "A natural description of a {placeholder} in a scene", "negative_template": "blurry, low quality", "notes": "..."}',
        "lisp-like": '{"positive_template": "(prompt (subject \\"{placeholder}\\") (style \\"{placeholder2}\\"))", "negative_template": "(negative blurry)", "notes": "..."}',
        "structured-fields": '{"positive_template": "Subject: {placeholder}\\nEnvironment: ...", "negative_template": "Avoid: blurry", "notes": "..."}',
    }
    ex = style_examples.get(style_name, '{"positive_template":"...","negative_template":"...","notes":"..."}')

    user_prompt = (
        f"Source: {source_pos}\n"
        f"{'Negative: ' + source_neg if source_neg else ''}\n"
        f"Style: {style_name}\n"
        f"Preserve: {required_str}\n"
        f"Format: {ex}"
    )
    return [
        {"role": "system", "content": "You are a helpful assistant that outputs only valid JSON. Never use thinking tags."},
        {"role": "user", "content": user_prompt},
    ]


def _repair_json(text: str) -> str | None:
    """Try to fix common JSON issues: unquoted keys, trailing commas, single quotes."""
    text = re.sub(r"```[\s\S]*?```", "", text)
    brace_match = re.search(r"\{[\s\S]*\}", text)
    if not brace_match:
        return None
    blob = brace_match.group(0)

    # Replace single quotes with double quotes (but not inside already-quoted strings)
    def fix_quotes(m):
        s = m.group(0)
        if s.startswith("'") and s.endswith("'"):
            return '"' + s[1:-1] + '"'
        return s
    blob = re.sub(r"'[^']*'", fix_quotes, blob)

    # Add double quotes around unquoted keys: {key: value} -> {"key": value}
    blob = re.sub(r"(?<!\")(\b[a-zA-Z_][a-zA-Z0-9_]*)(\s*:)", r'"\1"\2', blob)

    # Remove trailing commas before }
    blob = re.sub(r",\s*}", "}", blob)
    blob = re.sub(r",\s*]", "]", blob)

    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


def extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```.*?\n", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n```.*$", "", text)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fixed = _repair_json(text)
    if fixed is not None:
        return fixed

    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        if text[idx] in " \t\n\r":
            idx += 1
            continue
        if text[idx] == "{":
            try:
                obj, end = decoder.raw_decode(text, idx)
                return obj
            except json.JSONDecodeError:
                pass
        idx += 1

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError(f"output did not contain a JSON object: {text[:500]}")
    return json.loads(match.group(0))


def call_server_chat(server_url: str, messages: list[dict], temperature: float, top_p: float, predict: int) -> str:
    body = json.dumps({
        "messages": messages,
        "max_tokens": predict,
        "temperature": temperature,
        "top_p": top_p,
        "repeat_penalty": 1.1,
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(
        f"{server_url.rstrip('/')}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    resp = json.loads(urllib.request.urlopen(req).read())
    return resp["choices"][0]["message"]["content"]


def _build_raw_prompt(messages: list[dict]) -> str:
    out = ""
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if role == "system":
            out += f"<|im_start|>system\n{content}<|im_end|>\n"
        elif role == "user":
            out += f"<|im_start|>user\n{content}<|im_end|>\n"
        elif role == "assistant":
            out += f"<|im_start|>assistant\n{content}<|im_end|>\n"
    out += "<|im_start|>assistant\n"
    return out


def main() -> None:
    args = parse_args()
    task = json.load(sys.stdin)
    messages = build_messages(task)

    if args.server:
        text = call_server_chat(args.server, messages, args.temperature, args.top_p, args.predict)
        response = extract_json(text)
        print(json.dumps(response, ensure_ascii=False))
        return

    prompt = _build_raw_prompt(messages)
    command = [
        args.llama_cli,
        "--simple-io",
        "--no-display-prompt",
        "--no-show-timings",
        "--ctx-size",
        str(args.ctx_size),
        "--predict",
        str(args.predict),
        "--temp",
        str(args.temperature),
        "--top-p",
        str(args.top_p),
        "--gpu-layers",
        str(args.gpu_layers),
        "--prompt",
        prompt,
    ]
    if args.model:
        command.extend(["--model", args.model])
    else:
        command.extend(["--hf-repo", args.hf_repo])
        if args.hf_file:
            command.extend(["--hf-file", args.hf_file])
    if args.threads:
        command.extend(["--threads", str(args.threads)])

    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
        raise SystemExit(result.returncode)

    response = extract_json(result.stdout)
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
