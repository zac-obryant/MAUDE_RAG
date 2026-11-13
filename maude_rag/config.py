"""Settings shared by every step of the pipeline."""

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_REPORTS = DATA_DIR / "reports.jsonl"
CHROMA_DIR = DATA_DIR / "chroma"
COLLECTION = "insulin_pump_narratives"

# FDA product codes that cover insulin pumps.
PRODUCT_CODES = {
    "LZG": "Pump, Infusion, Insulin",
    "QFG": "Alternate Controller Enabled Insulin Infusion Pump",
    "OZP": "Automated Insulin Dosing Device System, Single Hormonal Control",
    "OZO": "Automated Insulin Dosing, Threshold Suspend",
}

# Small, free, runs on a laptop CPU. Produces 384-number vectors and reads
# at most 256 tokens (roughly 190 words) of each text, hence the chunk size.
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CHUNK_WORDS = 150
CHUNK_OVERLAP = 30

# The narrative written by the reporter. The other type, "Additional
# Manufacturer Narrative", is mostly boilerplate and is left out of the baseline.
NARRATIVE_TYPE = "Description of Event or Problem"

ANSWER_MODEL = "claude-opus-5-5"
TOP_K = 8

# Step 3: a SQLite copy of the reports for counting questions.
DB_PATH = DATA_DIR / "reports.db"
MAX_SQL_ROWS = 200  # rows shown to the LLM; more than this is cut off and flagged

# Step 5: openFDA's device recall records, fetched live by the agent.
RECALL_API = "https://api.fda.gov/device/recall.json"
AGENT_MAX_STEPS = 10  # rounds of tool calls (one round can hold several calls) before it must answer
