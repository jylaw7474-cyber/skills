# Claude API examples (Python)

Two runnable programs built on the official [`anthropic`](https://github.com/anthropics/anthropic-sdk-python) SDK (1.x), both defaulting to `claude-opus-5`.

| File | What it does |
|---|---|
| `agent.py` | Tool-using agent: Claude calls your Python functions (sandboxed file tools, a calculator, a clock) through the SDK's beta tool runner, with streamed output and approval-gated writes. |
| `batch_processor.py` | Batch processor: classify, summarize, or run a custom prompt over thousands of items asynchronously via the Message Batches API at 50% of standard token prices. |

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...      # or: ant auth login
```

Offline checks (no API calls):

```bash
python -m unittest discover -s tests -v
```

## `agent.py` — tool-using agent

```bash
python agent.py "Read notes.md, compute the Q3 budget including contingency, and save it to budget.md"
python agent.py                                 # interactive; /reset clears history, /quit exits
python agent.py --effort xhigh --show-thinking "..."
python agent.py --yes "..."                     # approve every write_file without asking
```

What it does, and where to change it:

- **Tools** are plain functions decorated with `@beta_tool`; the SDK builds the JSON schema from the signature and docstring. Add a function, append it to `TOOLS`, done. Descriptions say *when* to call the tool, which is what Claude keys on.
- **The loop** is `client.beta.messages.tool_runner(...)`: it sends the request, runs any tool calls, feeds the results back, and repeats until Claude answers. `max_iterations` caps it (25). Turns stream (`stream=True`), and the transcript is mirrored into `history` so the interactive mode carries context across turns.
- **Safety**: file tools only touch `AGENT_WORKSPACE` (default `./workspace`; path traversal is refused), `write_file` asks for approval on the terminal unless `--yes`, and `calculate` evaluates an AST whitelist rather than `eval`. Tool failures are returned to Claude as `is_error` results (`ToolError`) so it can adapt.
- **Model settings**: adaptive thinking with summarized display (`--show-thinking` prints it), `output_config.effort` (`--effort`, default `high`; `xhigh` suits harder agentic tasks), and top-level `cache_control` so the growing conversation prefix is served from cache.
- **Refusal fallbacks are on by default**: `fallbacks="default"` with the `server-side-fallback-2026-07-01` beta re-runs a policy-declined request on Anthropic's recommended fallback model inside the same call; the turn summary prints `[fallback] served by <model>` when that happened. Pass `--no-fallbacks` to turn it off.
- Every turn prints the stop reason when it is not a clean `end_turn` (`refusal` with category, `max_tokens`, iteration cap) plus token usage including cache reads/writes.

## `batch_processor.py` — Message Batches

```bash
# one shot: submit, poll until done, write results
python batch_processor.py run sample_items.jsonl --task classify --labels positive,negative,neutral -o results.jsonl

# or step by step (state is saved to .batch_state.json so this survives restarts)
python batch_processor.py submit sample_items.jsonl --task summarize --max-words 40
python batch_processor.py status
python batch_processor.py wait --interval 30
python batch_processor.py results -o summaries.jsonl
python batch_processor.py cancel

# custom prompt, optionally with a JSON schema for structured output
python batch_processor.py run items.jsonl --task custom \
    --prompt "Extract the product names mentioned in: {text}" --schema products.schema.json

# a shared reference document goes into the cached system prefix
python batch_processor.py run tickets.jsonl --task classify --labels billing,bug,howto --context-file triage-guide.md
```

Input is JSONL with `id` and `text` fields (or a plain text file, one item per line). Output is JSONL keyed by your `id`, with `output` (a parsed object for structured tasks, text otherwise), `stop_reason`, and refusal details when present; failures go to `<output>.errors.jsonl` with `retryable` set (an `invalid_request_error` needs a fixed request, anything else can be resubmitted as-is).

Design notes:

- Requests over `--chunk-size` (default 10,000) are split into several batches; the API caps a batch at 100,000 requests / 256 MB.
- Results come back in arbitrary order, so everything is keyed by `custom_id`.
- `classify` uses structured outputs (`output_config.format` with a JSON schema whose `label` is an enum), so the output is always valid JSON with `label`, `confidence`, `reason`. It defaults to `--effort low`; `summarize` and `custom` default to `high`.
- The system prompt carries a `cache_control` breakpoint. Caching only engages once the shared prefix exceeds the model's minimum cacheable length, so pair it with `--context-file` when you have shared guidelines or reference material.
- `results` prints total tokens and an estimated cost at batch rates for the models in `PRICING`.
- `fallbacks` is not accepted by the Batches API, so refusals are recorded per item instead.
