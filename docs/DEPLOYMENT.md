# FraudLens Deployment Guide

This guide details how to deploy FraudLens from GitHub with the **FastAPI backend on Render** (as a Docker Web Service) and the **Vite frontend on Vercel**.

---

## 1. Architecture Overview

```mermaid
flowchart LR
    subgraph Browser["User Browser"]
        Client["Vite React SPA"]
    end

    subgraph Vercel["Vercel Edge Network"]
        Static["Static Assets (HTML/JS/CSS)"]
    end

    subgraph Render["Render Cloud"]
        FastAPI["Docker Web Service\n(FastAPI / Uvicorn on $PORT)"]
        Tesseract["Tesseract OCR Engine\n(eng, hin)"]
        PDFWorker["Isolated pypdf Worker\n(Subprocess)"]
    end

    subgraph External["External Services (Server-Side Only)"]
        Gemini["Google Gemini API\n(gemini-3.5-flash-lite)"]
        SafeBrowsing["Google Safe Browsing API\n(v5 urls.search)"]
    end

    Client -->|HTTPS Static Load| Static
    Client -->|API Requests (VITE_API_BASE_URL)| FastAPI
    FastAPI -->|Local Subprocess| Tesseract
    FastAPI -->|Local Subprocess| PDFWorker
    FastAPI -->|HTTPS (AI_API_KEY)| Gemini
    FastAPI -->|HTTPS with User Consent| SafeBrowsing
```

---

## 2. Render Deployment (Backend Docker Web Service)

