"""품목 패널 회귀: 추세와 사건(단절) 검정.

사용: python scripts/07_panel_regression.py --level hs4 --variant w1m_bal [--weighted]

표본: mart_net_metrics의 품목×연도 패널. 30년 전부 관측된 품목만 쓴다.
모형(모두 품목 고정효과 = 품목 내 평균 제거, 표준오차는 품목 군집):
  A 선형추세      y = a_p + b*tt + e,  tt = (t-1995)/10 (10년 단위)
  B 구간별 추세   y = a_p + b*tt + sum_e [g_e*Post_e + d_e*Post_e*(t-t_e)/10] + e,  t_e in {2009, 2018, 2020}
                  g_e = 사건 시점의 수준 점프, d_e = 이후 기울기 변화
  C 연도효과      y = a_p + sum_t tau_t*1[t] + e (1995 기준). 연도별 변화 D_t = tau_t - tau_{t-1}의 z값으로
                  사건 연도가 다른 해들 사이에서 두드러지는지 본다. 사건 창(전3년→후3년 평균 차)도 tau의 선형결합으로 검정.
  D 부별 추세     y = a_p + sum_s b_s*tt*1[section=s] + e
산출: analysis/panel/{level}_{variant}[_w]/ 에 표(csv)·그림(png)·summary.md
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.settings import DB_PATH, ROOT
import duckdb
import numpy as np
import pandas as pd
import statsmodels.api as sm
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

METRICS = {"log_n_nodes": "활성 국가 수(로그)", "density": "밀도", "reciprocity": "호혜성", "hhi_exp": "수출 HHI",
           "top5_exp_share": "상위5 수출점유", "gini_out_strength": "수출 지니", "centralization_out": "차수 중심화(수출)",
           "clustering_avg": "군집계수", "modularity": "모듈성", "max_kcore": "최대 k-코어", "intra_region_share": "역내 비중",
           "kor_hhi_dest": "한국 상대국 HHI", "kor_exp_share": "한국 수출 점유율"}
EVENTS = {"2009": 2009, "2018": 2018, "2020": 2020}
T0 = 1995


def stars(p):
    return "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.1 else ""


def within(df, cols, by="code", w=None):
    """품목 내 평균 제거(가중이면 가중평균)."""
    out = df[cols].copy()
    if w is None:
        out = out - df.groupby(by)[cols].transform("mean")
    else:
        ww = df[w]
        for c in cols:
            m = (df[c] * ww).groupby(df[by]).transform("sum") / ww.groupby(df[by]).transform("sum")
            out[c] = df[c] - m
    return out


def fit(y, X, groups, w=None):
    if w is None:
        return sm.OLS(y, X).fit(cov_type="cluster", cov_kwds={"groups": groups})
    return sm.WLS(y, X, weights=w).fit(cov_type="cluster", cov_kwds={"groups": groups})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="hs4")
    ap.add_argument("--variant", default="w1m_bal")
    ap.add_argument("--weighted", action="store_true", help="품목의 평균 총액으로 가중")
    a = ap.parse_args()
    tag = f"{a.level}_{a.variant}" + ("_w" if a.weighted else "")
    out = ROOT / "analysis" / "panel" / tag
    out.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(DB_PATH), read_only=True)
    m = con.execute("SELECT * FROM mart_net_metrics WHERE level = ? AND variant = ?", [a.level, a.variant]).df()
    sec = con.execute("SELECT DISTINCT hs2, section_name FROM dim_product").df()
    con.close()
    m["hs2"] = m.code.str[:2] if a.level != "total" else "00"
    m = m.merge(sec, on="hs2", how="left")
    m["log_n_nodes"] = np.log(m.n_nodes)
    m["max_kcore"] = m.max_kcore.astype(float)
    # 30년 전부 있는 품목만
    full = m.groupby("code").t.nunique()
    keep = full[full == full.max()].index
    m = m[m.code.isin(keep)].sort_values(["code", "t"]).reset_index(drop=True)
    m["tt"] = (m.t - T0) / 10.0
    m["gid"] = pd.factorize(m.code)[0]
    wcol = None
    if a.weighted:
        m["w"] = m.groupby("code").total_value.transform("mean")
        m["w"] = m.w / m.w.mean()
        wcol = "w"
    n_prod, n_year = m.code.nunique(), m.t.nunique()
    lines = [f"# 품목 패널 회귀 — {tag}", "",
             f"표본: 품목 {n_prod}개 × {n_year}년 = {len(m):,}행 (30년 전부 관측된 품목만). "
             f"품목 고정효과, 품목 군집 표준오차{', 총액 가중' if a.weighted else ''}.", ""]

    # 사건 회귀변수
    for k, ty in EVENTS.items():
        m[f"post{k}"] = (m.t >= ty).astype(float)
        m[f"post{k}_tt"] = m[f"post{k}"] * (m.t - ty) / 10.0
    year_cols = []
    for t in range(T0 + 1, m.t.max() + 1):
        m[f"y{t}"] = (m.t == t).astype(float)
        year_cols.append(f"y{t}")
    secs = sorted(m.section_name.dropna().unique())
    sec_cols = []
    for s in secs:
        c = f"s_{s}"
        m[c] = m.tt * (m.section_name == s)
        sec_cols.append(c)

    rowsA, rowsB, rowsC, rowsD = [], [], [], []
    fig, axes = plt.subplots(4, 4, figsize=(18, 14))
    axes = axes.flat
    for k, (met, label) in enumerate(METRICS.items()):
        d = m.dropna(subset=[met])
        if met.startswith("kor_"):
            # 한국이 30년 내내 있는 품목만
            ok = d.groupby("code").t.nunique()
            d = d[d.code.isin(ok[ok == n_year].index)]
        if d.code.nunique() < 30:
            continue
        sd = d[met].std()
        g = d.gid.values
        w = d[wcol].values if wcol else None
        # A
        Z = within(d, [met, "tt"], w=wcol)
        rA = fit(Z[met], Z[["tt"]], g, w)
        rowsA.append(dict(metric=met, label=label, n_products=d.code.nunique(), mean=d[met].mean(), sd=sd,
                          beta_decade=rA.params.tt, se=rA.bse.tt, p=rA.pvalues.tt, beta_std=rA.params.tt / sd))
        # B
        xb = ["tt"] + [f"post{e}" for e in EVENTS] + [f"post{e}_tt" for e in EVENTS]
        Z = within(d, [met] + xb, w=wcol)
        rB = fit(Z[met], Z[xb], g, w)
        rowB = dict(metric=met, label=label, sd=sd, trend=rB.params.tt, trend_p=rB.pvalues.tt)
        for e in EVENTS:
            rowB[f"jump{e}"] = rB.params[f"post{e}"]; rowB[f"jump{e}_se"] = rB.bse[f"post{e}"]; rowB[f"jump{e}_p"] = rB.pvalues[f"post{e}"]
            rowB[f"slope{e}"] = rB.params[f"post{e}_tt"]; rowB[f"slope{e}_p"] = rB.pvalues[f"post{e}_tt"]
        rowsB.append(rowB)
        # C
        Z = within(d, [met] + year_cols, w=wcol)
        rC = fit(Z[met], Z[year_cols], g, w)
        tau = pd.Series(np.r_[0.0, rC.params.values], index=range(T0, T0 + len(year_cols) + 1))
        V = rC.cov_params().values
        Vf = np.zeros((len(tau), len(tau))); Vf[1:, 1:] = V
        se_tau = np.sqrt(np.diag(Vf))
        # 연도별 변화 D_t와 z
        for i, t in enumerate(tau.index[1:], start=1):
            c = np.zeros(len(tau)); c[i] = 1; c[i - 1] = -1
            dv, dse = c @ tau.values, np.sqrt(c @ Vf @ c)
            rowsC.append(dict(metric=met, t=t, delta=dv, se=dse, z=dv / dse if dse > 0 else np.nan))
        # 사건 창: 후3년 평균 - 전3년 평균
        for e, ty in EVENTS.items():
            pre = [ty - 3, ty - 2, ty - 1]; post = [ty, ty + 1, ty + 2]
            post = [p for p in post if p in tau.index]
            c = np.zeros(len(tau))
            for p in pre: c[list(tau.index).index(p)] -= 1 / len(pre)
            for p in post: c[list(tau.index).index(p)] += 1 / len(post)
            dv, dse = c @ tau.values, np.sqrt(c @ Vf @ c)
            rowsC.append(dict(metric=met, t=f"win{e}", delta=dv, se=dse, z=dv / dse if dse > 0 else np.nan))
        ax = axes[k]
        ax.plot(tau.index, tau.values, color="k", lw=2)
        ax.fill_between(tau.index, tau.values - 1.96 * se_tau, tau.values + 1.96 * se_tau, alpha=0.25)
        ax.axhline(0, color="gray", lw=0.6)
        for ty in EVENTS.values():
            ax.axvline(ty, color="gray", ls=":", lw=0.8)
        ax.set_title(f"{label} (SD={sd:.3f})")
        # D
        Z = within(d, [met] + sec_cols, w=wcol)
        rD = fit(Z[met], Z[sec_cols], g, w)
        for s, c in zip(secs, sec_cols):
            n_s = d[d.section_name == s].code.nunique()
            rowsD.append(dict(metric=met, section=s, n_products=n_s, beta_decade=rD.params[c], se=rD.bse[c], p=rD.pvalues[c],
                              beta_std=rD.params[c] / sd))
    for ax in list(axes)[len(METRICS):]:
        ax.axis("off")
    fig.suptitle(f"연도 고정효과 tau_t (1995=0), 95% 신뢰구간, 품목 군집 SE — {tag}")
    fig.tight_layout()
    fig.savefig(out / "C_year_effects.png", dpi=110)
    plt.close(fig)

    A = pd.DataFrame(rowsA); B = pd.DataFrame(rowsB); C = pd.DataFrame(rowsC); D = pd.DataFrame(rowsD)
    A.to_csv(out / "A_trend.csv", index=False, encoding="utf-8-sig")
    B.to_csv(out / "B_piecewise.csv", index=False, encoding="utf-8-sig")
    C.to_csv(out / "C_year_changes.csv", index=False, encoding="utf-8-sig")
    D.to_csv(out / "D_section_trend.csv", index=False, encoding="utf-8-sig")

    # 요약 표
    lines += ["## A. 선형추세 (10년당 변화, 괄호는 SD 단위)", "", "| 지표 | 품목 수 | 평균 | 10년당 β | SE | p | β/SD |", "|---|---|---|---|---|---|---|"]
    for _, r in A.iterrows():
        lines.append(f"| {r.label} | {r.n_products} | {r['mean']:.3f} | {r.beta_decade:+.4f}{stars(r.p)} | {r.se:.4f} | {r.p:.3f} | {r.beta_std:+.2f} |")
    lines += ["", "## B. 구간별 추세: 사건 시점 수준 점프(g)와 이후 기울기 변화(d, 10년당)", "",
              "| 지표 | 기본추세 | g2009 | d2009 | g2018 | d2018 | g2020 | d2020 |", "|---|---|---|---|---|---|---|---|"]
    for _, r in B.iterrows():
        cells = [f"{r.trend:+.4f}{stars(r.trend_p)}"]
        for e in EVENTS:
            cells.append(f"{r[f'jump{e}']:+.4f}{stars(r[f'jump{e}_p'])}")
            cells.append(f"{r[f'slope{e}']:+.4f}{stars(r[f'slope{e}_p'])}")
        lines.append(f"| {r.label} | " + " | ".join(cells) + " |")
    lines += ["", "## C. 연도효과의 연도별 변화 — 사건 연도의 z값과, |z| 순위(29개 연도 변화 중)", "",
              "| 지표 | 2009 z (순위) | 2018 z (순위) | 2020 z (순위) | 창2009 | 창2018 | 창2020 |", "|---|---|---|---|---|---|---|"]
    for met, label in METRICS.items():
        c = C[C.metric == met]
        if c.empty:
            continue
        yearly = c[c.t.apply(lambda x: isinstance(x, (int, np.integer)))].copy()
        yearly["rank"] = yearly.z.abs().rank(ascending=False).astype(int)
        cells = []
        for e, ty in EVENTS.items():
            r = yearly[yearly.t == ty].iloc[0]
            cells.append(f"{r.z:+.1f} ({r['rank']})")
        for e in EVENTS:
            r = c[c.t == f"win{e}"].iloc[0]
            cells.append(f"{r.delta:+.4f}{stars(2 * (1 - __import__('scipy').stats.norm.cdf(abs(r.z))))}")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines += ["", "창: 후3년 평균 − 전3년 평균(연도효과의 선형결합). 순위 1 = 30년 중 가장 큰 연간 변화.", ""]
    key = ["density", "hhi_exp", "centralization_out", "modularity", "intra_region_share", "gini_out_strength"]
    lines += ["## D. 부별 선형추세 (10년당 β, SD 단위)", "", "| 부 | n | " + " | ".join(METRICS[k] for k in key) + " |",
              "|---|---|" + "---|" * len(key)]
    for s in secs:
        cells = []
        for k in key:
            r = D[(D.metric == k) & (D.section == s)]
            cells.append(f"{r.beta_std.iloc[0]:+.2f}{stars(r.p.iloc[0])}" if len(r) else "-")
        n_s = D[(D.section == s)].n_products.max()
        lines.append(f"| {s} | {n_s} | " + " | ".join(cells) + " |")
    lines += ["", "유의수준: * 10%, ** 5%, *** 1%. 품목 군집 표준오차.", ""]
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n산출물: {out}")


if __name__ == "__main__":
    main()
