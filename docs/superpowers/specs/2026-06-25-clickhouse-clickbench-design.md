# ClickHouse ClickBench 벤치마크 설계

- **작성일**: 2026-06-25
- **대상**: EKS EC2 Node Benchmark 프로젝트 (51개 xlarge 인스턴스)
- **목적**: ClickHouse(OLAP 컬럼형 DB)의 인스턴스 타입별 분석 쿼리 성능을 ClickBench 표준으로 비교

## 1. 배경 및 목표

기존 프로젝트는 sysbench/Redis/Nginx/Elasticsearch/SpringBoot 벤치마크로 51개 EC2 인스턴스(5~8세대,
Intel/AMD/Graviton)의 성능을 비교한다. 여기에 **OLAP 분석 워크로드**를 추가한다.

ClickHouse는 컬럼형 분석 DB로, 기존 벤치마크(트랜잭션/HTTP/인메모리)와 성격이 다른
**대용량 스캔·집계 중심 워크로드**를 대표한다. 측정 방법론은 ClickHouse 공식 벤치마크인
**ClickBench**(hits 데이터셋, 43개 분석 쿼리)를 사용한다.

### 측정하고 싶은 것
- 인스턴스 타입별 ClickBench 쿼리 지연시간(cold/hot)
- INSERT(적재) 처리량
- self-JOIN 쿼리 성능
- Intel vs AMD vs Graviton, 세대별/패밀리별 비교 및 가성비

## 2. 핵심 설계 결정 (확정)

| 항목 | 결정 | 이유 |
|------|------|------|
| 워크로드 | ClickBench (공식 hits 데이터셋, 43쿼리) | OLAP 표준, 비교 신뢰성 |
| 데이터셋 규모 | 전체 (100M행, ~14GB) | 공식 표준 규모 |
| 데이터 공급 | **EBS 스냅샷 `snap-024c86faa00cd0448`에서 PVC 복구** | 14GB×51 다운로드 회피, 적재 단계 생략 |
| 디스크 | **gp3 최고 성능** (StorageClass `gp3-clickhouse`: 16000 IOPS / 1000MB/s) | 모든 인스턴스 동일 디스크 → 디스크가 아닌 **CPU/메모리만 비교** |
| 쿼리 반복 | 43쿼리 × 3런(1 cold + 2 hot) × **5세트** | cold/hot 구분 + 분산 확인 |
| 추가 테스트 | **INSERT**(1천만 행 기본) + **self-JOIN** | 적재/조인 성능 확인 |
| 실행 형태 | 단일 컨테이너 Job (서버+클라이언트 로컬) | 네트워크 영향 배제, ClickBench 공식 방식 |
| 아키텍처 | Intel/Graviton 동일 스냅샷 | ClickHouse 데이터 포맷은 아키텍처 독립적 |

## 3. 아키텍처

### 3.1 데이터 흐름
```
snap-024c86faa00cd0448 (AWS EBS, 100GB, /var/lib/clickhouse 적재됨)
   │  (정적 바인딩)
   ▼
VolumeSnapshot: clickhouse-hits (benchmark ns) ──► VolumeSnapshotContent (pre-provisioned)
   │  dataSource
   ▼
PVC (인스턴스마다 1개, StorageClass gp3-clickhouse, ReadWriteOnce, 100GB)
   │  mount → /var/lib/clickhouse
   ▼
Job Pod (인스턴스 타입별 1개)
   ├─ clickhouse-server 기동 (로컬)
   ├─ clickhouse-client 로 43쿼리 × 3 × 5세트 실행
   ├─ INSERT 테스트 (1천만 행)
   └─ self-JOIN 테스트
   ▼
로그 → results/clickhouse/<instance>/setN.log
```

### 3.2 컴포넌트
1. **정적 VolumeSnapshot** (`benchmarks/clickhouse/clickhouse-snapshot.yaml`)
   - `snap-024c86faa00cd0448`를 가리키는 pre-provisioned VolumeSnapshotContent + VolumeSnapshot
   - DeletionPolicy: Retain (스냅샷 보존)

