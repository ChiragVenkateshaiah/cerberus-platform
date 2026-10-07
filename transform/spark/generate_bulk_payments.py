"""Cerberus 8.3 -- bulk synthetic payments generator for the Phase 8 scale ladder.

Writes about 1M-100M payment events into bronze as JSON Lines, per ADR 0018:

    s3a://<bronze>/payments_bulk/run_id=<run_id>/dt=YYYY-MM-DD/part-*.json

Same event schema and lifecycle rules as ingestion/scripts/payments_lib.py
(ADR 0003): created -> authorized -> settled or failed, some settled events
refunded, every timestamp clamped to "now". Built from Spark functions
instead of a Python loop, because the ingestion Lambda can't reach this
volume and the stock apache/spark image has no Faker.

Deterministic on purpose (ADR 0018): every random choice is a hash of
(run_id, row id, a per-field salt), and "now" is an argument, not the wall
clock. A re-run with the same arguments writes the same events, and dynamic
partition overwrite replaces only this run's run_id=/dt= directories -- so a
retried run never doubles its data and never touches another run or the
daily Lambda feed under payments/.

The roster below is a copy of payments_lib.build_roster()'s output (Faker
26.0.0, seed 42), not generated here -- the image has no Faker.
check_bulk_roster.py fails if the two ever drift. The lifecycle constants
are copied from payments_lib the same way.

The image runs Python 3.10, so this file avoids 3.11+ features.
"""

import argparse
import calendar
import math
import time

from pyspark.sql import Column, SparkSession
from pyspark.sql import functions as F

ACCOUNT_ID = "131715059025"
BRONZE_BUCKET = f"cerberus-platform-bronze-{ACCOUNT_ID}"
BULK_PREFIX = "payments_bulk/"

