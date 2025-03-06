// Modal.js
import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Stack,
  TextField,
  Button,
  Select,
  MenuItem,
  InputLabel,
  FormControl,
  CircularProgress,
  FormControlLabel,
  Checkbox,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
} from '@mui/material';
import { useFormik } from 'formik';
import * as Yup from 'yup';
import API from '../../api';
import useUserAgentsStore from '../../store/userAgents';
import M3UProfiles from './M3UProfiles';

const M3U = ({ playlist = null, isOpen, onClose }) => {
  const userAgents = useUserAgentsStore((state) => state.userAgents);
  const [file, setFile] = useState(null);
  const [profileModalOpen, setProfileModalOpen] = useState(false);

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      setFile(file);
    }
  };

  const formik = useFormik({
    initialValues: {
      name: '',
      server_url: '',
      max_streams: 0,
      user_agent: '',
      is_active: true,
    },
    validationSchema: Yup.object({
      name: Yup.string().required('Name is required'),
      user_agent: Yup.string().required('User-Agent is required'),
    }),
    onSubmit: async (values, { setSubmitting, resetForm }) => {
      if (playlist?.id) {
        await API.updatePlaylist({
          id: playlist.id,
          ...values,
          uploaded_file: file,
        });
      } else {
        await API.addPlaylist({
          ...values,
          uploaded_file: file,
        });
      }

      resetForm();
      setFile(null);
      setSubmitting(false);
      onClose();
    },
  });

  useEffect(() => {
    if (playlist) {
      formik.setValues({
        name: playlist.name,
        server_url: playlist.server_url,
        max_streams: playlist.max_streams,
        user_agent: playlist.user_agent,
        is_active: playlist.is_active,
      });
    } else {
      formik.resetForm();
    }
  }, [playlist]);

  if (!isOpen) {
    return <></>;
  }

  return (
    <Dialog open={isOpen} onClose={onClose}>
      <DialogTitle
        sx={{
          backgroundColor: 'primary.main',
          color: 'primary.contrastText',
        }}
      >
        M3U Account
      </DialogTitle>

      <form onSubmit={formik.handleSubmit}>
        <DialogContent>
          <TextField
            fullWidth
            id="name"
            name="name"
            label="Name"
            value={formik.values.name}
            onChange={formik.handleChange}
            onBlur={formik.handleBlur}
            error={formik.touched.name && Boolean(formik.errors.name)}
            helperText={formik.touched.name && formik.errors.name}
            variant="standard"
          />

          <TextField
            fullWidth
            id="server_url"
            name="server_url"
            label="URL"
            value={formik.values.server_url}
            onChange={formik.handleChange}
            onBlur={formik.handleBlur}
            error={
              formik.touched.server_url && Boolean(formik.errors.server_url)
            }
            helperText={formik.touched.server_url && formik.errors.server_url}
            variant="standard"
          />

          <Box mb={2}>
            <Stack
              direction="row"
              spacing={2}
              sx={{
                alignItems: 'center',
                pt: 2,
              }}
            >
              <Typography>File</Typography>

              <input
                type="file"
                id="uploaded_file"
                name="uploaded_file"
                accept="image/*"
                onChange={(event) => handleFileChange(event)}
                style={{ display: 'none' }}
              />
              <label htmlFor="uploaded_file">
                <Button variant="contained" component="span">
                  Browse...
                </Button>
              </label>
            </Stack>
          </Box>

          <TextField
            fullWidth
            id="max_streams"
            name="max_streams"
            label="Max Streams"
            value={formik.values.max_streams}
            onChange={formik.handleChange}
            onBlur={formik.handleBlur}
            error={
              formik.touched.max_streams && Boolean(formik.errors.max_streams)
            }
            helperText={formik.touched.max_streams && formik.errors.max_streams}
            variant="standard"
          />

          <FormControl variant="standard" fullWidth>
            <InputLabel id="user-agent-label">User-Agent</InputLabel>
            <Select
              labelId="user-agent-label"
              id="user_agent"
              name="user_agent"
              label="User-Agent"
              value={formik.values.user_agent}
              onChange={formik.handleChange}
              onBlur={formik.handleBlur}
              error={
                formik.touched.user_agent && Boolean(formik.errors.user_agent)
              }
              // helperText={formik.touched.user_agent && formik.errors.user_agent}
              variant="standard"
            >
              {userAgents.map((option, index) => (
                <MenuItem key={index} value={option.id}>
                  {option.user_agent_name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <FormControlLabel
            control={
              <Checkbox
                name="is_active"
                checked={formik.values.is_active}
                onChange={(e) =>
                  formik.setFieldValue('is_active', e.target.checked)
                }
              />
            }
            label="Is Active"
          />
        </DialogContent>

        <DialogActions>
          <Button
            variant="contained"
            color="primary"
            size="small"
            onClick={() => setProfileModalOpen(true)}
          >
            Profiles
          </Button>

          <Button
            type="submit"
            variant="contained"
            color="primary"
            disabled={formik.isSubmitting}
            size="small"
          >
            {formik.isSubmitting ? <CircularProgress size={24} /> : 'Submit'}
          </Button>
        </DialogActions>

        {playlist && (
          <M3UProfiles
            playlist={playlist}
            isOpen={profileModalOpen}
            onClose={() => setProfileModalOpen(false)}
          />
        )}
      </form>
    </Dialog>
  );
};

export default M3U;
