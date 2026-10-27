# -*- coding: utf-8 -*-
"""Remember me · 判定器（唯一真相源）

为什么换模型：
  第一版是「词表命中 = 重要」。在 2500 句真实日志上 P=34.6% / R=24.0%。
  错的地方不是词不够多，是模型错了——
    · 误判：「我爸跑车去了」当成死亡，「我妈出院了」当成危机，
            「想回老家」当成事实，「他说调岗」当成他的事。
            → 它在看词，没看**这句话在断言什么**。
    · 漏判：「考完了，最后一道大题没写完，我走出考场腿是软的，我完了」
            一个事件词都没有，但这是这个人一生最重的一天。
            → 它在看词，没看**这句话有多重**。

新模型：两条通路，各自独立。
  ┌ 事实通道（event）：不可逆事件 + 情态闸。只认「已发生」的断言。
  │    情态闸区分：事实 / 意愿 / 否定 / 未然 / 转述 / 假设。
  │    「想辞职」不是辞职，「差点提离职」不是离职，「他说调岗」不是调岗。
  └ 唤醒通道（arousal）：情绪强度 + 身体反应 + 决定宣告 + 异常长度。
       对应人类记忆里的闪光灯记忆（flashbulb）：高唤醒事件一次就刻住，
       不需要重复。这一条**不看频次**，所以没违反「重要性不含频次」的不变量。

两条通路取或。都只看「说了什么」，不看「说了几次」。
"""
import re
from . import seeds

# ============================================================
# 1. 唤醒通道：高唤醒事件一次就刻住
# ============================================================
# 情绪强度词：不是「烦」「累」这种日常情绪，是真正烧起来的那种
EMO_HIGH = [
    "崩溃", "绝望", "撑不住", "扛不住", "受不了了", "受不了", "想死", "活不下去",
    "后悔", "愧疚", "自责", "羞耻", "丢人", "恨", "恶心", "怕", "恐惧", "害怕",
    "哭", "眼泪", "哭了一晚上", "哭了很久", "哭到",
]
# 身体反应：人说不出「我很痛苦」的时候，会说身体。
# 这是最可靠的一类信号——它装不出来。
BODY_REACT = [
    "喘不上气", "喘不过气", "腿软", "腿是软的", "腿都软了", "手抖", "手在抖",
    "发抖", "浑身", "抽空", "被抽空", "空白", "脑子一片空白", "愣住", "愣住了",
    "沉默了很久", "说不出话", "吃不下", "睡不着了", "心慌", "恶心", "想吐",
    "心凉", "凉了半截", "坐不住", "站不住",
]
# 决定宣告：说「我决定了」的时候，事情已经发生了
DECIDE = [
    "我决定", "决定了", "我下定决心", "我想通了", "我不干了", "我不考了",
    "我不去了", "我们离婚", "我们分手", "我发誓", "再也不", "没戏了",
    "我完了", "全完了", "都完了",
]
# 极端否定：这些「没做成」本身是重大事件
FAIL_HARD = [
    "没考上", "没进面", "落榜", "差了几分", "差0.8", "没戏了", "被拒",
    "全拒了", "一个都没", "没通过", "挂了", "没钱了", "供不起", "交不起",
]

AROUSAL_RE = re.compile("|".join(
    sorted(set(EMO_HIGH + BODY_REACT + DECIDE + FAIL_HARD), key=len, reverse=True)))
NOT_AROUSAL = re.compile(r"(考|说|看|吃|做|买|忙|干|写|洗|改|读|完)完了")

# 长度：一段话突然变长，本身就是信号。分位数在 build 阶段标定。
# 技术/工作指令标记。这类文本再长也不是「人生」。
# 真实使用里一个库同时装着「我妈住院了」和「帮我装 cad 插件」，
# 后者动辄一千字，长度信号会把它们全打成刻度。
# 医疗语境词：弱委婉语（「有问题」「不太好」）只有在这些词附近才算病情。
MED_CTX = re.compile(
    r"(身体|检查|查出|查出来|复查|体检|医生|大夫|医院|住院|吃药|化疗|手术|"
    r"病|症状|指标|片子|CT|核磁|血|疼|痛|瘦了|吃不下|"
    r"我妈|我爸|我奶奶|我爷爷|外婆|外公|姥姥|姥爷|老伴|孩子|媳妇|老婆|老公)"
)

TECH_MARK = re.compile(
    r"(@skill:|@scene|@image|@file|@[a-z]+#|```|https?://|"
    r"[A-Za-z]:[\\\\/]|\\.(?:py|md|tsv|json|csv|xlsx|docx|pdf|png|jpg|dat)\\b|"
    r"\\b(?:git|npm|pip|curl|docker)\\b)"
)

LONG = 45
VERY_LONG = 80


