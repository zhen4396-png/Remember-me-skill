# -*- coding: utf-8 -*-
"""L2：人生轴。阶段 × 刻度 × 检索。

轴的作用不是「压缩内容」，是给内容一个**坐标**：
  · 哪一年
  · 哪一类事（生死/病/工作/学业/住处/钱/家/记性/伤/离散/心里）
  · 每种事第一次、最后一次、几次、跨多久
  · 一个东西（人、物、地方）被提起的整条线

有了坐标，「我十岁那年发生了什么」「老陈的病拖了多久」才答得出来。
关键词检索永远答不了这两个问题——这是轴存在的唯一理由。
"""
import bisect
import math
import re
from collections import Counter, defaultdict
from datetime import timedelta

# ============ 事件类型 ============
KIND_RULES = [
    ("death",   r"(去世|过世|离世|逝世|走了|没了|不在了|葬礼|出殡|灵堂|骨灰|头七|坟|扫墓|磕头)"),
    ("illness", r"(确诊|住院|手术|化疗|放疗|透析|病危|抢救|进ICU|插管|晚期|转移|复发|骨折|中风|脑梗|心梗|胰岛素|不好的病|长了东西)"),
    ("memory",  r"(记性|忘事|老忘|忘了关|走丢|认不出|糊涂|阿尔茨海默|痴呆)"),
    ("injury",  r"(摔了|摔了|摔倒|栽倒|车祸|被撞|晕倒|吐血)"),
    ("split",   r"(离婚|分手|离了|分了|冷战|分居|搬出去|不回来)"),
    ("job",     r"(辞职|离职|被裁|裁员|失业|下岗|退休|入职|转正|升职|提拔|降职|调岗|跳槽|面试|offer|签了|加班)"),
    ("study",   r"(高考|考研|中考|考公|考编|落榜|考上|录取|退学|休学|毕业|挂科|补考|成绩|出分|调剂|答辩|论文)"),
    ("house",   r"(搬家|买房|卖房|过户|拆迁|租房|房贷|房租|养老院|装修|漏水)"),
    ("money",   r"(欠债|借钱|还钱|赔钱|没钱|欠了|供不起|工资|拖欠|亏损|倒闭)"),
    ("family",  r"(结婚|订婚|怀孕|生孩子|生了|满月|孩子|女儿|儿子|老伴|婆婆|催婚|相亲)"),
    ("inner",   r"(想通|决定|后悔|愧疚|撑不住|崩溃|哭|难受|一个人)"),
]
KIND_RULES = [(k, re.compile(p)) for k, p in KIND_RULES]
KIND_CN = {
    "death": "生死", "illness": "病", "memory": "记性", "injury": "伤",
    "split": "离散", "job": "工作", "study": "学业", "house": "住处",
    "money": "钱", "family": "家", "inner": "心里",
}

# 问法别名：用户问「怎么走的」不会说「去世」。只用于检索，不参与打标签。
QUERY_ALIAS = {
    "death":   r"走|去世|死|没了|不在|最后",
    "illness": r"病|住院|医院|大夫|医生|身体|查|治",
    "memory":  r"记性|忘|糊涂",
    "injury":  r"摔|伤|撞|倒",
    "split":   r"离|分|吵|冷战",
    "job":     r"工作|上班|生意|店|忙|加班",
    "study":   r"考|学|上学|毕业|成绩",
    "house":   r"房|搬|住哪|养老院",
    "money":   r"钱|债|工资|赔",
    "family":  r"家|孩子|结婚|生|老婆|老公|女儿|儿子",
}
QUERY_ALIAS = {k: re.compile(p) for k, p in QUERY_ALIAS.items()}

STOP = set("的了是在有和就不都也很还我你他她它这那什么怎么为什么哪哪个多少几")
_PUNCT = re.compile(r"[，。！？、,.!?\s…~“”\"'：:；;（）()]")


def kinds_of(text):
    return [k for k, pat in KIND_RULES if pat.search(text)]


def bigrams(t, n=2):
    # 必须先 lower()：问「CAD 图纸」和原文「cad-mechanical」如果按原始大小写切片，
    # 二字组会是 {CA,AD} 与 {ca,ad}，交集为空 —— 中英混排时字面重合会整段失效。
    t = _PUNCT.sub("", (t or "").lower())
    return {t[i:i + n] for i in range(len(t) - n + 1)} if len(t) >= n else ({t} if t else set())


