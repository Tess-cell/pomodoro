"""
reward.py - Hệ thống tính toán và trao phần thưởng Omnia.

Tuân thủ nguyên tắc: logic thuần Python (không PySide6), tách khỏi giao diện.
- Nhà: mỗi việc hoàn thành +độ khó tầng, tối đa config.MAX_FLOORS = 9999.
- Thú ảo + Cây trồng: +CARE_POINTS_PER_DIFFICULTY x độ khó điểm chăm sóc,
  nhận SONG SONG đầy đủ (không chia đôi). Ngưỡng stage nằm ở
  config.GROWTH_THRESHOLDS = (0, 50, 180).

Toàn bộ phần thưởng (nhà + thú + cây) chạy trong MỘT transaction:
các hàm db được gọi với commit=False, chỉ commit một lần ở cuối
apply_task_rewards(); lỗi giữa chừng thì rollback sạch.
"""

from dataclasses import dataclass
import sqlite3

import config
from db import creatures as creatures_repo
from db import house as house_repo
from db import settings as settings_repo

ADULT_STAGE = 3


@dataclass(frozen=True)
class CreatureReward:
    """Kết quả cộng điểm chăm sóc cho một sinh vật đang nuôi."""

    kind: str              # 'pet' hoặc 'plant'
    creature_id: int
    name: str
    old_growth: int
    new_growth: int
    old_stage: int
    new_stage: int
    added_points: int

    @property
    def became_adult(self) -> bool:
        """True nếu lần cộng điểm này đưa sinh vật lên trưởng thành."""
        return self.old_stage < ADULT_STAGE <= self.new_stage


@dataclass(frozen=True)
class TaskRewardResult:
    """Kết quả tính toán và trao thưởng khi hoàn thành một công việc.

    Các trường care_points / pet / plant có giá trị mặc định để mã cũ
    (chỉ quan tâm tầng nhà) vẫn dựng được object mà không phải sửa.
    """

    difficulty: int
    added_floors: int
    total_floors: int
    is_max_floors: bool
    care_points: int = 0
    pet: CreatureReward | None = None
    plant: CreatureReward | None = None
    target: str = config.DEFAULT_OMNIA_TARGET   # Omnia đã nhận tiến trình


def calculate_house_floors(
    current_floors: int,
    difficulty: int,
    max_floors: int = config.MAX_FLOORS,
) -> tuple[int, int]:
    """
    Tính số tầng mới và số tầng thực tế được cộng thêm cho ngôi nhà.

    Quy tắc:
    - Mỗi lần hoàn thành việc, số tầng được cộng bằng đúng độ khó (difficulty).
    - Số tầng tối đa là max_floors (mặc định 9999). Nếu đã chạm trần hoặc
      cộng vào vượt trần, hàm sẽ clamp lại ở max_floors và chỉ cộng số tầng
      thực tế cho đến khi chạm trần.

    Tham số:
        current_floors: Số tầng hiện tại (>= 0).
        difficulty: Độ khó của công việc (1..5).
        max_floors: Giới hạn trần số tầng (9999).

    Trả về:
        (new_floors, added_floors): Số tầng sau khi cộng và số tầng thực tế tăng.
    """
    if not isinstance(difficulty, int):
        raise TypeError(f"Độ khó phải là số nguyên (int), nhận được: {type(difficulty)}")

    if not (config.TASK_DIFFICULTY_MIN <= difficulty <= config.TASK_DIFFICULTY_MAX):
        raise ValueError(
            f"Độ khó phải nằm trong khoảng {config.TASK_DIFFICULTY_MIN} đến {config.TASK_DIFFICULTY_MAX}, "
            f"nhận được: {difficulty}"
        )

    if not isinstance(current_floors, int):
        raise TypeError(f"Số tầng hiện tại phải là số nguyên (int), nhận được: {type(current_floors)}")

    if current_floors < 0:
        raise ValueError(f"Số tầng hiện tại không được âm, nhận được: {current_floors}")

    # Đảm bảo điểm khởi đầu không vượt trần
    base_floors = min(max_floors, current_floors)
    new_floors = min(max_floors, base_floors + difficulty)
    added_floors = new_floors - base_floors

    return new_floors, added_floors


def calculate_care_points(difficulty: int) -> int:
    """Điểm chăm sóc nhận được khi hoàn thành việc có độ khó cho trước."""
    if isinstance(difficulty, bool) or not isinstance(difficulty, int):
        raise TypeError(f"Độ khó phải là số nguyên (int), nhận được: {type(difficulty)}")

    if not (config.TASK_DIFFICULTY_MIN <= difficulty <= config.TASK_DIFFICULTY_MAX):
        raise ValueError(
            f"Độ khó phải nằm trong khoảng {config.TASK_DIFFICULTY_MIN} đến {config.TASK_DIFFICULTY_MAX}, "
            f"nhận được: {difficulty}"
        )

    return config.CARE_POINTS_PER_DIFFICULTY * difficulty


def stage_for_growth(growth: int) -> int:
    """Quy đổi điểm chăm sóc tích luỹ sang giai đoạn 1, 2 hoặc 3.

    GROWTH_THRESHOLDS = (0, 50, 180):
        0..49   -> stage 1 (sinh ra)
        50..179 -> stage 2 (lớn lên)
        >= 180  -> stage 3 (trưởng thành)
    """
    if isinstance(growth, bool) or not isinstance(growth, int):
        raise TypeError(f"Điểm chăm sóc phải là số nguyên (int), nhận được: {type(growth)}")
    if growth < 0:
        raise ValueError(f"Điểm chăm sóc không được âm, nhận được: {growth}")

    stage = 1
    for index in range(1, len(config.GROWTH_THRESHOLDS)):
        if growth >= config.GROWTH_THRESHOLDS[index]:
            stage = index + 1
    return stage


