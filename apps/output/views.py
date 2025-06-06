from django.http import HttpResponse
from django.urls import reverse
from apps.channels.models import Channel, ChannelProfile, Logo
from apps.epg.models import ProgramData
from django.utils import timezone
from datetime import datetime, timedelta
import re
import html  # Add this import for XML escaping
import hashlib  # Add this import for hashing

def generate_m3u(request, profile_name=None):
    """
    Dynamically generate an M3U file from channels.
    The stream URL now points to the new stream_view that uses StreamProfile.
    """
    if profile_name is not None:
        channel_profile = ChannelProfile.objects.get(name=profile_name)
        channels = Channel.objects.filter(
            channelprofilemembership__channel_profile=channel_profile,
            channelprofilemembership__enabled=True
        ).order_by('channel_number')
    else:
        channels = Channel.objects.order_by('channel_number')

    # Check if the request wants to use direct logo URLs instead of cache
    use_cached_logos = request.GET.get('cachedlogos', 'true').lower() != 'false'

    # Check if direct stream URLs should be used instead of proxy
    use_direct_urls = request.GET.get('direct', 'false').lower() == 'true'

    # Get the source to use for tvg-id value
    # Options: 'channel_number' (default), 'tvg_id', 'gracenote'
    tvg_id_source = request.GET.get('tvg_id_source', 'channel_number').lower()

    m3u_content = "#EXTM3U\n"
    for channel in channels:
        group_title = channel.channel_group.name if channel.channel_group else "Default"

        # Format channel number as integer if it has no decimal component
        if channel.channel_number is not None:
            if channel.channel_number == int(channel.channel_number):
                formatted_channel_number = int(channel.channel_number)
            else:
                formatted_channel_number = channel.channel_number
        else:
            formatted_channel_number = ""

        # Determine the tvg-id based on the selected source
        if tvg_id_source == 'tvg_id' and channel.tvg_id:
            tvg_id = channel.tvg_id
        elif tvg_id_source == 'gracenote' and channel.tvc_guide_stationid:
            tvg_id = channel.tvc_guide_stationid
        else:
            # Default to channel number (original behavior)
            tvg_id = str(formatted_channel_number) if formatted_channel_number != "" else str(channel.id)

        tvg_name = channel.name

        tvg_logo = ""
        if channel.logo:
            if use_cached_logos:
                # Use cached logo as before
                tvg_logo = request.build_absolute_uri(reverse('api:channels:logo-cache', args=[channel.logo.id]))
            else:
                # Try to find direct logo URL from channel's streams
                direct_logo = channel.logo.url if channel.logo.url.startswith(('http://', 'https://')) else None
                # If direct logo found, use it; otherwise fall back to cached version
                if direct_logo:
                    tvg_logo = direct_logo
                else:
                    tvg_logo = request.build_absolute_uri(reverse('api:channels:logo-cache', args=[channel.logo.id]))

        # create possible gracenote id insertion
        tvc_guide_stationid = ""
        if channel.tvc_guide_stationid:
            tvc_guide_stationid = f'tvc-guide-stationid="{channel.tvc_guide_stationid}" '

        extinf_line = (
            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{tvg_name}" tvg-logo="{tvg_logo}" '
            f'tvg-chno="{formatted_channel_number}" {tvc_guide_stationid}group-title="{group_title}",{channel.name}\n'
        )

        # Determine the stream URL based on the direct parameter
        if use_direct_urls:
            # Try to get the first stream's direct URL
            first_stream = channel.streams.first()
            if first_stream and first_stream.url:
                # Use the direct stream URL
                stream_url = first_stream.url
            else:
                # Fall back to proxy URL if no direct URL available
                base_url = request.build_absolute_uri('/')[:-1]
                stream_url = f"{base_url}/proxy/ts/stream/{channel.uuid}"
        else:
            # Standard behavior - use proxy URL
            base_url = request.build_absolute_uri('/')[:-1]
            stream_url = f"{base_url}/proxy/ts/stream/{channel.uuid}"

        m3u_content += extinf_line + stream_url + "\n"

    response = HttpResponse(m3u_content, content_type="audio/x-mpegurl")
    response['Content-Disposition'] = 'attachment; filename="channels.m3u"'
    return response

