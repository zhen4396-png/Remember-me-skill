#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UserPromptSubmit 钩子：让 Remember me 全自动工作，不用每次手动调用。

挂在 ~/.workbuddy/settings.json 的 hooks.UserPromptSubmit 上，每轮用户发言时运行一次。

它做两件事：
  1. **总是**把用户这句话原文追加进库（约 0.3ms，不调模型，不解析全库）
  2. **只在问到记忆相关的事时**，从库里取一段横截面打印到 stdout ——
     宿主会把它当附加上下文注入，模型于是"想起来了"

为什么第 2 步要加条件：每轮都注入会把上下文撑满，而且包里 90% 的话
（"帮我改个 bug"）跟人生记忆无关。日常琐事照样入库，只是不主动提。

关闭方式：
  · 全局：从 settings.json 删掉 hooks.UserPromptSubmit 这一段
  · 单个目录：在该目录下建一个空文件 `.remember-me-disable`
  · 临时：设环境变量 REMEMBER_ME_HOOK=off

退出码永远是 0 —— 钩子失败绝不能挡住用户说话。
"""
import json
import os
import re
import sys
import time

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.environ.get("REMEMBER_ME_HOME") or os.path.expanduser("~/.remember-me")
_T0 = time.perf_counter()   # 进程内起点，用来记「钩子自己花了多久」

DISABLE_MARK = ".remember-me-disable"

# 什么算"在问记忆"。这个表要窄：误触发的代价是上下文里多一段没用的原话，
# 漏触发的代价是它明明记得却不说话。宁可窄一点，配合主动提问。
CUES = re.compile(
    r"记得|还记得|记不记得|以前说|之前说|上次说|我说过|我提过|提过|"
    r"那年|那次|那年那月|什么时候|哪一年|当年|后来怎么样|后来呢|"
    r"你还知道|我跟你说过|我们聊过"
)


def _sanitize(s):
    """去掉孤立代理对（lone surrogate，如 U+DCAD）。

    这些字符来自宿主以非 UTF-8 编码把 prompt 写进 stdin 时、被 surrogateescape
    解码成的坏字节。它们无法再编码回 UTF-8，会让 store.add 的 json.dumps 崩溃、
    记忆被静默丢弃。这里先尝试把 surrogateescape 的字节还原成真实 UTF-8，失败就
    直接丢弃坏字符——宁可丢一个字，也不能丢整条记忆。
    """
    if not s:
        return s
    try:
        return s.encode("utf-8", "surrogateescape").decode("utf-8")
    except Exception:
        return s.encode("utf-8", "ignore").decode("utf-8", "ignore")


def _log(msg):
    """日志写 stderr，不污染 stdout —— stdout 会被宿主当钩子输出解析。"""
    try:
        sys.stderr.write(f"[remember-me] {msg}\n")
    except Exception:
        pass
    try:
        os.makedirs(HOME, exist_ok=True)
        with open(os.path.join(HOME, "hook.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
    except Exception:
        pass


def _emit(text):
    """把文本作为附加上下文交给宿主。

    必须是这个 JSON 结构，不能直接 print 文本：
    官方文档写明 UserPromptSubmit 的 stdout 走 `hookSpecificOutput.additionalContext`。

    而且必须按字节写 UTF-8。Windows 上 sys.stdout 是 cp936，
    直接 print 中文会乱码或抛 UnicodeEncodeError。
    """
    data = json.dumps({
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": text,
        },
    }, ensure_ascii=False)
    out = sys.stdout.buffer if hasattr(sys.stdout, "buffer") else sys.stdout
    try:
        out.write(data.encode("utf-8"))
        out.flush()
    except Exception as e:
        _log(f"输出失败：{e}")


def main():
    # ---------- 读 payload ----------
    # 必须按字节读、显式 UTF-8 解码。
    # sys.stdin.read() 在 Windows 上走 locale（cp936），宿主送的是 UTF-8：
    # 「测试」三个字节会被解成「娴嬭瘯」，写库时还可能抛 surrogates not allowed。
    # 这个坑第一轮真踩了，库里留了两条乱码。
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", "replace")
        payload = json.loads(raw) if raw.strip() else {}
    except Exception as e:
        _log(f"payload 解析失败：{e}")
        return 0

    prompt = _sanitize((payload.get("prompt") or "").strip())
    cwd = payload.get("cwd") or os.getcwd()

    if not prompt:
        return 0
    # 斜杠命令、系统注入不算用户的话
    if prompt.startswith("/") or prompt.startswith("<"):
        return 0
    if os.environ.get("REMEMBER_ME_HOOK", "").lower() in ("off", "0", "false"):
        return 0
    if os.path.exists(os.path.join(cwd, DISABLE_MARK)):
        return 0

    sys.path.insert(0, SKILL_DIR)
    try:
        from engine.store import Store
        from engine import axis
    except Exception as e:
        _log(f"引擎加载失败：{e}")
        return 0

    # ---------- 1. 需要时先取记忆横截面 ----------
    # 必须在写入之前取：否则刚说的这句会被自己检索出来，上下文里出现"你还记得我妈身体怎么样吗"
    # 这种自我回声，既没用又占地方。
    try:
        st = Store(HOME)
    except Exception as e:
        _log(f"库初始化失败：{e}")
        return 0

    injected = 0
    if CUES.search(prompt):
        try:
            recs = st.load()
            if recs:
                block = axis.render(recs, prompt, idx=st.index(), with_spine=True)
                _emit(block)
                injected = len(block)
        except Exception as e:
            _log(f"召回失败：{e}")

    # ---------- 2. 存原话 ----------
    stored = 0
    skipped = False
    is_query = False
    try:
        from engine import judge as _J
        # 追问记忆的话本身不是记忆。
        # 「你还记得老陈是怎么走的吗」如果入库，下一句「你还记得我养过狗吗」
        # 就会匹配到**上一个问句**——检索到的全是自己问过的话，不是她说过的事。
        # 判据：命中追问句式 + 短 + 判定器认为不含刻度，三者同时满足才跳过。
        # 加「短」这一条是为了不误伤「你还记得我妈住院吗？她今天出院了」。
        is_query = (CUES.search(prompt) and len(prompt) <= 30
                    and not _J.judge(prompt, st.V)["pin"])
        if is_query:
            skipped = True
        elif _last_record(st.path) == prompt:
            # 免重：宿主偶尔会重发同一句
            skipped = True
        else:
            st.add(prompt)
            stored = len(prompt)
    except Exception as e:
        _log(f"写入失败：{e}")

    ms = int((time.perf_counter() - _T0) * 1000)
    if stored:
        _log(f"OK 存={stored}字 注入={injected}字 耗时={ms}ms | {prompt[:24]}")
    elif skipped:
        why = "跳过(纯追问)" if is_query else "去重跳过"
        _log(f"{why} 注入={injected}字 耗时={ms}ms | {prompt[:24]}")
    return 0


def _last_record(path):
    """读最后一行原文，用于免重。只读文件尾，不解析全库。"""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 4096))
            tail = f.read().decode("utf-8", "replace").strip().splitlines()
        if not tail:
            return None
        return json.loads(tail[-1]).get("text")
    except Exception:
        return None


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:                      # 钩子绝不能挡住用户
        _log(f"未捕获异常：{e}")
        sys.exit(0)
