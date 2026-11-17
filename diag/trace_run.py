"""Run a test target with every DuckDB snapshot open traced (CA file, SSL env)."""
import os, ssl, sys, runpy
from toksearch.sql import _snapshot_db as S

_orig = S._open_duckdb


def traced(duckdb, token, base=None):
    con = _orig(duckdb, token, base)
    ca = con.execute("SELECT current_setting('ca_cert_file')").fetchone()[0]
    env = {k: v for k, v in os.environ.items() if "SSL" in k or "CERT" in k or "CA_BUNDLE" in k}
    print("\n[trace] open_duckdb verify_paths.cafile={} duckdb.ca_cert_file={} env={}".format(
        ssl.get_default_verify_paths().cafile, ca, env), file=sys.stderr, flush=True)
    return con


S._open_duckdb = traced
if sys.argv[1] == "-m":
    sys.argv = [sys.argv[2]] + sys.argv[3:]
    runpy.run_module(sys.argv[0], run_name="__main__", alter_sys=True)
else:
    sys.argv = sys.argv[1:]
    runpy.run_path(sys.argv[0], run_name="__main__")
