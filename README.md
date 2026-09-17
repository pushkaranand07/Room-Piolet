# RoomPilot

RoomPilot is a local AI meeting-room booking assistant. Users describe a meeting in natural language, and the application extracts the booking details, finds suitable rooms, checks availability, and stores the reservation in a JSON data file.

The project uses a React and Vite frontend, a Flask backend, LangGraph for workflow orchestration, and a selectable LLM provider. Gemini is the current live provider; a deterministic FakeLLM is available for local UI and automated tests.

## Features

- Natural-language room booking requests
- Multi-turn clarification for incomplete requests
- Date and time parsing, including relative dates such as `tomorrow`
- Capacity and equipment matching
- Flexible equipment matching, such as `projector` and `4K Projector`
- Booking conflict detection
- Alternative room search
- Flask session-based conversation history
- JSON room and booking storage for local development
- Responsive React interface
- Interactive room options, confirmation controls, receipts, booking lists, and booking details
- Date-only calendar control for missing dates; time remains natural-language input
- LocalStorage chat restoration during frontend development
- Application logs stored in `logs/`

## Architecture

```text
Browser
  |
  | React/Vite frontend served from frontend/dist
  v
Flask application: src/app.py
  |
  v
LangGraph workflow: src/booking_agent/workflow.py
  |
  +--> Gemini or Groq model for request parsing and response text
  +--> data/rooms.json for room matching
  +--> data/bookings.json for availability and reservations
  +--> logs/ for diagnostics
```

### Main components

| Component | Location | Responsibility |
| --- | --- | --- |
| React UI | `frontend/src/main.jsx` | Chat interface and API requests |
| Flask app | `src/app.py` | Serves the frontend and exposes the booking API |
| Workflow | `src/booking_agent/workflow.py` | Defines LangGraph nodes and transitions |
| Agent nodes | `src/booking_agent/nodes.py` | Parses, searches, checks, and books |
| Request schema | `src/booking_agent/schemas.py` | Defines parsed booking fields |
| Room service | `src/mock_apis/room_services.py` | Loads and filters rooms |
| Booking service | `src/mock_apis/booking_services.py` | Checks conflicts and saves bookings |
| Room data | `data/rooms.json` | Local room inventory |
| Booking data | `data/bookings.json` | Local reservations |

## Requirements

- Windows PowerShell, macOS, or Linux
- Python 3.11 or newer
- Node.js and npm
- A Gemini API key for live verification, or no API key when using `LLM_PROVIDER=fake`

Conda is optional. The commands below use the existing Windows virtual environment at `.venv`.

## Windows Quick Start

Open PowerShell in the project directory:

```powershell
cd "C:\coding\fun project\ai_chat_bot_booking"
```

### First-time setup

Create and activate the virtual environment if it does not already exist:

```powershell
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

Install Python and frontend dependencies:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
npm install
```

Create `.env` in the project root. You can copy `.env-example` and replace the placeholder values:

```powershell
Copy-Item .env-example .env
```

At minimum, configure these values for live Gemini use:

```env
PROJECT_NAME="RoomPilot"
PYTHONPATH="./src"
FLASK_APP="src.app"
FLASK_HOST="127.0.0.1"
FLASK_PORT="5001"
FLASK_SECRET_KEY="replace-with-a-local-secret"

LLM_PROVIDER="gemini"
GEMINI_API_KEY="your-gemini-api-key"
GEMINI_MODEL_NAME="gemini-3.6-flash"
TEMPERATURE="0.0"

LANGCHAIN_TRACING_V2="false"
LANGCHAIN_ENDPOINT=""
LANGCHAIN_API_KEY=""
```

Never commit `.env` or paste API keys into chat, source files, screenshots, or logs. The current working Gemini model is `gemini-3.6-flash`; model availability and quota depend on the Google account.

### Start the production-style local application

Build the React frontend first:

```powershell
npm run build
```

Start Flask:

```powershell
python -m flask --app src.app run --host 127.0.0.1 --port 5001 --no-debugger --no-reload
```

