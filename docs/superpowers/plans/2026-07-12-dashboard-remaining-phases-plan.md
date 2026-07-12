# 통합 대시보드 잔여 페이즈 구현 계획 (Phase 5~7)

- **설계 문서**: `docs/superpowers/specs/2026-07-08-unified-dashboard-design.md`,
  `docs/superpowers/specs/2026-07-09-dashboard-tab-content-design.md`
- **작성일**: 2026-07-12
- **base**: main
- **선행 완료**: Phase 0~4 — `site/`(SPA 셸+shared.js), `scripts/dashboard/`(파이프라인),
  10개 탭(sysbench/nginx/redis/iperf3/elasticsearch/kafka/clickhouse/geekbench/passmark/stress-ng)
  전부 커밋됨. 남은 것은 springboot 탭(Phase 5, 최대 규모), Overview 탭(Phase 6), 배포(Phase 7).

## 검증 방법 (이 프로젝트의 "테스트")

코드 단위테스트 프레임워크 대신 다음 게이트로 각 태스크를 검증한다(기존 9개 탭과 동일 패턴):
- 파서: `python3 scripts/dashboard/build_data.py <name>` 실행 후 `python3 scripts/dashboard/validate.py <name>` — legacy 51개 인스턴스 대비 상대오차 ≤0.5%, exit 0
- 커버리지: `site/data/<name>.json`의 `coverage` 필드가 기대치(54 또는 51) 이상
- 브라우저: Playwright(headless chromium, `/tmp/pwtest/check_*.js` 패턴 재사용) — 탭 로드 시 콘솔 에러 0건, summary-cards/canvas/table row 개수 확인, 탭 재방문 시 canvas 개수 불변(Chart.js destroy 검증)
- JS 문법: 브라우저에서 pageerror 없이 로드되면 통과(별도 린터 없음 — 기존 탭들과 동일)

## Task 1: springboot 파서 — wrk/coldstart

**Files:**
- Create: `scripts/dashboard/parsers/springboot.py`
- Test: `legacy/springboot.json` (Phase 1에서 이미 추출됨, 재사용)

`results/springboot/<instance>/wrk{1..5}.log`에서 3개 wrk 블록(`--- Main Page - 2 threads, 50
connections, 60s ---` / `100 connections` / `--- High Load - 2 threads, 200 connections, 30s
---`)의 `Requests/sec:`와 P50/P99 latency(200 conn 블록의 `Latency Distribution`)를 파싱해 5회
평균. `results/springboot/<instance>/coldstart{1..5}.log`에서 `Started PetClinicApplication in
X.XXX seconds` 정규식으로 콜드스타트를 파싱해 5회 평균(초 단위, `cold_s`로 저장). 54개 인스턴스
대상.

스키마(설계 §4.3): `wrk: {rps50, rps100, rps200, lat50_ms, lat99_ms}`, `cold_s`. `legacy c8g.xlarge:
rps50=57258, rps100=66933, rps200=74291, lat50=2.482, lat99=5.392, cold=4.29`를 정답지로 검증.

- [ ] `parse_wrk_log(path)`: 3개 conn 블록별 `Requests/sec:` 정규식 파싱 → `(rps50, rps100, rps200)`
- [ ] 200 connections 블록에서 `50%`/`99%` Latency Distribution 라인 파싱 → `(lat50_ms, lat99_ms)` (단위 통일: `ms`/`us`/`s` 표기 혼재 가능성 확인 후 ms로 정규화)
- [ ] `parse_coldstart_log(path)`: `Started PetClinicApplication in ([\d.]+) seconds` 정규식
- [ ] `build()`: 54개 인스턴스 순회, `wrk*.log` 5회 평균 + `coldstart*.log` 5회 평균, 봉투 `{benchmark:"springboot", coverage, headline:{field:"wrk.rps200", direction:"max", label:"Requests/sec (200 conn)", unit:"req/s"}, notes, instances}`
- [ ] `build_data.py`에 `"springboot": 54` EXPECTED_COVERAGE 추가 + 기본 targets 리스트에 추가
- [ ] `validate.py`에 `"springboot"` FIELD_MAPS 추가(`wrk.rps50→rps50`, `wrk.rps100→rps100`, `wrk.rps200→rps200`, `wrk.lat50_ms→lat50`, `wrk.lat99_ms→lat99`, `cold_s→cold`) — dot-path 지원은 이미 구현됨(elasticsearch 패턴 재사용)
- [ ] `python3 build_data.py springboot && python3 validate.py springboot` green, coverage=54

