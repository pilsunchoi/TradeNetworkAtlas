"""중국 허브화 추세의 전환점과 중국 제외 세계의 전환점.

1. 중국 시계열(w1m_bal, HS4): 1위 수출국인 품목 비율, 최대 연결국인 품목 비율, 품목 중위·평균 점유율
   → 단일 기울기 단절점(연속 구간선형, SSE 최소) 추정. 5년 구간별 변화.
2. 품목별 중국 점유율(3년 이동평균)의 정점 연도 분포. 정점 통과 품목(2024 < 정점×0.9, 정점 ≤ 2021)의 비율. 부별.
3. 중국 1위 지위의 획득·상실 건수(5년 구간).
4. 중국 제외 세계(w1m_bal_xchn): HHI·상위5·모듈성·차수 중심화·역내 비중의 품목 중위 시계열 → 같은 단절점 추정.
산출: analysis/china_turn/
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.settings import DB_PATH, ROOT
import duckdb
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False
CHN = 156
OUT = ROOT / "analysis" / "china_turn"


def break_fit(years, y, lo=2000, hi=2019):
    """연속 구간선형 y = a + b1*(t-t0) + b2*max(t-b,0). SSE 최소 단절점 b와 기울기."""
    t = np.asarray(years, float); y = np.asarray(y, float)
    best = None
    for b in range(lo, hi + 1):
        X = np.c_[np.ones_like(t), t - t[0], np.maximum(t - b, 0)]
        beta, res, *_ = np.linalg.lstsq(X, y, rcond=None)
        sse = ((y - X @ beta) ** 2).sum()
        if best is None or sse < best[0]:
            best = (sse, b, beta)
    sse, b, beta = best
    X0 = np.c_[np.ones_like(t), t - t[0]]
    beta0, *_ = np.linalg.lstsq(X0, y, rcond=None)
    sse0 = ((y - X0 @ beta0) ** 2).sum()
    return dict(break_year=b, slope_before=beta[1], slope_after=beta[1] + beta[2], sse_ratio=sse / sse0)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    con.execute("PRAGMA threads=8")
    ex = con.execute(f"""
        SELECT t, code, i, sum(v) AS x, count(*) AS d FROM edge_hs4
        WHERE v >= 1000 AND i IN (SELECT country_code FROM dim_fixed_country) AND j IN (SELECT country_code FROM dim_fixed_country)
        GROUP BY 1, 2, 3""").df()
    ex["s"] = ex.x / ex.groupby(["t", "code"]).x.transform("sum")
    sec = con.execute("SELECT DISTINCT hs4, section_name FROM dim_product").df().drop_duplicates("hs4").set_index("hs4").section_name
    top = ex.sort_values(["t", "code", "x"], ascending=[True, True, False]).groupby(["t", "code"]).head(1)
    topd = ex.sort_values(["t", "code", "d", "x"], ascending=[True, True, False, False]).groupby(["t", "code"]).head(1)
    chn = ex[ex.i == CHN]
    years = sorted(ex.t.unique())
    S = pd.DataFrame(index=years)
    S["top1_share"] = top.groupby("t").apply(lambda g: (g.i == CHN).mean())
    S["topdeg_share"] = topd.groupby("t").apply(lambda g: (g.i == CHN).mean())
    S["chn_median_share"] = chn.groupby("t").s.median()
    S["chn_mean_share"] = chn.groupby("t").s.mean()
    # 중국 제외 세계 지표
    xm = con.execute("SELECT t, code, hhi_exp, top5_exp_share, modularity, centralization_out, intra_region_share, gini_out_strength "
                     "FROM mart_net_metrics WHERE level='hs4' AND variant='w1m_bal_xchn'").df()
    for c in ["hhi_exp", "top5_exp_share", "modularity", "centralization_out", "intra_region_share", "gini_out_strength"]:
        S[f"x_{c}"] = xm.groupby("t")[c].median()
    S.to_csv(OUT / "series.csv", encoding="utf-8-sig")
    lines = ["# 중국 허브화의 전환점", ""]
    # 1. 단절점
    lines += ["## 1. 단일 기울기 단절점 (연속 구간선형, 1995–2024, 후보 2000–2019)", "",
              "| 계열 | 단절 연도 | 이전 기울기(연) | 이후 기울기(연) | SSE 비(단절/직선) |", "|---|---|---|---|---|"]
    names = {"top1_share": "중국이 1위 수출국인 품목 비율", "topdeg_share": "중국이 최대 연결국인 품목 비율",
             "chn_median_share": "중국 점유율 품목 중위", "chn_mean_share": "중국 점유율 품목 평균",
             "x_hhi_exp": "중국 제외 HHI 중위", "x_top5_exp_share": "중국 제외 상위5 점유율 중위",
             "x_modularity": "중국 제외 모듈성 중위", "x_centralization_out": "중국 제외 차수 중심화 중위",
             "x_intra_region_share": "중국 제외 역내 비중 중위", "x_gini_out_strength": "중국 제외 수출 지니 중위"}
    fits = {}
    for c, nm in names.items():
        f = break_fit(S.index, S[c]); fits[c] = f
        lines.append(f"| {nm} | {f['break_year']} | {f['slope_before']:+.4f} | {f['slope_after']:+.4f} | {f['sse_ratio']:.2f} |")
    lines.append("")
    # 5년 구간 변화
    lines += ["## 2. 5년 구간별 변화 (구간 끝 − 시작)", "", "| 구간 | 1위 품목 비율 | 최대연결 품목 비율 | 중국 점유율 중위 | 중국 제외 HHI | 중국 제외 모듈성 | 중국 제외 상위5 |", "|---|---|---|---|---|---|---|"]
    for a, b in [(1995, 2000), (2000, 2005), (2005, 2010), (2010, 2015), (2015, 2019), (2019, 2024)]:
        d = S.loc[b] - S.loc[a]
        lines.append(f"| {a}→{b} | {d.top1_share:+.3f} | {d.topdeg_share:+.3f} | {d.chn_median_share:+.3f} | {d.x_hhi_exp:+.4f} | {d.x_modularity:+.4f} | {d.x_top5_exp_share:+.4f} |")
    lines.append("")
    # 3. 품목별 정점 연도
    piv = chn.pivot_table(index="code", columns="t", values="s", fill_value=0.0)
    piv = piv.reindex(columns=years, fill_value=0.0)
    ma = piv.T.rolling(3, center=True, min_periods=2).mean().T
    peak_year = ma.idxmax(axis=1); peak_val = ma.max(axis=1); last = ma[years[-1]]
    ever = peak_val >= 0.05  # 중국 점유율이 한 번이라도 5% 이상이었던 품목만
    past = (last < 0.9 * peak_val) & (peak_year <= 2021) & ever
    pk = pd.DataFrame({"peak_year": peak_year, "peak": peak_val, "last": last, "past_peak": past, "ever5": ever})
    pk["section"] = pk.index.map(sec)
    pk.to_csv(OUT / "china_peak_by_product.csv", encoding="utf-8-sig")
    hist = pk[ever].peak_year.value_counts().sort_index()
    lines += [f"## 3. 품목별 중국 점유율(3년 이동평균) 정점 연도 — 점유율이 한 번이라도 5% 이상이었던 {int(ever.sum())}개 호", "",
              "| 정점 연도 | 품목 수 | 누적 비율 |", "|---|---|---|"]
    cum = 0
    for y, n in hist.items():
        cum += n
        if y % 2 == 0 or y >= 2019:
            lines.append(f"| {y} | {n} | {cum / ever.sum():.0%} |")
    lines += ["", f"정점 통과(2024 이동평균 < 정점×0.9, 정점 ≤ 2021): {int(past.sum())}개 ({past.sum() / ever.sum():.0%}). "
              f"정점이 2022년 이후(아직 상승 중): {int(((peak_year >= 2022) & ever).sum())}개 ({((peak_year >= 2022) & ever).sum() / ever.sum():.0%}).", ""]
    bysec = pk[ever].groupby("section").agg(n=("peak_year", "size"), median_peak=("peak_year", "median"),
                                             past_share=("past_peak", "mean"), rising_share=("peak_year", lambda s: (s >= 2022).mean()),
                                             median_last=("last", "median")).sort_values("past_share", ascending=False)
    bysec.to_csv(OUT / "china_peak_by_section.csv", encoding="utf-8-sig")
    lines += ["부별 (정점 통과 비율 순):", "", "| 부 | 품목 수 | 정점 연도 중위 | 정점 통과 비율 | 아직 상승 중 비율 | 2024 중국 점유율 중위 |", "|---|---|---|---|---|---|"]
    for s, r in bysec.iterrows():
        lines.append(f"| {s} | {int(r.n)} | {r.median_peak:.0f} | {r.past_share:.0%} | {r.rising_share:.0%} | {r.median_last:.1%} |")
    lines.append("")
    # 4. 1위 지위 획득·상실
    t1 = top.set_index(["t", "code"]).i.unstack("t")
    isc = (t1 == CHN)
    lines += ["## 4. 중국의 1위 지위 획득·상실 (구간 내 연도별 전환 합계)", "", "| 구간 | 획득 | 상실 | 순증 | 구간 끝 1위 품목 수 |", "|---|---|---|---|---|"]
    for a, b in [(1995, 2000), (2000, 2005), (2005, 2010), (2010, 2015), (2015, 2019), (2019, 2024)]:
        gain = lose = 0
        for y in range(a + 1, b + 1):
            gain += int((isc[y] & ~isc[y - 1]).sum()); lose += int((~isc[y] & isc[y - 1]).sum())
        lines.append(f"| {a}→{b} | {gain} | {lose} | {gain - lose:+d} | {int(isc[b].sum())} |")
    lose_to = top[(top.t == 2024)].set_index("code").i
    lost_codes = isc.index[isc[2019] & ~isc[2024]]
    who = lose_to.reindex(lost_codes).map(dict(zip(*con.execute("SELECT country_code, iso3 FROM dim_country").df().values.T))).value_counts()
    lines += ["", f"2019년 1위였다가 2024년 1위가 아닌 품목 {len(lost_codes)}개. 1위를 가져간 나라: " + ", ".join(f"{k} {v}" for k, v in who.head(8).items()), ""]
    # 그림
    fig, axes = plt.subplots(2, 3, figsize=(17, 9))
    panels = [("top1_share", "중국이 1위 수출국인 품목 비율"), ("topdeg_share", "중국이 최대 연결국인 품목 비율"), ("chn_median_share", "중국 점유율 품목 중위"),
              ("x_hhi_exp", "중국 제외 HHI 중위"), ("x_top5_exp_share", "중국 제외 상위5 점유율 중위"), ("x_modularity", "중국 제외 모듈성 중위")]
    for ax, (c, nm) in zip(axes.flat, panels):
        ax.plot(S.index, S[c], "k-", lw=2)
        f = fits[c]; b = f["break_year"]
        t = np.array(S.index, float)
        X = np.c_[np.ones_like(t), t - t[0], np.maximum(t - b, 0)]
        beta, *_ = np.linalg.lstsq(X, S[c].values, rcond=None)
        ax.plot(S.index, X @ beta, "r--", lw=1)
        ax.axvline(b, color="r", ls=":", lw=0.8)
        ax.set_title(f"{nm}\n단절 {b}: {f['slope_before']:+.4f}/년 → {f['slope_after']:+.4f}/년", fontsize=10)
    fig.tight_layout(); fig.savefig(OUT / "turning_points.png", dpi=110); plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(hist.index, hist.values, color="steelblue"); ax.set_title("품목별 중국 점유율 정점 연도 (3년 이동평균, 5% 이상 경험 품목)")
    fig.tight_layout(); fig.savefig(OUT / "china_peak_years.png", dpi=110); plt.close(fig)
    (OUT / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines)); print(f"\n산출물: {OUT}")


if __name__ == "__main__":
    main()
