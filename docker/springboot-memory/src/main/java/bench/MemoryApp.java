package bench;

import com.sun.management.GarbageCollectionNotificationInfo;
import java.lang.management.GarbageCollectorMXBean;
import java.lang.management.ManagementFactory;
import java.lang.management.MemoryUsage;
import java.lang.management.MemoryPoolMXBean;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.atomic.AtomicLong;
import java.util.stream.IntStream;
import javax.management.NotificationEmitter;
import javax.management.openmbean.CompositeData;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 메모리 부하 Spring Boot 벤치마크 앱.
 *
 * <p>시작 시 LIVE_SET_MB 만큼 캐시(엔트리당 ENTRY_KB)를 채워 힙 대부분을 살아 있는 데이터로 만든다.
 * 요청: /cache/get(읽기 — payload 일부를 읽어 메모리 접근) · /cache/put(교체 — 새 객체 할당, 이전 객체는
 * old 영역 가비지가 되어 G1 mixed GC를 유발), /process(운영형 요청 — 큰 본문을 WORK_KB 작업 객체로 펼쳐
 * HOLD_MS 동안 들고 있다가 응답: 하위 시스템이 느릴 때 처리 중 요청이 쌓여 힙이 차는 상황을 재현). /stats는 직전 reset 이후 구간의 GC 정지(통지 기준, 동시 단계 제외),
 * 프로세스 CPU 사용률, 힙 사용량을 보고한다 — 노드 샘플러 없이 JVM이 직접 측정.
 */
@SpringBootApplication
@RestController
public class MemoryApp {
    static final int ENTRY_KB = Integer.parseInt(System.getenv().getOrDefault("ENTRY_KB", "4"));
    static final long LIVE_SET_MB = Long.parseLong(System.getenv().getOrDefault("LIVE_SET_MB", "1024"));
    static final int N = (int) (LIVE_SET_MB * 1024 / ENTRY_KB);
    static final byte[] TEMPLATE = new byte[ENTRY_KB * 1024];
    static final Map<Integer, Entry> CACHE = new ConcurrentHashMap<>(N * 2);
    static volatile boolean ready = false;
    static final int WORK_KB = Integer.parseInt(System.getenv().getOrDefault("WORK_KB", "1024"));
    static final long HOLD_MS = Long.parseLong(System.getenv().getOrDefault("HOLD_MS", "1000"));
    // 요청 처리 중 금방 버려지는 객체(JSON 파싱·DTO 변환·직렬화 버퍼 흉내) — 처리량에 비례해 young GC 작업이 늘어난다.
    // 0이면 기존(1.2) 동작. 반은 대기 전(요청 파싱), 반은 대기 후(응답 직렬화)에 만든다.
    static final int GARBAGE_KB = Integer.parseInt(System.getenv().getOrDefault("GARBAGE_KB", "0"));
    static final AtomicLong inflight = new AtomicLong(), inflightPeak = new AtomicLong(), processed = new AtomicLong();

    record Entry(int id, long updated, byte[] payload) {}

    // ---- GC 통계 (구간) ----
    static final AtomicLong gcCount = new AtomicLong(), gcTotalUs = new AtomicLong(), gcMaxUs = new AtomicLong(),
            gcOver50 = new AtomicLong(), gcOver100 = new AtomicLong(), gcOver200 = new AtomicLong();
    static volatile long windowStartNs = System.nanoTime(), windowCpuNs = cpuNs();

    static long cpuNs() {
        return ((com.sun.management.OperatingSystemMXBean) ManagementFactory.getOperatingSystemMXBean()).getProcessCpuTime();
    }

    static void installGcListener() {
        for (GarbageCollectorMXBean gc : ManagementFactory.getGarbageCollectorMXBeans()) {
            ((NotificationEmitter) gc).addNotificationListener((n, h) -> {
                if (!GarbageCollectionNotificationInfo.GARBAGE_COLLECTION_NOTIFICATION.equals(n.getType())) return;
                var info = GarbageCollectionNotificationInfo.from((CompositeData) n.getUserData());
                // "G1 Concurrent GC"(JDK 20+)는 애플리케이션을 멈추지 않는 동시 단계 — 정지 통계에서 제외
                if (info.getGcName().contains("Concurrent")) return;
                long us = info.getGcInfo().getDuration() * 1000;
                gcCount.incrementAndGet();
                gcTotalUs.addAndGet(us);
                gcMaxUs.accumulateAndGet(us, Math::max);
                if (us > 50_000) gcOver50.incrementAndGet();
                if (us > 100_000) gcOver100.incrementAndGet();
                if (us > 200_000) gcOver200.incrementAndGet();
            }, null, null);
        }
    }

    public static void main(String[] args) {
        ThreadLocalRandom.current().nextBytes(TEMPLATE);
        installGcListener();
        new Thread(() -> {
            long t0 = System.nanoTime();
            IntStream.range(0, N).parallel().forEach(i -> CACHE.put(i, newEntry(i)));
            System.out.printf("PREFILL_DONE entries=%d live_set_mb=%d seconds=%.1f%n", N, LIVE_SET_MB, (System.nanoTime() - t0) / 1e9);
            ready = true;
        }, "prefill").start();
        SpringApplication.run(MemoryApp.class, args);
    }

    static Entry newEntry(int id) {
        byte[] p = TEMPLATE.clone();
        p[ThreadLocalRandom.current().nextInt(p.length)] ^= (byte) id;
        return new Entry(id, System.nanoTime(), p);
    }

    @GetMapping("/cache/get")
    public Map<String, Object> get(@RequestParam int k) {
        Entry e = CACHE.get(Math.floorMod(k, N));
        long sum = 0;
        if (e != null) for (int i = 0; i < e.payload().length; i += 256) sum += e.payload()[i];
        return Map.of("id", e == null ? -1 : e.id(), "updated", e == null ? 0 : e.updated(), "sum", sum);
    }

