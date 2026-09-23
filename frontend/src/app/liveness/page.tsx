'use client';

import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { authService, livenessService, logService, type VisitorLog } from '@/services/api';

interface ChallengeType {
  id: string;
  name: string;
  description: string;
  difficulty: 'easy' | 'medium' | 'hard';
  icon: string;
  estimatedTime: string;
}

const challenges: ChallengeType[] = [
  {
    id: 'blink',
    name: 'Blink Detection',
    description: 'Blink your eyes naturally to verify you are a real person',
    difficulty: 'easy',
    icon: '👁️',
    estimatedTime: '5-10 seconds',
  },
  {
    id: 'head_turn',
    name: 'Head Turn Challenge',
    description: 'Turn your head left and right to verify you are a real person',
    difficulty: 'medium',
    icon: '🔄',
    estimatedTime: '10-15 seconds',
  },
  {
    id: 'smile',
    name: 'Smile Detection',
    description: 'Smile naturally to verify you are a real person',
    difficulty: 'easy',
    icon: '😊',
    estimatedTime: '5-10 seconds',
  },
];

interface ChallengeCaptureConfig {
  intervalMs: number;
  durationMs: number;
  maxFrames: number;
  outputWidth: number;
  jpegQuality: number;
}

const challengeCaptureConfig: Record<string, ChallengeCaptureConfig> = {
  blink: { intervalMs: 350, durationMs: 5600, maxFrames: 14, outputWidth: 320, jpegQuality: 0.88 },
  head_turn: { intervalMs: 450, durationMs: 5600, maxFrames: 10, outputWidth: 320, jpegQuality: 0.88 },
  smile: { intervalMs: 450, durationMs: 5000, maxFrames: 10, outputWidth: 320, jpegQuality: 0.88 },
};

const defaultCaptureConfig = challengeCaptureConfig.blink;

