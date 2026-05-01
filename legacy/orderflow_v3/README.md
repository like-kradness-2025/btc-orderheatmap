# legacy/orderflow_v3

Historical renderer implementations kept only as git history/reference.

These files are not the canonical runtime entrypoints for v3.30. New operation must use:

```bash
./bin/run_orderflow_once.sh
./bin/run_orderflow_loop.sh
python3 -m orderflow.renderer
```

v3.30 replaced the historical version-number import chain with role-based modules under `vendor/orderflow_pack/orderflow/`:

- `engine_v330.py` — execution orchestration
- `runtime_v330.py` — shared config/data/base drawing helpers
- `absorption_v330.py` — absorption marker calculation
- `oi_v330.py` — OI loading/aggregation/subplot helpers
- `plot_v330.py` — final chart composition

Removed historical runtime files:

- `vendor/orderflow_pack/orderflow/chartProt3_ws_layered_v3.py`
- `vendor/orderflow_pack/orderflow/chartProt3_ws_layered_v322.py`
- `vendor/orderflow_pack/orderflow/chartProt3_ws_layered_v323.py`
- `vendor/orderflow_pack/orderflow/chartProt3_ws_layered_v323a.py`
- `vendor/orderflow_pack/orderflow/chartProt3_ws_layered_v327.py`
- `vendor/orderflow_pack/orderflow/chartProt3_ws_compat_v2.py`
- `vendor/orderflow_pack/orderflow/absorption_overlay_v2.py`
- `vendor/orderflow_pack/run_plot_v323a.sh`
- `vendor/orderflow_pack/run_plot_v327.sh`

Do not call historical versioned files directly from new scripts.
