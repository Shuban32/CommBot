# backend/main.py

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse # To serve audio files
from contextlib import asynccontextmanager
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service # Keep import just in case
import uvicorn
import logging
import time
import os # For reading environment variables
import uuid # For unique filenames
from pydantic import BaseModel # For request body validation

# Prometheus imports
from prometheus_client import Counter, Histogram, make_asgi_app, REGISTRY, Gauge

# CORS Middleware import
from fastapi.middleware.cors import CORSMiddleware

# Import scraper functions
# --- Import ALL scraper functions ---
from scraper import (
    scrape_live_matches,
    scrape_past_matches,
    scrape_match_commentary # Import the new function
)

# Import Llama for LLM
from llama_cpp import Llama

# Import Coqui TTS
try:
    from TTS.api import TTS as CoquiTTS
except ImportError:
    logging.error("Coqui TTS library not found. Please install it: pip install TTS")
    CoquiTTS = None # Define as None if import fails

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Prometheus Metrics ---
# Basic HTTP Metrics
REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total number of HTTP requests',
    ['method', 'endpoint']
)
REQUEST_LATENCY = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint']
)
# Scraper Metrics
MATCHES_FOUND = Gauge(
    'commentary_matches_found_total',
    'Number of matches found by scraper',
    ['match_type'] # live or past
)
SCRAPER_ERRORS = Counter(
    'commentary_scraper_errors_total',
    'Total number of scraper errors encountered',
    ['match_type']
)
# NEW: Commentary Scrape Time
COMMENTARY_SCRAPE_TIME = Histogram(
    'commentary_scrape_duration_seconds',
    'Time taken to scrape commentary for a specific match'
)
# Component Status Metrics
WEBDRIVER_STATUS = Gauge(
    'commentary_webdriver_status',
    'Status of the Selenium WebDriver (1=OK, 0=Error/Not Initialized)'
)
LLM_LOAD_STATUS = Gauge(
     'commentary_llm_load_status',
     'Status of the LLM loading (1=Loaded, 0=Failed/Not Loaded)'
)
TTS_LOAD_STATUS = Gauge(
     'commentary_tts_load_status',
     'Status of the TTS model loading (1=Loaded, 0=Failed/Not Loaded)'
)
# AI Generation Metrics
LLM_GENERATE_TIME = Histogram(
    'commentary_llm_generate_duration_seconds',
    'Time taken for LLM to generate commentary'
)
TTS_SYNTHESIS_TIME = Histogram(
    'commentary_tts_synthesis_duration_seconds',
    'Time taken for TTS to synthesize audio'
)
# Feedback Metrics
FEEDBACK_COUNT = Counter(
    'commentary_feedback_submissions_total',
    'Total number of feedback submissions'
)
FEEDBACK_SCORE = Histogram(
     'commentary_feedback_score',
     'Distribution of feedback scores (e.g., 1-5)',
     buckets=(1, 2, 3, 4, 5) # Buckets for a 1-5 score
)
DRIFT_SCORE = Histogram(
    'commentary_drift_score_negative_feedback',
    'Score indicating potential drift based on negative feedback'
)


# --- Global Variables ---
driver = None
llm = None
tts = None

