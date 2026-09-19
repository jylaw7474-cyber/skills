#!/usr/bin/env python3
"""Tool-using agent built on the Anthropic Python SDK's beta tool runner.

The runner drives the request -> execute tools -> feed results back loop; this
file only defines the tools and renders the streamed turns.

    python agent.py "List the files in the workspace and summarize the largest one"
    python agent.py                     # interactive multi-turn session

Credentials come from ANTHROPIC_API_KEY or an `ant auth login` profile.
File tools are confined to AGENT_WORKSPACE (default: ./workspace).
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import math
import operator
import os
import sys
import zoneinfo
from pathlib import Path

import anthropic
from anthropic import beta_tool
from anthropic.lib.tools import ToolError

DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 16000
MAX_ITERATIONS = 25
READ_LIMIT_CHARS = 20_000

WORKSPACE = Path(os.environ.get("AGENT_WORKSPACE", "workspace")).resolve()

SYSTEM_PROMPT = (
    "You are an assistant working inside a sandboxed workspace directory. "
    "Use list_files and read_file to inspect files, write_file to create or "
    "replace them, calculate for arithmetic, and get_current_datetime whenever "
    "the current date or time matters. Read before you write, and tell the user "
    "what you changed."
)

# Set from --yes; when False, write_file asks on the terminal before writing.
auto_approve = False


# --------------------------------------------------------------------------- tools

def _resolve(path: str) -> Path:
    """Map a tool-supplied path onto the workspace, refusing anything outside it."""
    candidate = (WORKSPACE / path).resolve()
    if candidate != WORKSPACE and WORKSPACE not in candidate.parents:
        raise ToolError(f"Refused: '{path}' is outside the workspace {WORKSPACE}")
    return candidate


@beta_tool
def list_files(directory: str = ".") -> str:
    """List files and folders inside the workspace. Call this first when you
    need to know what files exist before reading or writing.

    Args:
        directory: Folder relative to the workspace root, e.g. "." or "notes".
    """
    root = _resolve(directory)
    if not root.is_dir():
        raise ToolError(f"'{directory}' is not a directory in the workspace")
    lines = []
    for entry in sorted(root.rglob("*")):
        if any(part.startswith(".") for part in entry.relative_to(WORKSPACE).parts):
            continue
        rel = entry.relative_to(WORKSPACE)
        lines.append(f"{rel}/" if entry.is_dir() else f"{rel}  ({entry.stat().st_size} bytes)")
        if len(lines) >= 500:
            lines.append("... (truncated at 500 entries)")
            break
    return "\n".join(lines) or "(workspace is empty)"


@beta_tool
def read_file(path: str, max_chars: int = READ_LIMIT_CHARS) -> str:
    """Read a UTF-8 text file from the workspace. Use it before editing a file
    or when the user asks about a file's contents.

    Args:
        path: File path relative to the workspace root.
        max_chars: Maximum characters to return; longer files are truncated.
    """
    target = _resolve(path)
    if not target.is_file():
        raise ToolError(f"'{path}' does not exist in the workspace")
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + f"\n... (truncated, {len(text) - max_chars} more characters)"
    return text


@beta_tool
def write_file(path: str, content: str) -> str:
    """Create or overwrite a text file in the workspace. Call it only after you
    know what the file should contain; the user is asked to approve each write.

    Args:
        path: File path relative to the workspace root. Parent folders are created.
        content: The complete new contents of the file.
    """
    target = _resolve(path)
    if not auto_approve:
        if not sys.stdin.isatty():
            raise ToolError("User approval is required for writes but no terminal is attached; rerun with --yes")
        answer = input(f"\n[approve] write {len(content)} chars to {target.relative_to(WORKSPACE)}? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            raise ToolError("User declined the write")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {len(content.encode('utf-8'))} bytes to {target.relative_to(WORKSPACE)}"


_BIN_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"abs": abs, "round": round, "min": min, "max": max, "sqrt": math.sqrt,
          "log": math.log, "log10": math.log10, "exp": math.exp, "floor": math.floor,
          "ceil": math.ceil}
_CONSTANTS = {"pi": math.pi, "e": math.e}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 10_000:
            raise ToolError("Exponent too large")
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
        return _FUNCS[node.func.id](*(_eval_node(a) for a in node.args))
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    raise ToolError(f"Unsupported expression element: {type(node).__name__}")


@beta_tool
def calculate(expression: str) -> str:
    """Evaluate an arithmetic expression exactly. Use it for any calculation
    instead of doing the arithmetic yourself.

    Args:
        expression: Python-style arithmetic, e.g. "(1200 * 1.07) ** 3" or "sqrt(2) * pi".
            Supports + - * / // % **, parentheses, abs/round/min/max/sqrt/log/log10/exp/floor/ceil, pi and e.
    """
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval_node(tree)
    except ToolError:
        raise
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, TypeError) as exc:
        raise ToolError(f"Could not evaluate '{expression}': {exc}") from exc
    return json.dumps(result)


@beta_tool
def get_current_datetime(timezone: str = "UTC") -> str:
    """Return the current date and time. Call it whenever the answer depends on
    today's date, the current time, or a relative date like "next Friday".

    Args:
        timezone: IANA zone name such as "UTC", "Europe/London" or "Asia/Jerusalem".
    """
    try:
        zone = zoneinfo.ZoneInfo(timezone)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise ToolError(f"Unknown timezone '{timezone}'") from exc
    return dt.datetime.now(zone).isoformat(timespec="seconds")


TOOLS = [list_files, read_file, write_file, calculate, get_current_datetime]


# --------------------------------------------------------------------------- rendering

def _dim(text: str) -> str:
    return f"\033[2m{text}\033[0m" if sys.stdout.isatty() else text


def render_stream(stream, show_thinking: bool):
    """Print one assistant turn as it streams and return the final message."""
    in_thinking = False
    for event in stream:
        if event.type == "content_block_start":
            block = event.content_block
            if block.type == "thinking" and show_thinking:
                print(_dim("[thinking] "), end="", flush=True)
                in_thinking = True
            elif block.type == "tool_use":
                print(f"\n{_dim('[tool] ' + block.name)}", end="", flush=True)
        elif event.type == "content_block_delta":
            delta = event.delta
            if delta.type == "text_delta":
                print(delta.text, end="", flush=True)
            elif delta.type == "thinking_delta" and show_thinking:
                print(_dim(delta.thinking), end="", flush=True)
        elif event.type == "content_block_stop" and in_thinking:
            print()
            in_thinking = False
    message = stream.get_final_message()
    for block in message.content:
        if block.type == "tool_use":
            print(_dim(f"  {block.name}({json.dumps(block.input)[:300]})"))
    return message


def _summarize_tool_results(tool_response) -> None:
    for block in tool_response["content"]:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        content = block.get("content")
        if isinstance(content, list):
            content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
        preview = str(content).replace("\n", " ")[:200]
        marker = "error" if block.get("is_error") else "result"
        print(_dim(f"  [{marker}] {preview}"))


# --------------------------------------------------------------------------- agent loop

def build_runner(client: anthropic.Anthropic, history: list, args: argparse.Namespace):
    params = dict(
        model=args.model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=history,
        tools=TOOLS,
        thinking={"type": "adaptive", "display": "summarized"},
        output_config={"effort": args.effort},
        cache_control={"type": "ephemeral"},
        max_iterations=MAX_ITERATIONS,
        stream=True,
    )
    if not args.no_fallbacks:
        # Re-run a policy-declined request on Anthropic's recommended fallback
        # model server-side instead of surfacing the refusal.
        params["fallbacks"] = "default"
        params["betas"] = ["server-side-fallback-2026-07-01"]
    return client.beta.messages.tool_runner(**params)


def run_turn(client: anthropic.Anthropic, history: list, args: argparse.Namespace):
    """Run one user turn to completion, mirroring every message into `history`.

    The runner keeps its own copy of the conversation and does not expose it,
    so each assistant turn and tool-result turn is appended here to carry the
    transcript into the next user turn.
    """
    runner = build_runner(client, history, args)
    final = None
    for stream in runner:
        message = render_stream(stream, args.show_thinking)
        history.append({"role": "assistant", "content": message.content})
        final = message
        if message.stop_reason == "tool_use":
            tool_response = runner.generate_tool_call_response()
            if tool_response is not None:
                history.append(tool_response)
                _summarize_tool_results(tool_response)
    return final


def report_turn(message) -> None:
    print()
    if message is None:
        return
    if message.stop_reason == "refusal":
        details = message.stop_details
        category = getattr(details, "category", None) if details else None
        explanation = getattr(details, "explanation", None) if details else None
        print(f"[refused] category={category} {explanation or ''}".rstrip())
    elif message.stop_reason == "max_tokens":
        print(f"[truncated] hit max_tokens={MAX_TOKENS}; the answer above is incomplete")
    elif message.stop_reason == "tool_use":
        print(f"[stopped] reached the {MAX_ITERATIONS}-iteration cap with tool calls still pending")

    fallback_ran = any(entry.type == "fallback_message" for entry in (message.usage.iterations or []))
    if fallback_ran and message.stop_reason != "refusal":
        print(f"[fallback] served by {message.model}")

    usage = message.usage
    print(_dim(
        f"[usage] in={usage.input_tokens} out={usage.output_tokens} "
        f"cache_read={usage.cache_read_input_tokens or 0} cache_write={usage.cache_creation_input_tokens or 0}"
    ))


def make_client() -> anthropic.Anthropic:
    try:
        return anthropic.Anthropic()
    except anthropic.AnthropicError as exc:
        sys.exit(f"Could not create the Anthropic client: {exc}\n"
                 "Set ANTHROPIC_API_KEY or run `ant auth login`.")


def chat(client: anthropic.Anthropic, history: list, user_text: str, args: argparse.Namespace) -> bool:
    """Send one user message; return False when the error is not recoverable."""
    start = len(history)
    history.append({"role": "user", "content": user_text})
    try:
        report_turn(run_turn(client, history, args))
        return True
    except anthropic.AuthenticationError:
        print("Authentication failed: check ANTHROPIC_API_KEY or run `ant auth login`.")
        return False
    except anthropic.RateLimitError as exc:
        retry_after = exc.response.headers.get("retry-after", "?")
        print(f"Rate limited; retry after {retry_after}s.")
    except anthropic.APIStatusError as exc:
        print(f"API error {exc.status_code}: {exc.message}")
    except anthropic.APIConnectionError as exc:
        print(f"Connection error: {exc}")
    # Roll back the partial turn so the next request starts from a well-formed transcript.
    del history[start:]
    return True


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("task", nargs="?", help="single task to run; omit for an interactive session")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"],
                        help="thinking depth and token spend (default: high; xhigh suits harder agentic work)")
    parser.add_argument("--show-thinking", action="store_true", help="print summarized thinking as it streams")
    parser.add_argument("--yes", action="store_true", help="approve every write_file call without asking")
    parser.add_argument("--no-fallbacks", action="store_true",
                        help="disable server-side fallback to another model on a policy refusal")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    global auto_approve
    args = parse_args(argv)
    auto_approve = args.yes
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    client = make_client()
    history: list = []

    if args.task:
        return 0 if chat(client, history, args.task, args) else 1

    print(f"Workspace: {WORKSPACE}  Model: {args.model}  (/reset clears history, /quit exits)")
    while True:
        try:
            user_text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not user_text:
            continue
        if user_text in ("/quit", "/exit"):
            return 0
        if user_text == "/reset":
            history.clear()
            print("(history cleared)")
            continue
        if not chat(client, history, user_text, args):
            return 1


if __name__ == "__main__":
    sys.exit(main())
