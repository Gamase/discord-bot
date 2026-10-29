#!/data/data/com.termux/files/usr/bin/bash
set -uo pipefail

export PATH="/data/data/com.termux/files/usr/bin:/system/bin:$PATH"

DIR="/data/data/com.termux/files/home/discord-bot"
LOG="$DIR/bot.log"
PY="$DIR/venv/bin/python"
HEARTBEAT="$DIR/heartbeat"
TIMEOUT="${WATCHDOG_TIMEOUT:-120}"

cd "$DIR" || exit 1

if [ -f "$DIR/.env" ]; then
    set -a
    . "$DIR/.env"
    set +a
fi

AVISO="${AVISO_CANAL_ID:-${CANAL_ID:-0}}"

avisar() {
    [ -n "${DISCORD_TOKEN:-}" ] || return 0
    [ "$AVISO" != "0" ] || return 0

    ahora_aviso=$(date +%s)
    ultimo=$(cat "$DIR/.aviso_last" 2>/dev/null || echo 0)
    if [ $((ahora_aviso - ultimo)) -lt 300 ]; then
        return 0
    fi
    echo "$ahora_aviso" > "$DIR/.aviso_last"

    curl -s -o /dev/null --max-time 10 -X POST \
        -H "Authorization: Bot $DISCORD_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"content\": \"$1\"}" \
        "https://discord.com/api/v10/channels/$AVISO/messages" || true
}

if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 5242880 ]; then
    mv -f "$LOG" "$LOG.1"
fi

while true; do
    printf -v ahora '%(%Y-%m-%d %H:%M:%S)T' -1
    echo "[$ahora] iniciando bot" >> "$LOG"
    date +%s > "$HEARTBEAT"

    "$PY" -u main.py >> "$LOG" 2>&1 &
    pid=$!

    (
        while kill -0 "$pid" 2>/dev/null; do
            sleep 15
            ahora=$(date +%s)
            latido=$(stat -c %Y "$HEARTBEAT" 2>/dev/null || echo 0)
            edad=$((ahora - latido))
            if [ "$edad" -gt "$TIMEOUT" ]; then
                printf -v ts '%(%Y-%m-%d %H:%M:%S)T' -1
                echo "[$ts] watchdog: sin heartbeat hace ${edad}s; reiniciando (pid $pid)" >> "$LOG"
                avisar "⚠️ El bot se colgó (sin heartbeat hace ${edad}s). Reiniciando..."
                kill -TERM "$pid" 2>/dev/null
                sleep 5
                kill -KILL "$pid" 2>/dev/null
                exit 0
            fi
        done
    ) &
    wd=$!

    wait "$pid"
    codigo=$?

    kill "$wd" 2>/dev/null
    wait "$wd" 2>/dev/null

    printf -v ahora '%(%Y-%m-%d %H:%M:%S)T' -1
    echo "[$ahora] bot terminó (código $codigo); reinicio en 10 s" >> "$LOG"

    if [ "$codigo" -ne 0 ] && [ "$codigo" -ne 143 ] && [ "$codigo" -ne 137 ]; then
        avisar "⚠️ El bot se cayó (código $codigo). Reiniciando en 10 s..."
    fi

    sleep 10
done