# --- Lifespan Manager (Startup & Shutdown Logic) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global driver, llm, tts
    logging.info("Application startup sequence initiated...")

    # --- 1. Initialize WebDriver ---
    logging.info("Initializing Selenium WebDriver...")
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    try:
        driver = webdriver.Chrome(options=chrome_options)
        logging.info("Selenium WebDriver initialized successfully.")
        WEBDRIVER_STATUS.set(1)
    except Exception as e:
        logging.error(f"Failed to initialize WebDriver: {e}", exc_info=True)
        driver = None
        WEBDRIVER_STATUS.set(0)

    # --- 2. Load LLM Model ---
    logging.info("Loading LLM model...")
    llm_model_path = os.getenv("LLM_MODEL_PATH")
    n_gpu_layers_str = os.getenv("N_GPU_LAYERS", "0")
    n_ctx_str = os.getenv("N_CTX", "4096")
    chat_format = "mistral-instruct" # Assuming newer llama-cpp-python supports this
    if not llm_model_path:
         logging.warning("LLM_MODEL_PATH environment variable not set. LLM will be disabled.")
         LLM_LOAD_STATUS.set(0)
         llm = None
    elif not os.path.exists(llm_model_path):
        logging.error(f"LLM model file not found at path: {llm_model_path}")
        LLM_LOAD_STATUS.set(0)
        llm = None
    else:
        try:
            n_gpu_layers = int(n_gpu_layers_str)
            n_ctx = int(n_ctx_str)
            logging.info(f"Attempting to load Llama model from: {llm_model_path}")
            logging.info(f"GPU Layers: {n_gpu_layers}, Context Size: {n_ctx}, Chat Format: {chat_format}")
            start_load_time = time.time()
            llm = Llama(model_path=llm_model_path, n_gpu_layers=n_gpu_layers, n_ctx=n_ctx, chat_format=chat_format, verbose=True)
            load_duration = time.time() - start_load_time
            logging.info(f"LLM model loaded successfully in {load_duration:.2f} seconds.")
            LLM_LOAD_STATUS.set(1)
        except Exception as e:
            if "invalid chat format" in str(e).lower() or isinstance(e, KeyError) and chat_format in str(e):
                 logging.error(f"Failed to load LLM: Invalid or unsupported chat format '{chat_format}' for this llama-cpp-python version. Try 'llama-2' or upgrade. Error: {e}", exc_info=True)
            else:
                 logging.error(f"Failed to load LLM model: {e}", exc_info=True)
            llm = None
            LLM_LOAD_STATUS.set(0)

    # --- 3. Load TTS Model ---
    logging.info("Loading TTS model...")
    tts_model_name = os.getenv("TTS_MODEL_NAME")
    tts_model_path = os.getenv("TTS_MODEL_PATH")
    tts_config_path = os.getenv("TTS_CONFIG_PATH")
    static_dir = "/app/static"
    os.makedirs(static_dir, exist_ok=True)
    logging.info(f"Static directory for audio: {static_dir}")
    if CoquiTTS is None:
        logging.error("CoquiTTS library failed to import. TTS is disabled.")
        tts = None
        TTS_LOAD_STATUS.set(0)
    elif tts_model_path and tts_config_path: # Fine-tuned
        if not os.path.exists(tts_model_path) or not os.path.exists(tts_config_path):
             logging.error(f"Fine-tuned TTS model/config path not found.")
             tts = None
             TTS_LOAD_STATUS.set(0)
        else:
             logging.info(f"Attempting to load fine-tuned TTS model from: {tts_model_path}")
             try:
                 start_load_time = time.time()
                 tts = CoquiTTS(model_path=tts_model_path, config_path=tts_config_path, progress_bar=False, gpu=False)
                 load_duration = time.time() - start_load_time
                 logging.info(f"Fine-tuned TTS model loaded in {load_duration:.2f}s.")
                 TTS_LOAD_STATUS.set(1)
             except Exception as e:
                 logging.error(f"Failed to load fine-tuned TTS model: {e}", exc_info=True)
                 tts = None
                 TTS_LOAD_STATUS.set(0)
    elif tts_model_name: # Pre-trained
        logging.info(f"Attempting to load pre-trained TTS model: {tts_model_name}")
        try:
            start_load_time = time.time()
            tts = CoquiTTS(model_name=tts_model_name, progress_bar=False, gpu=False)
            load_duration = time.time() - start_load_time
            logging.info(f"Pre-trained TTS model '{tts_model_name}' loaded in {load_duration:.2f}s.")
            TTS_LOAD_STATUS.set(1)
        except Exception as e:
            logging.error(f"Failed to load pre-trained TTS model '{tts_model_name}': {e}", exc_info=True)
            tts = None
            TTS_LOAD_STATUS.set(0)
    else: # None configured
        logging.warning("No TTS model configured. TTS will be disabled.")
        tts = None
        TTS_LOAD_STATUS.set(0)

    logging.info("Application startup sequence complete.")
    yield # Application runs here

    # --- Shutdown Logic ---
    logging.info("Shutting down application...")
    if driver:
        logging.info("Quitting Selenium WebDriver...")
        try:
            driver.quit()
            logging.info("Selenium WebDriver shut down successfully.")
        except Exception as e:
            logging.error(f"Error quitting WebDriver: {e}", exc_info=True)
    logging.info("Application shutdown complete.")


