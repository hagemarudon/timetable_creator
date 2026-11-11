"""時間割作成で使うデータの形。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

FORMS = ["集団", "個別"]
WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]

# 時間割の種類
MODE_WEEKLY = "通常期"   # 毎週同じ曜日・コマの時間割（曜日ごと）
MODE_SEASON = "講習期"   # 冬期・夏期・春期講習など、期間中の日付ごとの時間割
MODES = [MODE_WEEKLY, MODE_SEASON]


def date_label(d: date) -> str:
    """講習期の日の書き方（例：12/24(木)）。空き時間の列は「12/24(木)1」「12/24(木)16:00」になる。"""
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


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
    # 必ずこのコマに入れる（入力の「固定」列）。希望講師があれば、その講師で固定する
    fixed: list[Slot] = field(default_factory=list)


@dataclass
class Season:
    """講習期の期間とコマ割。期間の日付から休みの曜日・休みの日を除いた日に授業を入れる。"""
    name: str
    start: date
    end: date
    komas: list[Koma]
    closed_weekdays: list[str] = field(default_factory=list)
    closed_dates: list[date] = field(default_factory=list)

    def all_dates(self) -> list[date]:
        """期間のすべての日付（休みも含む）。"""
        n = (self.end - self.start).days + 1
        return [self.start + timedelta(days=i) for i in range(max(n, 0))]

    def dates(self) -> list[date]:
        """授業をする日付。"""
        closed = set(self.closed_dates)
        return [d for d in self.all_dates()
                if WEEKDAYS[d.weekday()] not in self.closed_weekdays and d not in closed]

    @property
    def days(self) -> list[str]:
        return [date_label(d) for d in self.dates()]


@dataclass
class Settings:
    """時間割の条件。

    days と komas は、今の時間割の種類（mode）の開講日とコマ割を返す。
    通常期は weekdays（曜日）と weekly_komas、講習期は season の日付とコマ割で、両方を別々に持つ。
    """
    weekdays: list[str]
    weekly_komas: list[Koma]
    individual_booths: int
    group_rooms: int
    max_students_per_teacher: int
    allow_mixed_subjects: bool
    group_capacity: int
    time_limit_seconds: float
    weights: dict[str, int]
    season: Season
    mode: str = MODE_WEEKLY

    @property
    def is_season(self) -> bool:
        return self.mode == MODE_SEASON

    @property
    def days(self) -> list[str]:
        return self.season.days if self.is_season else self.weekdays

    @days.setter
    def days(self, value: list[str]) -> None:
        if self.is_season:
            raise ValueError("講習期の開講日は期間と休みの日（season）で決めます。")
        self.weekdays = list(value)

    @property
    def komas(self) -> list[Koma]:
        return self.season.komas if self.is_season else self.weekly_komas

    @komas.setter
    def komas(self, value: list[Koma]) -> None:
        if self.is_season:
            self.season.komas = list(value)
        else:
            self.weekly_komas = list(value)

    @property
    def count_column(self) -> str:
        """「生徒_受講希望」の回数の列。通常期は1週間の回数、講習期は講習期間全体の回数。"""
        return "回数" if self.is_season else "週の回数"

    @property
    def limit_column(self) -> str:
        """「講師_担当可能科目」の上限コマの列。通常期は1週間、講習期は講習期間全体。"""
        return "上限コマ" if self.is_season else "週の上限コマ"

    @property
    def period(self) -> str:
        """回数や上限を数える期間の呼び方。"""
        return "講習期間" if self.is_season else "週"

    @property
    def slots(self) -> list[Slot]:
        return [Slot(d, k.no) for d in self.days for k in self.komas]


@dataclass
class Problem:
    settings: Settings
    students: dict[str, Student]
    teachers: dict[str, Teacher]
    requests: list[Request]
    # 「講師_担当可能科目」シートの列見出しから読んだ科目（シートの列順）
    subjects: list[str] = field(default_factory=list)


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
