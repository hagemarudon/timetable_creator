"""動作確認用のサンプル入力（架空の生徒30人・講師8人）を作る。

使い方: python make_sample.py sample/サンプル入力.xlsx
Googleスプレッドシートにアップロードすれば、そのまま入力の見本になります。
"""
import random
import sys
from pathlib import Path

import pandas as pd

from timetable.loader import load_settings
from timetable.model import SUBJECTS

random.seed(7)
settings = load_settings(Path(__file__).with_name("config.toml"))
slot_labels = [s.label for s in settings.slots]

LAST = ["佐藤", "鈴木", "高橋", "田中", "伊藤", "渡辺", "山本", "中村", "小林", "加藤", "吉田", "山田", "松本", "井上", "木村"]
FIRST = ["蓮", "陽翔", "結衣", "葵", "湊", "陽葵", "大和", "凛", "悠真", "美咲", "颯太", "芽依", "樹", "心春", "海斗"]
GRADES = ["中3", "高1", "高2", "高3"]


def name(i):
    return LAST[i % len(LAST)] + FIRST[(i * 7 + i // len(LAST)) % len(FIRST)]


def availability(n_days, komas_from):
    days = random.sample(settings.days, n_days)
    return {f"{d}{k.no}" for d in days for k in settings.komas if k.no >= komas_from}


teachers = [
    ("T001", ["英語"], True, True),
    ("T002", ["数学"], True, True),
    ("T003", ["数学", "物理"], False, True),
    ("T004", ["物理", "化学"], True, True),
    ("T005", ["化学"], False, True),
    ("T006", ["国語"], True, True),
    ("T007", ["英語", "国語"], False, True),
    ("T008", ["数学", "英語"], False, True),
]
t_rows, t_av_rows = [], []
for i, (tid, subs, grp, ind) in enumerate(teachers):
    nm = LAST[(i + 5) % len(LAST)] + "先生"
    row = {"講師ID": tid, "氏名": nm}
    row.update({s: "○" if s in subs else "" for s in SUBJECTS})
    row.update({"集団可": "○" if grp else "", "個別可": "○" if ind else "", "週の上限コマ": random.choice([8, 10, 12])})
    t_rows.append(row)
    av = availability(random.choice([3, 4, 5]), 1)
    t_av_rows.append({"講師ID": tid, "氏名": nm, **{c: "○" if c in av else "" for c in slot_labels}})

req_rows, s_av_rows = [], []
for i in range(30):
    sid = f"S{i + 1:03d}"
    nm = name(i)
    grade = random.choice(GRADES)
    subs = random.sample([s for s in SUBJECTS if not (grade == "中3" and s in ("物理", "化学"))], random.choice([1, 2, 2, 3]))
    for subj in subs:
        form = random.choice(["集団", "個別", "個別"])
        pref = ""
        if form == "個別" and random.random() < 0.3:
            pref = random.choice([t[0] for t in teachers if subj in t[1]])
        req_rows.append({"生徒ID": sid, "氏名": nm, "学年": grade, "科目": subj, "形式": form,
                         "週の回数": random.choice([1, 1, 2]), "希望講師（任意）": pref})
    av = availability(random.choice([2, 3, 4]), random.choice([1, 2]))
    s_av_rows.append({"生徒ID": sid, "氏名": nm, **{c: "○" if c in av else "" for c in slot_labels}})

koma_rows = [{"コマ": k.no, "開始": k.start, "終了": k.end} for k in settings.komas]

out = Path(sys.argv[1] if len(sys.argv) > 1 else "sample/サンプル入力.xlsx")
out.parent.mkdir(parents=True, exist_ok=True)
with pd.ExcelWriter(out, engine="openpyxl") as xw:
    pd.DataFrame(koma_rows).to_excel(xw, sheet_name="コマ設定", index=False)
    pd.DataFrame(req_rows).to_excel(xw, sheet_name="生徒_受講希望", index=False)
    pd.DataFrame(s_av_rows).to_excel(xw, sheet_name="生徒_空き時間", index=False)
    pd.DataFrame(t_rows).to_excel(xw, sheet_name="講師_担当可能科目", index=False)
    pd.DataFrame(t_av_rows).to_excel(xw, sheet_name="講師_空き時間", index=False)
print(f"{out} を作りました（生徒{len(s_av_rows)}人・受講希望{len(req_rows)}件・講師{len(t_rows)}人）")
