"""Pure business rules; intervals are [start, end)."""
from datetime import datetime, timedelta


def overlaps(start: datetime, end: datetime, other_start: datetime, other_end: datetime) -> bool:
    return start < other_end and other_start < end


def validate_booking(service_minutes: int, slot_start: datetime, slot_end: datetime,
                     appointment_start: datetime, supported: bool) -> None:
    if any(d.tzinfo is None or d.utcoffset() is None for d in (slot_start, slot_end, appointment_start)):
        raise ValueError('Дата должна содержать часовой пояс')
    if not supported:
        raise ValueError('Специалист не оказывает эту услугу')
    if service_minutes <= 0 or appointment_start < slot_start or appointment_start + timedelta(minutes=service_minutes) > slot_end:
        raise ValueError('Услуга не помещается в выбранный слот')


def summary_metrics(booked_minutes: float, available_minutes: float, cancelled: int, total: int) -> dict:
    return {'utilization': round(100*booked_minutes/available_minutes, 2) if available_minutes else 0.0,
            'cancellation_rate': round(100*cancelled/total, 2) if total else 0.0}