2. **ClickBench Job 템플릿** (`benchmarks/clickhouse/clickhouse-clickbench.yaml`)
   - 인스턴스별 PVC를 `dataSource: VolumeSnapshot`으로 동적 복구 (다중 문서 YAML: PVC + Job)
   - **initContainer**: 복구된 볼륨 소유권 정정 `chown -R 101:101 /var/lib/clickhouse` (스냅샷 uid 불일치 방지)
   - **메인 컨테이너 실행 스크립트**: clickhouse-server를 **백그라운드 기동** → TCP/HTTP ready 폴링 →
     쿼리를 **개별 실행**(per-query 타이밍, 3런 cold/hot) → 결과 로그(§10 포맷) 출력 → server graceful stop → **정상 종료**
     (foreground 기동 금지 — Job이 완료되지 않음)
   - 쿼리 SQL은 **ConfigMap**으로 마운트(`/queries/`), generate 스크립트가 `kubectl create configmap --from-file`로 생성
   - nodeSelector(인스턴스 타입), arch, podAntiAffinity(노드 격리), benchmark toleration, `backoffLimit: 0` (OOM 시 무한 재시작 방지)
   - 컨테이너 이미지: `clickhouse/clickhouse-server:CLICKHOUSE_VERSION` (placeholder, Phase 0에서 확정)
   - placeholder: `INSTANCE_SAFE`, `INSTANCE_TYPE`, `ARCH`, `RUN_NUMBER`, `CLICKHOUSE_VERSION`

3. **쿼리 SQL** (`benchmarks/clickhouse/queries/`)
   - `queries.sql`: ClickBench 공식 43쿼리
   - `insert.sql`: `INSERT INTO hits SELECT * FROM hits LIMIT 10000000` (행 수 파라미터화)
   - `join.sql`: 대표 self-JOIN 쿼리

4. **결과/리포트** (`results/clickhouse/`)
   - `<instance>/setN.log`: 세트별 쿼리 cold/hot ms
   - `report-charts.html`: 표준 리포트(Top20, 세대별, 패밀리별, 가성비 버블/Top15, 필터 테이블)

## 4. 측정 메트릭

| 메트릭 | 단위 | 방향 |
|--------|------|------|
| 쿼리 cold 지연 | ms | ⬇️ lower is better |
| 쿼리 hot 지연 | ms | ⬇️ lower is better |
| 전체 43쿼리 합계(hot) | s | ⬇️ lower is better |
| INSERT 처리량 | rows/sec | ⬆️ higher is better |
| JOIN 지연 | ms | ⬇️ lower is better |

## 5. 공정성 보장 및 교란변수 (consensus P2 반영)

- **볼륨 스펙 동일화**: 모든 인스턴스가 동일 gp3 스펙(16000 IOPS/1000MB/s) PVC 사용 → **볼륨 자체의
  IOPS/throughput 차이는 제거**.
- **⚠️ 한계 — per-instance EBS 대역폭 교란**: gp3 볼륨이 16000 IOPS/1000MB/s로 설정돼도, 실제 처리량은
  **인스턴스 자체의 EBS 대역폭 상한**에 종속된다. 구형/소형 인스턴스(예: 5세대 일부 ~593MB/s, baseline)는
  볼륨 한도보다 낮아 I/O가 인스턴스 EBS 대역폭에 병목된다. 또한 hits 데이터셋(~14GB)은 8GB C패밀리의
  OS page cache에 들어가지 않으므로 **hot 쿼리도 EBS를 다시 읽는다**. 따라서 "디스크 완전 중립화"는 성립하지
  않으며, 본 벤치마크는 다음으로 대응한다:
  1. 각 인스턴스의 **per-instance EBS baseline/burst 대역폭을 리포트에 함께 표기**(교란 가시화).
  2. **주 비교 지표는 hot 지연**으로 하되, "메모리 ≥ 데이터셋"인 인스턴스(R패밀리 32GB 등)에서만
     순수 page-cache-bound로 간주하고, 그 외는 "CPU+EBS 혼합"으로 명시.
  3. cold 런 지연은 **disk+CPU 혼합**으로 라벨링(순수 CPU/메모리 아님).
- **노드 격리**: podAntiAffinity로 다른 벤치마크 Pod와 노드 분리.
- **EBS lazy-load 주의**: 스냅샷 복구 볼륨은 첫 블록 접근 시 S3에서 lazy-load됨 → 첫 cold 런이
  느릴 수 있음. 5세트×3런 구조로 hot 수치는 상대적으로 안정. 필요 시 FSR(Fast Snapshot Restore)로 사전 워밍(옵션, 비용 발생).
- **메모리 차이**: C(8GB)/M(16GB)/R(32GB) — ClickHouse는 디스크 기반 컬럼 스토어라 8GB에서도 동작하나
  집계 쿼리에서 메모리 차이가 드러남 (의도된 비교 대상).
- **OOM 처리**: self-JOIN/INSERT가 소메모리 인스턴스(8GB)에서 OOM될 수 있다. spill 설정
  (`max_bytes_before_external_group_by`, `join_algorithm='grace_hash'`, `max_memory_usage`)을 적용하고,
  그래도 실패하면 **해당 인스턴스의 그 항목을 "FAILED"로 명시 기록**(누락이 아니라 비교 가능한 실패 데이터점).
