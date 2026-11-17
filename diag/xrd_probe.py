"""Does loading XRootD/Pelican before DuckDB break httpfs TLS on macOS?"""
import ctypes, os, subprocess, sys, time
import duckdb
from toksearch.sql import _snapshot_db as S, snapshot

MODE, ROUNDS = sys.argv[1], int(sys.argv[2])
BASE = "https://osdf-director.osg-htc.org/fdp-d3d/metadata/d3drdb/"
URL = BASE + "d3drdb_20261006T135944Z/SHOTS.parquet"
TOK = os.environ["BEARER_TOKEN"]

if MODE.startswith("xrd"):
    loc = snapshot.locator_for("d3d", "d3drdb")
    print("resolved", loc.base_url, "->", snapshot.resolve_base(loc.base_url), flush=True)
elif MODE == "curlplugin":
    ext = ".dylib" if sys.platform == "darwin" else ".so"
    ctypes.CDLL(os.path.join(sys.prefix, "lib", "libXrdClCurl-5" + ext))


def libs():
    out = subprocess.run(["lsof", "-p", str(os.getpid())], capture_output=True, text=True).stdout
    return sorted({ln.split()[-1].replace(sys.prefix, "$P") for ln in out.splitlines()
                   if any(k in ln for k in ("ssl", "crypto", "curl", "httpfs", "Xrd"))})


ok = fail = 0
for i in range(ROUNDS):
    tgt = subprocess.run(["curl", "-s", "-o", "/dev/null", "-I", "-H", "Authorization: Bearer " + TOK,
                          "-w", "%{redirect_url}", URL], capture_output=True, text=True).stdout
    host = tgt.split("/")[2] if tgt.count("/") > 2 else "?"
    con = S._open_duckdb(duckdb, TOK, BASE)
    if MODE.endswith("httplib"):
        con.execute("SET httpfs_client_implementation = 'httplib'")
    try:
        n = con.execute("SELECT count(*) FROM read_parquet(?)", [URL]).fetchone()[0]
        res, ok = "OK {}".format(n), ok + 1
    except Exception as exc:
        res, fail = "FAIL " + str(exc).splitlines()[0][:90], fail + 1
    con.close()
    if i == 0:
        print("libs:", *libs(), sep="\n  ", flush=True)
    print("  {} [{}] curl-says {} -> {}".format(MODE, i + 1, host, res), flush=True)
    time.sleep(5)
print("SUMMARY {} ok={} fail={}".format(MODE, ok, fail), flush=True)
