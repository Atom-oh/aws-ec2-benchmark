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

## Task 0: 사전 검증 + 스냅샷 ClickHouse 메타데이터 확인 (Phase 0, 라이브)

**Files:**
- Modify: `docs/superpowers/specs/2026-06-25-clickhouse-clickbench-design.md`

먼저 클러스터 자산 존재 확인(CRD/SC/snapclass/CSI), 이후 `snap-024c86faa00cd0448`를 정적
VolumeSnapshot으로 바인딩 → 임시 PVC 복구 → 임시 Pod에서 `clickhouse-server` 기동 후 메타데이터 확인 →
설계 문서 §7 기록 → 임시 리소스 정리. 기본값(default.hits / 24.8)으로 후속 태스크는 병행 작성 가능.

- [ ] 사전 검증: `kubectl get crd volumesnapshots.snapshot.storage.k8s.io`, `get storageclass gp3-clickhouse`, `get volumesnapshotclass gp3-clickhouse-snapclass`
- [ ] 임시 VolumeSnapshot/PVC/Pod로 스냅샷 마운트 (initContainer chown 101:101)
- [ ] `SELECT version()` — 적재 ClickHouse 버전 확인 → 이미지 핀
- [ ] `SELECT database,name FROM system.tables WHERE name='hits'` — DB/테이블 확정 (`default.hits` 기대)
- [ ] `SELECT count() FROM hits` — 행 수 확인 (~100M 기대)
- [ ] 설계 문서 §7에 버전/DB·테이블/행수 기록
- [ ] 임시 리소스 정리 (Pod/PVC 삭제, 스냅샷 보존)

## Task 1: StorageClass + VolumeSnapshotClass 매니페스트 (재현성)

**Files:**
- Create: `benchmarks/clickhouse/clickhouse-storageclass.yaml`
- Modify: `tests/clickhouse/validate.sh`

이미 클러스터에 존재하나 repo에 매니페스트가 없으므로 재현성/문서화 목적으로 추가(멱등 apply).
StorageClass `gp3-clickhouse`(provisioner `ebs.csi.aws.com`, type gp3, iops 16000, throughput 1000,
encrypted, WaitForFirstConsumer, allowVolumeExpansion) + VolumeSnapshotClass `gp3-clickhouse-snapclass`
(driver `ebs.csi.aws.com`, deletionPolicy Retain).

- [ ] StorageClass + VolumeSnapshotClass 작성 (기존 클러스터 값과 일치)
- [ ] validate.sh에 YAML 파싱 + dry-run 검증 추가

## Task 2: 정적 VolumeSnapshot 매니페스트

**Files:**
- Create: `benchmarks/clickhouse/clickhouse-snapshot.yaml`
- Modify: `tests/clickhouse/validate.sh`

정적 바인딩: VolumeSnapshotContent(`spec.source.snapshotHandle: snap-024c86faa00cd0448`,
`spec.driver: ebs.csi.aws.com`, `spec.volumeSnapshotClassName: gp3-clickhouse-snapclass`,
`spec.deletionPolicy: Retain`, `spec.volumeSnapshotRef: {name: clickhouse-hits, namespace: benchmark}`) +
VolumeSnapshot `clickhouse-hits`(benchmark ns, `spec.source.volumeSnapshotContentName: <content>`).

**⚠️ 라이브 충돌 방지**: 클러스터에 이미 작동 중인 `clickhouse-hits` binding이 authoritative. 이 매니페스트는
**bootstrap/dry-run 전용**으로 헤더 주석 명시하고, 기존 클러스터엔 apply하지 않는다(또는 기존 content 이름을
재사용해 no-op). validate는 dry-run만.

- [ ] VolumeSnapshotContent(volumeSnapshotRef) + VolumeSnapshot(source.volumeSnapshotContentName) 작성 — API 필드 정확히
- [ ] 헤더에 "bootstrap-only / 기존 클러스터 live-apply 금지" 주석 명시
- [ ] validate.sh에 YAML 파싱 + `--dry-run=client` 검증만 추가 (live apply 안 함)

## Task 3: ClickBench 43쿼리 SQL

**Files:**
- Create: `benchmarks/clickhouse/queries/queries.sql`
- Modify: `tests/clickhouse/validate.sh`

ClickHouse 공식 ClickBench 43쿼리. Task 0 확정 테이블(`default.hits`) 참조. 쿼리 구분자는
파서/실행 루프가 개별 실행할 수 있도록 한 줄당 1쿼리(세미콜론 종결) 형식.

- [ ] 공식 43쿼리 작성 (한 줄당 1쿼리)
- [ ] validate.sh에 쿼리 수(43)·세미콜론 종결 검증 추가

## Task 4: INSERT 테스트 SQL

**Files:**
- Create: `benchmarks/clickhouse/queries/insert.sql`
- Modify: `tests/clickhouse/validate.sh`

`INSERT INTO hits SELECT * FROM hits LIMIT INSERT_ROWS` (기본 10000000, placeholder).
실행 순서상 43쿼리 세트 **이후**에 실행(테이블 행수 변경).

- [ ] INSERT 쿼리 작성 (placeholder `INSERT_ROWS`)
- [ ] validate.sh에 placeholder 존재 검증 추가

## Task 5: self-JOIN 테스트 SQL

**Files:**
- Create: `benchmarks/clickhouse/queries/join.sql`
- Modify: `tests/clickhouse/validate.sh`

