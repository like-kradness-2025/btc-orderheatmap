# legacy/orderflow_v3

Historical renderer implementations kept for reference and rollback.

These files are not the canonical runtime entrypoints for v3.29. New operation
must use:

```bash
./bin/run_orderflow_once.sh
./bin/run_orderflow_loop.sh
python3 -m orderflow.renderer
```

Current v3.29 keeps the historical rendering behavior behind a stable internal
alias while removing versioned filenames from the public runtime path.

Known historical files to move here in a local 5S sweep when file moves are
performed with `git mv`:

- `vendor/orderflow_pack/orderflow/chartProt3_ws_layered_v3.py`
- `vendor/orderflow_pack/orderflow/chartProt3_ws_layered_v322.py`
- `vendor/orderflow_pack/orderflow/chartProt3_ws_layered_v323.py`
- `vendor/orderflow_pack/orderflow/chartProt3_ws_layered_v323a.py`
- `vendor/orderflow_pack/orderflow/chartProt3_ws_layered_v327.py`
- `vendor/orderflow_pack/orderflow/chartProt3_ws_compat.py`
- `vendor/orderflow_pack/orderflow/chartProt3_ws_compat_v2.py`
- `vendor/orderflow_pack/orderflow/absorption_overlay_v2.py`
- `vendor/orderflow_pack/run_plot.sh`
- `vendor/orderflow_pack/run_plot_v2.sh`
- `vendor/orderflow_pack/run_plot_v323a.sh`
- `vendor/orderflow_pack/run_plot_v327.sh`

Do not call these files directly from new scripts.