## Task 2: springboot timeseries 사이드카 파서

**Files:**
- Modify: `scripts/dashboard/parsers/springboot.py`

`results/springboot-flex/timeseries-all.csv`(컬럼: `instance,run,elapsed_sec,requests_per_sec,
avg_latency_ms,p99_latency_ms`)에서 Run 2(레거시가 사용한 run — `reports/springboot-report.html`
L1486 주석 확인)의 6개 인스턴스(`c7i-flex.xlarge, c8i-flex.xlarge, m7i-flex.xlarge,
r8i-flex.xlarge, c8i.xlarge, c8g.xlarge` — 레거시 키 `c7iFlex/c8iFlex/m7iFlex/r8iFlex/c8iStd/c8g`
매핑) × 60 포인트(elapsed_sec 10~600, 10초 간격)를 읽어 `springboot.json` top-level
`timeseries: {interval_s:10, points:60, series:{"<실제 인스턴스명>": {throughput:[60], lat_avg_ms:[60], lat_p99_ms:[60]}}}`로 저장(설계 §4.4 — 레거시 camelCase 키 폐기, 실제 인스턴스명 사용).

- [ ] CSV를 pandas 없이 `csv.DictReader`로 읽어 `run==2`만 필터, `elapsed_sec` 오름차순 정렬
- [ ] 6개 인스턴스만 추출해 `series[instance] = {throughput, lat_avg_ms, lat_p99_ms}` (각 60개 값)
- [ ] `build()` 반환값에 `timeseries` 키 추가(instances 딸림이 아니라 envelope top-level)
- [ ] 값 검증: `legacy/springboot.json`의 `timeseries.throughput.c7iFlex[0]` == 신규 `series["c7i-flex.xlarge"].throughput[0]` (수동 diff, validate.py 대상 아님 — 사이드카는 FIELD_MAPS에 없음)

## Task 3: springboot 탭 골격 + 표준 컴포넌트

**Files:**
- Create: `site/tabs/springboot.html`
- Create: `site/js/tabs/springboot.js`

표준 골격(hero→summary-cards→toc→methodology→...→table→conclusion)을 따르되 bespoke 슬롯
4개(Task 4~6에서 구현)를 위한 빈 컨테이너를 배치. `tabs/sysbench.html`을 원형으로 복사해 시작.

- [ ] hero: "Spring Boot PetClinic 벤치마크", coverage 배지
- [ ] summary-cards 슬롯: 최고 처리량(rps200)/최저 콜드스타트/최고 가성비
- [ ] methodology 섹션: wrk 3단계 설정(50/100/200 conn) 표+콜드스타트 측정 방식 설명(정적 HTML)
- [ ] `[SLOT A: 시나리오 탭]` 빈 컨테이너 (Task 4)
- [ ] 표준 `metricTabChart`(rps50/100/200 3-way) 컨테이너
- [ ] coldstart `topNBar` 컨테이너
- [ ] `[SLOT A: family-filter 차트]` 빈 컨테이너 (Task 4)
- [ ] `priceSection` 컨테이너(mainMetric=rps200, gridMetrics=[rps200, cold_s(direction min)])
- [ ] `[SLOT A: time-series 라인차트]` 빈 컨테이너 (Task 5)
- [ ] `[SLOT A: Flex vs Standard 서사]` 빈 컨테이너 (Task 6)
- [ ] `resultTable` 컨테이너(columns: name/arch/gen/rps50/rps100/rps200/lat50/lat99/cold_s/price)
- [ ] conclusion 섹션(정적 서사)
- [ ] `render(root, {rows})`에서 summary-cards/metricTabChart/coldstart topNBar/priceSection/resultTable/buildToc까지 표준 컴포넌트로 연결(Task 4~6 이전에도 이 부분만으로 탭이 렌더되어야 함 — 중간 검증 지점)

## Task 4: springboot bespoke — 시나리오 탭 + family-filter 차트

**Files:**
- Modify: `site/tabs/springboot.html`
- Modify: `site/js/tabs/springboot.js`