def add_care_points(
    conn: sqlite3.Connection,
    points: int,
    *,
    kind: str | None = None,
    commit: bool = True,
) -> list[CreatureReward]:
    """Cộng `points` điểm chăm sóc cho sinh vật đang nuôi.

    kind='pet'/'plant' -> chỉ cộng cho kind đó (dùng khi chọn 1 Omnia).
    kind=None          -> cộng cho mọi sinh vật đang nuôi (tiện cho test/debug).

    - Không có sinh vật active thì bỏ qua, trả về danh sách rỗng (không lỗi).
    - growth + stage + is_active được ghi trong cùng một câu UPDATE.
    - Đạt stage 3: con vẫn Ở LẠI ô nuôi và tiếp tục nhận điểm (nuôi tiếp).
      growth chặn ở giới hạn kỹ thuật của SQLite INTEGER (thực tế vô hạn)
      và vẫn được hiển thị bình thường.
    - commit=False để caller gộp vào transaction lớn hơn.
    """
    if isinstance(points, bool) or not isinstance(points, int):
        raise TypeError(f"Điểm chăm sóc phải là số nguyên (int), nhận được: {type(points)}")
    if points < 0:
        raise ValueError(f"Điểm chăm sóc không được âm, nhận được: {points}")
    if kind is not None and kind not in config.CREATURE_KINDS:
        raise ValueError(f"Loại sinh vật '{kind}' không hợp lệ.")

    if not commit:
        return _award_care_points(conn, points, kind)

    try:
        rewards = _award_care_points(conn, points, kind)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return rewards


def _award_care_points(
    conn: sqlite3.Connection,
    points: int,
    kind: str | None = None,
) -> list[CreatureReward]:
    """Phần ghi CSDL của add_care_points (không commit)."""
    rewards: list[CreatureReward] = []
    kinds = (kind,) if kind is not None else config.CREATURE_KINDS

    for kind in kinds:
        creature = creatures_repo.get_active_creature(conn, kind)
        if creature is None:
            continue

        old_growth = int(creature["growth"])
        old_stage = int(creature["stage"])
        new_growth = min(config.MAX_GROWTH, old_growth + points)
        new_stage = stage_for_growth(new_growth)
        # Trưởng thành KHÔNG tự rời ô nuôi nữa: vẫn active để tăng điểm tiếp.
        still_active = bool(creature["is_active"])

        # Một câu UPDATE duy nhất: growth, stage, is_active luôn đồng bộ.
        creatures_repo.update_growth_stage(
            conn,
            int(creature["id"]),
            growth=new_growth,
            stage=new_stage,
            is_active=still_active,
            commit=False,
        )

        rewards.append(
            CreatureReward(
                kind=kind,
                creature_id=int(creature["id"]),
                name=creature["name"],
                old_growth=old_growth,
                new_growth=new_growth,
                old_stage=old_stage,
                new_stage=new_stage,
                added_points=new_growth - old_growth,
            )
        )

    return rewards


def apply_task_rewards(
    conn: sqlite3.Connection,
    difficulty: int,
    target: str | None = None,
    *,
    award: bool = True,
) -> TaskRewardResult:
    """
    Trao tiến trình khi hoàn thành công việc cho ĐÚNG MỘT Omnia.

    target=None  -> đọc lựa chọn đang lưu trong bảng settings.
    target: 'house' -> +difficulty tầng nhà (clamp 9999).
            'pet'   -> +2*difficulty điểm cho thú ảo đang nuôi.
            'plant' -> +2*difficulty điểm cho cây trồng đang nuôi.
    award=False  -> không trao gì (người dùng chọn "giữ lựa chọn" khi ô nuôi trống).

    Nếu chọn thú/cây mà ô nuôi trống thì không lỗi: care_points = 0 và
    không có CreatureReward. Mọi thay đổi nằm trong MỘT transaction,
    commit một lần, lỗi giữa chừng thì rollback.
    """
    care_points = calculate_care_points(difficulty)

    if target is None:
        target = settings_repo.get_active_omnia(conn)
    if target not in config.OMNIA_TARGETS:
        raise ValueError(f"Omnia '{target}' không hợp lệ (chỉ nhận {config.OMNIA_TARGETS}).")

    current_floors = house_repo.get_house_floors(conn, commit=False)
    is_max_floors = current_floors >= config.MAX_FLOORS

    if not award:
        return TaskRewardResult(
            difficulty=difficulty,
            added_floors=0,
            total_floors=current_floors,
            is_max_floors=is_max_floors,
            care_points=0,
            target=target,
        )

    if target == "house":
        new_floors, added = calculate_house_floors(current_floors, difficulty)
        try:
            if added > 0:
                house_repo.update_house_floors(conn, new_floors, commit=False)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        return TaskRewardResult(
            difficulty=difficulty,
            added_floors=added,
            total_floors=new_floors,
            is_max_floors=(new_floors >= config.MAX_FLOORS),
            care_points=0,
            target=target,
        )

    # target là 'pet' hoặc 'plant': chỉ sinh vật đang nuôi của kind đó nhận điểm
    try:
        rewards = _award_care_points(conn, care_points, kind=target)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    creature_reward = rewards[0] if rewards else None
    return TaskRewardResult(
        difficulty=difficulty,
        added_floors=0,
        total_floors=current_floors,
        is_max_floors=is_max_floors,
        care_points=(care_points if creature_reward is not None else 0),
        pet=creature_reward if target == "pet" else None,
        plant=creature_reward if target == "plant" else None,
        target=target,
    )
