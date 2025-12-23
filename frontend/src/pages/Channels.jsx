import React from 'react';
import ChannelsTable from '../components/tables/ChannelsTable';
import StreamsTable from '../components/tables/StreamsTable';
import { Box, } from '@mantine/core';
import { Allotment } from 'allotment';
import { USER_LEVELS } from '../constants';
import useAuthStore from '../store/auth';
import useLocalStorage from '../hooks/useLocalStorage';
import ErrorBoundary from '../components/ErrorBoundary';

const PageContent = () => {
  const authUser = useAuthStore((s) => s.user);

  const [allotmentSizes, setAllotmentSizes] = useLocalStorage(
    'channels-splitter-sizes',
    [50, 50]
  );

  const handleSplitChange = (sizes) => {
    setAllotmentSizes(sizes);
  };

  const handleResize = (sizes) => {
    setAllotmentSizes(sizes);
  };

  if (!authUser.id) return <></>;

  if (authUser.user_level <= USER_LEVELS.STANDARD) {
    return (
      <Box style={{ padding: 10 }}>
        <ChannelsTable />
      </Box>
    );
  }

  return (
    <Box h={'100vh'} w={'100%'} display={'flex'}
         style={{ overflowX: 'auto' }}
    >
      <Allotment
        defaultSizes={allotmentSizes}
        h={'100%'} w={'100%'} miw={'600px'}
        className="custom-allotment"
        minSize={100}
        onChange={handleSplitChange}
        onResize={handleResize}
      >
        <Box p={10} miw={'100px'} style={{ overflowX: 'auto' }}>
          <Box miw={'600px'}>
            <ChannelsTable />
          </Box>
        </Box>
        <Box p={10} miw={'100px'} style={{ overflowX: 'auto' }}>
          <Box miw={'600px'}>
            <StreamsTable />
          </Box>
        </Box>
      </Allotment>
    </Box>
  );
};

const ChannelsPage = () => {
  return (
    <ErrorBoundary>
      <PageContent/>
    </ErrorBoundary>
  );
};

export default ChannelsPage;