### Service Setup
1. Log in to [Render Dashboard](https://dashboard.render.com/) and click **New +** > **Web Service**.
2. Connect your GitHub repository (`FraudLens`).
3. Select the branch: `deploy/portfolio-live` (or `main` when merged).

### Dashboard Configuration Settings

| Setting | Value | Notes |
| :--- | :--- | :--- |
| **Name** | `fraudlens-api` | Or your preferred service name |
| **Region** | Choose nearest (e.g. `Frankfurt`, `Oregon`, `Singapore`) | Keep close to target users |
| **Branch** | `deploy/portfolio-live` | Or your target branch |
| **Root Directory** | `backend` *(recommended)* or leave blank | If `backend`, uses `backend/Dockerfile`. If blank, uses root `Dockerfile`. |
| **Runtime** | `Docker` | Render builds using the Dockerfile |
| **Instance Type** | `Starter` ($7/mo) or `Free` | Starter recommended to avoid free-tier cold starts |
| **Dockerfile Path** | `Dockerfile` (if root dir is `backend`) or `backend/Dockerfile` | Both Dockerfiles are configured |
| **Docker Context** | `.` | Current directory of root directory |
| **Health Check Path** | `/api/v1/health` | Returns `200 OK` (`{"status": "ok", "service": "fraudlens-api"}`). Also supports `/health`. |
| **Auto-Deploy** | `Yes` | Automatically deploys new commits pushed to the branch |

### Render Environment Variables

| Variable | Value | Required? | Purpose / Description |
| :--- | :--- | :--- | :--- |
| `ENVIRONMENT` | `production` | **Yes** | Disables Swagger `/docs` and enables production mode |
| `ALLOWED_ORIGINS` | `https://<your-app>.vercel.app,http://localhost:5173,http://127.0.0.1:5173` | **Yes** | Comma-separated list of allowed CORS origins. Localhost is automatically preserved. |
| `AI_PROVIDER` | `gemini` | **Yes** | Enables Google Gemini integration (`gemini` or `none`) |
| `AI_MODEL` | `gemini-3.5-flash-lite` | **Yes** | Model ID for structured analysis |
| `AI_API_KEY` | `AIzaSy...` | **Yes** | Dedicated Gemini API key generated in Google AI Studio |
| `SAFE_BROWSING_API_KEY` | `AIzaSy...` | Optional | Google Safe Browsing API key for URL reputation lookups |
| `SAFE_BROWSING_VERSION` | `v5` | Optional | Safe Browsing API protocol version (`v5` or `v4`) |

> [!NOTE]
> Render automatically injects `PORT` (e.g. `10000`). The Docker container launches Uvicorn via `sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"`, binding dynamically to `0.0.0.0:$PORT`.

---

## 3. Vercel Deployment (Frontend Vite SPA)

### Project Setup
1. Log in to [Vercel Dashboard](https://vercel.com/) and click **Add New...** > **Project**.
2. Import your GitHub repository (`FraudLens`).

### Dashboard Configuration Settings

| Setting | Value | Notes |
| :--- | :--- | :--- |
| **Project Name** | `fraudlens` | Generates `https://fraudlens.vercel.app` |
| **Framework Preset** | `Vite` | Auto-detects Vite configuration |
| **Root Directory** | `frontend` | **Crucial:** Click "Edit" and select the `frontend` folder |
| **Build Command** | `npm run build` | Runs `tsc -b && vite build` |
| **Output Directory** | `dist` | Default build output folder |
| **Install Command** | `npm install` | Installs dependencies |

### Vercel Environment Variables

| Variable | Value | Environments | Notes |
| :--- | :--- | :--- | :--- |
| `VITE_API_BASE_URL` | `https://fraudlens-api.onrender.com` | Production, Preview, Development | **No trailing slash.** Point to your live Render backend URL. |

> [!IMPORTANT]
> Provider keys (`AI_API_KEY`, `SAFE_BROWSING_API_KEY`) must **NEVER** be added to Vercel. They are kept purely server-side on Render.

---

## 4. Security & Public Exposure Advisory (Rate Limiting)

> [!WARNING]
> **Provider-Backed Routes Rate Limiting Notice:**
> Inspecting the backend implementation confirms that **neither `/api/v1/analyze/text` (Gemini API) nor `/api/v1/inspect/url/reputation` (Google Safe Browsing API) has route-level or IP-level rate limiting middleware** in the application layer.
> - While Safe Browsing caches queries via SHA-256 hashes, distinct URLs bypass the cache.
> - If deployed publicly without access controls or rate limits, open internet traffic or automated crawlers could exhaust your Google AI Studio free tier quota (15 RPM / 1M TPM) or generate unexpected API costs.
>
> **Recommendations for Public Use:**
> 1. **Portfolio / Demo Mode**: Only share your deployment link privately or with evaluators.
> 2. **Cloudflare / CDN Rate Limiting**: If placing a custom domain in front of Render, configure Cloudflare Web Application Firewall (WAF) rate limiting (e.g., 5 requests per minute per IP on `/api/v1/analyze/*`).
> 3. **Future Hardening**: Consider adding `slowapi` with in-memory or Redis-backed sliding window rate limiting before opening the endpoints to untrusted public traffic.

---

## 5. Verification Checklist After Deployment

Once both services are deployed:

1. **Backend Health Check**:
   ```bash
   curl -i https://<your-render-service>.onrender.com/api/v1/health
   # Expected: HTTP 200 OK, {"status":"ok","service":"fraudlens-api"}
   ```

2. **Capabilities Verification**:
   ```bash
   curl -s https://<your-render-service>.onrender.com/api/v1/capabilities | jq .
   # Verify:
   # "text_analysis": true
   # "screenshot_extraction": true (Tesseract is ready)
   # "ocr_languages": ["eng", "hin"]
   # "ocr_prerequisite_status": "ready"
   # "ai_configuration": "present" (when AI_API_KEY is configured)
   ```

3. **CORS Check**:
   ```bash
   curl -i -X OPTIONS https://<your-render-service>.onrender.com/api/v1/capabilities \
     -H "Origin: https://<your-app>.vercel.app" \
     -H "Access-Control-Request-Method: GET"
   # Expected: access-control-allow-origin: https://<your-app>.vercel.app
   ```

4. **Frontend UI Test**:
   - Open `https://<your-app>.vercel.app` in your browser.
   - Verify header indicators:
     - Backend Connection: **Connected** (green)
     - Gemini AI Model: **Configured** (green)
     - Tesseract OCR: **Ready (eng, hin)**
   - Test Text Analysis with a sample message.
   - Test Screenshot Extraction with an image.
   - Test PDF Document Extraction with a sample PDF.
   - Test URL Structure Inspection (local) and URL Reputation (requires explicit consent checkbox).
