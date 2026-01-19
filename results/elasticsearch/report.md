# Elasticsearch Cold Start Benchmark Report
## AWS EC2 Instance Performance Comparison (5th~8th Generation)

**Author:** EKS Benchmark Team
**Date:** January 19, 2026
**Region:** ap-northeast-2 (Seoul)

---

## Interactive Charts & Korean Version

| Report | Description |
|--------|-------------|
| **[Interactive Charts (HTML)](./report-charts.html)** | Open in browser for interactive visualizations with Chart.js |
| **[Korean Report (한글)](./report-ko.md)** | 한글 버전 리포트 (Mermaid 차트 포함) |

---

## Executive Summary

This comprehensive benchmark analyzes Elasticsearch cold start performance across **51 EC2 instance types** spanning 4 generations of Intel/AMD and AWS Graviton processors. Our goal: determine which instances deliver the best performance and value for Elasticsearch workloads in production Kubernetes environments.

### Key Findings at a Glance

| Finding | Winner | Improvement |
|---------|--------|-------------|
| Fastest Cold Start | **m8g.xlarge** (8.9s) | 60% faster than slowest |
| Best Price-Performance | **c8g.xlarge** | $0.18/hr with 9.1s startup |
| Architecture Winner | **Graviton** | 9.1% faster cold start |
| Generation Upgrade Value | **Gen 8** | 40-47% faster than Gen 5 |

> **Bottom Line:** The newest isn't always the best for your wallet, but 8th generation Graviton instances offer an exceptional balance of performance and cost for Elasticsearch workloads.

---

## Table of Contents

