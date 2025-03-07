// frontend/src/pages/Guide.js
import React, { useMemo, useState, useEffect, useRef } from 'react';
import {
  Box,
  Typography,
  Paper,
  Stack,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Slide,
  CircularProgress,
  Backdrop,
} from '@mui/material';
import dayjs from 'dayjs';
import API from '../api';
import useChannelsStore from '../store/channels';
import logo from '../images/logo.png';
import useVideoStore from '../store/useVideoStore'; // NEW import
import useAlertStore from '../store/alerts';
import useSettingsStore from '../store/settings';

/** Layout constants */
const CHANNEL_WIDTH = 120; // Width of the channel/logo column
const PROGRAM_HEIGHT = 90; // Height of each channel row
const HOUR_WIDTH = 300; // The width for a 1-hour block
const MINUTE_INCREMENT = 15; // For positioning programs every 15 min
const MINUTE_BLOCK_WIDTH = HOUR_WIDTH / (60 / MINUTE_INCREMENT);

// Modal size constants
const MODAL_WIDTH = 600;
const MODAL_HEIGHT = 400;

// Slide transition for Dialog
const Transition = React.forwardRef(function Transition(props, ref) {
  return <Slide direction="up" ref={ref} {...props} />;
});

export default function TVChannelGuide({ startDate, endDate }) {
  const { channels } = useChannelsStore();

  const [programs, setPrograms] = useState([]);
  const [guideChannels, setGuideChannels] = useState([]);
  const [now, setNow] = useState(dayjs());
  const [selectedProgram, setSelectedProgram] = useState(null);
  const [loading, setLoading] = useState(true);
  const { showAlert } = useAlertStore();
  const {
    environment: { env_mode },
  } = useSettingsStore();

  const guideRef = useRef(null);

  // Load program data once
  useEffect(() => {
    if (!channels || channels.length === 0) {
      console.warn('No channels provided or empty channels array');
      showAlert('No channels available', 'error');
      setLoading(false);
      return;
    }

    const fetchPrograms = async () => {
      console.log('Fetching program grid...');
      const fetched = await API.getGrid(); // GETs your EPG grid
      console.log(`Received ${fetched.length} programs`);

      // Unique tvg_ids from returned programs
      const programIds = [...new Set(fetched.map((p) => p.tvg_id))];

      // Filter your Redux/Zustand channels by matching tvg_id
      const filteredChannels = channels.filter((ch) =>
        programIds.includes(ch.tvg_id)
      );
      console.log(
        `found ${filteredChannels.length} channels with matching tvg_ids`
      );

      setGuideChannels(filteredChannels);
      setPrograms(fetched);
      setLoading(false);
    };

    fetchPrograms();
  }, [channels]);

  // Use start/end from props or default to "today at midnight" +24h
  const defaultStart = dayjs(startDate || dayjs().startOf('day'));
  const defaultEnd = endDate ? dayjs(endDate) : defaultStart.add(24, 'hour');

  // Expand timeline if needed based on actual earliest/ latest program
  const earliestProgramStart = useMemo(() => {
    if (!programs.length) return defaultStart;
    return programs.reduce((acc, p) => {
      const s = dayjs(p.start_time);
      return s.isBefore(acc) ? s : acc;
    }, defaultStart);
  }, [programs, defaultStart]);

  const latestProgramEnd = useMemo(() => {
    if (!programs.length) return defaultEnd;
    return programs.reduce((acc, p) => {
      const e = dayjs(p.end_time);
      return e.isAfter(acc) ? e : acc;
    }, defaultEnd);
  }, [programs, defaultEnd]);

  const start = earliestProgramStart.isBefore(defaultStart)
    ? earliestProgramStart
    : defaultStart;
  const end = latestProgramEnd.isAfter(defaultEnd)
    ? latestProgramEnd
    : defaultEnd;

  // Time increments in 15-min steps (for placing programs)
  const programTimeline = useMemo(() => {
    const times = [];
    let current = start;
    while (current.isBefore(end)) {
      times.push(current);
      current = current.add(MINUTE_INCREMENT, 'minute');
    }
    return times;
  }, [start, end]);

  // Hourly marks
  const hourTimeline = useMemo(() => {
    const hours = [];
    let current = start;
    while (current.isBefore(end)) {
      hours.push(current);
      current = current.add(1, 'hour');
    }
    return hours;
  }, [start, end]);

  // Scroll to "now" on load
  useEffect(() => {
    if (guideRef.current) {
      const nowOffset = dayjs().diff(start, 'minute');
      const scrollPosition =
        (nowOffset / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH -
        MINUTE_BLOCK_WIDTH;
      guideRef.current.scrollLeft = Math.max(scrollPosition, 0);
    }
  }, [programs, start]);

  // Update “now” every 60s
  useEffect(() => {
    const interval = setInterval(() => {
      setNow(dayjs());
    }, 60000);
    return () => clearInterval(interval);
  }, []);

  // Pixel offset for the “now” vertical line
  const nowPosition = useMemo(() => {
    if (now.isBefore(start) || now.isAfter(end)) return -1;
    const minutesSinceStart = now.diff(start, 'minute');
    return (minutesSinceStart / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH;
  }, [now, start, end]);

  // Helper: find channel by tvg_id
  function findChannelByTvgId(tvgId) {
    return guideChannels.find((ch) => ch.tvg_id === tvgId);
  }

  // The “Watch Now” click => show floating video
  const { showVideo } = useVideoStore.getState(); // or useVideoStore()
  function handleWatchStream(program) {
    const matched = findChannelByTvgId(program.tvg_id);
    if (!matched) {
      console.warn(`No channel found for tvg_id=${program.tvg_id}`);
      return;
    }
    // Build a playable stream URL for that channel
    let vidUrl = `/output/stream/${matched.channel_number}/`;
    if (env_mode == 'dev') {
      vidUrl = `${window.location.protocol}//${window.location.hostname}:5656${vidUrl}`;
    }

    showVideo(vidUrl);

    // Optionally close the modal
    setSelectedProgram(null);
  }

  // On program click, open the details modal
  function handleProgramClick(program, event) {
    // Optionally scroll that element into view or do something else
    event.currentTarget.scrollIntoView({
      behavior: 'smooth',
      inline: 'center',
    });
    setSelectedProgram(program);
  }

  // Close the modal
  function handleCloseModal() {
    setSelectedProgram(null);
  }

  // Renders each program block
  function renderProgram(program, channelStart) {
    const programKey = `${program.tvg_id}-${program.start_time}`;
    const programStart = dayjs(program.start_time);
    const programEnd = dayjs(program.end_time);
    const startOffsetMinutes = programStart.diff(channelStart, 'minute');
    const durationMinutes = programEnd.diff(programStart, 'minute');
    const leftPx = (startOffsetMinutes / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH;
    const widthPx = (durationMinutes / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH;

    // Highlight if currently live
    const isLive = now.isAfter(programStart) && now.isBefore(programEnd);

    return (
      <Box
        key={programKey}
        sx={{
          position: 'absolute',
          left: leftPx,
          top: 0,
          width: widthPx,
          cursor: 'pointer',
        }}
        onClick={(e) => handleProgramClick(program, e)}
      >
        <Paper
          elevation={2}
          sx={{
            position: 'relative',
            left: 2,
            width: widthPx - 4,
            top: 2,
            height: PROGRAM_HEIGHT - 4,
            p: 1,
            overflow: 'hidden',
            whiteSpace: 'nowrap',
            textOverflow: 'ellipsis',
            borderRadius: '8px',
            background: isLive
              ? 'linear-gradient(to right, #1e3a8a, #2c5282)'
              : 'linear-gradient(to right, #2d3748, #2d3748)',
            color: '#fff',
            transition: 'background 0.3s ease',
            '&:hover': {
              background: isLive
                ? 'linear-gradient(to right, #1e3a8a, #2a4365)'
                : 'linear-gradient(to right, #2d3748, #1a202c)',
            },
          }}
        >
          <Typography variant="body2" noWrap sx={{ fontWeight: 'bold' }}>
            {program.title}
          </Typography>
          <Typography variant="overline" noWrap>
            {programStart.format('h:mma')} - {programEnd.format('h:mma')}
          </Typography>
        </Paper>
      </Box>
    );
  }

  if (loading) {
    return (
      <Backdrop
        sx={{
          // color: '#fff',
          zIndex: (theme) => theme.zIndex.drawer + 1,
          position: 'fixed', // Ensure it covers the entire page
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
        }}
        open={loading}
      >
        <CircularProgress color="inherit" />
      </Backdrop>
    );
  }

  return (
    <Box
      sx={{
        overflow: 'hidden',
        width: '100%',
        height: '100%',
        backgroundColor: '#1a202c',
        color: '#fff',
        fontFamily: 'Roboto, sans-serif',
      }}
    >
      {/* Sticky top bar */}
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          backgroundColor: '#2d3748',
          color: '#fff',
          p: 2,
          position: 'sticky',
          top: 0,
          zIndex: 999,
        }}
      >
        <Typography variant="h6" sx={{ fontWeight: 'bold' }}>
          TV Guide
        </Typography>
        <Typography variant="body2">
          {now.format('dddd, MMMM D, YYYY • h:mm A')}
        </Typography>
      </Box>

      {/* Main layout */}
      <Stack direction="row">
        {/* Channel Logos Column */}
        <Box sx={{ backgroundColor: '#2d3748', color: '#fff' }}>
          <Box
            sx={{
              width: CHANNEL_WIDTH,
              height: '40px',
              borderBottom: '1px solid #4a5568',
            }}
          />
          {guideChannels.map((channel) => (
            <Box
              key={channel.channel_name}
              sx={{
                display: 'flex',
                height: PROGRAM_HEIGHT,
                alignItems: 'center',
                justifyContent: 'center',
                borderBottom: '1px solid #4a5568',
              }}
            >
              <Box
                sx={{
                  width: CHANNEL_WIDTH,
                  display: 'flex',
                  p: 1,
                  justifyContent: 'center',
                  maxWidth: CHANNEL_WIDTH * 0.8,
                  maxHeight: PROGRAM_HEIGHT * 0.8,
                }}
              >
                <img
                  src={channel.logo_url || logo}
                  alt={channel.channel_name}
                  style={{
                    width: '100%',
                    height: 'auto',
                    objectFit: 'contain',
                  }}
                />
              </Box>
            </Box>
          ))}
        </Box>

        {/* Timeline & Program Blocks */}
        <Box
          ref={guideRef}
          sx={{
            flex: 1,
            overflowX: 'auto',
            overflowY: 'auto',
          }}
        >
          {/* Sticky timeline header */}
          <Box
            sx={{
              display: 'flex',
              position: 'sticky',
              top: 0,
              zIndex: 10,
              backgroundColor: '#171923',
              borderBottom: '1px solid #4a5568',
            }}
          >
            <Box sx={{ flex: 1, display: 'flex' }}>
              {hourTimeline.map((time, hourIndex) => (
                <Box
                  key={time.format()}
                  sx={{
                    width: HOUR_WIDTH,
                    height: '40px',
                    position: 'relative',
                    color: '#a0aec0',
                    borderRight: '1px solid #4a5568',
                  }}
                >
                  <Typography
                    variant="body2"
                    sx={{
                      position: 'absolute',
                      top: '50%',
                      left: hourIndex === 0 ? 4 : 'calc(50% - 16px)',
                      transform: 'translateY(-50%)',
                    }}
                  >
                    {time.format('h:mma')}
                  </Typography>
                  <Box
                    sx={{
                      position: 'absolute',
                      bottom: 0,
                      top: 0,
                      width: '100%',
                      display: 'grid',
                      gridTemplateColumns: 'repeat(4, 1fr)',
                      alignItems: 'end',
                    }}
                  >
                    {[0, 1, 2, 3].map((i) => (
                      <Box
                        key={i}
                        sx={{
                          width: '1px',
                          height: '10px',
                          backgroundColor: '#718096',
                          marginRight: i < 3 ? HOUR_WIDTH / 4 - 1 + 'px' : 0,
                        }}
                      />
                    ))}
                  </Box>
                </Box>
              ))}
            </Box>
          </Box>

          {/* Now line */}
          <Box sx={{ position: 'relative' }}>
            {nowPosition >= 0 && (
              <Box
                sx={{
                  position: 'absolute',
                  left: nowPosition,
                  top: 0,
                  bottom: 0,
                  width: '2px',
                  backgroundColor: '#38b2ac',
                  zIndex: 15,
                }}
              />
            )}

            {/* Channel rows */}
            {guideChannels.map((channel) => {
              const channelPrograms = programs.filter(
                (p) => p.tvg_id === channel.tvg_id
              );
              return (
                <Box
                  key={channel.channel_name}
                  sx={{
                    display: 'flex',
                    position: 'relative',
                    minHeight: PROGRAM_HEIGHT,
                    borderBottom: '1px solid #4a5568',
                  }}
                >
                  <Box sx={{ flex: 1, position: 'relative' }}>
                    {channelPrograms.map((prog) => renderProgram(prog, start))}
                  </Box>
                </Box>
              );
            })}
          </Box>
        </Box>
      </Stack>

      {/* Modal for program details */}
      <Dialog
        open={Boolean(selectedProgram)}
        onClose={handleCloseModal}
        TransitionComponent={Transition}
        keepMounted
        PaperProps={{
          sx: {
            width: MODAL_WIDTH,
            height: MODAL_HEIGHT,
            m: 'auto',
            backgroundColor: '#1a202c',
            border: '2px solid #718096',
          },
        }}
        sx={{
          '& .MuiDialog-container': {
            alignItems: 'center',
            justifyContent: 'center',
          },
        }}
      >
        {selectedProgram && (
          <>
            <DialogTitle sx={{ color: '#fff' }}>
              {selectedProgram.title}
            </DialogTitle>
            <DialogContent sx={{ color: '#a0aec0' }}>
              <Typography variant="caption" display="block">
                {dayjs(selectedProgram.start_time).format('h:mma')} -{' '}
                {dayjs(selectedProgram.end_time).format('h:mma')}
              </Typography>
              <Typography variant="body1" sx={{ mt: 2, color: '#fff' }}>
                {selectedProgram.description || 'No description available.'}
              </Typography>
            </DialogContent>
            <DialogActions>
              {/* Only show the Watch button if currently live */}
              {now.isAfter(dayjs(selectedProgram.start_time)) &&
                now.isBefore(dayjs(selectedProgram.end_time)) && (
                  <Button
                    onClick={() => handleWatchStream(selectedProgram)}
                    sx={{ color: '#38b2ac' }}
                  >
                    Watch Now
                  </Button>
                )}
              <Button onClick={handleCloseModal} sx={{ color: '#38b2ac' }}>
                Close
              </Button>
            </DialogActions>
          </>
        )}
      </Dialog>
    </Box>
  );
}
