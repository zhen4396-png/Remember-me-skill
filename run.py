#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Remember me · CLI

    python run.py init                    建库
    python run.py add "我妈住院了"          写一句（自动判刻度）
    python run.py ingest chat.tsv         批量导入（日期<TAB>文本 或 纯文本）
    python run.py recall "老陈是怎么走的"    取一次横截面，直接贴进上下文
    python run.py axis                    看轴（一年一格）
    python run.py milestone               看刻度（每种事首/末/几次/多久）
    python run.py stats                   库统计
    python run.py selftest                自检
"""
import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import axis, lexicon
from engine import judge as J
from engine.store import Store

DEFAULT_ROOT = os.path.join(os.path.expanduser("~"), ".remember-me")


def _store(args):
    return Store(args.home or DEFAULT_ROOT)


def cmd_init(args):
    st = _store(args)
    os.makedirs(st.root, exist_ok=True)
    if not os.path.exists(st.path):
        open(st.path, "a", encoding="utf-8").close()
    m = lexicon.meta()
    print(f"库已就绪：{st.root}")
    # 用去重后的关键词数：各域之间有重复，直接加总会虚高（532 vs 实际 475）
    print(f"词表：{len(st.V.get('_all_keywords', []))} 个关键词"
          # 标注清楚这是自建金标。真实口语上只有 P≈35% —— 那个数写在 README 里，
          # 这里不能拿自测分数当能力证明。
          f"　判定阈值 {m.get('threshold')}"
          f"　自建金标 P={m.get('precision')} R={m.get('recall')}（非真实语料）")
    return 0


def cmd_add(args):
    st = _store(args)
    r = st.add(args.text, args.date, sync=args.sync)
    if not r:
        print("空输入")
        return 1
    flag = "★ 刻度" if r["pin"] else "  普通"
    print(f"{flag}  {r['d']}  score={r['score']} 通道={r['ch']}")
    return 0


def cmd_ingest(args):
    st = _store(args)
    with open(args.file, encoding="utf-8") as f:
        n = st.ingest(f.readlines())
    s = st.stats()
    print(f"导入 {n} 句，库内共 {s['n']} 句 / {s['pinned']} 条刻度 / "
          f"{s['first']} ~ {s['last']}")
    return 0


def cmd_recall(args):
    st = _store(args)
    recs = st.load()
    if not recs:
        print("库是空的")
        return 1
    print(axis.render(recs, args.query, idx=st.index()))
    return 0


def cmd_axis(args):
    st = _store(args)
    recs = st.load()
    if not recs:
        print("库是空的")
        return 1
    print(f"{'年':<6}{'句数':>6}{'聊天日':>7}{'刻度':>6}  主要的事")
    for a in axis.build_axis(recs):
        ks = "、".join(f"{axis.KIND_CN.get(k, k)}{n}" for k, n in a["kinds"]) or "—"
        print(f"{a['year']:<6}{a['n']:>6}{a['days']:>7}{a['anchors']:>6}  {ks}")
    return 0


def cmd_milestone(args):
    st = _store(args)
    recs = st.load()
    for m in axis.milestones(recs):
        yrs = m["span_days"] / 365.25
        print(f"{m['cn']:<5}{m['n']:>4}次  跨{yrs:>5.1f}年  {m['first']['d']} → {m['last']['d']}")
        print(f"      首：{m['first']['text'][:60]}")
        if m["last"] is not m["first"]:
            print(f"      末：{m['last']['text'][:60]}")
    return 0


def cmd_stats(args):
    st = _store(args)
    s = st.stats()
    if not s.get("n"):
        print("库是空的")
        return 1
    print(json.dumps(s, ensure_ascii=False, indent=1))
    print(f"\n原文字节 {s['chars']}，常驻刻度层 {len(axis.spine(st.load()))} 句")
    return 0


def cmd_rejudge(args):
    """按当前判定器重算全库的 pin/score/kinds。

    为什么需要这个命令：pin 是**写入时定型**的（这是对的，读时不重算才快），
    代价是——判定器修好之后，旧记录还带着旧的结论。
    真实库上就吃过这个亏：43 条里 11 条是旧的"长度即重要"判出来的假刻度，
    重算后只剩 0 条。
    """
    st = _store(args)
    path = st.path
    if not os.path.exists(path):
        print("库是空的")
        return 1
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    if not rows:
        print("库是空的")
        return 1
    before = sum(1 for r in rows if r.get("pin"))
    changed = 0
    for r in rows:
        j = J.judge(r["text"], st.V)
        new = {"pin": bool(j["pin"]), "score": int(max(j["ev"], j["ar"])),
               "ch": j["ch"], "kinds": axis.kinds_of(r["text"])}
        if any(r.get(k) != v for k, v in new.items()):
            changed += 1
        r.update(new)
    after = sum(1 for r in rows if r["pin"])
    if not args.dry_run:
        import time as _t
        bak = path + ".bak-" + _t.strftime("%H%M%S")
        open(bak, "w", encoding="utf-8").writelines(
            l for l in open(path, encoding="utf-8") if l.strip())
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        st._mem = None
        try:
            if os.path.exists(os.path.join(st.root, ".cache.pkl")):
                os.remove(os.path.join(st.root, ".cache.pkl"))
        except Exception:
            pass
    print(f"{len(rows)} 条  刻度 {before} → {after}   改动 {changed} 条")
    if not args.dry_run:
        print(f"已备份 → {os.path.basename(bak)}")
    return 0


def cmd_report(args):
    """读 hook.log + 库，报真实的读写与注入开销。

    这不是跑分脚本，是**读你自己刚才那段对话的账**：
    每条消息钩子花了多久、注入了多少字、库长到多大。
    """
    import re as _re
    st = _store(args)
    logp = os.path.join(st.root, "hook.log")
    if not os.path.exists(logp):
        # 「还没聊过」不是错误，别返回 1 —— 那会让脚本化调用误判成失败。
        print(f"还没有 {logp}")
        print("钩子还没跑过。挂上钩子随便说几句，再来一次。")
        return 0
    lines = [l.rstrip("\n") for l in open(logp, encoding="utf-8") if l.strip()]
    total_lines = len(lines)
    if getattr(args, "last", 0):
        lines = lines[-args.last:]
    n_msg = len(lines)
    if not n_msg:
        print("hook.log 是空的")
        return 1

    n_ok = n_dedup = n_query = n_fail = 0
    inj, ms = [], []
    for l in lines:
        if "写入失败" in l or "FAIL" in l:
            n_fail += 1
            continue
        if "跳过(纯追问)" in l:
            n_query += 1
        elif "去重跳过" in l:
            n_dedup += 1
        elif "OK " in l:
            n_ok += 1
        m = _re.search(r"注入=(\d+)字", l)
        if m:
            inj.append(int(m.group(1)))
        m = _re.search(r"耗时=(\d+)ms", l)
        if m:
            ms.append(int(m.group(1)))

    def pct(xs, q):
        if not xs:
            return 0
        ys = sorted(xs)
        return ys[min(len(ys) - 1, int(len(ys) * q))]

    rows = [json.loads(x) for x in open(st.path, encoding="utf-8") if x.strip()] \
        if os.path.exists(st.path) else []
    n_rec = len(rows)
    nbytes = os.path.getsize(st.path) if os.path.exists(st.path) else 0

    inj_total = sum(inj)
    inj_hit = sum(1 for x in inj if x)
    print("=" * 56)
    scope = f"最近 {n_msg} 条（日志共 {total_lines} 条）" if getattr(args, "last", 0) else f"日志全量 {n_msg} 条消息"
    print(f"  {scope}")
    print("=" * 56)
    print(f"  写入成功      {n_ok} 条")
    print(f"  去重跳过      {n_dedup} 条   （连着说了同样的话）")
    print(f"  纯追问跳过    {n_query} 条   （「你还记得…」本身不算记忆）")
    print(f"  失败          {n_fail} 条")
    print()
    print(f"  触发注入      {inj_hit} / {n_msg} 条消息   （{inj_hit/max(n_msg,1):.0%}）")
    if inj_hit:
        print(f"  注入总量      {inj_total:,} 字")
        print(f"  平均每次      {inj_total//inj_hit:,} 字   最多 {max(inj):,} 字")
        print(f"  折算 token    约 {int(inj_total*0.6):,} ~ {inj_total:,} 个"
              f"（按 1 汉字 0.6~1 token 估，仅供量级参考）")
    else:
        print("  注入总量      0 字   （这段没人问「还记得」，所以一次都没注入）")
    print()
    if ms:
        print(f"  钩子自身耗时  P50 {pct(ms,.5)}ms  P95 {pct(ms,.95)}ms  最大 {max(ms)}ms")
        print(f"                （另加 Python 启动约 150ms，加 -S 后的实测值）")
    print()
    print(f"  库现在        {n_rec} 条  {nbytes/1024:.1f} KB  {nbytes/max(n_rec,1):.0f} 字节/条")
    if n_rec:
        print(f"  每天 100 句  一年 {36500*nbytes/n_rec/1024/1024:.1f} MB"
              f"   十年 {365000*nbytes/n_rec/1024/1024:.0f} MB")
    print("=" * 56)
    return 0


def cmd_selftest(args):
    """自检：五条不变量 + 三条轴性质。任何一条红就是坏了。"""
    import tempfile
    ok = True

    def chk(name, cond, detail=""):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  [{'PASS' if cond else 'FAIL':>4}] {name}" + (f"   {detail}" if detail else ""))

    print("不变量")
    V = lexicon.load()
    from engine import judge as J

    chk("I1 词表可加载", isinstance(V, dict) and V.get("_events") is not None,
        f"{len(V.get('_events', []))} 个事件词")
    # 死亡歧义
    chk("I2 「我先走了」不是死亡", not J.judge("我先走了", V)["pin"])
    chk("I3 「奶奶走了」是死亡", J.judge("奶奶走了", V)["pin"])
    chk("I4 「同事走了两个」不是死亡", not J.judge("同事走了两个", V)["pin"])
    chk("I5 「我爸跑车去了」不是死亡", not J.judge("我爸跑车去了", V)["pin"])
    chk("I6 「我妈住院了」是刻度", J.judge("我妈住院了", V)["pin"])
    chk("I7 「今天下雨了」不是刻度", not J.judge("今天下雨了，路上好堵", V)["pin"])
    chk("I8 「想回老家算了」不是事实", not J.judge("有时候想回老家算了", V)["pin"])

    # 检索零写入
    tmp = tempfile.mkdtemp()
    st = Store(tmp)
    for t, d in [("今天下雨了，路上好堵", "2024-01-01"),
                 ("我妈住院了，医生说要观察", "2024-01-02"),
                 ("今天下雨，堵死了", "2024-01-05")]:
        st.add(t, d)
    recs = st.load()
    before = json.dumps([(r["d"].isoformat(), r["text"], r["pin"], r["score"]) for r in recs],
                        ensure_ascii=False)
    _ = axis.render(recs, "下雨")
    after = json.dumps([(r["d"].isoformat(), r["text"], r["pin"], r["score"]) for r in recs],
                       ensure_ascii=False)
    chk("I9 检索不改变任何存储", before == after)

    # README 里写的推荐用法是 Store("~/.remember-me")。不展开 ~ 的话
    # 会在当前目录下建一个名字就叫「~」的文件夹——这是个真实踩过的坑。
    probe = os.path.join("~", ".remember-me-selftest-probe")
    st_probe = Store(probe)
    chk("I10 ~ 会展开成真实家目录", os.path.expanduser("~") in st_probe.root, st_probe.root)
    try:
        os.rmdir(st_probe.root)
    except OSError:
        pass

    print("轴")
    ax = axis.build_axis(recs)
    chk("A1 轴按年分格", len(ax) == 1 and ax[0]["year"] == 2024, f"{[a['year'] for a in ax]}")
    ms = axis.milestones(recs)
    chk("A2 刻度含首末", any(m["kind"] == "illness" for m in ms),
        f"{[m['cn'] for m in ms]}")
    sp = axis.spine(recs, cap=2)
    chk("A3 常驻层有上限且按时间排", len(sp) <= 2 and sp == sorted(sp, key=lambda r: r["d"]))
    got = axis.retrieve(recs, "我住院了吗")
    chk("A4 检索命中住院那条", any("住院" in r["text"] for r in got), f"{len(got)} 句")
    chk("A5 库里没有一句是模型写的",
        all(isinstance(r["text"], str) and r["text"] for r in recs))

    # 中英混排的大写/小写必须归一。真实语料里「CAD」和「cad-mechanical」是同一件事，
    # 不做 lower() 的话二字组零交集，问「CAD 图纸」召不回「帮我安装 cad 技能」。
    from engine.axis import bigrams as _bg
    chk("A6 大小写不影响字面重合", _bg("CAD 图纸") & _bg("帮我安装cad-mechanical"),
        f"{sorted(_bg('CAD 图纸') & _bg('帮我安装cad-mechanical'))}")

    # A7/A8/A9：这三条是真实使用中翻过的车，不是假想。
    # 曾经「长」被当成了「重要」：>=200 字的记录 100% 被判成刻度，<30 字的 0% 被判上。
    # 于是一段几百字的流水账顶掉了"我妈住院了"。
    long_doc = (
        "今天到公司已经快十点了，电梯又坏了，我爬了六层楼，到工位时后背全湿了。"
        "上午开了两个会，第一个会讲下季度的排期，讲了四十分钟，最后发现大家用的还是去年那份表。"
        "第二个会本来只要二十分钟，结果因为一个按钮放左边还是右边吵了一个小时。"
        "中午去楼下吃了面，还是那家，汤偏咸，我跟老板说少放点盐，他说他们家就是这个味。"
        "下午本来想写点东西，结果一直在回消息，回完一轮又来一轮，等抬头看窗外天已经黑了。"
        "下班时下起了小雨，我没带伞，在楼下等了十几分钟，最后还是跑着去了地铁站。"
        "地铁上人很多，我站在门口，旁边一个小孩一直在问他妈妈为什么隧道里看不见星星。"
        "回家洗了个澡，煮了碗面，看了一会儿剧，看到一半发现自己完全不记得前二十分钟讲了什么。"
        "现在坐在桌前，想了半天今天到底做了什么，好像什么都做了，又好像什么都没做。"
        "明天还得早起，先把这些写下来，免得以后想不起来这一天是怎么过去的。"
    )
    chk("A7 长文本身不能成为刻度（长度封顶 5 < 阈值 7）",
        not J.judge(long_doc, V)["pin"], f"{len(long_doc)} 字")
    chk("A8 技术指令再长也不是人生",
        not J.judge("帮我推荐几个合适的CAD绘图、标尺寸的skills，然后安装 cad-mechanical-part-drafting", V)["pin"])
    chk("A9 弱委婉语要有医疗语境",
        J.judge("我妈身体不太好", V)["pin"] and not J.judge("发现有问题，它进行了修复", V)["pin"])

    # A10/A11：检索的两个底线。真实库上问「我妈身体怎么样」，
    # 一个内容二字组都没命中，却照样给了 4 条（CAD 图纸、桌面整理）——
    # 排序永远有第一名，第一名不代表相关。
    probe2 = os.path.join(probe, "gate")
    try:
        st2 = Store(probe2)
        for _t in ("我妈住院了，医生说要观察几天", "在卫生间摔了一跤，膝盖磕在马桶边上",
                   "今天下雨了路上好堵"):
            st2.add(_t, d="2025-03-0%d" % (len(st2.load()) + 1))
        recs2, idx2 = st2.load(), st2.index()
        empty = axis.retrieve(recs2, "我养过狗吗", idx=idx2)
        chk("A10 没相关记忆时返回空，不拿疑问词凑数", len(empty) == 0, f"{len(empty)} 句")
        # 「摔了一跤」和「摔倒」没有共同二字组，靠关键单字兜住
        fall = axis.retrieve(recs2, "我摔倒是哪次", idx=idx2)
        chk("A11 关键单字能召回（摔倒 ↔ 摔了一跤）",
            len(fall) > 0 and all("摔" in r["text"] for r in fall), f"{len(fall)} 句")

        # A12：自建金标回归。这 99 条以前躺在 seeds.py 里没人读，
        # 是"死数据"——改了判定器也不知道有没有搞坏。接成断言它就活了。
        # 门槛留了余量（P>=0.95 / R>=0.90），不是按当前值卡死，
        # 否则以后每次正常波动都要改断言。
        from engine import seeds as _S
        _pos = [t for t, y in _S.GOLD if y]
        _neg = [t for t, y in _S.GOLD if not y]
        _tp = sum(1 for t in _pos if J.judge(t, V)["pin"])
        _fp = sum(1 for t in _neg if J.judge(t, V)["pin"])
        _P = _tp / max(_tp + _fp, 1)
        _R = _tp / max(len(_pos), 1)
        chk("A12 自建金标不劣化（P>=0.95 R>=0.90）",
            _P >= 0.95 and _R >= 0.90, f"P={_P:.3f} R={_R:.3f} n={len(_S.GOLD)}")
        shutil.rmtree(probe2, ignore_errors=True)
        # 父目录也要删：Store(probe2) 的 mkdir 会把上面 rmdir 掉的 probe 重新建出来，
        # 只删 gate 的话家目录里会留一个空壳。
        shutil.rmtree(os.path.expanduser(probe), ignore_errors=True)
    except Exception as exc:
        chk("A10/A11 检索闸", False, repr(exc))

    print("\n" + ("自检通过" if ok else "自检失败"))
    return 0 if ok else 1


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--home", default=argparse.SUPPRESS,
                        help=f"库目录（默认 {DEFAULT_ROOT}）")

    p = argparse.ArgumentParser(prog="remember-me",
                                description="长期记忆 + 关键事件 + 人生轴")
    p.add_argument("--home", default=None, help=f"库目录（默认 {DEFAULT_ROOT}）")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("init", parents=[common]).set_defaults(fn=cmd_init)

    a = sub.add_parser("add", parents=[common])
    a.add_argument("text")
    a.add_argument("--date")
    a.add_argument("--sync", action="store_true")
    a.set_defaults(fn=cmd_add)

    a = sub.add_parser("ingest", parents=[common])
    a.add_argument("file")
    a.set_defaults(fn=cmd_ingest)

    a = sub.add_parser("recall", parents=[common])
    a.add_argument("query")
    a.set_defaults(fn=cmd_recall)

    sub.add_parser("axis", parents=[common]).set_defaults(fn=cmd_axis)
    sub.add_parser("milestone", parents=[common]).set_defaults(fn=cmd_milestone)
    sub.add_parser("stats", parents=[common]).set_defaults(fn=cmd_stats)
    a = sub.add_parser("rejudge", parents=[common])
    a.add_argument("--dry-run", action="store_true", help="只报告，不写回")
    a.set_defaults(fn=cmd_rejudge)
    a = sub.add_parser("report", parents=[common])
    a.add_argument("--last", type=int, default=0, help="只看最近 N 条消息（新开对话测试用）")
    a.set_defaults(fn=cmd_report)
    sub.add_parser("selftest", parents=[common]).set_defaults(fn=cmd_selftest)

    args = p.parse_args()
    if not getattr(args, "fn", None):
        p.print_help()
        return 0
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
