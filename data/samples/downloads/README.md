# downloads sample

`sample_10k.jsonl.gz` is a golden sample of the `downloads` event family
(ADR 0030 Decision 7): about 10k events from 200 synthetic clients. All names
are synthetic (`region_nn`, `isp_nn_a`, `console_a`, `cl_<hex>`). It is gzip
so that the account-number scan skips it.

Regenerate it with the pure-Python core, no Spark:

    python3 transform/spark/generate_bulk_downloads.py --run-id sample-v1 \
      --events 10000 --now 2026-11-22T06:00:00Z \
      --local data/samples/downloads/sample_10k.jsonl.gz

The gzip header time is fixed, so the same arguments give the same bytes. A
test regenerates it and compares the decompressed content.
