import { useEffect, useCallback } from 'react';
import dayjs from 'dayjs';
import duration from 'dayjs/plugin/duration';
import relativeTime from 'dayjs/plugin/relativeTime';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';
import useSettingsStore from '../store/settings';
import useLocalStorage from '../hooks/useLocalStorage';

dayjs.extend(duration);
dayjs.extend(relativeTime);
dayjs.extend(utc);
dayjs.extend(timezone);

export const convertToMs = (dateTime) => dayjs(dateTime).valueOf();

export const initializeTime = (dateTime) => dayjs(dateTime);

export const startOfDay = (dateTime) => dayjs(dateTime).startOf('day');

export const isBefore = (date1, date2) => dayjs(date1).isBefore(date2);

export const isAfter = (date1, date2) => dayjs(date1).isAfter(date2);

export const isSame = (date1, date2, unit = 'day') => dayjs(date1).isSame(date2, unit);

export const add = (dateTime, value, unit) => dayjs(dateTime).add(value, unit);

export const diff = (date1, date2, unit = 'millisecond') => dayjs(date1).diff(date2, unit);

export const format = (dateTime, formatStr) => dayjs(dateTime).format(formatStr);

export const getNow = () => dayjs();

export const getNowMs = () => Date.now();

export const roundToNearest = (dateTime, minutes) => {
  const current = initializeTime(dateTime);
  const minute = current.minute();
  const snappedMinute = Math.round(minute / minutes) * minutes;

  return snappedMinute === 60
    ? current.add(1, 'hour').minute(0)
    : current.minute(snappedMinute);
};

export const useUserTimeZone = () => {
  const settings = useSettingsStore((s) => s.settings);
  const [timeZone, setTimeZone] = useLocalStorage(
    'time-zone',
    dayjs.tz?.guess
      ? dayjs.tz.guess()
      : Intl.DateTimeFormat().resolvedOptions().timeZone
  );

  useEffect(() => {
    const tz = settings?.['system-time-zone']?.value;
    if (tz && tz !== timeZone) {
      setTimeZone(tz);
    }
  }, [settings, timeZone, setTimeZone]);

  return timeZone;
};

export const useTimeHelpers = () => {
  const timeZone = useUserTimeZone();

  const toUserTime = useCallback(
    (value) => {
      if (!value) return dayjs.invalid();
      try {
        return initializeTime(value).tz(timeZone);
      } catch (error) {
        return initializeTime(value);
      }
    },
    [timeZone]
  );

  const userNow = useCallback(() => getNow().tz(timeZone), [timeZone]);

  return { timeZone, toUserTime, userNow };
};

export const RECURRING_DAY_OPTIONS = [
  { value: 6, label: 'Sun' },
  { value: 0, label: 'Mon' },
  { value: 1, label: 'Tue' },
  { value: 2, label: 'Wed' },
  { value: 3, label: 'Thu' },
  { value: 4, label: 'Fri' },
  { value: 5, label: 'Sat' },
];

export const useDateTimeFormat = () => {
  const [timeFormatSetting] = useLocalStorage('time-format', '12h');
  const [dateFormatSetting] = useLocalStorage('date-format', 'mdy');
  // Use user preference for time format
  const timeFormat = timeFormatSetting === '12h' ? 'h:mma' : 'HH:mm';
  const dateFormat = dateFormatSetting === 'mdy' ? 'MMM D' : 'D MMM';

  return [timeFormat, dateFormat]
};

export const toTimeString = (value) => {
  if (!value) return '00:00';
  if (typeof value === 'string') {
    const parsed = dayjs(value, ['HH:mm', 'HH:mm:ss', 'h:mm A'], true);
    if (parsed.isValid()) return parsed.format('HH:mm');
    return value;
  }
  const parsed = initializeTime(value);
  return parsed.isValid() ? parsed.format('HH:mm') : '00:00';
};

export const parseDate = (value) => {
  if (!value) return null;
  const parsed = dayjs(value, ['YYYY-MM-DD', dayjs.ISO_8601], true);
  return parsed.isValid() ? parsed.toDate() : null;
};