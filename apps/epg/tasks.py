import logging
import gzip  # <-- New import for gzip support
from celery import shared_task
from .models import EPGSource, EPGData, ProgramData
from django.utils import timezone
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone as dt_timezone
from django.db import transaction

logger = logging.getLogger(__name__)

@shared_task
def refresh_epg_data():
    logger.info("Starting refresh_epg_data task.")
    active_sources = EPGSource.objects.filter(is_active=True)
    logger.debug(f"Found {active_sources.count()} active EPGSource(s).")
    for source in active_sources:
        logger.info(f"Processing EPGSource: {source.name} (type: {source.source_type})")
        if source.source_type == 'xmltv':
            fetch_xmltv(source)
        elif source.source_type == 'schedules_direct':
            fetch_schedules_direct(source)
    logger.info("Finished refresh_epg_data task.")
    return "EPG data refreshed."

def fetch_xmltv(source):
    logger.info(f"Fetching XMLTV data from source: {source.name}")
    try:
        response = requests.get(source.url, timeout=30)
        response.raise_for_status()
        logger.debug("XMLTV data fetched successfully.")
        
        # If the URL ends with '.gz', decompress the response content
        if source.url.lower().endswith('.gz'):
            logger.debug("Detected .gz file. Decompressing...")
            decompressed_bytes = gzip.decompress(response.content)
            xml_data = decompressed_bytes.decode('utf-8')
        else:
            xml_data = response.text

        root = ET.fromstring(xml_data)
        logger.debug("Parsed XMLTV XML content.")

        # Group programmes by their tvg_id from the XMLTV file
        programmes_by_channel = {}
        for programme in root.findall('programme'):
            start_time = parse_xmltv_time(programme.get('start'))
            stop_time = parse_xmltv_time(programme.get('stop'))
            tvg_id = programme.get('channel')
            title = programme.findtext('title', default='No Title')
            desc = programme.findtext('desc', default='')

            programmes_by_channel.setdefault(tvg_id, []).append({
                'start_time': start_time,
                'end_time': stop_time,
                'title': title,
                'description': desc,
                'tvg_id': tvg_id,
            })

        # Process each group regardless of channel existence.
        for tvg_id, programmes in programmes_by_channel.items():
            # Create (or get) an EPGData record using the tvg_id.
            epg_data, created = EPGData.objects.get_or_create(
                tvg_id=tvg_id,
                defaults={'channel_name': tvg_id}  # Use tvg_id as a fallback name
            )
            if created:
                logger.info(f"Created new EPGData for tvg_id '{tvg_id}'.")
            else:
                logger.debug(f"Found existing EPGData for tvg_id '{tvg_id}'.")

            logger.info(f"Processing {len(programmes)} programme(s) for tvg_id '{tvg_id}'.")
            with transaction.atomic():
                for prog in programmes:
                    obj, created = ProgramData.objects.update_or_create(
                        epg=epg_data,
                        start_time=prog['start_time'],
                        title=prog['title'],
                        defaults={
                            'end_time': prog['end_time'],
                            'description': prog['description'],
                            'sub_title': '',
                            'tvg_id': tvg_id,
                        }
                    )
                    if created:
                        logger.info(f"Created ProgramData '{prog['title']}' for tvg_id '{tvg_id}'.")
                    else:
                        logger.info(f"Updated ProgramData '{prog['title']}' for tvg_id '{tvg_id}'.")
    except Exception as e:
        logger.error(f"Error fetching XMLTV from {source.name}: {e}", exc_info=True)

def fetch_schedules_direct(source):
    logger.info(f"Fetching Schedules Direct data from source: {source.name}")
    try:
        # NOTE: Provide the correct api_url for Schedules Direct.
        api_url = ''
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {source.api_key}',
        }
        logger.debug(f"Requesting subscriptions from Schedules Direct using URL: {api_url}")
        response = requests.get(api_url, headers=headers, timeout=30)
        response.raise_for_status()
        subscriptions = response.json()
        logger.debug(f"Fetched subscriptions: {subscriptions}")

        for sub in subscriptions:
            tvg_id = sub.get('stationID')
            logger.debug(f"Processing subscription for tvg_id: {tvg_id}")
            schedules_url = f"/schedules/{tvg_id}"
            logger.debug(f"Requesting schedules from URL: {schedules_url}")
            sched_response = requests.get(schedules_url, headers=headers, timeout=30)
            sched_response.raise_for_status()
            schedules = sched_response.json()
            logger.debug(f"Fetched schedules: {schedules}")

            # Create (or get) an EPGData record using the tvg_id.
            epg_data, created = EPGData.objects.get_or_create(
                tvg_id=tvg_id,
                defaults={'channel_name': tvg_id}
            )
            if created:
                logger.info(f"Created new EPGData for tvg_id '{tvg_id}'.")
            else:
                logger.debug(f"Found existing EPGData for tvg_id '{tvg_id}'.")

            for sched in schedules.get('schedules', []):
                title = sched.get('title', 'No Title')
                desc = sched.get('description', '')
                start_time = parse_schedules_direct_time(sched.get('startTime'))
                end_time = parse_schedules_direct_time(sched.get('endTime'))
                obj, created = ProgramData.objects.update_or_create(
                    epg=epg_data,
                    start_time=start_time,
                    title=title,
                    defaults={
                        'end_time': end_time,
                        'description': desc,
                        'sub_title': ''
                    }
                )
                if created:
                    logger.info(f"Created ProgramData '{title}' for tvg_id '{tvg_id}'.")
                else:
                    logger.info(f"Updated ProgramData '{title}' for tvg_id '{tvg_id}'.")
    except Exception as e:
        logger.error(f"Error fetching Schedules Direct data from {source.name}: {e}", exc_info=True)

def parse_xmltv_time(time_str):
    try:
        dt_obj = datetime.strptime(time_str[:14], '%Y%m%d%H%M%S')
        tz_sign = time_str[15]
        tz_hours = int(time_str[16:18])
        tz_minutes = int(time_str[18:20])
        if tz_sign == '+':
            dt_obj = dt_obj - timedelta(hours=tz_hours, minutes=tz_minutes)
        elif tz_sign == '-':
            dt_obj = dt_obj + timedelta(hours=tz_hours, minutes=tz_minutes)
        aware_dt = timezone.make_aware(dt_obj, timezone=dt_timezone.utc)
        logger.debug(f"Parsed XMLTV time '{time_str}' to {aware_dt}")
        return aware_dt
    except Exception as e:
        logger.error(f"Error parsing XMLTV time '{time_str}': {e}", exc_info=True)
        raise

def parse_schedules_direct_time(time_str):
    try:
        dt_obj = datetime.strptime(time_str, '%Y-%m-%dT%H:%M:%SZ')
        aware_dt = timezone.make_aware(dt_obj, timezone=dt_timezone.utc)
        logger.debug(f"Parsed Schedules Direct time '{time_str}' to {aware_dt}")
        return aware_dt
    except Exception as e:
        logger.error(f"Error parsing Schedules Direct time '{time_str}': {e}", exc_info=True)
        raise
