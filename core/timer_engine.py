"""
timer_engine.py - Bộ đếm + máy trạng thái, Python thuần.

Nguyên tắc:
  - KHÔNG import PySide6, KHÔNG đọc/ghi CSDL.
  - Đồng hồ được TIÊM từ ngoài: `now` là hàm trả về số giây (float).
    Mặc định time.monotonic. Test truyền đồng hồ giả để tua 25 phút tức thì.
  - Mỗi sự kiện trả về danh sách Effect; engine không tự làm tác dụng phụ.

Vì sao dùng `deadline` tuyệt đối thay vì trừ dần mỗi tick?
  Nếu Qt trễ tick (máy lag, kéo cửa sổ, overlay cướp focus), đồng hồ vẫn
  đúng: remaining = deadline - now. Không bị trôi, và overlay vi phạm không
  trở thành "tạm dừng miễn phí".
"""

from __future__ import annotations

import time
from typing import Callable

import config
from core.effects import (
    CycleFinished,
    Effect,
    FocusExtended,
    NeedNewTask,
    OpenQuickNote,
    SessionClosed,
    SessionOpened,
    ViolationRecorded,
)
from core.states import BREAK_STATES, RUNNING_STATES, Event, State

NowFn = Callable[[], float]


def format_duration(seconds: float) -> str:
    """Đổi số giây thành chuỗi thời lượng tiếng Việt thân thiện.

    - Dưới 60 giây: 'X giây' (ví dụ: '3 giây', '10 giây')
    - Từ 60 giây trở lên:
      + Nếu tròn phút: 'X phút' (ví dụ: '5 phút', '25 phút')
      + Nếu có giây lẻ: 'X phút Y giây' (ví dụ: '1 phút 30 giây')
    """
    total = max(0, int(round(seconds)))
    if total < 60:
        return f"{total} giây"

    minutes = total // 60
    rem_seconds = total % 60
    if rem_seconds == 0:
        return f"{minutes} phút"
    return f"{minutes} phút {rem_seconds} giây"


