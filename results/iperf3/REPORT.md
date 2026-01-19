# iperf3 Network Benchmark Report

**Date**: 2026-01-19  
**Instances**: 51 EC2 types (xlarge, 4 vCPU)  
**Runs**: 5 per instance (255 total)

## Top 10 by TCP Parallel Throughput

| Rank | Instance | TCP Parallel (Gbps) | TCP Single (Gbps) | Network |
|------|----------|---------------------|-------------------|---------|
| 1 | m6idn.xlarge | 29.80 | 9.53 | 25 Gbps |
| 2 | m6in.xlarge | 29.18 | 9.52 | 25 Gbps |
| 3 | c6in.xlarge | 28.64 | 8.61 | 25 Gbps |
| 4 | c5n.xlarge | 24.80 | 8.61 | 25 Gbps |
| 5 | m5zn.xlarge | 24.80 | 9.53 | 25 Gbps |
| 6 | r5dn.xlarge | 24.80 | 9.53 | 25 Gbps |
| 7 | r5n.xlarge | 23.42 | 5.87 | 25 Gbps |
| 8 | c6gn.xlarge | 23.38 | 5.88 | 25 Gbps |
| 9 | c6i.xlarge | 12.40 | 9.53 | 12.5 Gbps |
| 10 | c7i.xlarge | 12.40 | 5.39 | 12.5 Gbps |

## Performance by Generation

### Intel (5th-8th Gen)
- **5th Gen**: ~10 Gbps (c5, m5, r5)
- **6th Gen**: 12.5 Gbps standard, 25+ Gbps network-optimized (c6i, m6i, c6in)
- **7th Gen**: 12.5 Gbps (c7i, m7i, r7i)
- **8th Gen**: 12.5 Gbps (c8i, m8i, r8i)

### Graviton (2nd-4th Gen)
- **Graviton2**: 10 Gbps standard, 25 Gbps network-optimized (c6g, c6gn)
- **Graviton3**: 12.5 Gbps (c7g, m7g, r7g)
- **Graviton4**: 11-12.5 Gbps (c8g, m8g, r8g)

## Key Findings

1. **Network-optimized instances** (suffix: n, dn) deliver 2-3x throughput
2. **UDP jitter** consistently low (<0.03ms) across all instances
3. **Packet loss** minimal (<0.1%) for most instances
4. **TCP Single Stream** typically limited to ~9.5 Gbps

## Full Results
See: iperf3_summary.csv