1. [Test Methodology](#test-methodology)
2. [Test Environment](#test-environment)
3. [Complete Results](#complete-results)
4. [Performance Analysis](#performance-analysis)
5. [Price-Performance Analysis](#price-performance-analysis)
6. [Architecture Comparison](#architecture-comparison)
7. [Generation Analysis](#generation-analysis)
8. [Recommendations](#recommendations)

---

## Test Methodology

### Why This Benchmark Matters

Elasticsearch cold start time directly impacts:
- **Kubernetes pod scheduling** - How quickly can your search service recover?
- **Auto-scaling responsiveness** - Can you handle traffic spikes?
- **Cost optimization** - Spot instance interruption recovery time
- **Disaster recovery** - RTO (Recovery Time Objective) planning

### Test Design

```
┌─────────────────────────────────────────────────────────────┐
│                    BENCHMARK WORKFLOW                        │
├─────────────────────────────────────────────────────────────┤
│  1. Karpenter provisions fresh node (instance type X)       │
│  2. Pod scheduled with anti-affinity (isolated execution)   │
│  3. Elasticsearch 8.11.0 starts from cold state             │
│  4. Measure: Pod creation → HTTP ready (green status)       │
│  5. Execute indexing & search tests                         │
│  6. Repeat 5 times per instance type                        │
│  7. Calculate mean, std dev, remove outliers                │
└─────────────────────────────────────────────────────────────┘
```

### Metrics Collected

| Metric | Description | Unit | Direction |
|--------|-------------|------|-----------|
| Cold Start | Time from ES process start to HTTP ready | ms | ⬇️ Lower is better |
| Sequential Index | Index 100 docs one-by-one | ms | ⬇️ Lower is better |
| Bulk Index | Bulk index 1000 docs in single request | ms | ⬇️ Lower is better |
| Search (match_all) | Full scan query (10 iterations avg) | ms | ⬇️ Lower is better |
| Search (term) | Targeted term query (10 iterations avg) | ms | ⬇️ Lower is better |
| GC Time | Garbage collection during test | ms | ⬇️ Lower is better |

### Statistical Approach

- **Runs per instance:** 5 independent executions
- **Outlier handling:** Values > 2σ from mean flagged
- **Reported values:** Mean ± Standard Deviation
- **Confidence:** Results with Std Dev > 25% of mean noted

---

## Test Environment

### Infrastructure Setup

```yaml
Platform: Amazon EKS 1.31
Region: ap-northeast-2 (Seoul)
Node Provisioner: Karpenter 1.3.x
Container Runtime: containerd
```

### Instance Configuration

| Parameter | Value |
|-----------|-------|
| vCPU | 4 (xlarge size) |
| Instance Count | 51 types |
| Architecture | x86_64 (Intel/AMD), arm64 (Graviton) |
| Generations | 5th, 6th, 7th, 8th |
| Families | Compute (c), General (m), Memory (r) |

### Elasticsearch Configuration

```yaml
Version: 8.11.0
JVM Heap: 2GB initial, 4GB max
Discovery: single-node
Security: disabled (benchmark isolation)
Plugins: Default bundle (ML, SQL, etc.)
```

### Test Isolation Guarantees

```yaml
# Anti-affinity rule ensures each benchmark runs alone
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchExpressions:
            - key: benchmark
              operator: Exists
        topologyKey: "kubernetes.io/hostname"
```

**Why this matters:** Without isolation, noisy neighbors would invalidate results. Each test runs on a freshly provisioned, dedicated node.


---

## Complete Results

### Cold Start Performance (All 51 Instances)

| Rank | Instance | Arch | Gen | Cold Start (ms) | Std Dev | Bulk Index (ms) | Search Term (ms) | $/hr |
|------|----------|------|-----|-----------------|---------|-----------------|------------------|------|
| 1 | m8g.xlarge | arm64 | 8 | 8,908 | 402 | 224 | 8.2 | $0.221 |
| 2 | c8g.xlarge | arm64 | 8 | 9,124 | 413 | 230 | 9.0 | $0.180 |
| 3 | c8i.xlarge | x86_64 | 8 | 9,172 | 486 | 268 | 7.2 | $0.212 |
| 4 | r8g.xlarge | arm64 | 8 | 9,646 | 729 | 275 | 8.2 | $0.284 |
| 5 | c8i-flex.xlarge | x86_64 | 8 | 9,718 | 685 | 255 | 7.2 | $0.201 |
| 6 | m8i.xlarge | x86_64 | 8 | 9,913 | 729 | 272 | 7.2 | $0.260 |
| 7 | c7i-flex.xlarge | x86_64 | 7 | 9,956 | 685 | 272 | 9.8 | $0.192 |
| 8 | r8i-flex.xlarge | x86_64 | 8 | 10,107 | 742 | 284 | 8.8 | $0.318 |
| 9 | r7i.xlarge | x86_64 | 7 | 10,672 | 838 | 288 | 8.4 | $0.319 |
| 10 | r8i.xlarge | x86_64 | 8 | 10,813 | 2,252 | 286 | 9.2 | $0.335 |
| 11 | c7gd.xlarge | arm64 | 7 | 11,397 | 165 | 337 | 9.2 | $0.208 |
| 12 | m7i-flex.xlarge | x86_64 | 7 | 11,355 | 701 | 287 | 12.3 | $0.235 |
| 13 | r7gd.xlarge | arm64 | 7 | 11,610 | 349 | 348 | 11.0 | $0.327 |
| 14 | m7i.xlarge | x86_64 | 7 | 11,704 | 604 | 306 | 10.0 | $0.248 |
| 15 | m7gd.xlarge | arm64 | 7 | 11,891 | 626 | 339 | 10.4 | $0.263 |
| 16 | r7g.xlarge | arm64 | 7 | 12,180 | 710 | 333 | 11.0 | $0.258 |
| 17 | c7g.xlarge | arm64 | 7 | 12,471 | 523 | 333 | 11.3 | $0.163 |
| 18 | m7g.xlarge | arm64 | 7 | 12,476 | 1,026 | 337 | 11.0 | $0.201 |
| 19 | c7i.xlarge | x86_64 | 7 | 12,663 | 960 | 324 | 10.8 | $0.202 |
| 20 | m5zn.xlarge | x86_64 | 5 | 13,029 | 705 | 385 | 10.6 | $0.406 |
| 21 | c6id.xlarge | x86_64 | 6 | 13,099 | 790 | 332 | 9.6 | $0.231 |
| 22 | m6id.xlarge | x86_64 | 6 | 13,240 | 616 | 341 | 8.8 | $0.292 |
| 23 | r6i.xlarge | x86_64 | 6 | 13,354 | 514 | 350 | 10.2 | $0.304 |
| 24 | m6idn.xlarge | x86_64 | 6 | 13,424 | 611 | 336 | 9.2 | $0.386 |
| 25 | r6id.xlarge | x86_64 | 6 | 13,658 | 440 | 372 | 11.0 | $0.363 |
| 26 | c6in.xlarge | x86_64 | 6 | 13,840 | 983 | 345 | 10.6 | $0.256 |
| 27 | m6in.xlarge | x86_64 | 6 | 13,937 | 1,136 | 353 | 10.6 | $0.337 |
| 28 | m6i.xlarge | x86_64 | 6 | 14,010 | 953 | 341 | 10.0 | $0.236 |
| 29 | c6i.xlarge | x86_64 | 6 | 14,113 | 1,145 | 354 | 10.2 | $0.192 |
| 30 | c5a.xlarge | x86_64 | 5 | 14,948 | 907 | 386 | 14.0 | $0.172 |
| 31 | c5.xlarge | x86_64 | 5 | 15,275 | 617 | 394 | 12.4 | $0.192 |
| 32 | c5n.xlarge | x86_64 | 5 | 15,379 | 427 | 404 | 12.6 | $0.244 |
| 33 | m6gd.xlarge | arm64 | 6 | 15,645 | 760 | 450 | 13.2 | $0.222 |
| 34 | c6gn.xlarge | arm64 | 6 | 15,650 | 174 | 605 | 12.6 | $0.195 |
| 35 | c6g.xlarge | arm64 | 6 | 15,905 | 622 | 453 | 13.6 | $0.154 |
| 36 | r6g.xlarge | arm64 | 6 | 15,996 | 484 | 552 | 13.0 | $0.244 |
| 37 | r5d.xlarge | x86_64 | 5 | 16,094 | 726 | 430 | 11.6 | $0.346 |
| 38 | r6gd.xlarge | arm64 | 6 | 16,145 | 425 | 452 | 15.8 | $0.277 |
| 39 | c5d.xlarge | x86_64 | 5 | 16,262 | 1,873 | 477 | 12.7 | $0.220 |
| 40 | c6gd.xlarge | arm64 | 6 | 16,337 | 1,143 | 464 | 13.8 | $0.176 |
| 41 | r5n.xlarge | x86_64 | 5 | 16,615 | 806 | 433 | 12.2 | $0.356 |
| 42 | m6g.xlarge | arm64 | 6 | 16,697 | 942 | 501 | 14.5 | $0.188 |
| 43 | m5.xlarge | x86_64 | 5 | 16,738 | 1,337 | 419 | 12.3 | $0.236 |
| 44 | r5.xlarge | x86_64 | 5 | 16,785 | 495 | 434 | 14.0 | $0.304 |
| 45 | r5dn.xlarge | x86_64 | 5 | 17,113 | 712 | 420 | 12.4 | $0.398 |
| 46 | m5d.xlarge | x86_64 | 5 | 17,308 | 1,098 | 426 | 14.0 | $0.278 |
| 47 | r5b.xlarge | x86_64 | 5 | 17,530 | 399 | 403 | 12.0 | $0.356 |
| 48 | r5a.xlarge | x86_64 | 5 | 21,636 | 510 | 575 | 19.8 | $0.272 |
| 49 | m5a.xlarge | x86_64 | 5 | 22,288 | 1,134 | 537 | 19.6 | $0.212 |
| 50 | m5ad.xlarge | x86_64 | 5 | 22,207 | 701 | 522 | 20.5 | $0.254 |
| 51 | r5ad.xlarge | x86_64 | 5 | 22,273 | 286 | 569 | 18.6 | $0.316 |


---

## Performance Analysis

### Cold Start Time Distribution

```
Fastest ◀━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━▶ Slowest

 8.9s   m8g ████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
 9.1s   c8g █████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
 9.2s   c8i █████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
        ...
15.3s   c5  ███████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
16.7s   m5  █████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
22.3s   m5a █████████████████████████████████████████████████░  (slowest)

Range: 8,908ms - 22,288ms (2.5x difference)
```

### Key Observations

**1. Generation 8 Dominates Top 10**
The top 6 performers are all 8th generation instances. This is remarkable consistency across both architectures:
- Graviton4: m8g, c8g, r8g
- Intel Sapphire Rapids: c8i, c8i-flex, m8i

**2. AMD EPYC (5a series) Underperforms**
Instances with AMD EPYC processors (m5a, r5a, m5ad, r5ad) occupy the bottom 4 positions:
- 40-60% slower than 8th gen equivalents
- Even with lower prices, poor value proposition
- Likely due to older processor architecture and JVM optimization

**3. Surprising High Variance Cases**
| Instance | Std Dev | % of Mean | Analysis |
|----------|---------|-----------|----------|
| r8i.xlarge | 2,252ms | 21% | Inconsistent; avoid for latency-sensitive |
| c5d.xlarge | 1,873ms | 12% | Local NVMe doesn't help ES cold start |
| m5.xlarge | 1,337ms | 8% | Acceptable variance |

**4. flex Instances: Excellent Value**
"flex" variants offer near-identical performance at lower cost:
- c7i-flex: 9,956ms @ $0.19/hr (vs c7i: 12,663ms @ $0.20/hr) - **flex is faster!**
- c8i-flex: 9,718ms @ $0.20/hr (vs c8i: 9,172ms @ $0.21/hr)


---

## Price-Performance Analysis

### Cost Efficiency Score

We define **Cost Efficiency** as: `1,000,000 / (Cold Start ms × Hourly Price)`

Higher score = Better value (fast startup at low cost)

| Rank | Instance | Cold Start | $/hr | Efficiency Score | Value Tier |
|------|----------|------------|------|------------------|------------|
| 1 | **c8g.xlarge** | 9,124ms | $0.180 | 609 | ★★★ Best Value |
| 2 | c7i-flex.xlarge | 9,956ms | $0.192 | 523 | ★★★ Best Value |
| 3 | c7g.xlarge | 12,471ms | $0.163 | 491 | ★★★ Best Value |
| 4 | c8i-flex.xlarge | 9,718ms | $0.201 | 512 | ★★★ Best Value |
| 5 | m8g.xlarge | 8,908ms | $0.221 | 508 | ★★★ Best Value |
| 6 | c6g.xlarge | 15,905ms | $0.154 | 409 | ★★☆ Good Value |
| 7 | c8i.xlarge | 9,172ms | $0.212 | 515 | ★★★ Best Value |
| 8 | c6i.xlarge | 14,113ms | $0.192 | 369 | ★★☆ Good Value |
| 9 | m7g.xlarge | 12,476ms | $0.201 | 399 | ★★☆ Good Value |
| 10 | c6gd.xlarge | 16,337ms | $0.176 | 348 | ★★☆ Good Value |
| ... | | | | | |
| 47 | r5dn.xlarge | 17,113ms | $0.398 | 147 | ★☆☆ Poor Value |
| 48 | m5zn.xlarge | 13,029ms | $0.406 | 189 | ★☆☆ Poor Value |
| 49 | m6idn.xlarge | 13,424ms | $0.386 | 193 | ★☆☆ Poor Value |
| 50 | r5ad.xlarge | 22,273ms | $0.316 | 142 | ★☆☆ Poor Value |
| 51 | m5a.xlarge | 22,288ms | $0.212 | 212 | ★☆☆ Poor Value |

### Monthly Cost Projection (24/7 Operation)

| Instance | Hourly | Monthly (730hr) | Performance | Verdict |
|----------|--------|-----------------|-------------|---------|
| c6g.xlarge | $0.154 | **$112** | 15.9s | Budget pick |
| c8g.xlarge | $0.180 | **$131** | 9.1s | Best overall |
| c7i-flex.xlarge | $0.192 | **$140** | 10.0s | x86 budget |
| c8i.xlarge | $0.212 | **$155** | 9.2s | x86 premium |
| m8g.xlarge | $0.221 | **$161** | 8.9s | Fastest |
| r8g.xlarge | $0.284 | **$207** | 9.6s | Memory needs |

### Break-Even Analysis: When to Choose Premium Instances

**Scenario:** Your Elasticsearch cluster restarts 100 times/month (spot interruptions, rolling updates)

| Instance | Restart Time | Monthly Restarts | Total Downtime | Cost Impact |
|----------|-------------|------------------|----------------|-------------|
| c5.xlarge | 15.3s | 100 | 25.5 min | Baseline |
| c8g.xlarge | 9.1s | 100 | 15.2 min | -10.3 min |
| m8g.xlarge | 8.9s | 100 | 14.8 min | -10.7 min |

**Insight:** If downtime costs > $19/month ($0.63/minute), c8g pays for itself vs c5.


---

## Architecture Comparison: Intel/AMD vs Graviton

### Head-to-Head: Same Generation, Same Family

| Gen | Family | Intel/AMD | Time | Graviton | Time | Winner | Delta |
|-----|--------|-----------|------|----------|------|--------|-------|
| 8 | Compute | c8i | 9,172ms | **c8g** | 9,124ms | Graviton | -0.5% |
| 8 | General | m8i | 9,913ms | **m8g** | 8,908ms | Graviton | -10.1% |
| 8 | Memory | r8i | 10,813ms | **r8g** | 9,646ms | Graviton | -10.8% |
| 7 | Compute | c7i | 12,663ms | **c7g** | 12,471ms | Graviton | -1.5% |
| 7 | General | m7i | 11,704ms | m7g | 12,476ms | **Intel** | +6.6% |
| 6 | Compute | **c6i** | 14,113ms | c6g | 15,905ms | Intel | -11.3% |
| 6 | General | **m6i** | 14,010ms | m6g | 16,697ms | Intel | -16.1% |

### Architecture Summary

```
┌────────────────────────────────────────────────────────────────┐
│                 ARCHITECTURE PERFORMANCE TREND                  │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  Gen 5-6:  Intel/AMD leads (Graviton2 early optimization)      │
│            Intel wins by 11-16%                                │
│                                                                │
│  Gen 7:    Mixed results (Graviton3 catches up)                │
│            Depends on workload type                            │
│                                                                │
│  Gen 8:    Graviton4 leads (new architecture benefits)         │
│            Graviton wins by 0.5-11%                            │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### Why Graviton4 Excels for Elasticsearch

1. **Improved Branch Prediction** - JVM startup involves heavy class loading
2. **Better Memory Bandwidth** - ES indexes are memory-intensive
3. **Optimized JIT Compilation** - OpenJDK 21 has mature ARM64 support
4. **Lower Memory Latency** - Critical for Lucene segment operations

### Price Advantage: Graviton vs Intel

| Generation | Intel Price | Graviton Price | Savings |
|------------|-------------|----------------|---------|
| Gen 8 (c8) | $0.212/hr | $0.180/hr | **15%** |
| Gen 7 (c7) | $0.202/hr | $0.163/hr | **19%** |
| Gen 6 (c6) | $0.192/hr | $0.154/hr | **20%** |

> **Verdict:** Graviton4 delivers both better performance AND 15-20% cost savings.


---

## Generation Analysis: Is Newer Always Better?

### Generation-over-Generation Improvement

#### Intel/AMD (x86_64) Progression

| Transition | Old → New | Cold Start Δ | Improvement |
|------------|-----------|--------------|-------------|
| Gen 5 → 6 | c5 → c6i | 15,275 → 14,113ms | **7.6%** |
| Gen 6 → 7 | c6i → c7i | 14,113 → 12,663ms | **10.3%** |
| Gen 7 → 8 | c7i → c8i | 12,663 → 9,172ms | **27.6%** |
| **Total** | Gen 5 → 8 | 15,275 → 9,172ms | **40.0%** |

#### Graviton (arm64) Progression

| Transition | Old → New | Cold Start Δ | Improvement |
|------------|-----------|--------------|-------------|
| Gen 6 → 7 | c6g → c7g | 15,905 → 12,471ms | **21.6%** |
| Gen 7 → 8 | c7g → c8g | 12,471 → 9,124ms | **26.8%** |
| **Total** | Gen 6 → 8 | 15,905 → 9,124ms | **42.6%** |

### Visualizing Generational Progress

```
Cold Start Time (ms) - Compute Optimized Family

Gen 5 (Intel)   ████████████████████████████████████  15,275ms
Gen 6 (Intel)   █████████████████████████████████     14,113ms
Gen 6 (Graviton)████████████████████████████████████  15,905ms
Gen 7 (Intel)   ██████████████████████████████        12,663ms
Gen 7 (Graviton)█████████████████████████████         12,471ms
Gen 8 (Intel)   ███████████████████                    9,172ms
Gen 8 (Graviton)██████████████████                     9,124ms
                0        5000      10000     15000     20000
```

### The "Newer is Better" Myth: Debunked

**Claim:** "Always use the latest generation for best performance"

**Reality:** It depends on your architecture choice and workload.

| Scenario | Best Choice | Why |
|----------|-------------|-----|
| Pure performance | m8g.xlarge | Fastest cold start (8.9s) |
| Best value | c8g.xlarge | Great perf + low cost |
| x86 required | c8i.xlarge | Best Intel option |
| Budget constrained | c6g.xlarge | Cheapest ($0.154/hr) |
| Memory-heavy | r8g.xlarge | 32GB + fast startup |

### Upgrade ROI Calculator

**If upgrading from c5.xlarge → c8g.xlarge:**

| Metric | c5.xlarge | c8g.xlarge | Change |
|--------|-----------|------------|--------|
| Cold Start | 15,275ms | 9,124ms | -40% |
| Hourly Cost | $0.192 | $0.180 | -6% |
| Monthly Cost | $140 | $131 | -$9 |
| Performance/$ | 343 | 609 | +77% |

**Result:** Faster AND cheaper. Upgrade is a no-brainer.


---

## Recommendations

### By Use Case

#### Production Elasticsearch Clusters

| Priority | Recommended | Alternative | Notes |
|----------|-------------|-------------|-------|
| **Performance** | m8g.xlarge | c8i.xlarge | For latency-critical search |
| **Value** | c8g.xlarge | c7i-flex.xlarge | Best $/performance |
| **Budget** | c6g.xlarge | c5a.xlarge | Minimum viable option |
| **Memory-heavy** | r8g.xlarge | r7i.xlarge | Large index workloads |

#### Kubernetes/EKS Deployments

```yaml
# Recommended Karpenter NodePool for Elasticsearch
apiVersion: karpenter.sh/v1
kind: NodePool
spec:
  template:
    spec:
      requirements:
        - key: node.kubernetes.io/instance-type
          operator: In
          values:
            # Tier 1: Best Performance
            - m8g.xlarge
            - c8g.xlarge
            - c8i.xlarge
            # Tier 2: Good Value
            - c7i-flex.xlarge
            - c7g.xlarge
            - m7g.xlarge
            # Tier 3: Budget
            - c6g.xlarge
            - c6i.xlarge
```

#### Spot Instance Strategy

For spot-tolerant workloads, diversify across:
- **Primary:** c8g.xlarge, m8g.xlarge (Graviton - often more available)
- **Fallback:** c7i-flex.xlarge, c8i-flex.xlarge (flex instances)
- **Avoid:** m5a, r5a series (poor cold start = longer recovery)

### Instances to Avoid

| Instance | Reason | Better Alternative |
|----------|--------|-------------------|
| m5a.xlarge | 2.5x slower cold start | m8g.xlarge (+6% cost, 60% faster) |
| r5ad.xlarge | Slowest r-family | r8g.xlarge (57% faster) |
| m5zn.xlarge | High cost ($0.41/hr), mediocre perf | m8i.xlarge (36% cheaper, 24% faster) |
| r5dn.xlarge | Premium price, mid-tier perf | r8i-flex.xlarge (20% cheaper, 41% faster) |

---

## Conclusion

### The Definitive Answer

**Q: Which EC2 instance should I use for Elasticsearch?**

**A: c8g.xlarge** - It offers:
- Top 3 cold start performance (9.1 seconds)
- Best price-performance ratio (Efficiency Score: 609)
- 15% cheaper than Intel equivalent
- Mature ARM64 JVM support in ES 8.x

### Key Takeaways

1. **Generation 8 is transformational** - 40%+ improvement over Gen 5
2. **Graviton4 has arrived** - Now matches or beats Intel in JVM workloads
3. **flex instances surprise** - Often faster than standard variants
4. **AMD EPYC disappoints** - m5a/r5a series should be avoided
5. **Price ≠ Performance** - Expensive doesn't mean fast

### Future Work

- Benchmark with larger heap sizes (8GB, 16GB)
- Multi-node cluster formation time
- Index/search throughput under load
- Graviton vs Intel with native ES builds

---

## Appendix

### A. Raw Data Files

- `summary.csv` - Complete metrics for all 51 instances
- `prices.csv` - AWS pricing data (ap-northeast-2)
- `*/run[1-5].log` - Individual test run logs

### B. Reproduction Steps

```bash
# Clone benchmark repo
git clone <repo-url>
cd benchmark

# Deploy Karpenter NodePool
kubectl apply -f karpenter/nodepool-4vcpu.yaml

# Run single instance test
INSTANCE="c8g.xlarge"
sed -e "s/INSTANCE_TYPE/${INSTANCE}/g" \
    -e "s/INSTANCE_SAFE/$(echo $INSTANCE | tr '.' '-')/g" \
    -e "s/ARCH/arm64/g" \
    benchmarks/elasticsearch/elasticsearch-coldstart.yaml | kubectl apply -f -

# Collect results
kubectl logs -n benchmark <pod-name> > results/elasticsearch/${INSTANCE}.log
```

### C. Statistical Notes

- All times in milliseconds (ms)
- N=5 runs per instance type
- Std Dev reported for variance assessment
- Tests executed January 15-19, 2026

---

*Report generated by EKS Benchmark Automation*
*Data collected: January 2026 | Region: ap-northeast-2 (Seoul)*
