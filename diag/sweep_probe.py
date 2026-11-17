"""Sweep director redirects for rare bad caches; run the real cohort query repeatedly."""
import collections, os, socket, ssl, subprocess, sys, time
import duckdb
from toksearch.sql import _snapshot_db as S

BASE = "https://osdf-director.osg-htc.org/fdp-d3d/metadata/d3drdb/"
SNAP = BASE + "d3drdb_20261006T135944Z/"
TOK = os.environ["BEARER_TOKEN"]
CAF = ssl.get_default_verify_paths().cafile
FILES = ["SHOTS.parquet", "SHOTS_TYPE.parquet", "disruption_warning/shots_150000-159999.parquet"]


def p(*a):
    print(*a, flush=True)


def verify(host, port):
    ctx = ssl.create_default_context(cafile=CAF)
    try:
        with socket.create_connection((host, port), timeout=15) as s, \
                ctx.wrap_socket(s, server_hostname=host) as t:
            return "OK " + dict(x[0] for x in t.getpeercert()["issuer"]).get("commonName", "?")
    except Exception as exc:
        return "FAIL " + str(exc)[:160]


def sweep(n):
    seen = collections.Counter()
    for i in range(n):
        f = FILES[i % len(FILES)]
        out = subprocess.run(["curl", "-s", "-o", "/dev/null", "-I", "-H", "Authorization: Bearer " + TOK,
                              "-w", "%{http_code} %{redirect_url}", SNAP + f],
                             capture_output=True, text=True).stdout.split(" ", 1)
        tgt = out[1] if len(out) > 1 else ""
        seen[tgt.split("/")[2] if tgt.count("/") > 2 else "code=" + out[0]] += 1
    for hp, c in seen.most_common():
        host, _, port = hp.partition(":")
        res = verify(host, int(port or 443)) if not hp.startswith("code=") else ""
        p("  sweep {:5d}x {:55s} {}".format(c, hp, res))
        if res.startswith("FAIL") or "SSL.com" in res:
            out = subprocess.run(["openssl", "s_client", "-connect", hp, "-servername", host, "-showcerts"],
                                 input="", capture_output=True, text=True, timeout=30).stdout
            for ln in out.splitlines():
                if ln.strip().startswith(("0 s:", "1 s:", "2 s:", "3 s:", "i:", "Verify return")):
                    p("      ", ln.strip())


COHORT = ("SELECT s.shot, s.entered FROM read_parquet('{0}SHOTS.parquet') s JOIN "
          "read_parquet('{0}SHOTS_TYPE.parquet') t ON s.shot = t.shot WHERE t.shot_type = 'plasma' "
          "AND s.entered BETWEEN '2024-06-01' AND '2024-08-01' ORDER BY s.shot").format(SNAP)


def raw_cohort(i):
    con = S._open_duckdb(duckdb, TOK, BASE)
    con.execute("CALL enable_logging('HTTP')")
    try:
        n = len(con.execute(COHORT).fetchall())
        p("  raw [{}] OK rows={}".format(i, n))
    except Exception as exc:
        p("  raw [{}] FAIL {}".format(i, str(exc).splitlines()[0][:200]))
        try:
            for r in con.execute("SELECT * FROM duckdb_logs_parsed('HTTP')").fetchall()[-12:]:
                p("     log", str(r)[:600])
        except Exception as e2:
            p("     (log read failed: {})".format(e2))
    con.close()


def toolkit_cohort(i):
    import pandas as pd
    from toksearch_d3d.sql import connect_d3drdb
    import warnings
    warnings.simplefilter("ignore")
    try:
        with connect_d3drdb() as conn:
            df = pd.read_sql("SELECT s.shot, s.entered FROM shots s JOIN shots_type t ON s.shot = t.shot "
                             "WHERE t.shot_type = 'plasma' AND s.entered BETWEEN '2024-06-01' AND "
                             "'2024-08-01' ORDER BY s.shot", conn)
        p("  connect_d3drdb [{}] OK rows={}".format(i, len(df)))
    except Exception as exc:
        p("  connect_d3drdb [{}] FAIL {}".format(i, str(exc).splitlines()[0][:200]))


p("cafile", CAF, "duckdb", duckdb.__version__)
t = time.time(); sweep(int(os.environ.get("SWEEP", "400"))); p("  sweep took {:.0f}s".format(time.time() - t))
for i in range(6):
    t = time.time(); raw_cohort(i + 1); p("    ({:.0f}s)".format(time.time() - t))
    t = time.time(); toolkit_cohort(i + 1); p("    ({:.0f}s)".format(time.time() - t))
sweep(200)
