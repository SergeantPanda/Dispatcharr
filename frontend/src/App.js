// frontend/src/App.js
import React, { useEffect, useState } from 'react';
import axios from 'axios';
import {
  BrowserRouter as Router,
  Route,
  Routes,
  Navigate,
} from 'react-router-dom';
import Sidebar from './components/Sidebar';
import Login from './pages/Login';
import Channels from './pages/Channels';
import M3U from './pages/M3U';
import { ThemeProvider } from '@mui/material/styles';
import { Box, CssBaseline } from '@mui/material';
import theme from './theme';
import EPG from './pages/EPG';
import Guide from './pages/Guide';
import Settings from './pages/Settings';
import StreamProfiles from './pages/StreamProfiles';
import useAuthStore from './store/auth';
import Alert from './components/Alert';
import FloatingVideo from './components/FloatingVideo';
import SuperuserForm from './components/forms/SuperuserForm';
import { WebsocketProvider } from './WebSocket';

const drawerWidth = 240;
const miniDrawerWidth = 60;
const defaultRoute = '/channels';

const App = () => {
  const [open, setOpen] = useState(true);
  const [needsSuperuser, setNeedsSuperuser] = useState(false);
  const {
    isAuthenticated,
    setIsAuthenticated,
    logout,
    initData,
    initializeAuth,
  } = useAuthStore();

  const toggleDrawer = () => {
    setOpen(!open);
  };

  // Check if a superuser exists on first load.
  useEffect(() => {
    async function checkSuperuser() {
      try {
        const res = await axios.get('/api/accounts/initialize-superuser/');
        if (!res.data.superuser_exists) {
          setNeedsSuperuser(true);
        }
      } catch (error) {
        console.error('Error checking superuser status:', error);
      }
    }
    checkSuperuser();
  }, []);

  // Authentication check.
  useEffect(() => {
    const checkAuth = async () => {
      const loggedIn = await initializeAuth();
      if (loggedIn) {
        await initData();
        setIsAuthenticated(true);
      } else {
        await logout();
      }
    };
    checkAuth();
  }, [initializeAuth, initData, setIsAuthenticated, logout]);

  // If no superuser exists, show the initialization form.
  if (needsSuperuser) {
    return <SuperuserForm onSuccess={() => setNeedsSuperuser(false)} />;
  }

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <WebsocketProvider>
        <Router>
          <Sidebar
            open={open}
            miniDrawerWidth={miniDrawerWidth}
            drawerWidth={drawerWidth}
            toggleDrawer={toggleDrawer}
          />

          <Box
            sx={{
              display: 'flex',
              flexDirection: 'column',
              ml: `${open ? drawerWidth : miniDrawerWidth}px`,
              transition: 'width 0.3s, margin-left 0.3s',
              backgroundColor: '#495057',
              height: '100%',
            }}
          >
            <Box
              sx={{
                flex: 1,
                overflow: 'hidden',
                display: 'flex',
                flexDirection: 'column',
              }}
            >
              <Routes>
                {isAuthenticated ? (
                  <>
                    <Route path="/channels" element={<Channels />} />
                    <Route path="/m3u" element={<M3U />} />
                    <Route path="/epg" element={<EPG />} />
                    <Route
                      path="/stream-profiles"
                      element={<StreamProfiles />}
                    />
                    <Route path="/guide" element={<Guide />} />
                    <Route path="/settings" element={<Settings />} />
                  </>
                ) : (
                  <Route path="/login" element={<Login />} />
                )}
                <Route
                  path="*"
                  element={
                    <Navigate
                      to={isAuthenticated ? defaultRoute : '/login'}
                      replace
                    />
                  }
                />
              </Routes>
            </Box>
          </Box>
        </Router>
        <Alert />
        <FloatingVideo />
      </WebsocketProvider>
    </ThemeProvider>
  );
};

export default App;
