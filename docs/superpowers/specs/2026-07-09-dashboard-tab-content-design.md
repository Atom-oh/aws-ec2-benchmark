# 통합 대시보드 탭 콘텐츠·골격·스키마 상세 설계

- **작성일**: 2026-07-09
- **대상**: EKS EC2 Node Benchmark 프로젝트 (54개 xlarge 인스턴스)
- **전제**: [2026-07-08-unified-dashboard-design.md](2026-07-08-unified-dashboard-design.md)(상위 설계)를
  확장한다. site/ 레이아웃, 배포 절차, 데이터 파이프라인 정책(재사용 우선/검증 게이트)은 그 문서를
  따르며 여기서 재정의하지 않는다.

## 1. 배경

상위 설계 승인 후 "각 벤치마다 다른 종류의 내용을 담으므로 어떻게 설계할지 고민이 더 필요"라는
피드백을 받았다. 11개 레거시 리포트(`reports/*-report.html`)의 전 섹션·차트(총 ~130개 캔버스)·
위젯·인사이트 박스를 전수 카탈로그한 뒤, 그 결과를 기반으로 ①콘텐츠 보존 범위 ②탭 내부 구조
표준화 ③데이터 스키마 설계 3개 층위를 확정한다.

**전수 조사 핵심 발견:**
- 11개 리포트 전부가 이미 같은 자연 골격을 따른다: hero → 요약카드 → 목차 → 방법론 → Top-N 차트 →
  arch×gen(메트릭 스위처) → 패밀리 → 세대 개선율 → 가격 3-tab → avoid → 추천 → 전체 테이블 → 결론
- 같은 코드가 11벌 중복되어 있다: 3-tab 가격 섹션(함수명 11개), 메트릭 스위처(`select*MetricTab` ×
  11), 필터/정렬 테이블(구현 2종 × 11벌), AMD-gen5/Graviton-no-gen5 null 마스킹
- 레거시 데이터 지뢰: redis GET/Mixed 효율 차트는 **조작값**(ops×1.1/×1.05), passmark는 테이블과
  `priceData` 배열이 불일치, ES는 Graviton 세대를 2/3/4로 표기(다른 리포트는 6/7/8), 모든 탭 핸들러가
  전역 `event.target`에 의존

## 2. 표준 탭 골격 및 렌더 계약

### 2.1 캐노니컬 섹션 시퀀스

11개 탭 전부가 아래 순서를 따른다. 슬롯 A/B는 비어도 된다(nginx가 그 사례).

```
1. hero            제목/부제/커버리지 배지(N/54)/측정일 — 정적 HTML
2. summaryCards    4~6장, JS 계산(shared), expandHtml 옵션으로 확장형(redis/ES) 지원
3. toc             shared.buildToc(root)가 section[id]>h2 스캔 자동 생성 — 수동 TOC 금지
4. methodology     환경 테이블 + 방법론/캐비어트 박스 — 정적 HTML(+ data notes 삽입 가능)
5. [SLOT A]        벤치마크 고유 메인 분석 (kafka 3-phase, ES 페이지탭, springboot 시나리오…)
6. standardCharts  topNBar + metricTabChart(arch×gen) + familyChart + genImprovement
7. priceSection    3-tab: 버블 / 효율 Top-N / 지표별 grid-3 — shared
8. [SLOT B]        벤치마크 고유 보조 분석 (redis 모달, clickhouse per-query 탐색기…)
9. resultTable     검색 + arch/gen/family 필터 + 정렬 — shared
10. conclusion     정적 서사 + 선택적 computed 인사이트 박스(kafka 패턴)
```

### 2.2 렌더 계약 — 명령형(imperative) 채택

**결정: 선언형(HTML data-attribute 자동배선) 기각, 명령형 JS 호출 채택.**

이유: 컴포넌트 설정이 본질적으로 JS 객체(메트릭 배열·컬럼 정의·포맷 함수·인사이트 콜백)라 HTML
속성으로는 함수 전달이 불가능하고 이스케이프 지옥이 된다. 유지보수자가 Claude 세션이므로 "shared.js
JSDoc + 레퍼런스 탭(sysbench)을 그대로 따라 하라"는 단일 패턴이 가장 안전하다.

**계약** (`site/CLAUDE.md` 또는 프로젝트 CLAUDE.md에 이관할 문구):

