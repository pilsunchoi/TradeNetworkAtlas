"""파일럿 탐색: mart_net_metrics 시계열 요약 → analysis/explore/ 에 표(csv)와 그림(png), 요약(md).

사용: python scripts/06_explore.py --level hs2 --variant w1m
계획 §1의 질문 넷에 하나씩 대응한다.
 Q1 구조 변화: 지표별 품목 간 중위·사분위 시계열
 Q2 품목군 차이: HS 부(section)별 지표 궤적
 Q3 사건: 2008, 2018, 2020 전후 3년 평균 차이의 품목 분포
 Q4 한국: 품목별 수출 순위·점유율·상대국 집중도 추이
"""
import sys
import argparse
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

METRICS = ["n_nodes", "density", "reciprocity", "hhi_exp", "top5_exp_share", "gini_out_strength",
           "centralization_out", "clustering_avg", "assortativity_deg", "n_communities", "modularity",
           "max_kcore", "intra_region_share"]
EVENTS = {"2008 금융위기": (2005, 2007, 2009, 2011), "2018 미중갈등": (2015, 2017, 2019, 2021), "2020 팬데믹": (2017, 2019, 2021, 2023)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="hs2")
    ap.add_argument("--variant", default="w1m")
    a = ap.parse_args()
    out = ROOT / "analysis" / "explore" / f"{a.level}_{a.variant}"
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    m = con.execute("SELECT * FROM mart_net_metrics WHERE level = ? AND variant = ?", [a.level, a.variant]).df()
    prod = con.execute("SELECT DISTINCT hs2, section, section_name FROM dim_product").df()
    if a.level == "hs2":
        m = m.merge(prod, left_on="code", right_on="hs2", how="left")
    elif a.level == "hs4":
        m["hs2"] = m.code.str[:2]
        m = m.merge(prod, on="hs2", how="left")
    else:
        m["section_name"] = "전체"
    lines = [f"# 탐색 요약 — level={a.level}, variant={a.variant}", "",
             f"품목 {m.code.nunique()}개, 연도 {m.t.min()}–{m.t.max()}, 행 {len(m):,}", ""]

    # Q1: 지표별 품목 간 분위수 시계열
    q = m.groupby("t")[METRICS].quantile([0.25, 0.5, 0.75]).unstack()
    q.to_csv(out / "q1_metric_quantiles_by_year.csv", encoding="utf-8-sig")
    fig, axes = plt.subplots(4, 4, figsize=(18, 14))
    for ax, met in zip(axes.flat, METRICS):
        ax.plot(q.index, q[(met, 0.5)], color="k", lw=2)
        ax.fill_between(q.index, q[(met, 0.25)], q[(met, 0.75)], alpha=0.25)
        ax.set_title(met)
        for y in (2008, 2018, 2020):
            ax.axvline(y, color="gray", ls=":", lw=0.8)
    for ax in axes.flat[len(METRICS):]:
        ax.axis("off")
    fig.suptitle(f"품목 간 중위값과 사분위 범위 ({a.level}, {a.variant})")
    fig.tight_layout()
    fig.savefig(out / "q1_metric_quantiles.png", dpi=110)
    plt.close(fig)
    first, last = m.t.min(), m.t.max()
    chg = (q.loc[last] - q.loc[first]).unstack()
    lines += ["## Q1 지표별 중위값 변화 (첫해 → 끝해)", "", "| 지표 | 첫해 중위 | 끝해 중위 | 변화 |", "|---|---|---|---|"]
    for met in METRICS:
        lines.append(f"| {met} | {q.loc[first, (met, 0.5)]:.3f} | {q.loc[last, (met, 0.5)]:.3f} | {chg.loc[met, 0.5]:+.3f} |")
    lines.append("")

    # Q2: 부별 궤적 (핵심 지표 4개)
    key = ["hhi_exp", "density", "modularity", "intra_region_share"]
    sec = m.groupby(["section_name", "t"])[key].median().reset_index()
    sec.to_csv(out / "q2_section_trajectories.csv", index=False, encoding="utf-8-sig")
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    for ax, met in zip(axes.flat, key):
        for s, g in sec.groupby("section_name"):
            ax.plot(g.t, g[met], lw=1, label=s)
        ax.set_title(met)
    axes.flat[0].legend(fontsize=6, ncol=3)
    fig.suptitle("HS 부별 중위 궤적")
    fig.tight_layout()
    fig.savefig(out / "q2_section_trajectories.png", dpi=110)
    plt.close(fig)
    piv = sec[sec.t.isin([first, last])].pivot(index="section_name", columns="t", values="hhi_exp")
    lines += ["## Q2 부별 수출 집중도(hhi_exp) 중위: 첫해 → 끝해", "", "| 부 | 첫해 | 끝해 | 변화 |", "|---|---|---|---|"]
    for s, r in piv.iterrows():
        lines.append(f"| {s} | {r[first]:.3f} | {r[last]:.3f} | {r[last]-r[first]:+.3f} |")
    lines.append("")

    # Q3: 사건 전후 (전 3년 평균 → 후 3년 평균) 품목별 차이의 분포
    lines += ["## Q3 사건 전후 변화 (품목별 전3년 평균 → 후3년 평균, 중위값과 상승 품목 비율)", ""]
    rows = []
    for ev, (b0, b1, a0, a1) in EVENTS.items():
        before = m[m.t.between(b0, b1)].groupby("code")[METRICS].mean()
        after = m[m.t.between(a0, a1)].groupby("code")[METRICS].mean()
        d = (after - before).dropna()
        for met in METRICS:
            rows.append(dict(event=ev, metric=met, median_change=d[met].median(), share_up=(d[met] > 0).mean(), n=len(d)))
    ev = pd.DataFrame(rows)
    ev.to_csv(out / "q3_event_changes.csv", index=False, encoding="utf-8-sig")
    lines += ["| 사건 | 지표 | 중위 변화 | 상승 품목 비율 |", "|---|---|---|---|"]
    for _, r in ev.iterrows():
        if r.metric in ("density", "hhi_exp", "modularity", "intra_region_share", "reciprocity", "n_nodes"):
            lines.append(f"| {r.event} | {r.metric} | {r.median_change:+.4f} | {r.share_up:.0%} |")
    lines.append("")

    # Q4: 한국
    kor = m[["code", "section_name", "t", "kor_exp_share", "kor_exp_rank", "kor_pagerank_rank", "kor_hub_rank", "kor_n_dest", "kor_hhi_dest"]]
    kor.to_csv(out / "q4_korea_by_product_year.csv", index=False, encoding="utf-8-sig")
    top = kor[kor.t == last].nsmallest(15, "kor_exp_rank")
    lines += [f"## Q4 한국 수출 순위 상위 15개 품목 ({last}) 와 {first} 대비", "",
              "| 코드 | 부 | 순위(끝) | 순위(첫) | 점유율(끝) | 상대국 수 | 상대국 HHI |", "|---|---|---|---|---|---|---|"]
    firstk = kor[kor.t == first].set_index("code")
    for _, r in top.iterrows():
        r0 = firstk.loc[r.code] if r.code in firstk.index else None
        lines.append(f"| {r.code} | {r.section_name} | {r.kor_exp_rank} | {r0.kor_exp_rank if r0 is not None else '-'} | "
                     f"{r.kor_exp_share:.1%} | {r.kor_n_dest} | {r.kor_hhi_dest:.3f} |")
    lines.append("")
    ks = kor.groupby("t").agg(median_rank=("kor_exp_rank", "median"), share_top10=("kor_exp_rank", lambda s: (s <= 10).mean()),
                              median_hhi_dest=("kor_hhi_dest", "median"))
    ks.to_csv(out / "q4_korea_summary_by_year.csv", encoding="utf-8-sig")
    fig, axes = plt.subplots(1, 3, figsize=(16, 4))
    axes[0].plot(ks.index, ks.median_rank); axes[0].invert_yaxis(); axes[0].set_title("한국 수출 순위 중위(품목 간)")
    axes[1].plot(ks.index, ks.share_top10); axes[1].set_title("한국이 10위 안인 품목 비율")
    axes[2].plot(ks.index, ks.median_hhi_dest); axes[2].set_title("한국 수출 상대국 HHI 중위")
    fig.tight_layout()
    fig.savefig(out / "q4_korea_summary.png", dpi=110)
    plt.close(fig)
    lines += ["## Q4 한국 요약 (연도별)", "", "| 연도 | 순위 중위 | 10위내 품목 비율 | 상대국 HHI 중위 |", "|---|---|---|---|"]
    for t, r in ks.iterrows():
        if t % 5 == 0 or t >= 2022:
            lines.append(f"| {t} | {r.median_rank:.0f} | {r.share_top10:.0%} | {r.median_hhi_dest:.3f} |")
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n산출물: {out}")


if __name__ == "__main__":
    main()
