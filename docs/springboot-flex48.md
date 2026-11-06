# Spring Boot Flex 48시간 테스트

사용자 요청에 따라 `m7i-flex.xlarge`, `m8i-flex.xlarge`만 각각 48시간 측정한다.
두 서버는 4 vCPU / 16 GiB, 서울 리전 `ap-northeast-2c`의 기존 벤치마크 EKS에서
On-Demand로 실행한다. 각 서버에 별도의 `c6in.2xlarge` 부하 발생기를 사용한다.
Karpenter의 노드 격리 규칙을 유지하며 서버와 클라이언트에 CPU limit은 설정하지 않는다.
클러스터 시스템 DaemonSet은 각 노드에 존재한다.
최초 2a 시도는 부하 발생기 `c6in.2xlarge`의 실제 EC2 용량 부족으로 측정 시작 전에 중단했다.
AWS의 용량 오류가 제시한 가용 영역 중 기존 서브넷이 있는 2c로 서버와 클라이언트를 함께 이동했다.

## 측정 조건

- 기존 Java 21 / Spring Boot 3.2 simple 이미지의 `/` HTTP 엔드포인트.
- 기존 JVM 설정 유지: G1 GC, MaxRAMPercentage=60, TieredCompilation OFF.
- 서버/클라이언트 이미지 모두 digest 고정.
- 5분 준비 부하 이후 **172,800초 연속** `wrk -t4 -c200 --latency` 실행.
- 연속 부하와 동시에 `wrk -t2 -c100 --latency`로 약 60초마다 처리량과 평균/p99 지연시간 측정.
  따라서 전체 부하는 보통 6 threads / 300 connections다. 측정 창 사이에도 연속 부하는 유지된다.
- `probe_rps`는 측정 프로세스의 처리량이며 전체 처리량이 아니다. 전체 48시간 처리량은
  종료 시 `continuous.log`의 처리량과 각 probe의 원시 요청 수/시간을 함께 사용해야 한다.
  probe 실행 조건이 다르므로 기존 단기 `-t2 -c100` 결과와 직접 비교하지 않는다.
- 분 단위로 system/process CPU 사용률, JVM 메모리, GC, process uptime 원시 Actuator JSON 기록.
  system CPU 값은 0~1 비율이다. 낮은 CPU나 요청 오류가 있으면 포화 부하로 해석하지 않는다.
  CPU 저하가 관측되더라도 이 테스트 하나로 Flex의 특정 내부 메커니즘을 확정하지 않는다.
- 두 테스트는 병렬로 시작하지만 스케줄링과 5분 준비 부하 때문에 시작 시각은 조금 다를 수 있다.
  실제 시작/종료 epoch는 각각 `run.txt`에 기록한다.
- 준비 부하는 기록에서 분리한다. HTTP/socket 오류, metrics 수집 오류도 보존한다.
  처리량이 0이거나 지연시간 값이 누락되거나 연속 wrk가 일찍 종료하면 FAILED로 표시한다.
  실제 연속 부하 종료 시각까지 검사하므로 마지막 probe 중 조기 종료도 완료로 처리하지 않는다.

## 실행과 확인

```bash
python3 scripts/springboot_flex48.py prepare --run-id <RUN_ID> \
  --server-digest sha256:<DIGEST> --client-digest sha256:<DIGEST>
# 생성된 servers.yaml / clients.yaml 검증 및 리뷰 후:
python3 scripts/springboot_flex48.py launch --run-id <RUN_ID>
python3 scripts/springboot_flex48.py status --run-id <RUN_ID>
python3 scripts/springboot_flex48.py collect --run-id <RUN_ID>
python3 scripts/springboot_flex48.py watch --run-id <RUN_ID>
```

명령은 항상 `mall-apne2-mgmt` context를 지정한다. 사용자의 현재 kube context를 변경하지 않는다.
결과 경로는 `results/springboot-flex48/<RUN_ID>/<instance>/`다.
현재 실행의 최초 CSV 파서가 `Latency Distribution` 헤더까지 평균으로 읽는 문제가
첫 실제 probe에서 발견됐다. `collect`는 원본 `probes.log`의 각 측정 구간에 있는
실제 평균 지연시간으로 로컬 `samples.csv`를 복구하고, 수집한 원래 CSV는
`samples-raw.csv`로 보존한다. 클러스터의 원본 CSV 평균 값은 이 실행에서 0으로 남으므로
복구된 로컬 CSV 또는 원본 wrk 로그를 사용한다. 실행 중인 48시간 부하는 중단하지 않았다.
다음 실행용 shell 파서에도 헤더 제외를 적용했다.
`watch`는 1분마다 Job 상태를 확인하고 약 30분마다 실행 중 결과를 로컬에 복사한다.
두 Job이 종료되면 PVC에서 마지막 결과를 복구하고 끝난다. 최대 50시간 후 종료한다.
observer가 종료돼도 클러스터의 테스트와 PVC 기록은 계속 유지된다.

## 종료 및 보존

각 클라이언트는 성공/실패 시 자신의 서버 Job과 ClusterIP Service를 삭제한다.
삭제 권한은 해당 실행의 두 서버 이름으로 제한된다. 클라이언트 Job은 재시도하지 않는다.
서버는 재시작하지 않는 Job이므로 JVM/노드 장애가 발생해도 새로운 JVM으로 조용히 측정을 이어가지 않는다.
서버에는 50시간, 클라이언트에는 49.5시간 deadline을 적용한다.
15분 내 서버 준비를 확인한 뒤 클라이언트를 배포하므로 서버 deadline은 클라이언트 deadline과
서버 준비 시간을 모두 포함한다. 클라이언트 스케줄링/초기화가 약 85분 이상 지연되면
클라이언트 deadline 때문에 완전한 48시간 측정을 못 할 수 있으며, 이 경우 실패로 기록한다.
노드가 비면 기존 Karpenter 설정으로 정리된다. 종료된 Pod/Job은 7일 후 자동 삭제된다.

각 클라이언트의 1 GiB gp3 PVC는 종료 후에도 유지되며 소액의 저장 비용이 남는다.
완료된 Pod의 전체 결과는 `collect`가 임시 PVC reader Pod를 생성해서 복사한 뒤 reader를 삭제한다.
PVC 삭제는 결과 확보 후 해당 실행의 이름을 지정해서 수행한다.
대화나 로컬 프로세스가 종료돼도 측정과 서버 정리는 클러스터 안에서 계속된다.
클라이언트 패키지 설치 또는 노드 자체가 실패해 정리 코드가 실행되지 않는 경우 서버 deadline이
실행 시간을 제한한다. 이때는 COMPLETE로 해석하지 않는다.

검증: `python3 -m unittest discover -s tests/springboot-flex48 -v`, shell/Python 문법 검사,
생성 YAML의 클러스터 server dry-run, 배포 전 독립 리뷰.
