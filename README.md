# hnx-lake
This project involves the implementation of a cloud-based platform for collecting, processing, storing, and analyzing data from social media and blog portals, specifically Hacker News and X (Twitter). Built entirely on AWS, the solution follows the Medallion architecture to manage data flow through distinct stages of refinement

## Architecture Layers
**Bronze (Raw):** Ingests daily posts, comments, and jobs from Hacker News via Lambda functions and stores them in S3 in their native format.
**Silver (Validated):** Normalizes data into a 3NF schema, cleans HTML tags, synchronizes timestamps to UTC, and converts files to Parquet format.
**Gold (Enriched):** Aggregates business-level metrics and KPIs, such as daily user activity and top-performing content.
