# NOTICE — 자료에 관한 고지

[`LICENSE`](LICENSE)(MIT)는 **이 저장소의 코드와 문서에만** 적용된다.
아래 자료는 그 대상이 아니며 제공기관의 조건을 따른다.

## 원자료

| 자료 | 제공 | 조건 |
|---|---|---|
| BACI HS92, 판본 V202601 (1995–2024) | CEPII (Centre d'Études Prospectives et d'Informations Internationales) | Etalab Open Licence 2.0 — 이용·재배포·가공 자유, **출처표시 의무** |
| 미국 CPI-U 연평균 1995~2024 (`config/us_cpi_u_annual.csv`) | 미국 노동통계국(BLS), FRED(CPIAUCNS) 경유 | 미국 연방정부 저작물, 공공 영역 |

인용: Gaulier, G. and Zignago, S. (2010) "BACI: International Trade Database at the Product-Level. The 1994-2007 Version", CEPII Working Paper 2010-23. 판본 V202601, 2026-01-30 공개.

BACI는 UN 통계국(UNSD)의 UN Comtrade 보고를 CEPII가 조정해 만든 자료다. 이 저장소는 UN Comtrade 원자료를 담거나 재배포하지 않는다.

## 배포되는 파생 자료

`docs/data/*.js`는 BACI를 가공한 파생물이다. 가공 내용: 30년 내내 교역이 있는 207개국으로 노드 제한, 100만 달러 미만 흐름 제외, HS6를 HS4로 합산, 각 수입국의 상위 3개 공급국만 엣지로 보관, 금액을 천 달러에서 달러로 환산, PageRank 등 지표 계산. 이 파일을 다시 쓸 때도 위 BACI 출처표시를 유지해야 한다.

지역 분류(아시아·아메리카·중동·유럽·오세아니아·아프리카)는 이 저장소가 붙인 것이다.

CEPII가 이 저장소를 후원하거나 특수 관계에 있는 것으로 오인하게 하는 표시를 해서는 안 된다.
