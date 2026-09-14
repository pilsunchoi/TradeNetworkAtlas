"""품목×연도 네트워크 지표 계산 → mart_net_metrics, mart_net_nodes.

사용:
  python scripts/04_compute_metrics.py --level total
  python scripts/04_compute_metrics.py --level hs2
  python scripts/04_compute_metrics.py --level hs4 --workers 6

정의는 docs/연구계획_BACI_네트워크.md §4. 정의를 바꾸면 그 문서를 먼저 고친다.
변형: raw(모든 흐름), w1m(v >= 1,000 천달러 = 100만 달러 이상).
"""
import sys
import time
import argparse
import warnings

warnings.filterwarnings("ignore", category=RuntimeWarning)  # igraph HITS의 "30% zeros" 경고
import datetime as dt
from pathlib import Path
from multiprocessing import Pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.settings import DB_PATH, LOGS, ROOT

INTERIM = ROOT / "data" / "interim"
import numpy as np
import pandas as pd
import duckdb
import igraph as ig
import leidenalg as la

KOR = 410
# 변형: (가중치 하한 v, 고정 국가군 제한 여부, 제외 국가 코드). 정의는 연구계획 §3.
CHN = 156
VARIANTS = {"raw": (0.0, False, frozenset()), "w1m": (1000.0, False, frozenset()),
            "w1m_bal": (1000.0, True, frozenset()), "w1m_bal_xchn": (1000.0, True, frozenset({CHN}))}
NODE_KEEP_HS4 = 30  # hs4 수준에서 노드 표에 남길 상위 국가 수(+한국)

METRIC_COLS = ["level", "code", "t", "variant", "n_nodes", "n_edges", "total_value", "density", "reciprocity",
               "hhi_exp", "hhi_imp", "top5_exp_share", "top5_imp_share", "gini_out_strength", "gini_in_strength",
               "centralization_out", "centralization_in", "clustering_avg", "assortativity_deg",
               "n_communities", "modularity", "max_kcore", "intra_region_share",
               "kor_exp_share", "kor_exp_rank", "kor_imp_share", "kor_imp_rank",
               "kor_pagerank_rank", "kor_hub_rank", "kor_n_dest", "kor_hhi_dest"]
NODE_COLS = ["level", "code", "t", "variant", "country_code", "out_strength", "in_strength", "out_degree", "in_degree",
             "pagerank", "hub", "authority", "betweenness", "community", "kcore"]


def gini(x):
    x = np.sort(np.asarray(x, dtype=float))
    n = len(x)
    if n == 0 or x.sum() == 0:
        return np.nan
    cum = np.cumsum(x)
    return float((n + 1 - 2 * (cum / cum[-1]).sum()) / n)


def hhi(x):
    x = np.asarray(x, dtype=float)
    s = x.sum()
    return float(((x / s) ** 2).sum()) if s > 0 else np.nan


def top_share(x, k=5):
    x = np.sort(np.asarray(x, dtype=float))[::-1]
    s = x.sum()
    return float(x[:k].sum() / s) if s > 0 else np.nan


def rank_desc(values, idx):
    """values 중 idx 위치 값의 내림차순 순위(1이 최대). idx가 None이면 None."""
    if idx is None:
        return None
    v = np.asarray(values, dtype=float)
    return int((v > v[idx]).sum() + 1)


def centralization(deg, n):
    deg = np.asarray(deg, dtype=float)
    if n < 3:
        return np.nan
    return float((deg.max() - deg).sum() / ((n - 1) * (n - 1)))


