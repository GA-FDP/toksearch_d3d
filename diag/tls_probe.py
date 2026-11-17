"""Throwaway: why do macOS DuckDB reads of the d3drdb snapshot fail TLS?"""
import os
import platform
import socket
import ssl
import subprocess
import sys
import time
from urllib.parse import urlsplit

import duckdb
from toksearch.sql import _snapshot_db as S

BASE = "https://osdf-director.osg-htc.org/fdp-d3d/metadata/d3drdb/"
URL = BASE + "d3drdb_20261006T135944Z/SHOTS.parquet"
TOK = os.environ["BEARER_TOKEN"]
ROUNDS = int(os.environ.get("ROUNDS", "15"))
PAUSE = float(os.environ.get("PAUSE", "20"))
SYSTEM_BUNDLES = ["/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"]


def p(*a):
    print(*a, flush=True)


def redirect_target():
    out = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-I", "-H", "Authorization: Bearer " + TOK,
         "-w", "%{http_code} %{redirect_url}", URL],
        capture_output=True, text=True, timeout=60)
    return out.stdout.strip()


def verify(host, port, cafile):
    ctx = ssl.create_default_context(cafile=cafile)
    try:
        with socket.create_connection((host, port), timeout=20) as s:
            with ctx.wrap_socket(s, server_hostname=host) as t:
                c = t.getpeercert()
                issuer = dict(x[0] for x in c["issuer"])
                return "OK issuer={} notAfter={}".format(issuer.get("commonName"), c["notAfter"])
    except Exception as exc:
        return "FAIL " + str(exc)[:200]


def chain(host, port):
    out = subprocess.run(
        ["openssl", "s_client", "-connect", "{}:{}".format(host, port),
         "-servername", host, "-showcerts"],
        input="", capture_output=True, text=True, timeout=30)
    return [ln.strip() for ln in out.stdout.splitlines()
            if ln.strip().startswith(("0 s:", "1 s:", "2 s:", "3 s:", "i:", "s:"))]


def duck(url, scope, impl=None):
    con = S._open_duckdb(duckdb, None, BASE)
    con.execute(S._create_secret(TOK, scope))
    if impl:
        try:
            con.execute("SET httpfs_client_implementation = '{}'".format(impl))
        except Exception as exc:
            con.close()
            return "SKIP " + str(exc).splitlines()[0][:120]
    logging = True
    try:
        con.execute("CALL enable_logging('HTTP')")
    except Exception as exc:
        logging = False
        p("    (no HTTP logging: {})".format(str(exc)[:120]))
    try:
        n = con.execute("SELECT count(*) FROM read_parquet(?)", [url]).fetchone()[0]
        res = "OK rows={}".format(n)
    except Exception as exc:
        res = "FAIL " + str(exc).splitlines()[0][:220]
    if logging:
        try:
            rows = con.execute(
                "SELECT request.type, request.url, response.status, response.reason "
                "FROM duckdb_logs_parsed('HTTP')").fetchall()
            for r in rows[:8]:
                p("    http:", r)
        except Exception as exc:
            p("    (log read failed: {})".format(str(exc)[:160]))
    con.close()
    return res


def main():
    vp = ssl.get_default_verify_paths()
    p("platform", platform.platform(), "python", sys.version.split()[0],
      "duckdb", duckdb.__version__, "openssl", ssl.OPENSSL_VERSION)
    p("verify paths", vp)
    p("cafile exists:", bool(vp.cafile) and os.path.exists(vp.cafile))
    for b in SYSTEM_BUNDLES:
        p("system bundle", b, os.path.exists(b))
    con = S._open_duckdb(duckdb, None, BASE)
    for r in con.execute(
            "SELECT name, value FROM duckdb_settings() WHERE name ILIKE '%ca_cert%' "
            "OR name ILIKE '%httpfs%' OR name ILIKE '%http_%'").fetchall():
        p("setting", r)
    for r in con.execute(
            "SELECT extension_name, extension_version, install_mode, installed_from "
            "FROM duckdb_extensions() WHERE loaded").fetchall():
        p("extension", r)
    con.close()

    impls = [None]
    if sys.platform == "darwin":
        impls = [None, "httplib", "curl"]
    system = next((b for b in SYSTEM_BUNDLES if os.path.exists(b)), None)
    for i in range(ROUNDS):
        p("\n=== round {} {}".format(i + 1, time.strftime("%H:%M:%S")))
        r = redirect_target()
        p("  director ->", r)
        target = r.split(" ", 1)[1] if " " in r else ""
        if target:
            u = urlsplit(target)
            host, port = u.hostname, u.port or 443
            p("  py-ssl conda :", verify(host, port, vp.cafile))
            if system:
                p("  py-ssl system:", verify(host, port, system))
            for ln in chain(host, port):
                p("  chain", ln)
        for impl in impls:
            p("  duckdb via director impl={}: {}".format(impl, duck(URL, BASE, impl)))
        if target:
            scope = "{}://{}/".format(u.scheme, u.netloc)
            p("  duckdb direct to cache: {}".format(duck(target.split("?")[0], scope)))
        time.sleep(PAUSE)


if __name__ == "__main__":
    main()
