from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.oncall import Override, Rotation, Shift, on_call_at, shifts_between

ALICE, BOB, CAROL, DAVE = 1, 2, 3, 4

# Weekly rotation, handoff Mondays 09:00 Zagreb time, starting Monday 2026-01-05.
WEEKLY = Rotation(
    timezone="Europe/Zagreb",
    start=datetime(2026, 1, 5, 9, 0),  # noqa: DTZ001 - local wall time
    shift_days=7,
    participants=[ALICE, BOB, CAROL],
)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def who(rotation: Rotation, at: datetime, overrides: list[Override] | None = None) -> int | None:
    current = on_call_at(rotation, overrides or [], at)
    return current.user_id if current else None


class TestRotation:
    def test_first_participant_is_on_call_from_the_rotation_start(self):
        # 09:00 CET is 08:00 UTC in January.
        assert who(WEEKLY, utc(2026, 1, 5, 8, 0)) == ALICE

    def test_nobody_is_on_call_before_the_rotation_starts(self):
        assert who(WEEKLY, utc(2026, 1, 5, 7, 59, 59)) is None
        assert who(WEEKLY, utc(2025, 6, 1, 12, 0)) is None

    def test_handoff_happens_exactly_at_the_boundary(self):
        assert who(WEEKLY, utc(2026, 1, 12, 7, 59, 59)) == ALICE
        assert who(WEEKLY, utc(2026, 1, 12, 8, 0, 0)) == BOB

    def test_rotation_wraps_around_to_the_first_participant(self):
        assert who(WEEKLY, utc(2026, 1, 19, 8, 0)) == CAROL
        assert who(WEEKLY, utc(2026, 1, 26, 8, 0)) == ALICE

    def test_far_future_lookup(self):
        # 2026-01-05 + 520 weeks; 520 % 3 == 1.
        assert who(WEEKLY, utc(2035, 12, 24, 12, 0)) == BOB

    def test_single_participant_is_always_on_call(self):
        solo = Rotation("UTC", datetime(2026, 1, 1), 1, [DAVE])  # noqa: DTZ001
        assert who(solo, utc(2026, 7, 15, 3, 0)) == DAVE

    def test_rotation_without_participants_has_nobody_on_call(self):
        empty = Rotation("UTC", datetime(2026, 1, 1), 1, [])  # noqa: DTZ001
        assert who(empty, utc(2026, 1, 2)) is None

    def test_naive_datetime_is_rejected(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            on_call_at(WEEKLY, [], datetime(2026, 1, 12, 8, 0))  # noqa: DTZ001


class TestTimeZones:
    def test_handoff_follows_local_time_across_spring_dst_change(self):
        # Clocks go forward on 2026-03-29. The Monday 09:00 handoff is 08:00 UTC before the
        # change and 07:00 UTC after it.
        assert who(WEEKLY, utc(2026, 3, 23, 7, 59)) == BOB  # shift 10
        assert who(WEEKLY, utc(2026, 3, 23, 8, 0)) == CAROL  # shift 11
        assert who(WEEKLY, utc(2026, 3, 30, 6, 59)) == CAROL
        assert who(WEEKLY, utc(2026, 3, 30, 7, 0)) == ALICE  # shift 12

    def test_handoff_follows_local_time_across_autumn_dst_change(self):
        # Clocks go back on 2026-10-25: the handoff returns to 08:00 UTC.
        before = on_call_at(WEEKLY, [], utc(2026, 10, 19, 6, 59))
        after = on_call_at(WEEKLY, [], utc(2026, 10, 19, 7, 0))
        assert before.user_id != after.user_id

        assert who(WEEKLY, utc(2026, 10, 26, 7, 30)) == after.user_id
        assert who(WEEKLY, utc(2026, 10, 26, 8, 0)) != after.user_id

    def test_query_time_zone_does_not_matter_only_the_instant_does(self):
        instant = utc(2026, 1, 12, 8, 0)
        in_new_york = instant.astimezone(ZoneInfo("America/New_York"))
        in_tokyo = instant.astimezone(ZoneInfo("Asia/Tokyo"))
        assert who(WEEKLY, in_new_york) == who(WEEKLY, in_tokyo) == BOB

        just_before = (instant - timedelta(seconds=1)).astimezone(ZoneInfo("Asia/Tokyo"))
        assert who(WEEKLY, just_before) == ALICE

    def test_same_wall_clock_rotation_differs_between_time_zones(self):
        start = datetime(2026, 1, 5, 9, 0)  # noqa: DTZ001
        tokyo = Rotation("Asia/Tokyo", start, 7, [ALICE, BOB])
        new_york = Rotation("America/New_York", start, 7, [ALICE, BOB])
        # 2026-01-12 09:00 in Tokyo is 00:00 UTC; in New York it is 14:00 UTC.
        at = utc(2026, 1, 12, 6, 0)
        assert who(tokyo, at) == BOB
        assert who(new_york, at) == ALICE

    def test_daily_shift_is_23_hours_long_on_the_spring_forward_day(self):
        daily = Rotation("America/New_York", datetime(2026, 3, 1), 1, [ALICE, BOB])  # noqa: DTZ001
        shifts = shifts_between(daily, [], utc(2026, 3, 8, 5, 0), utc(2026, 3, 10, 4, 0))
        assert [(s.user_id, s.ends_at - s.starts_at) for s in shifts] == [
            (BOB, timedelta(hours=23)),
            (ALICE, timedelta(hours=24)),
        ]

    def test_handoff_at_a_nonexistent_local_time_leaves_no_gap(self):
        # 02:30 does not exist in Zagreb on 2026-03-29.
        daily = Rotation("Europe/Zagreb", datetime(2026, 3, 27, 2, 30), 1, [ALICE, BOB])  # noqa: DTZ001
        shifts = shifts_between(daily, [], utc(2026, 3, 28, 12, 0), utc(2026, 3, 30, 12, 0))
        assert [s.user_id for s in shifts] == [BOB, ALICE, BOB]
        for earlier, later in zip(shifts, shifts[1:], strict=False):
            assert earlier.ends_at == later.starts_at


class TestOverrides:
    def test_override_replaces_the_rotation_while_it_is_active(self):
        override = Override(1, DAVE, utc(2026, 1, 6, 18, 0), utc(2026, 1, 7, 6, 0))
        current = on_call_at(WEEKLY, [override], utc(2026, 1, 6, 20, 0))
        assert (current.user_id, current.source) == (DAVE, "override")

    def test_override_interval_is_half_open(self):
        override = Override(1, DAVE, utc(2026, 1, 6, 18, 0), utc(2026, 1, 7, 6, 0))
        assert who(WEEKLY, utc(2026, 1, 6, 17, 59, 59), [override]) == ALICE
        assert who(WEEKLY, utc(2026, 1, 6, 18, 0), [override]) == DAVE
        assert who(WEEKLY, utc(2026, 1, 7, 5, 59, 59), [override]) == DAVE
        assert who(WEEKLY, utc(2026, 1, 7, 6, 0), [override]) == ALICE

    def test_latest_created_override_wins_when_they_overlap(self):
        older = Override(1, DAVE, utc(2026, 1, 6, 0, 0), utc(2026, 1, 8, 0, 0))
        newer = Override(2, CAROL, utc(2026, 1, 7, 0, 0), utc(2026, 1, 7, 12, 0))
        for overrides in ([older, newer], [newer, older]):
            assert who(WEEKLY, utc(2026, 1, 6, 12, 0), overrides) == DAVE
            assert who(WEEKLY, utc(2026, 1, 7, 6, 0), overrides) == CAROL
            assert who(WEEKLY, utc(2026, 1, 7, 12, 0), overrides) == DAVE

    def test_override_spanning_a_handoff_hides_it(self):
        override = Override(1, DAVE, utc(2026, 1, 12, 6, 0), utc(2026, 1, 12, 10, 0))
        assert who(WEEKLY, utc(2026, 1, 12, 8, 0), [override]) == DAVE
        assert who(WEEKLY, utc(2026, 1, 12, 10, 0), [override]) == BOB

    def test_override_applies_even_before_the_rotation_starts(self):
        override = Override(1, DAVE, utc(2026, 1, 1, 0, 0), utc(2026, 1, 2, 0, 0))
        assert who(WEEKLY, utc(2026, 1, 1, 12, 0), [override]) == DAVE

    def test_override_in_another_offset_is_compared_as_an_instant(self):
        tokyo = ZoneInfo("Asia/Tokyo")
        # 2026-01-07 03:00-05:00 in Tokyo is 2026-01-06 18:00-20:00 UTC.
        override = Override(
            1,
            DAVE,
            datetime(2026, 1, 7, 3, 0, tzinfo=tokyo),
            datetime(2026, 1, 7, 5, 0, tzinfo=tokyo),
        )
        assert who(WEEKLY, utc(2026, 1, 6, 19, 0), [override]) == DAVE
        assert who(WEEKLY, utc(2026, 1, 7, 3, 0), [override]) == ALICE


class TestShiftsBetween:
    def test_rotation_shifts_are_clipped_to_the_requested_range(self):
        shifts = shifts_between(WEEKLY, [], utc(2026, 1, 8, 0, 0), utc(2026, 1, 20, 0, 0))
        assert shifts == [
            Shift(ALICE, "rotation", utc(2026, 1, 8, 0, 0), utc(2026, 1, 12, 8, 0)),
            Shift(BOB, "rotation", utc(2026, 1, 12, 8, 0), utc(2026, 1, 19, 8, 0)),
            Shift(CAROL, "rotation", utc(2026, 1, 19, 8, 0), utc(2026, 1, 20, 0, 0)),
        ]

    def test_override_splits_the_rotation_shift_around_it(self):
        override = Override(1, DAVE, utc(2026, 1, 6, 18, 0), utc(2026, 1, 7, 6, 0))
        shifts = shifts_between(WEEKLY, [override], utc(2026, 1, 6, 0, 0), utc(2026, 1, 8, 0, 0))
        assert shifts == [
            Shift(ALICE, "rotation", utc(2026, 1, 6, 0, 0), utc(2026, 1, 6, 18, 0)),
            Shift(DAVE, "override", utc(2026, 1, 6, 18, 0), utc(2026, 1, 7, 6, 0)),
            Shift(ALICE, "rotation", utc(2026, 1, 7, 6, 0), utc(2026, 1, 8, 0, 0)),
        ]

    def test_range_before_the_rotation_starts_is_empty(self):
        assert shifts_between(WEEKLY, [], utc(2025, 12, 1), utc(2025, 12, 31)) == []

    def test_range_starting_before_the_rotation_begins_at_the_first_handoff(self):
        shifts = shifts_between(WEEKLY, [], utc(2026, 1, 1), utc(2026, 1, 6))
        assert shifts == [Shift(ALICE, "rotation", utc(2026, 1, 5, 8, 0), utc(2026, 1, 6))]

    def test_empty_or_inverted_range_returns_nothing(self):
        assert shifts_between(WEEKLY, [], utc(2026, 1, 8), utc(2026, 1, 8)) == []
        assert shifts_between(WEEKLY, [], utc(2026, 1, 9), utc(2026, 1, 8)) == []

    def test_agrees_with_point_lookups_across_a_dst_change(self):
        overrides = [
            Override(1, DAVE, utc(2026, 3, 25, 22, 0), utc(2026, 3, 26, 6, 0)),
            Override(2, BOB, utc(2026, 3, 29, 0, 30), utc(2026, 3, 30, 9, 15)),
            Override(3, CAROL, utc(2026, 3, 29, 12, 0), utc(2026, 3, 29, 13, 0)),
        ]
        start, end = utc(2026, 3, 20), utc(2026, 4, 10)
        shifts = shifts_between(WEEKLY, overrides, start, end)

        assert shifts[0].starts_at == start
        assert shifts[-1].ends_at == end
        for earlier, later in zip(shifts, shifts[1:], strict=False):
            assert earlier.ends_at == later.starts_at
            assert (earlier.user_id, earlier.source) != (later.user_id, later.source)

        at = start
        while at < end:
            shift = next(s for s in shifts if s.starts_at <= at < s.ends_at)
            current = on_call_at(WEEKLY, overrides, at)
            assert (shift.user_id, shift.source) == (current.user_id, current.source), at
            at += timedelta(minutes=30)