- `tabs/<b>.html`은 정적 서사 전부 + 빈 컨테이너(`<div id="...">`, `<canvas id="...">`)만 담는다.
  **JS·인라인 이벤트 핸들러(onclick 등) 금지.**
- `js/tabs/<b>.js`는 `export async function render(root, {data, instances})` 하나만 export한다.
  이 함수가 shared 컴포넌트를 `root.querySelector`로 호출하고, 팩토리에 안 맞는 고유 차트를 직접
  Chart.js로 그리며, 이벤트 리스너는 전부 root 스코프로 부착한다(**전역 `event.target` 금지** —
  레거시 11개 전부 이 패턴을 쓰고 있어 이번 재작성에서 전면 교체).
- 라우터(`js/app.js`)는 한 번에 한 탭만 DOM에 마운트한다(innerHTML 교체, 파셜 텍스트는 캐시). 따라서
  탭 간 id 충돌이 없다 — id 네임스페이스 프리픽스 불필요.
- 탭 전환 시 이전 탭의 Chart.js 인스턴스를 정리해야 한다. `render()`는 `{destroy(): void}`를
  반환하거나, 생성한 Chart 인스턴스 배열을 반환해 라우터가 destroy를 호출할 수 있게 한다.

### 2.3 shared.js 컴포넌트 — 이것이 전부 (추가 금지 원칙)

| 컴포넌트 | 요지 | 흡수하는 레거시 중복 |
|---|---|---|
| `loadData(name)` | `data/<b>.json` + `data/instances.json` fetch·조인 → `rows[]`(arch/gen/family/price 부착, 효율 파생값 계산) | 11벌 |
| `summaryCards(el, cards)` | `{label, value, detail, expandHtml?}[]`. expandHtml 있으면 클릭 확장 | redis/ES 확장 카드 포함 전체 |
| `topNBar(el, rows, {metrics, n, ascending?})` | `metrics`가 2개 이상이면 스위처 탭 자동 생성. `ascending:true`가 avoid(Bottom-N) 차트 | Top-N 전부 + avoid 4종 + sysbench 메모리 Top-25 6캔버스→1 |
| `metricTabChart(el, rows, metrics)` | arch×gen 그룹 바 + 메트릭 스위처. `metric.insightHtml?`로 탭 내부 인사이트(stress-ng 패턴) 지원. gen축 null 마스킹(AMD gen5만 존재/Graviton gen5 없음) 내장 | `select*MetricTab` 11개 함수 + passmark 4-way + stress-ng 7-way(드롭다운도 탭 버튼으로 흡수) |
| `familyChart(el, rows, metric)` | C/M/R 패밀리 비교 | 전부 |
| `genImprovement(el, rows, metric)` | 세대별 개선율 | 전부 |
| `priceSection(el, rows, {mainMetric, gridMetrics})` | 3-tab: 버블 차트 / 효율 Top-N / 지표별 grid-3 | 11개 함수명·3종 탭-id 관례 통일 |
| `resultTable(el, rows, columns)` | 검색 + arch/gen/family 필터 + 헤더 정렬. 필터값은 `instances.json`의 canonical casing만 사용 | 구현 2종(JS 렌더/DOM hide) × 11벌 + `'Graviton'` vs `'graviton'` 불일치 |
| `buildToc(root)` | `section[id] > h2`를 스캔해 목차 자동 생성 | 수동 TOC 11벌 |
| 헬퍼 `ARCH_COLORS` / `badge()` / `fmt()` / `genAxis()` | 색상·배지·포맷·세대축 마스킹 | 중복 로직 전체 |

`metric` 설정 표준형: `{field, label, unit, direction: 'max'|'min', fmt?}`. `field`는 dot-path를
지원한다(예: `"rally.throughput"`, `"max.zstd.produce_mb_per_sec"`).

## 3. 탭별 콘텐츠 명세

범례: ✅유지(shared 컴포넌트) · 🔧유지(bespoke, 탭 모듈 내 자체 구현) · 📄정적(파셜 HTML) ·
🧮computed(렌더타임 데이터 계산) · ❌드롭

