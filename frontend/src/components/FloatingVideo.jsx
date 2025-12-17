// frontend/src/components/FloatingVideo.js
import React, { useCallback, useEffect, useRef, useState } from 'react';
import Draggable from 'react-draggable';
import useVideoStore from '../store/useVideoStore';
import mpegts from 'mpegts.js';
import { CloseButton, Flex, Loader, Text, Box } from '@mantine/core';

export default function FloatingVideo() {
  const isVisible = useVideoStore((s) => s.isVisible);
  const streamUrl = useVideoStore((s) => s.streamUrl);
  const contentType = useVideoStore((s) => s.contentType);
  const metadata = useVideoStore((s) => s.metadata);
  const hideVideo = useVideoStore((s) => s.hideVideo);
  const videoRef = useRef(null);
  const playerRef = useRef(null);
  const videoContainerRef = useRef(null);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [showOverlay, setShowOverlay] = useState(true);
  const [videoSize, setVideoSize] = useState({ width: 320, height: 180 });
  const [isResizing, setIsResizing] = useState(false);
  const resizeStateRef = useRef(null);
  const overlayTimeoutRef = useRef(null);
  const aspectRatioRef = useRef(320 / 180);
  const [dragPosition, setDragPosition] = useState(null);
  const dragPositionRef = useRef(null);
  const dragOffsetRef = useRef({ x: 0, y: 0 });
  const initialPositionRef = useRef(null);

  const MIN_WIDTH = 220;
  const MIN_HEIGHT = 124;
  const VISIBLE_MARGIN = 48; // keep part of the window visible when dragging

  // Safely destroy the mpegts player to prevent errors
  const safeDestroyPlayer = () => {
    try {
      if (playerRef.current) {
        setIsLoading(false);
        setLoadError(null);

        if (videoRef.current) {
          videoRef.current.removeAttribute('src');
          videoRef.current.load();
        }

        try {
          playerRef.current.pause();
        } catch (e) {
          // Ignore pause errors
        }

        try {
          playerRef.current.destroy();
        } catch (error) {
          if (
            error.name !== 'AbortError' &&
            !error.message?.includes('aborted')
          ) {
            console.log('Error during player destruction:', error.message);
          }
        } finally {
          playerRef.current = null;
        }
      }
    } catch (error) {
      console.log('Error during player cleanup:', error);
      playerRef.current = null;
    }

    // Clear overlay timer
    if (overlayTimeoutRef.current) {
      clearTimeout(overlayTimeoutRef.current);
      overlayTimeoutRef.current = null;
    }
  };

  // Start overlay auto-hide timer
  const startOverlayTimer = () => {
    if (overlayTimeoutRef.current) {
      clearTimeout(overlayTimeoutRef.current);
    }
    overlayTimeoutRef.current = setTimeout(() => {
      setShowOverlay(false);
    }, 4000); // Hide after 4 seconds
  };

  // Initialize VOD player (native HTML5 with enhanced controls)
  const initializeVODPlayer = () => {
    if (!videoRef.current || !streamUrl) return;

    setIsLoading(true);
    setLoadError(null);
    setShowOverlay(true); // Show overlay initially

    console.log('Initializing VOD player for:', streamUrl);

    const video = videoRef.current;

    // Enhanced video element configuration for VOD
    video.preload = 'metadata';
    video.crossOrigin = 'anonymous';

    // Set up event listeners
    const handleLoadStart = () => setIsLoading(true);
    const handleLoadedData = () => setIsLoading(false);
    const handleCanPlay = () => {
      setIsLoading(false);
      // Auto-play for VOD content
      video.play().catch((e) => {
        console.log('Auto-play prevented:', e);
        setLoadError('Auto-play was prevented. Click play to start.');
      });
      // Start overlay timer when video is ready
      startOverlayTimer();
    };
    const handleError = (e) => {
      setIsLoading(false);
      const error = e.target.error;
      let errorMessage = 'Video playback error';

      if (error) {
        switch (error.code) {
          case error.MEDIA_ERR_ABORTED:
            errorMessage = 'Video playback was aborted';
            break;
          case error.MEDIA_ERR_NETWORK:
            errorMessage = 'Network error while loading video';
            break;
          case error.MEDIA_ERR_DECODE:
            errorMessage = 'Video codec not supported by your browser';
            break;
          case error.MEDIA_ERR_SRC_NOT_SUPPORTED:
            errorMessage = 'Video format not supported by your browser';
            break;
          default:
            errorMessage = error.message || 'Unknown video error';
        }
      }

      setLoadError(errorMessage);
    };

    // Enhanced progress tracking for VOD
    const handleProgress = () => {
      if (video.buffered.length > 0) {
        const bufferedEnd = video.buffered.end(video.buffered.length - 1);
        const duration = video.duration;
        if (duration > 0) {
          const bufferedPercent = (bufferedEnd / duration) * 100;
          // You could emit this to a store for UI feedback
        }
      }
    };

    // Add event listeners
    video.addEventListener('loadstart', handleLoadStart);
    video.addEventListener('loadeddata', handleLoadedData);
    video.addEventListener('canplay', handleCanPlay);
    video.addEventListener('error', handleError);
    video.addEventListener('progress', handleProgress);

    // Set the source
    video.src = streamUrl;
    video.load();

    // Store cleanup function
    playerRef.current = {
      destroy: () => {
        video.removeEventListener('loadstart', handleLoadStart);
        video.removeEventListener('loadeddata', handleLoadedData);
        video.removeEventListener('canplay', handleCanPlay);
        video.removeEventListener('error', handleError);
        video.removeEventListener('progress', handleProgress);
        video.removeAttribute('src');
        video.load();
      },
    };
  };

  // Initialize live stream player (mpegts.js)
  const initializeLivePlayer = () => {
    if (!videoRef.current || !streamUrl) return;

    setIsLoading(true);
    setLoadError(null);

    console.log('Initializing live stream player for:', streamUrl);

    try {
      if (!mpegts.getFeatureList().mseLivePlayback) {
        setIsLoading(false);
        setLoadError(
          "Your browser doesn't support live video streaming. Please try Chrome or Edge."
        );
        return;
      }

      const player = mpegts.createPlayer({
        type: 'mpegts',
        url: streamUrl,
        isLive: true,
        enableWorker: true,
        enableStashBuffer: false,
        liveBufferLatencyChasing: true,
        liveSync: true,
        cors: true,
        autoCleanupSourceBuffer: true,
        autoCleanupMaxBackwardDuration: 10,
        autoCleanupMinBackwardDuration: 5,
        reuseRedirectedURL: true,
      });

      player.attachMediaElement(videoRef.current);

      player.on(mpegts.Events.LOADING_COMPLETE, () => {
        setIsLoading(false);
      });

      player.on(mpegts.Events.METADATA_ARRIVED, () => {
        setIsLoading(false);
      });

      player.on(mpegts.Events.ERROR, (errorType, errorDetail) => {
        setIsLoading(false);

        if (errorType !== 'NetworkError' || !errorDetail?.includes('aborted')) {
          console.error('Player error:', errorType, errorDetail);

          let errorMessage = `Error: ${errorType}`;

          if (errorType === 'MediaError') {
            const errorString = errorDetail?.toLowerCase() || '';

            if (
              errorString.includes('audio') ||
              errorString.includes('ac3') ||
              errorString.includes('ac-3')
            ) {
              errorMessage =
                'Audio codec not supported by your browser. Try Chrome or Edge for better audio codec support.';
            } else if (
              errorString.includes('video') ||
              errorString.includes('h264') ||
              errorString.includes('h.264')
            ) {
              errorMessage =
                'Video codec not supported by your browser. Try Chrome or Edge for better video codec support.';
            } else if (errorString.includes('mse')) {
              errorMessage =
                "Your browser doesn't support the codecs used in this stream. Try Chrome or Edge for better compatibility.";
            } else {
              errorMessage =
                'Media codec not supported by your browser. This may be due to unsupported audio (AC3) or video codecs. Try Chrome or Edge.';
            }
          } else if (errorDetail) {
            errorMessage += ` - ${errorDetail}`;
          }

          setLoadError(errorMessage);
        }
      });

      player.load();

      player.on(mpegts.Events.MEDIA_INFO, () => {
        setIsLoading(false);
        try {
          player.play().catch((e) => {
            console.log('Auto-play prevented:', e);
            setLoadError('Auto-play was prevented. Click play to start.');
          });
        } catch (e) {
          console.log('Error during play:', e);
          setLoadError(`Playback error: ${e.message}`);
        }
      });

      playerRef.current = player;
    } catch (error) {
      setIsLoading(false);
      console.error('Error initializing player:', error);

      if (
        error.message?.includes('codec') ||
        error.message?.includes('format')
      ) {
        setLoadError(
          'Codec not supported by your browser. Please try a different browser (Chrome/Edge recommended).'
        );
      } else {
        setLoadError(`Initialization error: ${error.message}`);
      }
    }
  };

  useEffect(() => {
    if (!isVisible || !streamUrl) {
      safeDestroyPlayer();
      return;
    }

    // Clean up any existing player
    safeDestroyPlayer();

    // Initialize the appropriate player based on content type
    if (contentType === 'vod') {
      initializeVODPlayer();
    } else {
      initializeLivePlayer();
    }

    // Cleanup when component unmounts or streamUrl changes
    return () => {
      safeDestroyPlayer();
    };
  }, [isVisible, streamUrl, contentType]);

  // Modified hideVideo handler to clean up player first
  const handleClose = (e) => {
    if (e) {
      e.stopPropagation();
      e.preventDefault();
    }
    safeDestroyPlayer();
    setTimeout(() => {
      hideVideo();
    }, 50);
  };

  const clampToVisible = useCallback(
    (x, y) => {
      if (typeof window === 'undefined') return { x, y };

      const minX = -(videoSize.width - VISIBLE_MARGIN);
      const minY = -(videoSize.height - VISIBLE_MARGIN);
      const maxX = window.innerWidth - VISIBLE_MARGIN;
      const maxY = window.innerHeight - VISIBLE_MARGIN;

      return {
        x: Math.min(Math.max(x, minX), maxX),
        y: Math.min(Math.max(y, minY), maxY),
      };
    },
    [VISIBLE_MARGIN, videoSize.height, videoSize.width]
  );

  const handleResizeMove = useCallback(
    (event) => {
      if (!resizeStateRef.current) return;

      const clientX =
        event.touches && event.touches.length ? event.touches[0].clientX : event.clientX;
      const clientY =
        event.touches && event.touches.length ? event.touches[0].clientY : event.clientY;

      const deltaX = clientX - resizeStateRef.current.startX;
      const deltaY = clientY - resizeStateRef.current.startY;
      const aspectRatio = resizeStateRef.current.aspectRatio || aspectRatioRef.current;

      // Derive width/height while keeping the original aspect ratio
      let nextWidth = resizeStateRef.current.startWidth + deltaX;
      let nextHeight = nextWidth / aspectRatio;

      // Allow vertical-driven resize if the user drags mostly vertically
      if (Math.abs(deltaY) > Math.abs(deltaX)) {
        nextHeight = resizeStateRef.current.startHeight + deltaY;
        nextWidth = nextHeight * aspectRatio;
      }

      // Respect minimums while keeping the ratio
      if (nextWidth < MIN_WIDTH) {
        nextWidth = MIN_WIDTH;
        nextHeight = nextWidth / aspectRatio;
      }

      if (nextHeight < MIN_HEIGHT) {
        nextHeight = MIN_HEIGHT;
        nextWidth = nextHeight * aspectRatio;
      }

      // Keep within viewport with a margin based on current position
      const posX = dragPositionRef.current?.x ?? 0;
      const posY = dragPositionRef.current?.y ?? 0;
      const margin = VISIBLE_MARGIN;

      const maxWidth = Math.max(MIN_WIDTH, window.innerWidth - posX - margin);
      const maxHeight = Math.max(MIN_HEIGHT, window.innerHeight - posY - margin);

      if (nextWidth > maxWidth) {
        nextWidth = maxWidth;
        nextHeight = nextWidth / aspectRatio;
      }

      if (nextHeight > maxHeight) {
        nextHeight = maxHeight;
        nextWidth = nextHeight * aspectRatio;
      }

      // Final pass to honor both bounds while keeping the ratio
      if (nextWidth > maxWidth) {
        nextWidth = maxWidth;
        nextHeight = nextWidth / aspectRatio;
      }

      setVideoSize({
        width: Math.round(nextWidth),
        height: Math.round(nextHeight),
      });
    },
    [MIN_HEIGHT, MIN_WIDTH, VISIBLE_MARGIN]
  );

  const endResize = useCallback(() => {
    setIsResizing(false);
    resizeStateRef.current = null;
    window.removeEventListener('mousemove', handleResizeMove);
    window.removeEventListener('mouseup', endResize);
    window.removeEventListener('touchmove', handleResizeMove);
    window.removeEventListener('touchend', endResize);
  }, [handleResizeMove]);

  const startResize = (event) => {
    event.stopPropagation();
    event.preventDefault();

    const clientX =
      event.touches && event.touches.length ? event.touches[0].clientX : event.clientX;
    const clientY =
      event.touches && event.touches.length ? event.touches[0].clientY : event.clientY;

    const aspectRatio =
      videoSize.height > 0 ? videoSize.width / videoSize.height : aspectRatioRef.current;
    aspectRatioRef.current = aspectRatio;

    resizeStateRef.current = {
      startX: clientX,
      startY: clientY,
      startWidth: videoSize.width,
      startHeight: videoSize.height,
      aspectRatio,
    };

    setIsResizing(true);

    window.addEventListener('mousemove', handleResizeMove);
    window.addEventListener('mouseup', endResize);
    window.addEventListener('touchmove', handleResizeMove);
    window.addEventListener('touchend', endResize);
  };

  useEffect(() => {
    return () => {
      endResize();
    };
  }, [endResize]);

  useEffect(() => {
    dragPositionRef.current = dragPosition;
  }, [dragPosition]);

  // Initialize the floating window near bottom-right once
  useEffect(() => {
    if (initialPositionRef.current || typeof window === 'undefined') return;

    const initialX = Math.max(10, window.innerWidth - videoSize.width - 20);
    const initialY = Math.max(10, window.innerHeight - videoSize.height - 20);
    const pos = clampToVisible(initialX, initialY);

    initialPositionRef.current = pos;
    setDragPosition(pos);
    dragPositionRef.current = pos;
  }, [clampToVisible, videoSize.height, videoSize.width]);

  const handleDragStart = useCallback(
    (event, data) => {
      const clientX = event.touches?.[0]?.clientX ?? event.clientX;
      const clientY = event.touches?.[0]?.clientY ?? event.clientY;
      const rect = videoContainerRef.current?.getBoundingClientRect();

      if (clientX != null && clientY != null && rect) {
        dragOffsetRef.current = {
          x: clientX - rect.left,
          y: clientY - rect.top,
        };
      } else {
        dragOffsetRef.current = { x: 0, y: 0 };
      }

      const clamped = clampToVisible(data?.x ?? 0, data?.y ?? 0);
      setDragPosition(clamped);
      dragPositionRef.current = clamped;
    },
    [clampToVisible]
  );

  const handleDrag = useCallback(
    (event) => {
      const clientX = event.touches?.[0]?.clientX ?? event.clientX;
      const clientY = event.touches?.[0]?.clientY ?? event.clientY;
      if (clientX == null || clientY == null) return;

      const nextX = clientX - (dragOffsetRef.current?.x ?? 0);
      const nextY = clientY - (dragOffsetRef.current?.y ?? 0);
      const clamped = clampToVisible(nextX, nextY);
      setDragPosition(clamped);
      dragPositionRef.current = clamped;
    },
    [clampToVisible]
  );

  const handleDragStop = useCallback(
    (_, data) => {
      const clamped = clampToVisible(data?.x ?? 0, data?.y ?? 0);
      setDragPosition(clamped);
      dragPositionRef.current = clamped;
    },
    [clampToVisible]
  );

  // If the floating video is hidden or no URL is selected, do not render
  if (!isVisible || !streamUrl) {
    return null;
  }

  return (
    <Draggable
      nodeRef={videoContainerRef}
      cancel=".floating-video-no-drag"
      disabled={isResizing}
      position={dragPosition || undefined}
      defaultPosition={initialPositionRef.current || { x: 0, y: 0 }}
      onStart={handleDragStart}
      onDrag={handleDrag}
      onStop={handleDragStop}
    >
      <div
        ref={videoContainerRef}
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: `${videoSize.width}px`,
          zIndex: 9999,
          backgroundColor: '#333',
          borderRadius: '8px',
          overflow: 'visible',
          boxShadow: '0 2px 10px rgba(0,0,0,0.7)',
        }}
      >
        {/* Simple header row with a close button */}
        <Flex
          justify="flex-end"
          style={{
            padding: 3,
          }}
        >
          <CloseButton
            onClick={handleClose}
            onTouchEnd={handleClose}
            onMouseDown={(e) => e.stopPropagation()}
            onTouchStart={(e) => e.stopPropagation()}
            style={{
              minHeight: '32px',
              minWidth: '32px',
              cursor: 'pointer',
              touchAction: 'manipulation',
            }}
          />
        </Flex>

        {/* Video container with relative positioning for the overlay */}
        <Box
          style={{ position: 'relative' }}
          onMouseEnter={() => {
            if (contentType === 'vod' && !isLoading) {
              setShowOverlay(true);
              if (overlayTimeoutRef.current) {
                clearTimeout(overlayTimeoutRef.current);
              }
            }
          }}
          onMouseLeave={() => {
            if (contentType === 'vod' && !isLoading) {
              startOverlayTimer();
            }
          }}
        >
          {/* Enhanced video element with better controls for VOD */}
          <video
            ref={videoRef}
            controls
            className="floating-video-no-drag"
            style={{
              width: '100%',
              height: `${videoSize.height}px`,
              backgroundColor: '#000',
              borderRadius: '0 0 8px 8px',
              // Better controls styling for VOD
              ...(contentType === 'vod' && {
                controlsList: 'nodownload',
                playsInline: true,
              }),
            }}
            // Add poster for VOD if available
            {...(contentType === 'vod' && {
              poster: metadata?.logo?.url, // Use VOD poster if available
            })}
          />

          {/* VOD title overlay when not loading - auto-hides after 4 seconds */}
          {!isLoading && metadata && contentType === 'vod' && showOverlay && (
            <Box
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                right: 0,
                background: 'linear-gradient(rgba(0,0,0,0.8), transparent)',
                padding: '10px 10px 20px',
                color: 'white',
                pointerEvents: 'none', // Allow clicks to pass through to video controls
                transition: 'opacity 0.3s ease-in-out',
                opacity: showOverlay ? 1 : 0,
              }}
            >
              <Text
                size="sm"
                weight={500}
                style={{ textShadow: '1px 1px 2px rgba(0,0,0,0.8)' }}
              >
                {metadata.name}
              </Text>
              {metadata.year && (
                <Text
                  size="xs"
                  color="dimmed"
                  style={{ textShadow: '1px 1px 2px rgba(0,0,0,0.8)' }}
                >
                  {metadata.year}
                </Text>
              )}
            </Box>
          )}

          {/* Loading overlay - only show when loading */}
          {isLoading && (
            <Box
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: '100%',
                backgroundColor: 'rgba(0, 0, 0, 0.7)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                zIndex: 5,
              }}
            >
              <Loader color="cyan" size="md" />
              <Text color="white" size="sm" mt={10}>
                Loading {contentType === 'vod' ? 'video' : 'stream'}...
              </Text>
            </Box>
          )}

          {/* Resize handle */}
          <Box
            className="floating-video-no-drag"
            onMouseDown={startResize}
            onTouchStart={startResize}
            style={{
              position: 'absolute',
              bottom: '-12px',
              right: '-12px',
              width: '22px',
              height: '22px',
              background: 'transparent',
              borderBottom: '2px solid white',
              borderRight: '2px solid white',
              borderRadius: '0 0 6px 0',
              cursor: 'nwse-resize',
              zIndex: 6,
              touchAction: 'none',
              boxShadow: '0 0 6px rgba(0,0,0,0.35)',
            }}
          />
        </Box>

        {/* Error message below video - doesn't block controls */}
        {!isLoading && loadError && (
          <Box
            style={{
              padding: '10px',
              backgroundColor: '#2d1b2e',
              borderTop: '1px solid #444',
            }}
          >
            <Text color="red" size="xs" style={{ textAlign: 'center' }}>
              {loadError}
            </Text>
          </Box>
        )}
      </div>
    </Draggable>
  );
}