# ============ 轴 ============
def build_axis(recs):
    years = defaultdict(list)
    for r in recs:
        years[r["d"].year].append(r)
    out = []
    for y in sorted(years):
        rs = years[y]
        kc = Counter(k for r in rs for k in r["kinds"])
        out.append(dict(
            year=y, n=len(rs), days=len({r["d"] for r in rs}),
            anchors=sum(1 for r in rs if r["pin"]),
            kinds=kc.most_common(3),
        ))
    return out


def milestones(recs):
    """刻度：每种事第一次 / 最后一次 / 几次 / 跨多久。"""
    by = defaultdict(list)
    for r in recs:
        for k in r["kinds"]:
            by[k].append(r)
    out = []
    for k, rs in by.items():
        rs.sort(key=lambda r: r["d"])
        out.append(dict(
            kind=k, cn=KIND_CN.get(k, k), n=len(rs),
            first=rs[0], last=rs[-1],
            span_days=(rs[-1]["d"] - rs[0]["d"]).days,
        ))
    out.sort(key=lambda x: (-x["span_days"], -x["n"]))
    return out


DAYS_PER_YEAR = 365.25    # 「跨几年」的换算。run.py 和 demo.py 都要用，别各写一份
SPINE_MAX_CHARS = 120     # 常驻层单条上限：超过就不是一句话了


