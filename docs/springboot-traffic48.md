# Spring Boot 트래픽 변화 48시간 비교

목적은 장시간 평상시 부하를 처리한 서버가 트래픽 증가/급증 때 어떻게 반응하는지
**m7i.xlarge 기준의 상대 값**으로 비교하는 것이다. 서비스 SLA 합격/불합격은 정하지 않는다.

비교군은 m7i.xlarge, m7i-flex.xlarge, m8i.xlarge, m8i-flex.xlarge,
m7g.xlarge, m8g.xlarge다. 모두 4 vCPU / 16 GiB이지만 Graviton의 코어 구성은
Intel의 vCPU 구성과 다르므로 같은 물리 코어 수 비교라고 해석하지 않는다.

## 트래픽 설정

1. m7i.xlarge에 5분 준비 부하 후 20개 요청량 단계에 각각 2분의 보정 부하를 보낸다.
   5,000~80,000 RPS에서는 5,000 단위로, 이후 90,000/100,000/120,000/150,000 RPS로
   측정한다. 준비 부하를 포함한 보정은 45분이며 48시간 측정과 별도다.
2. process.cpu.usage의 40%를 사이에 둔 유효 두 단계의 요청량으로 평상시 R40을 보간한다.
3. JVM CPU 90% 이상인 유효 단계에서 최대 성공 처리량을 측정 용량으로 잡는다.
   부하 발생기 CPU 80% 이상, dispatch 지연 p95 25 ms 초과, 미발생 요청 1% 초과,
   CPU/uptime 누락 또는 JVM 재시작이 있으면 보정 결과를 사용하지 않는다.
4. 피크 요청량은 이 **실측 성공 용량의 110%**다. 60/80 레벨은 R40과 피크 사이를 선형 보간한다.
   이 레벨은 트래픽 강도 이름이며 각 대상의 CPU가 실제로 60/80/100%가 된다는 뜻은 아니다.
5. 모든 서버에 같은 절대 요청량과 공통 UTC 시작 시각을 적용한다.

보정 시작이 1초 이상 늦으면 보정을 거부한다. 본 실행의 시작 지연, JVM 재시작,
누락 비교군은 comparison_valid와 quality에 표시한다. 동시 요청 상한·예약 지연·
취소에 의한 누락은 완료 status의 drop_reasons로 나누어 기록한다.

평상시 R40은 보간값이므로 정확히 CPU 40%라고 보장하지 않는다. 최초 평상시 구간의
m7i 실측 CPU를 함께 보고한다. 같은 요청량에서도 Flex/Graviton CPU는 다를 수 있다.
미공개 Flex 회복/제한 규칙을 가정하지 않는다.

## 48시간 시나리오

보정 및 공통 5분 준비 부하는 48시간에 포함하지 않는다.

| 측정 시간 | 반복 패턴 | 횟수 |
|---|---|---:|
| 0~24시간 | 40→60→80→100→80→60→40, 각각 45/30/30/30/30/30/45분 | 6 |
| 24~48시간 | 평상시 40 사이에 100 피크를 1/5/15/60분 삽입 | 6 |

첫날 전환은 각 구간의 처음 60초에 선형으로 바뀐다. 둘째 날은 갑자기 바뀐다.
둘째 날 한 주기는 40(45분),100(1분),40(39분),100(5분),40(30분),100(15분),
40(30분),100(60분),40(15분)이며 총 4시간이다.

각 구간에서 예정 요청을 독립적으로 예약한다. 서버가 느려져도 예정 요청량은 줄지 않는다.
클라이언트 동시 요청 상한 2048, 예정 시간보다 dispatch가 10 ms 이상 늦거나 상한을
초과한 요청은 dropped로 기록한다. timeout은 2초다. dropped는 실제 서버가 받은
요청과 구분하며 부하 발생기의 한계와 서버 대기 증가가 모두 가능하다.

## 응답시간, 메모리, GC

- `samples.ndjson`: 1초 간격의 offered/started/completed/success/error/timeout/dropped,
  예정 시작부터 완료까지의 지연시간 히스토그램, client CPU와 dispatch 지연.
- p50/p95/p99는 히스토그램을 합쳐 계산한다. 실패 요청의 완료 시간도 포함하고,
  미발생 요청은 지연시간 없이 별도 loss로 기록한다. 히스토그램은 64 us 이상에서
  상한 근사 오차 1.563% 미만이다. p99를 구간별로 평균 내지 않는다.
- `metrics.ndjson`: 10초 간격의 JVM/system CPU, uptime, heap used/committed/max,
  nonheap used, GC pause COUNT/TOTAL_TIME, allocation/promotion/live/max data.
  제공되지 않는 Actuator metric은 오류로 남긴다.