# --- FastAPI Application Instance ---
app = FastAPI(
    title="AI Cricket Commentary Backend",
    description="Generates cricket commentary using LLM and TTS, with web scraping.",
    version="0.4.0", # Incremented version for commentary scraping endpoint
    lifespan=lifespan
)

# --- CORS Middleware Configuration ---
origins = [
    "http://localhost",
    "http://localhost:80", # Explicitly add if needed (browser might normalize localhost to port 80)
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], # Allows all methods including OPTIONS, POST, GET
    allow_headers=["*"], # Allows all headers, including Content-Type
)

# --- Middleware for capturing metrics ---
@app.middleware("http")
async def track_metrics(request: Request, call_next):
    start_time = time.time()
    endpoint_label = request.url.path
    try:
        response = await call_next(request)
        if request.scope.get('route'):
            endpoint_label = request.scope['route'].path
        else:
             endpoint_label = f"ERR_{response.status_code}"
        latency = time.time() - start_time
        REQUEST_COUNT.labels(method=request.method, endpoint=endpoint_label).inc()
        REQUEST_LATENCY.labels(method=request.method, endpoint=endpoint_label).observe(latency)
        return response
    except Exception as e:
        latency = time.time() - start_time
        endpoint_label = request.url.path
        if request.scope.get('route'):
             endpoint_label = request.scope['route'].path
        REQUEST_COUNT.labels(method=request.method, endpoint=endpoint_label).inc()
        REQUEST_LATENCY.labels(method=request.method, endpoint=endpoint_label).observe(latency)
        logging.error(f"Unhandled exception in middleware/endpoint for {request.method} {request.url.path}: {e}", exc_info=True)
        raise e


# --- Mount Prometheus metrics endpoint ---
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# --- API Endpoints ---

@app.get("/", tags=["General"])
async def read_root():
    """Returns a welcome message."""
    return {"message": "Welcome to the AI Cricket Commentary Backend!"}

@app.get("/health", tags=["General"])
async def health_check():
    """Performs a health check, including WebDriver, LLM, and TTS status."""
    driver_status_val = 1 if driver else 0
    llm_status_val = 1 if llm else 0
    tts_status_val = 1 if tts else 0
    WEBDRIVER_STATUS.set(driver_status_val)
    LLM_LOAD_STATUS.set(llm_status_val)
    TTS_LOAD_STATUS.set(tts_status_val)
    return { "status": "ok", "dependencies": { "webdriver": "initialized" if driver else "failed_or_not_initialized", "llm_model": "loaded" if llm else "failed_or_not_loaded", "tts_model": "loaded" if tts else "failed_or_not_loaded" } }

@app.get("/live_matches", tags=["Scraping"])
async def get_live_matches():
    """Scrapes and returns a list of URLs for live/upcoming matches."""
    if not driver:
         SCRAPER_ERRORS.labels(match_type='live').inc()
         raise HTTPException(status_code=503, detail="WebDriver not available")
    try:
        logging.info("Endpoint /live_matches called")
        start_scrape_time = time.time()
        matches = scrape_live_matches(driver) # Calls function from scraper.py
        scrape_duration = time.time() - start_scrape_time
        MATCHES_FOUND.labels(match_type='live').set(len(matches))
        logging.info(f"/live_matches completed in {scrape_duration:.2f}s, found {len(matches)} matches.")
        return {"matches": matches}
    except Exception as e:
        logging.error(f"Error in /live_matches endpoint: {e}", exc_info=True)
        SCRAPER_ERRORS.labels(match_type='live').inc()
        MATCHES_FOUND.labels(match_type='live').set(0)
        raise HTTPException(status_code=500, detail=f"Failed to scrape live matches: {str(e)}")

