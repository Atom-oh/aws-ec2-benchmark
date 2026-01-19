# EC2 Instance Benchmark Results (2xlarge / 8 vCPU)

## Test Environment
- **EKS Cluster**: demo-hirehub-eks (ap-northeast-2)
- **Instance Size**: 2xlarge (8 vCPU)
- **Karpenter NodePool**: benchmark (dedicated taints)
- **Test Date**: 2026-01-15

## Instance Categories
| Category | Families | Tested |
|----------|----------|--------|
| Intel | c5~c8i, m5~m7i, r5~r7i (+flex, d, n variants) | 45+ |
| AMD | c5a~c7a, m5a~m7a, r5a~r7a | 11 |
| Graviton (ARM) | c6g~c8g, m6g~m8g, r6g~r8g | 17 |

---

## 1. CPU Benchmark (sysbench)
**Test**: Prime calculation, 20000 prime limit, 60s duration

### Top 10 Multi-thread Performance
| Rank | Instance | CPU | Events/sec |
|------|----------|-----|------------|
| 1 | c8g.2xlarge | Graviton 4 | 9,747 |
| 2 | m8g.2xlarge | Graviton 4 | 9,735 |
| 3 | r8g.2xlarge | Graviton 4 | 9,719 |
| 4 | m7g.2xlarge | Graviton 3 | 9,141 |
| 5 | c7g.2xlarge | Graviton 3 | 9,034 |
| 6 | m7gd.2xlarge | Graviton 3 | 8,891 |
| 7 | r7g.2xlarge | Graviton 3 | 8,857 |
| 8 | c7gd.2xlarge | Graviton 3 | 8,856 |
| 9 | r7gd.2xlarge | Graviton 3 | 8,849 |
| 10 | c6g.2xlarge | Graviton 2 | 8,562 |

### Top 5 Single-thread Performance
| Rank | Instance | CPU | Events/sec |
|------|----------|-----|------------|
| 1 | c8i-flex.2xlarge | Xeon 6975P-C | 1,286 |
| 2 | r8g.2xlarge | Graviton 4 | 1,251 |
| 3 | c8g.2xlarge | Graviton 4 | 1,251 |
| 4 | m8g.2xlarge | Graviton 4 | 1,250 |
| 5 | r7i.2xlarge | Xeon 8488C | 1,222 |

---

## 2. Redis Benchmark
**Test**: memtier_benchmark (Intel/AMD) / redis-benchmark (Graviton)

### Top 10 SET Performance
| Rank | Instance | SET (ops/sec) | Latency p50 |
|------|----------|---------------|-------------|
| 1 | c8i-flex.2xlarge | 218,591 | 0.88ms |
| 2 | c8i.2xlarge | 216,493 | 0.90ms |
| 3 | r7i.2xlarge | 212,831 | 0.93ms |
| 4 | c7i.2xlarge | 205,648 | 0.96ms |
| 5 | c6in.2xlarge | 200,008 | 0.88ms |
| 6 | c6i.2xlarge | 198,631 | 0.91ms |
| 7 | c6id.2xlarge | 197,037 | 0.91ms |
| 8 | m6i.2xlarge | 195,085 | 0.93ms |
| 9 | m6in.2xlarge | 193,912 | 0.92ms |
| 10 | r8g.2xlarge | 156,986 | 0.17ms |

---

## 3. Nginx Benchmark (wrk)
**Test**: HTTP requests, 8 threads, 400 connections, 30s duration

### Top 10 Performance
| Rank | Instance | Requests/sec | Latency Avg |
|------|----------|--------------|-------------|
| 1 | r8g.2xlarge | 279,824 | 1.47ms |
| 2 | m8g.2xlarge | 273,146 | 1.62ms |
| 3 | c8g.2xlarge | 255,805 | 1.75ms |
| 4 | c8i-flex.2xlarge | 242,153 | 1.81ms |
| 5 | c8i.2xlarge | 237,829 | 1.97ms |
| 6 | m7g.2xlarge | 221,792 | 1.83ms |
| 7 | r7g.2xlarge | 219,145 | 1.85ms |
| 8 | c7g.2xlarge | 209,328 | 2.05ms |
| 9 | c7i-flex.2xlarge | 190,062 | 2.92ms |
| 10 | c7i.2xlarge | 189,975 | 2.33ms |

---

## 4. JVM Startup Time (Java 21)
**Test**: javac + java with simple HTTP server, 5 runs average

### Top 10 Performance (Lower is Better)
| Rank | Instance | Architecture | Avg Time (ms) |
|------|----------|--------------|---------------|
| 1 | r8g.2xlarge | Graviton 4 | 368 |
| 2 | c8i.2xlarge | Intel 8th | 400 |
| 3 | c8g.2xlarge | Graviton 4 | 404 |
| 4 | m8g.2xlarge | Graviton 4 | 407 |
| 5 | c8i-flex.2xlarge | Intel 8th | 452 |
| 6 | m7g.2xlarge | Graviton 3 | 515 |
| 7 | c6i.2xlarge | Intel 6th | 518 |
| 8 | r7g.2xlarge | Graviton 3 | 527 |
| 9 | c7i.2xlarge | Intel 7th | 544 |
| 10 | c7g.2xlarge | Graviton 3 | 550 |

---

## Key Findings

### 🏆 Overall Winners
| Workload | Best Instance | Performance |
|----------|--------------|-------------|
| CPU Multi-thread | c8g.2xlarge (Graviton 4) | 9,747 events/sec |
| CPU Single-thread | c8i-flex.2xlarge (Intel) | 1,286 events/sec |
| Redis SET | c8i-flex.2xlarge (Intel) | 218,591 ops/sec |
| Nginx HTTP | r8g.2xlarge (Graviton 4) | 279,824 req/sec |
| JVM Startup | r8g.2xlarge (Graviton 4) | 368 ms |

### Graviton vs Intel Analysis
| Metric | Graviton 4 | Intel 8th Gen | Winner |
|--------|-----------|---------------|--------|
| CPU Multi-thread | 9,747 | 5,363 | Graviton (+82%) |
| CPU Single-thread | 1,251 | 1,286 | Intel (+3%) |
| Redis SET | 157k | 219k | Intel (+39%) |
| Nginx | 280k | 242k | Graviton (+16%) |

### Recommendations
- **Compute-intensive (multi-thread)**: Graviton 4 (c8g/m8g/r8g)
- **Single-thread sensitive**: Intel c8i-flex
- **Redis/In-memory workloads**: Intel c8i-flex, r7i
- **Web servers (Nginx)**: Graviton 4 (r8g, m8g)
- **Cost-optimized**: Graviton typically 20-40% cheaper

---

## Files Generated
- `sysbench-summary.csv` - CPU benchmark (45 instances)
- `redis-summary.csv` - Redis benchmark (38 instances)
- `nginx-summary.csv` - Nginx benchmark (26 instances)
- `springboot-summary.csv` - JVM startup benchmark (14 instances)

## Charts Generated
- `chart_cpu_multithread.png` - CPU multi-thread performance
- `chart_cpu_singlethread.png` - CPU single-thread performance (Top 20)
- `chart_redis_set.png` - Redis SET operations
- `chart_nginx.png` - Nginx HTTP requests/sec
- `chart_springboot.png` - JVM startup time
- `chart_summary.png` - Architecture comparison summary
