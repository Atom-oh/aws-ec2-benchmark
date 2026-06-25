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
   - 인스턴스별 PVC를 `dataSource: VolumeSnapshot`으로 동적 복구
   - nodeSelector(인스턴스 타입), arch, podAntiAffinity(노드 격리), benchmark toleration — 기존 패턴 동일
   - 컨테이너 이미지: `clickhouse/clickhouse-server:<버전>` (Phase 0에서 확정)
   - placeholder: `INSTANCE_SAFE`, `INSTANCE_TYPE`, `ARCH` (기존 규칙)

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

## 5. 공정성 보장

- **디스크 동일화**: 모든 인스턴스가 동일 gp3 스펙(16000 IOPS/1000MB/s) PVC 사용 → 디스크 성능 차이 제거,
  순수 CPU/메모리 차이만 측정
- **노드 격리**: podAntiAffinity로 다른 벤치마크 Pod와 노드 분리
- **EBS lazy-load 주의**: 스냅샷 복구 볼륨은 첫 블록 접근 시 S3에서 lazy-load됨 → 첫 cold 런이
  느릴 수 있음. 5세트×3런 구조로 hot 수치는 깨끗함. 필요 시 FSR(Fast Snapshot Restore)로 사전 워밍(옵션, 비용 발생).
- **메모리 차이**: C(8GB)/M(16GB)/R(32GB) — ClickHouse는 디스크 기반 컬럼 스토어라 8GB에서도 동작하나
  집계 쿼리에서 메모리 차이가 드러남 (의도된 비교 대상).

## 6. 실행 전략

- **Coldstart 방식과 달리**, 각 Job이 100GB PVC를 복구하므로 동시 51개는 EBS API/lazy-load 부하가 큼.
  → 배치(batch) 단위(예: 10~15개씩)로 나눠 실행하거나, FSR 적용 후 전체 병렬.
- 결과 수집은 기존 패턴(완료 즉시 로그 수집, TTL 만료 전)을 따른다.

## 7. Phase 0 (구현 첫 단계, 필수)

`snap-024c86faa00cd0448`에서 볼륨 1개를 복구해 마운트 → 적재된 데이터의 **ClickHouse 버전**과
**테이블/DB 이름**(`hits` 테이블이 어느 DB에 있는지), **행 수**를 확인한다. 이 버전으로 쿼리 컨테이너
이미지를 핀하고(데이터 호환성 보장), 쿼리 SQL의 테이블 참조를 맞춘다.

## 8. 산출물

```
benchmarks/clickhouse/clickhouse-snapshot.yaml      # 정적 VolumeSnapshot (snap-024)
benchmarks/clickhouse/clickhouse-clickbench.yaml    # Job 템플릿
benchmarks/clickhouse/queries/queries.sql           # ClickBench 43쿼리
benchmarks/clickhouse/queries/insert.sql            # INSERT 테스트
benchmarks/clickhouse/queries/join.sql              # self-JOIN 테스트
scripts/generate-clickhouse-benchmark.sh            # 배포+수집 스크립트 (기존 패턴)
results/clickhouse/<instance>/setN.log              # 결과 로그
results/clickhouse/report-charts.html               # 표준 리포트
CLAUDE.md                                            # ClickHouse 섹션 추가
```

## 9. 비범위 (YAGNI)

- 분산 ClickHouse 클러스터(샤딩/레플리카) — 단일 노드만
- 다른 데이터셋(Star Schema 등) — hits만
- 실시간 ingest 스트리밍 — INSERT 배치만