# --- Copied from payments_lib.py; keep in sync by hand -----------------------
MERCHANTS = [
    ("mrc_0001", "Rodriguez, Figueroa and Sanchez", "grocery"),
    ("mrc_0002", "Doyle Ltd", "retail"),
    ("mrc_0003", "Mcclain, Miller and Henderson", "dining"),
    ("mrc_0004", "Davis and Sons", "electronics"),
    ("mrc_0005", "Guzman, Hoffman and Baldwin", "electronics"),
    ("mrc_0006", "Gardner, Robinson and Lawrence", "travel"),
    ("mrc_0007", "Blake and Sons", "grocery"),
    ("mrc_0008", "Henderson, Ramirez and Lewis", "grocery"),
    ("mrc_0009", "Garcia-James", "fuel"),
    ("mrc_0010", "Abbott-Munoz", "retail"),
    ("mrc_0011", "Blair PLC", "retail"),
    ("mrc_0012", "Dudley Group", "grocery"),
    ("mrc_0013", "Arnold Ltd", "electronics"),
    ("mrc_0014", "Mcclure, Ward and Lee", "electronics"),
    ("mrc_0015", "Williams and Sons", "retail"),
]
CUSTOMERS = [
    ("cus_0001", "Kendra Galloway", "kendra.galloway0001@example.com"),
    ("cus_0002", "Melissa Delacruz", "melissa.delacruz0002@example.com"),
    ("cus_0003", "Norman Chavez", "norman.chavez0003@example.com"),
    ("cus_0004", "Mary Martin", "mary.martin0004@example.com"),
    ("cus_0005", "Michael Santiago", "michael.santiago0005@example.com"),
    ("cus_0006", "Jacqueline Sutton", "jacqueline.sutton0006@example.com"),
    ("cus_0007", "Charles Reid", "charles.reid0007@example.com"),
    ("cus_0008", "Amanda Sanchez", "amanda.sanchez0008@example.com"),
    ("cus_0009", "Steven Nelson", "steven.nelson0009@example.com"),
    ("cus_0010", "Sara Watts", "sara.watts0010@example.com"),
    ("cus_0011", "Jeffrey Nguyen", "jeffrey.nguyen0011@example.com"),
    ("cus_0012", "Kayla Brown", "kayla.brown0012@example.com"),
    ("cus_0013", "Lydia Trujillo", "lydia.trujillo0013@example.com"),
    ("cus_0014", "Richard Jones", "richard.jones0014@example.com"),
    ("cus_0015", "Robin Bradley", "robin.bradley0015@example.com"),
    ("cus_0016", "Jennifer Lewis", "jennifer.lewis0016@example.com"),
    ("cus_0017", "Victor Wilkerson", "victor.wilkerson0017@example.com"),
    ("cus_0018", "Dawn Thomas", "dawn.thomas0018@example.com"),
    ("cus_0019", "Donald Mcgee", "donald.mcgee0019@example.com"),
    ("cus_0020", "Amber Burgess", "amber.burgess0020@example.com"),
    ("cus_0021", "Ross Silva", "ross.silva0021@example.com"),
    ("cus_0022", "Michael Osborn", "michael.osborn0022@example.com"),
    ("cus_0023", "Devon Snyder", "devon.snyder0023@example.com"),
    ("cus_0024", "Katelyn Callahan", "katelyn.callahan0024@example.com"),
    ("cus_0025", "Eric Moore", "eric.moore0025@example.com"),
    ("cus_0026", "Erin Carlson", "erin.carlson0026@example.com"),
    ("cus_0027", "Paul Carlson", "paul.carlson0027@example.com"),
    ("cus_0028", "Taylor King", "taylor.king0028@example.com"),
    ("cus_0029", "Angela Dunlap", "angela.dunlap0029@example.com"),
    ("cus_0030", "Erin Wilson", "erin.wilson0030@example.com"),
    ("cus_0031", "Nicole Potter", "nicole.potter0031@example.com"),
    ("cus_0032", "Kayla Peterson", "kayla.peterson0032@example.com"),
    ("cus_0033", "Kelly Moore", "kelly.moore0033@example.com"),
    ("cus_0034", "Aaron Bowen", "aaron.bowen0034@example.com"),
    ("cus_0035", "Jennifer Stanton", "jennifer.stanton0035@example.com"),
    ("cus_0036", "Kathleen Romero", "kathleen.romero0036@example.com"),
    ("cus_0037", "Daniel Garrett", "daniel.garrett0037@example.com"),
    ("cus_0038", "Meagan Romero", "meagan.romero0038@example.com"),
    ("cus_0039", "James Brooks", "james.brooks0039@example.com"),
    ("cus_0040", "Evan Ashley", "evan.ashley0040@example.com"),
    ("cus_0041", "Sandra Sellers", "sandra.sellers0041@example.com"),
    ("cus_0042", "Carol Burns", "carol.burns0042@example.com"),
    ("cus_0043", "Daniel Cox", "daniel.cox0043@example.com"),
    ("cus_0044", "Tricia Roman", "tricia.roman0044@example.com"),
    ("cus_0045", "John Allen", "john.allen0045@example.com"),
    ("cus_0046", "Ashley Miller", "ashley.miller0046@example.com"),
    ("cus_0047", "Jessica Cabrera", "jessica.cabrera0047@example.com"),
    ("cus_0048", "Tiffany Patel", "tiffany.patel0048@example.com"),
    ("cus_0049", "David Keller", "david.keller0049@example.com"),
    ("cus_0050", "Stacey Martin", "stacey.martin0050@example.com"),
    ("cus_0051", "Allison Obrien", "allison.obrien0051@example.com"),
    ("cus_0052", "Tamara Hickman", "tamara.hickman0052@example.com"),
    ("cus_0053", "Karina Vaughn", "karina.vaughn0053@example.com"),
    ("cus_0054", "Jennifer Ross", "jennifer.ross0054@example.com"),
    ("cus_0055", "Emily Brooks", "emily.brooks0055@example.com"),
    ("cus_0056", "Rachel Hayes", "rachel.hayes0056@example.com"),
    ("cus_0057", "John Brown", "john.brown0057@example.com"),
    ("cus_0058", "Andrew Spencer", "andrew.spencer0058@example.com"),
    ("cus_0059", "Brianna Smith", "brianna.smith0059@example.com"),
    ("cus_0060", "Jean Brown", "jean.brown0060@example.com"),
    ("cus_0061", "Carlos Johnson", "carlos.johnson0061@example.com"),
    ("cus_0062", "Mark Palmer", "mark.palmer0062@example.com"),
    ("cus_0063", "Joshua Washington", "joshua.washington0063@example.com"),
    ("cus_0064", "Amber Cummings", "amber.cummings0064@example.com"),
    ("cus_0065", "Nicole Johnston", "nicole.johnston0065@example.com"),
    ("cus_0066", "John Kennedy", "john.kennedy0066@example.com"),
    ("cus_0067", "Richard Davis", "richard.davis0067@example.com"),
    ("cus_0068", "Donna Gomez", "donna.gomez0068@example.com"),
    ("cus_0069", "Robert Shields", "robert.shields0069@example.com"),
    ("cus_0070", "Brian Valdez", "brian.valdez0070@example.com"),
    ("cus_0071", "Debbie Brown", "debbie.brown0071@example.com"),
    ("cus_0072", "Jessica Mcbride", "jessica.mcbride0072@example.com"),
    ("cus_0073", "Daniel Lee", "daniel.lee0073@example.com"),
    ("cus_0074", "Amanda Taylor", "amanda.taylor0074@example.com"),
    ("cus_0075", "Isaiah Ford", "isaiah.ford0075@example.com"),
]
CARD_BRANDS = ["visa", "mastercard", "amex"]
CURRENCIES = ["USD", "USD", "USD", "EUR", "GBP"]
CREATED_WINDOW_DAYS = 7
AUTH_DELAY_SECONDS = (5, 120)
SETTLE_DELAY_HOURS = (1, 72)
FAIL_DELAY_SECONDS = (1, 30)
DECLINE_PROBABILITY = 0.05
REFUND_PROBABILITY = 0.05
REFUND_DELAY_DAYS = (1, 14)
# payment_method type weights: card 70, bank_transfer 20, wallet 10.
CARD_CUTOFF = 0.70
BANK_TRANSFER_CUTOFF = 0.90
# -----------------------------------------------------------------------------

