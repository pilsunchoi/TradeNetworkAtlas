"""BACI zip -> CSV 추출 -> DuckDB fact_baci 적재.

fact_baci는 BACI 원본 6열(t,i,j,k,v,q) 그대로. 파생 없음.
dim_source에 파일별 크기·행수·v합계·적재시각을 남긴다.
코드표(country_codes, product_codes)는 raw_* 테이블로 그대로 두고 dim은 02에서 만든다.
"""
import sys
import time
import zipfile
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.settings import (BACI_ZIP, EXTRACT, DB_PATH, PROCESSED, BACI_HS,
                             BACI_VERSION, YEARS, LOGS)
import duckdb


def log(msg):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    LOGS.mkdir(exist_ok=True)
    with open(LOGS / "01_load_baci.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main(force=False):
    assert BACI_ZIP.exists(), f"zip 없음: {BACI_ZIP}"
    PROCESSED.mkdir(parents=True, exist_ok=True)
    EXTRACT.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(BACI_ZIP) as z:
        names = z.namelist()
        log(f"zip 멤버 {len(names)}개: {names[:3]} ... {names[-3:]}")
        for n in names:
            out = EXTRACT / n
            if out.exists() and not force:
                continue
            z.extract(n, EXTRACT)
            log(f"추출 {n}")

    con = duckdb.connect(str(DB_PATH))
    con.execute("""CREATE TABLE IF NOT EXISTS dim_source(
        file VARCHAR PRIMARY KEY, bytes BIGINT, rows BIGINT, sum_v DOUBLE, loaded_at TIMESTAMP)""")
    con.execute("""CREATE TABLE IF NOT EXISTS fact_baci(
        t INTEGER NOT NULL, i INTEGER NOT NULL, j INTEGER NOT NULL, k VARCHAR NOT NULL,
        v DOUBLE, q DOUBLE)""")
    done = {r[0] for r in con.execute("SELECT file FROM dim_source").fetchall()}

    for y in YEARS:
        fn = f"BACI_{BACI_HS}_Y{y}_{BACI_VERSION}.csv"
        p = EXTRACT / fn
        if not p.exists():
            log(f"!! 없음 {fn}")
            continue
        if fn in done and not force:
            log(f"skip {fn} (적재됨)")
            continue
        t0 = time.time()
        con.execute("DELETE FROM fact_baci WHERE t = ?", [y])
        # q에는 'NA'가 올 수 있다. 전부 VARCHAR로 읽은 뒤 캐스팅해 원본 손실을 막는다.
        con.execute(f"""INSERT INTO fact_baci
            SELECT CAST(t AS INTEGER), CAST(i AS INTEGER), CAST(j AS INTEGER), k,
                   TRY_CAST(v AS DOUBLE), TRY_CAST(q AS DOUBLE)
            FROM read_csv('{p.as_posix()}', header=true, all_varchar=true)""")
        rows, sum_v = con.execute("SELECT count(*), sum(v) FROM fact_baci WHERE t = ?", [y]).fetchone()
        csv_rows = con.execute(
            f"SELECT count(*) FROM read_csv('{p.as_posix()}', header=true, all_varchar=true)").fetchone()[0]
        assert rows == csv_rows, f"{fn}: 적재 {rows} != CSV {csv_rows}"
        con.execute("INSERT OR REPLACE INTO dim_source VALUES (?,?,?,?,?)",
                    [fn, p.stat().st_size, rows, sum_v, dt.datetime.now()])
        log(f"{fn}: {rows:,}행, v합 {sum_v/1e6:,.1f}십억$ ({time.time()-t0:.0f}s)")

    for fn, tbl in [(f"country_codes_{BACI_VERSION}.csv", "raw_country_codes"),
                    (f"product_codes_{BACI_HS}_{BACI_VERSION}.csv", "raw_product_codes")]:
        p = EXTRACT / fn
        if p.exists():
            con.execute(f"CREATE OR REPLACE TABLE {tbl} AS "
                        f"SELECT * FROM read_csv('{p.as_posix()}', header=true, all_varchar=true)")
            n = con.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
            cols = [c[0] for c in con.execute(f"DESCRIBE {tbl}").fetchall()]
            log(f"{tbl}: {n}행, 열 {cols}")
        else:
            log(f"!! 코드표 없음 {fn}")

    tot = con.execute("SELECT count(*), min(t), max(t), count(DISTINCT k), count(DISTINCT i) FROM fact_baci").fetchone()
    log(f"fact_baci 합계: {tot[0]:,}행, {tot[1]}-{tot[2]}, HS6 {tot[3]:,}종, 수출국 {tot[4]}")
    con.close()


if __name__ == "__main__":
    main(force="--force" in sys.argv)
