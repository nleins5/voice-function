import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, GraduationCap, Loader2, Mic, Send, Square, Upload, UserRoundCheck, Volume2 } from 'lucide-react';
import { apiFetch, apiPost } from '../lib/api';

const MODES = {
    interview: {
        label: 'Phỏng vấn',
        icon: UserRoundCheck,
        language: 'vi',
        question: 'Hãy giới thiệu ngắn gọn về bản thân và kinh nghiệm phù hợp với vị trí bạn đang ứng tuyển.',
        placeholder: 'Nhập hoặc ghi âm câu trả lời phỏng vấn của bạn...',
        hint: 'AI sẽ chấm nội dung, cách diễn đạt, ngắt nghỉ và dấu hiệu phát âm từ transcript.',
    },
    english: {
        label: 'English Speaking',
        icon: GraduationCap,
        language: 'en',
        question: 'Tell me about your daily routine and one thing you want to improve this week.',
        placeholder: 'Type or record your English answer...',
        hint: 'AI sẽ đánh giá phát âm qua lỗi nhận diện, ngữ pháp, từ vựng và độ trôi chảy.',
    },
};

const initialFeedback = `Bấm ghi âm hoặc nhập câu trả lời để bắt đầu.

Transcript sau khi chuyển giọng nói thành văn bản sẽ được gửi cho AI để chấm điểm và đưa ra gợi ý cải thiện.`;

