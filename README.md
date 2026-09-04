# Observability Agent

This project is an observability agent built to help developers monitor application health, investigate issues faster, and ask questions about system behavior in plain language. It combines a FastAPI backend with an AI-powered chat workflow so teams can query logs, diagnostics, and service context without manually digging through multiple tools.

## What it does

- Provides a developer-facing chat interface for observability questions
- Connects to LLM providers for reasoning over operational context
- Structures agent workflows for troubleshooting and investigation
- Helps speed up root-cause analysis and support conversations

## Installation

### 1. Prerequisites

- Python 3.12+ (the current environment is using Python 3.14.6)
- Git
- A valid API key for either OpenAI or Google Generative AI

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root with one or more of the following:

```env
OPENAI_API_KEY=your_openai_key
GOOGLE_GENAI_API_KEY=your_google_key
```

You can also set the default model values in `app/core/config.py` if needed.

### 5. Run the app

```bash
uvicorn app.main:app --reload
```

Then open the API in your browser or client at:

```text
http://127.0.0.1:8000/docs
```

## Notes

This app is intended to help developers act more quickly during incidents by turning operational questions into guided AI-assisted investigation workflows.
