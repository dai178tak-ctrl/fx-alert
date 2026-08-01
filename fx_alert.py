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


def window_move(
    points: list[tuple[int, float]], now_ts: int, seconds: int
) -> tuple[float, float, float]:
    """Return signed intrawindow move, high, and low.

    The sign follows the order of the extremes: high then low is negative,
    while low then high is positive. This catches fast moves that later rebound.
    """
    window = [(ts, rate) for ts, rate in points if ts >= now_ts - seconds]
    if len(window) < 2:
        return 0.0, window[-1][1], window[-1][1]
    high_ts, high = max(window, key=lambda item: item[1])
    low_ts, low = min(window, key=lambda item: item[1])
    span = high - low
    signed_span = -span if high_ts < low_ts else span
    return signed_span, high, low


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
    body = json.dumps({"content": message}, ensure_ascii=False).encode("utf-8")
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
            raise RuntimeError(f"Discord通知に失敗しました: HTTP {response.status}")


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
    renotify_move = env_float("RENOTIFY_MOVE_JPY", 1.0) or 1.0

    reasons: list[str] = []
    trigger_moves: list[float] = []
    if rate_15m is not None:
        delta = current - rate_15m
        if abs(delta) >= (move_15m or 0):
            reasons.append(f"15分で {delta:+.2f}円")
            trigger_moves.append(delta)
        else:
            span, high, low = window_move(points, now_ts, 15 * 60)
            if abs(span) >= (move_15m or 0):
                reasons.append(
                    f"15分内の値幅 {abs(span):.2f}円（高値{high:.2f} / 安値{low:.2f}）"
                )
                trigger_moves.append(span)
    if rate_1h is not None:
        delta = current - rate_1h
        if abs(delta) >= (move_1h or 0):
            reasons.append(f"1時間で {delta:+.2f}円")
            trigger_moves.append(delta)
        else:
            span, high, low = window_move(points, now_ts, 60 * 60)
            if abs(span) >= (move_1h or 0):
                reasons.append(
                    f"1時間内の値幅 {abs(span):.2f}円（高値{high:.2f} / 安値{low:.2f}）"
                )
                trigger_moves.append(span)
    daily_pct = 0.0
    if rate_24h is not None:
        daily_pct = (current / rate_24h - 1) * 100
        if abs(daily_pct) >= (move_daily_pct or 0):
            reasons.append(f"24時間で {daily_pct:+.2f}%")
            trigger_moves.append(current - rate_24h)

    previous = state.get("last_rate")
    target_crossed = False
    if target_high is not None and current >= target_high and (previous is None or previous < target_high):
        reasons.append(f"上側目標 {target_high:.2f}円に到達")
        trigger_moves.append(1.0)
        target_crossed = True
    if target_low is not None and current <= target_low and (previous is None or previous > target_low):
        reasons.append(f"下側目標 {target_low:.2f}円に到達")
        trigger_moves.append(-1.0)
        target_crossed = True

    force = os.getenv("FORCE_NOTIFY", "false").lower() == "true"
    primary_move = max(trigger_moves, key=abs) if trigger_moves else 0.0
    direction = "up" if primary_move >= 0 else "down"
    last_alert = state.get("last_alert", {})
    last_alert_rate = last_alert.get("rate")
    condition_was_active = bool(state.get("condition_active", False))
    has_market_reason = bool(reasons)

    should_notify = (has_market_reason or force) and (
        force
        or target_crossed
        or not condition_was_active
        or not last_alert
        or last_alert.get("direction") != direction
        or last_alert_rate is None
        or abs(current - float(last_alert_rate)) >= renotify_move
    )

    if force:
        reasons.insert(0, "手動実行テスト")

    if should_notify:
        arrow = (
            "🧪 動作確認"
            if force and not has_market_reason
            else ("📈 円安方向" if direction == "up" else "📉 円高方向")
        )
        observed = datetime.fromtimestamp(now_ts, JST).strftime("%Y-%m-%d %H:%M JST")
        yen_value = round(current * usd_amount)
        intervention_suspected = daily_pct <= -2.0 or primary_move <= -2.0
        title = (
            "🚨【USD/JPY 急変・為替介入疑い】"
            if intervention_suspected
            else "【USD/JPY 為替通知】"
        )
        message = (
            f"**{title}**\n"
            f"現在: **{current:.2f}円**（{arrow}）\n"
            + "\n".join(f"・{reason}" for reason in reasons)
            + f"\n・{usd_amount:,.0f}ドルの概算: **{yen_value:,.0f}円**"
            + f"\n観測時刻: {observed}\n※参考レート。実際の両替レートとは異なります。"
        )
        notify_discord(message)
        state["last_alert"] = {
            "timestamp": now_ts,
            "direction": direction,
            "rate": current,
        }
        print("Discordへ通知しました")
    elif reasons:
        print(
            f"条件継続中・追加変動が{renotify_move:.2f}円未満のため通知抑制: "
            f"USD/JPY {current:.2f}"
        )
    else:
        print(f"通知条件未達: USD/JPY {current:.2f}")

    state.update(
        {
            "last_rate": current,
            "last_timestamp": now_ts,
            "condition_active": has_market_reason,
        }
    )
    save_state(state)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
