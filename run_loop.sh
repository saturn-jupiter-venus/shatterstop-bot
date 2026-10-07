#!/usr/bin/env bash
# ShatterStop self running loop. One GitHub job stays alive about 5.5 hours, posts a new
# product video roughly every 85 to 90 minutes between 8 AM and 7 PM Eastern, then starts
# the next job by itself. A backup schedule restarts the chain if it ever breaks.
# Needs env: GH_TOKEN, GITHUB_REPOSITORY, MAKE_WEBHOOK_URL.
set -u
GAP=5100                                   # seconds between posts (85 minutes)
END=$(( $(date +%s) + 5*3600 + 2400 ))     # stop after 5 hours 40 minutes and hand off
post_one() {
  rm -rf out; mkdir -p out
  K=$(gh release view videos --json body -q .body 2>/dev/null | grep -oE '^[0-9]+$' | head -1); K=${K:-17}   # post counter lives in the release notes
  POST_INDEX=$K python videobot.py || return 1
  for j in out/*.json; do
    [ -e "$j" ] || return 1
    name="$(date -u +%Y%m%d%H%M)_$(python -c "import json;print(json.load(open('$j'))['name'])")"
    cp "$(python -c "import json;print(json.load(open('$j'))['file'])")" "/tmp/$name"
    gh release upload videos "/tmp/$name" --clobber || return 1
    url="https://github.com/${GITHUB_REPOSITORY}/releases/download/videos/$name"
    python - "$j" "$url" > /tmp/payload.json <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8")); d["video_url"] = sys.argv[2]; d.pop("file", None)
print(json.dumps(d))
PY
    curl -sS --fail -X POST -H "Content-Type: application/json" --data @/tmp/payload.json "$MAKE_WEBHOOK_URL" || return 1; echo
  done
  gh release edit videos --notes "$((K+1))" >/dev/null || echo "counter update failed"
  gh release view videos --json assets -q '.assets | sort_by(.createdAt) | reverse | .[40:] | .[].name' | while read -r old; do gh release delete-asset videos "$old" -y; done
  return 0
}
[ -z "${MAKE_WEBHOOK_URL:-}" ] && { echo "No MAKE_WEBHOOK_URL set"; exit 1; }
gh release view videos >/dev/null 2>&1 || gh release create videos --title "Bot videos" --notes "Videos made by the ShatterStop bot"
while [ "$(date +%s)" -lt "$END" ]; do
  H=$(date -u +%H)
  if [ "$H" -ge 12 ] && [ "$H" -lt 23 ]; then          # 8 AM to 7 PM Eastern (daylight time)
    LAST=$(gh release view videos --json assets -q '[.assets[].createdAt] | max // empty' 2>/dev/null)
    if [ -n "$LAST" ]; then LASTS=$(date -u -d "$LAST" +%s); else LASTS=0; fi
    if [ $(( $(date +%s) - LASTS )) -ge "$GAP" ]; then
      echo "=== posting at $(date -u) ==="
      post_one || { echo "post failed, retry in 10 minutes"; sleep 600; continue; }
    fi
  fi
  sleep 300
done
echo "handing off to the next job"
gh workflow run post.yml --repo "$GITHUB_REPOSITORY" || echo "handoff failed, the backup schedule will restart it"
