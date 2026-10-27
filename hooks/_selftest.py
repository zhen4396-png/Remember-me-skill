# -*- coding: utf-8 -*-
"""钩子的本地自测：不挂到宿主上也能验。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "remember_hook.py")
PY = sys.executable

MSGS = [
    ("我妈住院了，医生说要观察几天", False),
    ("今天下雨了路上好堵", False),
    ("猫又把杯子推下去了", False),
    ("你还记得我妈身体怎么样吗", True),
    ("/clear", False),
    ("医生说我妈住院了，是转述不是事实", False),
]

# 孤立代理字符（宿主 JSON 里以 \udcad 转义送来的坏字节）。
# 不处理的话 json.dumps 会抛 surrogates not allowed，整条记忆被静默丢弃。
SURROGATE_RAW = r'{"prompt": "我差点辞职\udcad后来留下了", "cwd": "."}'



def main():
    home = tempfile.mkdtemp(prefix="rm-hook-")
    try:
        for text, expect_out in MSGS:
            payload = json.dumps({"prompt": text, "cwd": home}, ensure_ascii=False)
            r = subprocess.run([PY, HOOK], input=payload, capture_output=True,
                               text=True, encoding="utf-8",
                               env={**os.environ, "REMEMBER_ME_HOME": home})
            out = (r.stdout or "").strip()
            ctx = ""
            ok_json = True
            if out:
                try:
                    obj = json.loads(out)
                    ctx = (obj.get("hookSpecificOutput") or {}).get("additionalContext") or ""
                    ok_json = obj.get("hookSpecificOutput", {}).get("hookEventName") == "UserPromptSubmit"
                except Exception:
                    ok_json = False        # 裸文本 → 宿主注入不了
            got = bool(ctx)
            flag = "OK " if (got == expect_out and ok_json and r.returncode == 0) else "FAIL"
            print(f"[{flag}] 注入={got!s:<5} JSON={ok_json!s:<5} 退出={r.returncode}  {text}")
            if ctx:
                for ln in ctx.splitlines():
                    print("        " + ln)

        print("\n--- 库内容 ---")
        path = os.path.join(home, "events.jsonl")
        rows = []
        if os.path.exists(path):
            for ln in open(path, encoding="utf-8"):
                r = json.loads(ln)
                rows.append(r)
                print(("★" if r["pin"] else " "), r["d"], r["text"])
        else:
            print("（空）")

        # 追问记忆的话本身不是记忆。
        # 如果入库，下一句「你还记得…」会匹配到上一个问句，检索到的全是自己问过的话。
        stored = [r["text"] for r in rows]
        print(f"\n[{'OK ' if '你还记得我妈身体怎么样吗' not in stored else 'FAIL'}]"
              f" 纯追问不入库（库里 {len(stored)} 条，没有那句问话）")

        # 代理字符：必须不崩、必须落库（宁可丢一个字，也不能丢整条记忆）
        r = subprocess.run([PY, HOOK], input=SURROGATE_RAW, capture_output=True,
                           text=True, encoding="utf-8",
                           env={**os.environ, "REMEMBER_ME_HOME": home})
        print(f"\n[{'OK ' if r.returncode == 0 else 'FAIL'}] 孤立代理字符不崩溃，退出={r.returncode}")

        print("\n--- .remember-me-disable 门 ---")
        open(os.path.join(home, ".remember-me-disable"), "w").close()
        n_before = sum(1 for _ in open(path, encoding="utf-8"))
        subprocess.run([PY, HOOK], input=json.dumps({"prompt": "这句话不该入库", "cwd": home},
                                                    ensure_ascii=False),
                       capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "REMEMBER_ME_HOME": home})
        n_after = sum(1 for _ in open(path, encoding="utf-8"))
        print(f"禁用标记生效：{n_before} → {n_after}  {'OK' if n_before == n_after else 'FAIL'}")
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