def metrics_for(level, code, t, edges, region_of, fixed=None, variants=None):
    """edges: DataFrame(i, j, v). 변형별 (metric row, node rows) 반환.
    fixed: 고정 국가군(set). None이면 bal 변형을 건너뛴다. variants: 계산할 변형 이름 목록(None이면 전부)."""
    out_m, out_n = [], []
    for variant, (wmin, bal, excl) in VARIANTS.items():
        if variants and variant not in variants:
            continue
        if bal and not fixed:
            continue
        e = edges[edges.v >= wmin] if wmin > 0 else edges
        if bal:
            e = e[e.i.isin(fixed) & e.j.isin(fixed)]
        if excl:
            e = e[~e.i.isin(excl) & ~e.j.isin(excl)]
        if len(e) == 0:
            continue
        nodes = pd.unique(pd.concat([e.i, e.j], ignore_index=True))
        idx = {c: n for n, c in enumerate(nodes)}
        n = len(nodes)
        g = ig.Graph(n=n, edges=list(zip(e.i.map(idx), e.j.map(idx))), directed=True)
        g.es["weight"] = e.v.values.astype(float)
        g.vs["code"] = list(nodes)
        out_s = np.array(g.strength(mode="out", weights="weight"))
        in_s = np.array(g.strength(mode="in", weights="weight"))
        out_d = np.array(g.degree(mode="out"))
        in_d = np.array(g.degree(mode="in"))
        total = float(e.v.sum())
        m = len(e)
        # 무방향 가중 그래프 (양방향 합)
        gu = g.as_undirected(mode="collapse", combine_edges="sum")
        try:
            part = la.find_partition(gu, la.ModularityVertexPartition, weights="weight", seed=0)
            n_comm, modularity, membership = len(part), float(part.quality()), part.membership
        except Exception:
            n_comm, modularity, membership = None, np.nan, [None] * n
        pr = np.array(g.pagerank(weights="weight", directed=True))
        try:
            hubs = np.array(g.hub_score(weights="weight"))
            auth = np.array(g.authority_score(weights="weight"))
        except Exception:
            hubs, auth = np.full(n, np.nan), np.full(n, np.nan)
        btw = np.array(g.betweenness(directed=True))
        core = np.array(gu.coreness())
        try:
            assort = float(gu.assortativity_degree(directed=False))
        except Exception:
            assort = np.nan
        # 지역 내 비중
        ri = e.i.map(region_of)
        rj = e.j.map(region_of)
        known = ri.notna() & rj.notna()
        intra = float(e.v[known & (ri == rj)].sum() / e.v[known].sum()) if e.v[known].sum() > 0 else np.nan
        k = idx.get(KOR)
        if k is not None:
            dest = e[e.i == KOR]
            kor_n_dest, kor_hhi_dest = int(len(dest)), hhi(dest.v)
        else:
            kor_n_dest, kor_hhi_dest = 0, np.nan
        out_m.append(dict(
            level=level, code=code, t=t, variant=variant, n_nodes=n, n_edges=m, total_value=total,
            density=m / (n * (n - 1)) if n > 1 else np.nan,
            reciprocity=float(g.reciprocity(mode="ratio")) if m > 0 else np.nan,
            hhi_exp=hhi(out_s), hhi_imp=hhi(in_s), top5_exp_share=top_share(out_s), top5_imp_share=top_share(in_s),
            gini_out_strength=gini(out_s), gini_in_strength=gini(in_s),
            centralization_out=centralization(out_d, n), centralization_in=centralization(in_d, n),
            clustering_avg=float(gu.transitivity_avglocal_undirected(mode="zero")) if n > 2 else np.nan,
            assortativity_deg=assort, n_communities=n_comm, modularity=modularity, max_kcore=int(core.max()),
            intra_region_share=intra,
            kor_exp_share=float(out_s[k] / total) if k is not None else 0.0, kor_exp_rank=rank_desc(out_s, k),
            kor_imp_share=float(in_s[k] / total) if k is not None else 0.0, kor_imp_rank=rank_desc(in_s, k),
            kor_pagerank_rank=rank_desc(pr, k), kor_hub_rank=rank_desc(hubs, k) if k is not None and not np.isnan(hubs).all() else None,
            kor_n_dest=kor_n_dest, kor_hhi_dest=kor_hhi_dest))
        keep = np.arange(n)
        if level == "hs4":
            order = np.argsort(-(out_s + in_s))[:NODE_KEEP_HS4]
            keep = np.unique(np.concatenate([order, [k]])) if k is not None else order
        for x in keep:
            out_n.append((level, code, t, variant, int(nodes[x]), float(out_s[x]), float(in_s[x]), int(out_d[x]), int(in_d[x]),
                          float(pr[x]), float(hubs[x]), float(auth[x]), float(btw[x]),
                          None if membership[x] is None else int(membership[x]), int(core[x])))
    return out_m, out_n


