# 통합 벤치마크 대시보드 SPA 설계

- **작성일**: 2026-07-08
- **대상**: EKS EC2 Node Benchmark 프로젝트 (54개 xlarge 인스턴스)
- **목적**: 11개의 개별 정적 HTML 리포트 + 하드코딩 랜딩 페이지를, 원시 로그를 재파싱한 JSON 데이터 기반의 단일 SPA 대시보드로 통합

## 1. 배경 및 목표

현재 벤치마크 결과는 `reports/*-report.html` 11개(각 50~166KB, 데이터가 HTML 안에 JS 배열로
하드코딩) + 정적 하드코딩 랜딩 페이지(`reports/index.html`)로 구성되어 있다. 문제점:

- 리포트마다 HTML을 통째로 생성/수동 유지해야 해서 낭비. 6개 리포트(sysbench/Redis/Nginx/ES/
  SpringBoot/iperf3)는 51개 인스턴스 기준으로 낡았다 — 원시 로그는 8종 모두 54개분이 이미 존재하는데
  리포트 재생성이 리스크가 있어 보류된 상태(CLAUDE.md "리포트 갱신 범위" 참고)
- 랜딩 페이지 요약 카드가 전부 하드코딩된 텍스트라 데이터 갱신 시 수동 동기화 필요
- 룩앤필 불일치(랜딩=다크, 리포트=라이트)
- 가격 데이터가 리포트마다 다른 pricing 스냅샷을 써서 같은 인스턴스인데 리포트마다 가격이 다름
  (예: r8g.xlarge가 sysbench/redis에서 0.284, geekbench에서 0.250, stress-ng에서 0.229)
- main/docs 브랜치 디렉터리 레이아웃이 달라 경로 함정 존재(2026-07-07 실제 오판 사고 — CLAUDE.md
  "배포" 섹션 참고)

### 측정하고 싶은 것 (이 프로젝트가 이미 측정 중인 것을 어떻게 "보여줄지")
데이터 자체는 이미 8종 벤치마크(sysbench CPU/Memory, Redis, Nginx, Elasticsearch, SpringBoot,
iperf3, ClickHouse, Kafka) + geekbench/passmark/stress-ng로 완비되어 있음. 이 설계의 범위는
**표시 계층 재구축**이며 신규 벤치마크 워크로드 추가는 아니다.

## 2. 핵심 설계 결정 (확정)

| 항목 | 결정 | 이유 |
|------|------|------|
| 산출물 형태 | 단일 SPA(`site/index.html` + 데이터 JSON) | 11개 리포트를 각각 생성/유지하는 낭비 제거 |
| 기존 11개 리포트 | 완전 대체·삭제(main+docs) | 데이터 이중화·이원화 방지, 유지보수 지점 단일화 |
| 데이터 소스 | 원시 로그 재파싱 → 54개 인스턴스 완성 | 기존 51개 인라인 배열을 검증 정답지로 사용해 파싱 정확성 보증 |
| 탭 구성 | 공통 테마(nav/카드/뱃지/테이블/차트 팩토리) + 벤치마크별 고유 차트·서사 | "블로그 포스트" 모델 — 벤치마크마다 봐야 할 지표가 본질적으로 다름 |
| 테마 | 라이트 통일(`report-common.css` 기반) | 11개 리포트가 이미 라이트 톤의 성숙한 스타일을 갖고 있어 재작업 최소화. 다크 랜딩은 폐기 |
| 가격 데이터 | canonical PRICE dict 1곳(kafka 스크립트, 54개 API 소스 완비) | 가격 드리프트 근본 제거 |
| 배포 레이아웃 | main `site/` = docs 루트, 완전 동일 구조 | 경로 함정 구조적 제거 |

## 3. 아키텍처

### 3.1 최종 레이아웃

**main 브랜치** — 신규 `site/` 폴더, 완전 자기완결(모든 경로 sibling-relative):

```
site/
├── index.html              # SPA 셸: nav 탭, Chart.js CDN(@4 고정), 부트 스크립트
├── CNAME                   # benchmark.aws.atomai.click (docs에만 있던 것을 site/로 이동)
├── favicon.png
├── css/dashboard.css       # report-common.css 기반 단일 스타일시트
├── js/
│   ├── app.js              # hash 라우터 + 탭 lazy 로더
│   ├── shared.js           # 색상/badge/테이블/차트 팩토리/데이터 로더
│   └── tabs/               # overview.js + 벤치마크별 11개 모듈
├── tabs/                   # 벤치마크별 HTML 파셜 12개 (서사+캔버스)
└── data/
    ├── instances.json      # 공유 메타데이터 {name: {arch, gen, family, mem_mb, price}}
    └── <benchmark>.json    # 11개
scripts/dashboard/
├── build_data.py           # 원시 로그 → site/data/*.json
├── extract_legacy.py       # 일회성: reports/*.html 인라인 배열 → legacy/*.json (검증 정답지)
└── validate.py             # site/data vs legacy 필드별 diff (상대오차 ≤0.5%)
```

