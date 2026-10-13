# Warm Hermes worker measurements

Measured on the development host using the pinned, real Hermes core and synthetic
local model replies. No cloud inference, camera access or personal data was used.

Before optimization, six turns through commit `34a4033` took
2,142 / 2,161 / 2,637 / 2,311 / 2,143 / 2,098 ms: a median of **2,152 ms**.
That adapter started and discarded Hermes for every message.

The optimized adapter preloads both construction and conversation code once and
creates a fresh agent for every message inside the loaded worker. Its five warm
turns took **85 / 82 / 82 / 83 / 85 ms**, a median of **83 ms**. Time to the
first model request was 20–23 ms, including the first real turn after preloading.
The local startup overhead therefore fell by approximately **2.07 seconds**
against the original adapter. These are small samples, not a cloud latency SLA.

The same reproducible benchmark also restarted the optimized worker before each
turn, giving a cold median of 2,434 ms. Preloading itself took 2,018 ms, paid once
at backend startup. Cold construction now exercises the conversation path too;
this cold number should not be substituted for the old adapter's baseline.

Reproduce with:

```bash
venv/bin/python -m blob.evals.hermes_latency --turns 5 --output /tmp/blob-hermes-latency.json
```

[Raw results](hermes_latency.json) include startup, first-model, provider and total
timings. Model duration in this evaluation is effectively zero because replies
are synthetic. Actual chats still wait for Nebius and any requested tools.
Worker recovery after cancellation, failure or an idle crash pays startup again;
the interrupted task is never automatically replayed.

After restarting the actual backend, terminal verification confirmed readiness
before the first chat and worker reuse on both messages. Their Hermes runs took
1,862 and 933 ms, of which 1,694 and 845 ms were provider calls. A real reminder
creation-and-listing workflow completed with three model calls, two successful
reminder tools, zero startup wait and a 4,090 ms runtime. Exactly one temporary
reminder was created and then removed; existing reminders were preserved. These
live checks validate the running integration, not a controlled provider-latency
comparison against the previous version.
