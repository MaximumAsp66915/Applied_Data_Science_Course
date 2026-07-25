import time
from datetime import datetime, timedelta, timezone
from typing import Union
from dateutil.parser import parse as parse_datetime
import jdatetime


class TimeManager:
    """
    Utility class for managing and manipulating time, including UTC/local conversions, offsets, and formatting.
    """
    def __init__(self,
                 read_offset: timedelta = -timedelta(hours=1, minutes=0),
                 write_offset: timedelta = timedelta(hours=0)) -> None:
        """
        Initialize TimeManager with read and write offsets.
        Args:
            read_offset (timedelta): Offset to apply when reading times.
            write_offset (timedelta): Offset to apply when writing times.
        """
        self.datetime = datetime
        self.read_offset = read_offset
        self.write_offset = write_offset
        self.tehran_offset = timedelta(hours=3, minutes=30)  # Tehran is UTC+3:30 without DST

    def now_utc(self, apply_write_offset: bool = True) -> datetime:
        """
        Get current UTC datetime with optional write offset.
        Args:
            apply_write_offset (bool): Whether to apply the write offset.
        Returns:
            datetime: Current UTC datetime.
        """
        now = datetime.now(timezone.utc)
        return now + self.write_offset if apply_write_offset else now

    def now(self, apply_read_offset: bool = True) -> datetime:
        """
        Get current local time (timezone-aware) with optional read offset.
        Returns:
            datetime: Current local datetime with tzinfo.
        """
        now = datetime.now().astimezone()  # Make it timezone-aware
        return now + self.read_offset if apply_read_offset else now

    def time(self) -> float:
        """
        Get current UNIX timestamp (seconds since epoch).
        Returns:
            float: Current timestamp.
        """
        return time.time()

    def perf_counter(self) -> float:
        """
        High-resolution timer for performance measurement.
        Returns:
            float: Performance counter value.
        """
        return time.perf_counter()

    def timedelta(self, seconds) -> timedelta:
        return timedelta(seconds=seconds)

    def apply_read_offset_to(self, value: Union[datetime, float, str]) -> Union[datetime, float]:
        """
        Apply read offset to a datetime, float, or ISO 8601 string.
        Args:
            value (datetime|float|str): Value to offset.
        Returns:
            datetime|float: Offset value.
        Raises:
            ValueError: If string cannot be parsed as datetime.
            TypeError: If value is not a supported type.
        """
        if isinstance(value, datetime):
            return value + self.read_offset
        elif isinstance(value, str):
            try:
                parsed_dt = parse_datetime(value)
                return parsed_dt + self.read_offset
            except Exception as e:
                raise ValueError(f"Could not parse datetime string: {value}. Error: {e}")
        elif isinstance(value, (float, int)):
            return value + self.read_offset.total_seconds()
        else:
            raise TypeError("Expected datetime, float, int, or ISO 8601 datetime string.")

    def utc_offset_manual(self, hours: int = 0, minutes: int = 0, apply_write_offset: bool = True) -> datetime:
        """
        Get UTC time with custom manual offset and optional write offset.
        Args:
            hours (int): Hours to offset.
            minutes (int): Minutes to offset.
            apply_write_offset (bool): Whether to apply write offset.
        Returns:
            datetime: Offset UTC datetime.
        """
        base = self.now_utc(apply_write_offset=False) + timedelta(hours=hours, minutes=minutes)
        return base + self.write_offset if apply_write_offset else base

    def format_datetime(self, dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S %Z%z") -> str:
        """
        Format a datetime object as a string.
        Args:
            dt (datetime): Datetime to format.
            fmt (str): Format string.
        Returns:
            str: Formatted datetime string.
        """
        return dt.strftime(fmt)

    def utcnow_deprecated_replacement(self, apply_read_offset: bool = True) -> datetime:
        """
        Drop-in replacement for datetime.utcnow().
        Args:
            apply_read_offset (bool): Whether to apply read offset.
        Returns:
            datetime: Current UTC datetime.
        """
        return self.now_utc(apply_read_offset)

    def tehran_now(self, apply_write_offset: bool = True) -> datetime:
        """
        Get current time in Tehran (UTC+3:30) with optional write offset.
        Args:
            apply_write_offset (bool): Whether to apply write offset.
        Returns:
            datetime: Current Tehran datetime.
        """
        base = self.now_utc(apply_write_offset=False) + self.tehran_offset
        return base + self.write_offset if apply_write_offset else base

        # tehran_tz = timezone(timedelta(hours=3, minutes=30))
        # base = self.now_utc(apply_write_offset=False).astimezone(tehran_tz)
        # return base + self.write_offset if apply_write_offset else base

        #The actual correct one is bellow:
        # tehran_tz = timezone(timedelta(hours=3, minutes=30))
        # base = datetime.now(tehran_tz)
        # return base + self.write_offset if apply_write_offset else base

    def sleep(self, seconds):
        time.sleep(seconds)

    def fromisoformat(self, date_string: str):
        return datetime.fromisoformat(date_string)

    @staticmethod
    def shamsi_to_miladi(shamsi_datetime: str) -> str:
        """
        Convert a Shamsi (Persian) date and time to Miladi (Gregorian).
        Args:
            shamsi_datetime (str): Shamsi datetime in the format 'YYYY-MM-DD HH:MM'.
        Returns:
            str: Corresponding Miladi datetime in 'YYYY-MM-DD HH:MM' format.
        """
        try:
            # Split the input into date and time parts
            date_part, time_part = shamsi_datetime.split(" ") if " " in shamsi_datetime else (shamsi_datetime, "")

            # Split the date part into year, month, and day
            jalali_year, jalali_month, jalali_day = map(int, date_part.split("-"))

            # Create a jdatetime object for the given Shamsi date
            jalali_date = jdatetime.date(jalali_year, jalali_month, jalali_day)

            # Convert Shamsi to Gregorian
            gregorian_date = jalali_date.togregorian()  # This returns a datetime.date object

            # Return the full Gregorian date with time part preserved
            return f"{gregorian_date.year}-{gregorian_date.month:02d}-{gregorian_date.day:02d} {time_part}"

        except Exception as e:
            raise ValueError(f"Invalid Shamsi date format: {shamsi_datetime}. Error: {e}")

    @staticmethod
    def miladi_to_shamsi(miladi_datetime: str) -> str:
        """
        Convert a Miladi (Gregorian) date and time to Shamsi (Persian).
        Args:
            miladi_datetime (str): Miladi datetime in the format 'YYYY-MM-DD HH:MM'.
        Returns:
            str: Corresponding Shamsi datetime in 'YYYY-MM-DD HH:MM' format.
        """
        try:
            # Split the input into date and time parts
            date_part, time_part = miladi_datetime.split(" ") if " " in miladi_datetime else (miladi_datetime, "")

            # Parse the Miladi date part into a datetime object
            gregorian_time = datetime.strptime(date_part, '%Y-%m-%d')

            # Convert the Gregorian date to Jalali (Shamsi) using jdatetime
            jalali_date = jdatetime.datetime.fromgregorian(datetime=gregorian_time)

            # Return the full Shamsi date with time part preserved
            return f"{jalali_date.year}-{jalali_date.month:02d}-{jalali_date.day:02d} {time_part}"

        except Exception as e:
            raise ValueError(f"Invalid Miladi datetime format: {miladi_datetime}. Error: {e}")

# Example usage
if __name__ == "__main__":
    tm = TimeManager(
        read_offset=timedelta(hours=-1),  # simulate client lag, time from database
        write_offset=timedelta(hours=1)  # simulate future time when writing
    )

    tm = TimeManager()
    print("Shamsi to Miladi:", tm.shamsi_to_miladi("1404-09-09 2:12"))
    print("Miladi to Shamsi:", tm.miladi_to_shamsi("2025-11-30"))

    print("UTC now:", tm.format_datetime(tm.now_utc()))
    print("Local time:", tm.format_datetime(tm.now()))
    print("Tehran time (write context):", tm.format_datetime(tm.tehran_now()))
    print("Timestamp:", tm.time())
    print("Manual UTC+3:30 (write context):", tm.format_datetime(tm.utc_offset_manual(hours=0)))