**docs 브랜치** — 루트 = `site/` 내용 그대로 복사. main/docs 레이아웃 동일.

배포:
```bash
git worktree add /tmp/docs-deploy docs
rsync -a site/ /tmp/docs-deploy/     # 전환기: --delete 없이
cd /tmp/docs-deploy && git add -A && git commit -m "..." && git push origin docs
```

### 3.2 데이터 흐름

```
results/<benchmark>/<instance>/*.log  (원시 로그, 54개 or 51개)
   │
   ├─ build_data.py (파서: 기존 generate-*.py 함수 재사용)
   │
   ▼
site/data/<benchmark>.json  {benchmark, generated, coverage, notes, instances:{...}}
   │
   ├─ 검증: validate.py ── reports/*.html 인라인 배열(51개, 정답지) 대비 diff ≤0.5%
   │
   ▼
브라우저: fetch('data/<b>.json') + fetch('data/instances.json') → 클라이언트 조인(arch/gen/family/price)
   │
   ▼
js/tabs/<b>.js render() → 차트/테이블 렌더
```

### 3.3 인스턴스 메타데이터 (`instances.json`)

`config/instances-4vcpu.txt`(54개, name/arch/mem) + `generate-kafka-report.py`의 PRICE dict(유일
54개 완비, `aws pricing get-products` 소스) + 동일 스크립트의 `gen_family()` 로직 재사용.
벤치마크 JSON은 **측정치만** 담고 arch/gen/family/price는 클라이언트에서 조인 — 11중 중복과 가격
드리프트를 동시에 해결.

### 3.4 벤치마크 JSON 스키마

kafka/clickhouse의 기존 data.json 패턴을 그대로 표준화:

```json
{
  "benchmark": "sysbench",
  "generated": "2026-07-08",
  "coverage": 54,
  "notes": { "...메서드론 캐비어트..." },
  "instances": { "c8g.xlarge": { "cpu_mt": 4946.98, "cpu_st": 1249.99, "...": "..." } }
}
```

필드는 기존 인라인 배열 스키마(arch/price 제외)와 동일. 효율 파생 필드(`cpu_efficiency` 등)는
JSON에 저장하지 않고 클라이언트에서 canonical price로 계산 — 가격 스냅샷이 바뀌어도 재파싱 불필요.

### 3.5 파서 정책 — 재사용 우선, 재작성 금지

| 벤치마크 | 방식 |
|---|---|
| sysbench CPU/Memory | `generate-sysbench-report.py`의 `parse_cpu_log`/`parse_memory_log`/효율 공식 포팅 |
| Redis | `parse_redis_for_report.py` + `generate-redis-report.py` 집계 포팅 |
| Nginx / SpringBoot / Elasticsearch / iperf3 | 로그 형식이 단순 — 신규 파서 작성, `validate.py`로 헤드라인 수치 매핑 확정 |
| Kafka / ClickHouse | **재파싱 안 함** — 기존 `generate-{kafka,clickhouse}-report.py` 실행 후 `results/*/data.json`을 `site/data/`로 복사(추후 스크립트 출력 경로만 변경) |
| geekbench / passmark / stress-ng | **원시 재파싱 안 함**(51개 그대로, 커버리지 이득 0) — `extract_legacy.py` 산출물을 표준 봉투로 재구성 |

**알려진 갭**: `results/elasticsearch/{c8gn,r8gd}.xlarge/`는 coldstart 로그만 있고 rally 로그가
없음 → ES rally 필드는 nullable(51개), coldstart 필드는 54개.

### 3.6 검증 게이트

각 벤치마크 탭 UI 작업 전 `validate.py` green이 선행 조건:
- 기존 51개 인스턴스, 전 필드, 상대오차 ≤0.5% (라운딩 허용치)
- 효율 필드는 해당 레거시 리포트의 자체 가격으로 재계산해 비교(레거시 리포트마다 가격이 다르므로)
- 불일치 발견 시 = 집계 공식 미재현 → 파서 수정 후 진행. UI를 먼저 만들지 않는다.

## 4. SPA 아키텍처

- **라우팅**: `location.hash`(`#overview`, `#sysbench` 등). 최초 방문 시
  `fetch('tabs/x.html')` + `import('./js/tabs/x.js')` → `render(container, {data, instances})`.
  이후 캐시(재방문 시 재요청 없음). 프레임워크·빌드 스텝 없음(순수 ES modules + fetch).
  ⚠️ `file://` 프로토콜에선 fetch 불가 — 로컬 검증은 반드시 http 서버(code-server Live Preview)로.
- **테마**: 라이트(`report-common.css` 이식). Overview 헤더에만 그라데이션 유지(기존 다크 랜딩의
  유일하게 살릴 요소). Chart.js는 `@4`로 고정(기존 리포트는 unpinned latest — SPA에서는 향후 v5
  릴리스가 전체 차트를 한 번에 깨뜨리는 리스크가 있어 고정).
