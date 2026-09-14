"""집중의 주체 식별. edge_hs4에서 w1m_bal 조건으로 직접 계산한다.

A 최대 수출국·최대 연결국(수출 상대국 수 1위)의 정체: 연도별로 어느 나라가 몇 개 품목(과 총액의 몇 %)에서 1위인가
B HHI 분해: 품목별 ΔHHI(1995-97 → 2022-24) = Σ_i Δ(s_i²). 국가별 기여와, 중국 제외 재정규화 HHI의 추세
C 2020년 이후 재가속: 2019→2024 1위 점유율·중국 점유율 변화의 분포
D 한국: 상대국 점유율(총량·품목 중위)의 연도별 추이와 2016년 이후 재집중의 상대국

사용: python scripts/08_concentration_actors.py [--level hs4] [--wmin 1000]
산출: analysis/actors/{level}/
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
KOR = 410
FOCUS = ["CHN", "USA", "DEU", "JPN", "ITA", "FRA", "NLD", "KOR", "S19", "IND", "VNM", "MEX"]
LABEL = {"S19": "TWN"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="hs4")
    ap.add_argument("--wmin", type=float, default=1000.0)
    a = ap.parse_args()
    out = ROOT / "analysis" / "actors" / a.level
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    con.execute("PRAGMA threads=8")
    iso = con.execute("SELECT country_code, iso3 FROM dim_country").df()
    iso_of = dict(zip(iso.country_code, iso.iso3))
    edge = "edge_total" if a.level == "total" else f"edge_{a.level}"
    code_expr = "'ALL' AS code" if a.level == "total" else "code"
    # 수출국별 (t, code): 수출액 x, 상대국 수 d
    ex = con.execute(f"""
        SELECT t, {code_expr}, i, sum(v) AS x, count(*) AS d
        FROM {edge}
        WHERE v >= {a.wmin} AND i IN (SELECT country_code FROM dim_fixed_country) AND j IN (SELECT country_code FROM dim_fixed_country)
        GROUP BY 1, 2, 3""").df()
    ex["iso"] = ex.i.map(iso_of)
    tot = ex.groupby(["t", "code"]).x.transform("sum")
    ex["s"] = ex.x / tot
    lines = [f"# 집중의 주체 — {a.level}, w1m_bal", "", f"품목×연도 {ex.groupby(['t','code']).ngroups:,}개, 수출국-품목-연도 행 {len(ex):,}", ""]

    # A. 1위 정체
    top = ex.sort_values(["t", "code", "x"], ascending=[True, True, False]).groupby(["t", "code"]).head(1)
    topd = ex.sort_values(["t", "code", "d", "x"], ascending=[True, True, False, False]).groupby(["t", "code"]).head(1)
    top["val"] = top.x / top.s  # 품목 총액
    def share_table(df, name):
        cnt = df.groupby(["t", "iso"]).size().unstack(fill_value=0)
        cnt = cnt.div(cnt.sum(axis=1), axis=0)
        val = df.groupby(["t", "iso"]).val.sum().unstack(fill_value=0) if "val" in df else None
        cols = [c for c in FOCUS if c in cnt.columns]
        cols = sorted(cols, key=lambda c: -cnt[c].iloc[-1])[:8]
        cnt.to_csv(out / f"A_{name}_share_by_year.csv", encoding="utf-8-sig")
        return cnt, cols
    cntA, colsA = share_table(top, "top_exporter")
    top["val"] = top.x / top.s
    valA = top.groupby(["t", "iso"]).val.sum().unstack(fill_value=0)
    valA = valA.div(valA.sum(axis=1), axis=0)
    cntB, colsB = share_table(topd, "top_degree")
    yrs = [1995, 2000, 2005, 2010, 2015, 2019, 2024]
    lines += ["## A. 품목별 1위 수출국의 정체 — 1위인 품목의 비율 (괄호: 그 품목들의 총액 비중)", "",
              "| 연도 | " + " | ".join(LABEL.get(c, c) for c in colsA) + " |", "|---|" + "---|" * len(colsA)]
    for y in yrs:
        cells = [f"{cntA.loc[y, c]:.1%} ({valA.loc[y, c]:.0%})" for c in colsA]
        lines.append(f"| {y} | " + " | ".join(cells) + " |")
    lines += ["", "## A′. 품목별 최대 연결국(수출 상대국 수 1위)의 정체 — 차수 중심화를 끌어올리는 노드", "",
              "| 연도 | " + " | ".join(LABEL.get(c, c) for c in colsB) + " |", "|---|" + "---|" * len(colsB)]
    for y in yrs:
        lines.append(f"| {y} | " + " | ".join(f"{cntB.loc[y, c]:.1%}" for c in colsB) + " |")
    lines.append("")
    fig, axes = plt.subplots(1, 2, figsize=(16, 5))
    for ax, (cnt, cols, ttl) in zip(axes, [(cntA, colsA, "수출액 1위인 품목 비율"), (cntB, colsB, "상대국 수 1위인 품목 비율")]):
        for c in cols:
            ax.plot(cnt.index, cnt[c], label=LABEL.get(c, c), lw=2 if c == "CHN" else 1)
        ax.set_title(ttl); ax.legend(fontsize=8)
        for y in (2009, 2018, 2020):
            ax.axvline(y, color="gray", ls=":", lw=0.8)
    fig.tight_layout(); fig.savefig(out / "A_top_identity.png", dpi=110); plt.close(fig)

    # 1위 점유율 자체의 추이 (중위)
    s1 = top.groupby("t").s.median()
    lines += ["1위 수출국 점유율의 품목 중위: " + ", ".join(f"{y} {s1.loc[y]:.3f}" for y in yrs), ""]

    # B. HHI 분해
    def period_shares(y0, y1):
        d = ex[ex.t.between(y0, y1)].groupby(["code", "iso"]).s.mean().rename("s")
        return d
    s_start, s_end = period_shares(1995, 1997), period_shares(2022, 2024)
    both = pd.concat([s_start.rename("s0"), s_end.rename("s1")], axis=1).fillna(0.0)
    both["contrib"] = both.s1 ** 2 - both.s0 ** 2
    hhi0 = (both.s0 ** 2).groupby(level="code").sum(); hhi1 = (both.s1 ** 2).groupby(level="code").sum()
    dh = (hhi1 - hhi0)
    contrib = both.contrib.groupby(level="iso").sum() / len(dh)  # 품목 평균 기여
    contrib = contrib.sort_values()
    lines += ["## B. 품목 평균 HHI 변화의 국가별 분해 (1995-97 → 2022-24)", "",
              f"품목 평균 HHI: {hhi0.mean():.4f} → {hhi1.mean():.4f} (Δ {dh.mean():+.4f}); 상승 품목 비율 {(dh > 0).mean():.0%}", "",
              "| 국가 | 평균 기여 Δ(s²) | Δ의 몫 |", "|---|---|---|"]
    for c in list(contrib.index[-8:][::-1]) + list(contrib.index[:6]):
        lines.append(f"| {LABEL.get(c, c)} | {contrib[c]:+.4f} | {contrib[c] / dh.mean():+.0%} |")
    lines.append("")
    # 중국 제외 재정규화 HHI 추세
    exx = ex[ex.iso != "CHN"].copy()
    exx["s"] = exx.x / exx.groupby(["t", "code"]).x.transform("sum")
    hhi_ex = (exx.s ** 2).groupby([exx.t, exx.code]).sum().rename("hhi_ex")
    hhi_all = (ex.s ** 2).groupby([ex.t, ex.code]).sum().rename("hhi")
    hh = pd.concat([hhi_all, hhi_ex], axis=1).reset_index()
    hm = hh.groupby("t")[["hhi", "hhi_ex"]].agg(["median", "mean"])
    hm.to_csv(out / "B_hhi_exchina_by_year.csv", encoding="utf-8-sig")
    lines += ["중국 제외 재정규화 HHI (품목 중위 / 평균):", "", "| 연도 | HHI 중위 | 중국 제외 중위 | HHI 평균 | 중국 제외 평균 |", "|---|---|---|---|---|"]
    for y in yrs:
        lines.append(f"| {y} | {hm.loc[y, ('hhi','median')]:.3f} | {hm.loc[y, ('hhi_ex','median')]:.3f} | {hm.loc[y, ('hhi','mean')]:.3f} | {hm.loc[y, ('hhi_ex','mean')]:.3f} |")
    lines.append("")
    # 지니·중심화도 중국 제외로? 중심화는 최대 연결국이 중국인 품목 비율(A′)로 대신한다.
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(hm.index, hm[("hhi", "median")], "k-", lw=2, label="HHI 중위")
    ax.plot(hm.index, hm[("hhi_ex", "median")], "r--", lw=2, label="중국 제외 HHI 중위")
    ax.plot(hm.index, hm[("hhi", "mean")], "k-", lw=1, alpha=0.5, label="HHI 평균")
    ax.plot(hm.index, hm[("hhi_ex", "mean")], "r--", lw=1, alpha=0.5, label="중국 제외 평균")
    ax.legend(); ax.set_title("수출 집중도: 실제 vs 중국 제외 재정규화")
    fig.tight_layout(); fig.savefig(out / "B_hhi_exchina.png", dpi=110); plt.close(fig)

    # C. 2020년 이후: 2019 → 2024 점유율 변화
    piv = ex.pivot_table(index=["code", "iso"], columns="t", values="s", fill_value=0.0)
    for (y0, y1, tag) in [(2015, 2019, "2015→2019"), (2019, 2024, "2019→2024")]:
        dd = (piv[y1] - piv[y0]).groupby(level="iso").mean().sort_values()
        lines += [f"## C. 품목 평균 점유율 변화 {tag} (상위·하위 6개국)", "", "| 국가 | Δ점유율(품목 평균) | 상승 품목 비율 |", "|---|---|---|"]
        up = ((piv[y1] - piv[y0]) > 0).groupby(level="iso").mean()
        for c in list(dd.index[-6:][::-1]) + list(dd.index[:6]):
            lines.append(f"| {LABEL.get(c, c)} | {dd[c]:+.4f} | {up[c]:.0%} |")
        lines.append("")
    chn = piv.xs("CHN", level="iso") if "CHN" in piv.index.get_level_values("iso") else None
    if chn is not None:
        lines += ["중국 점유율의 품목 중위: " + ", ".join(f"{y} {chn[y].median():.3f}" for y in yrs), ""]

    # D. 한국 상대국
    kd = con.execute(f"""
        SELECT t, {code_expr}, j, sum(v) AS v FROM {edge}
        WHERE i = {KOR} AND v >= {a.wmin} AND j IN (SELECT country_code FROM dim_fixed_country)
        GROUP BY 1, 2, 3""").df()
    kd["iso"] = kd.j.map(iso_of)
    kd["s"] = kd.v / kd.groupby(["t", "code"]).v.transform("sum")
    # 총량 점유율
    ktot = kd.groupby(["t", "iso"]).v.sum().unstack(fill_value=0)
    ktot = ktot.div(ktot.sum(axis=1), axis=0)
    kcols = sorted(ktot.columns, key=lambda c: -ktot[c].loc[2024])[:8]
    ktot.to_csv(out / "D_korea_partner_share_total.csv", encoding="utf-8-sig")
    # 품목 중위 점유율
    kmed = kd.pivot_table(index=["t", "code"], columns="iso", values="s", fill_value=0.0).groupby(level="t").median()
    kmed.to_csv(out / "D_korea_partner_share_product_median.csv", encoding="utf-8-sig")
    lines += ["## D. 한국 수출 상대국 점유율 — 총량 (괄호: 품목 중위)", "",
              "| 연도 | " + " | ".join(LABEL.get(c, c) for c in kcols) + " |", "|---|" + "---|" * len(kcols)]
    for y in yrs + [2016]:
        pass
    for y in sorted(set(yrs + [2016])):
        lines.append(f"| {y} | " + " | ".join(f"{ktot.loc[y, c]:.1%} ({kmed.loc[y, c] if c in kmed.columns else 0:.1%})" for c in kcols) + " |")
    # 2016→2024 재집중: 품목별 HHI 변화와 그 품목에서 점유율이 가장 오른 상대국
    khhi = (kd.s ** 2).groupby([kd.t, kd.code]).sum().unstack("t")
    dk = (khhi[2024] - khhi[2016]).dropna()
    kp = kd.pivot_table(index=["code", "iso"], columns="t", values="s", fill_value=0.0)
    dsh = (kp[2024] - kp[2016])
    gain = dsh.groupby(level="code").idxmax().map(lambda x: x[1] if isinstance(x, tuple) else x)
    lose = dsh.groupby(level="code").idxmin().map(lambda x: x[1] if isinstance(x, tuple) else x)
    up_codes = dk[dk > 0].index
    kv = kd[kd.t == 2024].groupby("code").v.sum()
    g = gain.loc[gain.index.intersection(up_codes)]
    gcount = g.value_counts()
    gval = kv.reindex(g.index).groupby(g.values).sum().sort_values(ascending=False)
    lines += ["", f"2016→2024 한국 상대국 HHI가 오른 품목: {len(up_codes)}/{len(dk)}개 ({(dk>0).mean():.0%}). 그 품목에서 점유율이 가장 많이 오른 상대국:", "",
              "| 상대국 | 품목 수 | 그 품목들의 2024 한국 수출(십억$) |", "|---|---|---|"]
    for c in gcount.index[:8]:
        lines.append(f"| {LABEL.get(c, c)} | {gcount[c]} | {gval.get(c, 0) / 1e6:.1f} |")
    lcount = lose.loc[lose.index.intersection(up_codes)].value_counts()
    lines += ["", "같은 품목에서 점유율이 가장 많이 내린 상대국: " + ", ".join(f"{LABEL.get(c, c)} {n}" for c, n in lcount.head(5).items()), ""]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for c in kcols:
        ax.plot(ktot.index, ktot[c], label=LABEL.get(c, c), lw=2 if c in ("CHN", "USA") else 1)
    ax.axvline(2016, color="gray", ls=":", lw=0.8); ax.legend(fontsize=8); ax.set_title("한국 수출 상대국 점유율(총량, w1m_bal)")
    fig.tight_layout(); fig.savefig(out / "D_korea_partners.png", dpi=110); plt.close(fig)

    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines)); print(f"\n산출물: {out}")


if __name__ == "__main__":
    main()
