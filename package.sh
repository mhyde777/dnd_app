#!/bin/bash
#
[ -e package ] && rm -r package
mkdir -p package/opt
mkdir -p package/usr/share/applications
mkdir -p package/usr/share/icons/hicolor/scalable/apps 

cp -r dist/combat_tracker package/opt/combat_tracker
cp images/d20_icon.png package/usr/share/icons/hicolor/scalable/apps/combat_tracker.png
cp combat_tracker.desktop package/usr/share/applications

find package/opt/combat_tracker -type f -exec chmod 644 -- {} +
find package/opt/combat_tracker -type d -exec chmod 755 -- {} +
find package/usr/share -type f -exec chmod 644 -- {} +
chmod +x package/opt/combat_tracker/combat_tracker
