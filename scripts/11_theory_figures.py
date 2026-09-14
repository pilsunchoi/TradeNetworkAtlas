"""해설 문서 「교역 네트워크를 읽는 지표」의 그림 두 장.

그림 1: 네 가지 전형 구조(별형, 분산형, 두 공동체, 핵심-주변). 지표 값은 그 그래프에서 04와 같은 정의로 계산한다.
그림 2: 컴퓨터(HS 8471)의 1995년과 2024년 네트워크. 각 수입국을 1위 공급국에 잇는다. 지표는 mart_net_metrics(w1m_bal)에서 읽는다.
출력: docs/연구/네트워크_이론/그림/
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.settings import DB_PATH, ROOT
import duckdb
import numpy as np
import igraph as ig
import leidenalg as la
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False
OUT = ROOT / "docs" / "연구" / "네트워크_이론" / "그림"
REGION_HEX = {"Asia": "#2F7FD1", "America": "#2A8F55", "Middle East": "#8F62D8", "Europe": "#B8862A",
              "Oceania": "#1F9C90", "Africa": "#C95A4B", "Other": "#7C8593"}
REGION_KO = {"Asia": "아시아", "America": "아메리카", "Middle East": "중동", "Europe": "유럽", "Oceania": "오세아니아", "Africa": "아프리카"}


def metrics(g):
    """04_compute_metrics와 같은 정의. g: 방향 가중 그래프."""
    n = g.vcount(); m = g.ecount()
    outd = np.array(g.degree(mode="out")); outs = np.array(g.strength(mode="out", weights="weight"))
    p = outs / outs.sum()
    gu = g.as_undirected(mode="collapse", combine_edges="sum")
    part = la.find_partition(gu, la.ModularityVertexPartition, weights="weight", seed=0)
    return dict(density=m / (n * (n - 1)), central=float((outd.max() - outd).sum() / ((n - 1) ** 2)),
                hhi=float((p ** 2).sum()), clust=float(gu.transitivity_avglocal_undirected(mode="zero")),
                modularity=float(part.quality()), kcore=int(max(gu.coreness())), ncomm=len(part))


def toy(edges, n):
    g = ig.Graph(n=n, edges=edges, directed=True)
    g.es["weight"] = [1.0] * g.ecount()
    return g


def normalize(xy):
    """배치 좌표를 가운데로 옮기고 가장 먼 점이 1이 되게 줄인다. 네 칸이 같은 틀을 쓰게 한다."""
    xy = np.asarray(xy, float)
    xy = xy - (xy.max(0) + xy.min(0)) / 2
    return xy / np.abs(xy).max()


def fig1():
    n = 12
    star = toy([(0, j) for j in range(1, n)], n)                                   # 한 나라가 모두에게 수출
    rng = np.random.default_rng(3)
    disp = toy([(i, (i + k) % n) for i in range(n) for k in (1, 2)], n)            # 모두가 이웃 둘에게 수출
    a, b = list(range(6)), list(range(6, 12))                                       # 두 블록 + 다리 하나
    comm = toy([(i, j) for grp in (a, b) for i in grp for j in grp if i != j and rng.random() < 0.55] + [(5, 6)], n)
    core = toy([(i, j) for i in range(5) for j in range(5) if i != j] + [(i % 5, i) for i in range(5, 12)], n)
    panels = [("(가) 별형", star, "한 허브가 모두에게 공급", "star"), ("(나) 분산형", disp, "모두가 이웃 둘에게 공급", "circle"),
              ("(다) 두 공동체", comm, "안으로 촘촘, 사이는 선 하나", "kk"), ("(라) 핵심-주변", core, "5개국 핵심 + 주변 7개국", "kk")]
    fig, axes = plt.subplots(1, 4, figsize=(16, 5.2))
    vals = {}
    for ax, (title, g, sub, how) in zip(axes, panels):
        mt = metrics(g); vals[title] = mt
        lay = g.layout_star(center=0) if how == "star" else (g.layout_circle() if how == "circle" else g.layout("kk"))
        xy = normalize(lay.coords)
        for e in g.es:
            s, t = e.tuple
            ax.annotate("", xy=xy[t], xytext=xy[s],
                        arrowprops=dict(arrowstyle="-|>", color="#8A93A3", lw=0.9, shrinkA=7, shrinkB=7, mutation_scale=8))
        deg = np.array(g.degree(mode="all"))
        if "공동체" in title:
            cols = ["#2F7FD1" if v < 6 else "#B8862A" for v in range(n)]
        elif "핵심" in title:
            cols = ["#C95A4B" if v < 5 else "#2F7FD1" for v in range(n)]
        else:
            cols = ["#2F7FD1"] * n
        ax.scatter(xy[:, 0], xy[:, 1], s=60 + 18 * deg, c=cols, edgecolors="white", linewidths=1.2, zorder=3)
        ax.set_title(f"{title}\n{sub}", fontsize=12.5, pad=10)
        ax.set_xlim(-1.3, 1.3); ax.set_ylim(-1.3, 1.3); ax.set_aspect("equal"); ax.axis("off")
        ax.text(0.5, -0.04, f"밀도 {mt['density']:.2f}   중심화 {mt['central']:.2f}   HHI {mt['hhi']:.2f}\n"
                            f"군집 {mt['clust']:.2f}   모듈성 {mt['modularity']:.2f}   최대 k-코어 {mt['kcore']}",
                transform=ax.transAxes, ha="center", va="top", fontsize=11, linespacing=1.6)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.86, bottom=0.17, wspace=0.08)
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "fig1_네가지_전형구조.png", dpi=130, facecolor="white")
    plt.close(fig)
    return vals


def place_labels(ax, fig, xy, radius_pt, names, order):
    """큰 노드부터 이름표를 붙인다. 위·아래·오른쪽·왼쪽 가운데 이미 붙인 이름표와 겹치지 않는 첫 자리를 고른다."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    placed = []
    for k in order:
        r = radius_pt[k] + 2.5
        best, best_ov = None, None
        for dx, dy, ha, va in [(0, r, "center", "bottom"), (0, -r, "center", "top"), (r, 0, "left", "center"), (-r, 0, "right", "center")]:
            t = ax.annotate(names[k], xy=xy[k], xytext=(dx, dy), textcoords="offset points", ha=ha, va=va, fontsize=11, zorder=5,
                            bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="none", alpha=0.85))
            bb = t.get_window_extent(renderer).expanded(1.04, 1.1)
            ov = sum(max(0, min(bb.x1, p.x1) - max(bb.x0, p.x0)) * max(0, min(bb.y1, p.y1) - max(bb.y0, p.y0)) for p in placed)
            if best is None or ov < best_ov:
                if best is not None:
                    best.remove()
                best, best_ov, best_bb = t, ov, bb
            else:
                t.remove()
            if ov == 0:
                break
        placed.append(best_bb)