export default function LivenessPage() {
  const [selectedChallenge, setSelectedChallenge] = useState<string | null>(null);

  return (
    <div className="min-h-screen bg-[#050505] p-8">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="mb-12 text-center">
          <h1 className="text-4xl font-bold text-white mb-3">
            Liveness Verification
          </h1>
          <p className="text-lg text-gray-400">
            Verify you are a real person by completing one of the challenges below
          </p>
        </div>

        {/* Challenge Selection */}
        {!selectedChallenge && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
            {challenges.map((challenge) => (
              <Card
                key={challenge.id}
                className="cursor-pointer hover:shadow-lg transition-shadow"
                onClick={() => setSelectedChallenge(challenge.id)}
              >
                <CardHeader>
                  <div className="text-4xl mb-3">{challenge.icon}</div>
                  <CardTitle>{challenge.name}</CardTitle>
                  <CardDescription>{challenge.description}</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-gray-400">Difficulty:</span>
                      <span className={`px-3 py-1 rounded-full text-xs font-semibold ${
                        challenge.difficulty === 'easy' ? 'bg-green-500/10 text-green-400' :
                        challenge.difficulty === 'medium' ? 'bg-yellow-500/10 text-yellow-400' :
                        'bg-red-500/10 text-red-400'
                      }`}>
                        {challenge.difficulty.charAt(0).toUpperCase() + challenge.difficulty.slice(1)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-gray-400">Time:</span>
                      <span className="text-sm font-medium text-gray-200">{challenge.estimatedTime}</span>
                    </div>
                    <Button
                      className="w-full mt-4"
                      onClick={() => setSelectedChallenge(challenge.id)}
                    >
                      Start Challenge
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {/* Challenge In Progress */}
        {selectedChallenge && (
          <div className="mb-8">
            <Button
              variant="outline"
              onClick={() => setSelectedChallenge(null)}
              className="mb-4"
            >
              ← Back to Challenge Selection
            </Button>
            <LivenessChallengeComponent
              challengeId={selectedChallenge}
              onComplete={() => setSelectedChallenge(null)}
            />
          </div>
        )}

        {/* Info Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-12">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <span>✅</span> How It Works
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-gray-300">
                <strong>1. Camera Access:</strong> We need camera access to see your face
              </p>
              <p className="text-sm text-gray-300">
                <strong>2. Select Challenge:</strong> Choose one of the three challenges
              </p>
              <p className="text-sm text-gray-300">
                <strong>3. Complete Action:</strong> Follow the on-screen instructions
              </p>
              <p className="text-sm text-gray-300">
                <strong>4. Verify:</strong> We verify you're a real person and complete your verification
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <span>🔒</span> Privacy & Security
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-gray-300">
                ✓ Your camera feed is processed locally on your device
              </p>
              <p className="text-sm text-gray-300">
                ✓ We only store biometric data with your consent
              </p>
              <p className="text-sm text-gray-300">
                ✓ All data is encrypted in transit and at rest
              </p>
              <p className="text-sm text-gray-300">
                ✓ You can request data deletion anytime
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

interface LivenessChallengeComponentProps {
  challengeId: string;
  onComplete: () => void;
}

function LivenessChallengeComponent({
  challengeId,
  onComplete,
}: LivenessChallengeComponentProps) {
  const challengeConfig = challenges.find(c => c.id === challengeId);

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {challengeConfig?.icon} {challengeConfig?.name}
        </CardTitle>
        <CardDescription>Follow the instructions below</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-6">
          <div className="bg-gray-900/50 rounded-lg border border-white/10 p-6">
            <LivenessChallengeUI challengeId={challengeId} />
          </div>

          <div className="flex gap-4 justify-end">
            <Button variant="outline" onClick={onComplete}>
              Cancel
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

interface LivenessChallengeUIProps {
  challengeId: string;
}

// Issue 21: Countdown timer during recording
function RecordingCountdown({ challengeId }: { challengeId: string }) {
  const total = challengeCaptureConfig[challengeId]?.durationMs || defaultCaptureConfig.durationMs;
  const [remaining, setRemaining] = React.useState(total);

  React.useEffect(() => {
    const start = Date.now();
    const iv = setInterval(() => {
      const elapsed = Date.now() - start;
      setRemaining(Math.max(0, total - elapsed));
    }, 100);
    return () => clearInterval(iv);
  }, [total]);

  return (
    <span className="text-xs font-mono text-yellow-400 ml-2">
      {(remaining / 1000).toFixed(1)}s
    </span>
  );
}

function LivenessChallengeUI({ challengeId }: LivenessChallengeUIProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingLogs, setIsLoadingLogs] = useState(true);
  const [isBootstrappingSession, setIsBootstrappingSession] = useState(true);
  const [sessionReady, setSessionReady] = useState(false);
  const [status, setStatus] = useState<'ready' | 'recording' | 'processing' | 'complete'>('ready');
  const [result, setResult] = useState<any>(null);
  const [uiError, setUiError] = useState<string | null>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [cameraPermissionDenied, setCameraPermissionDenied] = useState(false);
  const [retryingCamera, setRetryingCamera] = useState(false);
  const [visitorLogId, setVisitorLogId] = useState('');
  const [challengeSessionId, setChallengeSessionId] = useState<string | null>(null);
  const [recentLogs, setRecentLogs] = useState<VisitorLog[]>([]);
  const videoRef = React.useRef<HTMLVideoElement>(null);
  const canvasRef = React.useRef<HTMLCanvasElement>(null);
  const activeStreamRef = React.useRef<MediaStream | null>(null);
  const currentCaptureConfig = challengeCaptureConfig[challengeId] || defaultCaptureConfig;
  const currentUrl = typeof window !== 'undefined' ? window.location.href : 'http://localhost:3001/liveness';

  const instructionMap: Record<string, string> = {
    blink: 'Blink your eyes naturally. Make sure to blink at least 3 times.',
    head_turn: 'Slowly turn your head to the left, then to the right.',
    smile: 'Smile naturally and hold the smile for 2-3 seconds.',
  };

  React.useEffect(() => {
    setStatus('ready');
    setIsLoading(false);
    setResult(null);
    setUiError(null);
    setChallengeSessionId(null);
  }, [challengeId]);

  React.useEffect(() => {
    let isMounted = true;

    const bootstrapSession = async () => {
      setIsBootstrappingSession(true);

      try {
        const restored = await authService.ensureSession();
        if (!isMounted) {
          return;
        }

        if (!restored) {
          setSessionReady(false);
          setUiError('Your session could not be restored. Sign in again, then reopen this page in a regular browser tab for camera access.');
          return;
        }

        setSessionReady(true);
      } catch (error) {
        if (isMounted) {
          setSessionReady(false);
          setUiError('Could not restore your session. Sign in again and retry the liveness challenge.');
        }
      } finally {
        if (isMounted) {
          setIsBootstrappingSession(false);
        }
      }
    };

    void bootstrapSession();

    return () => {
      isMounted = false;
    };
  }, []);

  React.useEffect(() => {
    let isMounted = true;

    const loadRecentLogs = async () => {
      if (!sessionReady) {
        setIsLoadingLogs(false);
        return;
      }

      setIsLoadingLogs(true);
      try {
        const response = await logService.getLogs({ limit: 12, page: 1 });
        const items = response.data.items || [];
        if (!isMounted) return;
        setRecentLogs(items);
        if (!visitorLogId && items.length > 0) {
          setVisitorLogId(items[0].id);
        }
      } catch (error: any) {
        if (isMounted) {
          if (error?.response?.status === 401) {
            setUiError('Your session expired before visitor logs could load. Sign in again and retry.');
            setSessionReady(false);
          } else {
            setUiError('Could not load recent visitor logs. You can still paste a log ID manually.');
          }
        }
      } finally {
        if (isMounted) {
          setIsLoadingLogs(false);
        }
      }
    };

    void loadRecentLogs();

    return () => {
      isMounted = false;
    };
  }, [sessionReady]);

  const stopStream = React.useCallback((mediaStream: MediaStream | null) => {
    mediaStream?.getTracks().forEach((track) => track.stop());
  }, []);

  const initCamera = React.useCallback(async () => {
    setCameraPermissionDenied(false);
    setUiError(null);

    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setCameraPermissionDenied(true);
      setUiError('This browser does not expose camera access. Open SentinelCV in a current Chrome, Edge, or Firefox window.');
      return;
    }

    if (
      typeof window !== 'undefined' &&
      !window.isSecureContext &&
      window.location.hostname !== 'localhost' &&
      window.location.hostname !== '127.0.0.1'
    ) {
      setCameraPermissionDenied(true);
      setUiError('Camera access requires HTTPS or localhost. Open this page from a secure browser origin and retry.');
      return;
    }

    try {
      stopStream(activeStreamRef.current);
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false,
      });
      activeStreamRef.current = mediaStream;
      setStream(mediaStream);
      if (videoRef.current) {
        videoRef.current.srcObject = mediaStream;
      }
    } catch (error: any) {
      console.error('Camera access denied:', error);
      setCameraPermissionDenied(true);
      if (error?.name === 'NotAllowedError' || error?.name === 'PermissionDeniedError') {
        setUiError('Camera access was blocked. If you opened this page inside the VS Code preview, reopen the same URL in Chrome, Edge, or Firefox and allow the camera there.');
      } else if (error?.name === 'NotFoundError' || error?.name === 'DevicesNotFoundError') {
        setUiError('No camera was found on this machine. Connect a webcam and retry.');
      } else if (error?.name === 'NotReadableError') {
        setUiError('The camera is already in use by another application. Close the other app and retry.');
      } else {
        setUiError('Camera access failed. Open this page in a regular browser window and retry.');
      }
    }
  }, [stopStream]);

  const retryCamera = async () => {
    setRetryingCamera(true);
    await initCamera();
    setRetryingCamera(false);
  };

  React.useEffect(() => {
    if (!sessionReady) {
      return;
    }

    void initCamera();

    return () => {
      stopStream(activeStreamRef.current);
      activeStreamRef.current = null;
    };
  }, [initCamera, sessionReady, stopStream]);

  const captureFrameData = (captureConfig: ChallengeCaptureConfig) => {
    if (!canvasRef.current || !videoRef.current) return null;
    if (videoRef.current.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return null;

    const ctx = canvasRef.current.getContext('2d');
    if (!ctx) return null;

    const sourceWidth = videoRef.current.videoWidth || 640;
    const sourceHeight = videoRef.current.videoHeight || 480;
    const aspectRatio = sourceHeight > 0 ? sourceWidth / sourceHeight : 4 / 3;
    const targetWidth = Math.max(240, Math.min(captureConfig.outputWidth, sourceWidth));
    const targetHeight = Math.max(180, Math.round(targetWidth / aspectRatio));

    canvasRef.current.width = targetWidth;
    canvasRef.current.height = targetHeight;
    ctx.drawImage(videoRef.current, 0, 0, targetWidth, targetHeight);
    return canvasRef.current.toDataURL('image/jpeg', captureConfig.jpegQuality);
  };

  const startChallenge = async () => {
    if (!sessionReady) {
      setUiError('Your session is still being restored. Wait for the page to finish bootstrapping, then try again.');
      return;
    }

    if (!stream) {
      setUiError('Camera is not ready yet. Allow camera access and wait for the preview before starting.');
      return;
    }

    if (!visitorLogId.trim()) {
      setUiError('Select a recent visitor log or paste a visitor log ID before starting.');
      return;
    }

    setIsLoading(true);
    setUiError(null);
    setResult(null);
    setStatus('ready');

    try {
      const startResponse = await livenessService.startChallenge({
        visitor_log_id: visitorLogId.trim(),
        challenge_type: challengeId,
      });
      const startedChallengeId = startResponse.data.challenge_id;
      setChallengeSessionId(startedChallengeId);

      if (stream) {
        const capturedFrames: string[] = [];
        const captureCurrentFrame = () => {
          const frameData = captureFrameData(currentCaptureConfig);
          if (frameData && capturedFrames.length < currentCaptureConfig.maxFrames) {
            capturedFrames.push(frameData);
          }
        };

        setStatus('recording');
        captureCurrentFrame();
        const captureInterval = window.setInterval(captureCurrentFrame, currentCaptureConfig.intervalMs);

        window.setTimeout(async () => {
          window.clearInterval(captureInterval);
          setStatus('processing');

          try {
            const latestFrame = captureFrameData(currentCaptureConfig);
            if (capturedFrames.length === 0 && latestFrame) {
              capturedFrames.push(latestFrame);
            }

            const response = await livenessService.verifyChallenge(
              capturedFrames.length > 1
                ? {
                    challenge_id: startedChallengeId,
                    video_frames: capturedFrames,
                  }
                : {
                    challenge_id: startedChallengeId,
                    video_frame: capturedFrames[0],
                  }
            );

            setResult(response.data);
            setStatus('complete');
          } catch (error: any) {
            console.error('Challenge submission error:', error);
            setResult({ error: error?.response?.data?.detail || 'Failed to verify challenge' });
            setStatus('complete');
          } finally {
            setIsLoading(false);
          }
        }, currentCaptureConfig.durationMs);
      }
    } catch (error) {
      console.error('Challenge start error:', error);
      setUiError('Failed to start challenge');
      setStatus('ready');
      setIsLoading(false);
    }
  };

  if (status === 'complete' && result) {
    return (
      <div className="space-y-4">
        {result.error ? (
          <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4 text-red-400">
            <p className="font-semibold">Verification Failed</p>
            <p className="text-sm mt-1">{result.error}</p>
          </div>
        ) : result.verified ? (
          <div className="bg-green-500/10 border border-green-500/20 rounded-lg p-4">
            <p className="font-semibold text-green-400">✓ Verification Successful</p>
            <p className="text-sm text-green-300 mt-1">
              Confidence: {((result.confidence || 0) * 100).toFixed(1)}%
            </p>
            {result.details && (
              <p className="text-xs text-green-400/70 mt-2">
                {JSON.stringify(result.details).substring(0, 100)}...
              </p>
            )}
          </div>
        ) : (
          <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-4">
            <p className="font-semibold text-yellow-400">Verification Inconclusive</p>
            <p className="text-sm text-yellow-300 mt-1">
              Confidence: {((result.confidence || 0) * 100).toFixed(1)}%
            </p>
            <p className="text-xs text-yellow-400/70 mt-2">Please try again</p>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {uiError && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4 text-red-400 text-sm">
          {uiError}
        </div>
      )}

      {isBootstrappingSession && (
        <div className="flex items-center gap-2 rounded-lg border border-brand-500/20 bg-brand-500/10 p-4 text-sm text-brand-300">
          <div className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-brand-500 border-t-transparent"></div>
          Restoring your session before loading camera and visitor logs...
        </div>
      )}

      <div className="bg-brand-500/10 border border-brand-500/20 rounded-lg p-4">
        <p className="text-sm text-brand-300">
          <strong>Instructions:</strong> {instructionMap[challengeId]}
        </p>
      </div>

      <div className="space-y-3">
        <div>
          <label className="block text-sm font-medium text-gray-200 mb-2">
            Visitor Log
          </label>
          <p className="text-xs text-gray-400 mb-2">
            Choose a recent log from live activities or paste a visitor log ID to bind this verification to a real detection.
          </p>
          {isLoadingLogs ? (
            <div className="text-sm text-gray-500">Loading recent visitor logs...</div>
          ) : recentLogs.length > 0 ? (
            <select
              value={visitorLogId}
              onChange={(e) => setVisitorLogId(e.target.value)}
              className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white"
            >
              {recentLogs.map((log) => (
                <option key={log.id} value={log.id}>
                  {`${new Date(log.timestamp).toLocaleString()} | ${log.visitor_name || log.status} | ${log.id.slice(0, 8)}`}
                </option>
              ))}
            </select>
          ) : (
            <div className="text-sm text-gray-500">No recent logs found. Paste a visitor log ID below.</div>
          )}
        </div>

        <input
          type="text"
          value={visitorLogId}
          onChange={(e) => setVisitorLogId(e.target.value)}
          className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder:text-gray-500"
          placeholder="Enter visitor log ID"
        />
        {challengeSessionId && (
          <p className="text-xs text-gray-500">
            Active challenge: {challengeSessionId}
          </p>
        )}
      </div>

      {cameraPermissionDenied && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-5 space-y-3">
          <div className="flex items-start gap-3">
            <span className="text-red-400 text-lg leading-none mt-0.5">⚠</span>
            <div>
              <p className="font-semibold text-red-400">Camera access denied</p>
              <p className="text-sm text-red-300/80 mt-1">
                SentinelCV needs camera access to run liveness checks. Please allow camera permissions in your browser settings, then click Retry.
              </p>
              <ol className="text-xs text-red-300/60 mt-2 space-y-0.5 list-decimal list-inside">
                <li>Click the camera icon in your browser address bar</li>
                <li>Select &ldquo;Allow&rdquo; for camera access</li>
                <li>If this page is inside the VS Code preview, open the same URL in Chrome, Edge, or Firefox</li>
                <li>Click Retry below</li>
              </ol>
              <p className="mt-2 break-all text-xs text-red-300/60">Browser URL: {currentUrl}</p>
            </div>
          </div>
          <Button
            onClick={retryCamera}
            disabled={retryingCamera || isBootstrappingSession}
            className="w-full"
          >
            {retryingCamera ? 'Requesting camera access…' : '↺ Retry camera access'}
          </Button>
        </div>
      )}

      {!cameraPermissionDenied && (
        <video
          ref={videoRef}
          autoPlay
          playsInline
          className="w-full max-h-96 bg-black rounded-lg"
        />
      )}

      <canvas
        ref={canvasRef}
        className="hidden"
        width={640}
        height={480}
      />

      {status === 'ready' && !cameraPermissionDenied && (
        <Button
          className="w-full"
          onClick={startChallenge}
          disabled={isLoading || isBootstrappingSession || !sessionReady || !stream}
        >
          {isLoading
            ? 'Starting...'
            : isBootstrappingSession
              ? 'Restoring session...'
              : !stream
                ? 'Waiting for camera...'
                : 'Start Challenge'}
        </Button>
      )}

      {status === 'recording' && (
        <div className="flex items-center justify-center gap-2 p-4 bg-yellow-500/10 border border-yellow-500/20 rounded-lg">
          <div className="animate-pulse bg-red-500 rounded-full w-3 h-3"></div>
          <span className="text-sm text-yellow-300">Recording... Please complete the action</span>
          <RecordingCountdown challengeId={challengeId} />
        </div>
      )}

      {status === 'processing' && (
        <div className="flex items-center justify-center gap-2 p-4 bg-brand-500/10 border border-brand-500/20 rounded-lg">
          <div className="animate-spin inline-block w-4 h-4 border-2 border-brand-500 border-t-transparent rounded-full"></div>
          <span className="text-sm text-brand-300">Processing your response...</span>
        </div>
      )}
    </div>
  );
}
