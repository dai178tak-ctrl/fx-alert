#!/usr/bin/env python3
"""USD/JPY movement alerts for GitHub Actions and Discord."""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/USDJPY=X?interval=5m&range=2d"
STATE_PATH = Path(os.getenv("STATE_PATH", ".state/fx_state.json"))
JST = timezone(timedelta(hours=9))


def env_float(name: str, default: float | None) -> float | None:
    raw = os.getenv(name, "").strip()
    return default if not raw else float(raw)


def fetch_rates() -> list[tuple[int, float]]:
    request = urllib.request.Request(YAHOO_URL, headers={"User-Agent": "Mozilla/5.0 fx-alert/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    result = payload["chart"]["result"][0]
    timestamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    points = [(int(ts), float(rate)) for ts, rate in zip(timestamps, closes) if rate is not None]
    if not points:
        raise RuntimeError("為替データを取得できませんでした")
    return points


def rate_at_or_before(points: list[tuple[int, float]], target: int) -> float | None:
    candidates = [rate for ts, rate in points if ts <= target]
    return candidates[-1] if candidates else None


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def notify_discord(message: str) -> None:
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        raise RuntimeError("DISCORD_WEBHOOK_URL が設定されていません")

    body = json.dumps(
        {"content": message},
        ensure_ascii=False,
    ).encode("utf-8")

    request = urllib.request.Request(
        webhook,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 fx-alert/1.1",
        },
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status not in (200, 204):
            raise RuntimeError(
                f"Discord通知に失敗しました: HTTP {response.status}"
            )


def main() -> int:

def main() -> int:
    points = fetch_rates()
    now_ts, current = points[-1]
    rate_15m = rate_at_or_before(points, now_ts - 15 * 60)
    rate_1h = rate_at_or_before(points, now_ts - 60 * 60)
    rate_24h = rate_at_or_before(points, now_ts - 24 * 60 * 60)
    state = load_state()

    move_15m = env_float("MOVE_15M_JPY", 0.5)
    move_1h = env_float("MOVE_1H_JPY", 0.8)
    move_daily_pct = env_float("MOVE_DAILY_PCT", 1.5)
    target_high = env_float("TARGET_HIGH", None)
    target_low = env_float("TARGET_LOW", None)
    usd_amount = env_float("USD_AMOUNT", 5000.0) or 5000.0
    cooldown = int(env_float("COOLDOWN_MINUTES", 60) or 60)

    reasons: list[str] = []
    changes: list[float] = []
    if rate_15m is not None:
        delta = current - rate_15m
        changes.append(delta)
        if abs(delta) >= (move_15m or 0):
            reasons.append(f"15分で {delta:+.2f}円")
    if rate_1h is not None:
        delta = current - rate_1h
        changes.append(delta)
        if abs(delta) >= (move_1h or 0):
            reasons.append(f"1時間で {delta:+.2f}円")
    if rate_24h is not None:
        pct = (current / rate_24h - 1) * 100
        if abs(pct) >= (move_daily_pct or 0):
            reasons.append(f"24時間で {pct:+.2f}%")

    previous = state.get("last_rate")
    if target_high is not None and current >= target_high and (previous is None or previous < target_high):
        reasons.append(f"上側目標 {target_high:.2f}円に到達")
    if target_low is not None and current <= target_low and (previous is None or previous > target_low):
        reasons.append(f"下側目標 {target_low:.2f}円に到達")

    force = os.getenv("FORCE_NOTIFY", "false").lower() == "true"
    direction = "up" if (changes and changes[0] >= 0) else "down"
    last_alert = state.get("last_alert", {})
    cooled_down = True
    if last_alert.get("direction") == direction and last_alert.get("timestamp"):
        cooled_down = now_ts - int(last_alert["timestamp"]) >= cooldown * 60

    if force:
        reasons.insert(0, "手動実行テスト")

    if reasons and (cooled_down or force or any("目標" in r for r in reasons)):
        arrow = "📈 円安方向" if direction == "up" else "📉 円高方向"
        observed = datetime.fromtimestamp(now_ts, JST).strftime("%Y-%m-%d %H:%M JST")
        yen_value = round(current * usd_amount)
        message = (
            f"**【USD/JPY 為替通知】**\n"
            f"現在: **{current:.2f}円**（{arrow}）\n"
            + "\n".join(f"・{reason}" for reason in reasons)
            + f"\n・{usd_amount:,.0f}ドルの概算: **{yen_value:,.0f}円**"
            + f"\n観測時刻: {observed}\n※参考レート。実際の両替レートとは異なります。"
        )
        notify_discord(message)
        state["last_alert"] = {"timestamp": now_ts, "direction": direction}
        print("Discordへ通知しました")
    else:
        print(f"通知条件未達: USD/JPY {current:.2f}")

    state.update({"last_rate": current, "last_timestamp": now_ts})
    save_state(state)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise

