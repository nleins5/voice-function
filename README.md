# Voice Coach & AI Gateway

A powerful, high-fidelity AI-powered Voice Coach and Multi-Provider AI Routing Gateway. This project provides real-time spoken English training and mock interview evaluations by transcribing speech and utilizing state-of-the-art LLMs to analyze content quality, fluency, pronunciation, grammar, vocabulary, and delivery metrics.

---

## 🌟 Key Features

- **Voice Recording & Audio Processing:** Built-in web audio recorder with support for uploading raw audio files.
- **Detailed Speech Metrics:** Analyzes pauses, speech speed, hesitations, and repeated words.
- **Dual Training Modes:**
  - **Interview Coach (Phỏng vấn):** Simulates a high-standard senior recruiter evaluation, providing a mock hiring recommendation and overall score.
  - **English Coach (English Speaking):** Acts as an elite IELTS/CEFR examiner focusing on natural vocabulary, structural transitions, and grammar corrections.
- **Brutally Honest AI Feedback:** Point-by-point diagnostic scoring across 6 key metrics, providing strengths, specific weaknesses, and a perfect native rewrite of the student's answer.
- **Resilient AI Routing & Failover:** Powered by an underlying AI gateway structure featuring robust multi-provider API routing, automatic fallback, and retries.

---

## 🛠️ Technology Stack

- **Frontend:** React 18, Vite, Tailwind CSS v3, Lucide Icons, and Web Audio API.
- **Backend:** FastAPI (Python 3.11+), Uvicorn, Pydantic, HTTPX, and OpenAI SDK.
- **Deployment:** Zero-config Vercel deployment using Serverless Functions (`api/index.py` handles backend routing via `vercel.json` rewrites).

---

## 📂 Project Structure

```text
├── app/                  # FastAPI backend source code
│   ├── api/              # API router endpoints
│   ├── core/             # AI Prompts & configuration
│   └── main.py           # FastAPI entry point
├── api/
│   └── index.py          # Vercel Serverless Function entry point
├── ui/                   # Vite + React Frontend
│   ├── dist/             # Production build output
│   ├── src/              # React components & UI pages
│   └── package.json
├── package.json          # Root scripts for build/run management
└── vercel.json           # Vercel deployment configuration
```

---

## ⚡ Quick Start & Development

### 1. Prerequisite Configuration (`.env`)

Create a `.env` file in the root directory (or use `.env.local` for local development):

```env
# Cloudflare (Used for AI Gateway/Workers)
CLOUDFLARE_ACCOUNT_ID="your_cloudflare_account_id"
CLOUDFLARE_API_KEY="your_cloudflare_api_key"

# AI Provider API Keys
GROQ_API_KEY="your_groq_api_key"
NVIDIA_API_KEY="your_nvidia_api_key"

# Frontend-Backend Protection Key
VITE_GATEWAY_KEY="voice_function_secret_key"

# Environment Settings
DISABLE_DATABASE="1"
NODE_VERSION="22.11.0"
PYTHON_VERSION="3.11.0"
```

### 2. Local Setup & Run

The project uses `npm` workspaces to manage both frontend and backend tasks.

#### Option A: Quickstart via Root Scripts
Install Node.js dependencies and start the backend/frontend together:

```bash
# Install dependencies
npm install

# Start the uvicorn development server
npm run dev:voice
```

The backend API will run on `http://localhost:8000`.

#### Option B: Standalone Manual Run

**Run Backend (Python):**
Ensure you have a Python virtual environment activated:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Run Frontend (Node):**
```bash
cd ui
npm install
npm run dev
```

---

## 🚀 Production Deployment (Vercel)

This repository is optimized for one-click deployment to **Vercel**:

1. Push this repository to GitHub.
2. Import the project into your Vercel Dashboard.
3. Configure the **Environment Variables** in Vercel to match your `.env` values (listed above).
4. Deploy! Vercel will automatically read `vercel.json`, build the React UI inside `ui/`, and set up the FastAPI serverless endpoint at `/api/index.py`.

---

## 🤝 Integration Guide for Boss

To integrate this Voice Coach engine into another existing project:

1. **API Integration:** The backend exposes a simple endpoint `/v1/chat/unified` that takes user transcriptions/metrics and evaluates them dynamically.
2. **Audio Transcription:** The `/v1/audio/transcriptions` endpoint handles direct file transcription and computes pause/hesitation metrics.
3. **Frontend Component:** The page `ui/src/pages/VoiceCoach.jsx` is highly modular and styled with Tailwind CSS, meaning it can easily be copied and integrated into any React/Next.js dashboard.
