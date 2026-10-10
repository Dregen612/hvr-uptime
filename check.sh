#!/bin/bash
# Off-site check: is the HVR live stream on air? Alerts Adam on Telegram if it's been down 5+ min.
VID=X0cUEL6VuTw; NOW=$(date +%s)
probe(){ curl -s -m 25 -A 'Mozilla/5.0' "https://www.youtube.com/watch?v=$VID" | grep -o '"isLiveNow":[a-z]*' | head -1; }
R=$(probe); [ -z "$R" ] && { sleep 20; R=$(probe); }
[ -z "$R" ] && { echo "unknown (page unreadable) - no alert"; exit 0; }
S=$(cat state.txt 2>/dev/null || echo "up 0 0"); read st since last <<<"$S"
tg(){ curl -s -m 20 -X POST "https://api.telegram.org/bot$TG_TOKEN/sendMessage" -d chat_id="$TG_CHAT" --data-urlencode "text=$1" >/dev/null; }
if [ "$R" = '"isLiveNow":true' ]; then
  [ "$st" = down ] && [ "$last" != 0 ] && tg "✅ HVR stream is back ON AIR (same link). Down about $(( (NOW-since)/60 )) min."
  echo "up 0 0" > state.txt; echo LIVE; exit 0; fi
[ "$st" = up ] && { since=$NOW; last=0; }
DOWN=$(( (NOW-since)/60 ))
if [ $DOWN -ge 5 ] && [ $(( NOW-last )) -ge 3600 ]; then
  tg "🔴 HVR stream has been OFF AIR for about $DOWN min (checked from outside your house). If the power or internet went out, the old Mini may be stuck at its login screen. Link: https://www.youtube.com/watch?v=$VID"; last=$NOW; fi
echo "down $since $last" > state.txt; echo "DOWN $DOWN min"
