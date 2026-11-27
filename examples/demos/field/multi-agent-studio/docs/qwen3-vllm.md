# Qwen3.6 with vLLM

For `nvidia/Qwen3.6-35B-A3B-NVFP4`, disable Qwen's internal thinking by default when using the model as a tool-calling assistant for Multi-Agent Studio. This keeps generated tokens available for tool calls and the final response instead of letting a long reasoning trace consume the response budget.

`--reasoning-parser qwen3` tells vLLM how to parse Qwen reasoning output; it does **not** disable thinking. Set the chat template option separately:

```bash
--default-chat-template-kwargs '{"enable_thinking": false}'
```

## Example launch script

This example follows the Qwen3.6 NVFP4 launch profile used by this project. Activate the environment that contains the pinned vLLM build, then save the following as `start_nonthinking_vllm_Qwen3.6.sh`. Adjust the environment path and hardware-related settings for your machine.

```bash
#!/usr/bin/env bash
set -euo pipefail
source "$HOME/unsloth-nvfp4-env/bin/activate"
export CUTE_DSL_ARCH=sm_121a
export MAX_JOBS=8

exec vllm serve nvidia/Qwen3.6-35B-A3B-NVFP4 \
  --revision 1355db6a052410cfd62085d94b58866fd0f2c3c5 \
  --moe-backend flashinfer_b12x \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 \
  --default-chat-template-kwargs '{"enable_thinking": false}' \
  --host 0.0.0.0 \
  --port 8000 \
  --tensor-parallel-size 1 \
  --trust-remote-code \
  --kv-cache-dtype fp8 \
  --attention-backend flashinfer \
  --gpu-memory-utilization 0.6 \
  --max-model-len 262144 \
  --max-num-seqs 4 \
  --max-num-batched-tokens 8192 \
  --enable-chunked-prefill \
  --async-scheduling \
  --enable-prefix-caching \
  --load-format fastsafetensors
```

The `sm_121a`, FlashInfer, NVFP4, and memory settings are hardware/build-specific; use the settings validated for your GPU and vLLM environment. Restart vLLM after changing launch arguments. In Multi-Agent Studio, connect to `http://127.0.0.1:8000/v1` and select the model ID reported by the server.

`--max-num-batched-tokens 8192` is a vLLM scheduling/batching setting, not the maximum number of tokens an agent may generate in one response. OpenClaw's response-token budget and task timeout are separate controls. Disabling thinking addresses runaway reasoning; it does not increase either OpenClaw limit. For tasks that specifically need Qwen reasoning, change the template value to `true` for that run/profile.

### Mission Control reasoning display

**Advanced reasoning** can display separately returned `reasoning` or `reasoning_content` from configured local servers, with or without an API key. It does not enable thinking or change this preset. With the latency-oriented `enable_thinking: false` setting above, no reasoning text is expected and the panel reports that it is unavailable.

Field names depend on the server version. Current [vLLM protocol code](https://github.com/vllm-project/vllm/blob/main/vllm/entrypoints/openai/chat_completion/protocol.py) uses `reasoning`, while earlier compatible responses may use `reasoning_content`. [llama.cpp's server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) supports a separate reasoning field through `--reasoning-format deepseek`; `none` leaves it in the ordinary answer. The app does not split ordinary answer text or infer reasoning from `<think>` tags.
