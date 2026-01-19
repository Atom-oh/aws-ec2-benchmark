#!/usr/bin/env python3
"""EC2 Instance Benchmark Report Generator with Charts"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import os

# Set style
plt.style.use('seaborn-v0_8-whitegrid')
plt.rcParams['figure.figsize'] = (14, 8)
plt.rcParams['font.size'] = 10

RESULTS_DIR = '/home/ec2-user/benchmark/results'

def get_arch_color(instance):
    """Return color based on architecture"""
    if 'g.' in instance or 'gd.' in instance or 'gn.' in instance:
        gen = instance.split('.')[0][-2:]
        if '8g' in gen: return '#1a5f2a'  # Graviton 4 - dark green
        if '7g' in gen: return '#2e8b57'  # Graviton 3 - green
        if '6g' in gen: return '#90ee90'  # Graviton 2 - light green
        return '#98fb98'
    elif 'a.' in instance or 'ad.' in instance:
        return '#e74c3c'  # AMD - red
    else:
        gen = instance.split('.')[0]
        if '8i' in gen: return '#1a237e'  # Intel 8th - dark blue
        if '7i' in gen: return '#303f9f'  # Intel 7th - blue
        if '6i' in gen: return '#5c6bc0'  # Intel 6th - medium blue
        if '5' in gen: return '#9fa8da'   # Intel 5th - light blue
        return '#7986cb'

def get_family(instance):
    """Extract family (c, m, r) from instance type"""
    return instance[0]

def load_data():
    """Load all benchmark CSV files"""
    data = {}
    data['cpu'] = pd.read_csv(f'{RESULTS_DIR}/sysbench-summary.csv')
    data['redis'] = pd.read_csv(f'{RESULTS_DIR}/redis-summary.csv')
    data['nginx'] = pd.read_csv(f'{RESULTS_DIR}/nginx-summary.csv')
    data['springboot'] = pd.read_csv(f'{RESULTS_DIR}/springboot-summary.csv')
    return data

def plot_cpu_multithread(df):
    """Plot CPU multi-thread benchmark"""
    df_sorted = df.sort_values('Multi-thread (events/sec)', ascending=True)

    fig, ax = plt.subplots(figsize=(14, 12))
    colors = [get_arch_color(inst) for inst in df_sorted['Instance Type']]

    bars = ax.barh(df_sorted['Instance Type'], df_sorted['Multi-thread (events/sec)'], color=colors)

    ax.set_xlabel('Events/sec (higher is better)', fontsize=12)
    ax.set_title('CPU Benchmark - Multi-thread Performance (sysbench)\n8 vCPU, 60s duration', fontsize=14, fontweight='bold')

    # Add value labels
    for bar, val in zip(bars, df_sorted['Multi-thread (events/sec)']):
        ax.text(val + 100, bar.get_y() + bar.get_height()/2, f'{val:,.0f}', va='center', fontsize=8)

    # Legend
    legend_elements = [
        mpatches.Patch(color='#1a5f2a', label='Graviton 4'),
        mpatches.Patch(color='#2e8b57', label='Graviton 3'),
        mpatches.Patch(color='#90ee90', label='Graviton 2'),
        mpatches.Patch(color='#1a237e', label='Intel 8th Gen'),
        mpatches.Patch(color='#303f9f', label='Intel 7th Gen'),
        mpatches.Patch(color='#5c6bc0', label='Intel 6th Gen'),
        mpatches.Patch(color='#9fa8da', label='Intel 5th Gen'),
        mpatches.Patch(color='#e74c3c', label='AMD'),
    ]
    ax.legend(handles=legend_elements, loc='lower right')

    plt.tight_layout()
    plt.savefig(f'{RESULTS_DIR}/chart_cpu_multithread.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("Generated: chart_cpu_multithread.png")

def plot_cpu_singlethread(df):
    """Plot CPU single-thread benchmark - Top 20"""
    df_sorted = df.sort_values('Single-thread (events/sec)', ascending=True).tail(20)

    fig, ax = plt.subplots(figsize=(12, 8))
    colors = [get_arch_color(inst) for inst in df_sorted['Instance Type']]

    bars = ax.barh(df_sorted['Instance Type'], df_sorted['Single-thread (events/sec)'], color=colors)

    ax.set_xlabel('Events/sec (higher is better)', fontsize=12)
    ax.set_title('CPU Benchmark - Single-thread Performance (Top 20)\nsysbench prime calculation', fontsize=14, fontweight='bold')

    for bar, val in zip(bars, df_sorted['Single-thread (events/sec)']):
        ax.text(val + 10, bar.get_y() + bar.get_height()/2, f'{val:,.0f}', va='center', fontsize=9)

    plt.tight_layout()
    plt.savefig(f'{RESULTS_DIR}/chart_cpu_singlethread.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("Generated: chart_cpu_singlethread.png")

def plot_redis(df):
    """Plot Redis SET performance"""
    df_sorted = df.sort_values('SET (ops/sec)', ascending=True)

    fig, ax = plt.subplots(figsize=(14, 10))
    colors = [get_arch_color(inst) for inst in df_sorted['Instance Type']]

    bars = ax.barh(df_sorted['Instance Type'], df_sorted['SET (ops/sec)'], color=colors)

    ax.set_xlabel('Operations/sec (higher is better)', fontsize=12)
    ax.set_title('Redis Benchmark - SET Performance\nmemtier_benchmark (Intel/AMD) / redis-benchmark (Graviton)', fontsize=14, fontweight='bold')

    for bar, val in zip(bars, df_sorted['SET (ops/sec)']):
        ax.text(val + 2000, bar.get_y() + bar.get_height()/2, f'{val:,.0f}', va='center', fontsize=8)

    plt.tight_layout()
    plt.savefig(f'{RESULTS_DIR}/chart_redis_set.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("Generated: chart_redis_set.png")

def plot_nginx(df):
    """Plot Nginx HTTP performance"""
    df_sorted = df.sort_values('8t/400c (req/sec)', ascending=True)

    fig, ax = plt.subplots(figsize=(14, 8))
    colors = [get_arch_color(inst) for inst in df_sorted['Instance Type']]

    bars = ax.barh(df_sorted['Instance Type'], df_sorted['8t/400c (req/sec)'], color=colors)

    ax.set_xlabel('Requests/sec (higher is better)', fontsize=12)
    ax.set_title('Nginx Benchmark - HTTP Performance\nwrk: 8 threads, 400 connections, 30s', fontsize=14, fontweight='bold')

    for bar, val in zip(bars, df_sorted['8t/400c (req/sec)']):
        ax.text(val + 2000, bar.get_y() + bar.get_height()/2, f'{val:,.0f}', va='center', fontsize=9)

    plt.tight_layout()
    plt.savefig(f'{RESULTS_DIR}/chart_nginx.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("Generated: chart_nginx.png")

def plot_springboot(df):
    """Plot Spring Boot/JVM startup time"""
    df_sorted = df.sort_values('Avg Time (ms)', ascending=False)

    fig, ax = plt.subplots(figsize=(12, 6))
    colors = [get_arch_color(inst) for inst in df_sorted['Instance Type']]

    bars = ax.barh(df_sorted['Instance Type'], df_sorted['Avg Time (ms)'], color=colors)

    ax.set_xlabel('Startup Time (ms) - lower is better', fontsize=12)
    ax.set_title('JVM Startup Time Benchmark\nJava 21 + Simple HTTP Server (5 runs average)', fontsize=14, fontweight='bold')

    for bar, val in zip(bars, df_sorted['Avg Time (ms)']):
        ax.text(val + 10, bar.get_y() + bar.get_height()/2, f'{val:.0f}ms', va='center', fontsize=9)

    # Add legend
    legend_elements = [
        mpatches.Patch(color='#1a5f2a', label='Graviton 4'),
        mpatches.Patch(color='#2e8b57', label='Graviton 3'),
        mpatches.Patch(color='#90ee90', label='Graviton 2'),
        mpatches.Patch(color='#1a237e', label='Intel 8th Gen'),
        mpatches.Patch(color='#303f9f', label='Intel 7th Gen'),
        mpatches.Patch(color='#5c6bc0', label='Intel 6th Gen'),
        mpatches.Patch(color='#9fa8da', label='Intel 5th Gen'),
    ]
    ax.legend(handles=legend_elements, loc='lower right')

    plt.tight_layout()
    plt.savefig(f'{RESULTS_DIR}/chart_springboot.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("Generated: chart_springboot.png")

def plot_comparison(data):
    """Plot architecture comparison summary"""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # Prepare comparison data
    cpu_df = data['cpu']
    redis_df = data['redis']
    nginx_df = data['nginx']

    # CPU Multi-thread by generation
    ax1 = axes[0, 0]
    generations = {
        'Graviton 4': cpu_df[cpu_df['Instance Type'].str.contains('8g')]['Multi-thread (events/sec)'].max(),
        'Graviton 3': cpu_df[cpu_df['Instance Type'].str.contains('7g')]['Multi-thread (events/sec)'].max(),
        'Graviton 2': cpu_df[cpu_df['Instance Type'].str.contains('6g')]['Multi-thread (events/sec)'].max(),
        'Intel 8th': cpu_df[cpu_df['Instance Type'].str.contains('8i')]['Multi-thread (events/sec)'].max(),
        'Intel 7th': cpu_df[cpu_df['Instance Type'].str.contains('7i')]['Multi-thread (events/sec)'].max(),
        'Intel 6th': cpu_df[cpu_df['Instance Type'].str.contains('6i')]['Multi-thread (events/sec)'].max(),
        'Intel 5th': cpu_df[cpu_df['Instance Type'].str.contains('c5\\.|m5\\.|r5\\.', regex=True)]['Multi-thread (events/sec)'].max(),
        'AMD': cpu_df[cpu_df['Instance Type'].str.contains('a\\.')]['Multi-thread (events/sec)'].max(),
    }
    colors = ['#1a5f2a', '#2e8b57', '#90ee90', '#1a237e', '#303f9f', '#5c6bc0', '#9fa8da', '#e74c3c']
    ax1.bar(generations.keys(), generations.values(), color=colors)
    ax1.set_ylabel('Events/sec')
    ax1.set_title('CPU Multi-thread (Best per Generation)')
    ax1.tick_params(axis='x', rotation=45)

    # Redis by architecture
    ax2 = axes[0, 1]
    redis_arch = {
        'Intel': redis_df[~redis_df['Instance Type'].str.contains('g\\.|a\\.')]['SET (ops/sec)'].max(),
        'AMD': redis_df[redis_df['Instance Type'].str.contains('a\\.')]['SET (ops/sec)'].max(),
        'Graviton': redis_df[redis_df['Instance Type'].str.contains('g\\.')]['SET (ops/sec)'].max(),
    }
    ax2.bar(redis_arch.keys(), redis_arch.values(), color=['#303f9f', '#e74c3c', '#2e8b57'])
    ax2.set_ylabel('Operations/sec')
    ax2.set_title('Redis SET (Best per Architecture)')

    # Nginx by architecture
    ax3 = axes[1, 0]
    nginx_arch = {
        'Intel': nginx_df[~nginx_df['Instance Type'].str.contains('g\\.|a\\.')]['8t/400c (req/sec)'].max(),
        'AMD': nginx_df[nginx_df['Instance Type'].str.contains('a\\.')]['8t/400c (req/sec)'].max(),
        'Graviton': nginx_df[nginx_df['Instance Type'].str.contains('g\\.')]['8t/400c (req/sec)'].max(),
    }
    ax3.bar(nginx_arch.keys(), nginx_arch.values(), color=['#303f9f', '#e74c3c', '#2e8b57'])
    ax3.set_ylabel('Requests/sec')
    ax3.set_title('Nginx HTTP (Best per Architecture)')

    # Top instances overall
    ax4 = axes[1, 1]
    top_data = {
        'CPU MT\nc8g.2xl': cpu_df.loc[cpu_df['Multi-thread (events/sec)'].idxmax(), 'Multi-thread (events/sec)'],
        'CPU ST\nc8i-flex': cpu_df.loc[cpu_df['Single-thread (events/sec)'].idxmax(), 'Single-thread (events/sec)'],
    }
    # Normalize for display
    ax4.text(0.5, 0.8, 'Overall Winners', ha='center', fontsize=14, fontweight='bold', transform=ax4.transAxes)
    ax4.text(0.5, 0.6, f"CPU Multi-thread: c8g.2xlarge (Graviton 4)", ha='center', fontsize=11, transform=ax4.transAxes)
    ax4.text(0.5, 0.45, f"CPU Single-thread: c8i-flex.2xlarge (Intel)", ha='center', fontsize=11, transform=ax4.transAxes)
    ax4.text(0.5, 0.3, f"Redis SET: c8i-flex.2xlarge (Intel)", ha='center', fontsize=11, transform=ax4.transAxes)
    ax4.text(0.5, 0.15, f"Nginx HTTP: r8g.2xlarge (Graviton 4)", ha='center', fontsize=11, transform=ax4.transAxes)
    ax4.axis('off')

    plt.suptitle('EC2 Instance Benchmark Summary (2xlarge / 8 vCPU)', fontsize=16, fontweight='bold')
    plt.tight_layout()
    plt.savefig(f'{RESULTS_DIR}/chart_summary.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("Generated: chart_summary.png")

def main():
    print("Loading benchmark data...")
    data = load_data()

    print(f"CPU data: {len(data['cpu'])} instances")
    print(f"Redis data: {len(data['redis'])} instances")
    print(f"Nginx data: {len(data['nginx'])} instances")
    print(f"Spring Boot data: {len(data['springboot'])} instances")

    print("\nGenerating charts...")
    plot_cpu_multithread(data['cpu'])
    plot_cpu_singlethread(data['cpu'])
    plot_redis(data['redis'])
    plot_nginx(data['nginx'])
    plot_springboot(data['springboot'])
    plot_comparison(data)

    print("\nAll charts generated successfully!")
    print(f"Output directory: {RESULTS_DIR}")

if __name__ == '__main__':
    main()
