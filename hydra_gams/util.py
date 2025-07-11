import logging
import pandas as pd
from datetime import datetime, timedelta
from dateutil.parser import parse
from decimal import Decimal, ROUND_HALF_UP
import pytz

log = logging.getLogger(__name__)

FORMAT = "%Y-%m-%d %H:%M:%S.%f"

def date_to_string(date, seasonal=False):
    """Convert a date to a standard string used by Hydra. The resulting string
    looks like this::

        '2013-10-03 00:49:17.568-0400'

    Hydra also accepts seasonal time series (yearly recurring). If the flag
    ``seasonal`` is set to ``True``, this function will generate a string
    recognised by Hydra as seasonal time stamp.
    """

    seasonal_key = '9999'
    if seasonal:
        FORMAT = seasonal_key+'-%m-%dT%H:%M:%S.%f'
    else:
        FORMAT = '%Y-%m-%dT%H:%M:%S.%f'
    return date.strftime(FORMAT)

def reindex_timeseries(ts_string, new_timestamps):
    """
        get data for timesamp

        :param a JSON string, in pandas-friendly format
        :param a timestamp or list of timestamps (datetime)
        :returns a pandas data frame, reindexed with the supplied timestamps or None if no data is found
    """
    #If a single timestamp is passed in, turn it into a list
    #Reindexing can't work if it's not a list
    if not isinstance(new_timestamps, list):
        new_timestamps = [new_timestamps]

    #Convert the incoming timestamps to datetimes
    #if they are not datetimes.
    new_timestamps_converted = []
    for t in new_timestamps:
        new_timestamps_converted.append(get_datetime(t))

    new_timestamps = new_timestamps_converted

    seasonal_year = '1678'
    seasonal_key = '9999'

    ts = ts_string.replace(seasonal_key, seasonal_year)

    timeseries = pd.read_json(ts)

    idx = timeseries.index

    ts_timestamps = new_timestamps

    #'Fix' the incoming timestamp in case it's a seasonal value
    if type(idx) == pd.DatetimeIndex:
        if set(idx.year) == set([int(seasonal_year)]):
            if isinstance(new_timestamps,  list):
                seasonal_timestamp = []
                for t in ts_timestamps:
                    t_1900 = t.replace(year=int(seasonal_year))
                    seasonal_timestamp.append(t_1900)
                ts_timestamps = seasonal_timestamp

    #Reindex the timeseries to reflect the requested timestamps
    reindexed_ts = timeseries.reindex(ts_timestamps, method='ffill')

    i = reindexed_ts.index

    reindexed_ts.index = pd.Index(new_timestamps, names=i.names)

    #If there are no values at all, just return None
    if len(reindexed_ts.dropna()) == 0:
        return None

    #Replace all numpy NAN values with None
    pandas_ts = reindexed_ts.where(reindexed_ts.notnull(), None)

    return pandas_ts


def get_datetime(timestamp):
    """
        Turn a string timestamp into a date time. First tries to use dateutil.
        Failing that it tries to guess the time format and converts it manually
        using stfptime.

        @returns: A timezone unaware timestamp.
    """
    timestamp_is_float = False
    try:
        float(timestamp)
        timestamp_is_float = True
    except (ValueError, TypeError):
        pass

    if timestamp_is_float == True:
        raise ValueError("Timestamp %s is a float"%(timestamp,))

    #First try to use date util. Failing that, continue
    try:
        parsed_dt = parse(timestamp, dayfirst=False)
        return parsed_dt.astimezone(pytz.utc)
    except:
        pass

    if isinstance(timestamp, datetime):
        return timestamp.astimezone(pytz.utc)

    fmt = guess_timefmt(timestamp)
    if fmt is None:
        fmt = FORMAT

    # and proceed as usual
    try:
        ts_time = datetime.strptime(timestamp, fmt)
    except ValueError as e:
        if e.message.split(' ', 1)[0].strip() == 'unconverted':
            utcoffset = e.message.split()[3].strip()
            timestamp = timestamp.replace(utcoffset, '')
            ts_time = datetime.strptime(timestamp, fmt)
            # Apply offset
            tzoffset = timedelta(hours=int(utcoffset[0:3]),
                                          minutes=int(utcoffset[3:5]))
            ts_time -= tzoffset
        else:
            raise e

    return ts_time

def timestamp_to_ordinal(timestamp):
    """Convert a timestamp as defined in the soap interface to the time format
    stored in the database.
    """

    if timestamp is None:
        return None

    ts_time = get_datetime(timestamp)
    # Convert time to Gregorian ordinal (1 = January 1st, year 1)
    ordinal_ts_time = Decimal(ts_time.toordinal())
    total_seconds = (ts_time -
                     datetime(ts_time.year,
                                       ts_time.month,
                                       ts_time.day,
                                       0, 0, 0)).total_seconds()

    fraction = (Decimal(repr(total_seconds)) / Decimal(86400)).quantize(Decimal('.00000000000000000001'),rounding=ROUND_HALF_UP)
    ordinal_ts_time += fraction
    log.debug("%s converted to %s", timestamp, ordinal_ts_time)

    return ordinal_ts_time