- **실행 순서 고정 (행수 일관성)**: ① pristine 스냅샷에서 43쿼리×3×5세트 → ② INSERT 테스트 →
  ③ self-JOIN 테스트. INSERT가 테이블 행수를 바꾸므로 순서를 모든 인스턴스에 동일 적용해 비교 가능성 보장.

## 6. 실행 전략

- **Coldstart 방식과 달리**, 각 Job이 100GB PVC를 복구하므로 동시 51개는 EBS API/lazy-load 부하가 큼.
  → 배치(batch) 단위(예: 10~15개씩)로 나눠 실행하거나, FSR 적용 후 전체 병렬.
- 결과 수집은 기존 패턴(완료 즉시 로그 수집, TTL 만료 전)을 따른다.

## 7. Phase 0 (구현 첫 단계, 필수)

`snap-024c86faa00cd0448`에서 볼륨 1개를 복구해 마운트 → 적재된 데이터의 **ClickHouse 버전**(`SELECT version()`),
**DB/테이블 이름**(`SELECT database,name FROM system.tables WHERE name='hits'` — ClickBench 표준은 `default.hits`),
**행 수**(`SELECT count() FROM hits` — ~100M 기대)를 확인한다. 이 버전으로 쿼리 컨테이너 이미지를 핀하고
(데이터 호환성 보장), 쿼리 SQL의 `FROM` 절을 확정한다.

**사전 검증**: Task 0 전에 클러스터 자산 존재 확인 — `kubectl get crd volumesnapshots.snapshot.storage.k8s.io`,
`kubectl get storageclass gp3-clickhouse`, `kubectl get volumesnapshotclass gp3-clickhouse-snapclass`.
(현재 모두 존재함을 확인 완료.)

**오프라인 기본값(authoring unblock)**: Task 0는 라이브 확인 단계지만, 그 결과를 기다리지 않고 산출물 작성을
시작할 수 있도록 기본값을 둔다 — 테이블 `default.hits`, 이미지 `clickhouse/clickhouse-server:24.8`(LTS,
스냅샷 호환 확인 후 정정). Task 0는 이 기본값의 **확정/정정** 역할.

## 8. 산출물

```
benchmarks/clickhouse/clickhouse-storageclass.yaml  # SC gp3-clickhouse + VolumeSnapshotClass (재현성; 이미 클러스터에 존재, 멱등 apply)
benchmarks/clickhouse/clickhouse-snapshot.yaml      # 정적 VolumeSnapshot (snap-024) + VolumeSnapshotContent
benchmarks/clickhouse/clickhouse-clickbench.yaml    # Job + PVC(dataSource) + 쿼리 ConfigMap 마운트
benchmarks/clickhouse/queries/queries.sql           # ClickBench 43쿼리
benchmarks/clickhouse/queries/insert.sql            # INSERT 테스트
benchmarks/clickhouse/queries/join.sql              # self-JOIN 테스트 (grace_hash)
scripts/generate-clickhouse-benchmark.sh            # ConfigMap 생성 + 배포 + 수집 (기존 패턴)
scripts/generate-clickhouse-report.py               # setN.log 파싱 → 리포트 데이터 주입
results/clickhouse/<instance>/setN.log              # 결과 로그 (포맷 §10)
results/clickhouse/report-charts.html               # 표준 리포트
CLAUDE.md                                            # ClickHouse 섹션 추가
```

**기존 클러스터 자산(확인됨, 재생성 불필요)**: StorageClass `gp3-clickhouse`(gp3/16000/1000),
VolumeSnapshotClass `gp3-clickhouse-snapclass`(Retain), EBS CSI driver, snapshot CRD,
VolumeSnapshot `clickhouse-hits` 모두 클러스터에 존재. repo 매니페스트는 재현성/문서화 목적(멱등 apply).

## 10. 결과 로그 포맷 (파서 계약)

각 `results/clickhouse/<instance>/setN.log`는 헤더 + CSV 라인으로 구성:
```
INSTANCE: c8i.xlarge
ARCH: amd64
CLICKHOUSE_VERSION: <version>
SET: N
# query results (per-query, 3 runs):
QUERY,run,cold_ms,hot1_ms,hot2_ms
q00,1,1234,210,205
...
q42,1,...
# insert test:
INSERT_ROWS: 10000000
INSERT_MS: <ms>
INSERT_ROWS_PER_SEC: <rps>
# self-join test:
JOIN_MS: <ms>   (또는 JOIN: FAILED:<reason>)
```
`scripts/generate-clickhouse-report.py`가 이 포맷을 파싱해 차트 데이터(JSON)를 리포트에 주입한다.

## 9. 비범위 (YAGNI)

- 분산 ClickHouse 클러스터(샤딩/레플리카) — 단일 노드만
- 다른 데이터셋(Star Schema 등) — hits만
- 실시간 ingest 스트리밍 — INSERT 배치만