| 탭 | 유지 | bespoke (SLOT) | 드롭 (사유) |
|---|---|---|---|
| **sysbench** (레퍼런스) | 표준 골격 전체. 메모리 Top-25 6캔버스→`topNBar` 1개+스위처 | 점선 family 트렌드 라인차트(Intel 실선/Graviton 점선) | 없음 |
| **geekbench** (51) | 표준 골격 | gen 트렌드의 family-vs-arch 뷰 토글(데이터셋 재그루핑, 소형 자체 구현) | 없음 |
| **passmark** (51) | 표준 골격. 4-way 상세테스트(Int/Float/Enc/Comp)→`metricTabChart`. x86-bias 캐비어트 박스 📄 | — | Intel/Graviton 이중 라인차트(정보 중복). `priceData` 배열(테이블과 불일치 — **정본은 HTML 51행 하드코딩 테이블**) |
| **stress-ng** (51) | 7-way→`metricTabChart`(탭별 인사이트는 `insightHtml`로 이식) | — | `<select>` 드롭다운(유일 예외 UI, 탭 버튼으로 통일) |
| **iperf3** | 표준 골격(single/parallel/reverse/udp 스위처) | — | 없음. 추천 카드 6장·env 그리드·메트릭 정의 테이블은 📄 정적 유지 |
| **elasticsearch** | 확장형 summaryCards ✅, 토글그룹 2개→`metricTabChart` | Rally/Coldstart/종합 페이지탭(섹션 show/hide, ~20줄), scatter 차트, dual-axis 차트 | 없음. rally는 51개(c8gn/r8gd는 null → 차트 자동 제외, 테이블엔 "—") 🧮 |
| **redis** | SET/GET 토글→`metricTabChart`, 확장형 summaryCards | 인스턴스 상세 모달(클릭→5-run 통계+CV 해석, 스키마의 `*_all[5]` 배열 사용) | **GET/Mixed 효율 차트 — 조작값(ops×1.1/×1.05)이므로 폐기.** GET은 `results/redis/benchmark_data.json`의 실측 `get_rps_avg`로 **교체**(드롭이 아니라 근본 해결). Mixed는 실측 데이터가 없어 완전 폐기 |
| **nginx** (최소) | 표준 골격 100%, 슬롯 비움 — "슬롯은 비어도 된다"는 증명 사례 | — | 없음 |
| **springboot** (최대) | 시나리오 탭(50/100/200 conn)→`metricTabChart`, coldstart는 표준 컴포넌트 | family-filter 비교 차트, **600초 time-series 라인차트**(6인스턴스×60pt×3지표, 메트릭 스위처), Flex vs Standard 서사(타일 수치는 🧮) | 없음(캔버스 20+개를 스위처 통합으로 ~12개로 압축만) |
| **kafka** (데이터 주도) | 표준 섹션은 shared로 치환(기존 자체 구현 버림) | 3-phase 구조 통째 이식(베이스라인/§9 포화+코덱/§10 램프), 레이턴시 커브 다중선택(≤5), empty-state 처리 | 없음. 동적 인사이트 5개(produceInsight 등)는 🧮 — **computed 패턴의 레퍼런스 구현** |
| **clickhouse** (데이터 주도) | breakdown 그루핑 탭→`metricTabChart` | per-query 탐색기(q00-q42 드롭다운 + arch/family 필터 + SQL 표시 + 차트 + 테이블), iso-value 컨투어 버블 | 없음. SQL 라이브러리는 데이터의 `queries` 키에서 렌더 🧮 |

**인사이트/서사 처리 원칙(전 탭 공통):** 특정 수치를 인용하지 않는 해석·방법론 서사는 정적 HTML로
둔다. 수치를 인용하는 문장(예: "최고 X가 Y보다 N% 빠름")은 kafka 패턴을 따라 computed 박스로
이관하거나, 이식 시점 데이터로 텍스트를 갱신해 정적으로 굳힌다. **판단 기준: 54개 백필로 값이 바뀔
수 있는 문장은 반드시 computed로 만든다** — 51→54 인스턴스 확장이 이 프로젝트에서 반복되는 패턴이기
때문이다.

## 4. 데이터 스키마

### 4.1 공통 봉투 (11개 전부)

상위 설계의 kafka/clickhouse `data.json` 패턴에 `headline` 필드를 추가한 것이 표준형이다.