# ============================================================
# 2. 情态闸：这句话在断言什么
# ============================================================
# 不收裸「要」：「我们要离婚」是宣告，不是意愿。
INTENT = re.compile(r"(想(?!不)|打算|准备|考虑|琢磨|要不要|该不该|希望能|盼着|改天)")
NEGATED = re.compile(r"(没|没有|不|别|未)(?!错|少|得了)")
COUNTERFACT = re.compile(r"(差点|差一点|几乎|本来|原本|要是|如果|万一|幸好|幸亏)")
REPORTED = re.compile(r"(他|她|他们|同事|朋友|领导|老板|医生|老师|同学|我妈|我爸|家里)说")
REPORTED2 = re.compile(r"(听说|据说|新闻|网上|电视上|说是)")
# 「提了离职」不等于「离职」：提起 ≠ 发生
PROPOSE_ONLY = re.compile(r"(提了|提过|说要|口头)(离职|辞职|分手|离婚)")


def modality(text):
    """返回这句话的情态。优先级：转述 > 未然 > 意愿 > 否定 > 事实。"""
    if REPORTED.search(text) or REPORTED2.search(text):
        return "reported"
    if COUNTERFACT.search(text):
        return "counterfactual"
    if INTENT.search(text):
        return "intent"
    if NEGATED.search(text):
        return "negated"
    return "fact"


CLAUSE_SPLIT = re.compile(r"[，。；！？、,;!?\n]")


def clause_at(text, pos):
    """取 pos 所在的那个小句。

    为什么必须按小句算情态：真实的人不说光秃秃的短句。
    「我妈住院了，医生说要观察几天」——整句含「医生说」，情态被判成转述，
    于是前半句那个真正的事实也被降级，pin 直接没了。
    情态是**局部**属性：说的这句话是什么语气，只跟它所在的那个小句有关。
    """
    start = 0
    for m in CLAUSE_SPLIT.finditer(text):
        if m.start() >= pos:
            return text[start:m.start()]
        start = m.end()
    return text[start:]


# ============================================================
# 3. 主体：这话说的是谁
# ============================================================
SELF = re.compile(r"我|咱|本人|自己")
# 死亡 B 级只认这几类主体。「同事走了」是离职，「我妈走了」才是走了。
KIN_CLOSE = re.compile(
    "|".join(sorted({
        "奶奶", "爷爷", "外婆", "外公", "姥姥", "姥爷", "妈", "爸", "母亲", "父亲",
        "老伴", "老头", "老太太", "老公", "老婆", "丈夫", "妻子", "爱人",
        "哥", "姐", "弟", "妹", "哥哥", "姐姐", "弟弟", "妹妹",
        "儿子", "女儿", "孩子", "孙子", "孙女", "外孙", "叔叔", "舅舅", "姑姑",
        "姨妈", "阿姨", "伯伯", "婶", "表哥", "表姐", "堂哥", "堂姐",
        "他", "她", "老人家", "老人",
    }, key=len, reverse=True)))
# 「我妈朋友的儿子」——隔了一层，不是我妈的事
INTERPOSE = re.compile(r"(的)?(朋友|同事|同学|邻居|亲戚|儿子|女儿|孩子|老公|老婆|他家|她家|家里)")
# 宠物不是人：宠物去世不该占「亲人离世」那个永久位。
# 只收通用词，不收具体名字 —— 曾经把测试人设里的猫名写死在这里，
# 那是拿一条测试数据换了引擎里的一行规则，换谁家的猫都认不出。
PET_SUBJ = re.compile(r"(猫|狗|宠物|它|喵|汪|毛孩子)")

MAJOR_MED = ["手术", "化疗", "放疗", "透析", "病危", "抢救", "确诊", "住院",
             "进ICU", "插管", "截肢", "中风", "脑梗", "心梗", "骨折", "昏迷"]
# 出院、复查、吃药不是危机，把它们算进来会让「我妈出院了」占一个永久位
MAJOR_MED_DROP = {"出院", "复查"}