def fig2():
    raw = json.loads((ROOT / "data" / "interim" / "network" / "8471.json").read_text(encoding="utf-8"))
    con = duckdb.connect(str(DB_PATH), read_only=True)
    mt = {int(r[0]): r[1:] for r in con.execute("""SELECT t, n_nodes, density, centralization_out, hhi_exp, modularity, max_kcore
        FROM mart_net_metrics WHERE level='hs4' AND code='8471' AND variant='w1m_bal' AND t IN (1995, 2024)""").fetchall()}
    fig, axes = plt.subplots(1, 2, figsize=(16, 8.4))
    info = {}
    for ax, year in zip(axes, (1995, 2024)):
        d = raw["years"][str(year)]
        all_nodes = d["n"]; total = d["total"]
        top = max(all_nodes, key=lambda x: x[3]); hub = max(all_nodes, key=lambda x: x[5])
        e1 = [(e[0], e[1]) for e in d["e"] if e[3] == 1]
        keep = sorted({c for pair in e1 for c in pair})                              # 1위 공급선에 닿지 않는 고립 노드는 뺀다
        byid = {x[0]: x for x in all_nodes}
        nodes = [byid[c] for c in keep]; idx = {c: k for k, c in enumerate(keep)}
        el = [(idx[s], idx[t]) for s, t in e1]
        g = ig.Graph(n=len(nodes), edges=el, directed=True)
        seed = np.random.default_rng(7).random((len(nodes), 2)).tolist()
        xy = np.array(g.layout_fruchterman_reingold(niter=2000, seed=seed).coords)
        size = np.array([x[3] + x[4] for x in nodes], float)
        for s, t in el:
            ax.plot([xy[s, 0], xy[t, 0]], [xy[s, 1], xy[t, 1]], color="#9AA3B2", lw=0.6, alpha=0.7, zorder=1)
        area = 12 + 1300 * np.sqrt(size / total)                                     # 산점도 면적(pt²)
        cols = [REGION_HEX.get(x[2], REGION_HEX["Other"]) for x in nodes]
        ax.scatter(xy[:, 0], xy[:, 1], s=area, c=cols, edgecolors="white", linewidths=0.8, zorder=2)
        pad = 0.06 * (xy.max(0) - xy.min(0))
        ax.set_xlim(xy[:, 0].min() - pad[0], xy[:, 0].max() + pad[0]); ax.set_ylim(xy[:, 1].min() - pad[1], xy[:, 1].max() + pad[1])
        ax.set_aspect("equal", adjustable="datalim"); ax.axis("off")                 # 두 칸의 상자 크기를 같게, 비율은 유지
        n_nodes, dens, cen, hhi, mod, kc = mt[year]
        info[year] = dict(top=top[1], top_share=top[3] / total, hub=hub[1], hub_od=hub[5], n=n_nodes, dens=dens, cen=cen, hhi=hhi, mod=mod, kcore=kc,
                          drawn=len(nodes), isolated=len(all_nodes) - len(nodes))
        ax.set_title(f"{year}년   수출 1위 {top[1]} {100 * top[3] / total:.0f}%   최대 연결국 {hub[1]} ({hub[5]}개국)", fontsize=13.5)
        ax.text(0.0, -0.02, f"국가 {n_nodes}   밀도 {dens:.3f}   중심화 {cen:.2f}   HHI {hhi:.3f}   모듈성 {mod:.2f}   최대 k-코어 {kc}",
                transform=ax.transAxes, fontsize=11.5, color="#333", va="top")
        order = list(np.argsort(-size)[:9])
        place_labels(ax, fig, xy, np.sqrt(area / np.pi), [x[1] for x in nodes], order)
    handles = [plt.Line2D([], [], marker="o", ls="", color=REGION_HEX[k], markersize=9, label=v) for k, v in REGION_KO.items()]
    fig.legend(handles=handles, loc="lower center", ncol=6, frameon=False, fontsize=11.5)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.94, bottom=0.1, wspace=0.05)
    fig.savefig(OUT / "fig2_컴퓨터_1995_2024.png", dpi=120, facecolor="white")
    plt.close(fig)
    return info


if __name__ == "__main__":
    v1 = fig1()
    for k, v in v1.items():
        print(k, {a: round(b, 3) if isinstance(b, float) else b for a, b in v.items()})
    v2 = fig2()
    for k, v in v2.items():
        print(k, {a: round(b, 3) if isinstance(b, float) else b for a, b in v.items()})
