# Kiwai

**Local-first idempotency for Python side effects.**

Kiwai prevents the same email, invoice, webhook, export, or external API action from running twice when a script is retried, a cron job overlaps, or a worker crashes and restarts.

```python
from kiwai import Kiwai

kiwai = Kiwai("automation-state.db")

@kiwai.idempotent(key=lambda invoice_id: f"invoice:{invoice_id}")
def send_invoice(invoice_id: int) -> dict:
    email_provider.send_invoice(invoice_id)
    return {"sent": True, "invoice_id": invoice_id}

send_invoice(23068)  # executes
send_invoice(23068)  # returns the cached result; no second email
```

## Why Kiwai?

Retries are necessary, but retrying side effects is dangerous. A timeout does not always mean an operation failed. A process can also restart after sending an email but before saving that it finished.

Popular task queues solve larger orchestration problems and usually require Redis, PostgreSQL, workers, or a hosted service. Kiwai is intentionally smaller:

- one decorator;
- one SQLite file;
- zero runtime dependencies;
- safe across threads and processes on the same machine;
- sync and async functions;
- payload conflict detection;
- leases for crashed workers;
- optional result caching and TTL;
- a CLI for inspection and cleanup.

Kiwai does **not** claim magical exactly-once delivery. It provides durable idempotency around your application logic. For payments and other critical APIs, also pass the same idempotency key to the downstream provider whenever supported.

## Installation

Until the first PyPI release:

```bash
pip install git+https://github.com/WesleyAtanasio/Kiwai.git
```

Local development:

```bash
git clone https://github.com/WesleyAtanasio/Kiwai.git
cd Kiwai
python -m pip install -e ".[dev]"
pytest
```

## Common patterns

### Prevent duplicate emails

```python
@kiwai.idempotent(key=lambda customer_id, month: f"statement:{customer_id}:{month}")
def email_statement(customer_id: int, month: str) -> dict:
    message_id = mailer.send_statement(customer_id, month)
    return {"message_id": message_id}
```

### Protect a cron job

```python
@kiwai.idempotent(key=lambda business_date: f"daily-close:{business_date}", ttl=7 * 86400)
def close_day(business_date: str) -> dict:
    return generate_and_upload_report(business_date)
```

### Retry failures, not successes

```python
attempts = 0

@kiwai.idempotent(key="supplier-sync")
def sync_supplier() -> dict:
    global attempts
    attempts += 1
    if attempts == 1:
        raise ConnectionError("temporary outage")
    return {"synced": True}

sync_supplier()  # fails and is recorded as failed
sync_supplier()  # runs again
sync_supplier()  # cached; does not run a third time
```

### Async functions

```python
@kiwai.idempotent(key=lambda event_id: f"webhook:{event_id}")
async def process_webhook(event_id: str) -> dict:
    await update_remote_system(event_id)
    return {"processed": event_id}
```

### Automatic keys

When `key` is omitted, Kiwai hashes the function name, positional arguments, and keyword arguments deterministically.

```python
@kiwai.idempotent(ttl=3600)
def build_export(customer_id: int, format: str = "csv") -> dict:
    ...
```

Use an explicit business key for important operations. Automatic keys are convenient for caching-like workloads but may change if function arguments change.

## Behavior

| Situation | Result |
|---|---|
| First call | Function runs and obtains a lease |
| Same key and same payload after success | Cached result is returned |
| Same key but different payload | `IdempotencyConflict` |
| Same operation currently running | `OperationInProgress` |
| Worker dies | Another worker can reclaim the key after the lease expires |
| Function raises | Failure is recorded and the next call may retry |
| TTL expires | The operation may run again |

## Result caching

Results must be JSON serializable when `cache_result=True` (the default). This keeps the storage transparent and language-neutral.

For fire-and-forget functions:

```python
@kiwai.idempotent(key="newsletter:2026-07", cache_result=False)
def send_newsletter() -> object:
    return provider.send()
```

The first call returns the original result. Replays return `None`, while the side effect remains protected.

If serialization fails after a side effect succeeds, Kiwai records the operation as successful before raising `ResultSerializationError`. This deliberately prevents a retry from duplicating the side effect.

## Leases and waiting

The default lease is five minutes. Pick a duration longer than the normal execution time.

```python
@kiwai.idempotent(key="large-export", lease=1800, wait_timeout=30)
def export() -> dict:
    ...
```

With `wait_timeout`, a duplicate caller briefly waits for the first worker's cached result instead of immediately raising `OperationInProgress`.

## CLI

```bash
kiwai --db automation-state.db list
kiwai --db automation-state.db list --status failed
kiwai --db automation-state.db show default:invoice:23068
kiwai --db automation-state.db delete default:invoice:23068
kiwai --db automation-state.db purge
```

The CLI outputs JSON so it can be piped into scripts and monitoring tools.

## Safety model

Kiwai uses SQLite `BEGIN IMMEDIATE` transactions, WAL mode, unique operation keys, owner tokens, and expiring leases. These protect competing processes using the same database file on one host.

For distributed deployments across multiple machines, use a shared database backend. PostgreSQL support is planned for a future release.

## Project status

Kiwai is an alpha MVP. The SQLite API and core decorator are ready for experimentation, but the project has not yet been battle-tested at large scale.

See [ROADMAP.md](ROADMAP.md) and open an issue with real-world cases. Contributions are welcome.

## License

MIT © Wesley Atanasio