# created + authorized, then failed (p=0.05) or settled (p=0.95), and a
# refund on 5% of settled: 2 + 0.05 + 0.95 * 1.05 = 3.0475 events per
# transaction. Used only to turn --events into a transaction count.
EVENTS_PER_TRANSACTION = (
    2 + DECLINE_PROBABILITY + (1 - DECLINE_PROBABILITY) * (1 + REFUND_PROBABILITY)
)
# Spark's JSON writer is compact (no spaces after separators), so a little
# under the ~464 bytes json.dumps gives the Lambda's events. Only used to
# size output files, not for correctness.
BYTES_PER_EVENT = 430
# created spans 7 days back from now, and the clamp to now adds today: the
# events land in about 8 dt= partitions.
DT_SPAN_DAYS = CREATED_WINDOW_DAYS + 1

TIMESTAMP_FORMAT = "yyyy-MM-dd'T'HH:mm:ss'Z'"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", required=True, help="names the run_id= partition")
    parser.add_argument("--events", type=int, required=True, help="target event count")
    parser.add_argument(
        "--now",
        required=True,
        help="fixed 'now' as YYYY-MM-DDTHH:MM:SSZ; part of what makes a re-run identical",
    )
    parser.add_argument("--target-file-mb", type=int, default=128)
    parser.add_argument(
        "--output",
        default=f"s3a://{BRONZE_BUCKET}/{BULK_PREFIX}",
        help="output root; override only for a local test",
    )
    return parser.parse_args()


