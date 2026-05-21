#!/usr/bin/env python3
"""Kronos Heartbeat — health check + status report"""
import json, sys, os, subprocess, time, urllib.request

REPORT = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), "checks": {}}

def check_http(url, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return {"ok": True, "status": r.status, "body": json.loads(r.read().decode())}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def check_process(name, cmdline_keyword):
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    cmd = f.read().decode(errors="replace").replace("\x00", " ")
                    if cmdline_keyword in cmd:
                        return {"ok": True, "pid": pid, "cmd": cmd[:200]}
            except:
                pass
        return {"ok": False, "error": f"process '{name}' not found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# 1. Bot API health
REPORT["checks"]["bot_api"] = check_http("http://127.0.0.1:8500/api/health")

# 2. Bot status
REPORT["checks"]["bot_status"] = check_http("http://127.0.0.1:8500/api/status")

# 3. Bot process
REPORT["checks"]["bot_process"] = check_process("bot", "bot.py")

# 4. Tunnel process
REPORT["checks"]["tunnel_process"] = check_process("cloudflared", "cloudflared")

# 5. Try to get tunnel URL from logs
try:
    log = subprocess.run(["journalctl", "-u", "cloudflared", "-n", "5"], capture_output=True, text=True, timeout=3)
    REPORT["checks"]["tunnel_log"] = {"ok": True, "lines": log.stdout.strip().split("\n")[-3:]}
except Exception as e:
    REPORT["checks"]["tunnel_log"] = {"ok": False, "error": str(e)}

# 6. Supabase connectivity (via bot API)
try:
    perf = check_http("http://127.0.0.1:8500/api/performance")
    REPORT["checks"]["supabase_data"] = perf
except Exception as e:
    REPORT["checks"]["supabase_data"] = {"ok": False, "error": str(e)}

# Determine overall health
healthy = all(c["ok"] for c in REPORT["checks"].values())
REPORT["healthy"] = healthy

# Print concise report
if healthy:
    status = "✅ HEALTHY"
else:
    status = "❌ DEGRADED"

lines = [f"[{REPORT['timestamp']}] KRONOS HEARTBEAT {status}"]
for name, result in REPORT["checks"].items():
    icon = "✅" if result["ok"] else "❌"
    detail = ""
    if name == "bot_status" and result["ok"]:
        b = result.get("body", {})
        detail = f" | market={b.get('market_str','?')} pred={b.get('prediction_direction','?')} conf={b.get('confidence','?')}"
    elif name == "supabase_data" and result["ok"]:
        b = result.get("body", {})
        detail = f" | balance=${b.get('balance','?')} trades={b.get('total_trades','?')} win={b.get('win_rate','?')}%"
    lines.append(f"  {icon} {name}{detail}")

print("\n".join(lines))
sys.exit(0 if healthy else 1)
