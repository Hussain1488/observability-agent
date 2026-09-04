"""Mock observability tools for the multi-agent assistant.

Each tool stands in for a real observability backend (Jaeger/Tempo for traces,
Loki/Elasticsearch for logs, Prometheus for metrics, a docs vector DB for RAG,
and the GitHub API / a code index for code search). No network calls or I/O
happen here -- every tool returns hardcoded, realistic-looking data so the
agents can be developed and demoed without live backends.

The mock data tells one coherent incident story: the `checkout` service is
slow because a `db.query` span is slow, and a downstream `payments` dependency
is timing out with 504s.
"""

from langchain_core.tools import tool, BaseTool


# ---------------------------------------------------------------------------
# Traces agent (Jaeger/Tempo)
# ---------------------------------------------------------------------------


@tool
def get_trace(service: str) -> str:
    """Get a span breakdown (total time and top spans) for the given service's most recent trace."""
    if service.lower() == "checkout":
        return (
            "Trace for service 'checkout' (trace_id=8f3a1c2e9b7d4f10, total=2140ms):\n"
            "  - http.request checkout.placeOrder      220ms\n"
            "  - db.query SELECT * FROM cart_items      1450ms  <-- slowest span\n"
            "  - grpc.call payments.authorize            410ms  (downstream, see get_slow_spans)\n"
            "  - cache.write order_cache                  60ms\n"
            "Bottleneck: db.query span accounts for ~68% of total trace time."
        )
    return (
        f"Trace for service '{service}' (trace_id=1a2b3c4d5e6f7890, total=180ms):\n"
        "  - http.request handler                  95ms  <-- slowest span\n"
        "  - db.query lookup                        60ms\n"
        "  - cache.read                              25ms\n"
        "No anomalies detected."
    )


@tool
def get_slow_spans(service: str) -> str:
    """Get the slowest spans recorded for the given service in the last hour."""
    if service.lower() == "checkout":
        return (
            "Slowest spans for 'checkout' (last 1h):\n"
            "  1. db.query SELECT * FROM cart_items   p99=1620ms  p50=1310ms  (1,204 occurrences)\n"
            "  2. grpc.call payments.authorize         p99=5000ms  p50=490ms   (312 occurrences, many timing out)\n"
            "  3. http.request checkout.placeOrder     p99=2400ms  p50=240ms   (1,204 occurrences)\n"
            "Note: db.query on cart_items is missing an index on cart_id, causing full table scans."
        )
    if service.lower() == "payments":
        return (
            "Slowest spans for 'payments' (last 1h):\n"
            "  1. grpc.server authorize                p99=5000ms  p50=310ms  (298 occurrences)\n"
            "  2. http.client fraud-check.verify        p99=4800ms  p50=280ms  (298 occurrences)\n"
            "Note: fraud-check.verify calls are timing out upstream, cascading into 504s."
        )
    return (
        f"Slowest spans for '{service}' (last 1h):\n"
        "  1. http.request handler   p99=210ms  p50=90ms  (842 occurrences)\n"
        "No spans exceeding SLO thresholds."
    )


# ---------------------------------------------------------------------------
# Logs agent (Loki/Elasticsearch)
# ---------------------------------------------------------------------------


@tool
def search_logs(query: str) -> str:
    """Search log lines across all services matching the given search string and return matches with counts."""
    q = query.lower()
    if "504" in q or "timeout" in q or "payments" in q:
        return (
            f"Log search for '{query}' matched 812 lines (last 1h):\n"
            "  [checkout] ERROR grpc.call to payments.authorize failed: context deadline exceeded (654 occurrences)\n"
            "  [payments] ERROR upstream fraud-check.verify returned 504 Gateway Timeout (298 occurrences)\n"
            "  [checkout] WARN retrying payments.authorize after timeout (654 occurrences)\n"
            "Pattern: payments 504s began at 09:14 UTC and correlate with checkout latency spike."
        )
    if "checkout" in q or "db" in q or "cart" in q:
        return (
            f"Log search for '{query}' matched 1,204 lines (last 1h):\n"
            "  [checkout] WARN slow query on cart_items table, duration=1450ms (1,204 occurrences)\n"
            "  [checkout] INFO order placed successfully (9,880 occurrences)\n"
            "Pattern: slow-query warnings correlate with db.query span latency in traces."
        )
    return (
        f"Log search for '{query}' matched 14 lines (last 1h):\n"
        "  [general] INFO no significant matches found\n"
        "No error patterns detected for this query."
    )


