#!/bin/bash
# Off-site check (GitHub, every 5 min). Reads the heartbeat the old Mini publishes every 5 min.
# Alerts Adam on Telegram after 5+ min down: heartbeat stale (power/internet out) or YouTube not live.
GIST=264164455a4e5fa12f3b28a43a6af69d; NOW=$(date +%s)
J=$(curl -s -m 20 -H "Authorization: Bearer $GH_TOKEN" "https://api.github.com/gists/$GIST" | python3 -c "import json,sys;print(json.load(sys.stdin)['files']['hb.json']['content'])" 2>/dev/null)
[ -z "$J" ] && { echo "gist unreadable - no alert"; exit 0; }
TS=$(echo "$J" | python3 -c "import json,sys;print(json.load(sys.stdin)['ts'])")
YT=$(echo "$J" | python3 -c "import json,sys;print(json.load(sys.stdin)['youtube'])")
AGE=$(( (NOW-TS)/60 ))
REASON=""
[ $AGE -ge 12 ] && REASON="the old Mini stopped checking in $AGE min ago (power or internet may be out, or it's stuck at the login screen)"
[ -z "$REASON" ] && [ "$YT" != live ] && [ "$YT" != unknown ] && REASON="YouTube says the stream is not live"
S=$(cat state.txt 2>/dev/null || echo "up 0 0"); read st since last <<<"$S"
tg(){ curl -s -m 20 -X POST "https://api.telegram.org/bot$TG_TOKEN/sendMessage" -d chat_id="$TG_CHAT" --data-urlencode "text=$1" >/dev/null; }
if [ -z "$REASON" ]; then
  [ "$st" = down ] && [ "$last" != 0 ] && tg "✅ HVR stream is back ON AIR (same link). Down about $(( (NOW-since)/60 )) min."
  echo "up 0 0" > state.txt; echo "OK age=${AGE}m yt=$YT"; exit 0; fi
[ "$st" = up ] && { since=$NOW; last=0; }
DOWN=$(( (NOW-since)/60 ))
# stale heartbeat already implies >=12 min, so alert on first sight; YouTube-not-live waits 5 min
if { [ $AGE -ge 12 ] || [ $DOWN -ge 5 ]; } && [ $(( NOW-last )) -ge 3600 ]; then
  tg "🔴 HVR stream problem: $REASON. Checked from outside your house. https://www.youtube.com/watch?v=X0cUEL6VuTw"; last=$NOW; fi
echo "down $since $last" > state.txt; echo "DOWN: $REASON"