hits self-JOIN 대표 집계 쿼리. 8GB 인스턴스 OOM 방지 위해 **RAM 상대 spill** 적용:
`SETTINGS join_algorithm='grace_hash', max_bytes_ratio_before_external_group_by=<ratio>`
(절대 바이트값 금지 — R패밀리 조기 spill/C패밀리 OOM 유발). 서버 레벨 `max_memory_usage_to_ram_ratio`도 비율 기반.

- [ ] self-JOIN 쿼리 작성 (grace_hash + RAM 비율 spill)
- [ ] validate.sh에 구문 sanity + ratio 기반 SETTINGS 존재 검증 추가

## Task 6: ClickBench Job 템플릿

**Files:**
- Create: `benchmarks/clickhouse/clickhouse-clickbench.yaml`
- Modify: `tests/clickhouse/validate.sh`

다중 문서 YAML: PVC(dataSource VolumeSnapshot `clickhouse-hits`, SC `gp3-clickhouse`, 100Gi, RWO) + Job.
- **initContainer**: `chown -R 101:101 /var/lib/clickhouse` (스냅샷 소유권 정정)
- **메인 컨테이너**(이미지 `clickhouse/clickhouse-server:CLICKHOUSE_VERSION`): 실행 스크립트가
  ① server 백그라운드 기동 → ② ready 폴링 → ③ `queries.sql`을 줄 단위로 분리해 **각 쿼리 개별 실행**
  (`clickhouse-client --time`, per-query cold/hot, §10 로그) — `cat queries.sql | client` 금지 →
  ④ INSERT → ⑤ JOIN → ⑥ server stop → ⑦ exit 0
- 쿼리 SQL은 ConfigMap `clickhouse-queries`를 `/queries/`에 마운트
- **메모리 정책**: Pod에 **고정 메모리 limit 미설정**(ClickHouse가 노드 전체 메모리 인식 = C/M/R 비교 변수).
  ClickHouse는 `max_server_memory_usage_to_ram_ratio` 비율로 자동 스케일.
- nodeSelector/arch, podAntiAffinity, benchmark toleration, ttl, **backoffLimit: 0**
- placeholder `INSTANCE_SAFE`/`INSTANCE_TYPE`/`ARCH`/`RUN_NUMBER`/`CLICKHOUSE_VERSION`

- [ ] PVC + Job + initContainer + 실행 스크립트(백그라운드 기동/ready 대기/줄단위 개별 쿼리/정상 종료) 작성
- [ ] ConfigMap 마운트, podAntiAffinity·toleration·nodeSelector·backoffLimit 0, **고정 메모리 limit 없음**
- [ ] validate.sh에 c8i(amd64)·c8g(arm64) 치환 dry-run + placeholder 잔류 0 + 하드코딩 메모리 limit 부재 검증 추가

## Task 7: 실행/수집 스크립트

**Files:**
- Create: `scripts/generate-clickhouse-benchmark.sh`
- Modify: `tests/clickhouse/validate.sh`

generate-springboot 패턴: 쿼리 ConfigMap 생성(`kubectl create configmap clickhouse-queries --from-file=benchmarks/clickhouse/queries/`),
인스턴스별 PVC+Job 배포(배치 기본 12개 — EBS lazy-load/API 부하 관리), 완료 즉시 로그 수집 →
`results/clickhouse/<instance>/setN.log`, Job/PVC 정리.

- [ ] 스크립트 작성 (ConfigMap 생성, INTEL/GRAVITON 51개, chained-pipe sed, 배치 실행)
- [ ] validate.sh에 `bash -n` + 인스턴스 51개 검증 추가

## Task 8: 리포트 데이터 파서

**Files:**
- Create: `scripts/generate-clickhouse-report.py`
- Modify: `tests/clickhouse/validate.sh`

`results/clickhouse/<instance>/setN.log`(§10 포맷)를 파싱해 인스턴스별 hot 합계/per-query/INSERT/JOIN/
EBS 대역폭 메타를 집계 → 리포트 HTML에 차트 데이터(JSON) 주입. 기존 generate-*-report.py 패턴.

- [ ] 파서 작성 (§10 포맷 파싱, FAILED 항목 처리, 가격 대비 성능 계산)
- [ ] validate.sh에 `python3 -m py_compile` + 빈 입력 graceful 검증 추가

## Task 9: 표준 리포트 스캐폴드

**Files:**
- Create: `results/clickhouse/report-charts.html`
- Modify: `tests/clickhouse/validate.sh`

표준 리포트 형식(CSS 변수, Summary Cards, 목차, 방법론, 환경, 차트 placeholder, 필터 테이블, 결론).
**방법론 섹션에 EBS 대역폭 교란(§5 한계) 명시**. 데이터는 Task 8 파서가 주입.

- [ ] HTML 스캐폴드 작성 (Chart.js CDN, 표준 색상, EBS 교란 명시)
- [ ] validate.sh에 닫힌 태그·CDN 포함 검증 추가

## Task 10: CLAUDE.md ClickHouse 섹션

**Files:**
- Modify: `CLAUDE.md`

벤치마크 상태 표 행, ClickHouse 상세 설명 섹션, placeholder 표 행 추가
(스냅샷 ID, SC 스펙, EBS 교란 주의 명시).

- [ ] 상태 표/상세 섹션/placeholder 표 갱신

## 비범위

분산 클러스터, 다른 데이터셋, 실시간 스트리밍 ingest. 실제 51개 벤치마크 **실행**은
사용자 트리거(라이브 클라우드 비용) — 본 계획은 산출물 작성까지.
