from datetime import datetime, timedelta, timezone
import pytest
from app.rules import overlaps, validate_booking, summary_metrics

START = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)

def test_overlapping_intervals_are_detected():
    assert overlaps(START, START+timedelta(hours=1), START+timedelta(minutes=30), START+timedelta(hours=2))

def test_adjacent_intervals_are_allowed():
    assert not overlaps(START, START+timedelta(hours=1), START+timedelta(hours=1), START+timedelta(hours=2))

def test_same_instant_with_different_offsets_overlaps():
    shifted = START.astimezone(timezone(timedelta(hours=3)))
    assert overlaps(START, START+timedelta(hours=1), shifted, shifted+timedelta(minutes=30))

def test_supported_service_fits_slot():
    assert validate_booking(30, START, START+timedelta(hours=1), START, True) is None

def test_unsupported_service_is_rejected():
    with pytest.raises(ValueError): validate_booking(30, START, START+timedelta(hours=1), START, False)

def test_short_slot_is_rejected():
    with pytest.raises(ValueError): validate_booking(90, START, START+timedelta(hours=1), START, True)

def test_booking_outside_slot_is_rejected():
    with pytest.raises(ValueError): validate_booking(30, START, START+timedelta(hours=1), START-timedelta(minutes=1), True)

def test_naive_dates_are_rejected():
    with pytest.raises(ValueError): validate_booking(30, START.replace(tzinfo=None), START+timedelta(hours=1), START, True)

def test_summary_uses_correct_denominators():
    assert summary_metrics(60, 240, 1, 4) == {'utilization': 25.0, 'cancellation_rate': 25.0}

def test_empty_summary_has_zero_rates():
    assert summary_metrics(0, 0, 0, 0) == {'utilization': 0.0, 'cancellation_rate': 0.0}
