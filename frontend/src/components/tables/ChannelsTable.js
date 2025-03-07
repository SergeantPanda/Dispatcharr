import { useEffect, useMemo, useRef, useState } from 'react';
import {
  MaterialReactTable,
  useMaterialReactTable,
} from 'material-react-table';
import {
  Box,
  Grid2,
  Stack,
  Typography,
  Tooltip,
  IconButton,
  Button,
  ButtonGroup,
  Snackbar,
  Popover,
  TextField,
  Autocomplete,
  InputAdornment,
} from '@mui/material';
import useChannelsStore from '../../store/channels';
import {
  Delete as DeleteIcon,
  Edit as EditIcon,
  Add as AddIcon,
  SwapVert as SwapVertIcon,
  LiveTv as LiveTvIcon,
  ContentCopy,
  Tv as TvIcon,
  Clear as ClearIcon,
} from '@mui/icons-material';
import API from '../../api';
import ChannelForm from '../forms/Channel';
import { TableHelper } from '../../helpers';
import utils from '../../utils';
import logo from '../../images/logo.png';
import useVideoStore from '../../store/useVideoStore';
import useSettingsStore from '../../store/settings';
import useStreamsStore from '../../store/streams';
import usePlaylistsStore from '../../store/playlists';

const ChannelStreams = ({ channel, isExpanded }) => {
  const [channelStreams, setChannelStreams] = useState([]);
  const channelStreamIds = useChannelsStore(
    (state) => state.channels[channel.id]?.stream_ids
  );
  const { playlists } = usePlaylistsStore();
  const { streams } = useStreamsStore();

  useEffect(
    () =>
      setChannelStreams(
        streams
          .filter((stream) => channelStreamIds.includes(stream.id))
          .sort(
            (a, b) =>
              channelStreamIds.indexOf(a.id) - channelStreamIds.indexOf(b.id)
          )
      ),
    [streams, channelStreamIds]
  );

  const removeStream = async (stream) => {
    let streamSet = new Set(channelStreams);
    streamSet.delete(stream);
    streamSet = Array.from(streamSet);
    await API.updateChannel({
      ...channel,
      streams: streamSet.map((stream) => stream.id),
    });
  };

  const channelStreamsTable = useMaterialReactTable({
    ...TableHelper.defaultProperties,
    data: channelStreams,
    columns: useMemo(
      () => [
        {
          header: 'Name',
          accessorKey: 'name',
        },
        {
          header: 'M3U',
          accessorFn: (row) =>
            playlists.find((playlist) => playlist.id === row.m3u_account)?.name,
        },
      ],
      [playlists]
    ),
    enableKeyboardShortcuts: false,
    enableColumnFilters: false,
    enableSorting: false,
    enableBottomToolbar: false,
    enableTopToolbar: false,
    columnFilterDisplayMode: 'popover',
    enablePagination: false,
    enableRowVirtualization: true,
    enableColumnHeaders: false,
    rowVirtualizerOptions: { overscan: 5 }, //optionally customize the row virtualizer
    initialState: {
      density: 'compact',
    },
    enableRowActions: true,
    enableRowOrdering: true,
    muiRowDragHandleProps: ({ table }) => ({
      onDragEnd: async () => {
        const { draggingRow, hoveredRow } = table.getState();

        if (hoveredRow && draggingRow) {
          channelStreams.splice(
            hoveredRow.index,
            0,
            channelStreams.splice(draggingRow.index, 1)[0]
          );

          // setChannelStreams([...channelStreams]);
          API.updateChannel({
            ...channel,
            streams: channelStreams.map((stream) => stream.id),
          });
        }
      },
    }),
    renderRowActions: ({ row }) => (
      <>
        <IconButton
          size="small" // Makes the button smaller
          color="error" // Red color for delete actions
          onClick={() => removeStream(row.original)}
        >
          <DeleteIcon fontSize="small" /> {/* Small icon size */}
        </IconButton>
      </>
    ),
  });

  if (!isExpanded) {
    return <></>;
  }

  return (
    <Box
      sx={{
        backgroundColor: 'primary.main',
        pt: 1,
        pb: 1,
        width: '100%',
      }}
    >
      <MaterialReactTable table={channelStreamsTable} />
    </Box>
  );
};

