# Public UI v23

Keep one top-level menu toggle; remove the duplicate rail header button. Toggle announces its actual state. The right pane has a stationary header and independent scroll content; guest desktop split is laid out before JS.

Opt-in guest state responses bundle quota and history with session start and successful turns; legacy response contracts are retained. Guest state reads use one read-only SQLite transaction. Public panel navigation uses a small JSON fragment with identical SSR content and metadata. Only public, static information is cached in page memory; pricing, FAQ and auth panels remain fresh. Existing access boundaries and quota unchanged.

Benchmark: isolated Chromium, simulated 150 ms network latency, 3 repeats per revision. Initial requests 7 -> 6; static navigation contacts/about/contacts/about 4 -> 1. Successful guest turn avoids follow-up history GET. Concurrent QA and unattended OS upgrade caused severe CPU pressure; timings and scroll frame measurements are not a clean A/B and cannot prove improvement in client scrolling. No system jobs stopped and no global styles/scale or Octoport modified.
