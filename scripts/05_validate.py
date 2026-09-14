"""검증. docs/연구계획_BACI_네트워크.md §6.

1. 적재 대조: dim_source 행수 = fact_baci 연도별 행수.
2. 세계 총액 시계열 출력(WTO와 눈으로 대조).
3. KCSDB2 대조: 한국 수출(BACI i=410) vs 관세청 fact_trade 연도 합계 비율, 2007-2024.
4. 지표 범위 검사.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.settings import DB_PATH, KCSDB_PATH
import duckdb

PASS, WARN, FAIL = [], [], []


def check(name, ok, msg, warn_only=False):
    (PASS if ok else (WARN if warn_only else FAIL)).append(f"{name}: {msg}")


def main():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    # 1
    bad = con.execute("""SELECT s.file, s.rows, f.n FROM dim_source s
        JOIN (SELECT t, count(*) n FROM fact_baci GROUP BY t) f
          ON s.file LIKE '%Y' || f.t || '_%' WHERE s.rows <> f.n""").fetchall()
    check("적재 행수", len(bad) == 0, f"불일치 {len(bad)}건 {bad[:3]}")
    years = con.execute("SELECT count(DISTINCT t), min(t), max(t) FROM fact_baci").fetchone()
    check("연도 범위", years == (30, 1995, 2024), f"{years}")
    nullv = con.execute("SELECT count(*) FROM fact_baci WHERE v IS NULL").fetchone()[0]
    check("v 결측", nullv == 0, f"{nullv}행")
    # 2
    print("\n세계 수출 총액(BACI, 십억$) — WTO 상품수출과 5~10% 낮은 것이 정상")
    for t, v in con.execute("SELECT t, sum(v)/1e6 FROM fact_baci GROUP BY t ORDER BY t").fetchall():
        if t % 5 == 0 or t >= 2022:
            print(f"  {t}: {v:,.0f}")
    # 3
    if KCSDB_PATH.exists():
        con.execute(f"ATTACH '{KCSDB_PATH.as_posix()}' AS k (READ_ONLY)")
        rows = con.execute("""
            WITH b AS (SELECT t, sum(v)*1000 AS baci FROM fact_baci WHERE i = 410 GROUP BY t),
                 c AS (SELECT yyyymm // 100 AS t, sum(exp_dlr) AS kcs FROM k.fact_trade GROUP BY 1)
            SELECT b.t, b.baci/1e9, c.kcs/1e9, b.baci/c.kcs FROM b JOIN c USING(t) ORDER BY t""").fetchall()
        print("\n한국 수출: BACI vs 관세청(십억$, 비율)")
        ratios = []
        for t, b, c, r in rows:
            ratios.append(r)
            if t % 3 == 0 or t >= 2022:
                print(f"  {t}: BACI {b:,.0f}  KCS {c:,.0f}  ratio {r:.3f}")
        spread = max(ratios) - min(ratios)
        check("한국 수출 비율 안정성", spread < 0.15, f"비율 범위 {min(ratios):.3f}~{max(ratios):.3f} (폭 {spread:.3f})", warn_only=True)
        con.execute("DETACH k")
    # 4
    if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='mart_net_metrics'").fetchone()[0]:
        r = con.execute("""SELECT
            sum(CASE WHEN density <= 0 OR density > 1 THEN 1 ELSE 0 END),
            sum(CASE WHEN hhi_exp <= 0 OR hhi_exp > 1 THEN 1 ELSE 0 END),
            sum(CASE WHEN modularity < -0.5 OR modularity > 1 THEN 1 ELSE 0 END),
            sum(CASE WHEN kor_exp_rank IS NOT NULL AND kor_exp_rank < 1 THEN 1 ELSE 0 END),
            count(*) FROM mart_net_metrics""").fetchone()
        check("지표 범위", sum(x or 0 for x in r[:4]) == 0, f"density/hhi/modularity/rank 위반 {r[:4]} / 전체 {r[4]:,}행")
        per = con.execute("SELECT level, variant, count(*) FROM mart_net_metrics GROUP BY 1,2 ORDER BY 1,2").fetchall()
        print("\nmart_net_metrics 행수:", per)
    con.close()
    print("\n=== 결과 ===")
    for tag, lst in (("PASS", PASS), ("WARN", WARN), ("FAIL", FAIL)):
        for s in lst:
            print(f"[{tag}] {s}")
    print(f"PASS {len(PASS)}, WARN {len(WARN)}, FAIL {len(FAIL)}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