@app.get("/past_matches", tags=["Scraping"])
async def get_past_matches():
    """Scrapes and returns a list of URLs for past matches."""
    if not driver:
         SCRAPER_ERRORS.labels(match_type='past').inc()
         raise HTTPException(status_code=503, detail="WebDriver not available")
    try:
        logging.info("Endpoint /past_matches called")
        start_scrape_time = time.time()
        matches = scrape_past_matches(driver) # Calls function from scraper.py
        scrape_duration = time.time() - start_scrape_time
        MATCHES_FOUND.labels(match_type='past').set(len(matches))
        logging.info(f"/past_matches completed in {scrape_duration:.2f}s, found {len(matches)} matches.")
        return {"matches": matches}
    except Exception as e:
        logging.error(f"Error in /past_matches endpoint: {e}", exc_info=True)
        SCRAPER_ERRORS.labels(match_type='past').inc()
        MATCHES_FOUND.labels(match_type='past').set(0)
        raise HTTPException(status_code=500, detail=f"Failed to scrape past matches: {str(e)}")

# --- Pydantic model for commentary request (Scraping based) ---
class ScrapeRequest(BaseModel):
    url: str

# --- NEW Endpoint to Scrape and Generate ---
@app.post("/scrape_commentary", tags=["AI Generation"])
async def scrape_and_generate(request: ScrapeRequest):
    """
    Scrapes commentary from the given match URL, processes the latest entry
    with LLM and TTS, and returns the results.
    """
    if not driver:
        raise HTTPException(status_code=503, detail="WebDriver not available")
    if not llm:
        LLM_LOAD_STATUS.set(0)
        raise HTTPException(status_code=503, detail="LLM model not available")

    logging.info(f"Received request to scrape commentary from: {request.url}")
    start_scrape_process_time = time.time()
    latest_raw_commentary = ""
    processed_commentary = ""
    audio_url = None

    # --- Scrape Commentary ---
    try:
        # Call the commentary scraping function from scraper.py
        scraped_commentaries = scrape_match_commentary(driver, request.url)
        scrape_duration = time.time() - start_scrape_process_time
        COMMENTARY_SCRAPE_TIME.observe(scrape_duration)
        logging.info(f"Scraping took {scrape_duration:.2f}s, found {len(scraped_commentaries)} entries.")

        if not scraped_commentaries:
            logging.warning(f"No commentary entries found for URL: {request.url}")
            return {"commentary": "(No commentary found on page)", "processed_commentary": None, "audio_url": None} # Return specific message

        latest_raw_commentary = scraped_commentaries[-1] # Get the last entry (latest ball)
        logging.info(f"Processing latest raw entry: '{latest_raw_commentary}'")

    except Exception as scrape_err:
        logging.error(f"Error during commentary scraping for {request.url}: {scrape_err}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to scrape commentary: {str(scrape_err)}")

    # --- LLM Processing ---
    start_llm_time = time.time()
    try:
        system_message = "You are an expert cricket commentator with an exciting, descriptive style like in the IPL."
        user_message = f"Make this commentary more exciting and descriptive: '{latest_raw_commentary}'"
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message}
        ]
        response = llm.create_chat_completion(
            messages=messages, max_tokens=150, temperature=0.7
        )

        if response and response.get('choices') and response['choices'][0].get('message') and response['choices'][0]['message'].get('content'):
             processed_commentary = response['choices'][0]['message']['content'].strip()
             if processed_commentary.startswith("assistant"): processed_commentary = processed_commentary[len("assistant"):].strip()
             if processed_commentary.startswith(":"): processed_commentary = processed_commentary[1:].strip()
             refusal_patterns = ["I cannot fulfill", "I am unable", "As an AI", "I'm sorry"]
             if any(pattern.lower() in processed_commentary.lower() for pattern in refusal_patterns):
                 logging.warning(f"LLM refused or failed the task: '{processed_commentary}'")
                 processed_commentary = f"(LLM processing failed: Refusal) - Original: {latest_raw_commentary}"
        else:
             logging.error(f"Unexpected LLM chat response structure: {response}")
             processed_commentary = f"(LLM processing failed: Bad Structure) - Original: {latest_raw_commentary}"

        llm_duration = time.time() - start_llm_time
        LLM_GENERATE_TIME.observe(llm_duration)
        logging.info(f"LLM processed commentary in {llm_duration:.2f}s: '{processed_commentary}'")

    except Exception as llm_err:
        logging.error(f"Error during LLM processing: {llm_err}", exc_info=True)
        processed_commentary = f"(LLM processing failed: Exception) - Original: {latest_raw_commentary}"

    # --- TTS Synthesis ---
    error_indicators = ["(LLM processing failed", "(No commentary found"]
    valid_processed_commentary = processed_commentary and not any(err in processed_commentary for err in error_indicators)

    if tts and valid_processed_commentary:
        logging.info("Synthesizing audio with TTS...")
        start_tts_time = time.time()
        try:
            filename = f"commentary_{uuid.uuid4()}.wav"
            output_path = os.path.join("/app/static", filename)
            tts_text = processed_commentary[:500]
            if len(processed_commentary) > 500: logging.warning(f"Processed commentary truncated for TTS: '{tts_text}'")
            tts.tts_to_file(text=tts_text, file_path=output_path)
            tts_duration = time.time() - start_tts_time
            TTS_SYNTHESIS_TIME.observe(tts_duration)
            logging.info(f"TTS synthesis completed in {tts_duration:.2f}s. File: {output_path}")
            audio_url = f"/audio/{filename}"
        except Exception as tts_err:
            logging.error(f"Error during TTS synthesis: {tts_err}", exc_info=True)
    elif not tts:
         logging.warning("TTS model not loaded, skipping audio synthesis.")
         TTS_LOAD_STATUS.set(0)
    elif not valid_processed_commentary:
         logging.warning(f"Invalid or placeholder processed commentary ('{processed_commentary}'), skipping audio synthesis.")

    # Return raw scraped text, processed text, and audio URL
    return {
        "raw_commentary": latest_raw_commentary or "(Raw commentary unavailable)",
        "processed_commentary": processed_commentary or "(Processed commentary unavailable)",
        "audio_url": audio_url
        }


