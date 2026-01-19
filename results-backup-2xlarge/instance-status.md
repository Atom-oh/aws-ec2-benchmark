# EC2 Instance Benchmark Status

## 서울 리전 (ap-northeast-2) 사용 가능 인스턴스: 51개

### 벤치마크 완료 현황

| 벤치마크 | 완료 | 누락 | 완료율 |
|----------|------|------|--------|
| sysbench (CPU) | 51 | 0 | 100% |
| Redis | 38 | 13 | 75% |
| Nginx | 30 | 21 | 59% |

### 인스턴스별 상세 현황

| Instance Type | Arch | sysbench | Redis | Nginx |
|---------------|------|----------|-------|-------|
| **Compute (c) - Intel 5th Gen** |
| c5.2xlarge | x86 | ✅ | ✅ | ✅ |
| c5a.2xlarge | x86 | ✅ | ✅ | ✅ |
| c5d.2xlarge | x86 | ✅ | ✅ | ✅ |
| c5n.2xlarge | x86 | ✅ | ✅ | ✅ |
| **Compute (c) - Intel 6th Gen** |
| c6i.2xlarge | x86 | ✅ | ✅ | ✅ |
| c6id.2xlarge | x86 | ✅ | ✅ | ✅ |
| c6in.2xlarge | x86 | ✅ | ✅ | ✅ |
| **Compute (c) - Intel 7th Gen** |
| c7i.2xlarge | x86 | ✅ | ✅ | ✅ |
| c7i-flex.2xlarge | x86 | ✅ | ✅ | ✅ |
| **Compute (c) - Intel 8th Gen** |
| c8i.2xlarge | x86 | ✅ | ✅ | ✅ |
| c8i-flex.2xlarge | x86 | ✅ | ✅ | ✅ |
| **Compute (c) - Graviton 2** |
| c6g.2xlarge | arm64 | ✅ | ✅ | ✅ |
| c6gd.2xlarge | arm64 | ✅ | ❌ | ❌ |
| c6gn.2xlarge | arm64 | ✅ | ❌ | ❌ |
| **Compute (c) - Graviton 3** |
| c7g.2xlarge | arm64 | ✅ | ✅ | ✅ |
| c7gd.2xlarge | arm64 | ✅ | ❌ | ❌ |
| **Compute (c) - Graviton 4** |
| c8g.2xlarge | arm64 | ✅ | ✅ | ✅ |
| **Memory (m) - Intel 5th Gen** |
| m5.2xlarge | x86 | ✅ | ✅ | ✅ |
| m5a.2xlarge | x86 | ✅ | ✅ | ✅ |
| m5ad.2xlarge | x86 | ✅ | ✅ | ✅ |
| m5d.2xlarge | x86 | ✅ | ✅ | ✅ |
| m5zn.2xlarge | x86 | ✅ | ✅ | ❌ |
| **Memory (m) - Intel 6th Gen** |
| m6i.2xlarge | x86 | ✅ | ✅ | ❌ |
| m6id.2xlarge | x86 | ✅ | ✅ | ❌ |
| m6idn.2xlarge | x86 | ✅ | ✅ | ❌ |
| m6in.2xlarge | x86 | ✅ | ✅ | ❌ |
| **Memory (m) - Intel 7th Gen** |
| m7i.2xlarge | x86 | ✅ | ✅ | ❌ |
| m7i-flex.2xlarge | x86 | ✅ | ❌ | ✅ |
| **Memory (m) - Intel 8th Gen** |
| m8i.2xlarge | x86 | ✅ | ❌ | ✅ |
| **Memory (m) - Graviton 2** |
| m6g.2xlarge | arm64 | ✅ | ✅ | ✅ |
| m6gd.2xlarge | arm64 | ✅ | ❌ | ❌ |
| **Memory (m) - Graviton 3** |
| m7g.2xlarge | arm64 | ✅ | ✅ | ✅ |
| m7gd.2xlarge | arm64 | ✅ | ❌ | ❌ |
| **Memory (m) - Graviton 4** |
| m8g.2xlarge | arm64 | ✅ | ✅ | ✅ |
| **Memory-Opt (r) - Intel 5th Gen** |
| r5.2xlarge | x86 | ✅ | ✅ | ❌ |
| r5a.2xlarge | x86 | ✅ | ✅ | ✅ |
| r5ad.2xlarge | x86 | ✅ | ✅ | ✅ |
| r5b.2xlarge | x86 | ✅ | ✅ | ❌ |
| r5d.2xlarge | x86 | ✅ | ✅ | ❌ |
| r5dn.2xlarge | x86 | ✅ | ❌ | ❌ |
| r5n.2xlarge | x86 | ✅ | ❌ | ❌ |
| **Memory-Opt (r) - Intel 6th Gen** |
| r6i.2xlarge | x86 | ✅ | ✅ | ❌ |
| r6id.2xlarge | x86 | ✅ | ✅ | ❌ |
| **Memory-Opt (r) - Intel 7th Gen** |
| r7i.2xlarge | x86 | ✅ | ✅ | ❌ |
| **Memory-Opt (r) - Intel 8th Gen** |
| r8i.2xlarge | x86 | ✅ | ❌ | ✅ |
| r8i-flex.2xlarge | x86 | ✅ | ❌ | ✅ |
| **Memory-Opt (r) - Graviton 2** |
| r6g.2xlarge | arm64 | ✅ | ✅ | ✅ |
| r6gd.2xlarge | arm64 | ✅ | ❌ | ❌ |
| **Memory-Opt (r) - Graviton 3** |
| r7g.2xlarge | arm64 | ✅ | ✅ | ✅ |
| r7gd.2xlarge | arm64 | ✅ | ❌ | ❌ |
| **Memory-Opt (r) - Graviton 4** |
| r8g.2xlarge | arm64 | ✅ | ✅ | ✅ |

### 누락된 인스턴스 요약

#### Redis 누락 (13개)
- Graviton variants: c6gd, c6gn, c7gd, m6gd, m7gd, r6gd, r7gd
- Intel variants: m7i-flex, m8i, r5dn, r5n, r8i, r8i-flex

#### Nginx 누락 (21개)
- Intel 5th: m5zn
- Intel 6th: m6i, m6id, m6idn, m6in, r6i, r6id
- Intel 7th: m7i, r7i
- Intel 5th r-series: r5, r5b, r5d, r5dn, r5n
- Graviton variants: c6gd, c6gn, c7gd, m6gd, m7gd, r6gd, r7gd

### 아키텍처별 분류

| Architecture | Total | Compute (c) | Memory (m) | Memory-Opt (r) |
|--------------|-------|-------------|------------|----------------|
| Intel 5th Gen | 16 | 4 | 5 | 7 |
| Intel 6th Gen | 9 | 3 | 4 | 2 |
| Intel 7th Gen | 5 | 2 | 2 | 1 |
| Intel 8th Gen | 4 | 2 | 1 | 2 |
| AMD (5th Gen) | 4 | 1 | 2 | 2 |
| Graviton 2 | 7 | 3 | 2 | 2 |
| Graviton 3 | 6 | 2 | 2 | 2 |
| Graviton 4 | 3 | 1 | 1 | 1 |
| **Total** | **51** | **17** | **17** | **17** |