PATTERNS = [
    (re.compile(r"(离了|分了|散了|掰了|复合了|怀上了|怀了)"), 7, "离散"),
    (re.compile(r"(咳|疼|低烧|发烧|拉肚子|头晕|失眠|睡不着).{0,4}(了)?[一二两三四五六七八九十几半\d]+个?(月|年)"), 6, "慢性症状"),
    (re.compile(r"(记性.{0,3}(差|不好|不行|不如)|老忘|忘事|走丢|找不着家|认不出|老糊涂|糊涂了)"), 7, "记忆衰退"),
    (re.compile(r"(房子|房|车|店|铺子|摊)(卖|买|租|盘)了"), 6, "处置资产"),
    (re.compile(r"欠了.{0,6}(万|千|块|元|\d)"), 6, "欠债"),
    (re.compile(r"判给"), 7, "抚养权"),
    (re.compile(r"(出分了|放榜|录取了|录了)"), 6, "出分"),
    (re.compile(r"(我|妈|爸|奶奶|爷爷|外婆|外公|姥姥|姥爷|老人).{0,3}摔"), 6, "摔倒"),
    (re.compile(r"(出事了|出车祸|被车撞|着火了|被抢)"), 7, "事故"),
    (re.compile(r"(胰岛素|开始打针|长期吃药)"), 7, "长期治疗"),
    (re.compile(r"(签了|签约|签合同|offer)"), 6, "签约"),
    (re.compile(r"(手续|离婚|过户|贷款|签证).{0,4}(办完|办好|办下来)"), 7, "办手续"),
    (re.compile(r"(冷战|没说话).{0,4}[一二两三四五六七八九十几\d]+天"), 6, "持久冷战"),
    (re.compile(r"(拖欠|拖了.{0,6}(工资|钱|稿费)|不给钱|要账)"), 7, "被拖欠"),
    (re.compile(r"(开了药|给我开|吃了一段时间|副作用)"), 6, "就医用药"),
    # 刻度：「最后一次」「再也没」天然不可逆；「第一次」必须接动作，否则「第一次去北京」也中
    (re.compile(r"(最后一次|最后一面|再也没|再没|唯一一次)"), 7, "刻度-终"),
    (re.compile(r"(第一次|头一回|头一次)(见|叫|开口|抱|亲|送|一个人)"), 6, "刻度-初"),
    # 下面这些是 p4 那种"叙述型"老人教会我的
    (re.compile(r"(摔了一跤|摔了一交|摔倒|栽倒)"), 6, "摔倒"),
    (re.compile(r"(车祸|被撞|撞了)"), 8, "车祸"),
    (re.compile(r"(不好的病|不好的东西|长了个东西|长了东西|那个病)"), 8, "隐语-病"),
    (re.compile(r"(磕头|跪下|灵前|上坟|扫墓|坟上|坟前)"), 7, "丧仪"),
    (re.compile(r"(吐了一夜|吐血|便血|晕倒)"), 7, "危急症状"),
    (re.compile(r"(没了|走了).{0,8}(车祸|病|医院|抢救|突然)"), 9, "死亡-补语"),
]
# 只在事实情态下才算的模式（意愿/未然时不算）
FACT_ONLY = {"离散", "处置资产", "欠债", "抚养权", "出分", "摔倒", "事故",
             "签约", "办手续", "被拖欠", "长期治疗"}
# 「他们俩分手了」「听说她爸住院了」——别人的事不该占我的永久位
OTHER_SUBJ = re.compile(r"(他们|她们|他俩|她俩|两人|两个人)")


