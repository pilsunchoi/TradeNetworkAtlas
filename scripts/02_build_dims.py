"""dim_country, dim_product 구축.

dim_country: BACI 국가코드표(raw_country_codes) 그대로에 대륙(region)을 붙인다.
  region은 KCSDB2 dim_country.continent_common을 ISO3로 조인해 가져오고, 없으면 아래 수동표로 보충한다.
dim_product: BACI 품목코드표(raw_product_codes)에 hs4, hs2, HS 부(section)를 붙인다.
"""
import sys
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.settings import DB_PATH, KCSDB_PATH
import duckdb

# 지역 체계: KCSDB2 dim_country.continent_common을 따른다(Asia, Europe, Africa, America, Middle East).
# KCSDB2는 오세아니아를 따로 두지 않으므로 아래 ISO3 목록으로 Oceania를 보충하고,
# 'South America'·'North America'는 America로, 'Australia(Oceania)'는 Oceania로 통일한다.
REGION_NORMALIZE = {"South America": "America", "North America": "America", "Australia(Oceania)": "Oceania"}
OCEANIA_ISO3 = {"AUS", "NZL", "PNG", "FJI", "SLB", "VUT", "WSM", "TON", "KIR", "FSM", "MHL", "NRU", "PLW", "TUV",
                "NCL", "PYF", "GUM", "COK", "NIU", "WLF", "ASM", "MNP", "NFK", "PCN", "TKL"}

# KCSDB2에 없거나 BACI 고유 코드인 경우의 지역 보충. (BACI 코드 → 지역)
MANUAL_REGION = {
    410: "Asia",       # Rep. of Korea (KCSDB2 국가표는 상대국 목록이라 한국 자신이 없다)
    408: "Asia",       # Dem. People's Rep. of Korea
    490: "Asia",       # Other Asia, nes (대만)
    58: "Europe",      # Belgium-Luxembourg (1995-98)
    200: "Europe",     # Czechoslovakia
    280: "Europe",     # Fmr Fed. Rep. of Germany
    810: "Europe",     # Fmr USSR
    890: "Europe",     # Fmr Yugoslavia
    891: "Europe",     # Serbia and Montenegro
    728: "Africa",     # South Sudan
    729: "Africa",     # Sudan (2012-)
    736: "Africa",     # Fmr Sudan
    535: "America",    # Bonaire, Sint Eustatius and Saba
    531: "America",    # Curaçao
    534: "America",    # Sint Maarten
    530: "America",    # Netherlands Antilles
    849: "Oceania",    # US Misc. Pacific Isds
}

# HS 부(section) — 류 범위와 짧은 이름. 품목군 비교용.
HS_SECTIONS = [
    (1, 5, "I", "동물성 생산품"), (6, 14, "II", "식물성 생산품"), (15, 15, "III", "유지"),
    (16, 24, "IV", "식품·음료·담배"), (25, 27, "V", "광물성 생산품"), (28, 38, "VI", "화학공업 생산품"),
    (39, 40, "VII", "플라스틱·고무"), (41, 43, "VIII", "가죽·모피"), (44, 46, "IX", "목재·코르크"),
    (47, 49, "X", "펄프·종이"), (50, 63, "XI", "섬유"), (64, 67, "XII", "신발·모자"),
    (68, 70, "XIII", "석·도자·유리"), (71, 71, "XIV", "귀금속·보석"), (72, 83, "XV", "비금속(卑金屬)"),
    (84, 85, "XVI", "기계·전기기기"), (86, 89, "XVII", "운송장비"), (90, 92, "XVIII", "정밀·의료·시계·악기"),
    (93, 93, "XIX", "무기"), (94, 96, "XX", "잡품"), (97, 99, "XXI", "예술품·기타"),
]


def section_of(ch):
    for lo, hi, sec, name in HS_SECTIONS:
        if lo <= ch <= hi:
            return sec, name
    return None, None