def uniform(run_id: str, salt: str) -> Column:
    """A deterministic value in [0, 1) per (run_id, row id, salt)."""
    h = F.xxhash64(F.lit(run_id), F.col("id"), F.lit(salt))
    return F.pmod(h, F.lit(1 << 31)) / F.lit(float(1 << 31))


def randint(run_id: str, salt: str, low: int, high: int) -> Column:
    """Like random.randint: an integer in [low, high], both ends included."""
    return (F.floor(uniform(run_id, salt) * (high - low + 1)) + low).cast("long")


def pick(run_id: str, salt: str, values: list) -> Column:
    """Like random.choice over a list of literal Columns."""
    index = F.floor(uniform(run_id, salt) * len(values)).cast("int") + 1
    return F.element_at(F.array(*values), index)


def hex_digest(run_id: str, salt: str, length: int) -> Column:
    key = F.concat_ws(":", F.lit(run_id), F.col("id").cast("string"), F.lit(salt))
    return F.substring(F.sha2(key, 256), 1, length)


def build_transactions(spark, run_id: str, transactions: int, now_epoch: int):
    merchants = [
        F.struct(
            F.lit(mid).alias("merchant_id"), F.lit(name).alias("name"), F.lit(cat).alias("category")
        )
        for mid, name, cat in MERCHANTS
    ]
    customers = [
        F.struct(
            F.lit(cid).alias("customer_id"), F.lit(name).alias("name"), F.lit(email).alias("email")
        )
        for cid, name, email in CUSTOMERS
    ]

    method_roll = uniform(run_id, "method_type")
    method_type = (
        F.when(method_roll < CARD_CUTOFF, "card")
        .when(method_roll < BANK_TRANSFER_CUTOFF, "bank_transfer")
        .otherwise("wallet")
    )
    is_card = method_type == "card"
    # tok_ + 16 lowercase letters, never digits (2026-10-06 data-quality
    # finding: digit runs in tokens can pass the Luhn check). Hex digits
    # 0-9 map to g-p, so all 16 characters are letters a-p.
    token = F.concat(
        F.lit("tok_"), F.translate(hex_digest(run_id, "token", 16), "0123456789", "ghijklmnop")
    )
    payment_method = F.struct(
        method_type.alias("type"),
        F.when(is_card, pick(run_id, "brand", [F.lit(b) for b in CARD_BRANDS])).alias("brand"),
        F.when(is_card, F.lpad(randint(run_id, "last4", 0, 9999).cast("string"), 4, "0")).alias(
            "last4"
        ),
        token.alias("token"),
    )

    now = F.lit(now_epoch)
    created = now - randint(run_id, "created", 0, CREATED_WINDOW_DAYS * 86400)
    authorized = F.least(created + randint(run_id, "auth", *AUTH_DELAY_SECONDS), now)
    declined = uniform(run_id, "decline") < DECLINE_PROBABILITY
    failed = authorized + randint(run_id, "fail", *FAIL_DELAY_SECONDS)
    settled = F.least(authorized + randint(run_id, "settle", *SETTLE_DELAY_HOURS) * 3600, now)
    refunded = settled + randint(run_id, "refund", *REFUND_DELAY_DAYS) * 86400
    is_refunded = ~declined & (uniform(run_id, "refund_roll") < REFUND_PROBABILITY)

    def event(event_type: str, ts: Column, condition: Column | None = None) -> Column:
        value = F.struct(F.lit(event_type).alias("event_type"), F.least(ts, now).alias("ts"))
        return value if condition is None else F.when(condition, value)

    lifecycle = F.array(
        event("created", created),
        event("authorized", authorized),
        event("failed", failed, declined),
        event("settled", settled, ~declined),
        event("refunded", refunded, is_refunded),
    )

    return (
        spark.range(transactions)
        .select(
            "id",
            F.concat(F.lit("txn_"), hex_digest(run_id, "txn", 32)).alias("transaction_id"),
            F.round(F.lit(1.00) + uniform(run_id, "amount") * (999.99 - 1.00), 2).alias("amount"),
            pick(run_id, "currency", [F.lit(c) for c in CURRENCIES]).alias("currency"),
            pick(run_id, "merchant", merchants).alias("merchant"),
            pick(run_id, "customer", customers).alias("customer"),
            payment_method.alias("payment_method"),
            lifecycle.alias("lifecycle"),
        )
        .select("*", F.explode("lifecycle").alias("e"))
        .where(F.col("e").isNotNull())
    )