레거시의 부하 시나리오 탭(50/100/200 conn 각각 Top20)과 family-filter 붙은 비교 차트(전체/C/M/R
필터, 아키텍처 색상 유지)를 bespoke로 구현. `reports/springboot-report.html`의
`wrkTop20Chart200/100/50`, `scenarioCompareChart`, `switchScenarioFamily` 로직을 참고해 포팅
(단, `topNBar`의 metrics 배열로 3-way 스위처는 이미 Task 3에서 표준화했으므로 여기서는 **family
필터 붙은 그룹 비교 차트**만 신규 구현하면 됨 — 중복 방지).

- [ ] family-filter 탭 버튼(전체/C/M/R) + 그룹 바 차트(50/100/200 3계열, 선택 family로 rows 필터링 후 arch별 평균)
- [ ] 필터 전환 시 Chart.js `update()` 또는 destroy+재생성(다른 탭의 metricTabChart 패턴 참고)
- [ ] `render()`의 handles 배열에 destroy 등록

## Task 5: springboot bespoke — 600초 time-series 라인차트

**Files:**
- Modify: `site/tabs/springboot.html`
- Modify: `site/js/tabs/springboot.js`

`data.timeseries`(Task 2가 만든 envelope 필드)를 사용해 6개 인스턴스 × 3지표(throughput/
lat_avg_ms/lat_p99_ms) 라인차트 + 메트릭 스위처(3-way 탭 버튼, `reports/springboot-report.html`의
`switchTimeseriesMetric` 로직 포팅) + 통계 타일(5-run 평균/최소/최대/CV, 원본 CSV의 run 컬럼이
1개만 쓰였으므로 이 통계는 레거시처럼 "run 2 단일 실행"으로 명시).

`loadData()`가 `envelope`도 반환하므로(Phase 4 clickhouse 탭에서 이미 사용한 패턴)
`render(root, {rows, envelope})`에서 `envelope.timeseries`로 접근.

- [ ] 라인차트: x축=elapsed_sec(10~600), y축=선택 메트릭, 6개 데이터셋(Graviton 점선/Intel 실선 구분 유지)
- [ ] 3-way 메트릭 스위처 탭(처리량/평균지연/P99지연) — 클릭 시 데이터셋 교체 + y축 타이틀 갱신
- [ ] "데이터 소스: results/springboot-flex/timeseries-all.csv (Run 2, 60 points)" 안내 문구(정적)
- [ ] destroy 시 라인차트 정리

## Task 6: springboot bespoke — Flex vs Standard 서사 + 결론

**Files:**
- Modify: `site/tabs/springboot.html`
- Modify: `site/js/tabs/springboot.js`

Flex 인스턴스(`flex:true`)와 Standard 대응 인스턴스(같은 세대/패밀리)를 비교하는 서사 섹션.
`reports/springboot-report.html`의 "5.2 Standard vs Flex" 섹션(c8i vs c8i-flex 등)을 참고해 rows
데이터로 computed 통계 타일(rps200 차이 %, 콜드스타트 차이) 생성 — 하드코딩 수치 금지(54개
백필로 값이 바뀔 수 있는 문장은 반드시 computed, 콘텐츠 명세 §3 원칙).

- [ ] `rows`에서 `flex:true`인 인스턴스와 이름에서 `-flex` 뗀 짝(`c7i-flex.xlarge` ↔ `c7i.xlarge`)을 매칭
- [ ] 짝별 rps200/cold_s 차이(%) 계산해 stat-tile로 렌더(하드코딩 없이 computed)
- [ ] conclusion 섹션의 요약 문장도 computed 값 참조(예: "Flex가 평균 N% 빠름" — N은 위 계산값)

## Task 7: 회귀 확인 (Playwright)

**Files:**
- Test: 없음(코드 변경 없음, 검증 전용 — Playwright 스크립트는 `/tmp/pwtest/`에 임시 작성, 커밋 대상 아님)

- [ ] `python3 scripts/dashboard/build_data.py && python3 scripts/dashboard/validate.py` 전체 실행 — 11개 벤치마크 전부 OK
- [ ] 로컬 서버(`python3 -m http.server`)로 `site/` 서빙, springboot 탭 로드 — 콘솔 에러 0건, canvas 개수 확인, 시나리오탭/family필터/timeseries스위처 클릭 동작 확인
- [ ] springboot 탭 이탈→재방문 시 canvas 개수 불변(destroy 검증)
- [ ] 기존 10개 탭 중 3개 이상 샘플 재확인(회귀 없음) — 특히 elasticsearch(envelope 사용 패턴 공유)