# ============================================================
# 4. 主判定
# ============================================================
def judge(text, V):
    """返回 dict: pin, score, channel, why"""
    why = []
    ev_score = 0
    ar_score = 0
    mod = modality(text)

    # ---------- 通道 A：事实 ----------
    scored = set()

    # A 级判死：出现即判，不看情态（「他走了」不会因为情态不明就不算）
    for w in V["_death_strong"]:
        if w in text:
            ev_score += 10
            why.append(f"死亡A:{w}")
            scored.add(w)
            break

    # B 级判死：必须有近亲主体，且不是宠物
    for v in ("走了", "没了", "不在了", "老了"):
        if v in text:
            head = text.split(v)[0]
            if KIN_CLOSE.search(head[-8:]) and not PET_SUBJ.search(head[-8:]):
                ev_score += 9
                why.append(f"死亡B:{v}")
                scored.add(v)
            break

    # 硬兜底
    for w in seeds.LOSS_HARD:
        if w in text and w not in scored:
            ev_score += 10
            why.append(f"重病:{w}")
            scored.add(w)
            break

    # 委婉语
    for w in list(seeds.ILLNESS_SOFT) + ["瞒着", "没告诉", "不让说", "先别说"]:
        if w in text and w not in scored:
            ev_score += 8
            why.append(f"委婉:{w}")
            scored.add(w)
            break
    else:
        # 弱委婉语必须沾着医疗或亲人。否则「发现有问题」这种调试用语会被当成报病危。
        for w in getattr(seeds, "ILLNESS_WEAK", []):
            if w in text and w not in scored:
                if MED_CTX.search(text):
                    ev_score += 8
                    why.append(f"委婉弱+语境:{w}")
                    scored.add(w)
                else:
                    why.append(f"委婉弱(无语境，不计):{w}")
                break

    # 重大医疗：去掉出院/复查；宠物不算
    for w in MAJOR_MED:
        if w in text and w not in scored and w not in MAJOR_MED_DROP:
            _cl = clause_at(text, text.find(w))
            _ml = modality(_cl)
            if OTHER_SUBJ.search(_cl) or _ml == "reported" or INTERPOSE.search(text[:text.find(w)][-12:]):
                ev_score += 2
                why.append(f"他人就医:{w}+2")
            elif PET_SUBJ.search(text[:text.find(w)][-6:]):
                ev_score -= 4
                why.append(f"宠物就医:{w}-4")
            else:
                ev_score += 8
                why.append(f"重大医疗:{w}")
            scored.add(w)
            break

    # 不可逆事件：过情态闸
    for w in V["_events"]:
        if w not in text or w in scored:
            continue
        head = text[:text.find(w)][-12:]
        base = 6
        _cl = clause_at(text, text.find(w))
        mod_l = modality(_cl)
        if PROPOSE_ONLY.search(_cl):
            base = 2
            why.append(f"只是提:{w}+2")
        elif mod_l == "intent":
            base = 2
            why.append(f"意愿:{w}+2")
        elif mod_l == "counterfactual":
            base = 1
            why.append(f"未然:{w}+1")
        elif mod_l == "negated":
            base = 2
            why.append(f"否定:{w}+2")
        elif mod_l == "reported":
            base = 1
            why.append(f"转述:{w}+1")
        elif INTERPOSE.search(head):
            base = 1
            why.append(f"隔一层:{w}+1")
        else:
            who = "我" if SELF.search(head) else ("亲" if KIN_CLOSE.search(head) else "默认自己")
            why.append(f"事件+{who}:{w}+6")
        ev_score += base
        scored.add(w)
        break

    # 模式
    for pat, wt, label in PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        if label in FACT_ONLY and mod != "fact":
            ev_score += 1
            why.append(f"{label}(非事实)+1")
        else:
            ev_score += wt
            why.append(f"{label}+{wt}")
        break

    # ---------- 通道 B：唤醒 ----------
    ar_hits = [w for w in AROUSAL_RE.findall(text) if not NOT_AROUSAL.search(text)]
    if ar_hits:
        uniq = list(dict.fromkeys(ar_hits))
        # 身体反应 / 决定 / 极端失败：单独一条就够（这些装不出来）
        strong = [w for w in uniq if w in BODY_REACT or w in DECIDE or w in FAIL_HARD]
        if strong:
            ar_score += 8
            why.append(f"硬唤醒:{strong[0]}+8")
        # 纯情绪词：一条不够，「我有点怕」不该永久占位
        if len(uniq) >= 3:
            ar_score += 6
            why.append(f"情绪x{len(uniq)}+6")
        elif len(uniq) == 2:
            ar_score += 3
            why.append("情绪x2+3")
        elif not strong:
            ar_score += 1
            why.append("情绪x1+1")

    n = len(text)
    # 长度不是独立信号 —— 这条在真实库上翻过车：
    # 43 条里凡是 >=200 字的 4 条全被判成刻度（100%），<30 字的 18 条一条都没判上（0%）。
    # 因为那 4 条是一千字的任务指令，不是人生。
    # 现在的规矩：①必须有个人信号（我/家人/身体反应/已判出的事实）②技术文本不给
    # ③封顶 +5，永远够不到 pin 阈值 7，长度无法单独造出一个刻度。
    personal = bool(SELF.search(text) or KIN_CLOSE.search(text)
                    or PET_SUBJ.search(text) or ar_hits or ev_score > 0)
    tech = bool(TECH_MARK.search(text))
    if personal and not tech:
        if n >= VERY_LONG:
            ar_score += 5
            why.append(f"长叙({n})+5")
        elif n >= LONG:
            ar_score += 3
            why.append(f"长叙({n})+3")
        elif n >= 32:
            ar_score += 2
            why.append(f"长叙({n})+2")
    elif n >= LONG:
        why.append("长叙不计(技术文本)" if tech else "长叙不计(无个人信号)")

    if mod == "fact" and re.search(r"(我|咱)", text) and re.search(r"[，。！？、]", text):
        ar_score += 1                    # 有分句的第一人称叙述，通常是在讲事

    # ---------- 身份 ----------
    id_score = 0
    for p in seeds.IDENTITY_PATTERNS:
        if re.search(p, text):
            id_score += 7
            why.append("身份+7")
            break
    for w in seeds.SELF_DISCLOSURE:
        if w in text:
            id_score += 5
            why.append(f"自我揭示+5")
            break

    if OTHER_SUBJ.search(text):
        ev_score -= 6
        why.append("他人主体-6")
    ev_score = ev_score + id_score
    pin = ev_score >= 6 or ar_score >= 7
    channel = "fact" if ev_score >= 6 else ("arousal" if ar_score >= 7 else "-")
    return dict(pin=pin, ev=ev_score, ar=ar_score, ch=channel,
                mod=mod, why=why)
