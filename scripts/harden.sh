#!/usr/bin/env bash
# Harden this project locally. LibreLane runs in Docker. Run
# scripts/harden-setup.sh once first. Run from the project top level.
# Output goes to ./runs/wokwi/. The last steps print the run stats and the
# cell summary.
#
#   scripts/harden.sh          full flow, same steps as the CI gds job
#   scripts/harden.sh --fast   skip Magic.DRC (about 30 of 33 minutes on the
#                              template design). Not a sign-off run: it writes
#                              no commit_id.json or pdk.json. CI signs off.
set -euo pipefail

HOME_DIR="${PROTOEMU_HARDEN_HOME:-$HOME/.local/share/protoemu-harden}"

fast=0
case "${1:-}" in
    "") ;;
    --fast) fast=1 ;;
    *) echo "usage: scripts/harden.sh [--fast]" >&2; exit 2 ;;
esac

if [ ! -f info.yaml ] || [ ! -d tt ] || [ ! -f "$HOME_DIR/env.sh" ]; then
    echo "harden: run from the project top level, after scripts/harden-setup.sh" >&2
    exit 2
fi
# shellcheck source=/dev/null
. "$HOME_DIR/env.sh"

python ./tt/tt_tool.py --create-user-config --ihp
if [ "$fast" -eq 1 ]; then
    # Mirror tt/project.py harden(): merge the config, clear old step
    # directories, then run the same LibreLane command plus --skip.
    python -c '
import json
cfg = json.load(open("src/config.json"))
cfg.update(json.load(open("src/user_config.json")))
cfg.pop("//", None)  # tt read_config drops the comment keys
json.dump(cfg, open("src/config_merged.json", "w"), indent=2)
'
    rm -rf runs/wokwi
    mkdir -p runs/wokwi
    python -m librelane --docker-no-tty --dockerized --pdk-root "$PDK_ROOT" \
        --pdk ihp-sg13cmos5l --manual-pdk --run-tag wokwi \
        --force-run-dir runs/wokwi --skip Magic.DRC src/config_merged.json
else
    python ./tt/tt_tool.py --harden --ihp
fi
python ./tt/tt_tool.py --print-stats --ihp
python ./tt/tt_tool.py --print-cell-summary --ihp