class TimerEngine:
    """Bộ đếm Pomodoro theo bảng chuyển trạng thái đã chốt."""

    def __init__(
        self,
        now: NowFn = time.monotonic,
        *,
        strict_mode: bool = config.STRICT_MODE,
        focus_seconds: float = config.FOCUS_SECONDS,
        short_break_seconds: float = config.SHORT_BREAK_SECONDS,
        long_break_seconds: float = config.LONG_BREAK_SECONDS,
        grace_seconds: float = config.GRACE_SECONDS,
        cycles_before_long_break: int = config.CYCLES_BEFORE_LONG_BREAK,
        auto_confirm_seconds: float = config.AUTO_CONFIRM_BREAK_SECONDS,
    ) -> None:
        self._now = now

        # Cấu hình (cho phép test ghi đè mà không sửa config.py)
        self._strict_mode = strict_mode
        self._focus_seconds = focus_seconds
        self._short_break_seconds = short_break_seconds
        self._long_break_seconds = long_break_seconds
        self._grace_seconds = grace_seconds
        self._cycles_before_long_break = cycles_before_long_break
        self._auto_confirm_seconds = auto_confirm_seconds

        # --- Trạng thái công khai ---
        self.state: State = State.IDLE
        self.pomodoros_done: int = 0          # chỉ tăng khi focus chạy hết giờ
        self.cycle_counted: bool = True       # chống cộng trùng một chu kỳ
        self.current_task_id: int | None = None
        self.violations_in_cycle: int = 0
        self.resume_state: State | None = None
        self.awaiting_confirm: bool = False   # đồng hồ đã nạp nhưng chưa chạy

        # --- Trạng thái nội bộ ---
        self._remaining: float = 0.0          # dùng khi đồng hồ không chạy
        self._deadline: float | None = None    # dùng khi đồng hồ đang chạy
        self._auto_confirm_at: float | None = None
        self._session_open: bool = False
        self._grace_extended_seconds: float = 0.0   # đã gia hạn bao nhiêu

    # ------------------------------------------------------------------
    # Thuộc tính chỉ đọc
    # ------------------------------------------------------------------
    @property
    def cycle_index(self) -> int:
        """Chu kỳ hiện tại trong vòng 4: 1, 2, 3, 4 rồi quay lại 1."""
        return self.pomodoros_done % self._cycles_before_long_break + 1

    @property
    def display_cycle_index(self) -> int:
        """Chu kỳ hiển thị trên giao diện (1..4).

        - Trong giai đoạn nghỉ (SHORT_BREAK, LONG_BREAK, PAUSED từ nghỉ):
          hiển thị chu kỳ vừa hoàn thành.
        - Ở IDLE, FOCUS, GRACE và lúc chờ vào FOCUS:
          hiển thị chu kỳ hiện tại / sắp tới.
        """
        if self.is_break_phase:
            return (self.pomodoros_done - 1) % self._cycles_before_long_break + 1
        return self.cycle_index

    @property
    def clock_is_running(self) -> bool:
        """Đồng hồ có đang đếm ngược thật không.

        False khi IDLE, PAUSED, hoặc đang chờ người dùng bấm xác nhận.
        """
        if self.awaiting_confirm or self.state in (State.IDLE, State.PAUSED):
            return False
        return self._deadline is not None

    @property
    def can_scan_for_blocked_app(self) -> bool:
        """Chỉ quét app cấm khi đang FOCUS/GRACE và đồng hồ chạy thật."""
        return self.clock_is_running and self.state in RUNNING_STATES

    @property
    def remaining_seconds(self) -> float:
        """Thời gian còn lại của giai đoạn hiện tại."""
        if self._deadline is not None:
            return max(0.0, self._deadline - self._now())
        return self._remaining

    @property
    def is_break_phase(self) -> bool:
        """Có đang trong giai đoạn nghỉ không (kể cả lúc đang tạm dừng nghỉ).

        Dùng để quyết định hiện ô ghi chú ghim và hiển thị chu kỳ vừa hoàn thành.
        """
        if self.state in BREAK_STATES:
            return True
        return self.state is State.PAUSED and self.resume_state in BREAK_STATES

    @property
    def strict_mode(self) -> bool:
        """True = nghiêm ngặt, False = linh hoạt (dùng GRACE)."""
        return self._strict_mode

    def set_durations(
        self,
        *,
        focus_seconds: float,
        short_break_seconds: float,
        long_break_seconds: float,
        force: bool = False,
    ) -> bool:
        """Đổi thời lượng ba giai đoạn (từ Cài đặt).

        Chỉ đổi khi đồng hồ KHÔNG đang đếm: cột `sessions` đang mở đã ghi
        theo thời lượng cũ, đổi giữa chừng sẽ lệch dữ liệu. Đồng hồ đang dừng
        ở IDLE thì phần đếm màn hình được làm mới theo thời lượng mới.

        Trả về True nếu đã áp dụng.
        """
        can_change = force or not self.clock_is_running
        if not can_change:
            return False

        self._focus_seconds = float(focus_seconds)
        self._short_break_seconds = float(short_break_seconds)
        self._long_break_seconds = float(long_break_seconds)

        # Chưa chạy: cho màn hình hiện đúng thời lượng mới ngay.
        if self.state is State.IDLE:
            self._remaining = 0.0
        elif self.awaiting_confirm and self.state in BREAK_STATES:
            self._remaining = (
                self._short_break_seconds
                if self.state is State.SHORT_BREAK
                else self._long_break_seconds
            )
        return True

    def set_strict_mode(self, strict: bool, *, force: bool = False) -> bool:
        """Đổi chế độ Nghiêm ngặt/Linh hoạt.

        Chỉ đổi được khi đồng hồ KHÔNG chạy (IDLE hoặc đang chờ xác nhận):
        đổi giữa chu kỳ sẽ làm giai đoạn đang chạy lệch với cột `mode` của
        session đã mở. `force=True` dành cho test/khôi phục lúc khởi động.

        Trả về True nếu chế độ đã được áp dụng.
        """
        can_change = force or self.state is State.IDLE or (
            self.awaiting_confirm and self.state is not State.GRACE
        )
        if not can_change:
            return False
        self._strict_mode = bool(strict)
        return True

    @property
    def focus_seconds(self) -> float:
        """Thời lượng tập trung (giây) mà engine đang dùng."""
        return self._focus_seconds

    @property
    def short_break_seconds(self) -> float:
        """Thời lượng nghỉ ngắn (giây) mà engine đang dùng."""
        return self._short_break_seconds

    @property
    def long_break_seconds(self) -> float:
        """Thời lượng nghỉ dài (giây) mà engine đang dùng."""
        return self._long_break_seconds

    @property
    def grace_seconds(self) -> float:
        """Thời lượng gia hạn GRACE (giây) ở chế độ linh hoạt."""
        return self._grace_seconds

    @property
    def auto_confirm_at(self) -> float | None:
        """Thời điểm tự xác nhận (theo đồng hồ của engine), None nếu không hẹn."""
        return self._auto_confirm_at

    @property
    def auto_confirm_seconds(self) -> float:
        """Số giây chờ tự xác nhận đã cấu hình cho giai đoạn nghỉ."""
        return self._auto_confirm_seconds

    @property
    def seconds_until_auto_confirm(self) -> float | None:
        """Số giây còn lại tới lúc tự xác nhận, None nếu không hẹn."""
        if self._auto_confirm_at is None:
            return None
        return max(0.0, self._auto_confirm_at - self._now())

    @property
    def phase_seconds(self) -> float:
        """Số giây của giai đoạn đang chạy.

        Khi IDLE thì trả về độ dài focus sắp tới, để đồng hồ hiển thị
        "25:00" thay vì "00:00".
        """
        if self.state is State.IDLE:
            return self._focus_seconds
        return self.remaining_seconds

    # ------------------------------------------------------------------
    # Cổng vào duy nhất
    # ------------------------------------------------------------------
    def handle(
        self,
        event: Event,
        task_id: int | None = None,
        *,
        seconds: float | None = None,
    ) -> list[Effect]:
        """Xử lý một sự kiện, trả về danh sách việc cần làm bên ngoài.

        Sự kiện không hợp lệ với trạng thái hiện tại bị bỏ qua (trả về []),
        không ném exception: giao diện có thể bắn sự kiện thoải mái.

        `seconds` chỉ dùng cho EXTEND_FOCUS (mốc gia hạn người dùng chọn).
        """
        if event is Event.EXTEND_FOCUS:
            return self._on_extend_focus(seconds)
        if event is Event.START:
            return self._on_start(task_id)
        if event is Event.PAUSE:
            return self._on_pause()
        if event is Event.RESUME:
            return self._on_resume()
        if event is Event.STOP:
            return self._on_stop()
        if event is Event.CONFIRM:
            return self._on_confirm(auto=False)
        if event is Event.AUTO_CONFIRM:
            return self._on_confirm(auto=True)
        if event is Event.TIME_UP:
            return self._on_time_up()
        if event is Event.TASK_DONE:
            return self._on_task_done(task_id)
        if event is Event.END_GRACE_NOW:
            return self._on_end_grace_now()
        if event is Event.VIOLATION_DETECTED:
            return self._on_violation()
        return []

    def update(self) -> list[Effect]:
        """Gọi định kỳ (Mốc 3: mỗi ~200ms). Tự sinh TIME_UP / AUTO_CONFIRM.

        Không chặn, không ngủ: chỉ so sánh giờ hiện tại với deadline.
        """
        effects: list[Effect] = []

        if self.awaiting_confirm:
            # Chỉ giai đoạn NGHỈ mới được tự chạy. FOCUS thì chờ người dùng.
            if (
                self._auto_confirm_at is not None
                and self.state in BREAK_STATES
                and self._now() >= self._auto_confirm_at
            ):
                effects.extend(self.handle(Event.AUTO_CONFIRM))
            return effects

        if self._deadline is not None and self._now() >= self._deadline:
            effects.extend(self.handle(Event.TIME_UP))

        return effects

    @property
    def grace_extended_seconds(self) -> float:
        """Tổng số giây đã gia hạn trong chu kỳ GRACE hiện tại."""
        return self._grace_extended_seconds

    @property
    def extend_options_seconds(self) -> tuple[float, ...]:
        """Các mốc gia hạn được phép, theo giai đoạn nghỉ sắp tới.

        - Nghỉ ngắn: 1 hoặc 2 phút.
        - Nghỉ dài : 1, 2, 3, 4 hoặc 5 phút.
        Ở trạng thái khác GRACE trả về tuple rỗng.
        """
        if self.state is not State.GRACE:
            return ()
        if self._next_break_state() is State.LONG_BREAK:
            return config.LONG_GRACE_OPTIONS_SECONDS
        return config.SHORT_GRACE_OPTIONS_SECONDS

    @property
    def grace_cap_seconds(self) -> float:
        """Hạn mức gia hạn tổng của chu kỳ GRACE hiện tại (giây)."""
        options = self.extend_options_seconds
        return max(options) if options else 0.0

    def fast_forward(self, seconds: float | None = None) -> list[Effect]:
        """Tua nhanh giai đoạn hiện tại về số giây đếm ngược cuối.

        - Nếu đồng hồ đang đếm ngược: kéo deadline về now + seconds để người dùng
          thấy đồng hồ đếm ngược 1-2 giây cuối rồi tự hết giờ qua nhịp tick bình thường.
        - Nếu đang chờ tự xác nhận nghỉ: kéo auto_confirm_at về now + seconds.
        - Nếu bấm lần nữa khi thời gian còn lại đã <= seconds: lập tức kết thúc giai đoạn.
        """
        rem = seconds if seconds is not None else config.FAST_FORWARD_REMAINING_SECONDS

        if self.awaiting_confirm:
            if self._auto_confirm_at is not None and self.state in BREAK_STATES:
                if self._auto_confirm_at - self._now() <= rem:
                    self._auto_confirm_at = self._now()
                else:
                    self._auto_confirm_at = self._now() + rem
                return self.update()
            return []

        if self._deadline is not None:
            if self.remaining_seconds <= rem:
                self._deadline = self._now()
            else:
                self._deadline = self._now() + rem
            return self.update()

        return []

    # ------------------------------------------------------------------
    # Xử lý từng sự kiện
    # ------------------------------------------------------------------
    def _on_start(self, task_id: int | None) -> list[Effect]:
        if self.state is not State.IDLE:
            return []
        self.current_task_id = task_id
        return self._begin_focus()

    def _on_pause(self) -> list[Effect]:
        # Đồng hồ chưa chạy thì pause vô nghĩa
        if self.awaiting_confirm:
            return []
        if self.state not in RUNNING_STATES + BREAK_STATES:
            return []

        self._remaining = self.remaining_seconds   # đóng băng thời gian còn lại
        self._deadline = None
        self.resume_state = self.state
        self.state = State.PAUSED
        return []

    def _on_resume(self) -> list[Effect]:
        if self.state is not State.PAUSED or self.resume_state is None:
            return []

        self.state = self.resume_state
        self.resume_state = None
        self._deadline = self._now() + self._remaining
        return []

    def _on_stop(self) -> list[Effect]:
        if self.state is State.IDLE:
            return []

        effects: list[Effect] = []
        if self._session_open:
            effects.append(
                SessionClosed(completed=False, violations=self.violations_in_cycle)
            )
            self._session_open = False

        self._go_idle()
        return effects

    def _on_confirm(self, auto: bool) -> list[Effect]:
        # GRACE linh hoạt: nút "Bắt đầu nghỉ" trên overlay -> kết thúc focus
        # và cho nghỉ chạy NGAY (người dùng đã chủ động, không hỏi lại).
        if self.state is State.GRACE:
            if auto:
                return []
            return self._finish_focus(start_break_now=True)
        if not self.awaiting_confirm:
            return []
        # AUTO_CONFIRM không bao giờ áp dụng cho FOCUS
        if auto and self.state not in BREAK_STATES:
            return []

        self.awaiting_confirm = False
        self._auto_confirm_at = None
        self._deadline = self._now() + self._remaining

        # Chu kỳ focus chỉ thật sự bắt đầu (và mở session) khi đồng hồ chạy
        if self.state is State.FOCUS:
            self._session_open = True
            return [self._session_opened_effect()]
        return []

    def _on_time_up(self) -> list[Effect]:
        if self.awaiting_confirm or self.state is State.PAUSED:
            return []
        if self._deadline is None or self._now() < self._deadline:
            return []

        if self.state is State.FOCUS:
            if self._strict_mode:
                return self._finish_focus()
            return self._enter_grace()

        if self.state is State.GRACE:
            # Hết mốc gia hạn (nếu có) -> kết thúc focus, sang nghỉ.
            return self._finish_focus()

        if self.state is State.SHORT_BREAK:
            return self._enter_focus_waiting_confirm()

        if self.state is State.LONG_BREAK:
            return self._finish_round()

        return []

    def _on_task_done(self, task_id: int | None) -> list[Effect]:
        """Chỉ lo phần ĐỒNG HỒ. Phần thưởng do core/reward.py làm (Mốc 5).

        Chỉ coi là việc hiện tại đã xong khi task_id không None VÀ bằng current_task_id.
        Khi đó:
          - ở GRACE: kết thúc chu kỳ, chuyển sang nghỉ ngay
          - ở FOCUS: phát NeedNewTask, đồng hồ vẫn chạy
          - ở trạng thái khác: không đổi đồng hồ, không phát effect
          - current_task_id được đặt lại về None.
        Nếu task_id khác current_task_id, hoặc current_task_id là None,
        hoặc truyền task_id = None thì không làm gì và không phát effect.
        """
        if task_id is None or self.current_task_id is None or task_id != self.current_task_id:
            return []

        self.current_task_id = None

        if self.state is State.GRACE:
            return self._finish_focus()
        if self.state is State.FOCUS:
            return [NeedNewTask()]

        return []

    def _on_end_grace_now(self) -> list[Effect]:
        if self.state is not State.GRACE:
            return []
        return self._finish_focus()

    def _on_extend_focus(self, seconds: float | None) -> list[Effect]:
        """Cộng thêm `seconds` giây focus trong GRACE (chế độ linh hoạt).

        Mốc hợp lệ phụ thuộc giai đoạn nghỉ sắp tới:
          - nghỉ ngắn: 1 hoặc 2 phút
          - nghỉ dài : 1..5 phút
        Cộng dồn nhiều lần không vượt quá hạn mức tổng của chu kỳ này.
        Mốc lạ / sai trạng thái -> bỏ qua, trả về [].
        """
        if self.state is not State.GRACE or seconds is None:
            return []

        options = self.extend_options_seconds
        if seconds not in options:
            return []

        cap = max(options)
        can_add = min(float(seconds), cap - self.grace_extended_seconds)
        if can_add <= 0:
            return []

        self._deadline = (self._deadline or self._now()) + can_add
        self._remaining += can_add
        self._grace_extended_seconds += can_add
        return [
            FocusExtended(
                seconds=can_add, total=self._grace_extended_seconds
            )
        ]

    def _on_violation(self) -> list[Effect]:
        if not self.can_scan_for_blocked_app:
            return []
        self.violations_in_cycle += 1
        return [ViolationRecorded(total=self.violations_in_cycle)]

    # ------------------------------------------------------------------
    # Chuyển giai đoạn (dùng nội bộ)
    # ------------------------------------------------------------------
    def _begin_focus(self) -> list[Effect]:
        self.state = State.FOCUS
        self._remaining = self._focus_seconds
        self._deadline = self._now() + self._focus_seconds
        self.awaiting_confirm = False
        self._auto_confirm_at = None
        self.resume_state = None
        self.cycle_counted = False
        self.violations_in_cycle = 0
        self._session_open = True
        return [self._session_opened_effect()]

    def _enter_grace(self) -> list[Effect]:
        """Hết giờ focus ở chế độ linh hoạt: chuyển GRACE và báo cho giao diện.

        Session CHƯA đóng ở đây (vẫn là focus đang mở) — chỉ đóng khi kết
        thúc thật (_finish_focus). GRACE mặc định chờ người dùng chọn gia hạn
        hay bắt đầu nghỉ, nên đồng hồ tạm dừng (`deadline = None`).
        """
        next_state = self._next_break_state()
        self.state = State.GRACE
        self._remaining = 0.0
        self._deadline = None
        self.awaiting_confirm = False
        self._auto_confirm_at = None
        self._grace_extended_seconds = 0.0

        return [
            CycleFinished(
                from_state=State.FOCUS,
                next_state=next_state,
                pomodoros_done=self.pomodoros_done,
            )
        ]

    def _next_break_state(self) -> State:
        """Giai đoạn nghỉ sẽ tới sau khi kết thúc focus hiện tại."""
        if (self.pomodoros_done + 1) % self._cycles_before_long_break == 0:
            return State.LONG_BREAK
        return State.SHORT_BREAK

    def _finish_focus(self, *, start_break_now: bool = False) -> list[Effect]:
        """Kết thúc focus (hết giờ, TASK_DONE trong GRACE, hoặc Nghỉ ngay).

        `start_break_now=True` khi người dùng ĐÃ chủ động bấm "Bắt đầu nghỉ"
        trên overlay (luồng linh hoạt): nghỉ chạy ngay, không bắt xác nhận
        thêm lần nữa. Mặc định (nghiêm ngặt, hết mốc gia hạn) vẫn vào nghỉ ở
        trạng thái chờ xác nhận như cũ.
        """
        effects: list[Effect] = []

        # Cộng chu kỳ đúng MỘT lần cho mỗi chu kỳ
        if not self.cycle_counted:
            self.pomodoros_done += 1
            self.cycle_counted = True

        if self._session_open:
            effects.append(
                SessionClosed(completed=True, violations=self.violations_in_cycle)
            )
            self._session_open = False

        next_state = (
            State.LONG_BREAK
            if self.pomodoros_done % self._cycles_before_long_break == 0
            else State.SHORT_BREAK
        )
        effects.extend(self._enter_break(next_state, start_now=start_break_now))
        effects.append(OpenQuickNote())
        return effects

    def _enter_break(
        self, state: State, *, start_now: bool = False
    ) -> list[Effect]:
        from_state = self.state
        self.state = state
        self._remaining = (
            self._short_break_seconds
            if state is State.SHORT_BREAK
            else self._long_break_seconds
        )
        self.resume_state = None

        if start_now:
            # Người dùng đã bấm "Bắt đầu nghỉ": nghỉ chạy luôn.
            self._deadline = self._now() + self._remaining
            self.awaiting_confirm = False
            self._auto_confirm_at = None
        else:
            self._deadline = None
            self.awaiting_confirm = True
            if self._auto_confirm_seconds > 0:
                self._auto_confirm_at = self._now() + self._auto_confirm_seconds
            else:
                self._auto_confirm_at = None

        return [
            CycleFinished(
                from_state=from_state,
                next_state=state,
                pomodoros_done=self.pomodoros_done,
            )
        ]

    def _enter_focus_waiting_confirm(self) -> list[Effect]:
        from_state = self.state
        self.state = State.FOCUS
        self._remaining = self._focus_seconds
        self._deadline = None
        self.awaiting_confirm = True
        self._auto_confirm_at = None   # FOCUS không bao giờ tự chạy
        self.resume_state = None
        self.cycle_counted = False
        self.violations_in_cycle = 0

        return [
            CycleFinished(
                from_state=from_state,
                next_state=State.FOCUS,
                pomodoros_done=self.pomodoros_done,
            )
        ]

    def _finish_round(self) -> list[Effect]:
        from_state = self.state
        self._go_idle()
        return [
            CycleFinished(
                from_state=from_state,
                next_state=State.IDLE,
                pomodoros_done=self.pomodoros_done,
            )
        ]

    def _go_idle(self) -> None:
        self.state = State.IDLE
        self._remaining = 0.0
        self._deadline = None
        self._auto_confirm_at = None
        self.awaiting_confirm = False
        self.resume_state = None
        self.cycle_counted = True
        self.violations_in_cycle = 0

    def _session_opened_effect(self) -> SessionOpened:
        return SessionOpened(
            cycle_index=self.cycle_index,
            task_id=self.current_task_id,
            mode="strict" if self._strict_mode else "flexible",
        )