    @GetMapping("/cache/put")
    public Map<String, Object> put(@RequestParam int k) {
        int id = Math.floorMod(k, N);
        CACHE.put(id, newEntry(id));
        return Map.of("id", id, "ok", true);
    }

    /** 운영형 요청: 본문(예: 64KB)을 WORK_KB 크기의 작업 객체로 펼쳐 HOLD_MS 동안 유지(하위 시스템 대기) 후 요약 응답. */
    @PostMapping("/process")
    public Map<String, Object> process(@RequestBody byte[] body) throws InterruptedException {
        long now = inflight.incrementAndGet();
        inflightPeak.accumulateAndGet(now, Math::max);
        try {
            int chunk = Math.max(body.length, 1024);
            int n = Math.max(1, WORK_KB * 1024 / chunk);
            List<byte[]> work = new ArrayList<>(n);
            for (int i = 0; i < n; i++) {
                byte[] c = new byte[chunk];
                System.arraycopy(body, 0, c, 0, Math.min(body.length, chunk));
                c[i % chunk] ^= (byte) i;
                work.add(c);
            }
            // 요청이 세션/캐시를 갱신하는 운영 패턴: 상주 데이터 1항목 교체(이전 객체는 old 영역 가비지)
            int key = ThreadLocalRandom.current().nextInt(N);
            CACHE.put(key, newEntry(key));
            long g = churn(GARBAGE_KB / 2, body);
            Thread.sleep(HOLD_MS);
            g += churn(GARBAGE_KB - GARBAGE_KB / 2, body);
            long sum = g;
            for (byte[] c : work) sum += c[0] + c[c.length - 1];
            processed.incrementAndGet();
            return Map.of("chunks", n, "sum", sum, "inflight", now);
        } finally {
            inflight.decrementAndGet();
        }
    }

    /** kb만큼 짧게 사는 객체를 만들고 버린다(4KB 조각 + 문자열 변환). 결과 합을 돌려줘 JIT가 지우지 못하게 한다. */
    static long churn(int kb, byte[] body) {
        long acc = 0;
        for (int done = 0; done < kb; done += 4) {
            byte[] b = new byte[4096];
            System.arraycopy(body, 0, b, 0, Math.min(body.length, b.length));
            b[done % 4096] ^= (byte) done;
            String str = new String(b, 0, 256, java.nio.charset.StandardCharsets.ISO_8859_1);
            acc += str.hashCode() + b[4095];
        }
        return acc;
    }

    @GetMapping("/health")
    public ResponseEntity<String> health() {
        return ready ? ResponseEntity.ok("ok") : ResponseEntity.status(503).body("prefilling");
    }

    @GetMapping("/version")
    public String version() {
        return "java " + System.getProperty("java.version") + " " + System.getProperty("java.vm.vendor")
                + " springboot " + SpringApplication.class.getPackage().getImplementationVersion()
                + " gc " + ManagementFactory.getGarbageCollectorMXBeans().stream().map(GarbageCollectorMXBean::getName).toList()
                + " entries " + N + " entry_kb " + ENTRY_KB + " work_kb " + WORK_KB + " hold_ms " + HOLD_MS + " garbage_kb " + GARBAGE_KB
                + " heap_max_mb " + (Runtime.getRuntime().maxMemory() >> 20)
                + " virtual_threads " + Thread.currentThread().isVirtual()
                + " cpus " + Runtime.getRuntime().availableProcessors();
    }

    /** 직전 reset 이후 구간 통계. reset=1이면 반환 후 구간을 새로 시작한다. */
    @GetMapping("/stats")
    public Map<String, Object> stats(@RequestParam(defaultValue = "0") int reset) {
        long now = System.nanoTime(), cpu = cpuNs();
        double wallS = (now - windowStartNs) / 1e9;
        int cpus = Runtime.getRuntime().availableProcessors();
        MemoryUsage heap = ManagementFactory.getMemoryMXBean().getHeapMemoryUsage();
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("window_s", Math.round(wallS * 10) / 10.0);
        m.put("proc_cpu_pct", wallS > 0 ? Math.round((cpu - windowCpuNs) / 1e9 / wallS / cpus * 1000) / 10.0 : null);
        m.put("gc_pauses", gcCount.get());
        m.put("gc_pause_total_ms", gcTotalUs.get() / 1000);
        m.put("gc_pause_max_ms", gcMaxUs.get() / 1000);
        m.put("gc_pause_over50ms", gcOver50.get());
        m.put("gc_pause_over100ms", gcOver100.get());
        m.put("gc_pause_over200ms", gcOver200.get());
        m.put("heap_used_mb", heap.getUsed() >> 20);
        m.put("heap_max_mb", heap.getMax() >> 20);
        m.put("entries", CACHE.size());
        long oldAfterGc = 0;
        for (MemoryPoolMXBean pool : ManagementFactory.getMemoryPoolMXBeans()) {
            if (pool.getName().contains("Old Gen") && pool.getCollectionUsage() != null) oldAfterGc = pool.getCollectionUsage().getUsed() >> 20;
        }
        m.put("old_after_gc_mb", oldAfterGc);
        m.put("inflight_now", inflight.get());
        m.put("inflight_peak", inflightPeak.get());
        m.put("processed", processed.get());
        if (reset == 1) {
            gcCount.set(0); gcTotalUs.set(0); gcMaxUs.set(0); gcOver50.set(0); gcOver100.set(0); gcOver200.set(0);
            inflightPeak.set(inflight.get()); processed.set(0);
            windowStartNs = now; windowCpuNs = cpu;
        }
        return m;
    }
}
