"""대시보드용 네트워크 JSON 추출. 여러 품목, 1995–2024 연도별, 품목당 파일 하나(압축 배열 형식).

사용: python scripts/10_export_network_json.py            # PRODUCTS 전부
      python scripts/10_export_network_json.py --codes 8471,8542
조건: w1m_bal (고정 207개국, 100만 달러 이상). 각 수입국을 상위 3개 공급국에 연결(대시보드에서 1~3 선택).
출력: docs/data/<code>.js, docs/data/products.js (대시보드용). 같은 내용의 JSON은 data/interim/network/ (로컬)
노드 배열: [iso, name, region, exp, imp, out_degree, in_degree, pagerank, sup[[iso,v]...], dst[[iso,v]...]]  (금액 달러)
엣지 배열: [exporter_iso, importer_iso, v, rank]
"""
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.settings import DB_PATH, ROOT
import duckdb
import igraph as ig

PRODUCTS = [  # (HS92 4자리, 한국어 이름, 짧은 영문)
    ("8471", "컴퓨터 (자동자료처리기계)", "Computers"),
    ("8542", "집적회로 (반도체)", "Integrated circuits"),
    ("8525", "무선 송신기기 (휴대전화 포함, HS92 기준)", "Radio/TV transmitters incl. mobile phones"),
    ("8528", "TV·모니터 수상기", "Television receivers"),
    ("8703", "승용차", "Passenger cars"),
    ("8708", "자동차 부품", "Motor vehicle parts"),
    ("8901", "선박 (여객선·화물선)", "Ships"),
    ("2709", "원유", "Crude petroleum"),
    ("2710", "석유제품", "Refined petroleum"),
    ("3004", "의약품 (조제)", "Medicaments"),
    ("6109", "티셔츠·내의 (메리야스)", "T-shirts"),
    ("1201", "대두", "Soybeans"),
]
SHORT = {"Rep. of Korea": "Korea", "USA": "United States", "China, Hong Kong SAR": "Hong Kong", "Other Asia, nes": "Taiwan",
         "Russian Federation": "Russia", "Viet Nam": "Vietnam", "United Arab Emirates": "UAE",
         "Bolivia (Plurinational State of)": "Bolivia", "Venezuela (Bolivarian Republic of)": "Venezuela",
         "Lao People's Dem. Rep.": "Laos", "Dem. People's Rep. of Korea": "North Korea", "Dem. Rep. of the Congo": "DR Congo",
         "China, Macao SAR": "Macao", "Rep. of Moldova": "Moldova", "United Rep. of Tanzania": "Tanzania",
         "Syrian Arab Republic": "Syria", "Brunei Darussalam": "Brunei", "TFYR of Macedonia": "North Macedonia",
         "State of Palestine": "Palestine", "Bosnia Herzegovina": "Bosnia", "Saint Kitts and Nevis": "St Kitts",
         "Saint Vincent and the Grenadines": "St Vincent", "Saint Lucia": "St Lucia", "Antigua and Barbuda": "Antigua",
         "Trinidad and Tobago": "Trinidad", "Iran": "Iran", "Türkiye": "Türkiye"}
TOPN = 3


