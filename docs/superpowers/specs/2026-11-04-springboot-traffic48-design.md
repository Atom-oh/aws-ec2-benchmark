# Spring Boot 48시간 트래픽 변화 비교

사용자 요구: m7i.xlarge의 평상시 CPU 약 40%에 해당하는 **동일한 요청량**을
m7i.xlarge, m7i-flex.xlarge, m8i.xlarge, m8i-flex.xlarge, m7g.xlarge,
m8g.xlarge에 보낸다. 48시간 내내 부하를 변경하고, m7i 실측 처리 용량을
초과하는 피크에서 상대 응답시간, 성공 처리량, 오류 및 회복을 비교한다.
서비스의 절대 응답시간 SLA는 설정하지 않는다.

## 측정 대상과 기준

기존 처리량 대상은 PetClinic이 아닌 springboot-simple `/`이다(CLAUDE.md).
이 앱과 Java 21, G1, MaxRAMPercentage=60, TieredCompilation OFF를 유지한다.
기존 springboot-flex48 리소스, 실행 코드, PVC 및 결과를 변경하지 않는다.
신규 실험 이름은 springboot-traffic48, 리소스 접두사는 sb-traffic48이다.

m7i를 5분 준비한 뒤 여러 고정 요청 속도로 보정한다. process.cpu.usage로
40% 부하를 보간하고, 유효한 부하 발생기 구간에서의 최대 성공 RPS를 실측
용량으로 삼는다. 평상시 R40부터 실측 용량 110%인 Rpeak까지 60/80/100
레벨을 선형 보간한다. 레벨은 m7i 기준 트래픽 강도 이름이지 각 서버 CPU 목표가 아니다.
보정은 48시간에서 제외한다. 기존 단기 로그의 수치나 Flex 감소율 환산값을
이번 비교의 표준형 실측으로 사용하지 않는다.

## 48시간 요청 시나리오

첫 24시간: 아래 240분 주기를 6회 반복한다.

| 레벨 | 40 | 60 | 80 | 100 | 80 | 60 | 40 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 분 | 45 | 30 | 30 | 30 | 30 | 30 | 45 |

다음 24시간: 아래 240분 주기를 6회 반복한다.

| 레벨 | 40 | 100 | 40 | 100 | 40 | 100 | 40 | 100 | 40 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 분 | 45 | 1 | 39 | 5 | 30 | 15 | 30 | 60 | 15 |

처음 주기의 전환은 60초 동안 선형 ramp로 진행한다(구간 길이에 포함).
두 번째 날의 피크는 즉시 전환한다. 요청 시작 시각을 기준으로 동일 schedule을
모든 대상에 적용하고 미래의 공통 UTC epoch로 동기화한다. 재시작 및 자동 재시도는 금지한다.

## 요청 발생 및 저장

서버 응답 속도와 독립적으로 요청을 예약하는 Go 표준 라이브러리 클라이언트.
고정 연결/동시 실행 상한을 두고, 밀린 예약 및 상한 초과는 dropped로 기록한다.
응답 대기 시간은 예정 요청 시작부터 종료까지 측정한다. 클라이언트 자체가
못 보낸 요청을 정상 처리량으로 숨기지 않는다. HTTP 요청 timeout은 2초다.

1초 간격의 카운터와 병합 가능한 압축 히스토그램을 NDJSON에 보존한다.
각 원본 phase 식별자를 붙여 전환 후 늦게 완료된 요청도 추적한다.
p50/p95/p99는 히스토그램을 병합해서 산출하며 구간 p99의 평균을 사용하지 않는다.
히스토그램의 근사 오차 및 bin 정의를 기록한다. 서버 Actuator CPU/GC/메모리/
uptime을 10초마다, 클라이언트 CPU 및 예약 지연을 1초마다 보존한다.
힙 used/committed/max, nonheap used, GC allocated/promoted/live/max data size를
추가 수집한다. 미지원 metric은 오류로 명시한다. GC와 safepoint unified
logging을 각 서버의 별도 1Gi gp3 PVC에 회전 로그로 기록한다. p99 상승과
GC pause의 시간적 동반 변화를 비교하되 원인이라고 자동 단정하지 않는다.
부하 발생기 부족, metrics 누락 및 uptime 초기화는 별도 경고로 드러낸다.

## EKS 배치와 수명

mall-apne2-mgmt context / benchmark namespace를 모든 명령에 명시한다.
서버 6대와 전용 c6in.2xlarge 부하 발생기 6대, 서울 2c, On-Demand.
benchmark 라벨 Exists에 대한 hostname required anti-affinity를 유지해
기존 벤치마크와 신규 서버/클라이언트 사이의 노드 공유를 막는다.
CPU limit은 없고 서버 3000m/12Gi, 클라이언트 6000m/4Gi 요청을 사용한다.
server account token은 끈다. ClusterIP만 사용한다.
이미지는 digest 고정, 서버 manifest의 arm64/amd64 지원을 배포 전 확인한다.
Job은 backoffLimit=0, restartPolicy=Never, 7일 TTL, 유한 deadline을 갖는다.
각 클라이언트 1Gi gp3 PVC와 서버 GC 1Gi gp3 PVC는 결과 수집 후 명시적으로 삭제한다.
정상/실패 종료 시 자신의 서버 Job/Service만 정리할 수 있는 resourceNames
제한 Role을 사용한다. deadline은 정리 코드가 실패할 때도 서버 실행을 제한한다.

## 결과와 검증

results/springboot-traffic48/<run-id>/<instance>/에 저장한다.
m7i 대비 성공 RPS 비율, p95/p99 지연 비율, 오류율 차이(percentage point),
요청 손실률 및 피크 종료 후 회복 시간을 같은 완료 phase에서 비교한다.
부분 phase는 관측 통계만 표시하고 상대 배수는 null로 둔다. 실제 sample interval의
합집합과 누락을 확인하며 raw counter/histogram 및 최종 totals를 대조한다.
GC 원본의 수집 coverage와 회전으로 사라진 구간을 별도로 기록한다.
회복은 직전 평상시 자신의 p99/성공률 범위(지연 +10%, 성공률 -1pp)에
30초 연속 복귀한 첫 시점으로 정의한다. 회복 범위가 없으면 null이다.
한 인스턴스/한 호스트 표본이라는 한계를 기록한다. Flex 내부 제한 원인을
CPU 감소 하나로 확정하지 않는다.

배포 전 local tests, Go race test, server-side dry-run, 이미지 검증 및
독립 content-review-agent 점수 85 이상 필수. 보정은 별도 짧은 Job이고
유효한 m7i 기준값을 확보한 후 48시간 시나리오를 시작한다.