const ChannelsTable = ({}) => {
  const [channel, setChannel] = useState(null);
  const [channelModalOpen, setChannelModalOpen] = useState(false);
  const [rowSelection, setRowSelection] = useState([]);
  const [channelGroupOptions, setChannelGroupOptions] = useState([]);

  const [anchorEl, setAnchorEl] = useState(null);
  const [textToCopy, setTextToCopy] = useState('');
  const [snackbarMessage, setSnackbarMessage] = useState('');
  const [snackbarOpen, setSnackbarOpen] = useState(false);

  const [filterValues, setFilterValues] = useState({});

  const { showVideo } = useVideoStore();
  const {
    channels,
    isLoading: channelsLoading,
    fetchChannels,
    setChannelsPageSelection,
  } = useChannelsStore();

  useEffect(() => {
    setChannelGroupOptions([
      ...new Set(
        Object.values(channels).map((channel) => channel.channel_group?.name)
      ),
    ]);
  }, [channels]);

  const handleFilterChange = (columnId, value) => {
    console.log(columnId);
    console.log(value);
    setFilterValues((prev) => ({
      ...prev,
      [columnId]: value ? value.toLowerCase() : '',
    }));
  };

  const outputUrlRef = useRef(null);

  const {
    environment: { env_mode },
  } = useSettingsStore();

  // Configure columns
  const columns = useMemo(
    () => [
      {
        header: '#',
        size: 50,
        accessorKey: 'channel_number',
      },
      {
        header: 'Name',
        accessorKey: 'channel_name',
        muiTableHeadCellProps: {
          sx: { textAlign: 'center' }, // Center-align the header
        },
        Header: ({ column }) => (
          <TextField
            variant="standard"
            label="Name"
            value={filterValues[column.id]}
            onChange={(e) => handleFilterChange(column.id, e.target.value)}
            size="small"
            margin="none"
            fullWidth
            sx={
              {
                // '& .MuiInputBase-root': { fontSize: '0.875rem' }, // Text size
                // '& .MuiInputLabel-root': { fontSize: '0.75rem' }, // Label size
                // width: '200px', // Optional: Adjust width
              }
            }
            slotProps={{
              input: {
                endAdornment: (
                  <InputAdornment position="end">
                    <IconButton
                      onClick={() => handleFilterChange(column.id, '')} // Clear text on click
                      edge="end"
                      size="small"
                    >
                      <ClearIcon sx={{ fontSize: '1rem' }} />
                    </IconButton>
                  </InputAdornment>
                ),
              },
            }}
          />
        ),
        meta: {
          filterVariant: null,
        },
      },
      {
        header: 'Group',
        accessorFn: (row) => row.channel_group?.name || '',
        Header: ({ column }) => (
          <Autocomplete
            disablePortal
            options={channelGroupOptions}
            size="small"
            sx={{ width: 300 }}
            clearOnEscape
            onChange={(event, newValue) =>
              handleFilterChange(column.id, newValue)
            }
            renderInput={(params) => (
              <TextField
                {...params}
                label="Group"
                size="small"
                variant="standard"
                onClick={(e) => e.stopPropagation()}
                sx={{
                  pb: 0.8,
                  //   '& .MuiInputBase-root': { fontSize: '0.875rem' }, // Text size
                  //   '& .MuiInputLabel-root': { fontSize: '0.75rem' }, // Label size
                  //   width: '200px', // Optional: Adjust width
                }}
              />
            )}
          />
        ),
      },
      {
        header: 'Logo',
        accessorKey: 'logo_url',
        enableSorting: false,
        size: 55,
        Cell: ({ cell }) => (
          <Grid2
            container
            direction="row"
            sx={{
              justifyContent: 'center',
              alignItems: 'center',
            }}
          >
            <img src={cell.getValue() || logo} width="20" alt="channel logo" />
          </Grid2>
        ),
        meta: {
          filterVariant: null,
        },
      },
    ],
    [channelGroupOptions]
  );

  // Access the row virtualizer instance (optional)
  const rowVirtualizerInstanceRef = useRef(null);

  const [isLoading, setIsLoading] = useState(true);
  const [sorting, setSorting] = useState([]);

  const closeSnackbar = () => setSnackbarOpen(false);

  const editChannel = async (ch = null) => {
    setChannel(ch);
    setChannelModalOpen(true);
  };

  const deleteChannel = async (id) => {
    await API.deleteChannel(id);
  };

  function handleWatchStream(channelNumber) {
    let vidUrl = `/output/stream/${channelNumber}/`;
    if (env_mode == 'dev') {
      vidUrl = `${window.location.protocol}//${window.location.hostname}:5656${vidUrl}`;
    }
    showVideo(vidUrl);
  }

  // (Optional) bulk delete, but your endpoint is @TODO
  const deleteChannels = async () => {
    setIsLoading(true);
    const selected = table
      .getRowModel()
      .rows.filter((row) => row.getIsSelected());
    await utils.Limiter(
      4,
      selected.map((chan) => () => deleteChannel(chan.original.id))
    );
    // If you have a real bulk-delete endpoint, call it here:
    // await API.deleteChannels(selected.map((sel) => sel.id));
    setIsLoading(false);
  };

  // ─────────────────────────────────────────────────────────
  // The "Assign Channels" button logic
  // ─────────────────────────────────────────────────────────
  const assignChannels = async () => {
    try {
      // Get row order from the table
      const rowOrder = table.getRowModel().rows.map((row) => row.original.id);

      // Call our custom API endpoint
      setIsLoading(true);
      const result = await API.assignChannelNumbers(rowOrder);
      setIsLoading(false);

      // We might get { message: "Channels have been auto-assigned!" }
      setSnackbarMessage(result.message || 'Channels assigned');
      setSnackbarOpen(true);

      // Refresh the channel list
      await fetchChannels();
    } catch (err) {
      console.error(err);
      setSnackbarMessage('Failed to assign channels');
      setSnackbarOpen(true);
    }
  };

  // ─────────────────────────────────────────────────────────
  // The new "Match EPG" button logic
  // ─────────────────────────────────────────────────────────
  const matchEpg = async () => {
    try {
      // Hit our new endpoint that triggers the fuzzy matching Celery task
      const resp = await fetch('/api/channels/channels/match-epg/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${await API.getAuthToken()}`,
        },
      });

      if (resp.ok) {
        setSnackbarMessage('EPG matching task started!');
      } else {
        const text = await resp.text();
        setSnackbarMessage(`Failed to start EPG matching: ${text}`);
      }
    } catch (err) {
      setSnackbarMessage(`Error: ${err.message}`);
    }
    setSnackbarOpen(true);
  };

  const closeChannelForm = () => {
    setChannel(null);
    setChannelModalOpen(false);
  };

  useEffect(() => {
    if (typeof window !== 'undefined') {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    // Scroll to the top of the table when sorting changes
    try {
      rowVirtualizerInstanceRef.current?.scrollToIndex?.(0);
    } catch (error) {
      console.error(error);
    }
  }, [sorting]);

  const closePopover = () => {
    setAnchorEl(null);
    setSnackbarMessage('');
  };
  const openPopover = Boolean(anchorEl);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(textToCopy);
      setSnackbarMessage('Copied!');
    } catch (err) {
      const inputElement = outputUrlRef.current.querySelector('input'); // Get the actual input

      if (inputElement) {
        inputElement.focus();
        inputElement.select();

        // For older browsers
        document.execCommand('copy');
        setSnackbarMessage('Copied!');
      }
    }
    setSnackbarOpen(true);
  };

  // Example copy URLs
  const copyM3UUrl = (event) => {
    setAnchorEl(event.currentTarget);
    setTextToCopy(
      `${window.location.protocol}//${window.location.host}/output/m3u`
    );
  };
  const copyEPGUrl = (event) => {
    setAnchorEl(event.currentTarget);
    setTextToCopy(
      `${window.location.protocol}//${window.location.host}/output/epg`
    );
  };
  const copyHDHRUrl = (event) => {
    setAnchorEl(event.currentTarget);
    setTextToCopy(
      `${window.location.protocol}//${window.location.host}/output/hdhr`
    );
  };

  const onRowSelectionChange = (e, test) => {
    console.log(e());
    console.log(test);
    setRowSelection(e);
  };

  useEffect(() => {
    const selectedRows = table
      .getSelectedRowModel()
      .rows.map((row) => row.original);
    setChannelsPageSelection(selectedRows);
  }, [rowSelection]);

  const filteredData = Object.values(channels).filter((row) =>
    columns.every(({ accessorKey }) =>
      filterValues[accessorKey]
        ? row[accessorKey]?.toLowerCase().includes(filterValues[accessorKey])
        : true
    )
  );

  const table = useMaterialReactTable({
    ...TableHelper.defaultProperties,
    columns,
    data: filteredData,
    enablePagination: false,
    enableColumnActions: false,
    enableRowVirtualization: true,
    enableRowSelection: true,
    onRowSelectionChange: onRowSelectionChange,
    onSortingChange: setSorting,
    state: {
      isLoading: isLoading || channelsLoading,
      sorting,
      rowSelection,
    },
    rowVirtualizerInstanceRef, // optional
    rowVirtualizerOptions: { overscan: 5 },
    initialState: {
      density: 'compact',
    },
    enableRowActions: true,
    enableExpandAll: false,
    displayColumnDefOptions: {
      'mrt-row-select': {
        size: 50, // Set custom width (default is ~40px)
      },
      'mrt-row-expand': {
        size: 10, // Set custom width (default is ~40px)
        header: '',
        muiTableHeadCellProps: {
          sx: { width: 38, minWidth: 38, maxWidth: 38, height: '100%' },
        },
        muiTableBodyCellProps: {
          sx: { width: 38, minWidth: 38, maxWidth: 38 },
        },
      },
      'mrt-row-actions': {
        size: 68, // Set custom width (default is ~40px)
      },
    },
    muiExpandButtonProps: ({ row, table }) => ({
      onClick: () => {
        setRowSelection({ [row.index]: true });
        table.setExpanded({ [row.id]: !row.getIsExpanded() }); //only 1 detail panel open at a time
      },
      sx: {
        transform: row.getIsExpanded() ? 'rotate(180deg)' : 'rotate(-90deg)',
        transition: 'transform 0.2s',
      },
    }),
    renderDetailPanel: ({ row }) => (
      <ChannelStreams channel={row.original} isExpanded={row.getIsExpanded()} />
    ),
    renderRowActions: ({ row }) => (
      <Box sx={{ justifyContent: 'right' }}>
        <Tooltip title="Edit Channel">
          <IconButton
            size="small"
            color="warning"
            onClick={() => {
              editChannel(row.original);
            }}
            sx={{ py: 0, px: 0.5 }}
          >
            <EditIcon fontSize="small" />
          </IconButton>
        </Tooltip>

        <Tooltip title="Delete Channel">
          <IconButton
            size="small"
            color="error"
            onClick={() => deleteChannel(row.original.id)}
            sx={{ py: 0, px: 0.5 }}
          >
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Tooltip>

        <Tooltip title="Preview Channel">
          <IconButton
            size="small"
            color="info"
            onClick={() => handleWatchStream(row.original.channel_number)}
            sx={{ py: 0, px: 0.5 }}
          >
            <LiveTvIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>
    ),
    muiTableContainerProps: {
      sx: {
        height: 'calc(100vh - 75px)',
        overflowY: 'auto',
      },
    },
    muiSearchTextFieldProps: {
      variant: 'standard',
    },
    renderTopToolbarCustomActions: ({ table }) => {
      const selectedRowCount = table.getSelectedRowModel().rows.length;

      return (
        <Stack direction="row" sx={{ alignItems: 'center' }}>
          <Typography>Channels</Typography>
          <Tooltip title="Add New Channel">
            <IconButton
              size="small"
              color="success"
              variant="contained"
              onClick={() => editChannel()}
            >
              <AddIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Delete Channels">
            <IconButton
              size="small"
              color="error"
              variant="contained"
              onClick={deleteChannels}
              disabled={selectedRowCount == 0}
            >
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Assign Channels">
            <IconButton
              size="small"
              color="warning"
              variant="contained"
              onClick={assignChannels}
              disabled={selectedRowCount == 0}
            >
              <SwapVertIcon fontSize="small" />
            </IconButton>
          </Tooltip>

          {/* Our brand-new button for EPG matching */}
          <Tooltip title="Auto-match EPG with fuzzy logic">
            <IconButton
              size="small"
              color="success"
              variant="contained"
              onClick={matchEpg}
            >
              <TvIcon fontSize="small" />
            </IconButton>
          </Tooltip>

          <ButtonGroup sx={{ marginLeft: 1 }}>
            <Button variant="contained" size="small" onClick={copyHDHRUrl}>
              HDHR URL
            </Button>
            <Button variant="contained" size="small" onClick={copyM3UUrl}>
              M3U URL
            </Button>
            <Button variant="contained" size="small" onClick={copyEPGUrl}>
              EPG
            </Button>
          </ButtonGroup>
        </Stack>
      );
    },
  });

  return (
    <Box>
      <MaterialReactTable table={table} />

      {/* Channel Form Modal */}
      <ChannelForm
        channel={channel}
        isOpen={channelModalOpen}
        onClose={closeChannelForm}
      />

      {/* Popover for the "copy" URLs */}
      <Popover
        open={openPopover}
        anchorEl={anchorEl}
        onClose={closePopover}
        anchorOrigin={{
          vertical: 'bottom',
          horizontal: 'left',
        }}
      >
        <div style={{ padding: 16, display: 'flex', alignItems: 'center' }}>
          <TextField
            id="output-url"
            value={textToCopy}
            variant="standard"
            // disabled
            size="small"
            sx={{ marginRight: 1 }}
            ref={outputUrlRef}
          />
          <IconButton onClick={handleCopy} color="primary">
            <ContentCopy />
          </IconButton>
        </div>
      </Popover>

      {/* Snackbar for feedback */}
      <Snackbar
        anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
        open={snackbarOpen}
        autoHideDuration={5000}
        onClose={closeSnackbar}
        message={snackbarMessage}
      />
    </Box>
  );
};

export default ChannelsTable;
