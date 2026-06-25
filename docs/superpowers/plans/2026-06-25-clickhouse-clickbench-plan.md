# ClickHouse ClickBench 벤치마크 구현 계획

- **설계 문서**: `docs/superpowers/specs/2026-06-25-clickhouse-clickbench-design.md`
- **작성일**: 2026-06-25
- **base**: main

## 검증 방법 (이 프로젝트의 "테스트")

코드 단위테스트 대신 다음 게이트로 각 태스크를 검증한다:
- YAML: `python3 -c "import yaml; list(yaml.safe_load_all(open(f)))"` 파싱 통과
- 템플릿 치환: 샘플 인스턴스(c8i.xlarge / c8g.xlarge)로 sed 치환 후
  `kubectl apply --dry-run=client -f -` 통과 (placeholder 잔류 0)
- 기존 규칙 준수: podAntiAffinity 존재, placeholder 규칙, 공식/ECR 이미지 사용
- SQL: 구문 sanity (줄/세미콜론 검증, 가능 시 clickhouse-client parse)
- Shell: `bash -n` 통과

검증 스크립트는 `tests/clickhouse/validate.sh`에 모아 둔다 (run-all 진입점).

## Task 0: 스냅샷에서 ClickHouse 메타데이터 확인 (Phase 0, 라이브)

**Files:**
- Modify: `docs/superpowers/specs/2026-06-25-clickhouse-clickbench-design.md`

`snap-024c86faa00cd0448`를 정적 VolumeSnapshot으로 바인딩 → 임시 PVC 복구 →
임시 Pod에서 `clickhouse-server` 기동 후 메타데이터 확인 → 설계 문서 §7 기록 → 임시 리소스 정리.

- [ ] 임시 VolumeSnapshot/PVC/Pod로 스냅샷 마운트
- [ ] `SELECT version()` — 적재 ClickHouse 버전 확인
- [ ] `SHOW DATABASES; SHOW TABLES` — DB/테이블 이름(`hits`) 확인
- [ ] `SELECT count() FROM hits` — 행 수 확인 (~100M 기대)
- [ ] 설계 문서 §7에 버전/테이블/행수 기록
- [ ] 임시 리소스 정리 (Pod/PVC 삭제, 스냅샷 보존)

## Task 1: 정적 VolumeSnapshot 매니페스트

**Files:**
- Create: `benchmarks/clickhouse/clickhouse-snapshot.yaml`
- Modify: `tests/clickhouse/validate.sh`

pre-provisioned VolumeSnapshotContent(snapshotHandle `snap-024c86faa00cd0448`,
driver `ebs.csi.aws.com`, class `gp3-clickhouse-snapclass`, DeletionPolicy Retain) +
VolumeSnapshot `clickhouse-hits`(benchmark ns) 정적 바인딩.

- [ ] VolumeSnapshotContent + VolumeSnapshot 작성 (정적 바인딩 spec.source.volumeSnapshotContentName)
- [ ] validate.sh에 YAML 파싱 + dry-run 검증 추가
- [ ] `kubectl apply --dry-run=client` 통과 확인

## Task 2: ClickBench 43쿼리 SQL

**Files:**
- Create: `benchmarks/clickhouse/queries/queries.sql`
- Modify: `tests/clickhouse/validate.sh`

ClickHouse 공식 ClickBench 43쿼리. Task 0에서 확인한 테이블(`hits`) 참조.

- [ ] 공식 43쿼리 작성
- [ ] validate.sh에 쿼리 수(43)·세미콜론 종결 검증 추가

## Task 3: INSERT 테스트 SQL

**Files:**
- Create: `benchmarks/clickhouse/queries/insert.sql`
- Modify: `tests/clickhouse/validate.sh`

`INSERT INTO hits SELECT * FROM hits LIMIT INSERT_ROWS` (기본 10000000, placeholder).

- [ ] INSERT 쿼리 작성 (placeholder `INSERT_ROWS`)
- [ ] validate.sh에 placeholder 존재 검증 추가

## Task 4: self-JOIN 테스트 SQL

**Files:**
- Create: `benchmarks/clickhouse/queries/join.sql`
- Modify: `tests/clickhouse/validate.sh`

hits self-JOIN 대표 집계 쿼리.

- [ ] self-JOIN 쿼리 작성
- [ ] validate.sh에 구문 sanity 검증 추가

## Task 5: ClickBench Job 템플릿

**Files:**
- Create: `benchmarks/clickhouse/clickhouse-clickbench.yaml`
- Modify: `tests/clickhouse/validate.sh`

Job: PVC(dataSource VolumeSnapshot `clickhouse-hits`, SC `gp3-clickhouse`, 100Gi, RWO) +
Pod(이미지 `clickhouse/clickhouse-server:<Task0버전>`, /var/lib/clickhouse 마운트, server 기동 →
43쿼리×3×5세트 + INSERT + JOIN 실행 → 결과 stdout). nodeSelector/arch, podAntiAffinity,
benchmark toleration, ttl. placeholder `INSTANCE_SAFE`/`INSTANCE_TYPE`/`ARCH`/`RUN_NUMBER`.

- [ ] Job + PVC 템플릿 작성
- [ ] podAntiAffinity·toleration·nodeSelector 포함
- [ ] validate.sh에 c8i(amd64)·c8g(arm64) 치환 dry-run + placeholder 잔류 0 검증 추가

## Task 6: 실행/수집 스크립트

**Files:**
- Create: `scripts/generate-clickhouse-benchmark.sh`
- Modify: `tests/clickhouse/validate.sh`

generate-springboot 패턴: 인스턴스별 배포(배치 기본 12개), 완료 즉시 로그 수집 →
`results/clickhouse/<instance>/setN.log`, Job/PVC 정리.

- [ ] 스크립트 작성 (INTEL/GRAVITON 51개, chained-pipe sed)
- [ ] validate.sh에 `bash -n` + 인스턴스 51개 검증 추가

## Task 7: 표준 리포트 스캐폴드

**Files:**
- Create: `results/clickhouse/report-charts.html`
- Modify: `tests/clickhouse/validate.sh`

표준 리포트 형식(CSS 변수, Summary Cards, 목차, 방법론, 환경, 차트 placeholder, 필터 테이블, 결론).
데이터는 수집 후 주입(스캐폴드만).

- [ ] HTML 스캐폴드 작성 (Chart.js CDN, 표준 색상)
- [ ] validate.sh에 닫힌 태그·CDN 포함 검증 추가

## Task 8: CLAUDE.md ClickHouse 섹션

**Files:**
- Modify: `CLAUDE.md`

벤치마크 상태 표 행, ClickHouse 상세 설명 섹션, placeholder 표 행 추가
(스냅샷 ID, SC 스펙 명시).

- [ ] 상태 표/상세 섹션/placeholder 표 갱신

## 비범위

분산 클러스터, 다른 데이터셋, 실시간 스트리밍 ingest. 실제 51개 벤치마크 **실행**은
사용자 트리거(라이브 클라우드 비용) — 본 계획은 산출물 작성까지.
