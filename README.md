# hnx-lake
This project involves the implementation of a cloud-based platform for collecting, processing, storing, and analyzing data from social media and blog portals, specifically Hacker News and X (Twitter). Built entirely on AWS, the solution follows the Medallion architecture to manage data flow through distinct stages of refinement

## Architecture Layers
* **Bronze (Raw):** Ingests daily posts, comments, and jobs from Hacker News via Lambda functions and stores them in S3 in their native format.
* **Silver (Validated):** Normalizes data into a 3NF schema, cleans HTML tags, synchronizes timestamps to UTC, and converts files to Parquet format.
* **Gold (Enriched):** Aggregates business-level metrics and KPIs, such as daily user activity and top-performing content.

## Gold Layer — Metrics & KPIs

The Gold layer is a single Lambda function (`visor-inc-gold-lambda`) that reads the normalized Silver tables (`posts`, `users`) and produces business-level metrics and a data-quality KPI as partitioned Parquet in the Gold bucket. It runs daily via EventBridge (03:00 UTC, after Silver) and can also be invoked on demand for a specific date.

For each run date it produces the following tables:

| Table | Spec metric | Columns | Partitioning |
|-------|-------------|---------|--------------|
| `daily_content_metrics` | Daily count of stories/asks/comments/jobs/polls | date, platform, post_type, post_count | date |
| `daily_users_metric` | Daily HN & X user counts | date, platform, total_users, new_users | platform, date |
| `top_hn_users_by_karma` | Top/bottom 10 HN users by karma | date, direction, rank, username, karma_score | date |
| `top_hn_jobs_by_score` | Top 10 HN jobs by score | date, rank, post_id, author_username, score, content_text | date |
| `top_hn_posts_by_score` | Top 10 HN posts by score | date, rank, post_id, author_username, score, content_text | date |
| `top_x_users_by_engagement` | Top 10 X users by followers | date, rank, username, engagement_score | date |
| `data_quality_score` | Data Quality KPI | date, table_name, total_rows, non_null_cells, total_cells, dq_score_pct | date |

Notes:
- **`daily_users_metric`** is cumulative: `total_users` counts distinct users first seen on/before the date, `new_users` counts users first seen on that date.
- **`top_x_users_by_engagement`** uses engagement (`Likes + Retweets`) as a proxy for reach, because the X dataset used (`goyaladi/twitter-dataset`) has no follower-count column. The per-post `score` carries this engagement for X (and the points for Hacker News).
- **`data_quality_score`** measures the share of non-null cells over the *required* columns of each Silver table (id, author/username, timestamp, type/platform), so schema-nullable fields (`karma_score` for X, `is_verified` for HN) don't unfairly lower the score.

### Running

```bash
# The daily run is automatic (EventBridge cron 03:00 UTC).
# Manual run for a specific date:
aws lambda invoke \
  --function-name visor-inc-gold-lambda \
  --payload '{"date":"2026-05-29"}' \
  --cli-binary-format raw-in-base64-out \
  --cli-read-timeout 900 \
  response.json
```

If no `date` is provided, the function defaults to "yesterday" (UTC).

### Implementation notes
- Reads/writes Parquet with **awswrangler** (provided by the AWS-managed `AWSSDKPandas` Lambda layer).
- Writes use `mode="overwrite_partitions"`, so re-running for a date is **idempotent** (overwrites that date's partitions instead of appending duplicates).
- Runs inside the private subnet; reaches S3 via the Gateway VPC endpoint and Discord via the NAT instance. The Lambda's IAM role is scoped to read Silver and write Gold only (least privilege).
- Sends a Discord notification summarizing rows written / errors on every run.
- Metric logic is implemented as pure pandas functions (`compute_*`), unit-tested locally in `terraform/modules/lambda/gold/test_gold_lambda.py`.
