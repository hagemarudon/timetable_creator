"""OR-Tools (CP-SAT) で時間割を組む。

必須条件は制約として必ず守り、優先条件は目的関数の点数で調整する。
入りきらない授業は「未配置」として理由つきで返す。
"""
from __future__ import annotations

import math
from collections import defaultdict

from ortools.sat.python import cp_model

from .model import Lesson, Problem, Request, Result, Slot, Unassigned


def _group_key(problem: Problem, r: Request) -> tuple[str, str]:
    return (r.subject, problem.students[r.student_id].grade)


def solve(problem: Problem) -> Result:
    s = problem.settings
    w = s.weights
    slots = s.slots
    students, teachers = problem.students, problem.teachers
    m = cp_model.CpModel()

    # 生徒・講師が各コマで入っている授業の変数
    student_busy: dict[tuple[str, Slot], list] = defaultdict(list)
    teacher_busy: dict[tuple[str, Slot], list] = defaultdict(list)
    assigned_terms: list = []        # 入った授業1回ごと
    bonus_terms: list = []           # 加点
    penalty_terms: list = []         # 減点（係数, 変数）

    # ---------------- 個別授業 ----------------
    ind_reqs = [r for r in problem.requests if r.form == "個別"]
    x: dict[tuple[int, str, Slot], cp_model.IntVar] = {}
    ind_by_ts: dict[tuple[str, Slot], list] = defaultdict(list)
    ind_by_ts_subject: dict[tuple[str, Slot, str], list] = defaultdict(list)
    for r in ind_reqs:
        st = students[r.student_id]
        elig = [t for t in teachers.values() if t.can_individual and r.subject in t.subjects]
        per_req = []
        for t in elig:
            used_t = []
            for sl in sorted(st.available & t.available, key=slots.index):
                v = m.NewBoolVar(f"x_{r.index}_{t.id}_{sl.label}")
                x[r.index, t.id, sl] = v
                per_req.append(v)
                used_t.append(v)
                student_busy[r.student_id, sl].append(v)
                ind_by_ts[t.id, sl].append(v)
                ind_by_ts_subject[t.id, sl, r.subject].append(v)
                if r.preferred_teacher == t.id:
                    bonus_terms.append((w["preferred_teacher"], v))
            if used_t:
                # 講師が何人目かを数えるための変数（毎回同じ講師を優先）
                u = m.NewBoolVar(f"u_{r.index}_{t.id}")
                for v in used_t:
                    m.AddImplication(v, u)
                penalty_terms.append((w["same_teacher"], u))
        m.Add(sum(per_req) <= r.times)
        assigned_terms.extend(per_req)
        for sl in r.fixed:
            pinned = x.get((r.index, r.preferred_teacher, sl))
            at_sl = [pinned] if pinned is not None else [v for (ri, _, sl2), v in x.items() if ri == r.index and sl2 == sl]
            if at_sl:
                m.Add(sum(at_sl) == 1)
        for d in s.days:
            day_vars = [v for (ri, _, sl), v in x.items() if ri == r.index and sl.day == d]
            if len(day_vars) > 1:
                rep = m.NewIntVar(0, len(day_vars), f"rep_{r.index}_{d}")
                m.Add(rep >= sum(day_vars) - 1)
                penalty_terms.append((w["same_day_repeat"], rep))

    # 講師が個別授業をしているコマ（= ブースを1つ使う）
    y: dict[tuple[str, Slot], cp_model.IntVar] = {}
    for (tid, sl), vs in ind_by_ts.items():
        yv = m.NewBoolVar(f"y_{tid}_{sl.label}")
        y[tid, sl] = yv
        m.Add(sum(vs) <= s.max_students_per_teacher * yv)
        m.Add(sum(vs) >= yv)
        teacher_busy[tid, sl].append(yv)
        if not s.allow_mixed_subjects:
            subj_vars = []
            for (t2, sl2, subj), svs in ind_by_ts_subject.items():
                if t2 == tid and sl2 == sl:
                    z = m.NewBoolVar(f"ys_{tid}_{sl.label}_{subj}")
                    for v in svs:
                        m.AddImplication(v, z)
                    subj_vars.append(z)
            m.Add(sum(subj_vars) <= 1)
    for sl in slots:
        booth_vars = [yv for (tid, sl2), yv in y.items() if sl2 == sl]
        if booth_vars:
            m.Add(sum(booth_vars) <= s.individual_booths)

    # ---------------- 集団授業 ----------------
    # 科目×学年でクラスを作り、定員を超える場合は複数クラスに分ける
    grp_reqs: dict[tuple[str, str], list[Request]] = defaultdict(list)
    for r in problem.requests:
        if r.form == "集団":
            grp_reqs[_group_key(problem, r)].append(r)

    sections: list[dict] = []
    g: dict[tuple[int, str, Slot], cp_model.IntVar] = {}
    att: dict[tuple[int, int, Slot], cp_model.IntVar] = {}
    member: dict[tuple[int, int], cp_model.IntVar] = {}
    for (subj, grade), reqs in grp_reqs.items():
        n_sec = max(1, math.ceil(len(reqs) / s.group_capacity))
        times = max(r.times for r in reqs)
        elig = [t for t in teachers.values() if t.can_group and subj in t.subjects]
        sec_ids = []
        for k in range(n_sec):
            ci = len(sections)
            name = f"{subj} {grade}" + (f" {chr(ord('A') + k)}組" if n_sec > 1 else "")
            sections.append({"subject": subj, "grade": grade, "name": name, "reqs": reqs})
            sec_ids.append(ci)
            held = []
            for sl in slots:
                at_slot = []
                for t in elig:
                    if sl in t.available:
                        v = m.NewBoolVar(f"g_{ci}_{t.id}_{sl.label}")
                        g[ci, t.id, sl] = v
                        at_slot.append(v)
                        teacher_busy[t.id, sl].append(v)
                        penalty_terms.append((1, v))  # 誰も来ない授業を作らない
                if at_slot:
                    m.Add(sum(at_slot) <= 1)
                    held.extend(at_slot)
            m.Add(sum(held) <= times)
            for r in reqs:
                mv = m.NewBoolVar(f"m_{r.index}_{ci}")
                member[r.index, ci] = mv
                for sl in students[r.student_id].available:
                    gs = [g[ci, t.id, sl] for t in elig if (ci, t.id, sl) in g]
                    if not gs:
                        continue
                    a = m.NewBoolVar(f"a_{r.index}_{ci}_{sl.label}")
                    att[r.index, ci, sl] = a
                    m.AddImplication(a, mv)
                    m.Add(a <= sum(gs))
                    student_busy[r.student_id, sl].append(a)
                    assigned_terms.append(a)
            m.Add(sum(member[r.index, ci] for r in reqs) <= s.group_capacity)
        for r in reqs:
            m.AddExactlyOne(member[r.index, ci] for ci in sec_ids)
            mine = [a for (ri, ci, _), a in att.items() if ri == r.index]
            m.Add(sum(mine) <= r.times)
            for sl in r.fixed:
                at_sl = [a for (ri, _, sl2), a in att.items() if ri == r.index and sl2 == sl]
                if at_sl:
                    m.Add(sum(at_sl) == 1)
            for d in s.days:
                day_vars = [a for (ri, _, sl), a in att.items() if ri == r.index and sl.day == d]
                if len(day_vars) > 1:
                    rep = m.NewIntVar(0, len(day_vars), f"grep_{r.index}_{d}")
                    m.Add(rep >= sum(day_vars) - 1)
                    penalty_terms.append((w["same_day_repeat"], rep))
        # 同じ科目・学年のクラスの並び順を固定して、同じ答えの探索を省く
        for a_ci, b_ci in zip(sec_ids, sec_ids[1:]):
            m.Add(sum(member[r.index, a_ci] for r in reqs) >= sum(member[r.index, b_ci] for r in reqs))

    for sl in slots:
        room_vars = [v for (ci, tid, sl2), v in g.items() if sl2 == sl]
        if room_vars:
            m.Add(sum(room_vars) <= s.group_rooms)

    # ---------------- 生徒・講師の重複禁止と優先条件 ----------------
    busy_expr: dict[tuple[str, Slot], object] = {}
    for (sid, sl), vs in student_busy.items():
        m.Add(sum(vs) <= 1)
        busy_expr[sid, sl] = sum(vs)

    for (tid, sl), vs in teacher_busy.items():
        m.Add(sum(vs) <= 1)
    for t in teachers.values():
        all_t = [v for (tid, _), vs in teacher_busy.items() if tid == t.id for v in vs]
        if t.max_komas is not None and all_t:
            m.Add(sum(all_t) <= t.max_komas)
        for d in s.days:
            day_t = [v for (tid, sl), vs in teacher_busy.items() if tid == t.id and sl.day == d for v in vs]
            if day_t:
                wd = m.NewBoolVar(f"wd_{t.id}_{d}")
                for v in day_t:
                    m.AddImplication(v, wd)
                penalty_terms.append((w["teacher_work_day"], wd))

    # 生徒・講師の1日の授業は必ず連続させる（間に空きコマを作らない）
    # 授業のかたまりの始まりを数え、1日に1つまでにする
    komas = [k.no for k in s.komas]
    teacher_expr = {key: sum(vs) for key, vs in teacher_busy.items()}
    for kind, people, expr in (("s", students, busy_expr), ("t", teachers, teacher_expr)):
        for pid in people:
            for d in s.days:
                day_busy = [expr.get((pid, Slot(d, k)), 0) for k in komas]
                if sum(1 for b in day_busy if not isinstance(b, int)) < 2:
                    continue
                starts = []
                for i, b in enumerate(day_busy):
                    prev = day_busy[i - 1] if i > 0 else 0
                    st_v = m.NewBoolVar(f"start_{kind}_{pid}_{d}_{i}")
                    m.Add(st_v >= b - prev)
                    starts.append(st_v)
                m.Add(sum(starts) <= 1)

    m.Maximize(
        w["assigned_lesson"] * sum(assigned_terms)
        + sum(c * v for c, v in bonus_terms)
        - sum(c * v for c, v in penalty_terms)
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = s.time_limit_seconds
    solver.parameters.num_workers = 8
    code = solver.Solve(m)
    status = {cp_model.OPTIMAL: "最適解", cp_model.FEASIBLE: "時間内の最良解"}.get(code)
    if status is None:
        reason = ("固定したコマなどの必須条件を同時に満たせません" if code == cp_model.INFEASIBLE
                  else "計算が時間内に終わりませんでした")
        return Result("解けませんでした", [], [Unassigned(r, r.times, reason) for r in problem.requests])

    # ---------------- 結果の取り出し ----------------
    lessons: list[Lesson] = []
    for (tid, sl), yv in y.items():
        if not solver.Value(yv):
            continue
        reqs = [problem.requests[ri] for (ri, t2, sl2), v in x.items() if t2 == tid and sl2 == sl and solver.Value(v)]
        subjects = sorted({r.subject for r in reqs})
        lessons.append(Lesson(sl, "個別", "・".join(subjects), tid, [r.student_id for r in reqs],
                              student_subjects={r.student_id: r.subject for r in reqs}))
    for (ci, tid, sl), v in g.items():
        if not solver.Value(v):
            continue
        sec = sections[ci]
        sids = [r.student_id for r in sec["reqs"] if (r.index, ci, sl) in att and solver.Value(att[r.index, ci, sl])]
        lessons.append(Lesson(sl, "集団", sec["subject"], tid, sids, class_name=sec["name"],
                              student_subjects={sid: sec["subject"] for sid in sids}))

    # 教室・ブースの番号を振る
    by_slot: dict[Slot, list[Lesson]] = defaultdict(list)
    for ls in lessons:
        by_slot[ls.slot].append(ls)
    for sl, ls_list in by_slot.items():
        gi = ii = 0
        for ls in sorted(ls_list, key=lambda z: (z.form, z.teacher_id)):
            if ls.form == "集団":
                gi += 1
                ls.room = f"集団教室{gi}"
            else:
                ii += 1
                ls.room = f"ブース{ii}"
    lessons.sort(key=lambda z: (slots.index(z.slot), z.room))

    unassigned: list[Unassigned] = []
    for r in problem.requests:
        if r.form == "個別":
            got = sum(solver.Value(v) for (ri, _, _), v in x.items() if ri == r.index)
        else:
            got = sum(solver.Value(a) for (ri, _, _), a in att.items() if ri == r.index)
        if got < r.times:
            unassigned.append(Unassigned(r, r.times - got, _reason(problem, r)))

    return Result(status, lessons, unassigned, solver.ObjectiveValue())


def _reason(problem: Problem, r: Request) -> str:
    """入らなかった理由を、入力データから分かる範囲で推定する。"""
    st = problem.students[r.student_id]
    if r.form == "個別":
        elig = [t for t in problem.teachers.values() if t.can_individual and r.subject in t.subjects]
    else:
        elig = [t for t in problem.teachers.values() if t.can_group and r.subject in t.subjects]
    if not elig:
        return f"{r.subject}（{r.form}）を担当できる講師がいない"
    common = set().union(*(st.available & t.available for t in elig))
    if not common:
        return f"生徒の空き時間に、{r.subject}の担当講師が空いていない"
    if len(common) < r.times:
        labels = "・".join(sl.label for sl in sorted(common, key=problem.settings.slots.index))
        return f"生徒と担当講師の共通の空きコマが{len(common)}コマ（{labels}）しかない"
    total = sum(q.times for q in problem.requests if q.student_id == r.student_id)
    if len(st.available) < total:
        return f"生徒の空きコマ（{len(st.available)}）が受講回数の合計（{total}）より少ない"
    if r.form == "集団":
        return "同じクラスの他の生徒と時間が合わなかった、教室・講師が足りない、または授業を連続させる条件で入らなかった"
    return "他の授業とコマ・ブース・講師を取り合った、または授業を連続させる条件で入らなかった"
