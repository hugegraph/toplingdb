#!/usr/bin/bash

if [ -e sideplugin/topling-rocks-bak ]; then
    echo sideplugin/topling-rocks-bak exists >&2
    exit 1
fi
mv sideplugin/{topling-rocks,topling-rocks-bak}
mv sideplugin/cspp-memtable{,-bak}
mkdir sideplugin/cspp-memtable # create empty dir
make WITH_TOPLING_ROCKS=1 $@
mv sideplugin/{topling-rocks-bak,topling-rocks}
mv -fT sideplugin/cspp-memtable{-bak,}
