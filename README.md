# TradeNetworkAtlas — 품목별 세계 교역 네트워크 (1995–2024)

[![License: MIT](https://img.shields.io/badge/code-MIT-green.svg)](LICENSE)
[![Dashboard](https://img.shields.io/badge/%EB%8C%80%EC%8B%9C%EB%B3%B4%EB%93%9C-pilsunchoi.github.io%2FTradeNetworkAtlas-1f6feb)](https://pilsunchoi.github.io/TradeNetworkAtlas/)

CEPII의 BACI(HS92) 양자 무역 자료로 품목마다 나라를 노드, 수출입 흐름을 엣지로 하는 네트워크를 해마다 만들고, 그 구조가 30년 동안 어떻게 바뀌었는지를 본다. 대시보드에서 12개 주요 품목의 네트워크를 연도별로 넘겨 볼 수 있고, 연구 탭에 네트워크 지표 해설과 분석 보고서가 있다.

## 무엇이 들어 있나

| 경로 | 내용 |
|---|---|
| `docs/index.html` | 대시보드(GitHub Pages). 품목 선택, 연도 슬라이더와 재생, 공급국 링크 수(1~3), 색 기준(지역·PageRank·수출 비중), 국가 강조, 표, 정보, 연구 탭 |
| `docs/data/*.js` | 대시보드 자료. 품목별 1995–2024년 노드(수출입·상대국 수·PageRank·상위 공급국과 상대국)와 각 수입국의 상위 3개 공급국 엣지 |
| `analysis/네트워크_이론/` | 해설 문서 「교역 네트워크를 읽는 지표」, 그림 두 장, 그림과 인용 수치를 만드는 노트북 |
| `analysis/중국허브화/` | 분석 보고서 「중국 허브화와 세계 교역 네트워크, 1995~2024」, 그림 여섯 장, 표 수치와 그림을 만드는 노트북 |
| `scripts/` | BACI 적재부터 네트워크 지표와 대시보드 자료까지 만드는 스크립트 |
| `config/settings.py` | 경로와 BACI 판본 |
| `config/us_cpi_u_annual.csv` | 미국 CPI-U 연평균(1995~2024, FRED CPIAUCNS). 실질 임곗값 변형에 쓴다 |

대시보드의 12개 품목(HS92 4자리): 컴퓨터 8471, 집적회로 8542, 무선 송신기기 8525, TV·모니터 8528, 승용차 8703, 자동차 부품 8708, 선박 8901, 원유 2709, 석유제품 2710, 의약품 3004, 티셔츠 6109, 대두 1201.

## 네트워크 정의

- 노드: 1995–2024년 매년 수출과 수입이 모두 있는 207개국. 100만 달러 미만 흐름은 뺐다(명목 기준). 연구 폴더의 견고성 분석에는 1995년 불변가격 100만 달러를 미국 CPI-U로 환산한 실질 임곗값 변형도 있다.
- 엣지: 수출국 → 수입국, 가중치는 금액(BACI 원산지 기준, 달러).
- 대시보드의 선은 각 수입국을 그해 상위 N개 공급국에만 잇는다. 지표는 줄이기 전의 전체 그래프에서 계산한다.
- 대만은 BACI 코드 490("Other Asia, nes")이다.

## 다시 만들기

BACI 원자료와 DuckDB 파일은 저장소에 없다(각 2.4GB·4GB). CEPII 누리집에서 `BACI_HS92_V202601.zip`을 받아 `data/raw/baci/`에 둔다.

```
conda activate kcsdb                      # Python 3.12, duckdb, pandas, igraph, leidenalg, statsmodels, matplotlib
python scripts/01_load_baci.py            # zip → fact_baci (2억 6,989만 행)
python scripts/02_build_dims.py           # dim_country(지역), dim_product(HS 부)
python scripts/03_build_edges.py          # edge_total, edge_hs2, edge_hs4
python scripts/04_compute_metrics.py --level total
python scripts/04_compute_metrics.py --level hs2 --workers 4
python scripts/04_compute_metrics.py --level hs4 --workers 6   # mart_net_metrics, mart_net_nodes (변형 raw, w1m, w1m_bal, w1m_bal_xchn, 실질 임곗값 w1m_bal_real과 w1m_bal_xchn_real)
python scripts/05_validate.py             # 적재·범위·한국 수출 대조
python scripts/10_export_network_json.py  # docs/data/*.js
```

연구 폴더의 표 수치와 그림은 각 폴더의 `분석_파이썬_코드.ipynb`가 만든다(커널 "Python (kcsdb)"). 위에서 아래로 실행하면 그림은 `img/`에, 표는 `outputs/`(저장소 제외)에 저장된다. 보고서 노트북은 마지막 셀에서 보고서가 인용한 수치를 다시 계산해 대조한다.

`02`의 지역 분류는 KCSDB2의 국가 표를 쓰므로 그 DB가 같은 머신에 있어야 한다(`config/settings.py`의 `KCSDB_PATH`). 없으면 지역이 비고 나머지는 그대로 돈다.

대시보드를 로컬에서 보려면:

```
python -m http.server 8765 --directory docs
```

## 출처와 이용 조건

- **자료**: BACI — Gaulier, G. and Zignago, S. (2010) "BACI: International Trade Database at the Product-Level. The 1994-2007 Version", CEPII Working Paper 2010-23. 판본 V202601(2026-01-30 공개). 라이선스 Etalab Open Licence 2.0, 출처표시 의무.
- BACI는 UN Comtrade의 보고를 조정해 만든 자료다. 이 저장소는 UN Comtrade 원자료를 담거나 재배포하지 않는다.
- 코드와 문서는 [MIT 라이선스](LICENSE)를 따른다. `docs/data/`의 자료는 BACI의 파생물이므로 BACI의 조건을 따른다. 상세는 [NOTICE](NOTICE.md).