export default function VoiceCoach() {
    const [mode, setMode] = useState('interview');
    const [transcript, setTranscript] = useState('');
    const [feedback, setFeedback] = useState(initialFeedback);
    const [isRecording, setIsRecording] = useState(false);
    const [isTranscribing, setIsTranscribing] = useState(false);
    const [isScoring, setIsScoring] = useState(false);
    const [status, setStatus] = useState('');
    const [audioLevel, setAudioLevel] = useState(0);
    const [micPermission, setMicPermission] = useState('unknown');
    const [userId] = useState(() => {
        let id = localStorage.getItem('voice_coach_user_id');
        if (!id) {
            id = crypto.randomUUID();
            localStorage.setItem('voice_coach_user_id', id);
        }
        return id;
    });

    const mediaRecorderRef = useRef(null);
    const audioChunksRef = useRef([]);
    const streamRef = useRef(null);
    const audioContextRef = useRef(null);
    const animationFrameRef = useRef(null);

    const activeMode = MODES[mode];

    useEffect(() => {
        let cancelled = false;
        const inspectMicPermission = async () => {
            if (!navigator.permissions?.query) return;
            try {
                const permission = await navigator.permissions.query({ name: 'microphone' });
                if (!cancelled) setMicPermission(permission.state);
                permission.onchange = () => {
                    setMicPermission(permission.state);
                };
            } catch {
                if (!cancelled) setMicPermission('unknown');
            }
        };

        inspectMicPermission();
        return () => {
            cancelled = true;
        };
    }, []);

    const cleanupRecording = useCallback((resetLevel = true) => {
        if (animationFrameRef.current) {
            cancelAnimationFrame(animationFrameRef.current);
            animationFrameRef.current = null;
        }
        if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
            audioContextRef.current.close();
            audioContextRef.current = null;
        }
        if (streamRef.current) {
            streamRef.current.getTracks().forEach((track) => track.stop());
            streamRef.current = null;
        }
        if (resetLevel) setAudioLevel(0);
    }, []);

    useEffect(() => {
        return () => cleanupRecording(false);
    }, [cleanupRecording]);

    const submitForScoring = async (textOverride) => {
        const answerText = (textOverride ?? transcript).trim();
        if (!answerText || !userId) return;

        setIsScoring(true);
        setStatus('AI đang phân tích câu trả lời...');
        try {
            const response = await apiPost('/v1/chat/unified', {
                query: answerText,
                user_id: userId,
                task: mode,
                history: [],
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail || error.error || response.statusText);
            }

            const data = await response.json();
            setFeedback(data.answer || 'Không nhận được phản hồi từ AI.');
            setStatus('Đã chấm điểm xong.');
        } catch (error) {
            setFeedback(`Không thể chấm điểm lúc này.\n\n${error.message}`);
            setStatus('Có lỗi khi gọi AI.');
        } finally {
            setIsScoring(false);
        }
    };

    const getAudioFilename = (audioBlob, mimeType) => {
        if (audioBlob.name) return audioBlob.name;
        if (mimeType.includes('webm')) return 'voice.webm';
        if (mimeType.includes('wav')) return 'voice.wav';
        if (mimeType.includes('aiff')) return 'voice.aiff';
        if (mimeType.includes('mpeg')) return 'voice.mp3';
        return 'voice.mp4';
    };

    const transcribeAudio = async (audioBlob, mimeType = audioBlob.type || 'audio/mp4') => {
        setIsTranscribing(true);
        setStatus('Đang chuyển giọng nói thành văn bản...');
        try {
            const formData = new FormData();
            formData.append('file', audioBlob, getAudioFilename(audioBlob, mimeType));
            formData.append('language', activeMode.language);

            const response = await apiFetch('/v1/audio/transcriptions', {
                method: 'POST',
                body: formData,
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail || error.error || response.statusText);
            }

            const data = await response.json();
            const text = data.text?.trim() || '';
            if (!text) {
                setStatus('Chưa nghe rõ. Hãy thử nói gần micro hơn.');
                return;
            }

            setTranscript(text);
            setStatus('Đã có transcript. Đang gửi AI chấm điểm...');
            await submitForScoring(text);
        } catch (error) {
            setStatus(`Lỗi ghi âm: ${error.message}`);
        } finally {
            setIsTranscribing(false);
        }
    };

    const startRecording = async () => {
        if (!window.isSecureContext) {
            setStatus('Microphone cần HTTPS hoặc localhost. Hãy mở bằng http://localhost:8000/playground hoặc HTTPS.');
            return;
        }
        if (!navigator.mediaDevices?.getUserMedia) {
            setStatus('Trình duyệt này không mở được microphone. Hãy thử Chrome/Safari hoặc dùng nút tải file audio.');
            return;
        }
        if (!window.MediaRecorder) {
            setStatus('Trình duyệt này không hỗ trợ MediaRecorder. Hãy dùng Chrome/Safari hoặc tải file audio lên.');
            return;
        }

        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            streamRef.current = stream;

            let options = undefined;
            if (MediaRecorder.isTypeSupported('audio/webm')) {
                options = { mimeType: 'audio/webm' };
            } else if (MediaRecorder.isTypeSupported('audio/mp4')) {
                options = { mimeType: 'audio/mp4' };
            }

            const recorder = new MediaRecorder(stream, options);
            mediaRecorderRef.current = recorder;
            audioChunksRef.current = [];

            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
            audioContextRef.current = audioContext;
            const source = audioContext.createMediaStreamSource(stream);
            const analyser = audioContext.createAnalyser();
            analyser.fftSize = 512;
            source.connect(analyser);

            const dataArray = new Uint8Array(analyser.frequencyBinCount);
            const updateLevel = () => {
                analyser.getByteFrequencyData(dataArray);
                const average = dataArray.reduce((sum, value) => sum + value, 0) / dataArray.length;
                setAudioLevel(Math.min(100, Math.round((average / 255) * 220)));
                animationFrameRef.current = requestAnimationFrame(updateLevel);
            };

            recorder.ondataavailable = (event) => {
                if (event.data.size > 0) audioChunksRef.current.push(event.data);
            };

            recorder.onstop = () => {
                const mimeType = recorder.mimeType || options?.mimeType || 'audio/mp4';
                const audioBlob = new Blob(audioChunksRef.current, { type: mimeType });
                audioChunksRef.current = [];
                cleanupRecording();
                if (audioBlob.size > 0) transcribeAudio(audioBlob, mimeType);
            };

            recorder.start(100);
            setIsRecording(true);
            setFeedback(initialFeedback);
            setStatus('Đang ghi âm...');
            updateLevel();
        } catch (error) {
            cleanupRecording();
            setIsRecording(false);
            if (error.name === 'NotAllowedError' || error.name === 'SecurityError') {
                setMicPermission('denied');
                setStatus('Microphone đang bị chặn. Hãy bấm biểu tượng quyền trên thanh địa chỉ để Allow, hoặc cấp quyền Microphone cho Codex/Chrome trong System Settings.');
            } else if (error.name === 'NotFoundError') {
                setStatus('Không tìm thấy microphone. Hãy kiểm tra thiết bị đầu vào âm thanh.');
            } else {
                setStatus(`Không thể mở microphone: ${error.message}`);
            }
        }
    };

    const stopRecording = () => {
        if (mediaRecorderRef.current?.state === 'recording') {
            mediaRecorderRef.current.stop();
        }
        setIsRecording(false);
    };

    const switchMode = (nextMode) => {
        if (isRecording) stopRecording();
        setMode(nextMode);
        setTranscript('');
        setFeedback(initialFeedback);
        setStatus('');
    };

    const handleAudioFile = async (event) => {
        const file = event.target.files?.[0];
        event.target.value = '';
        if (!file) return;
        setTranscript('');
        setFeedback(initialFeedback);
        await transcribeAudio(file, file.type || 'audio/mp4');
    };

    const isBusy = isRecording || isTranscribing || isScoring;
    const micStateLabel = {
        granted: 'Mic đã được cấp quyền',
        denied: 'Mic đang bị chặn',
        prompt: 'Mic cần cấp quyền',
        unknown: 'Mic chưa xác định quyền',
    }[micPermission] || 'Mic chưa xác định quyền';

    return (
        <main className="min-h-screen bg-[#f7f4ee] text-[#1f2933]">
            <div className="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-4 py-5 sm:px-6 lg:px-8">
                <header className="flex flex-col gap-4 border-b border-[#ded6c8] pb-5 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                        <div className="flex items-center gap-3">
                            <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-[#245c4f] text-white">
                                <Volume2 className="h-5 w-5" />
                            </div>
                            <div>
                                <h1 className="text-2xl font-bold tracking-normal text-[#16221f]">Voice Coach</h1>
                                <p className="text-sm text-[#66736d]">Luyện nói, nhận transcript và phản hồi AI trong một màn hình.</p>
                            </div>
                        </div>
                    </div>

                    <div className="flex rounded-lg border border-[#d7cec0] bg-white p-1 shadow-sm">
                        {Object.entries(MODES).map(([key, item]) => {
                            const Icon = item.icon;
                            return (
                                <button
                                    key={key}
                                    type="button"
                                    onClick={() => switchMode(key)}
                                    className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm font-semibold transition-colors ${
                                        mode === key
                                            ? 'bg-[#245c4f] text-white'
                                            : 'text-[#53615b] hover:bg-[#eef4f1] hover:text-[#16221f]'
                                    }`}
                                >
                                    <Icon className="h-4 w-4" />
                                    {item.label}
                                </button>
                            );
                        })}
                    </div>
                </header>

                <section className="grid flex-1 gap-5 py-5 lg:grid-cols-[0.92fr_1.08fr]">
                    <div className="flex flex-col gap-5">
                        <div className="rounded-lg border border-[#ded6c8] bg-white p-5 shadow-sm">
                            <div className="mb-3 text-xs font-bold uppercase tracking-[0.16em] text-[#7a8a83]">Câu hỏi luyện tập</div>
                            <p className="text-lg font-semibold leading-7 text-[#16221f]">{activeMode.question}</p>
                            <p className="mt-3 text-sm leading-6 text-[#66736d]">{activeMode.hint}</p>
                        </div>

                        <div className="rounded-lg border border-[#ded6c8] bg-white p-5 shadow-sm">
                            <label htmlFor="transcript" className="mb-3 block text-sm font-bold text-[#16221f]">
                                Transcript
                            </label>
                            <textarea
                                id="transcript"
                                value={transcript}
                                onChange={(event) => setTranscript(event.target.value)}
                                placeholder={activeMode.placeholder}
                                className="min-h-[220px] w-full resize-none rounded-md border border-[#d7cec0] bg-[#fbfaf7] p-4 text-base leading-7 text-[#1f2933] outline-none transition focus:border-[#245c4f] focus:ring-4 focus:ring-[#245c4f]/10"
                            />

                            <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                                <div className="flex flex-col gap-3 sm:flex-row">
                                    <button
                                        type="button"
                                        onClick={isRecording ? stopRecording : startRecording}
                                        disabled={isTranscribing || isScoring}
                                        className={`inline-flex items-center justify-center gap-2 rounded-md px-4 py-3 text-sm font-bold transition ${
                                            isRecording
                                                ? 'bg-[#b33a3a] text-white hover:bg-[#972f2f]'
                                                : 'bg-[#245c4f] text-white hover:bg-[#1d4b41]'
                                        } disabled:cursor-not-allowed disabled:opacity-60`}
                                    >
                                        {isRecording ? <Square className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
                                        {isRecording ? 'Dừng ghi âm' : 'Ghi âm'}
                                    </button>

                                    <label className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-md border border-[#cfc5b6] bg-white px-4 py-3 text-sm font-bold text-[#245c4f] transition hover:bg-[#eef4f1]">
                                        <Upload className="h-4 w-4" />
                                        Tải file audio
                                        <input
                                            type="file"
                                            accept="audio/*"
                                            className="hidden"
                                            onChange={handleAudioFile}
                                            disabled={isBusy}
                                        />
                                    </label>
                                </div>

                                <button
                                    type="button"
                                    onClick={() => submitForScoring()}
                                    disabled={!transcript.trim() || isBusy}
                                    className="inline-flex items-center justify-center gap-2 rounded-md bg-[#16221f] px-4 py-3 text-sm font-bold text-white transition hover:bg-[#2b3a35] disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                    {isScoring ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                                    Chấm điểm
                                </button>
                            </div>

                            <div className="mt-4 h-2 overflow-hidden rounded-full bg-[#e7dfd3]">
                                <div
                                    className={`h-full rounded-full transition-all duration-100 ${isRecording ? 'bg-[#2a8c78]' : 'bg-[#c7bda9]'}`}
                                    style={{ width: `${isRecording ? Math.max(audioLevel, 8) : 0}%` }}
                                />
                            </div>

                            {status && (
                                <div className={`mt-4 flex items-start gap-2 rounded-md px-3 py-2 text-sm ${
                                    micPermission === 'denied'
                                        ? 'bg-[#fff3e8] text-[#9a4b16]'
                                        : 'bg-[#eef4f1] text-[#245c4f]'
                                }`}>
                                    {isTranscribing || isScoring ? <Loader2 className="mt-0.5 h-4 w-4 animate-spin" /> : micPermission === 'denied' ? <AlertCircle className="mt-0.5 h-4 w-4" /> : <CheckCircle2 className="mt-0.5 h-4 w-4" />}
                                    {status}
                                </div>
                            )}

                            <div className="mt-3 text-xs leading-5 text-[#7a6b58]">
                                {micStateLabel}. Nếu đang dùng in-app browser và bị chặn, cấp quyền Microphone cho Codex trong macOS System Settings, rồi refresh trang.
                            </div>
                        </div>
                    </div>

                    <section className="rounded-lg border border-[#ded6c8] bg-white p-5 shadow-sm">
                        <div className="mb-3 flex items-center justify-between gap-3">
                            <div>
                                <div className="text-xs font-bold uppercase tracking-[0.16em] text-[#7a8a83]">Feedback từ AI</div>
                                <h2 className="mt-1 text-xl font-bold tracking-normal text-[#16221f]">Kết quả đánh giá</h2>
                            </div>
                            {(isTranscribing || isScoring) && <Loader2 className="h-5 w-5 animate-spin text-[#245c4f]" />}
                        </div>
                        <div className="min-h-[520px] whitespace-pre-wrap rounded-md border border-[#ebe4d9] bg-[#fbfaf7] p-5 text-[15px] leading-7 text-[#26332f]">
                            {feedback}
                        </div>
                    </section>
                </section>
            </div>
        </main>
    );
}
