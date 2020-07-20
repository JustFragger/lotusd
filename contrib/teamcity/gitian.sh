#!/usr/bin/env bash

export LC_ALL=C

set -euxo pipefail

: "${TOPLEVEL:=$(git rev-parse --show-toplevel)}"
: "${BUILD_DIR:=${TOPLEVEL}/build}"
: "${THREADS:=$(nproc || sysctl -n hw.ncpu)}"

COMMIT=$(git -C "${TOPLEVEL}" rev-parse HEAD)
export COMMIT
export USE_LXC=1
export GITIAN_HOST_IP=10.0.3.1
export LXC_BRIDGE=lxcbr0
export LXC_GUEST_IP=10.0.3.5

cd "${TOPLEVEL}/contrib/gitian-builder"

# Build the base image if it doesn't already exist
if [ ! -f "base-buster-amd64" ]; then
  ./bin/make-base-vm --lxc --arch amd64 --distro debian --suite buster
fi

if [[ "${OS_NAME}" == "osx" ]]; then
  OSX_SDK="MacOSX10.14.sdk.tar.gz"
  OSX_SDK_SHA256="2322086a96349db832abbcadea493b79db843553a2e604163238d99fa058a286"
  mkdir -p inputs
  pushd inputs
  if ! echo "${OSX_SDK_SHA256}  ${OSX_SDK}" | sha256sum -c; then
    rm -f "${OSX_SDK}"
    wget https://storage.googleapis.com/27cd7b2a42a430926cc621acdc3bda72a8ed2b0efc080e3/"${OSX_SDK}"
    echo "${OSX_SDK_SHA256}  ${OSX_SDK}" | sha256sum -c
  fi
  popd
fi

RESULT_DIR="${BUILD_DIR}/gitian-results"
OS_DIR="${RESULT_DIR}/${OS_NAME}"
mkdir -p "${OS_DIR}"

move_log() {
  mv var/install.log "${RESULT_DIR}/"
  mv var/build.log "${RESULT_DIR}/"
}
trap "move_log" ERR

./bin/gbuild -j${THREADS} -m3500 --commit bitcoin=${COMMIT} --url bitcoin="${TOPLEVEL}" "${TOPLEVEL}/contrib/gitian-descriptors/gitian-${OS_NAME}.yml"

move_log
mv result/*.yml "${OS_DIR}/"
mv build/out/* "${OS_DIR}/"