## Task 8: Overview 탭 데이터 계약 + 골격

**Files:**
- Create: `site/tabs/overview.html`
- Create: `site/js/tabs/overview.js`

설계 §4.5의 headline 계약을 소비. `js/app.js`가 이미 `overview` 탭을 라우팅 대상으로 등록해뒀으나
`tabs/overview.html`/`js/tabs/overview.js`가 없어 404였던 상태(Phase 2~4 검증 로그에 기록된 예상된
에러)를 해소.

- [ ] 11개 벤치마크의 `data/<name>.json`을 병렬 fetch(`Promise.all`)
- [ ] 각 파일의 `headline`(`{field, direction, label, unit}`)으로 dot-path 값 추출, `direction:"min"`이면 `best/value*100`, `"max"`면 `value/best*100`으로 정규화 — **overview.js에 벤치마크별 분기 코드 0줄**(설계 수용 기준)
- [ ] hero: 다크 그라데이션(설계 §3.2 "Overview 헤더에만 그라데이션 유지")

## Task 9: Overview 히트맵 + 종합 점수

**Files:**
- Modify: `site/js/tabs/overview.js`

- [ ] 순수 HTML `<table>` 히트맵: 54행 × 11열(벤치마크), 셀 배경색 = 정규화 점수 기반 green→red 그라데이션(인라인 style, 별도 차트 라이브러리 불필요)
- [ ] 커버리지 미달 벤치마크(geekbench/passmark/stress-ng는 51개, ES는 rally 51개)의 결측 인스턴스는 셀에 "—" + `heatmap-na` 클래스(이미 `dashboard.css`에 정의됨)
- [ ] 종합 점수 = 인스턴스별 가용 정규화 점수의 평균 + 커버리지 개수 표기(예: "8/11 벤치마크 반영")
- [ ] 히트맵에 `resultTable`과 동일한 검색/정렬 UX(공유 컴포넌트 재사용 시도 — 안 맞으면 최소 검색 input만이라도)

## Task 10: Overview 위너 카드 + 종합 랭킹 차트

**Files:**
- Modify: `site/js/tabs/overview.js`

- [ ] 벤치마크별 위너 카드(최고 성능 인스턴스 + 최고 가성비 인스턴스) — `summaryCards` 컴포넌트 재사용, 11개 카드 자동 생성(하드코딩 금지)
- [ ] 종합 점수 랭킹 바 차트(Top 20, `topNBar` 재사용 가능 여부 확인 — rows에 `__compositeScore` 필드를 계산해 주입하면 재사용 가능)
- [ ] 종합점수-가격 버블 차트(`priceSection`의 버블 탭 로직 참고, mainMetric을 `__compositeScore`로)
- [ ] sanity 대조: c8g/r8g/m8g(Graviton4)가 상위권에 있는지 육안 확인 — 기존 9개 탭에서 일관되게 관찰된 패턴과 부합해야 함

## Task 11: Overview 검증 (Playwright) + 전체 SPA 통합 확인

**Files:**
- Test: 없음(검증 전용)

- [ ] `python3 scripts/dashboard/build_data.py`로 모든 데이터 최신화(springboot 포함 11개) 후 Overview 로드
- [ ] 콘솔 에러 0건, 히트맵 54행 렌더, 위너 카드 11개, sanity 대조 통과
- [ ] `js/app.js`의 기본 라우트(`location.hash` 없을 때 `overview`)가 정상 로드되는지 확인(이전 Phase들에서 404였던 부분의 해소 확인)
- [ ] 전체 12개 탭 순회 스모크 테스트(각 탭 로드 시 콘솔 에러 0건) — 회귀 종합 확인

## Task 12: 배포 준비 — reports/ 삭제 + 생성 스크립트 출력 경로 전환

**Files** (모두 `git rm`으로 제거 대상 — parse_plan.py는 Delete 액션이 없어 Modify로 표기):
- Modify: `scripts/generate-kafka-report.py`
- Modify: `scripts/generate-clickhouse-report.py`
- Modify: `reports/index.html`
- Modify: `reports/sysbench-report.html`
- Modify: `reports/geekbench-report.html`
- Modify: `reports/passmark-report.html`
- Modify: `reports/stress-ng-report.html`
- Modify: `reports/iperf3-report.html`
- Modify: `reports/redis-report.html`
- Modify: `reports/nginx-report.html`
- Modify: `reports/springboot-report.html`
- Modify: `reports/elasticsearch-report.html`
- Modify: `reports/clickhouse-report.html`
- Modify: `reports/kafka-report.html`
- Modify: `reports/report-common.css`
- Modify: `reports/report-nav.js`

