# apps/m3u/tasks.py
import logging
import re
import requests
import os
from celery.app.control import Inspect
from celery import shared_task, current_app
from django.conf import settings
from django.core.cache import cache
from .models import M3UAccount
from apps.channels.models import Stream
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)

LOCK_EXPIRE = 120  # Lock expires after 120 seconds

def _get_group_title(extinf_line: str) -> str:
    """Extract group title from EXTINF line."""
    match = re.search(r'group-title="([^"]*)"', extinf_line)
    return match.group(1) if match else "Default Group"

def _matches_filters(stream_name: str, group_name: str, filters) -> bool:
    logger.info("Testing filter")
    for f in filters:
        pattern = f.regex_pattern
        target = group_name if f.filter_type == 'group' else stream_name
        logger.info(f"Testing {pattern} on: {target}")
        if re.search(pattern, target or '', re.IGNORECASE):
            logger.debug(f"Filter matched: {pattern} on {target}. Exclude={f.exclude}")
            return f.exclude
    return False

def acquire_lock(task_name, account_id):
    """Acquire a lock to prevent concurrent task execution."""
    lock_id = f"task_lock_{task_name}_{account_id}"
    lock_acquired = cache.add(lock_id, "locked", timeout=LOCK_EXPIRE)
    if not lock_acquired:
        logger.warning(f"Lock for {task_name} and account_id={account_id} already acquired. Task will not proceed.")
    return lock_acquired

def release_lock(task_name, account_id):
    """Release the lock after task execution."""
    lock_id = f"task_lock_{task_name}_{account_id}"
    cache.delete(lock_id)

@shared_task
def refresh_m3u_accounts():
    """Queue background parse for all active M3UAccounts."""
    active_accounts = M3UAccount.objects.filter(is_active=True)
    count = 0
    for account in active_accounts:
        refresh_single_m3u_account.delay(account.id)
        count += 1

    msg = f"Queued M3U refresh for {count} active account(s)."
    logger.info(msg)
    return msg

@shared_task
def refresh_single_m3u_account(account_id):
    logger.info(f"Task {refresh_single_m3u_account.request.id}: Starting refresh for account_id={account_id}")

    if not acquire_lock('refresh_single_m3u_account', account_id):
        return f"Task already running for account_id={account_id}."

    try:
        account = M3UAccount.objects.get(id=account_id, is_active=True)
        filters = list(account.filters.all())
        logger.info(f"Found active M3UAccount (id={account.id}, name={account.name}).")
    except M3UAccount.DoesNotExist:
        msg = f"M3UAccount with ID={account_id} not found or inactive."
        logger.warning(msg)
        release_lock('refresh_single_m3u_account', account_id)
        return msg
    except Exception as e:
        logger.error(f"Error fetching M3UAccount {account_id}: {e}")
        release_lock('refresh_single_m3u_account', account_id)
        return str(e)

    try:
        lines = []
        if account.server_url:
            if not account.user_agent:
                err_msg = f"User-Agent not provided for account id {account_id}."
                logger.error(err_msg)
                release_lock('refresh_single_m3u_account', account_id)
                return err_msg

            headers = {"User-Agent": account.user_agent.user_agent}
            response = requests.get(account.server_url, timeout=60, headers=headers)
            response.raise_for_status()
            lines = response.text.splitlines()
        elif account.uploaded_file:
            file_path = account.uploaded_file.path
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.read().splitlines()
        else:
            err_msg = f"No server_url or uploaded_file provided for account_id={account_id}."
            logger.error(err_msg)
            release_lock('refresh_single_m3u_account', account_id)
            return err_msg
    except Exception as e:
        err_msg = f"Failed fetching M3U: {e}"
        logger.error(err_msg)
        release_lock('refresh_single_m3u_account', account_id)
        return err_msg

    logger.info(f"M3U has {len(lines)} lines. Now parsing for Streams.")
    skip_exts = ('.mkv', '.mp4', '.ts', '.m4v', '.wav', '.avi', '.flv', '.m4p', '.mpg',
                 '.mpeg', '.m2v', '.mp2', '.mpe', '.mpv')

    created_count, updated_count, excluded_count = 0, 0, 0
    current_info = None

    for line in lines:
        line = line.strip()
        if line.startswith('#EXTINF'):
            tvg_name_match = re.search(r'tvg-name="([^"]*)"', line)
            tvg_logo_match = re.search(r'tvg-logo="([^"]*)"', line)
            # Extract tvg-id
            tvg_id_match = re.search(r'tvg-id="([^"]*)"', line)
            tvg_id = tvg_id_match.group(1) if tvg_id_match else ""

            fallback_name = line.split(",", 1)[-1].strip() if "," in line else "Default Stream"

            name = tvg_name_match.group(1) if tvg_name_match else fallback_name
            logo_url = tvg_logo_match.group(1) if tvg_logo_match else ""
            group_title = _get_group_title(line)

            logger.debug(f"Parsed EXTINF: name={name}, logo_url={logo_url}, tvg_id={tvg_id}, group_title={group_title}")
            current_info = {
                "name": name,
                "logo_url": logo_url,
                "group_title": group_title,
                "tvg_id": tvg_id,  # save the tvg-id here
            }

        elif current_info and line.startswith('http'):
            lower_line = line.lower()
            if any(lower_line.endswith(ext) for ext in skip_exts):
                logger.debug(f"Skipping file with unsupported extension: {line}")
                current_info = None
                continue

            if len(line) > 2000:
                logger.warning(f"Stream URL too long, skipping: {line}")
                excluded_count += 1
                current_info = None
                continue

            if _matches_filters(current_info['name'], current_info['group_title'], filters):
                logger.info(f"Stream excluded by filter: {current_info['name']} in group {current_info['group_title']}")
                excluded_count += 1
                current_info = None
                continue

            # Include tvg_id in the defaults so it gets saved
            defaults = {
                "logo_url": current_info["logo_url"],
                "tvg_id": current_info["tvg_id"]
            }
            try:
                obj, created = Stream.objects.update_or_create(
                    name=current_info["name"],
                    custom_url=line,
                    m3u_account=account,
                    group_name=current_info["group_title"],
                    defaults=defaults
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1
            except Exception as e:
                logger.error(f"Failed to update/create stream {current_info['name']}: {e}")
            finally:
                current_info = None

    logger.info(f"Completed parsing. Created {created_count} new Streams, updated {updated_count} existing Streams, excluded {excluded_count} Streams.")
    release_lock('refresh_single_m3u_account', account_id)
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "updates",
        {
            "type": "m3u_refresh",
            "message": {"success": True, "message": "M3U refresh completed successfully"}
        },
    )
    return f"Account {account_id} => Created {created_count}, updated {updated_count}, excluded {excluded_count} Streams."

