import React, {
  useState,
  useEffect,
  useRef,
  createContext,
  useContext,
} from 'react';
import useStreamsStore from './store/streams';
import useAlertStore from './store/alerts';

export const WebsocketContext = createContext(false, null, () => {});

export const WebsocketProvider = ({ children }) => {
  const [isReady, setIsReady] = useState(false);
  const [val, setVal] = useState(null);

  const { showAlert } = useAlertStore();

  const ws = useRef(null);

  useEffect(() => {
    let wsUrl = `ws://${window.location.host}/ws/`;
    if (process.env.REACT_APP_ENV_MODE == 'dev') {
      wsUrl = `ws://${window.location.hostname}:8001/ws/`;
    }

    const socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      console.log('websocket connected');
      setIsReady(true);
    };

    // Reconnection logic
    socket.onclose = () => {
      setIsReady(false);
      setTimeout(() => {
        const reconnectWs = new WebSocket(wsUrl);
        reconnectWs.onopen = () => setIsReady(true);
      }, 3000); // Attempt to reconnect every 3 seconds
    };

    socket.onmessage = async (event) => {
      event = JSON.parse(event.data);
      switch (event.type) {
        case 'm3u_refresh':
          if (event.message?.success) {
            useStreamsStore.getState().fetchStreams();
            showAlert(event.message.message, 'success');
          }
          break;

        default:
          console.error(`Unknown websocket event type: ${event.type}`);
          break;
      }
    };

    ws.current = socket;

    return () => {
      socket.close();
    };
  }, []);

  const ret = [isReady, val, ws.current?.send.bind(ws.current)];

  return (
    <WebsocketContext.Provider value={ret}>
      {children}
    </WebsocketContext.Provider>
  );
};

export const useWebSocket = () => {
  const socket = useContext(WebsocketContext);
  return socket;
};
