# Dragon versus Mac inference speed

Measured October 2, 2026 (America/Los_Angeles). Keep Mac-local inference for the current Goose configuration: at its 131,072-token context allocation the Mac generates about **1.74 times as many tokens per second** as Dragon. Dragon is about 19–21% faster at the smaller 8k and 32k allocations.

| Context allocation | Mac decode tokens/s | Dragon decode tokens/s | Mac request seconds | Dragon request seconds | Mac prefill tokens/s | Dragon prefill tokens/s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 8,192 | 34.68 | 42.04 | 5.54 | 4.41 | 669 | 1,001 |
| 32,768 | 36.70 | 43.80 | 5.34 | 4.28 | 670 | 1,018 |
| 131,072 | 32.73 | 18.83 | 5.76 | 8.52 | 672 | 774 |

Values are medians of two warmed requests per endpoint and context. Each paired request uses exactly the same synthetic prompt and settings, with 1,203–1,204 prompt tokens and exactly 128 generated tokens. Wall time includes the HTTP round trip and a small post-request `/api/ps` inspection. Token throughput uses Ollama's separate evaluation durations, rather than wall time. Host order alternates between trials. The prompt varies near its beginning between trials to avoid reusing an entire cached prefix.

Both endpoints advertise the exact same `qwen3.8:27b` digest, `aaee06c39dcf2437cde036998d960e1fc1494b8191be7cc9657d01e509097813`: 27.3B parameters, Q4_K_M weights. Settings were `think=false`, `temperature=0`, `seed=42`, `num_predict=128`. The Mac is an M5 Max Mac Studio with 64 GB memory. Ollama versions differ: Mac 0.34.4, Dragon 0.35.0. The Mac's previously inspected server configuration specifies Q8 KV cache; Dragon's Q8 setting is user-reported. This test does not independently inspect Dragon's runner configuration or GPU model.

Both were initially unloaded. At 8k the first request took 9.51 seconds on the Mac and 12.07 seconds on Dragon, including reported load times of 3.57 and 7.37 seconds respectively. Increasing context caused new runner loads; those first requests are excluded from the warmed table.

At 8k and 32k, both `/api/ps` responses report `size_vram == size`. At 128k, the Mac reports 18.47 GB for both fields, while Dragon reports 19.05 GB total and 16.29 GB in VRAM. The 2.76 GB difference is consistent with partial host-memory allocation/offload and accompanies Dragon's decode slowdown. The API does not establish which tensors or operations moved to the CPU; runner logs would be needed to confirm that mechanism.

This is a short-input speed assay, not a full Goose conversation or accuracy evaluation. Allocating a 128k context does not mean processing a 128k prompt. Sustained long-context prefill, concurrent requests, tool calls, thinking output, network outages, and judging quality remain unmeasured. The servers are left with the benchmark model resident for the requested ten-minute keep-alive; no configuration changes or model downloads were made.

Reproduce from the repository:

```sh
python3 scripts/benchmark-ollama-speed
python3 scripts/benchmark-ollama-speed --contexts 131072 --output work/speed-benchmark/results-128k.json
```

Raw timings, messages, digests, settings and allocation snapshots are saved in `work/speed-benchmark/results.json` and `work/speed-benchmark/results-128k.json`. The script checks matching model digests, writes each completed result immediately, and stops without an automatic inference retry on a request error. All 18 requests completed successfully; the script also passes Python compilation.
