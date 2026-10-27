# -*- coding: utf-8 -*-
"""词表加载。运行时只有一个 json，不依赖任何语料文件。"""
import json
import os

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
_CACHE = {}


def load(path=None):
    p = path or os.path.join(ASSETS, "lexicon.json")
    if p in _CACHE:
        return _CACHE[p]
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    V = data["lexicon"]
    # 旧版产物可能缺派生字段，这里兜一下
    V.setdefault("_death_strong", [])
    V.setdefault("_events", V.get("les_event", []))
    _CACHE[p] = V
    return V


def meta(path=None):
    """lexicon.json 的 meta 段。跟着 load() 走同一个缓存，不重复读文件。"""
    p = path or os.path.join(ASSETS, "lexicon.json")
    key = (p, "meta")
    if key not in _CACHE:
        with open(p, encoding="utf-8") as f:
            _CACHE[key] = json.load(f).get("meta", {})
    return _CACHE[key]