- `gc/`: JVM `gc*` 및 safepoint 원본 회전 로그. 30분 수집 시 `all.log`에 확보한 로그를
  누적한다. 실행 중인 서버는 `sh`로 파일 목록을 확인하고 `cat`으로 읽어 Java 이미지의
  `tar` 유무에 의존하지 않는다. 실패한 캡처는 이전 원본을 유지하고 수집 오류로 기록한다.
  회전 속도가 수집보다 빠르면 원본 일부가 없어질 수 있다.
  `coverage.json`은 남은 원본의 최초 시각부터 복사 시작까지를 관측 구간으로 추정하고,
  이전 수집 이후 원본이 사라진 시간은 gaps로 기록한다. 복사는 원자적이지 않으므로
  이 coverage는 보존 상태 추정값이다. raw 로그의 GC pause 횟수/총 시간/최대 시간을
  같은 phase에 합산하고 큰 p99 표본 주변 ±2초의 GC 이벤트를 표시한다.
  로그 기반 횟수·총 시간은 확보된 이벤트의 하한으로 해석하며, 추정 구간이 가득 차도
  GC가 없었다는 확정값을 내지 않는다. p99와 GC의 시간적 동반 관측에도 이 한계를 표시한다.
- GC가 없는 경우와 로그 미수집은 구분이 제한되므로 coverage 필드를 함께 보고한다.
  동시에 관측됐다는 이유만으로 GC를 p99 변화의 원인이라고 단정하지 않는다.

측정 앱은 **springboot-simple의 `/`**이다. 기존 처리량 앱과 동일하게 Java 21,
G1, heap 60%, TieredCompilation OFF를 사용한다. PetClinic은 기존 콜드스타트
테스트용이었다. 정적 응답의 객체 할당은 실제 DB/세션/캐시를 가진 앱의 GC 패턴을
대표하지 않는다. 이 실험은 같은 테스트 앱에서의 인스턴스 차이를 관측한다.

## 결과 해석

완료되고 수집 무결성이 확인된 같은 phase에서 m7i 대비 성공 RPS 배수, p95/p99 배수,
오류율 차이(pp)를 계산한다. 서버 CPU 및 메모리·GC를 같이 보여준다.
진행 중 phase는 대상별 통계만 표시하고, 시간창이 완성되기 전 상대 배수는 null로 둔다.
부하 발생기 자체의 CPU/dispatch/drop 문제가 있으면 낮은 처리량을 서버 한계로
자동 해석하지 않는다. 완료 결과와 진행 중 일부 구간을 구분하며 누락 비교군을 명시한다.

회복 시간은 피크 뒤 40 구간에서, 피크 전 자신의 평상시 p99 +10% 이내와
성공 비율 -1pp 이내에 30초 연속 돌아온 첫 시점이다. 이전 평상시 표본이
없거나 복귀가 관측되지 않으면 null이다. 이 범위는 분석용 설정이며 서비스 SLA가 아니다.
실험은 타입당 한 호스트/한 JVM이므로 반복 및 다른 호스트 없이 제품 전체로 일반화하지 않는다.

## 실행

```bash
python3 scripts/springboot_traffic48.py prepare --run-id <run-id> \
  --server-digest sha256:<digest> --client-digest sha256:<digest>
# 현재 코드의 독립 검토 결과(review.json, score >=85, artifact hash 일치) 필요
python3 scripts/springboot_traffic48.py calibrate --run-id <run-id>
python3 scripts/springboot_traffic48.py launch --run-id <run-id>
python3 scripts/springboot_traffic48.py status --run-id <run-id>
python3 scripts/springboot_traffic48.py collect --run-id <run-id>
python3 scripts/springboot_traffic48.py analyze --run-id <run-id>
python3 scripts/springboot_traffic48.py watch --run-id <run-id>
```

결과는 `results/springboot-traffic48/<run-id>/`에 저장한다. context는 항상
mall-apne2-mgmt이며 현재 context는 바꾸지 않는다. 여섯 서버와 여섯 전용
c6in.2xlarge 클라이언트는 2c/On-Demand 및 hostname anti-affinity로 격리한다.
기존 springboot-flex48 리소스를 변경하거나 재시작하지 않는다.

`watch`와 `collect`는 보고서 분석을 현재 Python 인터프리터의 별도 자식
프로세스에서 실행하고 종료를 기다린다. 분석 프로세스가 종료되면 사용한
메모리를 운영체제에 반환한다. 분석 중에는 다음 수집을 시작하지 않아 같은
입력 파일을 동시에 갱신하지 않는다. 분석이 실패하면 오류를 기록하고 기존
원자적으로 저장된 보고서를 유지한다. 직접 `analyze`를 실행해도 같은 집계와
검증을 적용한다.

