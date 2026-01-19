#!/usr/bin/env python3
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from es_pricing import PRICING, get_generation, get_family, is_graviton

# Load data
df = pd.read_csv('/home/ec2-user/benchmark/results/elasticsearch/summary.csv')
df['price'] = df['instance'].map(PRICING)
df['gen'] = df['instance'].apply(get_generation)
df['family'] = df['instance'].apply(get_family)
df['arch'] = df['instance'].apply(lambda x: 'Graviton' if is_graviton(x) else 'Intel/AMD')

# Cost efficiency (lower cold_start is better, so invert)
df['cold_efficiency'] = (1000 / df['cold_start_avg']) / df['price']
df['bulk_efficiency'] = (1000 / df['bulk_index_avg']) / df['price']
df['search_efficiency'] = (1000 / df['search_match_all_avg']) / df['price']

# Sort by cold start
df_sorted = df.sort_values('cold_start_avg')

# Create charts
fig, axes = plt.subplots(3, 2, figsize=(16, 18))

# 1. Cold Start by Generation
for i, gen in enumerate([5, 6, 7, 8]):
    subset = df[df['gen'] == gen].sort_values('cold_start_avg')
    colors = ['#FF6B6B' if is_graviton(x) else '#4ECDC4' for x in subset['instance']]
    axes[0,0].barh(range(len(subset)), subset['cold_start_avg'], color=colors, alpha=0.8)
axes[0,0].set_title('Cold Start Time by Instance (ms) - Lower is Better')
axes[0,0].set_xlabel('Cold Start (ms)')

# Simplified: Top 15 Cold Start
top15 = df_sorted.head(15)
colors = ['#FF6B6B' if is_graviton(x) else '#4ECDC4' for x in top15['instance']]
axes[0,1].barh(top15['instance'], top15['cold_start_avg'], color=colors)
axes[0,1].set_title('Top 15 - Cold Start (ms)')
axes[0,1].invert_yaxis()

# 2. Bulk Index
df_bulk = df.sort_values('bulk_index_avg')
top15_bulk = df_bulk.head(15)
colors = ['#FF6B6B' if is_graviton(x) else '#4ECDC4' for x in top15_bulk['instance']]
axes[1,0].barh(top15_bulk['instance'], top15_bulk['bulk_index_avg'], color=colors)
axes[1,0].set_title('Top 15 - Bulk Index Time (ms)')
axes[1,0].invert_yaxis()

# 3. Search Performance
df_search = df.sort_values('search_match_all_avg')
top15_search = df_search.head(15)
colors = ['#FF6B6B' if is_graviton(x) else '#4ECDC4' for x in top15_search['instance']]
axes[1,1].barh(top15_search['instance'], top15_search['search_match_all_avg'], color=colors)
axes[1,1].set_title('Top 15 - Search Time (ms)')
axes[1,1].invert_yaxis()

# 4. Cost Efficiency - Cold Start
df_eff = df.sort_values('cold_efficiency', ascending=False)
top15_eff = df_eff.head(15)
colors = ['#FF6B6B' if is_graviton(x) else '#4ECDC4' for x in top15_eff['instance']]
axes[2,0].barh(top15_eff['instance'], top15_eff['cold_efficiency'], color=colors)
axes[2,0].set_title('Top 15 - Cost Efficiency (Cold Start)')
axes[2,0].invert_yaxis()

# 5. Generation Comparison
gen_stats = df.groupby('gen').agg({'cold_start_avg': 'mean', 'bulk_index_avg': 'mean'}).reset_index()
x = np.arange(len(gen_stats))
axes[2,1].bar(x - 0.2, gen_stats['cold_start_avg'], 0.4, label='Cold Start', color='#4ECDC4')
axes[2,1].bar(x + 0.2, gen_stats['bulk_index_avg']*10, 0.4, label='Bulk Index (x10)', color='#FF6B6B')
axes[2,1].set_xticks(x)
axes[2,1].set_xticklabels([f'Gen {g}' for g in gen_stats['gen']])
axes[2,1].set_title('Performance by Generation')
axes[2,1].legend()

plt.tight_layout()
plt.savefig('/home/ec2-user/benchmark/results/elasticsearch/charts.png', dpi=150)
print("Charts saved!")

# Generate markdown report
with open('/home/ec2-user/benchmark/results/elasticsearch/report_full.md', 'w') as f:
    f.write("# Elasticsearch Benchmark Report\n\n")
    f.write("## Overview\n")
    f.write("- **Instances Tested**: 51 (Intel 5-8세대, Graviton 2-4세대)\n")
    f.write("- **Test**: Elasticsearch 8.x Cold Start, Bulk Indexing, Search\n")
    f.write("- **Runs**: 5회 반복 측정, 평균값 사용\n\n")

    f.write("## Key Findings\n\n")
    best = df_sorted.iloc[0]
    f.write(f"### 🏆 Best Overall: **{best['instance']}**\n")
    f.write(f"- Cold Start: {best['cold_start_avg']:.0f}ms\n")
    f.write(f"- Price: ${best['price']}/hour\n\n")

    f.write("## All 51 Instances - Complete Results\n\n")
    f.write("| Rank | Instance | Cold Start (ms) | Bulk Index (ms) | Search (ms) | Price ($/hr) | Cost Efficiency |\n")
    f.write("|------|----------|-----------------|-----------------|-------------|--------------|----------------|\n")
    for i, row in df_sorted.iterrows():
        rank = list(df_sorted.index).index(i) + 1
        f.write(f"| {rank} | {row['instance']} | {row['cold_start_avg']:.0f} | {row['bulk_index_avg']:.0f} | {row['search_match_all_avg']:.1f} | ${row['price']:.3f} | {row['cold_efficiency']:.1f} |\n")

    f.write("\n## Generation Analysis\n\n")
    for gen in [5, 6, 7, 8]:
        subset = df[df['gen'] == gen]
        f.write(f"### Gen {gen}\n")
        f.write(f"- Avg Cold Start: {subset['cold_start_avg'].mean():.0f}ms\n")
        f.write(f"- Best: {subset.loc[subset['cold_start_avg'].idxmin(), 'instance']}\n\n")

print("Report saved!")