def generate_dummy_epg(channel_id, channel_name, xml_lines=None, num_days=1, program_length_hours=4):
    """
    Generate dummy EPG programs for channels without EPG data.
    Creates program blocks for a specified number of days.

    Args:
        channel_id: The channel ID to use in the program entries
        channel_name: The name of the channel to use in program titles
        xml_lines: Optional list to append lines to, otherwise returns new list
        num_days: Number of days to generate EPG data for (default: 1)
        program_length_hours: Length of each program block in hours (default: 4)

    Returns:
        List of XML lines for the dummy EPG entries
    """
    if xml_lines is None:
        xml_lines = []

    # Get current time rounded to hour
    now = timezone.now()
    now = now.replace(minute=0, second=0, microsecond=0)

    # Humorous program descriptions based on time of day
    time_descriptions = {
        (0, 4): [
            f"Late Night with {channel_name} - Where insomniacs unite!",
            f"The 'Why Am I Still Awake?' Show on {channel_name}",
            f"Counting Sheep - A {channel_name} production for the sleepless"
        ],
        (4, 8): [
            f"Dawn Patrol - Rise and shine with {channel_name}!",
            f"Early Bird Special - Coffee not included",
            f"Morning Zombies - Before coffee viewing on {channel_name}"
        ],
        (8, 12): [
            f"Mid-Morning Meetings - Pretend you're paying attention while watching {channel_name}",
            f"The 'I Should Be Working' Hour on {channel_name}",
            f"Productivity Killer - {channel_name}'s daytime programming"
        ],
        (12, 16): [
            f"Lunchtime Laziness with {channel_name}",
            f"The Afternoon Slump - Brought to you by {channel_name}",
            f"Post-Lunch Food Coma Theater on {channel_name}"
        ],
        (16, 20): [
            f"Rush Hour - {channel_name}'s alternative to traffic",
            f"The 'What's For Dinner?' Debate on {channel_name}",
            f"Evening Escapism - {channel_name}'s remedy for reality"
        ],
        (20, 24): [
            f"Prime Time Placeholder - {channel_name}'s finest not-programming",
            f"The 'Netflix Was Too Complicated' Show on {channel_name}",
            f"Family Argument Avoider - Courtesy of {channel_name}"
        ]
    }

    # Create programs for each day
    for day in range(num_days):
        day_start = now + timedelta(days=day)

        # Create programs with specified length throughout the day
        for hour_offset in range(0, 24, program_length_hours):
            # Calculate program start and end times
            start_time = day_start + timedelta(hours=hour_offset)
            end_time = start_time + timedelta(hours=program_length_hours)

            # Get the hour for selecting a description
            hour = start_time.hour

            # Find the appropriate time slot for description
            for time_range, descriptions in time_descriptions.items():
                start_range, end_range = time_range
                if start_range <= hour < end_range:
                    # Pick a description using the sum of the hour and day as seed
                    # This makes it somewhat random but consistent for the same timeslot
                    description = descriptions[(hour + day) % len(descriptions)]
                    break
            else:
                # Fallback description if somehow no range matches
                description = f"Placeholder program for {channel_name} - EPG data went on vacation"

            # Format times in XMLTV format
            start_str = start_time.strftime("%Y%m%d%H%M%S %z")
            stop_str = end_time.strftime("%Y%m%d%H%M%S %z")

            # Create program entry with escaped channel name
            xml_lines.append(f'  <programme start="{start_str}" stop="{stop_str}" channel="{channel_id}">')
            xml_lines.append(f'    <title>{html.escape(channel_name)}</title>')
            xml_lines.append(f'    <desc>{html.escape(description)}</desc>')
            xml_lines.append(f'  </programme>')

    return xml_lines

