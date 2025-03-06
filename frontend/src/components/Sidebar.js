import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  ListItemIcon,
  Box,
  Divider,
  Drawer,
  TextField,
} from '@mui/material';
import {
  Tv as TvIcon,
  CalendarMonth as CalendarMonthIcon,
  VideoFile as VideoFileIcon,
  LiveTv as LiveTvIcon,
  PlaylistPlay as PlaylistPlayIcon,
  Settings as SettingsIcon,
  Logout as LogoutIcon,
} from '@mui/icons-material';
import logo from '../images/logo.png';
import useAuthStore from '../store/auth';
import useSettingsStore from '../store/settings';

const items = [
  { text: 'Channels', icon: <TvIcon />, route: '/channels' },
  { text: 'M3U', icon: <PlaylistPlayIcon />, route: '/m3u' },
  { text: 'EPG', icon: <CalendarMonthIcon />, route: '/epg' },
  {
    text: 'Stream Profiles',
    icon: <VideoFileIcon />,
    route: '/stream-profiles',
  },
  { text: 'TV Guide', icon: <LiveTvIcon />, route: '/guide' },
  { text: 'Settings', icon: <SettingsIcon />, route: '/settings' },
];

const Sidebar = ({ open, miniDrawerWidth, drawerWidth, toggleDrawer }) => {
  const location = useLocation();
  const { isAuthenticated } = useAuthStore();
  const {
    environment: { public_ip },
  } = useSettingsStore();

  return (
    <Drawer
      variant="permanent"
      open={open}
      sx={{
        width: open ? drawerWidth : miniDrawerWidth,
        flexShrink: 0,
        '& .MuiDrawer-paper': {
          width: open ? drawerWidth : miniDrawerWidth,
          transition: 'width 0.3s',
          overflowX: 'hidden',
          '& .MuiDrawer-paper': {
            display: 'flex',
            flexDirection: 'column',
            height: '100vh',
          },
        },
      }}
    >
      <Box sx={{ flexGrow: 1 }}>
        <List sx={{ backgroundColor: '#495057', color: 'white' }}>
          <ListItem disablePadding>
            <ListItemButton
              onClick={toggleDrawer}
              size="small"
              sx={{
                pt: 0,
                pb: 0,
              }}
            >
              <img src={logo} width="33x" alt="logo" />
              {open && (
                <ListItemText primary="Dispatcharr" sx={{ paddingLeft: 3 }} />
              )}
            </ListItemButton>
          </ListItem>
        </List>
        <Divider />

        <List>
          {items.map((item) => (
            <ListItem key={item.text} disablePadding>
              <ListItemButton
                component={Link}
                to={item.route}
                selected={location.pathname == item.route}
              >
                <ListItemIcon>{item.icon}</ListItemIcon>
                {open && <ListItemText primary={item.text} />}
              </ListItemButton>
            </ListItem>
          ))}
        </List>
      </Box>

      {isAuthenticated && (
        <Box sx={{ flexGrow: 1, borderTop: '1px solid #ccc' }}>
          <List>
            <ListItem disablePadding>
              <ListItemButton>
                <ListItemIcon>
                  <LogoutIcon />
                </ListItemIcon>
                <ListItemText primary="Logout" />
              </ListItemButton>
            </ListItem>
          </List>
          <TextField
            size="small"
            fullWidth
            label="Public IP"
            value={public_ip || ''}
            disabled
          />
        </Box>
      )}
    </Drawer>
  );
};

export default Sidebar;
