// frontend/src/components/forms/SuperuserForm.js
import React, { useState } from 'react';
import axios from 'axios';
import {
  Box,
  Paper,
  Typography,
  Grid2,
  TextField,
  Button,
} from '@mui/material';

function SuperuserForm({ onSuccess }) {
  const [formData, setFormData] = useState({
    username: '',
    password: '',
    email: '',
  });
  const [error, setError] = useState('');

  const handleChange = (e) => {
    setFormData((prev) => ({
      ...prev,
      [e.target.name]: e.target.value,
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const res = await axios.post('/api/accounts/initialize-superuser/', {
        username: formData.username,
        password: formData.password,
        email: formData.email,
      });
      if (res.data.superuser_exists) {
        onSuccess();
      }
    } catch (err) {
      let msg = 'Failed to create superuser.';
      if (err.response && err.response.data && err.response.data.error) {
        msg += ` ${err.response.data.error}`;
      }
      setError(msg);
    }
  };

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
          Create your Super User Account
        </Typography>
        {error && (
          <Typography variant="body2" color="error" sx={{ mb: 2 }}>
            {error}
          </Typography>
        )}
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
                onChange={handleChange}
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
                onChange={handleChange}
                required
                size="small"
              />
            </Grid2>
            <Grid2 xs={12}>
              <TextField
                label="Email (optional)"
                variant="standard"
                type="email"
                fullWidth
                name="email"
                value={formData.email}
                onChange={handleChange}
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
                Create Superuser
              </Button>
            </Grid2>
          </Grid2>
        </form>
      </Paper>
    </Box>
  );
}

export default SuperuserForm;
