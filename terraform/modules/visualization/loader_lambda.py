import json
import os
import time
from datetime import datetime, timedelta, timezone

import urllib3
import pandas as pd

try:
    import awswrangler as wr
    HAS_WRANGLER = True
except ImportError:
    HAS_WRANGLER = False
    print("Warning: awswrangler not available (attach the AWSSDKPandas layer)")

# pg8000 is bundled in the AWS-managed AWSSDKPandas Lambda layer.
import pg8000.dbapi  # noqa: E402

http = urllib3.PoolManager()

GOLD_BUCKET = os.environ.get("GOLD_BUCKET_NAME", "visor-inc-amazing-datalake-gold")
DB_HOST = os.environ.get("DB_HOST", "")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "metrics")
DB_USER = os.environ.get("DB_USER", "")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# --- Target schema (mirrors gold_lambda.py output tables) -------------------
# For each gold table: ordered column list + CREATE TABLE DDL. Every table has
# a `date` column, which is what per-date-replace keys on. Score/karma columns
# use BIGINT to be safe; dq_score_pct is NUMERIC.
TABLES = {
    "daily_content_metrics": {
        "columns": ["date", "platform", "post_type", "post_count"],
        "ddl": """
            CREATE TABLE IF NOT EXISTS daily_content_metrics (
                date        DATE    NOT NULL,
                platform    TEXT    NOT NULL,
                post_type   TEXT    NOT NULL,
                post_count  INTEGER,
                PRIMARY KEY (date, platform, post_type)
            )""",
    },
    "daily_users_metric": {
        "columns": ["date", "platform", "total_users", "new_users"],
        "ddl": """
            CREATE TABLE IF NOT EXISTS daily_users_metric (
                date         DATE    NOT NULL,
                platform     TEXT    NOT NULL,
                total_users  INTEGER,
                new_users    INTEGER,
                PRIMARY KEY (date, platform)
            )""",
    },
    "top_hn_users_by_karma": {
        "columns": ["date", "direction", "rank", "username", "karma_score"],
        "ddl": """
            CREATE TABLE IF NOT EXISTS top_hn_users_by_karma (
                date         DATE    NOT NULL,
                direction    TEXT    NOT NULL,
                rank         INTEGER NOT NULL,
                username     TEXT,
                karma_score  BIGINT,
                PRIMARY KEY (date, direction, rank)
            )""",
    },
    "top_hn_jobs_by_score": {
        "columns": ["date", "rank", "post_id", "author_username", "score", "content_text"],
        "ddl": """
            CREATE TABLE IF NOT EXISTS top_hn_jobs_by_score (
                date             DATE    NOT NULL,
                rank             INTEGER NOT NULL,
                post_id          TEXT,
                author_username  TEXT,
                score            BIGINT,
                content_text     TEXT,
                PRIMARY KEY (date, rank)
            )""",
    },
    "top_hn_posts_by_score": {
        "columns": ["date", "rank", "post_id", "author_username", "score", "content_text"],
        "ddl": """
            CREATE TABLE IF NOT EXISTS top_hn_posts_by_score (
                date             DATE    NOT NULL,
                rank             INTEGER NOT NULL,
                post_id          TEXT,
                author_username  TEXT,
                score            BIGINT,
                content_text     TEXT,
                PRIMARY KEY (date, rank)
            )""",
    },
    "top_x_users_by_engagement": {
        "columns": ["date", "rank", "username", "engagement_score"],
        "ddl": """
            CREATE TABLE IF NOT EXISTS top_x_users_by_engagement (
                date              DATE    NOT NULL,
                rank              INTEGER NOT NULL,
                username          TEXT,
                engagement_score  BIGINT,
                PRIMARY KEY (date, rank)
            )""",
    },
    "data_quality_score": {
        "columns": ["date", "table_name", "total_rows", "non_null_cells", "total_cells", "dq_score_pct"],
        "ddl": """
            CREATE TABLE IF NOT EXISTS data_quality_score (
                date            DATE    NOT NULL,
                table_name      TEXT    NOT NULL,
                total_rows      INTEGER,
                non_null_cells  INTEGER,
                total_cells     INTEGER,
                dq_score_pct    NUMERIC(6,2),
                PRIMARY KEY (date, table_name)
            )""",
    },
}

INT_COLUMNS = {"post_count", "total_users", "new_users", "rank",
               "karma_score", "score", "engagement_score",
               "total_rows", "non_null_cells", "total_cells"}
FLOAT_COLUMNS = {"dq_score_pct"}
DATE_COLUMNS = {"date"}