def generate_epg(request, profile_name=None):
    """
    Dynamically generate an XMLTV (EPG) file using the new EPGData/ProgramData models.
    Since the EPG data is stored independently of Channels, we group programmes
    by their associated EPGData record.
    This version filters data based on the 'days' parameter.
    """
    xml_lines = []
    xml_lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    xml_lines.append('<tv generator-info-name="Dispatcharr" generator-info-url="https://github.com/Dispatcharr/Dispatcharr">')

    if profile_name is not None:
        channel_profile = ChannelProfile.objects.get(name=profile_name)
        channels = Channel.objects.filter(
            channelprofilemembership__channel_profile=channel_profile,
            channelprofilemembership__enabled=True
        )
    else:
        channels = Channel.objects.all()

    # Check if the request wants to use direct logo URLs instead of cache
    use_cached_logos = request.GET.get('cachedlogos', 'true').lower() != 'false'

    # Get the source to use for tvg-id value
    # Options: 'channel_number' (default), 'tvg_id', 'gracenote'
    tvg_id_source = request.GET.get('tvg_id_source', 'channel_number').lower()

    # Get the number of days for EPG data
    try:
        # Default to 0 days (everything) for real EPG if not specified
        days_param = request.GET.get('days', '0')
        num_days = int(days_param)
        # Set reasonable limits
        num_days = max(0, min(num_days, 365))  # Between 0 and 365 days
    except ValueError:
        num_days = 0  # Default to all data if invalid value

    # For dummy EPG, use either the specified value or default to 3 days
    dummy_days = num_days if num_days > 0 else 3

    # Calculate cutoff date for EPG data filtering (only if days > 0)
    now = timezone.now()
    cutoff_date = now + timedelta(days=num_days) if num_days > 0 else None

    # Retrieve all active channels
    for channel in channels:
        # Format channel number as integer if it has no decimal component - same as M3U generation
        if channel.channel_number is not None:
            if channel.channel_number == int(channel.channel_number):
                formatted_channel_number = int(channel.channel_number)
            else:
                formatted_channel_number = channel.channel_number
        else:
            formatted_channel_number = ""

        # Determine the channel ID based on the selected source
        if tvg_id_source == 'tvg_id' and channel.tvg_id:
            channel_id = channel.tvg_id
        elif tvg_id_source == 'gracenote' and channel.tvc_guide_stationid:
            channel_id = channel.tvc_guide_stationid
        else:
            # Default to channel number (original behavior)
            channel_id = str(formatted_channel_number) if formatted_channel_number != "" else str(channel.id)

        # Add channel logo if available
        tvg_logo = ""
        if channel.logo:
            if use_cached_logos:
                # Use cached logo as before
                tvg_logo = request.build_absolute_uri(reverse('api:channels:logo-cache', args=[channel.logo.id]))
            else:
                # Try to find direct logo URL from channel's streams
                direct_logo = channel.logo.url if channel.logo.url.startswith(('http://', 'https://')) else None
                # If direct logo found, use it; otherwise fall back to cached version
                if direct_logo:
                    tvg_logo = direct_logo
                else:
                    tvg_logo = request.build_absolute_uri(reverse('api:channels:logo-cache', args=[channel.logo.id]))
        display_name = channel.epg_data.name if channel.epg_data else channel.name
        xml_lines.append(f'  <channel id="{channel_id}">')
        xml_lines.append(f'    <display-name>{html.escape(display_name)}</display-name>')
        xml_lines.append(f'    <icon src="{html.escape(tvg_logo)}" />')

        xml_lines.append('  </channel>')

    for channel in channels:
        # Use the same channel ID determination for program entries
        if tvg_id_source == 'tvg_id' and channel.tvg_id:
            channel_id = channel.tvg_id
        elif tvg_id_source == 'gracenote' and channel.tvc_guide_stationid:
            channel_id = channel.tvc_guide_stationid
        else:
            # Get formatted channel number
            if channel.channel_number is not None:
                if channel.channel_number == int(channel.channel_number):
                    formatted_channel_number = int(channel.channel_number)
                else:
                    formatted_channel_number = channel.channel_number
            else:
                formatted_channel_number = ""
            # Default to channel number
            channel_id = str(formatted_channel_number) if formatted_channel_number != "" else str(channel.id)

        display_name = channel.epg_data.name if channel.epg_data else channel.name
        if not channel.epg_data:
            # Use the enhanced dummy EPG generation function with defaults
            program_length_hours = 4  # Default to 4-hour program blocks
            generate_dummy_epg(
                channel_id,
                display_name,
                xml_lines,
                num_days=dummy_days,  # Use dummy_days (3 days by default)
                program_length_hours=program_length_hours
            )
        else:
            # For real EPG data - filter only if days parameter was specified
            if num_days > 0:
                programs = channel.epg_data.programs.filter(
                    start_time__gte=now,
                    start_time__lt=cutoff_date
                )
            else:
                # Return all programs if days=0 or not specified
                programs = channel.epg_data.programs.all()

            for prog in programs:
                start_str = prog.start_time.strftime("%Y%m%d%H%M%S %z")
                stop_str = prog.end_time.strftime("%Y%m%d%H%M%S %z")
                xml_lines.append(f'  <programme start="{start_str}" stop="{stop_str}" channel="{channel_id}">')
                xml_lines.append(f'    <title>{html.escape(prog.title)}</title>')

                # Add subtitle if available
                if prog.sub_title:
                    xml_lines.append(f'    <sub-title>{html.escape(prog.sub_title)}</sub-title>')

                # Add description if available
                if prog.description:
                    xml_lines.append(f'    <desc>{html.escape(prog.description)}</desc>')

                # Process custom properties if available
                if prog.custom_properties:
                    try:
                        import json
                        custom_data = json.loads(prog.custom_properties)

                        # Add categories if available
                        if 'categories' in custom_data and custom_data['categories']:
                            for category in custom_data['categories']:
                                xml_lines.append(f'    <category>{html.escape(category)}</category>')

                        # Handle episode numbering - multiple formats supported
                        # Standard episode number if available
                        if 'episode' in custom_data:
                            xml_lines.append(f'    <episode-num system="onscreen">E{custom_data["episode"]}</episode-num>')

                        # Handle onscreen episode format (like S06E128)
                        if 'onscreen_episode' in custom_data:
                            xml_lines.append(f'    <episode-num system="onscreen">{html.escape(custom_data["onscreen_episode"])}</episode-num>')

                        # Handle dd_progid format
                        if 'dd_progid' in custom_data:
                            xml_lines.append(f'    <episode-num system="dd_progid">{html.escape(custom_data["dd_progid"])}</episode-num>')

                        # Add season and episode numbers in xmltv_ns format if available
                        if 'season' in custom_data and 'episode' in custom_data:
                            season = int(custom_data['season']) - 1 if str(custom_data['season']).isdigit() else 0
                            episode = int(custom_data['episode']) - 1 if str(custom_data['episode']).isdigit() else 0
                            xml_lines.append(f'    <episode-num system="xmltv_ns">{season}.{episode}.</episode-num>')

                        # Add rating if available
                        if 'rating' in custom_data:
                            rating_system = custom_data.get('rating_system', 'TV Parental Guidelines')
                            xml_lines.append(f'    <rating system="{html.escape(rating_system)}">')
                            xml_lines.append(f'      <value>{html.escape(custom_data["rating"])}</value>')
                            xml_lines.append(f'    </rating>')

                        # Add actors/directors/writers if available
                        if 'credits' in custom_data:
                            xml_lines.append(f'    <credits>')
                            for role, people in custom_data['credits'].items():
                                if isinstance(people, list):
                                    for person in people:
                                        xml_lines.append(f'      <{role}>{html.escape(person)}</{role}>')
                                else:
                                    xml_lines.append(f'      <{role}>{html.escape(people)}</{role}>')
                            xml_lines.append(f'    </credits>')

                        # Add program date/year if available
                        if 'year' in custom_data:
                            xml_lines.append(f'    <date>{html.escape(custom_data["year"])}</date>')

                        # Add country if available
                        if 'country' in custom_data:
                            xml_lines.append(f'    <country>{html.escape(custom_data["country"])}</country>')

                        # Add icon if available
                        if 'icon' in custom_data:
                            icon_url = custom_data["icon"]

                            if use_cached_logos and icon_url.startswith(('http://', 'https://')):
                                # Hash the URL to create a cache key
                                url_hash = hashlib.md5(icon_url.encode()).hexdigest()

                                # Create a cached URL that nginx can intercept and handle
                                cached_icon = request.build_absolute_uri(
                                    reverse('images:proxy', args=[url_hash])
                                ) + f"?url={html.escape(icon_url)}"
                            else:
                                # When caching is disabled, use the direct URL
                                cached_icon = icon_url

                            xml_lines.append(f'    <icon src="{html.escape(cached_icon)}" />')

                        # Add special flags as proper tags
                        if custom_data.get('previously_shown', False):
                            xml_lines.append(f'    <previously-shown />')

                        if custom_data.get('premiere', False):
                            xml_lines.append(f'    <premiere />')

                        if custom_data.get('new', False):
                            xml_lines.append(f'    <new />')

                        if custom_data.get('live', False):
                            xml_lines.append(f'    <live />')

                    except Exception as e:
                        xml_lines.append(f'    <!-- Error parsing custom properties: {html.escape(str(e))} -->')

                xml_lines.append('  </programme>')

    xml_lines.append('</tv>')
    xml_content = "\n".join(xml_lines)

    response = HttpResponse(xml_content, content_type="application/xml")
    response['Content-Disposition'] = 'attachment; filename="epg.xml"'
    return response