def main():
    con = duckdb.connect(str(DB_PATH))
    cols = [c[0] for c in con.execute("DESCRIBE raw_country_codes").fetchall()]
    print("raw_country_codes 열:", cols)
    # BACI 코드표 열 이름은 판본마다 조금 다르다. 있는 것만 쓴다.
    code_col = next(c for c in cols if "code" in c.lower())
    name_col = next(c for c in cols if "name" in c.lower())
    iso3_col = next((c for c in cols if "iso3" in c.lower()), None)
    iso2_col = next((c for c in cols if "iso2" in c.lower()), None)
    # BACI 국가코드 파일의 일부 국명이 이중 인코딩돼 있다(예: 'TÃ¼rkiye'). latin-1로 되돌려 UTF-8로 다시 읽으면 복원된다.
    def fix_mojibake(s):
        if s is None:
            return None
        try:
            fixed = s.encode("latin-1").decode("utf-8")
            return fixed if fixed != s else s
        except (UnicodeEncodeError, UnicodeDecodeError):
            return s
    con.create_function("fix_mojibake", fix_mojibake, ["VARCHAR"], "VARCHAR")
    con.execute(f"""CREATE OR REPLACE TABLE dim_country AS
        SELECT CAST({code_col} AS INTEGER) AS country_code,
               fix_mojibake({name_col}) AS country_name,
               {f"{iso2_col}" if iso2_col else "NULL"} AS iso2,
               {f"{iso3_col}" if iso3_col else "NULL"} AS iso3,
               CAST(NULL AS VARCHAR) AS region,
               CAST(NULL AS VARCHAR) AS region_source
        FROM raw_country_codes""")

    if KCSDB_PATH.exists():
        con.execute(f"ATTACH '{KCSDB_PATH.as_posix()}' AS k (READ_ONLY)")
        con.execute("""UPDATE dim_country SET region = s.continent_common, region_source = 'kcsdb2'
            FROM (SELECT iso3, any_value(continent_common) continent_common FROM k.dim_country
                  WHERE iso3 IS NOT NULL AND continent_common IS NOT NULL GROUP BY iso3) s
            WHERE dim_country.iso3 = s.iso3""")
        con.execute("DETACH k")
        for old, new in REGION_NORMALIZE.items():
            con.execute("UPDATE dim_country SET region = ? WHERE region = ?", [new, old])
    con.execute("UPDATE dim_country SET region = 'Oceania', region_source = 'manual' WHERE iso3 IN (SELECT unnest(?))",
                [sorted(OCEANIA_ISO3)])
    for code, reg in MANUAL_REGION.items():
        con.execute("UPDATE dim_country SET region = ?, region_source = 'manual' WHERE country_code = ? AND region IS NULL",
                    [reg, code])
    n, n_reg = con.execute("SELECT count(*), count(region) FROM dim_country").fetchone()
    print(f"dim_country: {n}개국, region 있음 {n_reg}")
    print("region 분포:", con.execute("SELECT region, count(*) FROM dim_country GROUP BY 1 ORDER BY 2 DESC").fetchall())
    missing = con.execute("""SELECT country_code, country_name, iso3 FROM dim_country
        WHERE region IS NULL AND country_code IN (SELECT DISTINCT i FROM fact_baci WHERE t = 2024)""").fetchall()
    print("2024년 수출국 중 region 없음:", missing)

    pcols = [c[0] for c in con.execute("DESCRIBE raw_product_codes").fetchall()]
    print("raw_product_codes 열:", pcols)
    pcode = next(c for c in pcols if "code" in c.lower())
    pdesc = next(c for c in pcols if "desc" in c.lower())
    con.execute(f"""CREATE OR REPLACE TABLE dim_product AS
        SELECT lpad({pcode}, 6, '0') AS hs6, {pdesc} AS description,
               substr(lpad({pcode}, 6, '0'), 1, 4) AS hs4, substr(lpad({pcode}, 6, '0'), 1, 2) AS hs2,
               CAST(NULL AS VARCHAR) AS section, CAST(NULL AS VARCHAR) AS section_name
        FROM raw_product_codes""")
    for lo, hi, sec, name in HS_SECTIONS:
        con.execute("UPDATE dim_product SET section = ?, section_name = ? WHERE CAST(hs2 AS INTEGER) BETWEEN ? AND ?",
                    [sec, name, lo, hi])
    # fact에 있는데 코드표에 없는 HS6 확인
    orphan = con.execute("""SELECT count(DISTINCT k) FROM fact_baci WHERE k NOT IN (SELECT hs6 FROM dim_product)""").fetchone()[0]
    print(f"dim_product: {con.execute('SELECT count(*) FROM dim_product').fetchone()[0]}개 HS6; fact에만 있는 코드 {orphan}개")
    con.execute("""CREATE OR REPLACE TABLE dim_build_log AS SELECT ? AS built_at""", [dt.datetime.now()])
    con.close()


if __name__ == "__main__":
    main()
