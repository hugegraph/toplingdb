#!/bin/bash

export SANDCASTLE=1
export BUILD_PREFIX=../build-toplingdb/
export CXX=clang++
export CC=clang

ROCKSDB_VERSION=`build_tools/version.sh full`
TOPLING_CORE_DIR=sideplugin/topling-zip
COMPILER=`bash ${TOPLING_CORE_DIR}/get-compiler-name.sh`
WITH_BMI2=`bash ${TOPLING_CORE_DIR}/cpu_has_bmi2.sh`
UNAME_MachineSystem=`uname -m -s | sed 's:[ /]:-:g'`
BUILD_NAME=${UNAME_MachineSystem}-${COMPILER}-bmi2-${WITH_BMI2}
BUILD_ROOT=build/${BUILD_NAME}

dir=${BUILD_PREFIX}build/${BUILD_NAME}/dbg/v${ROCKSDB_VERSION}
dir_ut=${BUILD_PREFIX}build-ut/${BUILD_NAME}/dbg/v${ROCKSDB_VERSION}
DEBUG_LEVEL=2
function map() {
    if [[ $1 == *test*.o ]]; then
        echo $dir_ut/$1
    elif [[ $1 == *.o ]]; then
        echo $dir/$1
    else
        echo $1
    fi
}
targets=(`for i in $@;do map $i;done`)

make PREFIX=/opt UPDATE_REPO=0 -j`nproc` ${targets[@]}
