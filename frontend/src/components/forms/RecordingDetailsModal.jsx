import useChannelsStore from '../../store/channels.jsx';
import { useDateTimeFormat, useTimeHelpers } from '../../utils/dateTimeUtils.js';
import React from 'react';
import API from '../../api.js';
import {
  Badge,
  Button,
  Card,
  Flex,
  Group,
  Image,
  Modal,
  Stack,
  Text,
} from '@mantine/core';
import useVideoStore from '../../store/useVideoStore.jsx';
import { notifications } from '@mantine/notifications';

export const RecordingDetailsModal = ({
                                        opened,
                                        onClose,
                                        recording,
                                        channel,
                                        posterUrl,
                                        onWatchLive,
                                        onWatchRecording,
                                        env_mode,
                                        onEdit,
                                      }) => {
  const allRecordings = useChannelsStore((s) => s.recordings);
  const channelMap = useChannelsStore((s) => s.channels);
  const { toUserTime, userNow } = useTimeHelpers();
  const [childOpen, setChildOpen] = React.useState(false);
  const [childRec, setChildRec] = React.useState(null);
  const [timeformat, dateformat] = useDateTimeFormat();

  const safeRecording = recording || {};
  const customProps = safeRecording.custom_properties || {};
  const program = customProps.program || {};
  const recordingName = program.title || 'Custom Recording';
  const description = program.description || customProps.description || '';
  const start = toUserTime(safeRecording.start_time);
  const end = toUserTime(safeRecording.end_time);
  const stats = customProps.stream_info || {};

  const statRows = [
    ['Video Codec', stats.video_codec],
    [
      'Resolution',
      stats.resolution ||
      (stats.width && stats.height ? `${stats.width}x${stats.height}` : null),
    ],
    ['FPS', stats.source_fps],
    ['Video Bitrate', stats.video_bitrate && `${stats.video_bitrate} kb/s`],
    ['Audio Codec', stats.audio_codec],
    ['Audio Channels', stats.audio_channels],
    ['Sample Rate', stats.sample_rate && `${stats.sample_rate} Hz`],
    ['Audio Bitrate', stats.audio_bitrate && `${stats.audio_bitrate} kb/s`],
  ].filter(([, v]) => v !== null && v !== undefined && v !== '');

  // Rating (if available)
  const rating =
    customProps.rating ||
    customProps.rating_value ||
    (program && program.custom_properties && program.custom_properties.rating);
  const ratingSystem = customProps.rating_system || 'MPAA';

  const fileUrl = customProps.file_url || customProps.output_file_url;
  const canWatchRecording =
    (customProps.status === 'completed' ||
      customProps.status === 'interrupted') &&
    Boolean(fileUrl);

  // Prefix in dev (Vite) if needed
  let resolvedPosterUrl = posterUrl;
  if (
    typeof import.meta !== 'undefined' &&
    import.meta.env &&
    import.meta.env.DEV
  ) {
    if (resolvedPosterUrl && resolvedPosterUrl.startsWith('/')) {
      resolvedPosterUrl = `${window.location.protocol}//${window.location.hostname}:5656${resolvedPosterUrl}`;
    }
  }

  const isSeriesGroup = Boolean(
    safeRecording._group_count && safeRecording._group_count > 1
  );
  const upcomingEpisodes = React.useMemo(() => {
    if (!isSeriesGroup) return [];
    const arr = Array.isArray(allRecordings)
      ? allRecordings
      : Object.values(allRecordings || {});
    const tvid = program.tvg_id || '';
    const titleKey = (program.title || '').toLowerCase();
    const filtered = arr.filter((r) => {
      const cp = r.custom_properties || {};
      const pr = cp.program || {};
      if ((pr.tvg_id || '') !== tvid) return false;
      if ((pr.title || '').toLowerCase() !== titleKey) return false;
      const st = toUserTime(r.start_time);
      return st.isAfter(userNow());
    });
    // Deduplicate by program.id if present, else by time+title
    const seen = new Set();
    const deduped = [];
    for (const r of filtered) {
      const cp = r.custom_properties || {};
      const pr = cp.program || {};
      // Prefer season/episode or onscreen code; else fall back to sub_title; else program id/slot
      const season = cp.season ?? pr?.custom_properties?.season;
      const episode = cp.episode ?? pr?.custom_properties?.episode;
      const onscreen =
        cp.onscreen_episode ?? pr?.custom_properties?.onscreen_episode;
      let key = null;
      if (season != null && episode != null) key = `se:${season}:${episode}`;
      else if (onscreen) key = `onscreen:${String(onscreen).toLowerCase()}`;
      else if (pr.sub_title) key = `sub:${(pr.sub_title || '').toLowerCase()}`;
      else if (pr.id != null) key = `id:${pr.id}`;
      else
        key = `slot:${r.channel}|${r.start_time}|${r.end_time}|${pr.title || ''}`;
      if (seen.has(key)) continue;
      seen.add(key);
      deduped.push(r);
    }
    return deduped.sort(
      (a, b) => toUserTime(a.start_time) - toUserTime(b.start_time)
    );
  }, [
    allRecordings,
    isSeriesGroup,
    program.tvg_id,
    program.title,
    toUserTime,
    userNow,
  ]);

  if (!recording) return null;

  const EpisodeRow = ({ rec }) => {
    const cp = rec.custom_properties || {};
    const pr = cp.program || {};
    const start = toUserTime(rec.start_time);
    const end = toUserTime(rec.end_time);
    const season = cp.season ?? pr?.custom_properties?.season;
    const episode = cp.episode ?? pr?.custom_properties?.episode;
    const onscreen =
      cp.onscreen_episode ?? pr?.custom_properties?.onscreen_episode;
    const se =
      season && episode
        ? `S${String(season).padStart(2, '0')}E${String(episode).padStart(2, '0')}`
        : onscreen || null;
    const posterLogoId = cp.poster_logo_id;
    let purl = posterLogoId
      ? `/api/channels/logos/${posterLogoId}/cache/`
      : cp.poster_url || posterUrl || '/logo.png';
    if (
      typeof import.meta !== 'undefined' &&
      import.meta.env &&
      import.meta.env.DEV &&
      purl &&
      purl.startsWith('/')
    ) {
      purl = `${window.location.protocol}//${window.location.hostname}:5656${purl}`;
    }
    const onRemove = async (e) => {
      e?.stopPropagation?.();
      try {
        await API.deleteRecording(rec.id);
      } catch (error) {
        console.error('Failed to delete upcoming recording', error);
      }
      try {
        await useChannelsStore.getState().fetchRecordings();
      } catch (error) {
        console.error('Failed to refresh recordings after delete', error);
      }
    };
    return (
      <Card
        withBorder
        radius="md"
        padding="sm"
        style={{ backgroundColor: '#27272A', cursor: 'pointer' }}
        onClick={() => {
          setChildRec(rec);
          setChildOpen(true);
        }}
      >
        <Flex gap="sm" align="center">
          <Image
            src={purl}
            w={64}
            h={64}
            fit="contain"
            radius="sm"
            alt={pr.title || recordingName}
            fallbackSrc="/logo.png"
          />
          <Stack gap={4} style={{ flex: 1 }}>
            <Group justify="space-between">
              <Text
                fw={600}
                size="sm"
                lineClamp={1}
                title={pr.sub_title || pr.title}
              >
                {pr.sub_title || pr.title}
              </Text>
              {se && (
                <Badge color="gray" variant="light">
                  {se}
                </Badge>
              )}
            </Group>
            <Text size="xs">
              {start.format(`${dateformat}, YYYY ${timeformat}`)} – {end.format(timeformat)}
            </Text>
          </Stack>
          <Group gap={6}>
            <Button size="xs" color="red" variant="light" onClick={onRemove}>
              Remove
            </Button>
          </Group>
        </Flex>
      </Card>
    );
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        isSeriesGroup
          ? `Series: ${recordingName}`
          : `${recordingName}${program.sub_title ? ` - ${program.sub_title}` : ''}`
      }
      size="lg"
      centered
      radius="md"
      zIndex={9999}
      overlayProps={{ color: '#000', backgroundOpacity: 0.55, blur: 0 }}
      styles={{
        content: { backgroundColor: '#18181B', color: 'white' },
        header: { backgroundColor: '#18181B', color: 'white' },
        title: { color: 'white' },
      }}
    >
      {isSeriesGroup ? (
        <Stack gap={10}>
          {upcomingEpisodes.length === 0 && (
            <Text size="sm" c="dimmed">
              No upcoming episodes found
            </Text>
          )}
          {upcomingEpisodes.map((ep) => (
            <EpisodeRow key={`ep-${ep.id}`} rec={ep} />
          ))}
          {childOpen && childRec && (
            <RecordingDetailsModal
              opened={childOpen}
              onClose={() => setChildOpen(false)}
              recording={childRec}
              channel={channelMap[childRec.channel]}
              posterUrl={
                (childRec.custom_properties?.poster_logo_id
                  ? `/api/channels/logos/${childRec.custom_properties.poster_logo_id}/cache/`
                  : childRec.custom_properties?.poster_url ||
                  channelMap[childRec.channel]?.logo?.cache_url) ||
                '/logo.png'
              }
              env_mode={env_mode}
              onWatchLive={() => {
                const rec = childRec;
                const now = userNow();
                const s = toUserTime(rec.start_time);
                const e = toUserTime(rec.end_time);
                if (now.isAfter(s) && now.isBefore(e)) {
                  const ch = channelMap[rec.channel];
                  if (!ch) return;
                  let url = `/proxy/ts/stream/${ch.uuid}`;
                  if (env_mode === 'dev') {
                    url = `${window.location.protocol}//${window.location.hostname}:5656${url}`;
                  }
                  useVideoStore.getState().showVideo(url, 'live');
                }
              }}
              onWatchRecording={() => {
                let fileUrl =
                  childRec.custom_properties?.file_url ||
                  childRec.custom_properties?.output_file_url;
                if (!fileUrl) return;
                if (env_mode === 'dev' && fileUrl.startsWith('/')) {
                  fileUrl = `${window.location.protocol}//${window.location.hostname}:5656${fileUrl}`;
                }
                useVideoStore.getState().showVideo(fileUrl, 'vod', {
                  name:
                    childRec.custom_properties?.program?.title || 'Recording',
                  logo: {
                    url:
                      (childRec.custom_properties?.poster_logo_id
                        ? `/api/channels/logos/${childRec.custom_properties.poster_logo_id}/cache/`
                        : channelMap[childRec.channel]?.logo?.cache_url) ||
                      '/logo.png',
                  },
                });
              }}
            />
          )}
        </Stack>
      ) : (
        <Flex gap="lg" align="flex-start">
          <Image
            src={resolvedPosterUrl}
            w={180}
            h={240}
            fit="contain"
            radius="sm"
            alt={recordingName}
            fallbackSrc="/logo.png"
          />
          <Stack gap={8} style={{ flex: 1 }}>
            <Group justify="space-between" align="center">
              <Text c="dimmed" size="sm">
                {channel ? `${channel.channel_number} • ${channel.name}` : '—'}
              </Text>
              <Group gap={8}>
                {onWatchLive && (
                  <Button
                    size="xs"
                    variant="light"
                    onClick={(e) => {
                      e.stopPropagation?.();
                      onWatchLive();
                    }}
                  >
                    Watch Live
                  </Button>
                )}
                {onWatchRecording && (
                  <Button
                    size="xs"
                    variant="default"
                    onClick={(e) => {
                      e.stopPropagation?.();
                      onWatchRecording();
                    }}
                    disabled={!canWatchRecording}
                  >
                    Watch
                  </Button>
                )}
                {onEdit && start.isAfter(userNow()) && (
                  <Button
                    size="xs"
                    variant="light"
                    color="blue"
                    onClick={(e) => {
                      e.stopPropagation?.();
                      onEdit(recording);
                    }}
                  >
                    Edit
                  </Button>
                )}
                {customProps.status === 'completed' &&
                  (!customProps?.comskip ||
                    customProps?.comskip?.status !== 'completed') && (
                    <Button
                      size="xs"
                      variant="light"
                      color="teal"
                      onClick={async (e) => {
                        e.stopPropagation?.();
                        try {
                          await API.runComskip(recording.id);
                          notifications.show({
                            title: 'Removing commercials',
                            message: 'Queued comskip for this recording',
                            color: 'blue.5',
                            autoClose: 2000,
                          });
                        } catch (error) {
                          console.error('Failed to run comskip', error);
                        }
                      }}
                    >
                      Remove commercials
                    </Button>
                  )}
              </Group>
            </Group>
            <Text size="sm">
              {start.format(`${dateformat}, YYYY ${timeformat}`)} – {end.format(timeformat)}
            </Text>
            {rating && (
              <Group gap={8}>
                <Badge color="yellow" title={ratingSystem}>
                  {rating}
                </Badge>
              </Group>
            )}
            {description && (
              <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
                {description}
              </Text>
            )}
            {statRows.length > 0 && (
              <Stack gap={4} pt={6}>
                <Text fw={600} size="sm">
                  Stream Stats
                </Text>
                {statRows.map(([k, v]) => (
                  <Group key={k} justify="space-between">
                    <Text size="xs" c="dimmed">
                      {k}
                    </Text>
                    <Text size="xs">{v}</Text>
                  </Group>
                ))}
              </Stack>
            )}
          </Stack>
        </Flex>
      )}
    </Modal>
  );
};