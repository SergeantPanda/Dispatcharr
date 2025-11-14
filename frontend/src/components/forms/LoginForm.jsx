import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import useAuthStore from '../../store/auth';
import {
  Paper,
  Title,
  TextInput,
  Button,
  Center,
  Stack,
  Text,
  Image,
  Group,
  Divider,
} from '@mantine/core';
import logo from '../../assets/logo.png';

const LoginForm = () => {
  const login = useAuthStore((s) => s.login);
  const logout = useAuthStore((s) => s.logout);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const initData = useAuthStore((s) => s.initData);

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

    try {
      await login(formData);
      await initData();
      // Navigation will happen automatically via the useEffect or route protection
    } catch (e) {
      console.log(`Failed to login: ${e}`);
      await logout();
    }
  };

  return (
    <Center
      style={{
        height: '100vh',
      }}
    >
      <Paper
        elevation={3}
        style={{ padding: 30, width: '100%', maxWidth: 500 }}
      >
        <Stack align="center" spacing="lg">
          <Image
            src={logo}
            alt="Dispatcharr Logo"
            width={120}
            height={120}
            fit="contain"
          />
          <Title order={2} align="center">
            Dispatcharr
          </Title>
          <Text size="sm" color="dimmed" align="center">
            Welcome back! Please log in to continue.
          </Text>
          <Divider style={{ width: '100%' }} />
        </Stack>
        <form onSubmit={handleSubmit}>
          <Stack>
            <TextInput
              label="Username"
              name="username"
              value={formData.username}
              onChange={handleInputChange}
              required
            />

            <TextInput
              label="Password"
              type="password"
              name="password"
              value={formData.password}
              onChange={handleInputChange}
              // required
            />

            <Button type="submit" mt="sm" fullWidth>
              Login
            </Button>
          </Stack>
        </form>
      </Paper>
    </Center>
  );
};

export default LoginForm;