def process_uploaded_m3u_file(file, account):
    """Save and parse an uploaded M3U file."""
    upload_dir = os.path.join(settings.MEDIA_ROOT, 'm3u_uploads')
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.name)

    with open(file_path, 'wb+') as destination:
        for chunk in file.chunks():
            destination.write(chunk)

    try:
        parse_m3u_file(file_path, account)
    except Exception as e:
        logger.error(f"Error parsing uploaded M3U file {file_path}: {e}")

def parse_m3u_file(file_path, account):
    """Parse a local M3U file and create or update Streams."""
    skip_exts = ('.mkv', '.mp4', '.ts', '.m4v', '.wav', '.avi', '.flv', '.m4p', '.mpg',
                 '.mpeg', '.m2v', '.mp2', '.mpe', '.mpv')

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
    except Exception as e:
        logger.error(f"Failed to read M3U file {file_path}: {e}")
        return f"Error reading M3U file {file_path}"

    created_count, updated_count, excluded_count = 0, 0, 0
    current_info = None

    for line in lines:
        line = line.strip()
        if line.startswith('#EXTINF'):
            tvg_name_match = re.search(r'tvg-name="([^"]*)"', line)
            tvg_logo_match = re.search(r'tvg-logo="([^"]*)"', line)
            fallback_name = line.split(",", 1)[-1].strip() if "," in line else "Stream"
            tvg_id_match = re.search(r'tvg-id="([^"]*)"', line)
            tvg_id = tvg_id_match.group(1) if tvg_id_match else ""

            name = tvg_name_match.group(1) if tvg_name_match else fallback_name
            logo_url = tvg_logo_match.group(1) if tvg_logo_match else ""

            current_info = {"name": name, "logo_url": logo_url, "tvg_id": tvg_id}

        elif current_info and line.startswith('http'):
            lower_line = line.lower()
            if any(lower_line.endswith(ext) for ext in skip_exts):
                logger.info(f"Skipping file with unsupported extension: {line}")
                current_info = None
                continue

            defaults = {
                "logo_url": current_info["logo_url"],
                "tvg_id": current_info.get("tvg_id", "")
            }

            try:
                obj, created = Stream.objects.update_or_create(
                    name=current_info["name"],
                    custom_url=line,
                    m3u_account=account,
                    defaults=defaults
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1
            except Exception as e:
                logger.error(f"Failed to update/create stream {current_info['name']}: {e}")
            finally:
                current_info = None

    return f"Parsed local M3U file {file_path}, created {created_count} Streams, updated {updated_count} Streams, excluded {excluded_count} Streams."