def send_discord_notification(message, is_error=True):
    """Same notification contract as bronze/silver/gold."""
    if not DISCORD_WEBHOOK_URL:
        print("Discord webhook URL not configured")
        return
    try:
        color = 15158332 if is_error else 3066993  # red / green
        payload = {"embeds": [{
            "title": "Loader Lambda Job Failed" if is_error else "Loader Lambda Job Succeeded",
            "description": message,
            "color": color,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "Visor Inc Data Lake"},
        }]}
        resp = http.request("POST", DISCORD_WEBHOOK_URL,
                            body=json.dumps(payload).encode("utf-8"),
                            headers={"Content-Type": "application/json"})
        if resp.status != 204:
            print(f"Discord notification failed: {resp.status}")
    except Exception as e:
        print(f"Error sending Discord notification: {e}")


def read_gold_table(table_name):
    """Read a whole gold table (all partitions) as a dataframe. Partition
    columns (date / platform) are reconstructed from the S3 path by awswrangler."""
    path = f"s3://{GOLD_BUCKET}/{table_name}/"
    try:
        df = wr.s3.read_parquet(path=path, dataset=True)
        print(f"[loader] read {len(df)} rows from {path}")
        return df
    except Exception as e:
        print(f"[loader] no data at {path} ({e}); treating as empty")
        return pd.DataFrame()


def _coerce(col, val):
    """Convert a pandas cell into a Postgres-friendly Python value."""
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    if col in DATE_COLUMNS:
        if isinstance(val, str):
            return datetime.strptime(val[:10], "%Y-%m-%d").date()
        if hasattr(val, "date"):
            return val.date()
        return val
    if col in INT_COLUMNS:
        return int(val)
    if col in FLOAT_COLUMNS:
        return float(val)
    return str(val)


def _rows(df, columns):
    df = df.reindex(columns=columns)
    return [tuple(_coerce(c, r[c]) for c in columns) for _, r in df.iterrows()]


def load_table(cur, table_name, spec, date_str):
    """CREATE IF NOT EXISTS, delete the target date, insert its rows. Idempotent."""
    columns = spec["columns"]
    cur.execute(spec["ddl"])

    df = read_gold_table(table_name)
    if not df.empty and "date" in df.columns:
        df["date"] = df["date"].astype(str).str.slice(0, 10)
        df = df[df["date"] == date_str]

    # per-date replace
    cur.execute(f"DELETE FROM {table_name} WHERE date = %s", (date_str,))

    if df.empty:
        print(f"[loader] {table_name}: no rows for {date_str}")
        return 0

    rows = _rows(df, columns)
    placeholders = ", ".join(["%s"] * len(columns))
    collist = ", ".join(columns)
    cur.executemany(
        f"INSERT INTO {table_name} ({collist}) VALUES ({placeholders})",
        rows,
    )
    print(f"[loader] {table_name}: inserted {len(rows)} rows for {date_str}")
    return len(rows)


def lambda_handler(event, context):
    start = time.time()
    event = event or {}
    date_str = event.get("date") or (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).strftime("%Y-%m-%d")
    print(f"[loader] loading gold metrics into PostgreSQL for date: {date_str}")

    if not HAS_WRANGLER:
        raise RuntimeError("awswrangler is required (attach the AWSSDKPandas layer)")
    if not DB_HOST or not DB_USER:
        raise RuntimeError("DB_HOST / DB_USER not configured")

    loaded = {}
    errors = []
    con = None
    try:
        con = pg8000.dbapi.connect(
            user=DB_USER, password=DB_PASSWORD,
            host=DB_HOST, port=DB_PORT, database=DB_NAME,
            timeout=30,
        )
        cur = con.cursor()
        for name, spec in TABLES.items():
            try:
                loaded[name] = load_table(cur, name, spec, date_str)
                con.commit()
            except Exception as e:
                con.rollback()
                msg = f"{name}: {e}"
                print(f"[loader] ERROR {msg}")
                errors.append(msg)
        cur.close()

        elapsed = time.time() - start
        summary = (
            f"**Gold -> PostgreSQL Load Summary**\n"
            f"Date: {date_str}\n"
            + "\n".join(f"- {k}: {v} rows" for k, v in loaded.items())
            + f"\n\nExecution Time: {elapsed:.2f}s\nErrors: {len(errors)}"
        )
        if errors:
            summary += "\n**Error Details:**\n" + "\n".join(errors[:10])
        send_discord_notification(summary, is_error=bool(errors))

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Loader completed",
                "date": date_str,
                "loaded": loaded,
                "execution_time": elapsed,
                "error_count": len(errors),
                "errors": errors or None,
            }),
        }
    except Exception as e:
        err = f"Loader Lambda execution failed: {e}"
        print(err)
        send_discord_notification(f"**Critical Failure**\n{err}\n\nDate: {date_str}", is_error=True)
        raise
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass
