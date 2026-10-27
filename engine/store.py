# -*- coding: utf-8 -*-
"""L0：全部原话 + 索引。只追加，不修改，不删除。

三条硬约束：
  1. 只有一条写入路径 add()。pinned 和 kinds 在落盘那一刻定型，之后没人能改。
  2. 没有任何删除接口。想「忘掉」只能降级检索优先级，不能删字节。
  3. 检索不写。recall 是纯函数，不入库、不加权、不改任何字段。

性能设计（这三条是为了「读取不慢」）：
  · 写入时就把 kinds 算好存进 jsonl。读的时候不再跑正则——这是 1.3 秒变 60 毫秒的关键。
  · 落盘一份 pickle 缓存，用 (mtime, size) 做签名。签名一致就跳过解析。
  · 倒排索引（bigram → 行号）在内存里建一次，之后所有检索只扫候选集。
"""
import json
import os
import pickle
from datetime import date, datetime

from . import judge as J
from . import lexicon

EVENTS = "events.jsonl"
CACHE = ".cache.pkl"


class Index:
    """内存倒排索引。检索只碰候选集，不扫全表。"""

    def __init__(self, recs, bigrams):
        self.recs = recs
        self.dates = [r["d"] for r in recs]     # 按日期有序，供时间窗二分
        # 小写副本：二字组已经 lower 了，这里的子串核验也必须一致，
        # 否则「CAD 图纸」能靠二字组拿到分，却过不了最后这道 `sub in text`。
        self.low = [r["text"].lower() for r in recs]
        self.bg = {}            # bigram -> set(行号)
        self.pins = []          # 刻度句的行号
        self.by_year = {}       # 年 -> [行号]
        self.by_kind = {}       # 事件类型 -> [行号]
        n = len(recs)
        # 太常见的 bigram 没有区分度，只会在候选集里灌水。
        # 2000 条或 20% 取大者作为上限。
        self._cap = max(2000, int(n * 0.2))
        for i, r in enumerate(recs):
            for g in bigrams(r["text"]):
                s = self.bg.get(g)
                if s is None:
                    self.bg[g] = s = set()
                if len(s) <= self._cap:
                    s.add(i)
            if r.get("pin"):
                self.pins.append(i)
            self.by_year.setdefault(r["d"].year, []).append(i)
            for k in r.get("kinds", ()):
                self.by_kind.setdefault(k, []).append(i)

    def postings(self, g):
        s = self.bg.get(g)
        if not s or len(s) > self._cap:
            return None
        return s

    def contains(self, sub, bigrams):
        """sub 出现在哪些行（用倒排求交，再逐条核验）。"""
        gs = list(bigrams(sub))
        if not gs:
            return []
        sets = []
        for g in gs:
            s = self.postings(g)
            if s is None:
                return []
            sets.append(s)
        cur = min(sets, key=len)
        for s in sets:
            if s is cur:
                continue
            cur = cur & s
            if not cur:
                return []
        sub_l = sub.lower()
        return [i for i in cur if sub_l in self.low[i]]


class Store:
    def __init__(self, root):
        # 必须展开 ~。不展开的话 Store("~/.remember-me") 会在当前目录下
        # 建一个名字就叫「~」的文件夹，而 README 里写的正是这个用法。
        self.root = os.path.abspath(os.path.expanduser(os.fspath(root)))
        self.path = os.path.join(self.root, EVENTS)
        self.cache_path = os.path.join(root, CACHE)
        self.V = lexicon.load()
        os.makedirs(self.root, exist_ok=True)
        self._mem = None        # (sig, recs, index)

    # ---------- 写 ----------
    def add(self, text, d=None, sync=False):
        text = (text or "").strip().replace("\n", " ")
        if not text:
            return None
        d = d or date.today().isoformat()
        if isinstance(d, date):
            d = d.isoformat()
        j = J.judge(text, self.V)
        from . import axis
        rec = {
            "d": d,
            "text": text,
            "pin": bool(j["pin"]),
            "score": int(max(j["ev"], j["ar"])),
            "ch": j["ch"],
            "kinds": axis.kinds_of(text),      # 写时定型，读时不再算
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if sync:
                f.flush()
                os.fsync(f.fileno())
        self._mem = None                       # 让下次 load 重建
        return rec

    def ingest(self, lines):
        n = 0
        for ln in lines:
            ln = ln.rstrip("\n")
            if not ln.strip():
                continue
            parts = ln.split("\t")
            if len(parts) >= 2 and len(parts[0]) == 10 and parts[0][4] == "-":
                try:
                    datetime.strptime(parts[0], "%Y-%m-%d")
                except ValueError:
                    self.add(ln)
                    n += 1
                    continue
                txt = "\t".join(parts[2:]) if len(parts) >= 3 else parts[1]
                self.add(txt, parts[0])
                n += 1
            else:
                self.add(ln)
                n += 1
        return n

    # ---------- 读 ----------
    def _sig(self):
        try:
            st = os.stat(self.path)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def load(self):
        """返回记录列表。带内存缓存 + 磁盘 pickle 缓存，两级。"""
        sig = self._sig()
        if sig is None:
            return []
        if self._mem and self._mem[0] == sig:
            return self._mem[1]

        recs = None
        try:
            with open(self.cache_path, "rb") as f:
                blob = pickle.load(f)
            if blob.get("sig") == sig:
                recs = blob["recs"]
        except (OSError, pickle.UnpicklingError, EOFError, AttributeError, KeyError):
            recs = None

        if recs is None:
            from . import axis
            recs = []
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    try:
                        r["d"] = datetime.strptime(r["d"], "%Y-%m-%d").date()
                    except (ValueError, KeyError):
                        r["d"] = date(1970, 1, 1)
                    if "kinds" not in r:            # 兼容旧库
                        r["kinds"] = axis.kinds_of(r["text"])
                    recs.append(r)
            recs.sort(key=lambda r: r["d"])
            try:
                tmp = self.cache_path + ".tmp"
                with open(tmp, "wb") as f:
                    pickle.dump({"sig": sig, "recs": recs}, f, protocol=4)
                os.replace(tmp, self.cache_path)
            except OSError:
                pass

        self._mem = (sig, recs)
        return recs

    def index(self):
        """内存倒排索引。第一次调用时建，之后跟着 load 缓存一起复用。"""
        recs = self.load()
        if self._mem and len(self._mem) == 3:
            return self._mem[2]
        from . import axis
        idx = Index(recs, axis.bigrams)
        sig = self._mem[0]
        self._mem = (sig, recs, idx)
        return idx

    def stats(self):
        recs = self.load()
        if not recs:
            return dict(n=0)
        return dict(
            n=len(recs),
            days=len({r["d"] for r in recs}),
            first=recs[0]["d"].isoformat(),
            last=recs[-1]["d"].isoformat(),
            pinned=sum(1 for r in recs if r["pin"]),
            chars=sum(len(r["text"]) for r in recs),
        )