def spine(recs, cap=64):
    """常驻刻度层：一生中最重的那些原话，永远带着（约 3KB）。

    为什么必须有它：实体线会被代词切断——「五点二十，他走了」不含「老陈」。
    而一个人一辈子的刻度本来就只有几十句，全放进去也不贵。
    """
    import heapq
    # 小库（刚用几天）里如果全进常驻层，「常驻」就失去意义了。
    # 上限取 1/4，但不少于 8 句。
    cap = min(cap, max(8, len(recs) // 4))
    # 常驻层的每一条都要**真的**放进系统提示，所以单条必须够短。
    # 曾经混进过 763 字的任务指令：一条就吃掉 1.5KB，而且每次问答都带着。
    # 常驻该是「几十句短话」，不是「几篇文档」。
    pool = [r for r in recs if len(r["text"]) <= SPINE_MAX_CHARS]
    top = heapq.nlargest(cap, pool, key=lambda r: (r.get("score", 0), -r["d"].toordinal()))
    return sorted(top, key=lambda r: r["d"])


# ============ 检索 ============
# 疑问脚手架：这些二字组不承载「在问什么」。
# 真实库里就吃过这个亏 —— 问「我妈身体怎么样」，唯一命中的二字组是「怎么」，
# 于是 CAD 图纸、桌面整理、一千字的开发需求全被当成相关记忆返回。
# 不是排序错了，是**根本没有匹配**，只是没人敢返回空。
Q_GRAMS = {
    "怎么", "么样", "怎样", "什么", "么时", "时候", "为什", "多少",
    "哪个", "哪些", "哪里", "是不", "不是", "了吗", "没有", "一个",
    "这个", "那个", "可以", "告诉", "说说", "还有", "就是", "帮我",
    "我们", "你们", "他们", "现在", "然后", "如果", "因为", "所以",
}

# 关键单字：一个字就能定性的动作/状态。
# 为什么需要它 —— 中文里「摔了一跤」和「摔倒」没有任何共同二字组，
# 二字组检索必然落空。而这类字恰恰是最该被检索到的。
# 只收「一字定性」的字：说「摔」就是摔了，说「婚」就是在讲婚姻。
# 「体」「情」「事」这种到处都能撞上的字一个都不收 —— 收了会把「体现」当成「身体」。
CRITICAL_CHARS = set(
    "摔跌病亡葬婚离考孕残卖治丧嫁娶逝夭跪哭吼债骗赌醉醒娩"
)
POOL_CAP = 4000          # 单次检索最多打分的候选条数（超过就等距抽样）


def _sample(lst, cap):
    if len(lst) <= cap:
        return lst
    step = len(lst) / cap
    return [lst[int(i * step)] for i in range(cap)]


def build_index(recs):
    """独立建索引（不经过 Store 时用）。"""
    from .store import Index
    return Index(recs, bigrams)


def _hit(text, needle):
    """大小写不敏感的包含判断。中英混排里「CAD」和「cad」必须是同一件事。"""
    return needle in text or needle.lower() in text.lower()


def _dedup(recs, n=12):
    """按前 n 个字去重，保留首次出现的顺序。

    用前 12 字而不是整句当键：同一句话从不同来源进来时可能差一两个标点，
    整句比对会漏掉这种重复。
    """
    out, seen = [], set()
    for r in recs:
        k = r["text"][:n]
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def entities(q, recs, idx=None, topn=2):
    """从问题里认出「谁」和「什么」。

    人记住事是按「谁」串的。问题里的 2-4 字片段，如果在库里反复出现，
    那就是一个实体。有索引时用倒排求交，不扫全表。
    """
    cand = {}
    for n in (4, 3, 2):
        for i in range(len(q) - n + 1):
            c = q[i:i + n]
            if any(ch in STOP for ch in c):
                continue
            if not all("\u4e00" <= ch <= "\u9fff" for ch in c):
                continue
            if idx is not None:
                hits = len(idx.contains(c, bigrams))
            else:
                hits = sum(1 for r in recs if _hit(r["text"], c))
            if hits >= 3:
                cand[c] = hits * n
    out = []
    for c, _ in sorted(cand.items(), key=lambda kv: -kv[1]):
        if any(c in o or o in c for o in out):
            continue
        out.append(c)
        if len(out) >= topn:
            break
    return out


def retrieve(recs, q, budget=20, idx=None):
    """轴上取横截面。一条公式，不分路配额。

    配额制（每个来源单独保证位子）是 bug 的温床：上一轮因为它引入过 6 个错，
    其中 5 个是同一类——好东西在管道里被后一步悄悄丢掉。

    候选集来自倒排索引，只对候选打分，不扫全表。
    """
    if idx is None:
        idx = build_index(recs)
    qg = {g for g in bigrams(q) if g not in Q_GRAMS}   # 去掉疑问脚手架
    ents = entities(q, recs, idx)
    qkinds = {k for k, pat in KIND_RULES if pat.search(q)}
    qkinds |= {k for k, pat in QUERY_ALIAS.items() if pat.search(q)}
    m = re.search(r"(20\d\d)", q)
    year = int(m.group(1)) if m else None

    # ---------- 候选集 ----------
    # 注意：不把「所有刻度句」塞进候选池。那样每问一句都会把同一批 69 条
    # 刻度全捞出来，把真正相关的那几条挤到后面（问「摔倒是哪次」先返回 2021 年的病）。
    # 刻度层的职责是「永远在场」，那是 spine() 的事，不是检索的事。
    pool = set()
    for g in qg:
        s = idx.postings(g)
        if s:
            pool |= s
    for e in ents:
        pool |= set(idx.contains(e, bigrams))
    for k in qkinds:
        pool |= set(_sample(idx.by_kind.get(k, []), POOL_CAP))
    if year:
        pool |= set(_sample(idx.by_year.get(year, []), POOL_CAP))

    # 稀有度权重：字面重合必须按 IDF 加权。
    # 不加权的话「我倒是看完了」会因为和「摔倒是哪次」共享一个「倒是」被当成相关。
    n_doc = len(recs)
    too_common = max(3, int(n_doc * 0.3))     # 超过 30% 的文档都有的二字组，没有区分度

    def _w(g):
        df = len(idx.bg.get(g, ()))
        if df == 0:
            df = n_doc
        return 1.0 / math.log(2 + df)

    # 中文单字兜底：「摔了一跤」和「摔倒」没有共同二字组。
    # 注意：这里用的是关键单字表，不是"罕见字"——
    # 早先那版按 `idx.bg.get(单字)` 判罕见度，而索引里只有二字组，
    # 于是这个集合**恒为空**，那段兜底一直是死代码，只是没人发现。
    crit_q = CRITICAL_CHARS & set(q)

    def score(r):
        s = 3.0 * sum(_w(g) for g in (qg & bigrams(r["text"])))
        s += 2.0 * len(crit_q & set(r["text"]))
        s += 0.6 * r.get("score", 0)
        if r.get("pin"):
            s += 3.0
        if any(_hit(r["text"], e) for e in ents):
            s += 6.0
        if qkinds & set(r["kinds"]):
            s += 3.0
        if year and r["d"].year == year:
            s += 2.0
        return s

    cand = [recs[i] for i in pool]
    ranked = sorted(cand, key=lambda r: (-score(r), r["d"]))[:budget]

    # 实体线的两头 + 两端的上下文窗：
    # 「安安出生那天」——出生那条原话里还没有「安安」这个名字；
    # 「为什么从加拿大回来」——讲原因那条原话里没有「加拿大」。
    tail = []
    for e in ents:
        pos = idx.contains(e, bigrams)
        if len(pos) < 3:
            continue
        rs = sorted((recs[i] for i in pos), key=lambda r: r["d"])
        tail += [rs[0], rs[-1]]
        for a in (rs[0]["d"], rs[-1]["d"]):
            lo = bisect.bisect_left(idx.dates, a - timedelta(days=25))
            hi = bisect.bisect_right(idx.dates, a + timedelta(days=25))
            # 窗口里只收有信号的句子。否则「老陈第一次出现」前后 25 天
            # 会把「菠菜四块五一斤」「蟹爪兰开了七八朵」全捞进来。
            tail += [recs[i] for i in range(lo, hi)
                     if recs[i].get("pin") or recs[i].get("score", 0) >= 7]

    out = _dedup(ranked + tail)
    # ---------- 相关性闸：宁可不给，也不给错 ----------
    # 上面那批分是「排序」，不是「有没有」。真实库上问「我妈身体怎么样」，
    # 一个内容二字组都没命中，但排序照样给出 4 条（CAD 图纸、桌面整理……）。
    # 排序永远有第一名，可第一名不代表相关。
    # 所以这里单独判一次「够不够格」，不够就返回空 —— 空比错好，
    # 因为模型拿到不相干的材料就会顺着编，而拿到空会老实说「不记得」。
    if qg:
        # 「有效查询词」= 这个二字组在本库里**真的存在**（df>0），且不太常见。
        # 为什么不用简单覆盖率：自然问句会切出一堆跨词边界的碎片
        # （「晋升失败那次我说了什么」会切出「升失」「败那」「次我」「我说」），
        # 分母被这些碎片灌大，只命中「晋升」一条也过不了 20% 的线，
        # 结果是该召回的题被闸掉。用「存在且不常见」筛一遍，碎片自动出局。
        # 太常见的词（「那次」「我说」）即使命中也不算相关
        target = {g for g in qg if 0 < len(idx.bg.get(g, ())) <= too_common}

        def _ok(r):
            if target & bigrams(r["text"]):
                return True
            if any(_hit(r["text"], e) for e in ents):
                return True
            if crit_q & set(r["text"]):
                return True
            return False

        out = [r for r in out if _ok(r)]
        if not out:
            return []
    else:
        # 查询里没有内容词（比如「还记得吗」），只给刻度层，不瞎给
        out = [r for r in out if r.get("pin")]

    # 先按优先级截断，再按时间排。反过来会把「最早的 N 条」留下，后面高分句全被扔掉。
    out = out[:budget + 6]
    out.sort(key=lambda r: r["d"])
    return out


def render(recs, q, idx=None, with_spine=False):
    """把一次检索渲染成可以直接贴进上下文的文本块。

    with_spine=False 时只给问题相关的句子——刻度层应该由调用方
    在系统提示里单独常驻，不要混进每一次检索。
    """
    got = retrieve(recs, q, idx=idx)
    from collections import Counter as _C
    kc = _C(k for r in got for k in r["kinds"])
    head = "【记忆检索】" + q
    if kc:
        head += "　（涉及：" + "、".join(KIND_CN.get(k, k) for k, _ in kc.most_common(3)) + "）"
    # 一条都没相关时，不要硬塞常驻层。
    # 问「我养过狗吗」却给她看 16 句「老陈去世」，模型很可能顺着那些话答，
    # 而不是老实说「没有」。空着比塞满安全 —— 这正是「不要编」的实现方式。
    if with_spine and got:
        sp = spine(recs)
        lines = [head, f"（刻度层 {len(sp)} 句 + 相关 {len(got)} 句，按时间排）"]
        got = _dedup(sorted(sp + got, key=lambda r: r["d"]))
    elif with_spine:
        lines = [head, "（没有和这个问题相关的记忆。不要编，直接说不记得。）"]
    else:
        lines = [head, f"（从你 {len(recs)} 句原话里取出的 {len(got)} 句，按时间排）"]
    for r in got:
        mark = "★" if r.get("pin") else " "
        lines.append(f"{mark}{r['d']}　{r['text']}")
    if not got and not with_spine:
        lines.append("（没有相关记忆。不要编。）")
    return "\n".join(lines)
