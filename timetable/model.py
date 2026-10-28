"""時間割作成で使うデータの形。"""
from __future__ import annotations

from dataclasses import dataclass, field

SUBJECTS = ["英語", "数学", "物理", "化学", "国語"]
FORMS = ["集団", "個別"]


@dataclass(frozen=True)
class Koma:
    no: int
    start: str
    end: str


@dataclass(frozen=True)
class Slot:
    day: str
    koma: int

    @property
    def label(self) -> str:
        return f"{self.day}{self.koma}"


@dataclass
class Student:
    id: str
    name: str
    grade: str
    available: set[Slot] = field(default_factory=set)

    @property
    def label(self) -> str:
        """同姓同名でも見分けられる表示名（例：木村悠真（高1・S015））。"""
        return f"{self.name}（{self.grade}・{self.id}）"


@dataclass
class Teacher:
    id: str
    name: str
    subjects: set[str]
    can_group: bool
    can_individual: bool
    max_komas: int | None
    available: set[Slot] = field(default_factory=set)


@dataclass
class Request:
    """1生徒×1科目の受講希望。"""
    index: int
    student_id: str
    subject: str
    form: str
    times: int
    preferred_teacher: str | None


@dataclass
class Settings:
    days: list[str]
    komas: list[Koma]
    individual_booths: int
    group_rooms: int
    max_students_per_teacher: int
    allow_mixed_subjects: bool
    group_capacity: int
    time_limit_seconds: float
    weights: dict[str, int]

    @property
    def slots(self) -> list[Slot]:
        return [Slot(d, k.no) for d in self.days for k in self.komas]


@dataclass
class Problem:
    settings: Settings
    students: dict[str, Student]
    teachers: dict[str, Teacher]
    requests: list[Request]


@dataclass
class Lesson:
    """時間割上の1つの授業（1コマ）。"""
    slot: Slot
    form: str
    subject: str
    teacher_id: str
    student_ids: list[str]
    room: str = ""
    # 個別で科目が混ざる場合に、生徒ごとの科目を持つ（生徒ID → 科目）
    student_subjects: dict[str, str] = field(default_factory=dict)
    class_name: str = ""


@dataclass
class Unassigned:
    request: Request
    missing: int
    reason: str


@dataclass
class Result:
    status: str
    lessons: list[Lesson]
    unassigned: list[Unassigned]
    objective: float | None = None