Keep this terminal open. Open the application in Chrome:

```text
http://localhost:5001/
```

If the page was already open, press `Ctrl+Shift+R` after rebuilding or restarting Flask.

### Subsequent starts

After the first-time setup, use:

```powershell
cd "C:\coding\fun project\ai_chat_bot_booking"
.\.venv\Scripts\Activate.ps1
npm run build
python -m flask --app src.app run --host 127.0.0.1 --port 5001 --no-debugger --no-reload
```

For frontend work, use the Vite development server instead:

```powershell
npm run dev
```

Open `http://localhost:5173/`. Vite proxies `/api` requests to Flask on port `5001` and provides hot reload. The Flask production-style local workflow serves the built frontend from `frontend/dist` on `http://localhost:5001/`.

For UI work without Gemini quota, set `LLM_PROVIDER="fake"` in `.env`, restart Flask, and use `npm run dev`.

### Vercel deployment

The repository includes `vercel.json`, `api/index.py`, and `pyproject.toml` for Vercel. The Python runtime is constrained to Python 3.11 or 3.12 so `pydantic-core` uses a prebuilt wheel instead of attempting a Rust build under Python 3.14.

Set these Vercel environment variables before deploying:

```text
PROJECT_NAME
FLASK_SECRET_KEY
TEMPERATURE
LLM_PROVIDER
GEMINI_API_KEY
GEMINI_MODEL_NAME
```

Vercel functions have ephemeral storage. The local JSON booking store and SQLite checkpoint database are suitable for demos and preview testing, but durable deployment requires an external database or storage service.

### One-shot live verification

Use this only after setting `LLM_PROVIDER="gemini"` and a valid `GEMINI_API_KEY`:

```powershell
\.venv\Scripts\python.exe -m src.app
```

In a second PowerShell window:

```powershell
\.venv\Scripts\python.exe tests/smoke_test.py
```

The live check should search and present rooms, collect a name, require explicit confirmation, write a booking receipt, and reject an automatic booking in a fresh session. Gemini quota errors (`429`) are account-level failures and cannot be fixed by the frontend.

## Testing the API

Check that the API is alive:

```powershell
Invoke-RestMethod http://127.0.0.1:5001/api/booking
```

Expected initial response:

```json
{
  "messages": []
}
```

Send a booking request:

```powershell
$body = @{
  user_input = "Book a meeting room on 2026-09-20 at 10:00 AM for 2 hours for 6 people with a projector. My name is Alex."
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://127.0.0.1:5001/api/booking" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

The browser normally keeps the session cookie automatically. When testing with PowerShell, use a `WebRequestSession` if multiple requests must share the same conversation.

Reset the current conversation:

```powershell
Invoke-WebRequest http://127.0.0.1:5001/reset
```

The reset route clears the Flask session and returns to the React interface.

## Writing Booking Requests

For the most reliable parsing, include:

- Full date, preferably `YYYY-MM-DD`
- Time with `AM` or `PM`
- Duration
- Number of attendees
- Equipment, if required
- Booker name

Example:

```text
Book a meeting room on 2026-09-20 at 10:00 AM for 2 hours for 6 people with a projector. My name is Alex.
```

Relative dates are also supported:

```text
Book a meeting room tomorrow from 10:00 AM to 12:00 PM for 6 people with a projector. My name is Alex.
```

The workflow selects the first available matching room and saves the booking automatically. Use a different date and time when repeating a test after a previous reservation has been stored.

## API Routes

| Route | Method | Purpose |
| --- | --- | --- |
| `/` | GET | React application |
| `/api/booking` | GET | Read the current conversation |
| `/api/booking` | POST | Process a booking request |
| `/reset` | GET | Clear the current session and return to the React app |
| `/booking` | GET/POST | Legacy server-rendered interface |

The React frontend uses `/api/booking`. The older `/booking` route remains for compatibility but is not the primary interface.

The POST response may include a structured `ui` payload. The React frontend renders these payload types:

- `room_options`
- `confirmation`
- `booking_receipt`
- `cancellation_receipt`
- `booking_list`
- `booking_detail`

## Data Files

### Room record

```json
{
  "id": 2,
  "name": "Tech Hub",
  "capacity": 12,
  "equipments": [
    "4K Projector",
    "Video Conferencing",
    "Charging Stations"
  ]
}
```

### Booking record

```json
{
  "2": [
    {
      "room_id": 2,
      "start_time": "2026-09-20T10:00:00",
      "end_time": "2026-09-20T12:00:00",
      "booked_by": "Alex"
    }
  ]
}
```

Bookings are grouped by room ID. The JSON files are intended for local development and do not provide database transactions or multi-user locking.

## Searching the Project

Search source files with ripgrep:

```powershell
rg --files -g "! .venv/**" -g "! node_modules/**"
```

Search for routes and API calls:

```powershell
rg "/api/booking|/reset|/booking" src frontend
```

Search the workflow:

```powershell
rg "add_node|add_edge|conditional_edges|parse_request|confirm_booking" src/booking_agent
```

Search room and booking logic:

```powershell
rg "load_rooms|find_matching|load_bookings|check_time_conflict|book_room" src
```

Search errors in logs:

```powershell
rg -i "error|exception|failed|traceback|400|500" logs
```

List rooms with capacity of at least 10:

```powershell
$rooms = Get-Content data/rooms.json -Raw | ConvertFrom-Json
$rooms | Where-Object { $_.capacity -ge 10 } | Format-Table id, name, capacity
```

List current bookings:

```powershell
Get-Content data/bookings.json
```

## Troubleshooting

### Chrome shows a blank page

Confirm Flask is running on port `5001`, then press `Ctrl+Shift+R` in Chrome. Also confirm that `npm run build` completed successfully.

### `Unexpected token '<'` or `<!doctype html>` appears

This means the frontend received an HTML Flask error page instead of JSON. Check the latest log file:

```powershell
$latest = Get-ChildItem logs | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Get-Content $latest.FullName | Select-Object -Last 80
```

Restart Flask after fixing the reported backend error.

### Gemini model or quota errors

Check the active provider without printing secrets:

```powershell
Get-Content .env | Where-Object { $_ -match '^(LLM_PROVIDER|GEMINI_MODEL_NAME)=' }
```

`429 You exceeded your current quota` means the Google account quota is exhausted or billing is required. Wait for the quota reset or enable an appropriate billing/quota plan. Restart Flask after changing `.env`.

### Groq model errors

List models available to the configured Groq account:

```powershell
python -c "from groq import Groq; from src.config import GROQ_API_KEY; print('\n'.join(model.id for model in Groq(api_key=GROQ_API_KEY).models.list().data))"
```

Set `GROQ_MODEL_NAME` in `.env` to one of the returned model IDs, then restart Flask.

### Port 5001 is already in use

Find the process using the port:

```powershell
Get-NetTCPConnection -LocalPort 5001 -State Listen | Select-Object OwningProcess
```

Use another port if necessary:

```powershell
python -m flask --app src.app run --host 127.0.0.1 --port 5002 --no-debugger --no-reload
```

Then open `http://localhost:5002/`.

### A previous booking blocks a test

Use a different date and time. To inspect the stored records:

```powershell
Get-Content data/bookings.json
```

Do not delete booking data unless you intentionally want to reset the local test database.

## Documentation

- [Project documentation](docs/Project_Documentation.md)
- [System architecture diagram](docs/system_architecture.svg)
- [Workflow diagram](docs/flowchart.svg)

## Production Considerations

This project is a local prototype. Before production use:

- Replace JSON storage with a transactional database
- Add authentication and authorization
- Add request validation and rate limiting
- Protect secrets with a deployment secret manager
- Configure HTTPS and security headers
- Add automated tests and monitoring
- Use a production WSGI server instead of Flask's development server

Built with React, Vite, Flask, LangGraph, LangChain, Gemini, Groq, and Pydantic.