def export_edges(con, level, force=False):
    """DuckDB의 edge 표를 parquet로 내보낸다. 워커는 DB 파일을 열지 않고 이것을 읽는다
    (DuckDB는 쓰기 연결이 열린 파일을 다른 연결이 읽기 전용으로 열 수 없다)."""
    out = INTERIM / f"edge_{level}"
    if out.exists() and not force:
        return out
    out.mkdir(parents=True, exist_ok=True)
    if level == "total":
        con.execute(f"COPY (SELECT t, i, j, v FROM edge_total) TO '{(out / 'all.parquet').as_posix()}' (FORMAT PARQUET)")
    else:
        con.execute(f"COPY (SELECT t, code, i, j, v FROM edge_{level}) TO '{out.as_posix()}' "
                    f"(FORMAT PARQUET, PARTITION_BY (code), OVERWRITE_OR_IGNORE)")
    return out


def fixed_country_set(con):
    """고정 국가군: 1995-2024년 매년 수출과 수입이 모두 양인 국가 (edge_total 기준)."""
    rows = con.execute("""
        WITH ex AS (SELECT i AS c FROM (SELECT DISTINCT t, i FROM edge_total) GROUP BY i HAVING count(*) = (SELECT count(DISTINCT t) FROM edge_total)),
             im AS (SELECT j AS c FROM (SELECT DISTINCT t, j FROM edge_total) GROUP BY j HAVING count(*) = (SELECT count(DISTINCT t) FROM edge_total))
        SELECT c FROM ex WHERE c IN (SELECT c FROM im) ORDER BY c""").fetchall()
    return frozenset(r[0] for r in rows)