def to_events(df, run_id: str):
    ts = F.timestamp_seconds(F.col("e.ts"))
    return df.select(
        "transaction_id",
        F.col("e.event_type").alias("event_type"),
        F.date_format(ts, TIMESTAMP_FORMAT).alias("event_timestamp"),
        "amount",
        "currency",
        "merchant",
        "customer",
        "payment_method",
        # Path columns only: partitionBy moves them into the key, so the
        # JSON lines keep exactly ADR 0003's eight fields.
        F.lit(run_id).alias("run_id"),
        F.date_format(ts, "yyyy-MM-dd").alias("dt"),
    )


def main():
    args = parse_args()
    now_epoch = calendar.timegm(time.strptime(args.now, "%Y-%m-%dT%H:%M:%SZ"))
    transactions = math.ceil(args.events / EVENTS_PER_TRANSACTION)

    # About args.target_file_mb per file: estimate the bytes per dt=
    # partition, split each partition into that many write tasks, and cap
    # rows per file so a task that gets two buckets still splits its output.
    target_bytes = args.target_file_mb * 1024 * 1024
    files_per_dt = max(1, math.ceil(args.events * BYTES_PER_EVENT / DT_SPAN_DAYS / target_bytes))
    rows_per_file = target_bytes // BYTES_PER_EVENT

    spark = (
        SparkSession.builder.appName("cerberus-generate-bulk-payments")
        .config(
            "spark.hadoop.fs.s3a.aws.credentials.provider",
            "com.amazonaws.auth.WebIdentityTokenCredentialsProvider",
        )
        # date_format renders in the session time zone; events are UTC.
        .config("spark.sql.session.timeZone", "UTC")
        # Overwrite only the run_id=/dt= directories this run writes.
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
        .config("spark.sql.files.maxRecordsPerFile", str(rows_per_file))
        .getOrCreate()
    )

    print(
        f"[generate] run_id={args.run_id} now={args.now} target_events={args.events} "
        f"transactions={transactions} files_per_dt={files_per_dt} rows_per_file={rows_per_file}"
    )

    events = to_events(build_transactions(spark, args.run_id, transactions, now_epoch), args.run_id)
    # _bucket spreads one dt= partition over files_per_dt write tasks.
    events = events.withColumn(
        "_bucket", F.pmod(F.xxhash64("transaction_id"), F.lit(files_per_dt))
    ).repartition(DT_SPAN_DAYS * files_per_dt, "dt", "_bucket")

    started = time.time()
    (events.drop("_bucket").write.mode("overwrite").partitionBy("run_id", "dt").json(args.output))
    elapsed = time.time() - started

    # A second pass over the same deterministic generation, no I/O: the
    # per-partition counts are this run's manifest for the 8.4
    # reconciliation (events written per run_id and dt).
    counts = events.groupBy("dt").count().orderBy("dt").collect()
    total = sum(row["count"] for row in counts)
    for row in counts:
        print(f"[generate] dt={row['dt']} events={row['count']}")
    print(
        f"[generate] done run_id={args.run_id} events={total} partitions={len(counts)} "
        f"write_seconds={elapsed:.1f} events_per_second={total / elapsed:.0f}"
    )
    spark.stop()


if __name__ == "__main__":
    main()