@tool
def get_error_logs(service: str) -> str:
    """Get the most frequent error logs for the given service with occurrence counts and percentages."""
    if service.lower() == "checkout":
        return (
            "Top error logs for 'checkout' (last 1h, 2,010 total errors):\n"
            "  1. grpc.call to payments.authorize failed: context deadline exceeded  -- 654 (32.5%)\n"
            "  2. slow query on cart_items table exceeded 1000ms threshold           -- 1,204 (59.9%)\n"
            "  3. order placement retried after downstream timeout                    -- 152 (7.6%)\n"
        )
    if service.lower() == "payments":
        return (
            "Top error logs for 'payments' (last 1h, 298 total errors):\n"
            "  1. upstream fraud-check.verify returned 504 Gateway Timeout  -- 298 (100.0%)\n"
        )
    return (
        f"Top error logs for '{service}' (last 1h, 6 total errors):\n"
        "  1. minor validation warning on request payload  -- 6 (100.0%)\n"
        "Error volume is within normal range."
    )


# ---------------------------------------------------------------------------
# Metrics agent (Prometheus)
# ---------------------------------------------------------------------------


@tool
def get_metric(name: str) -> str:
    """Get the current value and short trend for a named numeric metric (e.g. throughput, cpu, memory, latency)."""
    n = name.lower()
    if "latency" in n or "duration" in n:
        return (
            "Metric 'checkout.request.latency.p99': current=2140ms, 1h ago=310ms, "
            "trend=rising sharply since 09:14 UTC (+590%)."
        )
    if "throughput" in n or "rps" in n or "requests" in n:
        return (
            "Metric 'checkout.request.throughput': current=142 req/s, 1h ago=210 req/s, "
            "trend=declining (-32%), consistent with client-side timeouts and abandoned checkouts."
        )
    if "cpu" in n:
        return "Metric 'checkout.pod.cpu_utilization': current=38%, 1h ago=41%, trend=stable. CPU is not the bottleneck."
    if "memory" in n or "mem" in n:
        return "Metric 'checkout.pod.memory_utilization': current=54%, 1h ago=52%, trend=stable."
    return f"Metric '{name}': current=1.0, 1h ago=1.0, trend=flat. No data indicating anomalies."


@tool
def get_error_rate(service: str) -> str:
    """Get the current error rate for the given service compared against its baseline."""
    if service.lower() == "checkout":
        return (
            "Error rate for 'checkout': current=18.4%, baseline=0.6%, "
            "delta=+17.8pp. Spike began 09:14 UTC, correlated with payments 504s."
        )
    if service.lower() == "payments":
        return (
            "Error rate for 'payments': current=22.1%, baseline=0.3%, "
            "delta=+21.8pp, driven entirely by fraud-check.verify 504 Gateway Timeouts."
        )
    return f"Error rate for '{service}': current=0.4%, baseline=0.5%, delta=-0.1pp. Within normal range."


# ---------------------------------------------------------------------------
# Docs agent (docs vector DB / RAG)
# ---------------------------------------------------------------------------


@tool
def search_docs(query: str) -> str:
    """Search internal documentation and return the single best-matching snippet for the given query."""
    q = query.lower()
    if "payments" in q or "504" in q or "timeout" in q:
        return (
            "Best match: 'Payments Service Architecture' (docs/payments/architecture.md)\n"
            "\"...the payments service calls the third-party fraud-check provider synchronously "
            "with a 5s timeout. Provider-side incidents surface as 504 Gateway Timeout responses "
            "and propagate to callers such as checkout unless a circuit breaker is configured...\""
        )
    if "checkout" in q or "cart" in q or "db" in q or "index" in q:
        return (
            "Best match: 'Checkout Service Data Model' (docs/checkout/data-model.md)\n"
            "\"...the cart_items table is queried by cart_id on every checkout request. "
            "As of the last schema review, cart_id is not indexed, which can cause full table "
            "scans under load...\""
        )
    return (
        "Best match: 'Observability Platform Overview' (docs/platform/overview.md)\n"
        "\"...this platform aggregates traces, logs, and metrics across services to help "
        "on-call engineers diagnose incidents quickly...\""
    )


