import { useEffect, useMemo, useRef, useState } from 'react';
import {
  MaterialReactTable,
  MRT_ShowHideColumnsButton,
  MRT_ToggleFullScreenButton,
  useMaterialReactTable,
} from 'material-react-table';
import {
  Box,
  Grid2,
  Stack,
  Typography,
  IconButton,
  Tooltip,
  Checkbox,
  Select,
  MenuItem,
  Snackbar,
} from '@mui/material';
import API from '../../api';
import {
  Delete as DeleteIcon,
  Edit as EditIcon,
  Add as AddIcon,
  SwapVert as SwapVertIcon,
  Check as CheckIcon,
  Close as CloseIcon,
  Refresh as RefreshIcon,
} from '@mui/icons-material';
import useEPGsStore from '../../store/epgs';
import EPGForm from '../forms/EPG';
import { TableHelper } from '../../helpers';

const EPGsTable = () => {
  const [epg, setEPG] = useState(null);
  const [epgModalOpen, setEPGModalOpen] = useState(false);
  const [rowSelection, setRowSelection] = useState([]);
  const [snackbarMessage, setSnackbarMessage] = useState('');
  const [snackbarOpen, setSnackbarOpen] = useState(false);

  const epgs = useEPGsStore((state) => state.epgs);

  const columns = useMemo(
    //column definitions...
    () => [
      {
        header: 'Name',
        accessorKey: 'name',
      },
      {
        header: 'Source Type',
        accessorKey: 'source_type',
      },
      {
        header: 'URL / API Key',
        accessorKey: 'max_streams',
      },
    ],
    []
  );

  //optionally access the underlying virtualizer instance
  const rowVirtualizerInstanceRef = useRef(null);

  const [isLoading, setIsLoading] = useState(true);
  const [sorting, setSorting] = useState([]);

  const closeSnackbar = () => {
    setSnackbarOpen(false);
  };

  const editEPG = async (epg = null) => {
    setEPG(epg);
    setEPGModalOpen(true);
  };

  const deleteEPG = async (id) => {
    setIsLoading(true);
    await API.deleteEPG(id);
    setIsLoading(false);
  };

  const refreshEPG = async (id) => {
    await API.refreshEPG(id);
    setSnackbarMessage('EPG refresh initiated');
    setSnackbarOpen(true);
  };

  const closeEPGForm = () => {
    setEPG(null);
    setEPGModalOpen(false);
  };

  useEffect(() => {
    if (typeof window !== 'undefined') {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    //scroll to the top of the table when the sorting changes
    try {
      rowVirtualizerInstanceRef.current?.scrollToIndex?.(0);
    } catch (error) {
      console.error(error);
    }
  }, [sorting]);

  const table = useMaterialReactTable({
    ...TableHelper.defaultProperties,
    columns,
    data: epgs,
    enablePagination: false,
    enableRowVirtualization: true,
    enableRowSelection: true,
    onRowSelectionChange: setRowSelection,
    onSortingChange: setSorting,
    state: {
      isLoading,
      sorting,
      rowSelection,
    },
    rowVirtualizerInstanceRef, //optional
    rowVirtualizerOptions: { overscan: 5 }, //optionally customize the row virtualizer
    initialState: {
      density: 'compact',
    },
    enableRowActions: true,
    renderRowActions: ({ row }) => (
      <>
        <IconButton
          size="small" // Makes the button smaller
          color="info" // Red color for delete actions
          onClick={() => editEPG(row.original)}
          sx={{ pt: 0, pb: 0 }}
        >
          <EditIcon fontSize="small" /> {/* Small icon size */}
        </IconButton>
        <IconButton
          size="small" // Makes the button smaller
          color="error" // Red color for delete actions
          onClick={() => deleteEPG(row.original.id)}
          sx={{ pt: 0, pb: 0 }}
        >
          <DeleteIcon fontSize="small" /> {/* Small icon size */}
        </IconButton>
        <IconButton
          size="small" // Makes the button smaller
          color="info" // Red color for delete actions
          onClick={() => refreshEPG(row.original.id)}
          sx={{ pt: 0, pb: 0 }}
        >
          <RefreshIcon fontSize="small" /> {/* Small icon size */}
        </IconButton>
      </>
    ),
    muiTableContainerProps: {
      sx: {
        height: 'calc(43vh - 0px)',
      },
    },
    renderTopToolbarCustomActions: ({ table }) => (
      <Stack
        direction="row"
        sx={{
          alignItems: 'center',
        }}
      >
        <Typography>EPGs</Typography>
        <Tooltip title="Add New EPG">
          <IconButton
            size="small" // Makes the button smaller
            color="success" // Red color for delete actions
            variant="contained"
            onClick={() => editEPG()}
          >
            <AddIcon fontSize="small" /> {/* Small icon size */}
          </IconButton>
        </Tooltip>
      </Stack>
    ),
  });

  return (
    <Box
      sx={{
        padding: 1,
      }}
    >
      <MaterialReactTable table={table} />

      <EPGForm epg={epg} isOpen={epgModalOpen} onClose={closeEPGForm} />

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

export default EPGsTable;
