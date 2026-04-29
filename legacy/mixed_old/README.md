# legacy/mixed_old

This area is reserved for files that are not part of the canonical orderheatmap
runtime, such as old receiver helpers, TPO scripts, and generated example charts.

They should not be called from the v3.29 production path.

Canonical v3.29 runtime:

```bash
./bin/run_orderflow_once.sh
./bin/run_orderflow_loop.sh
```

Known candidates for a later `git mv` cleanup:

- `bin/start_receiver.sh`
- `bin/ensure_receiver.sh`
- `bin/monitor_receiver.sh`
- `bin/run_tpo*.sh`
- `bin/send_tpo*.sh`
- `artifacts/examples/tpo*.png`
- `artifacts/output/tpo_chart.png`
