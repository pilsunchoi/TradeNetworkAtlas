from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "baci"
EXTRACT = RAW / "extracted"
PROCESSED = ROOT / "data" / "processed"
DB_PATH = PROCESSED / "baci_net.duckdb"
LOGS = ROOT / "logs"

BACI_VERSION = "V202601"
BACI_HS = "HS92"
BACI_ZIP = RAW / f"BACI_{BACI_HS}_{BACI_VERSION}.zip"
YEARS = list(range(1995, 2025))

KCSDB_PATH = Path(r"C:\Work\Projects\KCSDB2\data\processed\kcsdb.duckdb")
