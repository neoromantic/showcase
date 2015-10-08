import datetime
import time

from threading import Lock


__all__ = 'TasksList', 'datetime_to_timestamp', 'timestamp_to_datetime', 'now'


class TasksList(list):

    def __init__(self, *args, **kwargs):
        # Create a lock
        self._lock = Lock()
        # Call the original __init__
        super(TasksList, self).__init__(*args, **kwargs)

    def remove(self, value):
        self._lock.acquire()
        try:
            super(TasksList, self).remove(value)
        finally:
            self._lock.release()


def datetime_to_timestamp(dt):
    """ Convert datetime to unixtimestamp in milliseconds, returns int"""
    return round(dt.timestamp() * 1000)


def timestamp_to_datetime(ts):
    """ Convert unixtimestamp in milliseconds to datetime, returns datetime.datetime"""
    return datetime.datetime.fromtimestamp(ts / 1000)


def now():
    """ Return current unixtimestamp in milliseconds, return bytes"""
    return bytes("{}".format(int(time.time() * 1000)), encoding='ascii')


def parse_timetable(value):
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    if len(value) <= 1:
        return None

    often, unit = value[:-1], value[-1]
    # Convert all to ms
    if unit == 'u':
        interval = int(often)
    elif unit == 's':
        interval = int(often) * 1000
    elif unit == 'm':
        interval = int(often) * 1000 * 60
    elif unit == 'h':
        interval = int(often) * 1000 * 60 * 60
    elif unit == 'd':
        interval = int(often) * 1000 * 60 * 60 * 24
    elif unit == 'w':
        interval = int(often) * 1000 * 60 * 60 * 24 * 7
    else:
        return None
    return interval
