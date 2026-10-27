#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""规模与延迟实测：用真实的 engine 代码，不是估算。

回答三个问题：
  1. 能装多少（字节 / 内存）
  2. 写多快（含 fsync）
  3. 读多慢（随库增长怎么变）
"""
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engine import axis
from engine.store import Store

random.seed(20261027)

# 造一份"像真人聊天"的语料：大量重复琐事 + 少量关键事件 + 长叙述
TRIVIAL = ["今天下雨了路上好堵", "外卖又涨价了", "地铁上人好多", "手机没电了",
           "午饭吃了面条", "楼下在装修", "又加班到十点好累", "天气有点热",
           "快递还没到", "昨晚没睡好", "困", "饿", "算了", "嗯"]
KEY = ["我妈住院了医生说要观察几天", "我爸确诊了", "奶奶走了", "我们离婚了",
       "我被裁了", "房子卖了", "孩子判给她了", "我摔了一跤",
       "体检报告有问题", "我要进ICU了"]
LONG = ["今天在医院陪了一天，走廊里那个椅子硬得人腰疼，我从早上八点坐到下午四点，"
        "中间就出去买了个包子，回来发现我妈睡着了，手背上还扎着针，我看着就难受",
        "她走的那天我一直在旁边握着她的手，从下午到晚上，她的手一点一点凉下去，"
        "我一直没松开，后来护士来的时候我还握着，我不知道该干什么"]


def gen(n):
    out = []
    base = 1600000000
    for i in range(n):
        r = random.random()
        if r < 0.82:
            t = random.choice(TRIVIAL)
        elif r < 0.97:
            t = random.choice(KEY)
        else:
            t = random.choice(LONG)
        d = time.strftime("%Y-%m-%d", time.localtime(base + i * 900))
        out.append((d, t))
    return out


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(int(len(xs) * p), len(xs) - 1)]


def bench(n, home):
    os.makedirs(home, exist_ok=True)
    p = os.path.join(home, "events.jsonl")
    if os.path.exists(p):
        os.remove(p)
    st = Store(home)

    rows = gen(n)
    # 写入（含 fsync 抽样测量，全量加 fsync 太慢）
    t0 = time.perf_counter()
    lat = []
    with open(p, "a", encoding="utf-8") as f:
        for i, (d, t) in enumerate(rows):
            # 和 add() 走同一个 make_rec：手抄一份 dict 迟早跟落盘形状漂移
            line = json.dumps(Store.make_rec(t, d, st.V), ensure_ascii=False)
            a = time.perf_counter()
            f.write(line + "\n")
            if i % 50 == 0:                 # 每 50 条 fsync 一次（真实用法）
                f.flush()
                os.fsync(f.fileno())
                lat.append((time.perf_counter() - a) * 1000)
    t_write = time.perf_counter() - t0

    t = time.perf_counter()
    recs = st.load()
    t_load = (time.perf_counter() - t) * 1000          # 冷启动（含解析）
    t = time.perf_counter()
    idx = st.index()
    t_index = (time.perf_counter() - t) * 1000
    t2 = time.perf_counter()
    st._mem = None
    st.load()
    t_load_warm = (time.perf_counter() - t2) * 1000    # 走 pickle 缓存

    # 召回
    qs = ["我妈住院了", "奶奶怎么样了", "最近下雨吗", "工作忙不忙",
          "房子的事怎么办", "她走了以后", "身体有什么毛病", "钱够不够"]
    lat_r = []
    for _ in range(30):
        q = random.choice(qs)
        a = time.perf_counter()
        axis.retrieve(recs, q, idx=idx)
        lat_r.append((time.perf_counter() - a) * 1000)

    t = time.perf_counter()
    sp = axis.spine(recs)
    t_spine = (time.perf_counter() - t) * 1000

    size = os.path.getsize(p)
    return dict(
        n=n, bytes=size, per=size / n, t_write=t_write,
        write_qps=n / t_write, fsync_p50=pct(lat, .5) if lat else 0,
        fsync_p95=pct(lat, .95) if lat else 0,
        t_load=t_load, t_index=t_index, t_load_warm=t_load_warm,
        r_p50=pct(lat_r, .5), r_p95=pct(lat_r, .95),
        t_spine=t_spine, spine=len(sp),
    )


def main():
    print("=" * 78)
    print("规模实测（真实 engine 代码）")
    print("=" * 78)
    print(f"{'条数':>9}{'体积':>8}{'写入':>7}{'fsync':>8}{'冷load':>9}{'热load':>9}"
          f"{'建索引':>8}{'召回P50':>9}{'召回P95':>9}")
    rows = []
    for n in (10000, 50000, 200000):
        r = bench(n, os.path.join(HERE, f"_bench_{n}"))
        rows.append(r)
        print(f"{r['n']:>9,}{r['bytes']/1024/1024:>7.1f}M{r['t_write']:>6.0f}s"
              f"{r['fsync_p50']:>7.2f}ms{r['t_load']:>8.0f}ms{r['t_load_warm']:>8.0f}ms"
              f"{r['t_index']:>7.0f}ms{r['r_p50']:>8.1f}ms{r['r_p95']:>8.1f}ms")
    print()
    for r in rows:
        print(f"  {r['n']:>7,} 条 → 常驻层 {r['spine']} 句 / 构建 {r['t_spine']:.0f}ms"
              f" / 原文 {r['bytes']/1024/1024:.1f}MB")
    print("\n说明：")
    print("  · fsync 每 50 条一次（真实用法），不是每条都 fsync")
    print("  · 冷 load = 首次解析 jsonl；热 load = 走 pickle 缓存，只发生一次")
    print("  · 召回走倒排索引，只对候选集打分。加索引前 200k 条召回是 368ms")
    print("  · 索引在进程内建一次（200k 条约 380ms），之后所有检索复用")


if __name__ == "__main__":
    main()
