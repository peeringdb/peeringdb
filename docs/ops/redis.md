# Redis Configuration

PeeringDB supports two Redis deployment modes:

1. **Single Redis Instance** - Standalone Redis server
2. **Redis with Sentinel** - High-availability Redis with automatic failover

**Mode Selection:** The presence or absence of `REDIS_SENTINEL_NODES` controls which mode is used:
- `REDIS_SENTINEL_NODES` **set** (non-empty) → Sentinel mode enabled
- `REDIS_SENTINEL_NODES` **unset** (empty or not defined) → Single instance mode

## Environment Variables

### Common Settings (both modes)

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `127.0.0.1` | For single instance: Redis host IP<br>For Sentinel: master service name |
| `REDIS_PASSWORD` | `""` | Redis authentication password |

### Single Redis Instance Only

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_PORT` | `6379` | Redis server port |

### Redis Sentinel Only

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_SENTINEL_NODES` | `[]` | List of Sentinel nodes: `[("host1", port1), ("host2", port2)]` |
| `REDIS_SENTINEL_ENABLED` | Auto | Automatically `True` if `REDIS_SENTINEL_NODES` is set |
| `REDIS_SENTINEL_PASSWORD` | `""` | Sentinel authentication password (if different from Redis) |
| `REDIS_SOCKET_TIMEOUT` | `0.5` | Socket timeout (seconds) |
| `REDIS_SOCKET_CONNECT_TIMEOUT` | `0.5` | Connection timeout (seconds) |
| `REDIS_RETRY_ON_TIMEOUT` | `True` | Retry on timeout |

## Configuration Examples

### Single Redis Instance

```bash
export REDIS_HOST="127.0.0.1"
export REDIS_PORT="6379"
export REDIS_PASSWORD="mypassword"
```

### Redis with Sentinel

```bash
# Master service name (not IP address)
export REDIS_HOST="mymaster"

# Sentinel nodes
export REDIS_SENTINEL_NODES='[("sentinel1.example.com", 26379), ("sentinel2.example.com", 26379), ("sentinel3.example.com", 26379)]'

# Passwords
export REDIS_PASSWORD="redispassword"
export REDIS_SENTINEL_PASSWORD="sentinelpassword"  # Optional, if different
```

**Note:** `REDIS_SENTINEL_NODES` must be a valid Python list. Setting this variable automatically enables Sentinel mode.

## How It Works

The system automatically detects which mode to use:

- If `REDIS_SENTINEL_NODES` is set → Uses Sentinel mode
- Otherwise → Uses single instance mode

On startup, it tests connectivity and falls back to DatabaseCache or LocMemCache if Redis is unavailable.