def export_one(con, meta, code):
    desc_rows = con.execute("SELECT hs6, description FROM dim_product WHERE hs4 = ? ORDER BY hs6", [code]).fetchall()
    edges = con.execute("""
        SELECT t, i, j, v FROM edge_hs4
        WHERE code = ? AND v >= 1000 AND i IN (SELECT country_code FROM dim_fixed_country) AND j IN (SELECT country_code FROM dim_fixed_country)
        ORDER BY t, j, v DESC""", [code]).df()
    years, facts = {}, {}
    for t, g in edges.groupby("t"):
        nodes_set = sorted(set(g.i) | set(g.j))
        idx = {c: k for k, c in enumerate(nodes_set)}
        G = ig.Graph(n=len(nodes_set), edges=list(zip(g.i.map(idx), g.j.map(idx))), directed=True)
        G.es["weight"] = g.v.values.astype(float)
        pr = G.pagerank(weights="weight", directed=True)
        exp = g.groupby("i").v.sum(); imp = g.groupby("j").v.sum()
        outd = g.groupby("i").size(); ind = g.groupby("j").size()
        sup = {jj: [(int(r.i), float(r.v)) for r in gg.head(5).itertuples()] for jj, gg in g.groupby("j")}
        dst = {ii: [(int(r.j), float(r.v)) for r in gg.sort_values("v", ascending=False).head(5).itertuples()] for ii, gg in g.groupby("i")}
        nodes = []
        for c in nodes_set:
            m = meta[c]
            nodes.append([m["iso"], m["name"], m["region"], round(float(exp.get(c, 0.0)) * 1000), round(float(imp.get(c, 0.0)) * 1000),
                          int(outd.get(c, 0)), int(ind.get(c, 0)), round(pr[idx[c]], 5),
                          [[meta[s]["iso"], round(v * 1000)] for s, v in sup.get(c, [])],
                          [[meta[d]["iso"], round(v * 1000)] for d, v in dst.get(c, [])]])
        el = []
        for jj, gg in g.groupby("j"):
            for r_, row in enumerate(gg.head(TOPN).itertuples(), start=1):
                el.append([meta[row.i]["iso"], meta[jj]["iso"], round(float(row.v) * 1000), r_])
        total = float(g.v.sum()) * 1000
        years[int(t)] = dict(n=nodes, e=el, total=round(total))
        top = sorted(nodes, key=lambda n: -n[3])[:3]
        facts[int(t)] = [[n[1], round(n[3] / total, 3)] for n in top]
    return dict(code=code, years=years), desc_rows, facts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default="")
    a = ap.parse_args()
    codes = [c for c in a.codes.split(",") if c] or [p[0] for p in PRODUCTS]
    names = {p[0]: (p[1], p[2]) for p in PRODUCTS}
    con = duckdb.connect(str(DB_PATH), read_only=True)
    cn = con.execute("SELECT country_code, iso3, country_name, region FROM dim_country").df()
    meta = {int(r.country_code): dict(iso=r.iso3 if r.iso3 != "S19" else "TWN", name=SHORT.get(r.country_name, r.country_name), region=r.region or "Other")
            for r in cn.itertuples()}
    out_dir = ROOT / "docs" / "data"
    json_dir = ROOT / "data" / "interim" / "network"
    json_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = json_dir / "products.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"products": []}
    existing = {p["code"]: p for p in index["products"]}
    for code in codes:
        payload, desc_rows, facts = export_one(con, meta, code)
        p = json_dir / f"{code}.json"
        js_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        p.write_text(js_text, encoding="utf-8")
        # 게시 환경은 fetch를 막고 <script>만 허용하므로 같은 내용을 전역 변수에 담는 .js로도 쓴다.
        (out_dir / f"{code}.js").write_text(f'window.__NET=window.__NET||{{}};window.__NET["{code}"]={js_text};', encoding="utf-8")
        ko, en = names.get(code, (f"HS {code}", f"HS {code}"))
        existing[code] = dict(code=code, name_ko=ko, name_en=en, hs6=[[h, d] for h, d in desc_rows],
                              facts={str(y): facts[y] for y in (1995, 2005, 2015, 2024) if y in facts},
                              years=[min(payload["years"]), max(payload["years"])])
        yy = payload["years"][2024]
        print(f"{code} {ko}: {p.stat().st_size/1e6:.2f} MB, 2024 nodes {len(yy['n'])}, edges {len(yy['e'])}, top: {facts[2024]}")
    order = [p[0] for p in PRODUCTS] + [c for c in existing if c not in names]
    index["products"] = [existing[c] for c in order if c in existing]
    index["source"] = "BACI HS92 V202601 (CEPII). 고정 207개국, 100만 달러 이상 흐름, 각 수입국의 상위 3개 공급국."
    idx_text = json.dumps(index, ensure_ascii=False, separators=(",", ":"))
    index_path.write_text(idx_text, encoding="utf-8")
    (out_dir / "products.js").write_text(f"window.__PRODUCTS={idx_text};", encoding="utf-8")
    print(f"products.json: {len(index['products'])}개 품목")


if __name__ == "__main__":
    main()