def work(args):
    level, code, region_of, edge_dir, fixed, variants = args
    edge_dir = Path(edge_dir)
    if level == "total":
        src = (edge_dir / "all.parquet").as_posix()
    else:
        src = (edge_dir / f"code={code}" / "*.parquet").as_posix()
    df = duckdb.sql(f"SELECT t, i, j, v FROM read_parquet('{src}') ORDER BY t").df()
    rows_m, rows_n = [], []
    for t, grp in df.groupby("t", sort=True):
        m, nn = metrics_for(level, code, int(t), grp[["i", "j", "v"]].reset_index(drop=True), region_of, fixed, variants)
        rows_m += m
        rows_n += nn
    return rows_m, rows_n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", required=True, choices=["total", "hs2", "hs4"])
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0, help="테스트용: 앞의 N개 코드만")
    ap.add_argument("--reexport", action="store_true", help="edge parquet를 다시 내보낸다(03을 다시 돌린 뒤)")
    ap.add_argument("--variants", default="", help="쉼표로 구분한 변형 이름. 지정하면 그 변형만 지우고 다시 계산")
    a = ap.parse_args()
    con = duckdb.connect(str(DB_PATH))
    rdf = con.execute("SELECT country_code, region FROM dim_country").df()
    region_of = dict(zip(rdf.country_code, rdf.region))
    edge_dir = export_edges(con, a.level, force=a.reexport)
    print(f"edge parquet: {edge_dir}", flush=True)
    fixed = fixed_country_set(con)
    print(f"고정 국가군(w1m_bal): {len(fixed)}개국", flush=True)
    con.execute("CREATE OR REPLACE TABLE dim_fixed_country AS SELECT unnest(?) AS country_code", [sorted(fixed)])
    if a.level == "total":
        codes = ["ALL"]
    else:
        codes = [r[0] for r in con.execute(f"SELECT DISTINCT code FROM edge_{a.level} ORDER BY code").fetchall()]
    if a.limit:
        codes = codes[:a.limit]
    con.execute(f"""CREATE TABLE IF NOT EXISTS mart_net_metrics ({', '.join(
        f'{c} VARCHAR' if c in ('level','code','variant') else f'{c} DOUBLE' if c not in ('t','n_nodes','n_edges','n_communities','max_kcore','kor_exp_rank','kor_imp_rank','kor_pagerank_rank','kor_hub_rank','kor_n_dest') else f'{c} INTEGER'
        for c in METRIC_COLS)})""")
    con.execute(f"""CREATE TABLE IF NOT EXISTS mart_net_nodes (level VARCHAR, code VARCHAR, t INTEGER, variant VARCHAR,
        country_code INTEGER, out_strength DOUBLE, in_strength DOUBLE, out_degree INTEGER, in_degree INTEGER,
        pagerank DOUBLE, hub DOUBLE, authority DOUBLE, betweenness DOUBLE, community INTEGER, kcore INTEGER)""")
    variants = [v for v in a.variants.split(",") if v] or None
    if variants:
        unknown = set(variants) - set(VARIANTS)
        assert not unknown, f"모르는 변형: {unknown}"
    if not a.limit:
        if variants:
            con.execute("DELETE FROM mart_net_metrics WHERE level = ? AND variant IN (SELECT unnest(?))", [a.level, variants])
            con.execute("DELETE FROM mart_net_nodes WHERE level = ? AND variant IN (SELECT unnest(?))", [a.level, variants])
        else:
            con.execute("DELETE FROM mart_net_metrics WHERE level = ?", [a.level])
            con.execute("DELETE FROM mart_net_nodes WHERE level = ?", [a.level])
    t0 = time.time()
    tasks = [(a.level, c, region_of, str(edge_dir), fixed, variants) for c in codes]
    done = 0

    def flush(rows_m, rows_n):
        if rows_m:
            dm = pd.DataFrame(rows_m)[METRIC_COLS]
            con.register("dm", dm)
            con.execute("INSERT INTO mart_net_metrics SELECT * FROM dm")
            con.unregister("dm")
        if rows_n:
            dn = pd.DataFrame(rows_n, columns=NODE_COLS)
            con.register("dn", dn)
            con.execute("INSERT INTO mart_net_nodes SELECT * FROM dn")
            con.unregister("dn")

    if a.workers > 1:
        with Pool(a.workers) as pool:
            for rows_m, rows_n in pool.imap_unordered(work, tasks, chunksize=4):
                flush(rows_m, rows_n)
                done += 1
                if done % 50 == 0 or done == len(tasks):
                    print(f"{a.level}: {done}/{len(tasks)} codes ({time.time()-t0:.0f}s)", flush=True)
    else:
        for task in tasks:
            rows_m, rows_n = work(task)
            flush(rows_m, rows_n)
            done += 1
            if done % 10 == 0 or done == len(tasks):
                print(f"{a.level}: {done}/{len(tasks)} codes ({time.time()-t0:.0f}s)", flush=True)
    nm = con.execute("SELECT count(*) FROM mart_net_metrics WHERE level = ?", [a.level]).fetchone()[0]
    nn = con.execute("SELECT count(*) FROM mart_net_nodes WHERE level = ?", [a.level]).fetchone()[0]
    print(f"완료 {a.level}: metrics {nm:,}행, nodes {nn:,}행, {time.time()-t0:.0f}s")
    LOGS.mkdir(exist_ok=True)
    with open(LOGS / "04_compute_metrics.log", "a", encoding="utf-8") as f:
        f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {a.level} metrics={nm} nodes={nn} sec={time.time()-t0:.0f}\n")
    con.close()


if __name__ == "__main__":
    main()
