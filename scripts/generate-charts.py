#!/usr/bin/env python3
"""Generate benchmark charts for xlarge instances"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

plt.style.use('seaborn-v0_8-whitegrid')
RESULTS_DIR = '/home/ec2-user/benchmark/results'

def get_color(instance):
    if 'g.' in instance or 'gd.' in instance or 'gn.' in instance:
        if '8g' in instance: return '#1a5f2a'
        if '7g' in instance: return '#2e8b57'
        return '#90ee90'
    elif 'a.' in instance or 'ad.' in instance:
        return '#e74c3c'
    else:
        if '8i' in instance: return '#1a237e'
        if '7i' in instance: return '#303f9f'
        if '6i' in instance: return '#5c6bc0'
        return '#9fa8da'

def plot_redis():
    df = pd.read_csv(f'{RESULTS_DIR}/redis-summary.csv')
    df = df.sort_values('SET (ops/sec)', ascending=True)

    fig, ax = plt.subplots(figsize=(12, 14))
    colors = [get_color(i) for i in df['Instance Type']]
    ax.barh(df['Instance Type'], df['SET (ops/sec)'], color=colors)
    ax.set_xlabel('Operations/sec')
    ax.set_title('Redis SET Performance (xlarge instances)', fontweight='bold')
    plt.tight_layout()
    plt.savefig(f'{RESULTS_DIR}/chart_redis.png', dpi=150)
    plt.close()
    print("Generated: chart_redis.png")

def plot_nginx():
    df = pd.read_csv(f'{RESULTS_DIR}/nginx-summary.csv')
    df = df.sort_values('Requests/sec', ascending=True)

    fig, ax = plt.subplots(figsize=(12, 10))
    colors = [get_color(i) for i in df['Instance Type']]
    ax.barh(df['Instance Type'], df['Requests/sec'], color=colors)
    ax.set_xlabel('Requests/sec')
    ax.set_title('Nginx HTTP Performance (xlarge instances)', fontweight='bold')
    plt.tight_layout()
    plt.savefig(f'{RESULTS_DIR}/chart_nginx.png', dpi=150)
    plt.close()
    print("Generated: chart_nginx.png")

def plot_springboot():
    df = pd.read_csv(f'{RESULTS_DIR}/springboot-summary.csv')
    df = df.sort_values('Startup (sec)', ascending=False)

    fig, ax = plt.subplots(figsize=(12, 14))
    colors = [get_color(i) for i in df['Instance Type']]
    ax.barh(df['Instance Type'], df['Startup (sec)'], color=colors)
    ax.set_xlabel('Startup Time (seconds) - lower is better')
    ax.set_title('Spring Boot JVM Startup (xlarge instances)', fontweight='bold')
    plt.tight_layout()
    plt.savefig(f'{RESULTS_DIR}/chart_springboot.png', dpi=150)
    plt.close()
    print("Generated: chart_springboot.png")

if __name__ == '__main__':
    plot_redis()
    plot_nginx()
    plot_springboot()
    print("All charts generated!")
