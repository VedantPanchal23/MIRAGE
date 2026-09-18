# ADR 0002: Rate Limiting Algorithm Unification (Atomic Token Bucket with Redis Server Time)

## Status
**ACCEPTED** (Ratified in Phase P0.4)

## Context
A cross-document specification audit conducted during Phase P0.4 identified conflicting rate-limiting requirements across the project documentation:
- **`Security_Access.md` §7.2**: Specifies a *"sliding window algorithm in Redis"*, returning `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, and `Retry-After`.
- **`Technical_Architecture.md` §7.4**: Specifies rate-limiting keys as `ratelimit:{tenant_id}:{minute_bucket}` (a fixed/sliding window counter schema).
- **`Testing_Strategy.md` §7 (Line 150)**: Dictates verifying that *"token-bucket limits are enforced by tenant key, not just IP address"*.
- **Implementation Reality**: The initial gateway prototype implemented an in-memory sliding-window timestamp list (`SlidingWindowRateLimiter` using `defaultdict(list)`), which was not distributed, non-atomic, and subject to unbounded memory growth and process restart resets.

## Decision
We formally adopt the **Atomic Token Bucket with Redis Server Time** as the authoritative distributed rate-limiting algorithm across all MIRAGE gateway endpoints.

### 1. Header Contract Preservation
The Token Bucket implementation preserves full backward compatibility with the HTTP response contract specified in `Security_Access.md` §7.2:
- `X-RateLimit-Limit`: Maximum tier burst capacity ($C$).
- `X-RateLimit-Remaining`: Integer floor of remaining available tokens in the bucket ($\lfloor \text{tokens} \rfloor$).
- `X-RateLimit-Reset`: Unix epoch timestamp when the bucket will completely refill to capacity $C$.
- `Retry-After`: Integer seconds until sufficient tokens are refilled to satisfy the rejected request.

### 2. Algorithmic Advantages Over Sliding-Window Log (ZSET)
1. **$O(1)$ Constant Memory**:
   - A Sliding-Window Log using Redis Sorted Sets (`ZSET`) stores an individual entry for every request timestamp. At Enterprise tier limits (1,000 req/min) across thousands of tenants, this incurs severe Redis memory bloat and garbage collection pauses.
   - The Token Bucket algorithm stores only two floating-point numbers (`tokens`, `last_updated`) in a single Redis Hash per tenant, consuming a constant $\approx 100$ bytes per tenant regardless of traffic volume.
2. **Burst Capacity with Smooth Rate Shaping**:
   - Token bucket naturally accommodates legitimate traffic bursts up to capacity $C$ while enforcing smooth long-term throughput matching the refill rate $r$.
3. **Atomic Lua Execution**:
   - All state transitions (time retrieval, refill computation, capacity capping, consumption decrement, and TTL extension) execute within a single atomic Redis Lua script, eliminating race conditions across distributed gateway instances.

### 3. Distributed Clock Synchronization via Redis Server Time
- Rather than trusting or synchronizing application server clocks (`time.time()`), the Lua script queries the authoritative Redis server clock directly via `local t = redis.call('TIME')`.
- This provides microsecond precision ($\text{sec} + \frac{\text{usec}}{10^6}$) and completely eliminates rate-limiting errors caused by NTP drift, host clock skew, or client clock tampering.

## Consequences
- **Positive**: Distributed atomicity, zero double-spending under concurrent bursts, $O(1)$ memory footprint, and clock skew immunity.
- **Positive**: Seamless tier boundaries (`free`: 60 req/min, `pro`: 300 req/min, `enterprise`: 1000 req/min).
- **Compliance**: Replaces the unshared in-memory `SlidingWindowRateLimiter` with a distributed, least-privilege Redis implementation.
