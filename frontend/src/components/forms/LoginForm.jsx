import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import useAuthStore from '../../store/auth';
import API from '../../api';
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
  Modal,
  Anchor,
  Code,
  Checkbox,
} from '@mantine/core';
import logo from '../../assets/logo.png';

const LoginForm = () => {
  const login = useAuthStore((s) => s.login);
  const logout = useAuthStore((s) => s.logout);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const initData = useAuthStore((s) => s.initData);

  const navigate = useNavigate(); // Hook to navigate to other routes
  const [formData, setFormData] = useState({ username: '', password: '' });
  const [rememberMe, setRememberMe] = useState(false);
  const [forgotPasswordOpened, setForgotPasswordOpened] = useState(false);
  const [version, setVersion] = useState(null);

  useEffect(() => {
    // Fetch version info
    API.getVersion().then((data) => {
      setVersion(data?.version);
    });
  }, []);

  useEffect(() => {
    // Load saved username if it exists
    const savedUsername = localStorage.getItem(
      'dispatcharr_remembered_username'
    );
    if (savedUsername) {
      setFormData((prev) => ({ ...prev, username: savedUsername }));
      setRememberMe(true);
    }
  }, []);

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

      // Save username if remember me is checked
      if (rememberMe) {
        localStorage.setItem(
          'dispatcharr_remembered_username',
          formData.username
        );
      } else {
        localStorage.removeItem('dispatcharr_remembered_username');
      }

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
        style={{
          paddingTop: 30,
          paddingLeft: 30,
          paddingRight: 30,
          paddingBottom: 8,
          width: '100%',
          maxWidth: 500,
        }}
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

            <Group justify="space-between" align="center">
              <Checkbox
                label="Remember me"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.currentTarget.checked)}
                size="sm"
              />
              <Anchor
                size="sm"
                component="button"
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  setForgotPasswordOpened(true);
                }}
              >
                Forgot password?
              </Anchor>
            </Group>

            <Button type="submit" mt="sm" fullWidth>
              Login
            </Button>
          </Stack>
        </form>

        {version && (
          <Text
            size="xs"
            color="dimmed"
            align="right"
            style={{
              marginTop: '4px',
            }}
          >
            v{version}
          </Text>
        )}
      </Paper>

      <Modal
        opened={forgotPasswordOpened}
        onClose={() => setForgotPasswordOpened(false)}
        title="Reset Your Password"
        centered
      >
        <Stack spacing="md">
          <Text>
            To reset your password, your administrator needs to run a Django
            management command:
          </Text>
          <div>
            <Text weight={500} size="sm" mb={8}>
              If running with Docker:
            </Text>
            <Code block>
              docker exec &lt;container_name&gt; python manage.py changepassword
              &lt;username&gt;
            </Code>
          </div>
          <div>
            <Text weight={500} size="sm" mb={8}>
              If running locally:
            </Text>
            <Code block>python manage.py changepassword &lt;username&gt;</Code>
          </div>
          <Text size="sm" color="dimmed">
            The command will prompt for a new password. Replace
            <code>&lt;container_name&gt;</code> with your Docker container name
            and <code>&lt;username&gt;</code> with the account username.
          </Text>
          <Text size="sm" color="dimmed" italic>
            Please contact your system administrator to perform a password
            reset.
          </Text>
        </Stack>
      </Modal>
    </Center>
  );
};

export default LoginForm;