```json
{
  "benchmark": "redis",
  "generated": "2026-07-XX",
  "coverage": 54,
  "headline": { "field": "set_rps", "direction": "max", "label": "SET Throughput", "unit": "ops/s" },
  "notes": { "method": "...", "caveat": "..." },
  "instances": { "c8g.xlarge": { "...측정치만...": 0 } }
}
```

- **`headline`**: Overview 탭이 벤치마크별 지식 0줄로 히트맵·위너카드를 만들기 위한 열쇠. `field`는
  dot-path를 허용한다(예: ES는 rally가 51개뿐이라 `"coldstart.avg_ms"`, `direction:"min"`을
  헤드라인으로 선택).
- arch/gen/family/price/mem_mb는 **`instances.json` 전용**이며 벤치마크 JSON에는 넣지 않는다.
  kafka/clickhouse의 기존 `data.json`이 이 필드들을 이미 갖고 있어도 그대로 두고, 클라이언트 조인
  값이 우선하도록 처리한다(재생성 비용을 피하는 저렴한 선택).
- 파생 효율 필드(`value`, `*_per_dollar` 등)는 JSON에 저장하지 않고 클라이언트에서 canonical price로
  계산한다.

### 4.2 `instances.json`

```json
{
  "c8g.xlarge": {
    "arch": "graviton", "gen": 8, "family": "C",
    "mem_mb": 8192, "price": 0.180, "flex": false, "graviton_gen": 4
  }
}
```

- `gen`은 항상 5–8로 정규화한다 — ES가 Graviton 세대를 2/3/4로 표기하던 문제를 여기서 근절한다.
- `graviton_gen`(1–4)은 라벨 표시용이다(예: "Graviton4 (8세대)").
- `flex`는 springboot의 Flex vs Standard 분석과 `-flex` 인스턴스 배지에 쓴다.
- 소스: `config/instances-4vcpu.txt`(name/arch/mem) + `scripts/generate-kafka-report.py`의 PRICE
  dict(54개 완비, API 소스) + 동일 스크립트의 `gen_family()` 로직.

### 4.3 벤치마크별 instance 필드 (측정치만, 파생값 제외)

| 벤치마크 | 필드 |
|---|---|
| sysbench | `cpu_mt, cpu_st, mem_seq_write, mem_seq_read, mem_rnd_write, mem_rnd_read, mem_large_block` |
| geekbench | `single, multi` (coverage 51) |
| passmark | `cpu_mark, single, int, float, encryption, compression` — `int/float/encryption/compression`은 `notes.estimated`에 "cpu_mark 비율 추정치"임을 명시. 정본은 HTML 51행 테이블 |
| stress-ng | `matrix, float, int, memcpy, cache, ctx_switch, branch, total` (레거시 `switch` 필드는 JS 예약어 인상을 피하려 `ctx_switch`로 개명) |
| iperf3 | `single_gbps, parallel_gbps, reverse_gbps, udp_mbps, jitter_ms, loss_pct` |
| nginx | `req_sec, latency_ms` |
| redis | `set_rps, get_rps, set_lat_ms, get_lat_ms, set_p99_ms, get_p99_ms, set_rps_all[5], get_rps_all[5]` — 5-run 원시 배열은 `results/redis/benchmark_data.json`에 이미 존재하므로 그대로 옮긴다. 모달의 min/max/stdev/CV는 배열에서 클라이언트가 계산(별도 저장 불필요) |
| elasticsearch | `rally: {throughput, lat_p50, lat_p99, gc_young, indexing_s, merge_s} \| null`, `coldstart: {avg_ms, sequential_index_ms, bulk_index_ms, search_match_all_ms, search_term_ms}` — **nullable 규약: 미측정 서브그룹은 필드별이 아니라 객체 전체를 null로.** c8gn/r8gd는 `rally: null`. 차트 헬퍼는 dot-path 해석이 실패하면 해당 인스턴스를 자동 제외 |
| springboot | `wrk: {rps50, rps100, rps200, lat50_ms, lat99_ms}`, `cold_s` |
| kafka | **기존 스키마 그대로**(flat 필드 + `max.{uncompressed,lz4,zstd}` + `ramp.{..., curve[8]}`) + 공통 봉투 3필드(`headline`/`coverage`/`generated`)만 추가. 필드 구조 자체는 변경하지 않는다 |
| clickhouse | **기존 스키마 그대로**(flat 필드 + `per_query_ms{q00..q42}`) + 공통 봉투 3필드만 추가 |