# --- Endpoint to serve generated audio files ---
@app.get("/audio/{filename}", tags=["Audio"])
async def get_audio(filename: str):
    """Serves the generated audio WAV file."""
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename format")
    file_path = os.path.join("/app/static", filename)
    logging.debug(f"Attempting to serve audio file: {file_path}")
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path, media_type="audio/wav")
    else:
        logging.warning(f"Audio file not found or is not a file: {file_path}")
        raise HTTPException(status_code=404, detail=f"Audio file '{filename}' not found")

# --- Pydantic model for feedback request ---
class FeedbackRequest(BaseModel):
    commentary_text: str # Should ideally be the processed commentary
    score: int
    comment: str | None = None

@app.post("/feedback", tags=["Feedback"])
async def submit_feedback(feedback: FeedbackRequest):
    """Receives and logs user feedback on generated commentary."""
    FEEDBACK_COUNT.inc()
    FEEDBACK_SCORE.observe(feedback.score)
    log_message = f"FEEDBACK RECEIVED - Score: {feedback.score} | Text: '{feedback.commentary_text[:100]}...'"
    if feedback.comment: log_message += f" | Comment: '{feedback.comment}'"
    logging.info(log_message)
    if feedback.score < 3:
        DRIFT_SCORE.observe(feedback.score)
        logging.warning(f"Negative feedback score ({feedback.score}) received, potentially indicating model drift.")
    return {"message": "Feedback successfully received"}


# --- Uvicorn entrypoint (if running script directly) ---
# if __name__ == "__main__":
#     uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)