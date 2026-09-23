"use client";

import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Box, CheckCircle2, AlertCircle } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import {
  threeDFaceService,
  ThreeDFaceCapturePayload,
  ThreeDFaceResponse,
  ThreeDFaceComparePayload,
  ThreeDFaceCompareResponse,
  ThreeDFaceLivenessResponse,
} from '@/services/api';

type MessageState = { type: 'success' | 'error'; text: string } | null;

type CaptureFormState = {
  visitor_id: string;
  detection_log_id: string;
  embedding_3d: string;
  embedding_confidence: number;
  capture_quality_score: number;
};

type CompareFormState = {
  face_data_1_id: string;
  face_data_2_id: string;
  match_threshold: number;
};

type LivenessFormState = {
  face_data_id: string;
};

const parseEmbedding = (value: string): number[] | undefined => {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  const parts = trimmed.split(/[,\s]+/).filter(Boolean);
  const numbers = parts.map((item) => Number(item));
  if (numbers.some((n) => Number.isNaN(n))) {
    return undefined;
  }
  return numbers;
};

const ThreeDFaceTab: React.FC = () => {
  const [message, setMessage] = useState<MessageState>(null);
  const [captureForm, setCaptureForm] = useState<CaptureFormState>({
    visitor_id: '',
    detection_log_id: '',
    embedding_3d: '',
    embedding_confidence: 0.0,
    capture_quality_score: 0.0,
  });
  const [compareForm, setCompareForm] = useState<CompareFormState>({
    face_data_1_id: '',
    face_data_2_id: '',
    match_threshold: 0.75,
  });
  const [livenessForm, setLivenessForm] = useState<LivenessFormState>({
    face_data_id: '',
  });

  const [capturing, setCapturing] = useState(false);
  const [comparing, setComparing] = useState(false);
  const [checkingLiveness, setCheckingLiveness] = useState(false);

  const [captureResult, setCaptureResult] = useState<ThreeDFaceResponse | null>(null);
  const [compareResult, setCompareResult] = useState<ThreeDFaceCompareResponse | null>(null);
  const [livenessResult, setLivenessResult] = useState<ThreeDFaceLivenessResponse | null>(null);

  const handleCapture = async (event: React.FormEvent) => {
    event.preventDefault();
    setMessage(null);
    if (!captureForm.visitor_id.trim()) {
      setMessage({ type: 'error', text: 'Visitor ID is required.' });
      return;
    }

    const embedding = parseEmbedding(captureForm.embedding_3d);
    if (captureForm.embedding_3d.trim() && !embedding) {
      setMessage({ type: 'error', text: 'Embedding must be a comma-separated list of numbers.' });
      return;
    }

    const payload: ThreeDFaceCapturePayload = {
      visitor_id: captureForm.visitor_id.trim(),
      detection_log_id: captureForm.detection_log_id.trim() || undefined,
      embedding_3d: embedding,
      embedding_confidence: captureForm.embedding_confidence,
      capture_quality_score: captureForm.capture_quality_score,
    };

    setCapturing(true);
    try {
      const res = await threeDFaceService.capture(payload);
      setCaptureResult(res.data);
      setMessage({ type: 'success', text: '3D face capture stored.' });
    } catch (err) {
      setMessage({ type: 'error', text: err instanceof Error ? err.message : 'Capture failed.' });
    } finally {
      setCapturing(false);
    }
  };

  const handleCompare = async (event: React.FormEvent) => {
    event.preventDefault();
    setMessage(null);
    if (!compareForm.face_data_1_id.trim() || !compareForm.face_data_2_id.trim()) {
      setMessage({ type: 'error', text: 'Both 3D face IDs are required for comparison.' });
      return;
    }

    const payload: ThreeDFaceComparePayload = {
      face_data_1_id: compareForm.face_data_1_id.trim(),
      face_data_2_id: compareForm.face_data_2_id.trim(),
      match_threshold: compareForm.match_threshold,
    };

    setComparing(true);
    try {
      const res = await threeDFaceService.compare(payload);
      setCompareResult(res.data);
      setMessage({ type: 'success', text: '3D face comparison complete.' });
    } catch (err) {
      setMessage({ type: 'error', text: err instanceof Error ? err.message : 'Comparison failed.' });
    } finally {
      setComparing(false);
    }
  };

  const handleLiveness = async (event: React.FormEvent) => {
    event.preventDefault();
    setMessage(null);
    if (!livenessForm.face_data_id.trim()) {
      setMessage({ type: 'error', text: 'Face data ID is required for liveness check.' });
      return;
    }

    setCheckingLiveness(true);
    try {
      const res = await threeDFaceService.liveness(livenessForm.face_data_id.trim());
      setLivenessResult(res.data);
      setMessage({ type: 'success', text: '3D liveness check completed.' });
    } catch (err) {
      setMessage({ type: 'error', text: err instanceof Error ? err.message : 'Liveness check failed.' });
    } finally {
      setCheckingLiveness(false);
    }
  };

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="space-y-6">
      <Card>
        <CardHeader className="border-b border-white/5 bg-white/5">
          <CardTitle className="flex items-center gap-3 text-sky-400">
            <Box size={18} />
            3D Face Capture
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6 grid gap-4">
          {message && (
            <div className={`rounded-xl border px-4 py-3 text-sm flex items-center gap-2 ${message.type === 'success'
              ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
              : 'border-red-500/30 bg-red-500/10 text-red-300'
            }`}>
              {message.type === 'success' ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
              {message.text}
            </div>
          )}

          <form onSubmit={handleCapture} className="grid gap-3">
            <Input
              value={captureForm.visitor_id}
              onChange={(event) => setCaptureForm({ ...captureForm, visitor_id: event.target.value })}
              placeholder="Visitor ID"
            />
            <Input
              value={captureForm.detection_log_id}
              onChange={(event) => setCaptureForm({ ...captureForm, detection_log_id: event.target.value })}
              placeholder="Detection Log ID (optional)"
            />
            <Input
              value={captureForm.embedding_3d}
              onChange={(event) => setCaptureForm({ ...captureForm, embedding_3d: event.target.value })}
              placeholder="Embedding vector (comma-separated)"
            />
            <div className="grid gap-2 md:grid-cols-2">
              <Input
                type="number"
                step="0.01"
                min={0}
                max={1}
                value={captureForm.embedding_confidence}
                onChange={(event) => setCaptureForm({
                  ...captureForm,
                  embedding_confidence: Number(event.target.value || 0),
                })}
                placeholder="Embedding confidence"
              />
              <Input
                type="number"
                step="0.01"
                min={0}
                max={1}
                value={captureForm.capture_quality_score}
                onChange={(event) => setCaptureForm({
                  ...captureForm,
                  capture_quality_score: Number(event.target.value || 0),
                })}
                placeholder="Capture quality score"
              />
            </div>
            <Button type="submit" disabled={capturing}>
              {capturing ? 'Saving capture...' : 'Save 3D Capture'}
            </Button>
          </form>

          {captureResult && (
            <div className="rounded-xl border border-white/10 bg-white/5 p-4 text-sm text-gray-200">
              <p>Capture ID: {captureResult.id}</p>
              <p>Visitor: {captureResult.visitor_id}</p>
              <p>Confidence: {captureResult.embedding_confidence}</p>
              <p>Quality: {captureResult.capture_quality_score}</p>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="border-b border-white/5 bg-white/5">
            <CardTitle className="text-emerald-400">Compare 3D Captures</CardTitle>
          </CardHeader>
          <CardContent className="pt-6 grid gap-3">
            <form onSubmit={handleCompare} className="grid gap-3">
              <Input
                value={compareForm.face_data_1_id}
                onChange={(event) => setCompareForm({ ...compareForm, face_data_1_id: event.target.value })}
                placeholder="3D face data ID #1"
              />
              <Input
                value={compareForm.face_data_2_id}
                onChange={(event) => setCompareForm({ ...compareForm, face_data_2_id: event.target.value })}
                placeholder="3D face data ID #2"
              />
              <Input
                type="number"
                step="0.01"
                min={0}
                max={1}
                value={compareForm.match_threshold}
                onChange={(event) => setCompareForm({
                  ...compareForm,
                  match_threshold: Number(event.target.value || 0.75),
                })}
                placeholder="Match threshold"
              />
              <Button type="submit" disabled={comparing}>
                {comparing ? 'Comparing...' : 'Compare Faces'}
              </Button>
            </form>

            {compareResult && (
              <div className="rounded-xl border border-white/10 bg-black/20 p-4 text-sm text-gray-200">
                <p>Match confidence: {compareResult.match_confidence.toFixed(3)}</p>
                <p>Same person: {compareResult.is_same_person ? 'Yes' : 'No'}</p>
                <p>Cosine similarity: {compareResult.cosine_similarity ?? 'N/A'}</p>
                <p>L2 distance: {compareResult.l2_distance ?? 'N/A'}</p>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-white/5 bg-white/5">
            <CardTitle className="text-purple-400">3D Liveness Check</CardTitle>
          </CardHeader>
          <CardContent className="pt-6 grid gap-3">
            <form onSubmit={handleLiveness} className="grid gap-3">
              <Input
                value={livenessForm.face_data_id}
                onChange={(event) => setLivenessForm({ face_data_id: event.target.value })}
                placeholder="3D face data ID"
              />
              <Button type="submit" disabled={checkingLiveness}>
                {checkingLiveness ? 'Checking...' : 'Run Liveness Check'}
              </Button>
            </form>

            {livenessResult && (
              <div className="rounded-xl border border-white/10 bg-black/20 p-4 text-sm text-gray-200">
                <p>Face data ID: {livenessResult.face_data_id}</p>
                <p>Geometric score: {livenessResult.geometric_liveness_score.toFixed(3)}</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </motion.div>
  );
};

export default ThreeDFaceTab;
