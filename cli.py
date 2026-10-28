"""画面なしで時間割を作る。

使い方: python cli.py 入力.xlsx 出力.xlsx
       python cli.py "https://docs.google.com/spreadsheets/d/..." 出力.xlsx
"""
import sys
import time
from pathlib import Path

from timetable.loader import load_settings, parse, read_google_sheet, read_xlsx
from timetable.output import to_xlsx, unassigned_table
from timetable.solver import solve


def main(src: str, dst: str) -> int:
    settings = load_settings(Path(__file__).with_name("config.toml"))
    dfs = read_google_sheet(src) if src.startswith("http") else read_xlsx(src)
    problem, notes = parse(dfs, settings)
    for n in notes:
        print("注意:", n)
    if problem is None:
        return 1
    t0 = time.time()
    result = solve(problem)
    total = sum(r.times for r in problem.requests)
    missing = sum(u.missing for u in result.unassigned)
    print(f"{result.status}（{time.time() - t0:.1f}秒）: 希望{total}コマ中 {total - missing}コマを配置、授業{len(result.lessons)}件")
    if result.unassigned:
        print(unassigned_table(problem, result).to_string(index=False))
    Path(dst).write_bytes(to_xlsx(problem, result))
    print(f"{dst} に書き出しました")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