- **`js/shared.js`** (기존 리포트에서 포팅, 신규 발명 없음):
  - `ARCH_COLORS` / `archOf()` / `badge()` — graviton 초록 / intel 파랑 / amd 빨강
  - `resultTable(el, rows, columns)` — 검색 필터 + arch/gen/family 필터 + 헤더 클릭 정렬
    (nginx/sysbench의 테이블 코드를 1회 포팅해 11개 리포트의 중복 구현 제거)
  - 차트 팩토리 5종: `top20Bar` / `genArchGrouped` / `familyCompare` / `priceBubble` / `valueTop15`
    (CLAUDE.md "필수 차트 유형"과 일치, 기존 리포트 차트의 대다수를 커버)
- **탭 모듈 구조**: `tabs/<b>.html`(방법론·환경·인사이트 서사 — 기존 리포트에서 이식) +
  `js/tabs/<b>.js`(`render()` export). 팩토리에 안 맞는 벤치마크 고유 차트(Kafka 램프 곡선,
  ClickHouse per-query 탭, Redis 메트릭 스위처)는 각 모듈 내부에 자체 구현 — "테마는 공유, 콘텐츠는
  고유"라는 블로그 포스트 계약.

## 5. Overview 탭

- 벤치마크당 헤드라인 메트릭 1개, 방향 정규화(낮을수록 좋은 지표는 `best/value*100`으로 역변환),
  best=100 기준 백분율.
- **히트맵**: 순수 HTML `<table>`(54행 × ~13열), 셀 배경색은 인라인 계산 — 별도 차트 플러그인
  불필요, 공유 테이블 컴포넌트로 정렬/필터 재사용 가능. 미커버 셀(신규 3개 인스턴스 ×
  geekbench/passmark/stress-ng/ES-rally)은 회색 "—" 표시.
- **종합 점수** = 가용 정규화 점수의 평균 + 커버리지 개수 표기(51개 기준 벤치마크만 있는 인스턴스가
  불공정하게 비교되지 않도록). 랭킹 바 차트 + 종합점수-가격 버블 차트.
- **위너 카드**: 렌더 타임에 데이터로부터 생성(벤치마크별 최고 성능 + 최고 가성비) — 기존
  하드코딩 카드를 전면 대체.

## 6. 리스크 및 대응

| 리스크 | 대응 |
|---|---|
| docs 경로 함정(2026-07-07 사고 재현) | `site/`가 자기완결 + main/docs 레이아웃 완전 동일 → 구조적으로 함정 제거. "main 커밋=저장, docs push=배포" 원칙은 CLAUDE.md에 계속 유지 |
| 레거시 집계 공식(sysbench efficiency 등) 유실 우려 | 공식은 기존 `generate-*.py`에 존재(유실 아님) — `validate.py`로 재현 증명 후에만 탭 출시 |
| 가격 드리프트 | canonical PRICE(kafka dict) 1곳 통일. 검증 시엔 각 레거시 리포트 고유 가격으로 재계산해 비교(그래야 diff가 파싱 오류인지 가격 차이인지 구분됨) |
| ES rally 51개(신규 3개 누락) | nullable 필드로 처리, coldstart는 54개, 탭 서사에 커버리지 명시 |
| Kafka 고지연 11개 인스턴스 이상치 | 데이터 그대로 이관 + 기존 caveat 서사도 이관 — 파서 단계에서 "보정"하지 않음 |
| Chart.js CDN 버전 부동 | `@4`로 pin |
| 구 리포트 딥링크 소실 | (선택) `reports/<name>-report.html` 리다이렉트 스텁 11개 |

## 7. Phasing

1. 데이터 파이프라인 기반: `extract_legacy.py` + `instances.json` 빌더 + sysbench/iperf3 파서 +
   `validate.py` green
2. SPA 셸 + sysbench 탭 완전 포팅, Live Preview 검증
3. redis/nginx/springboot/elasticsearch/iperf3 탭 — 파서+검증 → 탭 포팅 → 브라우저 확인, 배치별
4. kafka+clickhouse(data.json 재사용) + geekbench/passmark/stress-ng(legacy 추출) 탭
5. Overview 탭(11개 데이터 전부 필요) — 히트맵/랭킹/위너 카드
6. 배포·컷오버: docs 1차 배포(구 리포트 병존) → 검증 → 2차 배포(`--delete`) → main `reports/` 삭제
   + `generate-{kafka,clickhouse}-report.py` 출력 경로 변경 + CLAUDE.md 갱신

## 8. 참조 파일

- `scripts/generate-kafka-report.py` — 봉투 스키마, PRICE dict, `gen_family()`, data.json 패턴
- `scripts/generate-sysbench-report.py` — 로그 파서 + 효율 공식
- `reports/report-common.css` — 테마 기반
- `reports/sysbench-report.html` — 레거시 배열 추출 + 첫 탭 포팅 기준
- `config/instances-4vcpu.txt` — 인스턴스 목록 정본(54개)