def ordinal_to_timestamp(date):
    if date is None:
        return None

    if isinstance(date, six.string_types):
        try:
            date = Decimal(date)
        except:
            log.warning("Unable to convert %s to a timestamp" % (date))
            return date

    day = int(date)
    time = Decimal(str(date - day))
    time_in_secs_ms = (time * Decimal(86400)).quantize(Decimal('.000001'),
                                                       rounding=ROUND_HALF_UP)

    time_in_secs = int(time_in_secs_ms)
    time_in_ms = int((time_in_secs_ms - time_in_secs) * 1000000)

    td = timedelta(seconds=int(time_in_secs), microseconds=time_in_ms)
    d = datetime.fromordinal(day) + td
    log.debug("%s converted to %s", date, d)

    return get_datetime(d)

def guess_timefmt(datestr):
    """
    Try to guess the format a date is written in.

    The following formats are supported:

    ================= ============== ===============
    Format            Example        Python format
    ----------------- -------------- ---------------
    ``YYYY-MM-DD``    2002-04-21     %Y-%m-%d
    ``YYYY.MM.DD``    2002.04.21     %Y.%m.%d
    ``YYYY MM DD``    2002 04 21     %Y %m %d
    ``DD-MM-YYYY``    21-04-2002     %d-%m-%Y
    ``DD.MM.YYYY``    21.04.2002     %d.%m.%Y
    ``DD MM YYYY``    21 04 2002     %d %m %Y
    ``DD/MM/YYYY``    21/04/2002     %d/%m/%Y
    ================= ============== ===============

    These formats can also be used for seasonal (yearly recurring) time series.
    The year needs to be replaced by ``9999`` or another configurable year
    representing the seasonal year..

    The following formats are recognised depending on your locale setting.
    There is no guarantee that this will work.

    ================= ============== ===============
    Format            Example        Python format
    ----------------- -------------- ---------------
    ``DD-mmm-YYYY``   21-Apr-2002    %d-%b-%Y
    ``DD.mmm.YYYY``   21.Apr.2002    %d.%b.%Y
    ``DD mmm YYYY``   21 Apr 2002    %d %b %Y
    ``mmm DD YYYY``   Apr 21 2002    %b %d %Y
    ``Mmmmm DD YYYY`` April 21 2002  %B %d %Y
    ================= ============== ===============

    .. note::
        - The time needs to follow this definition without exception:
            `%H:%M:%S.%f`. A complete date and time should therefore look like
            this::

                2002-04-21 15:29:37.522

        - Be aware that in a file with comma separated values you should not
          use a date format that contains commas.
    """

    if isinstance(datestr, float) or isinstance(datestr, int):
        return None

    seasonal_key = '9999'

    #replace 'T' with space to handle ISO times.
    if datestr.find('T') > 0:
        dt_delim = 'T'
    else:
        dt_delim = ' '

    delimiters = ['-', '.', ' ', '/']
    formatstrings = [['%Y', '%m', '%d'],
                     ['%d', '%m', '%Y'],
                     ['%d', '%b', '%Y'],
                     ['XXXX', '%m', '%d'],
                     ['%d', '%m', 'XXXX'],
                     ['%d', '%b', 'XXXX'],
                     [seasonal_key, '%m', '%d'],
                     ['%d', '%m', seasonal_key],
                     ['%d', '%b', seasonal_key]]

    timeformats = ['%H:%M:%S.%f', '%H:%M:%S', '%H:%M', '%H:%M:%S.%f000Z', '%H:%M:%S.%fZ']

    # Check if a time is indicated or not
    for timefmt in timeformats:
        try:
            datetime.strptime(datestr.split(dt_delim)[-1].strip(), timefmt)
            usetime = True
            break
        except ValueError:
            usetime = False

    # Check the simple ones:
    for fmt in formatstrings:
        for delim in delimiters:
            datefmt = fmt[0] + delim + fmt[1] + delim + fmt[2]
            if usetime:
                for timefmt in timeformats:
                    complfmt = datefmt + dt_delim + timefmt
                    try:
                        datetime.strptime(datestr, complfmt)
                        return complfmt
                    except ValueError:
                        pass
            else:
                try:
                    datetime.strptime(datestr, datefmt)
                    return datefmt
                except ValueError:
                    pass

    # Check for other formats:
    custom_formats = ['%d/%m/%Y', '%b %d %Y', '%B %d %Y','%d/%m/XXXX', '%d/%m/'+seasonal_key]

    for fmt in custom_formats:
        if usetime:
            for timefmt in timeformats:
                complfmt = fmt + dt_delim + timefmt
                try:
                    datetime.strptime(datestr, complfmt)
                    return complfmt
                except ValueError:
                    pass

        else:
            try:
                datetime.strptime(datestr, fmt)
                return fmt
            except ValueError:
                pass

    return None