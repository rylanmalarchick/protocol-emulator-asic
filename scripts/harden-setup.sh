#!/usr/bin/env bash
# Set up local hardening (RTL to GDS) for this project. Versions match
# TinyTapeout/tt-gds-action@ihp-cmos5l, the action that the CI gds job runs.
#
#   scripts/harden-setup.sh
#
# Run it from the project top level. It installs into $PROTOEMU_HARDEN_HOME
# (default ~/.local/share/protoemu-harden):
#
#   pdk/ihp-sg13cmos5l-2bbec75/   IHP-Open-PDK at the pinned commit (shallow)
#   venv/                         Python 3.11, tt-support-tools requirements,
#                                 librelane
#   env.sh                        variables that scripts/harden.sh reads
#
# It also clones tt-support-tools into ./tt (ignored by git) and pulls the
# LibreLane Docker image. Run it again to update ./tt to the branch head.
#
# Needs: git, Docker usable without sudo, and uv or python3.11.
set -euo pipefail

HOME_DIR="${PROTOEMU_HARDEN_HOME:-$HOME/.local/share/protoemu-harden}"

# Pins from TinyTapeout/tt-gds-action@ihp-cmos5l (action.yml and
# install_sg13cmos5l.sh). Update all four together.
TT_TOOLS_REPO="https://github.com/TinyTapeout/tt-support-tools"
TT_TOOLS_REF="ihp-sg13cmos5l"
LIBRELANE_VERSION="3.1.0.dev3"
IHP_PDK_REPO="https://github.com/IHP-GmbH/IHP-Open-PDK.git"
IHP_PDK_REV="2bbec755dc67ca3db0261c3d6163e15735d66710"

PDK_ROOT="$HOME_DIR/pdk/ihp-sg13cmos5l-${IHP_PDK_REV:0:7}"
VENV="$HOME_DIR/venv"

die() { echo "harden-setup: $*" >&2; exit 1; }

[ -f info.yaml ] || die "run from the project top level (no info.yaml here)"
command -v git >/dev/null || die "git not found"
command -v docker >/dev/null || die "docker not found"
docker info >/dev/null 2>&1 || die "docker does not run for this user (daemon down, or user not in the docker group)"

mkdir -p "$HOME_DIR"

echo "== tt-support-tools ($TT_TOOLS_REF) -> ./tt"
if [ -d tt/.git ]; then
    git -C tt fetch -q origin "$TT_TOOLS_REF"
    git -C tt checkout -q -B "$TT_TOOLS_REF" FETCH_HEAD
else
    git clone -q -b "$TT_TOOLS_REF" "$TT_TOOLS_REPO" tt
fi
git -C tt log --oneline -1

echo "== IHP-Open-PDK $IHP_PDK_REV -> $PDK_ROOT"
if [ "$(cat "$PDK_ROOT/ihp-sg13cmos5l/SOURCES" 2>/dev/null)" = "IHP-Open-PDK $IHP_PDK_REV" ]; then
    echo "present"
else
    rm -rf "$PDK_ROOT"
    mkdir -p "$PDK_ROOT"
    git -C "$PDK_ROOT" init -q
    git -C "$PDK_ROOT" fetch -q --depth 1 "$IHP_PDK_REPO" "$IHP_PDK_REV"
    git -C "$PDK_ROOT" checkout -q FETCH_HEAD
    echo "IHP-Open-PDK $IHP_PDK_REV" > "$PDK_ROOT/ihp-sg13cmos5l/SOURCES"
fi

echo "== Python 3.11 venv -> $VENV"
if [ ! -x "$VENV/bin/python" ]; then
    if command -v uv >/dev/null; then
        uv venv -q --python 3.11 "$VENV"
    elif command -v python3.11 >/dev/null; then
        python3.11 -m venv "$VENV"
    else
        die "need uv or python3.11 to make the venv"
    fi
fi
"$VENV/bin/python" --version | grep -q '^Python 3\.11\.' || die "$VENV is not Python 3.11. Delete it and run again."
if command -v uv >/dev/null; then
    uv pip install -q --python "$VENV/bin/python" -r tt/requirements.txt "librelane==$LIBRELANE_VERSION"
else
    "$VENV/bin/python" -m pip install -q --upgrade pip
    "$VENV/bin/python" -m pip install -q -r tt/requirements.txt "librelane==$LIBRELANE_VERSION"
fi

echo "== LibreLane Docker image $LIBRELANE_VERSION"
docker pull -q "ghcr.io/librelane/librelane:$LIBRELANE_VERSION"

cat > "$HOME_DIR/env.sh" <<EOF
# Written by scripts/harden-setup.sh. Read by scripts/harden.sh.
export PDK_ROOT="$PDK_ROOT"
export PDK=ihp-sg13cmos5l
export LIBRELANE_TAG="$LIBRELANE_VERSION"
export PATH="$VENV/bin:\$PATH"
EOF

echo "== done. Run: scripts/harden.sh --fast"
