#!/bin/bash
# makes recursive symbolic links to the claude skills folder
# can also run this piecewise to install individual skills
if [ -d "$1" ]; then
    rm -r ~/.claude/skills/"$1"
fi
mkdir -p ~/.claude/skills/"$1"
# cp -srf "${PWD}"/skills/"$1"/.[^.]* ~/.claude/skills/"$1"/ # SOURCE must resolve to an absolute path to work
cp -srf "${PWD}"/skills/"$1"/ ~/.claude/skills/ # SOURCE must resolve to an absolute path to work
