import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import useAuthStore from '../../store/auth';
import {
  Box,
  TextField,
  Button,
  Typography,
  Grid2,
  Paper,
} from '@mui/material';

const LoginForm = () => {
  const { login, isAuthenticated, initData } = useAuthStore(); // Get login function from AuthContext
  const navigate = useNavigate(); // Hook to navigate to other routes
  const [formData, setFormData] = useState({ username: '', password: '' });

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/channels');
    }
  }, [isAuthenticated, navigate]);

  const handleInputChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    await login(formData);
    initData();
    navigate('/channels'); // Or any other route you'd like
  };

  // // Handle form submission
  // const handleSubmit = async (e) => {
  //   e.preventDefault();
  //   setLoading(true);
  //   setError(''); // Reset error on each new submission

  //   await login(username, password)
  //   navigate('/channels'); // Or any other route you'd like
  // };

  return (
    <Box
      sx={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        height: '100vh',
        backgroundColor: '#f5f5f5',
      }}
    >
      <Paper elevation={3} sx={{ padding: 3, width: '100%', maxWidth: 400 }}>
        <Typography variant="h5" align="center" gutterBottom>
          Login
        </Typography>
        <form onSubmit={handleSubmit}>
          <Grid2
            container
            spacing={2}
            justifyContent="center"
            direction="column"
          >
            <Grid2 xs={12}>
              <TextField
                label="Username"
                variant="standard"
                fullWidth
                name="username"
                value={formData.username}
                onChange={handleInputChange}
                required
                size="small"
              />
            </Grid2>
            <Grid2 xs={12}>
              <TextField
                label="Password"
                variant="standard"
                type="password"
                fullWidth
                name="password"
                value={formData.password}
                onChange={handleInputChange}
                required
                size="small"
              />
            </Grid2>
            <Grid2 xs={12}>
              <Button
                type="submit"
                variant="contained"
                color="primary"
                fullWidth
              >
                Submit
              </Button>
            </Grid2>
          </Grid2>
        </form>
      </Paper>
    </Box>
  );
};

export default LoginForm;
