#!/usr/bin/env bash
# castlocal-console.sh — levanta el servidor en esta consola.
# Presioná Q para detenerlo y cerrar.
set -u
cd "$(dirname "$(readlink -f "$0")")"

PORT="${CASTLOCAL_PORT:-8000}"
ENV_FILE="$HOME/.config/castlocal.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

# La consola manda: frenar servicio o restos viejos que usen el puerto.
systemctl --user stop castlocal 2>/dev/null
pkill -f "[c]astlocal\.app" 2>/dev/null
sleep 1

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "=============================="
echo "  castlocal"
echo "  Abrí en el celu: http://${IP:-?}:$PORT"
echo "  Local: http://127.0.0.1:$PORT"
echo "=============================="
echo "Presioná Q para detener y cerrar."
echo

uv run python -m castlocal.app &
SRV=$!
cleanup() {
    kill "$SRV" 2>/dev/null
    wait "$SRV" 2>/dev/null
}
trap cleanup EXIT INT TERM

while IFS= read -rsn1 key; do
    [[ "$key" == [qQ] ]] && break
done
echo
echo "Servidor detenido."