설계 §7d: kafka/clickhouse 생성 스크립트가 `results/{kafka,clickhouse}/report-charts.html`에
HTML을 주입하던 로직을 제거하고 `site/data/{kafka,clickhouse}.json`에 직접 쓰도록 변경(이미
`scripts/dashboard/parsers/{kafka,clickhouse}.py`가 같은 소스 파일을 읽어 봉투를 추가하는 방식으로
존재하므로, 생성 스크립트 쪽은 **출력 파일 경로만** `site/data/`로 바꾸고 HTML 주입 스텝을 제거하면
됨 — 로직 중복 정리).

- [ ] `generate-kafka-report.py`: HTML 템플릿 주입 함수 제거, `data.json` 저장 경로를 `site/data/kafka.json`으로 직접 쓰거나(그러면 `parsers/kafka.py`의 read-and-wrap이 불필요해짐 — 택1: 스크립트가 직접 봉투 필드까지 쓰게 통합), 기존처럼 `results/kafka/data.json` 유지 후 `parsers/kafka.py`가 소비하는 현 구조를 유지(변경 리스크 낮음 — **권장**: 현 구조 유지, 이 태스크는 스킵 가능성 검토)
- [ ] 스킵 판단: 두 스크립트가 이미 `results/*/data.json`만 쓰고 있고(HTML 주입은 별도 함수), `reports/*-report.html` 삭제와 무관하게 동작 — 실제로 손댈 부분이 없으면 이 태스크는 **"변경 불필요 확인"으로 종료**하고 로그에 남긴다
- [ ] `reports/` 디렉터리 전체 삭제(11개 HTML + report-common.css + report-nav.js) — git으로 추적되므로 `git rm`
- [ ] 삭제 후 `site/`가 `reports/`의 어떤 파일도 참조하지 않는지 grep 확인(`grep -r "reports/" site/`)

## Task 13: docs 브랜치 1차 배포 (병존)

**Files:**
- 없음(git worktree 작업, 커밋은 `docs` 브랜치 대상)

설계 §7 배포 절차. **주의: 이 태스크는 `git push`를 포함하므로 하니스의 "커밋은 호스트만"
원칙상 호스트가 직접 실행하고, 구현자(codex)에게는 위임하지 않는다** — worktree/push는 파일
편집이 아니라 저장소 상태 변경이라 위임 범위 밖.

- [ ] `git worktree add /tmp/docs-deploy docs`
- [ ] `rsync -a site/ /tmp/docs-deploy/` (`--delete` 없이, 기존 `reports/` 병존)
- [ ] `/tmp/docs-deploy`에서 `git add -A && git commit -m "Deploy: 통합 대시보드 SPA 1차 배포"`
- [ ] **push는 사용자 확인 후에만** — commit까지 만들고 push 여부를 사용자에게 물어본다(원격 저장소 변경은 되돌리기 어려운 행동)

## Task 14: docs 브랜치 검증 + 2차 배포 (--delete)

**Files:**
- 없음

- [ ] 배포된 사이트(`https://benchmark.aws.atomai.click/`) 접속해 12개 탭 전부 확인(push 완료 후에만 — 사용자 승인 필요)
- [ ] 문제 없으면 `rsync -a --delete site/ /tmp/docs-deploy/`로 2차 배포(구 `reports/` 및 stale 서브트리 제거)
- [ ] 2차 커밋+push (사용자 확인 필요)
- [ ] `git worktree remove /tmp/docs-deploy`

## Task 15: main 정리 + CLAUDE.md 갱신

**Files:**
- Modify: `CLAUDE.md`

- [ ] CLAUDE.md의 "HTML 보고서 형식" 섹션 → 탭 작성 가이드로 교체(표준 골격 10단계, shared.js 컴포넌트 목록, 명령형 렌더 계약 요약)
- [ ] CLAUDE.md의 "배포" 섹션 → site/ 기반 rsync 절차로 교체, main/docs 레이아웃 동일 명시(경로 함정 구조적 해소 기록)
- [ ] 두 설계 스펙 문서(`2026-07-08`, `2026-07-09`) 링크를 CLAUDE.md에 참조 추가
