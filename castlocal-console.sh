#!/usr/bin/env bash
# castlocal — doble clic = alternar el servidor (iniciar / detener).
#
# - Si no está corriendo: lo inicia en segundo plano y muestra la dirección
#   en una ventanita.
# - Si ya está corriendo: pregunta si querés detenerlo.
# - Sin entorno gráfico (ssh, tty): modo consola clásico (Q para detener).
set -u
cd "$(dirname "$(readlink -f "$0")")"

LOG="$HOME/.cache/castlocal.log"
ENV_FILE="$HOME/.config/castlocal.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi
PORT="${CASTLOCAL_PORT:-8000}"

running() { pgrep -f "[c]astlocal\.app" >/dev/null; }

stop_server() {
    systemctl --user stop castlocal 2>/dev/null
    pkill -f "[c]astlocal\.app" 2>/dev/null
    sleep 1
}

have_gui() { [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] && command -v kdialog >/dev/null; }

server_url() {
    local ip
    ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    echo "http://${ip:-localhost}:$PORT"
}

gui_start() {
    stop_server
    mkdir -p "$(dirname "$LOG")"
    : >"$LOG"
    setsid nohup uv run python -m castlocal.app >>"$LOG" 2>&1 </dev/null &
    sleep 4
    if running; then
        kdialog --title "castlocal" --msgbox "Servidor corriendo.\n\nAbrí en el celu: $(server_url)\nLocal: http://127.0.0.1:$PORT\n\nPara detenerlo hacé doble clic de nuevo."
    else
        kdialog --title "castlocal" --error "No se pudo iniciar el servidor.\n\nDetalle en: $LOG"
    fi
}

gui_stop() {
    if kdialog --title "castlocal" --yesno "El servidor está corriendo (puerto $PORT).\n¿Querés detenerlo?"; then
        stop_server
        if running; then
            kdialog --title "castlocal" --sorry "No se pudo detener del todo.\nFijate en: $LOG"
        else
            kdialog --title "castlocal" --passivepopup "Servidor detenido." 4
        fi
    fi
}

console_mode() {
    echo "=============================="
    echo "  castlocal (modo consola)"
    echo "  Abrí en el celu: $(server_url)"
    echo "  Local: http://127.0.0.1:$PORT"
    echo "=============================="
    echo "Presioná Q para detener y cerrar."
    echo
    stop_server
    uv run python -m castlocal.app &
    SRV_PID=$!
    cleanup() {
        kill "$SRV_PID" 2>/dev/null
        wait "$SRV_PID" 2>/dev/null
        SRV_PID=""
    }
    trap cleanup EXIT INT TERM
    if [[ -t 0 ]]; then
        while IFS= read -rsn1 key; do
            [[ "$key" == [qQ] ]] && break
        done
        echo
        echo "Servidor detenido."
    else
        echo "Sin terminal: servidor en primer plano (Ctrl+C para detener)."
        wait "$SRV_PID"
    fi
}

if have_gui; then
    if running; then
        gui_stop
    else
        gui_start
    fi
else
    console_mode
fi