@tool
def get_runbook(name: str) -> str:
    """Get a short numbered incident runbook by name (e.g. high-latency, error-spike, downstream-timeout)."""
    n = name.lower()
    if "latency" in n or "checkout" in n or "slow" in n:
        return (
            "Runbook: 'checkout-high-latency'\n"
            "  1. Check get_trace('checkout') for the slowest span in the current trace.\n"
            "  2. If db.query dominates, check for missing indexes on cart_items (cart_id).\n"
            "  3. Check get_error_rate('payments') for downstream timeout cascades.\n"
            "  4. If payments 504s are present, page the payments on-call and consider enabling "
            "the checkout circuit breaker to fail fast.\n"
            "  5. File an incident ticket linking the trace_id and affected time window."
        )
    if "timeout" in n or "payments" in n or "downstream" in n:
        return (
            "Runbook: 'downstream-timeout'\n"
            "  1. Identify the failing downstream via get_slow_spans on the caller service.\n"
            "  2. Check get_error_logs on the downstream service for the root error.\n"
            "  3. Confirm whether the downstream's own dependency (e.g. a third-party provider) is degraded.\n"
            "  4. Apply a circuit breaker or fallback if available, then notify the downstream's on-call."
        )
    return (
        f"Runbook: '{name}'\n"
        "  1. Gather traces, logs, and metrics for the affected service.\n"
        "  2. Compare current metrics against baseline to confirm an anomaly.\n"
        "  3. Escalate to the owning team if the anomaly persists beyond 15 minutes."
    )


# ---------------------------------------------------------------------------
# Code agent (GitHub API / code index)
# ---------------------------------------------------------------------------


@tool
def search_code(query: str) -> str:
    """Search the codebase for a function or pattern and return the file path and function name where it's defined."""
    q = query.lower()
    if "cart_items" in q or "cart" in q or "checkout" in q:
        return (
            "Match: services/checkout/repository/cart_repository.py, function `get_cart_items`\n"
            "  Executes 'SELECT * FROM cart_items WHERE cart_id = ?' with no index hint; "
            "this is the query surfaced in the slow db.query span."
        )
    if "payments" in q or "authorize" in q or "fraud" in q:
        return (
            "Match: services/payments/client/fraud_check_client.py, function `verify_transaction`\n"
            "  Calls the fraud-check provider with a hardcoded 5000ms timeout and no retry/circuit breaker."
        )
    return (
        f"No strong match found for '{query}'. Closest result: "
        "services/common/utils/logging.py, function `configure_logger`."
    )


@tool
def get_recent_commits(service: str) -> str:
    """Get recent commits touching the given service, with short hash, author, message, and date."""
    if service.lower() == "checkout":
        return (
            "Recent commits for 'checkout':\n"
            "  a3f9c1e  M. Rossi     'Add cart summary caching before order placement'   2026-08-29\n"
            "  7bd21aa  J. Kim       'Bump grpc client timeout for payments.authorize'    2026-08-27\n"
            "  e0912fc  M. Rossi     'Refactor cart_repository query building'            2026-08-21\n"
            "Note: e0912fc changed the cart_items query but did not add an index migration."
        )
    if service.lower() == "payments":
        return (
            "Recent commits for 'payments':\n"
            "  9c4e77b  R. Alvarez   'Switch fraud-check provider to new endpoint'  2026-08-30\n"
            "  1f88de2  R. Alvarez   'Remove retry wrapper around fraud-check call'  2026-08-30\n"
            "Note: 1f88de2 removed the retry/backoff logic the same day the 504 rate increased."
        )
    return (
        f"Recent commits for '{service}':\n"
        "  4b2a601  A. Novak  'Routine dependency bump'  2026-08-30\n"
        "No recent changes of note."
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, BaseTool] = {
    t.name: t
    for t in (
        get_trace,
        get_slow_spans,
        search_logs,
        get_error_logs,
        get_metric,
        get_error_rate,
        search_docs,
        get_runbook,
        search_code,
        get_recent_commits,
    )
}


def get_tools(names: list[str]) -> list[BaseTool]:
    """Return the tools registered under the given names, raising KeyError for any unknown names."""
    unknown = [name for name in names if name not in TOOL_REGISTRY]
    if unknown:
        raise KeyError(
            f"Unknown tool name(s): {unknown}. Available tools: {sorted(TOOL_REGISTRY)}"
        )
    return [TOOL_REGISTRY[name] for name in names]
