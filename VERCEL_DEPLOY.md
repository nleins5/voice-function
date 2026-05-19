# Vercel deployment helper for Free AI Gateway

## Quick Start

```bash
# Install Vercel CLI
npm i -g vercel

# Login to Vercel
vercel login

# Deploy to preview
vercel

# Deploy to production
vercel --prod
```

## Environment Variables

Đặt các environment variables trên Vercel Dashboard:

### Required:
- `DATABASE_URL` - PostgreSQL connection string (Prisma)
- `ADMIN_SECRET` - Secret key for admin endpoints

### API Keys (Free Providers):
- `GROQ_API_KEY` - Groq API key
- `GEMINI_API_KEY` - Google Gemini API key
- `GITHUB_TOKEN` - GitHub Models token
- `CEREBRAS_API_KEY` - Cerebras API key
- `SAMBANOVA_API_KEY` - SambaNova API key
- `DEEPSEEK_API_KEY` - DeepSeek API key
- `MISTRAL_API_KEY` - Mistral AI API key
- `ANTHROPIC_API_KEY` - Anthropic/Claude API key

### Optional:
- `OPENAI_API_KEY` - OpenAI API key
- `PERPLEXITY_API_KEY` - Perplexity API key
- `COHERE_API_KEY` - Cohere API key
- `XAI_API_KEY` - xAI/Grok API key
- `TOGETHER_API_KEY` - Together AI API key
- `HUGGINGFACE_API_KEY` - HuggingFace API key
- `CLOUDFLARE_API_KEY` - Cloudflare AI API key
- `OPENROUTER_API_KEY` - OpenRouter API key
- `NVIDIA_API_KEY` - NVIDIA NIM API key
- `FREETHEAI_API_KEY` - FreeTheAI API key

## Build Settings

- **Framework Preset**: None
- **Build Command**: `cd ui && npm run build`
- **Output Directory**: `ui/dist`
- **Install Command**: `npm install`

## Structure

```
/
├── app/              # FastAPI backend
│   ├── main.py       # Entry point
│   ├── api/          # API routes
│   ├── services/     # Router, RAG services
│   └── core/         # Providers, state
├── ui/               # Frontend (Vite + React)
│   ├── src/
│   └── dist/         # Built files
├── vercel.json       # Vercel config
└── requirements.txt  # Python deps
```

## Troubleshooting

### Python version
Vercel automatically detects Python from `requirements.txt`.

### Database migrations
Run migrations manually:
```bash
vercel exec "cd /vercel/path0 && python -m prisma migrate deploy"
```

### Cold start
FastAPI on Vercel uses serverless functions. First request may be slower.