배포 전에 독립 검토자가 현재 소스에 대해 PASS를 내리고 정규화 점수가 85 이상이어야 한다.
검토 기록은 `results/springboot-traffic48/<run-id>/review.json`에 둔다:

```json
{
  "verdict": "PASS",
  "score": 95,
  "artifact_sha256": "<현재 artifact_hash() 값>",
  "reviewer": "<독립 검토자 식별자>",
  "evidence": "<검토 결과 파일 경로>"
}
```

점수만으로 통과하지 않는다. 작성자는 자신의 결과를 독립 PASS로 기록할 수 없다.
해시를 확인하는 명령은 다음과 같다. 검토 이후 소스가 바뀌면 다시 검토해야 한다.

```bash
PYTHONPATH=scripts python3 -c 'import springboot_traffic48 as r; print(r.artifact_hash())'
```

서버는 54시간, 측정 클라이언트는 50시간 deadline이며 재시도/재시작은 없다.
일반 liveness 재시작은 금지하고 죽은 서버는 요청 실패로 보존한다.
클라이언트는 종료 시 자기 서버 Job/ClusterIP만 삭제할 수 있다. 실행 준비나
클라이언트 시작 자체가 실패하면 서버 deadline이 남은 실행을 제한한다.
Job/Pod는 7일 TTL이다. 1Gi PVC 12개와 보정용 1Gi PVC 1개는 수집 후
실행 이름을 지정해 삭제해야 하며 보존 중 저장 비용이 발생한다.

## 실행 중 피크를 90,000 RPS로 변경

사용자가 지정한 새 목표는 90,000 RPS다. 기존 서버/JVM, 주 클라이언트,
측정 시작·종료 시각을 유지하면서 대상마다 독립된 c6in.2xlarge 생성기를 하나씩
추가한다. 각 추가 생성기는 별도 전용 노드와 1Gi 결과 PVC를 사용하며 CPU limit,
service-account token 및 서버 삭제 권한이 없다. 이미지 digest는 고정한다.

추가 생성기는 기존 피크 76,291.49022349785 RPS와 새 목표의 차이인
13,708.50977650215 RPS를 100 단계에만 더한다. 평상시·60·80 단계의 고정
목표는 유지한다. 첫날 피크 진입은 추가량을 60초에 걸쳐 올리고, 이어지는
80 단계의 첫 60초에는 추가량을 0으로 내린다. 둘째 날은 즉시 전환한다.

추가 생성기가 쉬는 구간은 `allow_idle=true`로 허용한 0 RPS phase다.
일반 생성기의 기본 유효성 검사는 여전히 0 RPS를 거부한다. 공유 시작 시각은
기존 schedule의 미래 phase 경계이며, 준비에 최소 15분을 확보한다.
추가 schedule은 기존 측정의 남은 구간만 포함하며 원래 종료 시각에 끝난다.

```bash
python3 scripts/springboot_traffic48_boost.py prepare --run-id <run-id> \
  --client-digest sha256:<추가 생성기 digest> --peak-rps 90000
# 현재 소스의 독립 검토 PASS >=85 및 artifact hash 일치 필요
python3 scripts/springboot_traffic48_boost.py launch --run-id <run-id>
python3 scripts/springboot_traffic48_boost.py status --run-id <run-id>
```

기존 metadata의 `boost`에 활성화 시각, 목표, 추가 schedule 및 manifest hash를
기록한다. 원본 phase는 변경하지 않아 이전 피크는 기존 목표로 남는다.
추가 원본은 `<instance>/boost/`에 수집한다. 두 생성기의 카운터·최종 totals·
누락 구간은 각각 검증하고, 응답시간 histogram과 성공/실패/미발생 요청만 합산한다.
시간 분모는 한 번만 적용한다. CPU와 dispatch 품질은 생성기별로 검사하며
서버 Actuator와 GC는 주 생성기의 원본만 사용해 중복 집계하지 않는다.
추가 원본 누락을 주 생성기의 coverage로 채우지 않는다. 해당 phase는 비교를
보류하며 기존 임계치를 완화하지 않는다. 변경 전/후 피크는 구분해 해석한다.

이미지 arm64/amd64 확인, local tests 및 독립 리뷰와 server dry-run을 통과한 뒤
배포한다. 클라이언트 이미지는 Go 표준 라이브러리만 사용한다.
