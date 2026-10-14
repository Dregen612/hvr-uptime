#!/bin/bash
# Off-site check (GitHub). Reads the heartbeat the old Mini publishes every 5 min, and
# cross-checks YouTube's public live page directly, so a late Mini check-in alone never
# reports the stream as down.
# Alerts only on a CONFIRMED problem: two bad readings in a row, and the public page does
# not show the stream live. "Back on air" is sent only after a real down alert, with no
# invented duration (GitHub's schedule can skip hours between runs).
GIST=264164455a4e5fa12f3b28a43a6af69d; NOW=$(date +%s)
LINK=https://www.youtube.com/watch?v=X0cUEL6VuTw
J=$(curl -s -m 20 "https://gist.githubusercontent.com/Dregen612/$GIST/raw/hb.json?t=$NOW")
echo "$J" | python3 -c "import json,sys;json.load(sys.stdin)" 2>/dev/null || J=""
if [ -n "$J" ]; then
  TS=$(echo "$J" | python3 -c "import json,sys;print(json.load(sys.stdin)['ts'])")
  YT=$(echo "$J" | python3 -c "import json,sys;print(json.load(sys.stdin)['youtube'])")
  AGE=$(( (NOW-TS)/60 ))
else
  YT=unknown; AGE=-1
fi

# Public YouTube check (no login): is the channel's live page showing a live broadcast?
P=$(curl -sL -m 20 -A "Mozilla/5.0" -H "Accept-Language: en-US" -b "SOCS=CAI" \
    "https://www.youtube.com/@HolyVoltageRadio/live")
if echo "$P" | grep -q '"isLive":true'; then PUB=live
elif echo "$P" | grep -q '"isLiveContent"'; then PUB=notlive
else PUB=unknown; fi
[ -n "$FORCE_PUB" ] && PUB=$FORCE_PUB   # test hook only
[ -n "$FORCE_AGE" ] && AGE=$FORCE_AGE   # test hook only

REASON=""
if [ "$PUB" != live ]; then
  [ "$AGE" -ge 20 ] && REASON="the old Mini stopped checking in $AGE min ago and YouTube's public page doesn't show the stream live"
  [ -z "$REASON" ] && [ "$YT" != live ] && [ "$YT" != unknown ] && [ "$AGE" -ge 0 ] && REASON="YouTube says the stream is not live"
  [ -z "$REASON" ] && [ "$PUB" = notlive ] && REASON="YouTube's public page shows the stream not live"
fi

# state: <up|suspect|down> <first_bad_ts> <alert_sent_ts>
S=$(cat state.txt 2>/dev/null || echo "up 0 0"); read st since last <<<"$S"
[ -z "$since" ] && since=0; [ -z "$last" ] && last=0
ct(){ TZ=America/Chicago date -d "@$1" '+%-I:%M %p CT' 2>/dev/null || TZ=America/Chicago date -r "$1" '+%-I:%M %p CT'; }
tg(){ [ -z "$TG_TOKEN" ] && { echo "(no TG_TOKEN) would send: $1"; return; }
      curl -s -m 20 -X POST "https://api.telegram.org/bot$TG_TOKEN/sendMessage" -d chat_id="$TG_CHAT" --data-urlencode "text=$1" >/dev/null; }

if [ -z "$REASON" ]; then
  if [ "$st" = down ] && [ "$last" != 0 ]; then
    tg "✅ HVR stream confirmed live again on YouTube (same link). First bad reading was at $(ct $since)."
  fi
  echo "up 0 0" > state.txt; echo "OK age=${AGE}m yt=$YT public=$PUB"; exit 0
fi

if [ "$st" = up ]; then
  # first bad reading: don't alert yet, just remember it
  echo "suspect $NOW 0" > state.txt; echo "SUSPECT (no alert yet): $REASON"; exit 0
fi
# second (or later) consecutive bad reading = confirmed
if [ "$last" = 0 ] || [ $(( NOW-last )) -ge 3600 ]; then
  tg "🔴 HVR stream problem (confirmed twice): $REASON. Checked from outside your house. $LINK"; last=$NOW
fi
echo "down $since $last" > state.txt; echo "DOWN: $REASON"
