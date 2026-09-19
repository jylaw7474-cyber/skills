#!/usr/bin/env python3
"""Process many items asynchronously through the Message Batches API (50% of
standard token prices; most batches finish within an hour, all within 24h).

    python batch_processor.py run items.jsonl --task classify --labels positive,negative,neutral -o results.jsonl
    python batch_processor.py submit items.jsonl --task summarize
    python batch_processor.py status
    python batch_processor.py wait
    python batch_processor.py results -o results.jsonl
    python batch_processor.py cancel

Input is JSONL (`{"id": "...", "text": "..."}` per line) or plain text with one
item per line. Submitted batch ids are saved to a state file (default
.batch_state.json) so `status`, `wait` and `results` work across restarts.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_STATE = Path(".batch_state.json")
# API limits: 100,000 requests or 256 MB per batch; chunk well below that.
DEFAULT_CHUNK = 10_000

# Standard $/MTok (input, output); batch requests bill at 50% of these.
PRICING = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


# --------------------------------------------------------------------------- input

def load_items(path: Path) -> list[dict]:
    """Return [{"id": str, "text": str}, ...] from a JSONL or one-per-line text file."""
    items = []
    with path.open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            if path.suffix == ".jsonl":
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    sys.exit(f"{path}:{lineno}: invalid JSON ({exc})")
                if "text" not in obj:
                    sys.exit(f"{path}:{lineno}: missing 'text' field")
                items.append({"id": str(obj.get("id", lineno)), "text": str(obj["text"])})
            else:
                items.append({"id": str(lineno), "text": line})
    if not items:
        sys.exit(f"{path}: no items found")
    return items


# --------------------------------------------------------------------------- request building

def classify_schema(labels: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "label": {"type": "string", "enum": labels},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string", "description": "One sentence justifying the label."},
        },
        "required": ["label", "confidence", "reason"],
        "additionalProperties": False,
    }


def build_task(args: argparse.Namespace) -> dict:
    """Resolve the task into a system prompt, a user-prompt template and an optional JSON schema."""
    if args.task == "classify":
        if not args.labels:
            sys.exit("--labels is required for --task classify (e.g. --labels positive,negative,neutral)")
        labels = [label.strip() for label in args.labels.split(",") if label.strip()]
        return {
            "system": "You are a careful classifier. Read each text and assign exactly one label "
                      f"from this set: {', '.join(labels)}.",
            "template": "Classify the following text.\n\n<text>\n{text}\n</text>",
            "schema": classify_schema(labels),
            "effort": args.effort or "low",
            "max_tokens": args.max_tokens or 4096,
        }
    if args.task == "summarize":
        return {
            "system": "You write faithful, compact summaries that keep every load-bearing fact.",
            "template": f"Summarize the following text in at most {args.max_words} words.\n\n<text>\n{{text}}\n</text>",
            "schema": None,
            "effort": args.effort or "high",
            "max_tokens": args.max_tokens or 16000,
        }
    if not args.prompt or "{text}" not in args.prompt:
        sys.exit("--task custom needs --prompt containing a {text} placeholder")
    schema = json.loads(Path(args.schema).read_text(encoding="utf-8")) if args.schema else None
    return {
        "system": args.system or "You are a helpful assistant.",
        "template": args.prompt,
        "schema": schema,
        "effort": args.effort or "high",
        "max_tokens": args.max_tokens or 16000,
    }


def build_system(task: dict, context_text: str | None) -> list[dict]:
    """Shared system blocks; the cache breakpoint sits on the last shared block so
    every request in the batch reuses the same cached prefix (once it exceeds the
    model's minimum cacheable length)."""
    blocks = [{"type": "text", "text": task["system"]}]
    if context_text:
        blocks.append({"type": "text", "text": context_text})
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def build_requests(items: list[dict], task: dict, model: str, context_text: str | None) -> list[Request]:
    system = build_system(task, context_text)
    requests = []
    for index, item in enumerate(items):
        params: dict = dict(
            model=model,
            max_tokens=task["max_tokens"],
            system=system,
            messages=[{"role": "user", "content": task["template"].replace("{text}", item["text"])}],
            output_config={"effort": task["effort"]},
        )
        if task["schema"]:
            params["output_config"]["format"] = {"type": "json_schema", "schema": task["schema"]}
        requests.append(Request(custom_id=f"item-{index:06d}", params=MessageCreateParamsNonStreaming(**params)))
    return requests


# --------------------------------------------------------------------------- state

def load_state(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"No state file at {path}; run `submit` first")
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- commands

def cmd_submit(client: anthropic.Anthropic, args: argparse.Namespace) -> dict:
    items = load_items(Path(args.input))
    task = build_task(args)
    context_text = Path(args.context_file).read_text(encoding="utf-8") if args.context_file else None
    requests = build_requests(items, task, args.model, context_text)

    batches = []
    for start in range(0, len(requests), args.chunk_size):
        chunk = requests[start:start + args.chunk_size]
        batch = client.messages.batches.create(requests=chunk)
        batches.append({"id": batch.id, "size": len(chunk), "status": batch.processing_status})
        print(f"Created batch {batch.id} with {len(chunk)} requests ({batch.processing_status})")

    state = {
        "model": args.model,
        "task": args.task,
        "structured": task["schema"] is not None,
        "ids": {f"item-{i:06d}": item["id"] for i, item in enumerate(items)},
        "batches": batches,
    }
    save_state(Path(args.state), state)
    print(f"Saved {len(batches)} batch id(s) to {args.state}")
    return state


def refresh(client: anthropic.Anthropic, state: dict) -> bool:
    """Update each batch's status and counts in place; return True when all have ended."""
    all_ended = True
    for entry in state["batches"]:
        batch = client.messages.batches.retrieve(entry["id"])
        counts = batch.request_counts
        entry["status"] = batch.processing_status
        entry["counts"] = {
            "processing": counts.processing, "succeeded": counts.succeeded,
            "errored": counts.errored, "canceled": counts.canceled, "expired": counts.expired,
        }
        all_ended &= batch.processing_status == "ended"
    return all_ended


def print_status(state: dict) -> None:
    for entry in state["batches"]:
        counts = entry.get("counts", {})
        print(f"{entry['id']}: {entry['status']}  " + "  ".join(f"{k}={v}" for k, v in counts.items()))


def cmd_status(client: anthropic.Anthropic, args: argparse.Namespace) -> dict:
    state = load_state(Path(args.state))
    refresh(client, state)
    save_state(Path(args.state), state)
    print_status(state)
    return state


def cmd_wait(client: anthropic.Anthropic, args: argparse.Namespace) -> dict:
    state = load_state(Path(args.state))
    while True:
        done = refresh(client, state)
        save_state(Path(args.state), state)
        print_status(state)
        if done:
            return state
        print(f"... polling again in {args.interval}s")
        time.sleep(args.interval)


def _text_of(message) -> str:
    return next((block.text for block in message.content if block.type == "text"), "")


def parse_output(message, structured: bool):
    text = _text_of(message)
    if not structured:
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"_unparsed": text}


def cmd_results(client: anthropic.Anthropic, args: argparse.Namespace) -> dict:
    state = load_state(Path(args.state))
    if not refresh(client, state):
        save_state(Path(args.state), state)
        print_status(state)
        sys.exit("Not every batch has ended yet; run `wait` first")

    out_path = Path(args.output)
    err_path = out_path.with_suffix(out_path.suffix + ".errors.jsonl")
    ok = failed = 0
    input_tokens = output_tokens = 0
    # Results arrive in any order - key everything by custom_id, never by position.
    with out_path.open("w", encoding="utf-8") as out, err_path.open("w", encoding="utf-8") as err:
        for entry in state["batches"]:
            for result in client.messages.batches.results(entry["id"]):
                original_id = state["ids"].get(result.custom_id, result.custom_id)
                kind = result.result.type
                if kind == "succeeded":
                    message = result.result.message
                    record = {
                        "id": original_id,
                        "custom_id": result.custom_id,
                        "stop_reason": message.stop_reason,
                        "output": parse_output(message, state["structured"]),
                    }
                    if message.stop_reason == "refusal" and message.stop_details:
                        record["refusal"] = {
                            "category": message.stop_details.category,
                            "explanation": message.stop_details.explanation,
                        }
                    input_tokens += message.usage.input_tokens
                    output_tokens += message.usage.output_tokens
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    ok += 1
                else:
                    record = {"id": original_id, "custom_id": result.custom_id, "result": kind}
                    if kind == "errored":
                        error = result.result.error.error
                        record["error"] = {"type": error.type, "message": error.message}
                        # invalid_request errors need a fixed request; anything else is safe to resubmit as-is.
                        record["retryable"] = error.type != "invalid_request_error"
                    else:
                        record["retryable"] = True
                    err.write(json.dumps(record, ensure_ascii=False) + "\n")
                    failed += 1

    print(f"Wrote {ok} results to {out_path}" + (f" and {failed} failures to {err_path}" if failed else ""))
    if not failed:
        err_path.unlink()
    print(f"Tokens: input={input_tokens} output={output_tokens}")
    if state["model"] in PRICING:
        in_rate, out_rate = PRICING[state["model"]]
        cost = (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000 * 0.5
        print(f"Estimated cost at batch rates: ${cost:.4f}")
    return state


def cmd_cancel(client: anthropic.Anthropic, args: argparse.Namespace) -> dict:
    state = load_state(Path(args.state))
    for entry in state["batches"]:
        if entry.get("status") != "ended":
            batch = client.messages.batches.cancel(entry["id"])
            entry["status"] = batch.processing_status
            print(f"{batch.id}: {batch.processing_status}")
    save_state(Path(args.state), state)
    return state


def cmd_run(client: anthropic.Anthropic, args: argparse.Namespace) -> dict:
    cmd_submit(client, args)
    cmd_wait(client, args)
    return cmd_results(client, args)


COMMANDS = {"submit": cmd_submit, "status": cmd_status, "wait": cmd_wait,
            "results": cmd_results, "cancel": cmd_cancel, "run": cmd_run}


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("input", nargs="?", help="JSONL or text file of items (submit/run)")
    parser.add_argument("--task", choices=["classify", "summarize", "custom"], default="classify")
    parser.add_argument("--labels", help="comma-separated labels for --task classify")
    parser.add_argument("--max-words", type=int, default=100, help="summary length for --task summarize")
    parser.add_argument("--prompt", help="user prompt template with a {text} placeholder for --task custom")
    parser.add_argument("--system", help="system prompt for --task custom")
    parser.add_argument("--schema", help="JSON schema file for structured output with --task custom")
    parser.add_argument("--context-file", help="shared document placed in the cached system prefix")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"],
                        help="thinking depth (default: low for classify, high otherwise)")
    parser.add_argument("--max-tokens", type=int, help="per-request output cap (default: 4096 classify, 16000 otherwise)")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK, help="requests per batch")
    parser.add_argument("--interval", type=int, default=60, help="seconds between polls for wait/run")
    parser.add_argument("--state", default=str(DEFAULT_STATE), help="where batch ids are saved")
    parser.add_argument("-o", "--output", default="results.jsonl", help="results file for results/run")
    args = parser.parse_args(argv)
    if args.command in ("submit", "run") and not args.input:
        parser.error(f"{args.command} requires an input file")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        client = anthropic.Anthropic()
        COMMANDS[args.command](client, args)
    except anthropic.AuthenticationError:
        sys.exit("Authentication failed: set ANTHROPIC_API_KEY or run `ant auth login`.")
    except anthropic.NotFoundError as exc:
        sys.exit(f"Not found: {exc.message} (an unknown model or a batch id from another workspace?)")
    except anthropic.RateLimitError as exc:
        sys.exit(f"Rate limited; retry after {exc.response.headers.get('retry-after', '?')}s.")
    except anthropic.APIStatusError as exc:
        sys.exit(f"API error {exc.status_code}: {exc.message}")
    except anthropic.APIConnectionError as exc:
        sys.exit(f"Connection error: {exc}")
    except anthropic.AnthropicError as exc:
        sys.exit(f"{exc}\nSet ANTHROPIC_API_KEY or run `ant auth login`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
