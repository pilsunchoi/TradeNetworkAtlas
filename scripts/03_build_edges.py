"""품목 수준별 엣지 집계 테이블.

edge_total(t, i, j, v), edge_hs2(t, code, i, j, v), edge_hs4(t, code, i, j, v).
fact_baci에서 합만 낸다. 다른 가공 없음. 04가 이 표를 읽는다.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.settings import DB_PATH
import duckdb


def main():
    con = duckdb.connect(str(DB_PATH))
    con.execute("PRAGMA threads=8")
    t0 = time.time()
    con.execute("""CREATE OR REPLACE TABLE edge_total AS
        SELECT t, i, j, sum(v) AS v FROM fact_baci GROUP BY t, i, j ORDER BY t, i, j""")
    print(f"edge_total {con.execute('SELECT count(*) FROM edge_total').fetchone()[0]:,}행 ({time.time()-t0:.0f}s)")
    t0 = time.time()
    con.execute("""CREATE OR REPLACE TABLE edge_hs2 AS
        SELECT t, substr(k, 1, 2) AS code, i, j, sum(v) AS v FROM fact_baci
        GROUP BY t, code, i, j ORDER BY code, t, i, j""")
    print(f"edge_hs2 {con.execute('SELECT count(*) FROM edge_hs2').fetchone()[0]:,}행 ({time.time()-t0:.0f}s)")
    t0 = time.time()
    con.execute("""CREATE OR REPLACE TABLE edge_hs4 AS
        SELECT t, substr(k, 1, 4) AS code, i, j, sum(v) AS v FROM fact_baci
        GROUP BY t, code, i, j ORDER BY code, t, i, j""")
    print(f"edge_hs4 {con.execute('SELECT count(*) FROM edge_hs4').fetchone()[0]:,}행 ({time.time()-t0:.0f}s)")
    con.close()


if __name__ == "__main__":
    main()