### 4.4 사이드카 데이터 (별도 파일을 만들지 않음 — 같은 JSON의 top-level 키)

- **springboot.json**의 top-level `timeseries`:
  ```json
  {
    "interval_s": 10, "points": 60,
    "series": {
      "c7i-flex.xlarge": { "throughput": [60개], "lat_avg_ms": [60개], "lat_p99_ms": [60개] }
      // 나머지 5개 인스턴스 동일 구조
    }
  }
  ```
  키는 실제 인스턴스명을 사용한다(레거시의 `c7iFlex`류 camelCase는 폐기 — `instances.json`과 조인
  가능하게). 6개 인스턴스 × 3지표 × 60포인트는 수 KB에 불과해 별도 파일로 분리하지 않는다.
- **clickhouse.json**의 기존 top-level `queries: {clickbench:[{id,sql}], insert, join}`은 그대로
  유지한다.
- **kafka.json**의 기존 `note_*` / `max_dataset` / `ramp_dataset` 필드는 위치를 유지한다(하위 호환).
  신규 `notes{}` 규약은 이후 새로 만드는 파일부터 적용한다.

### 4.5 Overview 탭 계약

`overview.js`는 11개 JSON을 병렬 fetch하고, 각 파일의 `headline` dot-path 값을 추출해 direction을
정규화한다(`direction:"min"`이면 `best/value*100`으로 역변환, `"max"`면 `value/best*100`). 이 값으로
히트맵(순수 HTML `<table>`, 54행 × ~13열)과 종합 점수(가용 정규화 점수의 평균 + 커버리지 개수 표기),
위너 카드(벤치마크별 최고 성능 + 최고 가성비)를 만든다.

**수용 기준: `overview.js`에 벤치마크별로 분기하는 코드가 0줄이어야 한다.** null(rally 미커버 등)은
회색 "—"로 표시하고 종합 점수의 분모에서 제외한다.

## 5. Phasing (상위 설계 갱신분)

springboot가 최대 규모 탭(bespoke 위젯 4종 + timeseries 사이드카 파서)임이 확정되어, 기존 상위 설계의
Phase 3 배치에서 분리해 단독 페이즈로 둔다.

1. 데이터 파이프라인 기반: `extract_legacy.py` + `instances.json` 빌더 + sysbench/iperf3 파서 +
   `validate.py` green
2. SPA 셸 + `shared.js` 전체 컴포넌트 + **sysbench 탭 = 레퍼런스 구현**(이후 탭이 그대로 따라 할 원형)
3. nginx → redis → iperf3 → elasticsearch (bespoke 오름차순: nginx로 shared 커버리지 검증, redis로
   모달+GET 실측 교체 검증, ES로 nullable 규약 검증)
4. kafka/clickhouse(봉투 필드 추가만 + UI 이식) + geekbench/passmark/stress-ng(legacy 추출)
5. **springboot 단독**: timeseries 파서 + wrk/coldstart 파서 + bespoke 위젯 4종. shared가 안정된
   뒤라 순수 콘텐츠 작업
6. Overview (headline 계약 소비)
7. 배포·컷오버(상위 설계 §7과 동일)

## 6. 검증 (상위 설계에 추가되는 항목)

- 탭별 Live Preview에서 탭 전환 시 이전 Chart.js 인스턴스가 실제로 destroy되는지 확인(메모리 누수
  방지 — 브라우저 개발자도구 힙 스냅샷 또는 Chart.js 인스턴스 카운트로 검증)
- Overview는 기존 리포트의 위너(c8g/r8g 우세 등)와 sanity 대조

## 7. 참조 파일

- [2026-07-08-unified-dashboard-design.md](2026-07-08-unified-dashboard-design.md) — 상위 설계
- `results/kafka/data.json` — 봉투/중첩 스키마 원형(`max`/`ramp` 구조는 그대로 유지)
- `results/redis/benchmark_data.json` — 5-run 배열 실데이터(모달 스키마 + GET 실측 교체의 근거)
- `reports/springboot-report.html` — 최대 탭 이식 원본(timeseries 인라인 데이터, L1489–1560 부근)
- `reports/sysbench-report.html` — 레퍼런스 탭 이식 원본
- `scripts/generate-kafka-report.py` — PRICE dict, `gen_family()`
